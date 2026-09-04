"""业务风险分析运行器模块 —— 业务风险分析流水线的"启动钥匙"。

本模块实现了 BusinessRiskRunner，负责启动业务风险分析流水线。

与主审查流水线（GraphRunner）的关系：
  - 主审查流水线关注：安全、性能、规则等通用代码审查
  - 业务风险分析流水线关注：业务状态变更风险、不变量违反、语义热点等
  - 两者共享相同的"引擎"（GraphRunner），但使用不同的节点和状态

类比：
  如果 GraphRunner 是一辆"汽车引擎"，那 BusinessRiskRunner 就是
  用这个引擎组装出来的一辆"业务风险检测车"——引擎相同，但装载的
  检测设备（节点）和检测目标（状态）不同。
"""
from __future__ import annotations

from graph.business_risk_result import build_business_risk_result
from graph.business_risk_state import BusinessRiskGraphState
from graph.runner import GraphRunner
from schemas.domain.business_risk_review import BusinessRiskReviewRequest, BusinessRiskReviewResult


class BusinessRiskRunner:
    """业务风险分析运行器 —— 封装 GraphRunner，专门处理业务风险审查请求。

    工作流程：
    1. 接收业务风险审查请求（BusinessRiskReviewRequest）
    2. 将请求转换为业务风险专用的共享状态（BusinessRiskGraphState）
    3. 调用 GraphRunner.run_state() 执行所有业务风险分析节点
    4. 将最终状态转换为业务风险审查结果（BusinessRiskReviewResult）
    """
    def __init__(self, runner: GraphRunner) -> None:
        """初始化业务风险运行器。

        参数:
            runner: 已经装配好业务风险节点的 GraphRunner 实例
                   （由 GraphBuilder 构建，包含提取器、RAG、不变量检查等节点）
        """
        self._runner = runner

    def run(self, request: BusinessRiskReviewRequest) -> BusinessRiskReviewResult:
        """执行完整的业务风险分析流水线。

        参数:
            request: 业务风险审查请求，包含代码变更、源码包等信息

        返回:
            BusinessRiskReviewResult: 包含风险等级、不变量违反、语义发现等的完整报告
        """
        # 将请求转换为共享状态（"公共白板"），供各节点读写
        state: BusinessRiskGraphState = {
            "task_id": request.task_id,       # 任务唯一标识
            "run_id": request.run_id,         # 本次运行唯一标识
            "trace_id": request.trace_id,     # 链路追踪 ID
            "request": request.model_dump(),  # 请求的完整字典形式
            "source_package": request.source_package.model_dump(),  # 源码包（含 AST、热点等）
        }
        # 执行所有业务风险分析节点
        graph_state = self._runner.run_state(state)
        # 将最终状态转换为前端可消费的结果
        return build_business_risk_result(request, graph_state)
