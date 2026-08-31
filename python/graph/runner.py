"""
图运行器模块 —— 流水线的"发动机"
================================

本模块实现了 GraphRunner，负责按顺序/并行执行流水线中的各个节点。

核心职责：
1. 按阶段（Phase）依次执行节点函数，每个节点读取并更新共享状态（GraphState）
2. 单节点阶段 → 顺序执行；多节点阶段 → 多线程并行执行
3. 支持断点续传（Checkpoint）：任务中断后可以从上次完成的位置恢复
4. 支持熔断器（CircuitBreaker）：某个 Agent 连续失败时自动跳过，避免雪崩
5. 支持动态 Agent 选择：根据代码变更特征决定跑哪些 Agent（节省 Token）
6. 最终将流水线状态转换为前端可消费的 ReviewResult

类比：
  GraphRunner 就像一条"自动化流水线"：
  - 每个阶段是一个"工位"
  - 单人工位 = 一个专家独立完成
  - 多人协作工位 = 几个专家同时干活，干完汇总
  - 断点续传 = 流水线停电后，来电了从断掉的地方继续，不用从头来
"""
from __future__ import annotations

import logging
import threading  # 线程锁：并行执行时保护日志写入的线程安全
from collections.abc import Callable
from concurrent.futures import (
    Future,             # 异步任务的"取票凭证"，用来获取线程执行结果
    ThreadPoolExecutor, # 线程池：同时启动多个线程干活
    TimeoutError as FutureTimeoutError,
)
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter  # 高精度计时器，用于测量节点执行耗时
from typing import TYPE_CHECKING, Any

from schemas.enums import RAGStatus, TaskStatus, Tier
from schemas.log import NodeLog
from schemas.request import ReviewRequest
from schemas.result import Recommendation, ReviewResult, RiskBreakdown

from app.utils import safe_detail
from graph.circuit_breaker import CircuitBreaker
from graph.state import GraphState, NodeContext
from services.checkpoint_service import CheckpointService
from services.image_service import ImageService
from services.image_url_replacer import replace_markdown_image_urls
from services.log_service import LogService
from services.task_service import TaskService
from telemetry.hooks import TelemetryHook

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# 并行 Agent 执行超时时间（秒）
# 为什么是 45 秒？经验值：单个 Agent（安全/性能分析）正常执行约 10-30 秒，
# 45 秒留了足够余量，超过这个时间大概率是 LLM 推理卡住了
AGENT_EXECUTION_TIMEOUT_SECONDS = 45
# 评分缩放因子：将 0~1 范围的风险分数转换为 0~100 的百分制
SCORE_SCALE_FACTOR = 100


# 并行 Agent 结果合并策略
# 当多个 Agent 同时运行并写回结果时，需要决定如何处理"冲突"：
# - "extend"   → 追加合并（如 tool_logs：每个 Agent 的日志都要保留，不能覆盖）
# - "replace"  → 后者覆盖前者（如 security_findings：安全审计的结果直接替换）
# - "overwrite"→ 默认策略，直接覆盖（同 replace）
MERGE_STRATEGY: dict[str, str] = {
    "tool_logs": "extend",           # 日志追加：多个 Agent 的日志合并在一起
    "rule_findings": "replace",      # 规则发现：直接替换
    "rag_context": "replace",        # RAG 上下文：直接替换
    "security_findings": "replace",  # 安全发现：直接替换
    "performance_findings": "replace",  # 性能发现：直接替换
    "semantic_findings": "replace",  # 语义发现：直接替换
    "rag_analysis": "overwrite",     # RAG 分析文本：直接覆盖
    "rag_status": "overwrite",       # RAG 状态：直接覆盖
}


@dataclass(slots=True)
class RunnerConfig:
    """运行器配置 —— GraphRunner 启动时需要的全部依赖。

    类比：就像启动汽车需要的"钥匙+导航+空调设置"——所有运行参数都在这里。
    """
    registry: ToolRegistry                  # 工具注册表：节点通过它调用各种检查工具
    log_service: LogService                 # 日志服务：记录每个节点的执行日志
    telemetry: TelemetryHook                # 遥测钩子：采集执行耗时等监控指标
    task_service: TaskService | None = None        # 任务服务：更新任务状态（可选）
    llm_client: Any | None = None                  # LLM 客户端：调用大模型（可选）
    circuit_breaker: CircuitBreaker | None = None  # 熔断器：Agent 连续失败时自动跳过
    agent_selector: (
        Callable[
            [GraphState],
            list[tuple[str, Callable[[GraphState, NodeContext], GraphState]]],
        ]
        | None
    ) = None                                       # Agent 选择器：动态决定跑哪些 Agent
    checkpoint_service: CheckpointService | None = None  # 断点续传服务（可选）


class GraphRunner:
    """流水线运行器 —— 按阶段执行节点，支持顺序/并行/断点续传。

    这是整个审查系统的"引擎"，负责：
    1. 初始化共享状态（GraphState）
    2. 按阶段顺序执行：单节点→直接跑，多节点→线程池并行跑
    3. 合并并行节点的结果
    4. 将最终状态转换为前端可消费的 ReviewResult
    """
    def __init__(
        self,
        phases: list[list[tuple[str, Callable[[GraphState, NodeContext], GraphState]]]],
        config: RunnerConfig,
    ) -> None:
        self._phases = phases   # 阶段列表：每个阶段是一个节点列表
        self._config = config   # 运行配置

    def count_nodes(self) -> int:
        """统计流水线中所有节点的总数（用于日志/监控）。"""
        return sum(len(p) for p in self._phases)

    def run(self, request: ReviewRequest) -> ReviewResult:
        """执行完整流水线：从请求开始 → 跑完所有节点 → 返回审查结果。

        这是外部调用的主入口，内部流程：
        1. 将请求转换为初始状态（GraphState）
        2. 调用 run_state() 执行所有节点
        3. 调用 _build_result() 将最终状态转换为 ReviewResult
        """
        state: GraphState = {
            "task_id": str(request.taskId),
            "request": request.model_dump(by_alias=True),
        }
        state = self.run_state(state)
        return self._build_result(request, state)

    def run_state(self, state: GraphState) -> GraphState:
        """执行流水线的核心方法 —— 按阶段依次执行所有节点。

        执行流程：
        1. 创建节点上下文（NodeContext）—— 每个节点的"工具箱"
        2. 尝试从断点恢复（如果有 CheckpointService）
        3. 遍历每个阶段：
           - 单节点阶段 → 直接执行，记录日志，保存断点
           - 多节点阶段 → 线程池并行执行，合并结果，保存断点
        4. 全部完成后清理断点数据

        为什么需要断点续传？
        - 流水线执行可能需要 10-30 秒（多次 LLM 调用）
        - 如果中途崩溃（进程被杀、OOM），下次重试不用从头跑
        - 类比：考试做到一半断电了，来电后从上次做到的题继续，不用重做
        """
        task_id = str(state.get("task_id") or state.get("run_id") or "unknown")
        # 创建节点上下文 —— 所有节点共享的"工具箱"
        context = NodeContext(
            task_id=task_id,
            registry=self._config.registry,
            task_service=self._config.task_service,
            telemetry=self._config.telemetry,
            llm_client=self._config.llm_client,
        )
        ckpt_svc = self._config.checkpoint_service

        # --- 尝试从断点恢复 ---
        # completed 记录已完成的阶段索引，跳过这些阶段不重复执行
        completed: set[int] = set()
        if ckpt_svc:
            ckpt = ckpt_svc.load(task_id)  # 从持久化存储加载断点
            if ckpt:
                state = ckpt.get("state", state)  # 恢复上次中断时的状态
                completed = set(ckpt.get("completed_phases", []))
                logger.info(
                    "Resuming task %s from checkpoint, completed_phases=%s",
                    task_id, sorted(completed),
                )

        # --- 主循环：按阶段依次执行 ---
        for phase_idx, phase in enumerate(self._phases):
            if len(phase) == 0:
                continue
            if phase_idx in completed:
                continue  # 跳过已完成的阶段（断点恢复场景）

            if len(phase) == 1:
                # ===== 单节点阶段：顺序执行 =====
                name, node = phase[0]
                start = perf_counter()  # 记录开始时间
                input_snapshot = dict(state)  # 快照输入状态（用于日志记录）
                try:
                    state = node(state, context)  # 执行节点函数
                    self._append_log(
                        name, context.task_id,
                        input_snapshot, dict(state),
                        start, "SUCCEEDED",
                    )
                    completed.add(phase_idx)
                    if ckpt_svc:
                        ckpt_svc.save(task_id, {
                            "state": dict(state),
                            "completed_phases": sorted(completed),
                        })
                except Exception as exc:
                    self._append_log(
                        name, context.task_id,
                        input_snapshot, {"error": str(exc)},
                        start, "FAILED",
                    )
                    raise  # 顺序节点失败 → 整个流水线中止
            else:
                # ===== 多节点阶段：并行执行 =====
                selected = self._select_agents_for_phase(phase, state)

                # --- 并行阶段 + 断点续传支持 ---
                saved_deltas: dict[str, dict] = {}  # 已完成的 Agent 的结果增量
                phase_input: GraphState = dict(state)  # 并行阶段的输入快照

                if ckpt_svc and ckpt:
                    # 从断点恢复已完成的 Agent 结果
                    saved_deltas = ckpt.get("parallel_results", {}) or {}
                    pi = ckpt.get("phase_input")
                    if pi:
                        phase_input = pi
                    # 从 phase_input + 已保存的增量 重建状态
                    state = self._merge_results(dict(phase_input), saved_deltas)

                # 过滤掉已完成的 Agent（断点恢复场景）
                remaining = [
                    (n, fn) for n, fn in selected if n not in saved_deltas
                ]

                if not remaining:
                    # 所有 Agent 都已完成（从断点恢复）
                    state = self._merge_results(dict(phase_input), saved_deltas)
                    completed.add(phase_idx)
                    if ckpt_svc:
                        ckpt_svc.save(task_id, {
                            "state": dict(state),
                            "completed_phases": sorted(completed),
                        })
                else:
                    # 执行前保存 phase_input，用于断点恢复时重建状态
                    if ckpt_svc:
                        ckpt_svc.save(task_id, {
                            "state": dict(state),
                            "completed_phases": sorted(completed),
                            "phase_input": dict(phase_input),
                            "parallel_results": dict(saved_deltas),
                        })

                    # 每个 Agent 完成后的回调 —— 增量保存结果
                    def _on_agent_done(agent_name: str, agent_output: dict) -> None:
                        if not ckpt_svc:
                            return
                        # 计算增量：只保存 Agent 新增/修改的字段
                        delta = {
                            k: v for k, v in agent_output.items()
                            if k not in phase_input or phase_input[k] != v
                        }
                        saved_deltas[agent_name] = delta
                        ckpt_svc.save(task_id, {
                            "state": dict(state),
                            "completed_phases": sorted(completed),
                            "phase_input": dict(phase_input),
                            "parallel_results": dict(saved_deltas),
                        })

                    merged_state = self._run_parallel(
                        remaining, state, context,
                        on_agent_done=_on_agent_done,
                    )

                    state = merged_state
                    completed.add(phase_idx)
                    if ckpt_svc:
                        ckpt_svc.save(task_id, {
                            "state": dict(state),
                            "completed_phases": sorted(completed),
                        })

        # 流水线全部完成 —— 清理断点数据
        if ckpt_svc:
            ckpt_svc.delete(task_id)

        return state

    def _select_agents_for_phase(self, phase, state):
        """动态选择当前阶段需要运行的 Agent。

        如果配置了 agent_selector（如 AgentSelector），则根据代码变更特征
        智能选择需要运行的 Agent（如小变更只跑规则检查，跳过安全/性能分析）。
        如果选择器出错，保守地回退到运行全部 Agent。
        """
        if self._config.agent_selector is None:
            return phase
        try:
            selected = self._config.agent_selector(state)
            name_map = {name: (name, fn) for name, fn in phase}
            result = []
            for name, _fn in selected:
                if name in name_map:
                    result.append(name_map[name])
            return result or phase
        except Exception as exc:
            logger.warning(
                "Agent selector failed, falling back to full phase: %s",
                safe_detail(exc),
            )
            return phase

    def _run_parallel(
        self,
        phase,
        state,
        context,
        on_agent_done: Callable[[str, dict], None] | None = None,
    ):
        """并行执行一个阶段内的多个 Agent。

        工作原理：
        1. 用 ThreadPoolExecutor 为每个 Agent 分配一个线程
        2. 检查熔断器：如果某个 Agent 连续失败太多次，直接跳过（避免反复失败浪费时间）
        3. 等待所有线程完成（超时 45 秒自动中止）
        4. 收集结果，合并到主状态中

        类比：
          就像餐厅的"多人协作工位"——安全审计员和性能分析员同时审查同一份代码，
          各自独立工作，最后把各自的发现汇总到一起。
        """
        log_lock = threading.Lock()  # 线程锁：多个线程同时写日志时需要排队
        results: dict[str, dict] = {}  # 各 Agent 的执行结果
        errors: dict[str, str] = {}    # 各 Agent 的错误信息

        with ThreadPoolExecutor(max_workers=len(phase)) as pool:
            futures: dict[Future, str] = {}  # Future → Agent 名称的映射
            for name, fn in phase:
                # 熔断器检查：如果 Agent 连续失败，暂时跳过它
                # 类比：保险丝烧了就不让再通电，等冷却后再试
                if (
                    self._config.circuit_breaker
                    and self._config.circuit_breaker.is_open(name)
                ):
                    logger.warning("Agent %s circuit open, skipping", name)
                    continue
                fut = pool.submit(
                    self._run_single_agent,
                    name, fn, state, context, log_lock,
                    on_agent_done,
                )
                futures[fut] = name

            # 收集所有线程的执行结果
            for future in futures:
                name = futures[future]
                try:
                    agent_state = future.result(timeout=AGENT_EXECUTION_TIMEOUT_SECONDS)
                    results[name] = agent_state
                    if self._config.circuit_breaker:
                        self._config.circuit_breaker.record_success(name)  # 成功 → 重置失败计数
                except FutureTimeoutError:
                    errors[name] = f"timeout after {AGENT_EXECUTION_TIMEOUT_SECONDS}s"
                    logger.error("Agent %s timeout", name)
                    if self._config.circuit_breaker:
                        self._config.circuit_breaker.record_failure(name)  # 超时 → 失败计数+1
                except Exception as exc:
                    errors[name] = safe_detail(exc)
                    logger.error("Agent %s failed: %s", name, exc)
                    if self._config.circuit_breaker:
                        self._config.circuit_breaker.record_failure(name)

        # 为被跳过或失败的 Agent 填充空结果（确保合并时不报错）
        for name, _fn in phase:
            if name not in results:
                results[name] = {}

        if errors:
            raise RuntimeError(
                f"Parallel phase agents failed: {errors}"
            )

        return self._merge_results(state, results)

    def _run_single_agent(self, name, fn, state, context, log_lock, on_done=None):
        """在线程中执行单个 Agent 节点。

        每个 Agent 在独立线程中运行，完成后：
        1. 用线程锁保护日志写入（避免多线程同时写导致日志混乱）
        2. 调用 on_done 回调（用于断点续传的增量保存）
        3. 返回 Agent 的输出状态
        """
        start = perf_counter()
        try:
            result_state = fn(state, context)
            with log_lock:  # 加锁：确保同一时刻只有一个线程在写日志
                self._append_log(
                    name, context.task_id, {}, dict(result_state), start, "SUCCEEDED"
                )
            if on_done:
                on_done(name, dict(result_state))  # 通知断点服务：这个 Agent 完成了
            return result_state
        except Exception as exc:
            with log_lock:
                self._append_log(
                    name, context.task_id, {}, {"error": str(exc)}, start, "FAILED"
                )
            raise

    def _merge_results(self, base: GraphState, results: dict[str, dict]) -> GraphState:
        """合并多个 Agent 的输出到主状态中。

        合并策略由 MERGE_STRATEGY 字典控制：
        - "extend"    → 列表追加（如 tool_logs：所有 Agent 的日志都要保留）
        - "replace"   → 直接替换（如 security_findings：安全审计结果直接覆盖）
        - "overwrite" → 默认策略，直接覆盖

        类比：
          多个专家各自写了审查报告，现在需要合并成一份总报告。
          有些章节是"追加"（如日志），有些是"覆盖"（如最终结论）。
        """
        for _name, agent_state in results.items():
            for key, value in agent_state.items():
                strategy = MERGE_STRATEGY.get(key, "overwrite")
                if strategy == "extend" and isinstance(value, list):
                    base.setdefault(key, []).extend(value)
                elif strategy == "replace":
                    base[key] = value
                else:
                    base[key] = value
        return base

    def _append_log(
        self,
        node_name: str,
        task_id: str,
        node_input: dict,
        node_output: dict,
        started_at: float,
        status: str,
    ) -> None:
        """记录节点执行日志（输入、输出、耗时、状态）。

        每次节点执行后都会调用此方法，用于事后排查问题。
        类比：就像工厂里每个工位都有"生产记录表"，记录做了什么、花了多久、成功还是失败。
        """
        duration_ms = int((perf_counter() - started_at) * 1000)  # 计算耗时（毫秒）
        log = NodeLog(
            task_id=task_id,
            node=node_name,
            input=node_input,
            output=node_output,
            duration_ms=duration_ms,
            status=status,
            timestamp=datetime.now(UTC),
        )
        self._config.log_service.append(log)

    def _build_result(self, request: ReviewRequest, state: GraphState) -> ReviewResult:
        """将流水线最终状态转换为前端可消费的 ReviewResult。

        这个方法负责"翻译"工作：
        - 将内部状态（GraphState 字典）转换为结构化的 API 响应对象
        - 处理评分格式转换（0~1 → 0~100 百分制）
        - 组装风险细分、建议列表、图片引用等

        类比：
          就像厨师做完菜后的"摆盘"——菜（数据）已经做好了，
          这里负责把它装进漂亮的盘子里（结构化响应），端给客人（前端）。
        """
        from config.settings import AppSettings

        # --- 转换风险评分细分为模型对象 ---
        breakdown_models: list[RiskBreakdown] = []
        for item in state.get("breakdown", []) or []:
            if isinstance(item, RiskBreakdown):
                breakdown_models.append(item)
                continue
            # 评分格式兼容：如果分数在 0~1 之间，转换为 0~100
            score = item.get("score", 0)
            if 0 <= score <= 1:
                score = int(round(score * SCORE_SCALE_FACTOR))
            else:
                score = int(round(score))
            breakdown_models.append(
                RiskBreakdown(dimension=item.get("dimension", "unknown"), score=score)
            )

        # --- 转换总风险评分 ---
        risk_score = state.get("risk_score", 50)
        if 0 <= risk_score <= 1:
            risk_score = int(round(risk_score * SCORE_SCALE_FACTOR))
        else:
            risk_score = int(round(risk_score))

        # 是否需要人工复核
        need_human_review = bool(state.get("need_human_review", False))
        task_status = (
            TaskStatus.NEED_REVIEW if need_human_review else TaskStatus.SUCCEEDED
        )

        # --- 组装最终的 ReviewResult ---
        result = ReviewResult(
            taskId=state["task_id"],
            status=task_status,
            riskScore=risk_score,
            riskSummary=state.get("summary", "No summary"),
            details=state.get("details", []),
            riskBreakdown=breakdown_models,
            recommendations=[
                Recommendation(title=rec.get("title", ""), detail=rec.get("detail", ""))
                for rec in state.get("recommendations", [])
            ]
            or [
                Recommendation(
                    title="summary", detail=state.get("summary", "No summary")
                )
            ],
            reportUrl=f"reports/{state['task_id']}.json",
            needHumanReview=need_human_review,
            ragStatus=state.get("rag_status", RAGStatus.NORMAL),
            tier=state.get("tier", Tier.LLM_ENHANCED),
            traceId=request.traceId or f"trace-{state['task_id']}",
            mode=request.mode.value,
        )

        self._replace_image_urls(result)
        return result

    def _replace_image_urls(self, result: ReviewResult) -> None:
        """替换结果文本中的图片占位 URL 为可访问的真实地址。

        LLM 生成的报告中可能包含 MinIO 图片链接，
        这里将占位符替换为前端可直接渲染的 Markdown 图片语法。
        如果替换失败也不影响主流程（catch 异常后仅记录警告）。
        """
        try:
            from config.settings import AppSettings

            settings = AppSettings()
            image_service = ImageService(settings)
            endpoint = settings.minio_endpoint.rstrip("/")
            bucket = settings.minio_image_bucket

            if result.riskSummary:
                result.riskSummary = replace_markdown_image_urls(
                    result.riskSummary, endpoint, bucket
                )
                result.riskSummary = image_service.replace_image_urls(result.riskSummary)

            result.details = [
                image_service.replace_image_urls(
                    replace_markdown_image_urls(d, endpoint, bucket)
                )
                for d in result.details
            ]

            result.recommendations = [
                Recommendation(
                    title=image_service.replace_image_urls(
                        replace_markdown_image_urls(rec.title, endpoint, bucket)
                    ),
                    detail=image_service.replace_image_urls(
                        replace_markdown_image_urls(rec.detail, endpoint, bucket)
                    ),
                )
                for rec in result.recommendations
            ]
        except Exception as exc:
            logger.warning("Image URL replacement failed: %s", safe_detail(exc))
