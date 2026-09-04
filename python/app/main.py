"""FastAPI 应用入口 —— Python AI 服务的启动文件和主配置。

这个文件是整个 Python 服务的"大门"。当服务启动时：
  1. 首先配置日志系统（configure_logging）
  2. 创建 FastAPI 应用实例
  3. 注册路由（Router）：将不同的 URL 路径映射到对应的处理函数
  4. 注册中间件（Middleware）：在每个请求前后执行的公共逻辑
  5. 注册异常处理器：自定义错误响应格式

路由结构：
  /ai/review/*     → 代码审查相关接口
  /ai/business-risk-source/* → 业务风险分析接口
  /ai/health/*     → 健康检查接口
  /ai/handoff/*    → 审查结果交接接口
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import exceptions
from app.dependencies import (
    get_ai_service,
    get_business_risk_source_readiness,
    get_business_risk_worker_state,
    get_settings,
)
from app.routers import review, health, handoff, business_risk_source
from app.utils import create_trace_id
from config.logging import configure_logging
from services.worker_registry import WorkerRegistry

# 初始化日志系统（在应用启动时执行一次）
configure_logging()
logger = logging.getLogger(__name__)


# 全局变量：Worker 注册表实例、心跳任务、Kafka 异步链路消费者
_registry_task: asyncio.Task | None = None
_registry: WorkerRegistry | None = None
_kafka_consumer_task: asyncio.Task | None = None
_kafka_consumer: object | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理器 —— 控制应用启动和关闭时的行为。

    启动时：
      1. 加载配置
      2. 创建 WorkerRegistry（向 Java 后端注册自己）
      3. 启动心跳循环（定期告诉 Java 后端"我还活着"）
      4. 若 kafka_enabled，启动 Kafka 审查任务消费者（Java 生产者 → Python 消费者）
    关闭时：
      1. 注销 Worker（告诉 Java 后端"我要下线了"）
      2. 取消心跳任务
      3. 停止 Kafka 消费者
    """
    global _registry, _registry_task, _kafka_consumer, _kafka_consumer_task
    settings = get_settings()
    app.state.settings = settings  # 将配置挂载到 app 对象上，供全局访问

    # 创建 Worker 注册表（负责与 Java 后端的服务发现通信）
    _registry = WorkerRegistry(
        settings=settings,
        readiness_provider=get_business_risk_source_readiness,  # 就绪状态检查函数
        worker_state=get_business_risk_worker_state(),
    )
    # 启动心跳循环（一个异步任务，定期发送心跳）
    _registry_task = asyncio.create_task(_registry.heartbeat_loop())
    logger.info("WorkerRegistry heartbeat sender started instance=%s", _registry._instance_id)

    # 若启用 Kafka 异步链路，启动审查任务消费者
    if settings.kafka_enabled:
        from mq.review_consumer import ReviewKafkaConsumer

        ai_service = get_ai_service()
        _kafka_consumer = ReviewKafkaConsumer(settings, process_message=ai_service.run)
        await _kafka_consumer.start()
        _kafka_consumer_task = asyncio.create_task(_kafka_consumer.run())
        logger.info("Kafka review consumer task started")

    yield  # <-- 应用运行期间停在这里

    # ---- 应用关闭时的清理工作 ----
    if _kafka_consumer_task is not None:
        _kafka_consumer_task.cancel()  # 取消消费任务
    if _kafka_consumer is not None:
        await _kafka_consumer.stop()  # 停止消费者/生产者，提交未提交 offset
    if _registry is not None:
        await _registry.unregister()  # 注销 Worker
    if _registry_task is not None:
        _registry_task.cancel()  # 取消心跳任务
    logger.info("WorkerRegistry unregistered")


# 创建 FastAPI 应用实例
app = FastAPI(title="AI Code Review Sentinel AI Layer", lifespan=lifespan)
# 注册路由（将 URL 路径映射到处理函数）
app.include_router(review.router, prefix="/ai", tags=["review"])
app.include_router(business_risk_source.router, prefix="/ai", tags=["business-risk-source"])
app.include_router(health.router, prefix="/ai", tags=["health"])
app.include_router(handoff.router, prefix="/ai", tags=["handoff"])


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    """链路追踪中间件 —— 为每个请求分配唯一的追踪 ID。

    什么是中间件？
      中间件是在请求到达路由处理函数之前/之后执行的公共逻辑。
      就像工厂的"门卫"：每个进出的人都要经过检查。

    这个中间件的作用：
      1. 从请求头中获取 X-Trace-Id（如果前端传了的话）
      2. 如果没有，就生成一个新的追踪 ID
      3. 将追踪 ID 挂载到 request.state 上（后续代码可以访问）
      4. 在响应头中也加上追踪 ID（方便前端调试）
    """
    # 优先使用请求头中的追踪 ID，否则生成新的
    trace_id = request.headers.get("X-Trace-Id") or create_trace_id()
    request.state.trace_id = trace_id  # 挂载到请求状态上
    response = await call_next(request)  # 继续执行后续的路由处理
    response.headers["X-Trace-Id"] = trace_id  # 在响应头中返回追踪 ID
    return response


@app.exception_handler(exceptions.ServiceError)
async def service_error_handler(request: Request, exc: exceptions.ServiceError):
    """ServiceError 异常处理器 —— 将 ServiceError 转换为统一的 JSON 响应。

    当代码中 raise ServiceError(...) 时，FastAPI 会自动调用这个处理器，
    返回格式统一的错误响应。
    """
    trace_id = getattr(request.state, "trace_id", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={"errorCode": "PY001", "message": exc.detail.get("message"), "traceId": trace_id},
    )
