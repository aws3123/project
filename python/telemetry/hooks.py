"""
遥测钩子抽象模块 —— 定义"如何记录 LangGraph 流水线中每个节点的执行情况"。

什么是遥测（Telemetry）？
    遥测就是"自动采集和上报系统运行数据"的机制。
    比如：某个节点执行了多久、成功还是失败、出了什么错误……
    这些数据可以帮助我们监控和调试流水线。

什么是钩子（Hook）？
    钩子是一种设计模式：在系统运行的关键节点"预埋"一个接口，
    允许外部插入自定义逻辑。就像在流水线上装了一个"观测窗口"。

本模块提供了：
    1. TelemetryHook  —— 一个"协议"（接口），定义了记录遥测数据的方法
    2. NoOpTelemetry   —— "什么都不做"的空实现（默认安全）
    3. LoggingTelemetryHook —— 把遥测数据写入 Python 标准日志
    4. CompositeTelemetryHook —— 把一条数据同时分发给多个钩子（扇出模式）
"""

from __future__ import annotations

import logging
# Protocol 是 Python 3.8+ 提供的"结构化子类型"机制
# 简单理解：它定义了一个"接口"，只要你的类实现了接口要求的方法，就自动算作"实现了这个接口"
# 不需要显式继承，这叫"鸭子类型"的形式化版本
from typing import Protocol

# NodeLog 是一个数据类，包含了某个节点执行后的日志信息
# 比如：task_id（任务ID）、node（节点名）、status（状态）、duration_ms（耗时）等
from schemas.log import NodeLog


# ============================================================
# TelemetryHook —— 遥测钩子的"协议"（接口定义）
# ============================================================
# 用 Protocol 定义接口，任何实现了 record_node 和 record_error 方法的类都自动满足这个协议
# 这就像定义了一份"合同"：你至少要提供这两个方法
class TelemetryHook(Protocol):
    """记录节点执行详情的契约（接口）。

    任何想充当遥测收集器的类，都需要实现下面两个方法：
    - record_node: 记录一次正常的节点执行
    - record_error: 记录一次节点执行中的异常
    """

    def record_node(self, log: NodeLog) -> None:
        """记录一个节点的成功/正常执行。

        参数:
            log: NodeLog 对象，包含节点名称、任务ID、执行耗时等信息
        """
        ...

    def record_error(self, log: NodeLog, exc: Exception) -> None:
        """记录一个节点执行时发生的错误。

        参数:
            log: NodeLog 对象，包含节点的上下文信息
            exc: 捕获到的异常对象，可以用 str(exc) 获取错误描述
        """
        ...


# ============================================================
# NoOpTelemetry —— "空操作"遥测实现
# ============================================================
# NoOp = No Operation（无操作）
# 这是默认使用的遥测实现：什么都不做，直接返回
# 为什么需要它？因为"空对象模式"可以避免到处写 if hook is None 的判断
# 有了它，调用方永远可以安全地调用 hook.record_node()，不用担心空指针
class NoOpTelemetry(TelemetryHook):
    """默认的遥测实现：什么都不做（空操作）。

    使用场景：
    - 本地开发/调试时不需要遥测
    - 作为默认值，避免调用方做 None 检查
    """

    def record_node(self, log: NodeLog) -> None:  # pragma: no cover - intentionally empty
        """什么都不做，直接返回 None。"""
        return None

    def record_error(self, log: NodeLog, exc: Exception) -> None:  # pragma: no cover
        """什么都不做，直接返回 None。"""
        return None


# ============================================================
# LoggingTelemetryHook —— 基于标准日志的遥测钩子
# ============================================================
# 这是最常用的实现：把节点执行信息写入 Python 的 logging 系统
# 生产环境中，logging 会输出到文件、控制台、或集中式日志平台（如 ELK）
class LoggingTelemetryHook(TelemetryHook):
    """把节点执行事件写入 Python 标准日志的遥测钩子。

    工作原理：
    - 内部持有一个 logging.Logger 实例
    - record_node 时以 INFO 级别记录节点名、耗时等
    - record_error 时以 ERROR 级别记录，额外包含异常信息

    参数:
        logger: 可选的自定义 Logger。如果不传，默认创建名为 "telemetry.node" 的 Logger
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        # 如果调用方没传 logger，就创建一个默认的
        # logging.getLogger("telemetry.node") 会获取（或创建）名为 "telemetry.node" 的 Logger
        self._logger = logger or logging.getLogger("telemetry.node")

    def record_node(self, log: NodeLog) -> None:
        """以 INFO 级别记录一次正常的节点执行。

        extra 字典中的字段会被日志格式化器使用（如果配置了 JSON 格式化器，
        这些字段会出现在 JSON 输出中，方便日志分析平台解析）。
        """
        self._logger.info(
            "node_execution",  # 日志消息（事件名称）
            extra={
                # extra 中的字段会附加到日志记录上，供日志处理器使用
                "trace_id": "-",          # 链路追踪ID（这里暂未集成，用 "-" 占位）
                "task_id": log.task_id,   # 当前任务的唯一标识
                "node": log.node,         # 节点名称（如 "security_audit", "performance_analysis"）
                "status": log.status,     # 执行状态（如 "success", "failed"）
                "duration_ms": log.duration_ms,  # 执行耗时（毫秒）
            },
        )

    def record_error(self, log: NodeLog, exc: Exception) -> None:
        """以 ERROR 级别记录一次节点执行异常。

        比 record_node 多了一个 "error" 字段，记录异常的文本描述。
        """
        self._logger.error(
            "node_execution_error",
            extra={
                "trace_id": "-",
                "task_id": log.task_id,
                "node": log.node,
                "status": log.status,
                "duration_ms": log.duration_ms,
                "error": str(exc),  # 把异常对象转成字符串，记录错误信息
            },
        )


# ============================================================
# CompositeTelemetryHook —— 组合/扇出遥测钩子
# ============================================================
# 设计模式：组合模式（Composite Pattern）
# 当你需要同时把遥测数据发送到多个目的地时使用
# 比如：同时写日志 + 发送到 Prometheus 指标系统
# 它内部维护一个钩子列表，每次调用时遍历列表，逐个委托
class CompositeTelemetryHook(TelemetryHook):
    """扇出（fan-out）钩子：把每次遥测调用委托给多个子钩子。

    使用场景：
    - 同时写入日志和发送到远程监控系统
    - 在测试中同时记录到内存和标准输出

    参数:
        hooks: 子钩子列表。如果不传，默认为空列表（相当于 NoOp）
    """

    def __init__(self, hooks: list[TelemetryHook] | None = None) -> None:
        # 保存子钩子列表；如果没传则初始化为空列表
        self._hooks = hooks or []

    def record_node(self, log: NodeLog) -> None:
        """遍历所有子钩子，依次调用它们的 record_node 方法。"""
        for hook in self._hooks:
            hook.record_node(log)

    def record_error(self, log: NodeLog, exc: Exception) -> None:
        """遍历所有子钩子，依次调用它们的 record_error 方法。"""
        for hook in self._hooks:
            hook.record_error(log, exc)
