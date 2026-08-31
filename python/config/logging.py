"""
日志配置模块
==========

本模块负责统一配置 Python 服务的日志输出格式和规则。

日志是什么？
----------
日志就像是程序的"行车记录仪"——程序运行过程中发生的一切（正常请求、异常报错、
关键决策）都会被记录下来。当线上出问题时，开发人员不用"猜"发生了什么，
直接查看日志就能还原案发现场。

本模块做了两件事：
1. **定义日志格式**：规定每条日志长什么样——包含时间、级别、模块名、追踪ID、任务ID、消息内容
2. **配置根日志器**：让整个项目的所有模块共享同一套日志输出规则，避免各写各的

为什么需要统一的日志格式？
-----------------------
- 如果每个模块的日志格式都不一样，排查问题时就像读一本每页排版都不同的书，效率极低
- 统一的格式（尤其是 trace_id 和 task_id 字段）可以和 Java 后端、ELK 日志平台对接，
  实现"一条请求在所有服务间的日志一键串联"
"""
from __future__ import annotations  # 延迟求值类型注解，提升启动速度

import logging  # Python 内置的日志库，就像程序自带的"行车记录仪 SDK"
import sys  # 系统相关功能，这里用来把日志输出到终端（stdout）

# ── 日志格式模板 ──────────────────────────────────────────────────
# 每条日志都按照这个模板输出，格式说明：
#   %(asctime)s    → 时间戳（如 2026-07-04 14:30:00,123）
#   %(levelname)s  → 日志级别（DEBUG / INFO / WARNING / ERROR）
#   %(name)s       → 发出日志的模块名（如 "app.routers.review"）
#   trace=...      → 追踪ID，串联同一请求的所有日志
#   task=...       → 任务ID，标识具体的异步任务
#   %(message)s    → 日志正文（开发人员手写的内容）
#
# 为什么 trace_id 和 task_id 写在自定义字段里而不是 message 里？
# 答：结构化字段可以被 ELK 等日志平台自动解析、搜索、聚合——
#     就像 Excel 表格里每个字段都有独立列，可以一键筛选，
#     如果全塞在 message 里就只能靠人眼 grep 了
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s trace=%(trace_id)s task=%(task_id)s %(message)s"


class _DefaultTraceFilter(logging.Filter):
    """
    日志过滤器：确保每条日志都有 trace_id 和 task_id 字段。

    为什么要这个过滤器？
    -----------------
    日志格式模板中使用了 %(trace_id)s 和 %(task_id)s，但并非所有地方都会
    主动设置这两个字段（比如项目启动阶段的日志还没有请求上下文）。
    如果某条日志没有这些字段，Python 的日志框架会直接报错，导致日志丢失。

    这个过滤器就像一个"补位员"：在每条日志输出前检查，如果某个字段缺失，
    就用 "-" 填充占位，保证日志格式永远不会炸。

    类比：就像考试时每个学生必须填姓名和学号，如果有人忘了，
    监考老师（本过滤器）会帮他写上"未知"，而不是直接不收卷子。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        在每条日志输出前被调用，补全缺失的字段。

        Args:
            record: 一条即将输出的日志记录对象，包含了日志的所有字段

        Returns:
            bool: 始终返回 True，表示"这条日志可以输出"（如果返回 False 会被丢弃）
        """
        # 检查日志记录上是否已有 trace_id 字段，没有就补 "-"
        # hasattr 就像问"这个对象有这个属性吗？"——安全地在不存在的属性上操作会直接报错
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        # 同理，为 task_id 提供默认值
        if not hasattr(record, "task_id"):
            record.task_id = "-"
        return True


def configure_logging() -> None:
    """
    配置根日志器（Root Logger），统一整个项目的日志输出规则。

    Python 的日志系统是树状结构——根日志器是所有日志器的"祖先"，
    就像公司总部的行政规定会生效到所有部门一样，根日志器的配置
    会被项目中所有子模块（routers / services / repositories 等）继承。

    具体配置了：
    1. **输出目标**：终端 stdout（容器环境下会被 Docker 收集，
       就像把行车记录仪的视频实时上传到云端）
    2. **输出格式**：使用上面定义的 LOG_FORMAT 模板
    3. **过滤器**：挂载 _DefaultTraceFilter，确保 trace_id / task_id 不会缺失
    4. **日志级别**：INFO（只记录正常信息及以上，DEBUG 调试信息默认不输出，
       避免日志量过大——就像行车记录仪没必要记录每一次正常刹车）
    5. **防重复**：如果已经配置过 handler，就不再重复添加（否则同一条日志会打印多次）

    Returns:
        None: 该函数没有返回值，它的作用是修改全局日志系统的状态（副作用）
    """
    # 创建一个输出到终端（stdout）的处理器
    # 为什么用 stdout 而不是 stderr？Docker / K8s 集群中 stdout 会被统一采集到日志平台
    handler = logging.StreamHandler(sys.stdout)

    # 把格式模板交给处理器——告诉它"每条日志长什么样"
    formatter = logging.Formatter(LOG_FORMAT)
    handler.setFormatter(formatter)

    # 挂载过滤器——在日志输出前自动补全 trace_id 和 task_id
    handler.addFilter(_DefaultTraceFilter())

    # 获取根日志器（所有日志器的"老祖宗"）
    root = logging.getLogger()

    # 防止重复添加：如果根日志器已经有 handler 了，就跳过
    # 这很重要！否则每次调用 configure_logging() 都会多装一个 handler，
    # 导致同一条日志被重复输出 N 次——就像同一个通知被钉钉、微信、短信各发了一遍
    if not root.handlers:
        root.addHandler(handler)

    # 设置全局日志级别为 INFO
    # 低于 INFO 的日志（如 DEBUG）会被直接丢弃，不输出
    # DEBUG 级别主要用于开发调试，生产环境不需要，避免日志量过大且包含敏感调试信息
    root.setLevel(logging.INFO)
