"""
图状态与节点上下文定义模块
========================

本模块定义了整个代码审查流水线的"共享数据容器"和"节点运行环境"。

核心概念：
- GraphState（图状态）：就像一块"公共白板"，流水线中每个节点（分析步骤）
  都在这块白板上写入自己的分析结果，后续节点可以读取前面所有节点的输出。
  用 TypedDict 定义，意味着它是一个有固定字段名的字典。
- NodeContext（节点上下文）：每个节点运行时携带的"工具箱"，
  包含工具注册表、LLM 客户端、任务服务等——节点需要的外部依赖都在这里。

为什么用 TypedDict 而不是 dataclass？
- TypedDict 本质还是 dict，可以灵活地 .get() 取值、动态添加字段
- dataclass 属性访问更严格，但不够灵活——流水线节点可能按需写入不同字段
"""
from __future__ import annotations  # 延迟类型注解：让 Python 不在模块加载时就解析所有类型，避免循环导入

from dataclasses import dataclass  # dataclass 装饰器：自动生成 __init__、__repr__ 等方法
from typing import TYPE_CHECKING, Any, Dict, List, TypedDict

from services.task_service import TaskService
from telemetry.hooks import TelemetryHook

# TYPE_CHECKING 为 True 仅在静态类型检查工具（如 mypy）运行时成立，
# Python 实际运行时为 False —— 这样导入只为了给类型检查器看，不会真正执行导入
# 好处：避免循环导入，同时保留类型提示
if TYPE_CHECKING:
    from tools.registry import ToolRegistry


class GraphState(TypedDict, total=False):
    """流水线全局共享状态 —— 所有节点通过读写这个字典来传递数据。

    类比：把它想象成一个"接力赛跑棒"，每个跑步者（节点）接过棒后
    在上面贴自己的分析结果，然后传给下一个跑步者。

    total=False 表示所有字段都是可选的（不是每个节点都会写入所有字段）。
    """
    task_id: str                                          # 任务唯一标识，贯穿整个流水线
    request: Dict[str, Any]                               # 原始审查请求（来自 Java BFF 层）
    diff_analysis: Dict[str, Any]                         # diff 分析结果（代码变更的文件、行数、实体等）
    classification: Dict[str, Any]                        # 变更分类结果（代码所在层次：controller/service/sql 等）
    rule_findings: List[Dict[str, Any]]                   # 规则检查发现（SQL风险、API兼容性、配置变更等）
    rag_context: List[Dict[str, Any]]                     # RAG 检索到的历史事故上下文
    rag_analysis: str                                     # LLM 基于 RAG 结果的风险关联分析文本
    rag_status: str                                       # RAG 运行状态（NORMAL/DEGRADED）
    security_findings: List[Dict[str, Any]]               # 安全审计发现（SQL注入、硬编码密码、XSS 等）
    performance_findings: List[Dict[str, Any]]            # 性能分析发现（N+1查询、循环IO、大事务等）
    code_graph: Dict[str, Any]                            # 代码知识图谱数据（类/方法的调用关系）
    impact_radius: Dict[str, Any]                         # 变更影响范围（受影响的文件列表、影响评分）
    tool_logs: List[Dict[str, Any]]                       # 工具调用日志（记录每个工具的输入输出）
    risk_score: float                                     # 综合风险评分（0~1 或 0~100）
    breakdown: List[Dict[str, Any]]                       # 风险评分的维度细分（安全/性能/规则等各维度得分）
    need_human_review: bool                               # 是否需要人工复核
    summary: str                                          # 审查报告摘要（给人类看的总结）
    details: List[str]                                    # 审查报告的具体发现列表
    recommendations: List[Dict[str, Any]]                 # 可操作的改进建议
    business_invariants: Dict[str, Any]                   # 业务不变量（如"库存扣减必须在事务内"）
    data_flow_paths: Dict[str, Any]                       # 数据流路径（方法间的调用链路）
    invariant_violations: Dict[str, Any]                  # 不变量违反项（如"库存操作缺少事务保护"）
    method_issues: Dict[str, Any]                         # 方法级别的问题（热点方法的异常检测）
    semantic_findings: Dict[str, Any]                     # 语义分析发现（LLM 对热点方法的业务风险判断）
    business_risk_report: Dict[str, Any]                  # 业务风险评估报告
    verified_risks: Dict[str, Any]                        # 经过自验证的风险项
    trivial: bool                                         # 是否为平凡变更（纯注释/文档，可跳过深度分析）
    force_human_review: bool                              # 是否强制人工复核（Agent 间矛盾时触发）
    cross_validated_findings: List[Dict[str, Any]]        # 交叉验证后的去重发现（多 Agent 共识）


@dataclass(slots=True)
class NodeContext:
    """节点运行上下文 —— 每个节点执行时携带的"工具箱"。

    类比：如果说 GraphState 是"接力赛跑棒"（传递数据），
    那 NodeContext 就是每个跑步者穿的"跑鞋和装备"（共享的工具和资源）。

    参数说明：
        task_id: 当前任务 ID，用于日志追踪和状态持久化
        registry: 工具注册表，节点通过它调用各种检查工具（如 diff_analyzer、ast_parser）
        task_service: 任务服务，用于更新任务状态（如"进行中"→"已完成"）
        telemetry: 遥测钩子，用于采集性能指标和监控数据
        llm_client: LLM 客户端，需要调用大模型分析的节点通过它发起请求
    """
    task_id: str
    registry: "ToolRegistry"
    task_service: TaskService | None = None
    telemetry: TelemetryHook | None = None
    llm_client: Any | None = None
