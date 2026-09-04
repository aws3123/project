"""自定义异常类型 —— FastAPI 层的统一错误处理。

为什么需要自定义异常？
  FastAPI 默认的错误格式不够统一。通过定义自己的异常类，
  可以确保所有错误都返回相同格式的 JSON 响应，方便前端处理。

本模块定义了一个 ServiceError 异常：
  - 继承自 HTTPException（FastAPI 内置的 HTTP 异常基类）
  - 固定返回 500 状态码（内部服务器错误）
  - 响应体包含 message（错误消息）和 traceId（追踪 ID）
"""

from fastapi import HTTPException, status


class ServiceError(HTTPException):
    """服务层错误异常 —— 表示业务逻辑执行过程中发生了不可恢复的错误。

    用法示例：
        raise ServiceError("数据库连接失败", trace_id="abc123")

    前端收到的响应：
        HTTP 500
        {"message": "数据库连接失败", "traceId": "abc123"}
    """

    def __init__(self, message: str, trace_id: str | None = None):
        # 调用父类构造函数，设置 HTTP 状态码和响应体
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,  # 500 内部服务器错误
            detail={"message": message, "traceId": trace_id},
        )
