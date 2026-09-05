"""
图构建器模块 —— 流水线装配工厂
==============================

本模块提供 GraphBuilder，用于"组装"代码审查流水线。

核心概念：
- 流水线由多个"阶段"（Phase）组成，每个阶段包含一个或多个"节点"（Node）
- 单节点阶段 → 顺序执行（一步一步走）
- 多节点阶段 → 并行执行（多个专家同时工作）

类比：
  把 GraphBuilder 想象成"乐高积木拼装说明书"：
  - add_node()      → 往流水线上添加一个"单人工位"
  - add_parallel_group() → 往流水线上添加一个"多人协作工位"
  - build()         → 按说明书把工位串起来，生成可运行的 GraphRunner

最终产出的 GraphRunner 就是真正执行审查的"流水线机器"。
"""

from __future__ import annotations  # 延迟类型注解，避免循环导入

from collections.abc import Callable  # Callable = 可调用对象的类型提示（函数、方法等）
from dataclasses import dataclass  # 自动生成 __init__ 等样板代码
from typing import TYPE_CHECKING, Any

from graph.circuit_breaker import (
    CircuitBreaker,  # 熔断器：某个 Agent 连续失败时自动跳过
)
from graph.runner import GraphRunner, RunnerConfig  # 实际执行流水线的运行器
from graph.state import GraphState, NodeContext  # 流水线共享状态 & 节点上下文
from services.checkpoint_service import (
    CheckpointService,  # 断点续传服务（任务中断后可恢复）
)
from services.log_service import LogService  # 日志服务（记录每个节点的输入输出）
from services.task_service import TaskService  # 任务状态管理服务
from telemetry.hooks import TelemetryHook  # 遥测钩子（监控指标采集）

if TYPE_CHECKING:
    from tools.registry import ToolRegistry  # 工具注册表（仅在类型检查时导入）

# 类型别名：让代码更易读
# NodeFn = 一个节点函数的类型：接收 (状态, 上下文)，返回更新后的状态
NodeFn = Callable[[GraphState, NodeContext], GraphState]
# Phase = 一个阶段：包含多个 (名称, 节点函数) 的元组列表
Phase = list[tuple[str, NodeFn]]


@dataclass(slots=True)
class BuilderConfig:
    """构建器配置 —— 集中存放创建 GraphRunner 所需的所有依赖。

    类比：就像开餐厅前准备的"设备清单"——厨房工具、服务员、收银机全在这里。
    """

    registry: ToolRegistry  # 工具注册表：节点通过它调用 diff_analyzer 等工具
    log_service: LogService  # 日志服务：记录每个节点的执行日志
    telemetry: TelemetryHook  # 遥测钩子：采集执行耗时等监控指标
    task_service: TaskService | None  # 任务服务：更新任务状态（可选）
    llm_client: Any | None = None  # LLM 客户端：调用大模型（可选，没有则走纯规则路径）
    circuit_breaker: CircuitBreaker | None = None  # 熔断器（可选，默认不启用）
    agent_selector: Callable[[GraphState], list[tuple[str, NodeFn]]] | None = (
        None  # Agent 选择器（动态决定跑哪些 Agent）
    )
    checkpoint_service: CheckpointService | None = None  # 断点续传服务（可选）


class GraphBuilder:
    """流水线构建器 —— 用"建造者模式"逐步组装审查流水线。

    使用方式（链式调用）：
        runner = (GraphBuilder(registry, log_svc, telemetry)
                  .add_node("diff分析", analyze_diff)        # 第1步：分析代码差异
                  .add_node("变更分类", classify_changes)     # 第2步：分类变更类型
                  .add_parallel_group([                       # 第3步：并行执行安全+性能分析
                      ("安全审计", audit_security),
                      ("性能分析", analyze_performance),
                  ])
                  .build())                                 # 最终：生成可运行的 GraphRunner

    为什么用建造者模式？
    - 流水线的节点组合是灵活的（不同场景可能需要不同步骤）
    - 建造者模式让组装过程清晰可读，像搭积木一样一步步叠加
    """

    def __init__(
        self,
        registry: ToolRegistry,
        log_service: LogService,
        telemetry: TelemetryHook,
        task_service: TaskService | None = None,
        llm_client: Any | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        agent_selector: Callable[[GraphState], list[tuple[str, NodeFn]]] | None = None,
        checkpoint_service: CheckpointService | None = None,
    ) -> None:
        # 将所有依赖打包存入 _config，后续 build() 时一次性取出
        self._config = BuilderConfig(
            registry,
            log_service,
            telemetry,
            task_service,
            llm_client,
            circuit_breaker,
            agent_selector,
            checkpoint_service,
        )
        # _phases 是有序的"阶段列表"，每个阶段是一个节点列表
        # 单节点列表 = 顺序执行，多节点列表 = 并行执行
        self._phases: list[Phase] = []

    def add_node(self, name: str, fn: NodeFn) -> GraphBuilder:
        """添加一个顺序执行节点（独立阶段）。

        类比：在流水线上增加一个"单人工作台"，前一个工位做完才轮到这个。
        返回 self 以支持链式调用（如 builder.add_node(...).add_node(...)）。
        """
        self._phases.append([(name, fn)])  # 单节点包装成单元素列表
        return self

    def add_parallel_group(self, nodes: list[tuple[str, NodeFn]]) -> GraphBuilder:
        """添加一组并行执行节点（并行阶段）。

        类比：在流水线上增加一个"多人协作工作台"，
        多个专家同时工作（如安全审计和性能分析同时进行），全部完成后才进入下一工位。

        为什么需要并行？
        - 安全审计和性能分析互不依赖，同时跑可以节省时间
        - 就像医院里验血和拍片可以同时进行，不用等一个做完再做另一个
        """
        self._phases.append(nodes)  # 多节点直接作为一个阶段
        return self

    def build(self) -> GraphRunner:
        """根据已添加的阶段列表，构建最终的 GraphRunner。

        类比：积木搭完了，按下"确认"按钮，生成一个可运行的成品。

        如果没有添加任何阶段就调用 build()，会抛出 ValueError——
        就像一条没有任何工位的流水线，没有意义。
        """
        if not self._phases:
            raise ValueError(
                "GraphBuilder requires at least one phase to build a runner"
            )
        # 将 BuilderConfig 转换为 RunnerConfig（运行器需要的配置格式）
        config = RunnerConfig(
            registry=self._config.registry,
            log_service=self._config.log_service,
            telemetry=self._config.telemetry,
            task_service=self._config.task_service,
            llm_client=self._config.llm_client,
            circuit_breaker=self._config.circuit_breaker
            or CircuitBreaker(),  # 没提供则用默认熔断器
            agent_selector=self._config.agent_selector,
            checkpoint_service=self._config.checkpoint_service,
        )
        # 用 .copy() 复制阶段列表，防止外部后续修改影响已构建的 Runner
        return GraphRunner(phases=self._phases.copy(), config=config)
