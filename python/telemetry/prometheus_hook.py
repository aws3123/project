"""Prometheus 遥测钩子 —— 把 LangGraph 节点执行指标暴露给 Prometheus。

与 LoggingTelemetryHook 不同，本钩子把节点执行数据转成**指标（Metrics）**，
而不是日志文本。Prometheus 通过 HTTP 拉取这些指标（/metrics 端点），
再交给 Grafana 做可视化与告警。

指标设计：
    - review_node_duration_seconds（Histogram）
        每个节点的执行耗时分布。标签：node（节点名）、status（状态）。
        用于观察"哪个节点最慢"、P50/P95 延迟。
    - review_node_total（Counter）
        节点执行次数累计。标签：node、status。用于观察执行量与成功率。
    - review_node_errors_total（Counter）
        节点执行失败次数累计。标签：node。失败率 = 该计数 / review_node_total。

使用 prometheus_client 的全局默认注册表（REGISTRY），
这样 /metrics 端点只需一行即可导出所有指标（含进程级 CPU/内存/GC 指标）。
"""

from prometheus_client import Counter, Histogram

from schemas.domain.log import NodeLog

# 节点执行耗时直方图：buckets 覆盖 10ms ~ 60s，贴合 LLM 节点（秒级~分钟级）耗时范围
_node_duration = Histogram(
    "review_node_duration_seconds",
    "Execution duration of a LangGraph review node",
    labelnames=["node", "status"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)

# 节点执行次数（按 节点+状态 维度累计）
_node_total = Counter(
    "review_node_total",
    "Total number of LangGraph review node executions",
    labelnames=["node", "status"],
)

# 节点执行失败次数（按 节点 维度累计）
_node_errors = Counter(
    "review_node_errors_total",
    "Total number of LangGraph review node errors",
    labelnames=["node"],
)


class PrometheusTelemetryHook:
    """把节点执行指标写入 Prometheus 默认注册表的遥测钩子。"""

    def record_node(self, log: NodeLog) -> None:
        """记录一次节点执行：更新耗时直方图与执行次数计数。"""
        status = (log.status or "UNKNOWN").lower()
        _node_duration.labels(node=log.node, status=status).observe(
            max(log.duration_ms, 0) / 1000.0
        )
        _node_total.labels(node=log.node, status=status).inc()

    def record_error(self, log: NodeLog, exc: Exception) -> None:
        """记录一次节点异常：更新失败计数（并补记一次失败的执行）。"""
        status = (log.status or "FAILED").lower()
        _node_errors.labels(node=log.node).inc()
        _node_total.labels(node=log.node, status=status).inc()
