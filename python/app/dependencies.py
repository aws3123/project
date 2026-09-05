"""依赖注入与组装模块 —— FastAPI 应用的"装配车间"。

什么是依赖注入？
  想象你要组装一台电脑：CPU、内存、硬盘、显卡各自独立，
  但最终需要有人把它们插到主板上连起来。
  这个模块就是"装配工"：
  - 创建数据库连接（Repository 层）
  - 创建业务服务（Service 层）
  - 创建 LLM 客户端
  - 构建审查流水线（Graph 层）
  然后把它们组装在一起，供路由层（Router）直接使用。

核心设计模式：
  - 单例模式（Singleton）：如 LLM 客户端、仓库实例，全局只创建一次
  - 懒加载（Lazy Loading）：第一次使用时才创建，避免启动时浪费时间
  - 线程安全：用 RLock（可重入锁）确保多线程环境下不会创建多个实例
"""

from functools import lru_cache
from threading import RLock

from fastapi import Request

from config.settings import AppSettings

# select_agents：根据代码变更内容动态选择要执行哪些 Agent
from graph.agent_selector import select_agents

# GraphBuilder：建造者模式，一步步构建审查流水线
from graph.builder import GraphBuilder
from graph.business_risk_runner import BusinessRiskRunner
from graph.circuit_breaker import CircuitBreaker

# 导入所有节点函数（每个节点就是一个普通的 Python 函数）
from graph.nodes import (
    analyze_diff,
    analyze_impact,
    analyze_performance,
    assess_business_risk,
    audit_security,
    business_risk_rag,
    check_invariants,
    classify_changes,
    deep_read_methods,
    extract_business_invariants,
    run_rag,
    run_rule_checks,
    scan_semantic_hotspots,
    score_risks,
    summarize,
    trace_data_flow,
    verify_business_risks,
)
from graph.runner import GraphRunner
from llm.client import LLMClient
from repositories.log_repository import InMemoryLogRepository
from repositories.log_repository_sql import SQLLogRepository
from repositories.result_repository import InMemoryResultRepository
from repositories.result_repository_sql import SQLResultRepository
from repositories.task_repository import InMemoryTaskRepository
from repositories.task_repository_sql import SQLTaskRepository
from schemas.api.result import (
    BusinessRiskReadinessComponent,
    BusinessRiskSourceReadinessStatus,
)
from services.ai_service import AIService
from services.business_risk_source_service import BusinessRiskSourceService
from services.business_risk_worker_state import BusinessRiskWorkerState
from services.checkpoint_service import CheckpointService
from services.log_service import LogService
from services.memory_service import MemoryService
from services.result_service import ResultService
from services.task_service import TaskService
from telemetry.hooks import (
    CompositeTelemetryHook,
    LoggingTelemetryHook,
    NoOpTelemetry,
    TelemetryHook,
)
from telemetry.prometheus_hook import PrometheusTelemetryHook
from tools.registry import ToolRegistry, build_default_registry

# ---------------------------------------------------------------------------
# 配置（Settings）
# ---------------------------------------------------------------------------


@lru_cache  # lru_cache：缓存函数返回值，第二次调用直接返回缓存（全局单例效果）
def get_settings() -> AppSettings:
    """获取全局唯一的应用配置实例。"""
    return AppSettings()


# ---------------------------------------------------------------------------
# 仓库单例（Repository Singletons）—— 懒加载 + 线程安全
# ---------------------------------------------------------------------------

# RLock：可重入锁（同一线程可以多次获取同一把锁而不会死锁）
_repo_lock = RLock()
# 三个仓库实例（初始为 None，第一次使用时创建）
_task_repo: InMemoryTaskRepository | SQLTaskRepository | None = None
_result_repo: InMemoryResultRepository | SQLResultRepository | None = None
_log_repo: InMemoryLogRepository | SQLLogRepository | None = None


def _make_repo(cls_sql, cls_mem, backend: str):
    """根据持久化后端类型创建仓库实例。

    参数：
        cls_sql: SQL 仓库类
        cls_mem: 内存仓库类
        backend: 后端类型（"sql" 或 "memory"）
    返回：
        对应类型的仓库实例
    """
    return cls_sql() if backend == "sql" else cls_mem()


def _get_task_repo() -> InMemoryTaskRepository | SQLTaskRepository:
    """获取任务仓库单例（线程安全的懒加载）。"""
    global _task_repo
    with _repo_lock:  # 加锁，确保同一时刻只有一个线程在创建实例
        if _task_repo is None:
            _task_repo = _make_repo(
                SQLTaskRepository,
                InMemoryTaskRepository,
                get_settings().persistence_backend,
            )
        return _task_repo


def _get_result_repo() -> InMemoryResultRepository | SQLResultRepository:
    """获取结果仓库单例。"""
    global _result_repo
    with _repo_lock:
        if _result_repo is None:
            _result_repo = _make_repo(
                SQLResultRepository,
                InMemoryResultRepository,
                get_settings().persistence_backend,
            )
        return _result_repo


def _get_log_repo() -> InMemoryLogRepository | SQLLogRepository:
    """获取日志仓库单例。"""
    global _log_repo
    with _repo_lock:
        if _log_repo is None:
            _log_repo = _make_repo(
                SQLLogRepository,
                InMemoryLogRepository,
                get_settings().persistence_backend,
            )
        return _log_repo


# ---------------------------------------------------------------------------
# 服务工厂（Service Factories）
# ---------------------------------------------------------------------------


def get_task_service() -> TaskService:
    """创建任务服务（封装任务仓库的业务逻辑）。"""
    return TaskService(_get_task_repo())


def get_result_service() -> ResultService:
    """创建结果服务（封装结果仓库的业务逻辑）。"""
    return ResultService(_get_result_repo())


def _create_log_service(telemetry: TelemetryHook | None = None) -> LogService:
    """创建日志服务。"""
    return LogService(_get_log_repo(), telemetry=telemetry or NoOpTelemetry())


def get_log_service() -> LogService:
    """获取日志服务实例。"""
    return _create_log_service()


# ---------------------------------------------------------------------------
# LLM 客户端单例
# ---------------------------------------------------------------------------

_llm_client: LLMClient | None = None
_llm_lock = RLock()


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例（线程安全的懒加载）。"""
    global _llm_client
    with _llm_lock:
        if _llm_client is None:
            _llm_client = LLMClient()
        return _llm_client


# ---------------------------------------------------------------------------
# 审查流水线构建（Graph Pipeline Builders）
# ---------------------------------------------------------------------------


def _build_graph_runner(
    task_service: TaskService,
    log_service: LogService,
    telemetry: TelemetryHook | None = None,
    registry: ToolRegistry | None = None,
    llm_client: LLMClient | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    checkpoint_service: CheckpointService | None = None,
) -> GraphRunner:
    """构建主审查流水线的 GraphRunner。

    流水线结构（按阶段顺序）：
      阶段1（串行）：diff 分析 → 变更分类 → 影响范围分析 → RAG 检索
      阶段2（并行）：规则检查 | 安全审计 | 性能分析（三 Agent 并行）
      阶段3（串行）：风险评分
      阶段4（串行）：报告生成

    为什么 RAG 前置为串行节点？
      RAG 检索结果（历史事故、相似案例）是安全审计和性能分析的
      共享上下文，放在并行组内会导致其他 Agent 拿不到 RAG 结果。
      前置为串行节点后，三个并行 Agent 都能读取 rag_context。

    参数：
        task_service: 任务服务
        log_service: 日志服务
        telemetry: 遥测钩子
        registry: 工具注册表
        llm_client: LLM 客户端
        circuit_breaker: 熔断器
        checkpoint_service: 检查点服务
    返回：
        配置好的 GraphRunner 实例
    """
    registry = registry or build_default_registry()
    builder = GraphBuilder(
        registry=registry,
        log_service=log_service,
        telemetry=telemetry or NoOpTelemetry(),
        task_service=task_service,
        llm_client=llm_client,
        circuit_breaker=circuit_breaker or CircuitBreaker(),
        agent_selector=select_agents,  # 动态 Agent 选择器
        checkpoint_service=checkpoint_service,
    )
    # 串行节点
    builder.add_node("diff", analyze_diff)
    builder.add_node("classifier", classify_changes)
    builder.add_node("impact", analyze_impact)
    builder.add_node(
        "rag", run_rag
    )  # RAG 前置：检索历史事故作为下游并行 Agent 的共享上下文
    # 并行节点组（三个 Agent 同时执行）
    builder.add_parallel_group(
        [
            ("rules", run_rule_checks),
            ("security", audit_security),
            ("performance", analyze_performance),
        ]
    )
    # 串行节点
    builder.add_node("scoring", score_risks)
    builder.add_node("report", summarize)
    return builder.build()


def _build_business_risk_runner(
    task_service: TaskService | None,
    log_service: LogService,
    telemetry: TelemetryHook | None = None,
    registry: ToolRegistry | None = None,
    llm_client: LLMClient | None = None,
    circuit_breaker: CircuitBreaker | None = None,
) -> GraphRunner:
    """构建业务风险分析流水线的 GraphRunner。

    流水线结构：
      阶段1（串行）：提取业务不变量 → 追踪数据流
      阶段2（并行）：检查不变量 | 深度阅读方法 | 语义热点扫描
      阶段3（串行）：评估业务风险 → RAG 检索 → 验证业务风险
    """
    registry = registry or build_default_registry()
    builder = GraphBuilder(
        registry=registry,
        log_service=log_service,
        telemetry=telemetry or NoOpTelemetry(),
        task_service=task_service,
        llm_client=llm_client,
        circuit_breaker=circuit_breaker or CircuitBreaker(),
    )
    builder.add_node("extract_business_invariants", extract_business_invariants)
    builder.add_node("trace_data_flow", trace_data_flow)
    builder.add_parallel_group(
        [
            ("check_invariants", check_invariants),
            ("deep_read_methods", deep_read_methods),
            ("semantic_hotspot_scan", scan_semantic_hotspots),
        ]
    )
    builder.add_node("assess_business_risk", assess_business_risk)
    builder.add_node("business_risk_rag", business_risk_rag)
    builder.add_node("verify_business_risks", verify_business_risks)
    return builder.build()


# ---------------------------------------------------------------------------
# 遥测（Telemetry）
# ---------------------------------------------------------------------------


def _resolve_telemetry(settings: AppSettings) -> TelemetryHook:
    """根据配置选择遥测实现。

    "noop"       = 不做任何遥测（开发/测试用）
    "prometheus" = 日志 + Prometheus 指标双写（扇出到两个钩子）
    其他         = 使用日志遥测（将遥测数据写入日志）
    """
    if settings.telemetry_backend == "noop":
        return NoOpTelemetry()
    if settings.telemetry_backend == "prometheus":
        return CompositeTelemetryHook(
            hooks=[LoggingTelemetryHook(), PrometheusTelemetryHook()]
        )
    return LoggingTelemetryHook()


# ---------------------------------------------------------------------------
# 顶层服务访问器（Top-level Service Accessors）
# ---------------------------------------------------------------------------


def get_ai_service() -> AIService:
    """组装并返回 AI 审查服务（主入口）。

    这个方法将所有依赖组装在一起：
    配置 → 仓库 → 服务 → 流水线 → AI 服务
    """
    settings = get_settings()
    task_service = get_task_service()
    telemetry = _resolve_telemetry(settings)
    log_service = _create_log_service(telemetry=telemetry)
    llm_client = get_llm_client()
    checkpoint_service = CheckpointService(settings)
    runner = _build_graph_runner(
        task_service=task_service,
        log_service=log_service,
        telemetry=telemetry,
        llm_client=llm_client,
        checkpoint_service=checkpoint_service,
    )
    # AIService 只依赖 runner.run 方法（依赖注入 / 鸭子类型）
    return AIService(runner.run)


_worker_state: BusinessRiskWorkerState | None = None
_worker_state_lock = RLock()


def get_business_risk_worker_state() -> BusinessRiskWorkerState:
    """获取业务风险工作器状态单例。"""
    global _worker_state
    with _worker_state_lock:
        if _worker_state is None:
            _worker_state = BusinessRiskWorkerState()
        return _worker_state


def get_memory_service() -> MemoryService:
    """获取会话记忆服务。"""
    return MemoryService(get_settings())


def get_business_risk_service() -> BusinessRiskSourceService:
    """组装并返回业务风险分析服务。"""
    settings = get_settings()
    telemetry = _resolve_telemetry(settings)
    log_service = _create_log_service(telemetry=telemetry)
    llm_client = get_llm_client()
    runner = _build_business_risk_runner(
        task_service=None,
        log_service=log_service,
        telemetry=telemetry,
        llm_client=llm_client,
    )
    return BusinessRiskSourceService(
        BusinessRiskRunner(runner), get_business_risk_worker_state()
    )


# ---------------------------------------------------------------------------
# 健康检查（Health Check）
# ---------------------------------------------------------------------------


def get_business_risk_source_readiness() -> BusinessRiskSourceReadinessStatus:
    """检查业务风险分析服务的就绪状态。

    检查项：
      - route：路由是否注册
      - config：LLM API Key 是否配置
      - persistence：持久化后端是否需要（无状态工作器不需要）
      - llm：LLM 客户端是否可用
    只有所有组件都是 "UP" 时，整体才是 "UP"。
    """
    settings = get_settings()

    route = BusinessRiskReadinessComponent(
        status="UP", detail="business-risk-source readiness route registered"
    )

    llm_key = settings.llm_api_key.strip()
    if llm_key:
        config = BusinessRiskReadinessComponent(
            status="UP", detail="llm_api_key configured"
        )
        llm = BusinessRiskReadinessComponent(
            status="UP", detail="llm_api_key configured"
        )
    else:
        config = BusinessRiskReadinessComponent(
            status="DOWN", detail="llm_api_key is required"
        )
        llm = BusinessRiskReadinessComponent(
            status="DOWN", detail="llm_api_key is required"
        )

    persistence = BusinessRiskReadinessComponent(
        status="UP", detail="stateless worker does not require task persistence"
    )

    components = (route, config, persistence, llm)
    overall = (
        "UP" if all(component.status == "UP" for component in components) else "DOWN"
    )

    return BusinessRiskSourceReadinessStatus(
        overall=overall,
        route=route,
        config=config,
        persistence=persistence,
        llm=llm,
    )


def get_trace_id(request: Request) -> str:
    """从请求对象中提取追踪 ID（用于链路追踪）。"""
    return getattr(request.state, "trace_id", "unknown")
