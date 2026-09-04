from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError

from config.settings import AppSettings
from mq.callback_producer import CallbackProducer
from mq.payload_client import PayloadClient, PayloadFetchError, PayloadNotFoundError
from schemas.api.backend_contract import parse_async_payload

logger = logging.getLogger(__name__)

DEDUP_KEY_PREFIX = "review:consumed:"

# 永久失败：schema 不兼容、diff 非法、payload 不存在等，重试无意义，直接进 DEAD_LETTER
class PermanentFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReviewKafkaConsumer:
    """Topic 1 审查任务消费者。

    语义：
      - enable_auto_commit=False，手动 commit（at-least-once）
      - 批处理：getmany 取一批 → 并发（信号量限流）逐条处理 → 整批完成后 commit。
        批级提交避免了分区内乱序提交导致的"跳过未处理消息"问题；
        若进程中途崩溃，整批重新投递（at-least-once，重复处理由 Redis 去重兜底）。
      - ack 策略：成功 → RESULT 回调；瞬时失败重试耗尽 / 永久失败 → DEAD_LETTER 回调，
        两者都视为"已处理"，随后正常 commit，避免无限重投打爆消费线程。
    """

    def __init__(
        self,
        settings: AppSettings | None = None,
        process_message: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
        producer: CallbackProducer | None = None,
        payload_client: PayloadClient | None = None,
    ) -> None:
        self._settings = settings or AppSettings()
        # process_message 注入审查流水线（默认为空，运行时由装配层提供）
        self._process_message = process_message
        self._producer = producer or CallbackProducer(self._settings)
        self._payload_client = payload_client or PayloadClient(self._settings)
        self._consumer: AIOKafkaConsumer | None = None
        self._redis: Any | None = None
        self._stop = False

    def _build_consumer(self) -> AIOKafkaConsumer:
        kwargs: dict[str, Any] = {
            "bootstrap_servers": self._settings.kafka_bootstrap_servers,
            "group_id": self._settings.kafka_group_id,
            "enable_auto_commit": False,
            "auto_offset_reset": "earliest",
            "max_poll_records": self._settings.kafka_max_poll_records,
            "max_poll_interval_ms": self._settings.kafka_max_poll_interval_ms,
            "value_deserializer": lambda v: json.loads(v.decode("utf-8")),
            "key_deserializer": lambda v: v.decode("utf-8") if v else None,
            "security_protocol": self._settings.kafka_security_protocol,
        }
        if self._settings.kafka_sasl_mechanism:
            kwargs.update(
                {
                    "sasl_mechanism": self._settings.kafka_sasl_mechanism,
                    "sasl_plain_username": self._settings.kafka_sasl_username,
                    "sasl_plain_password": self._settings.kafka_sasl_password,
                }
            )
        return AIOKafkaConsumer(
            self._settings.kafka_review_tasks_topic,
            **kwargs,
        )

    async def start(self) -> None:
        if self._process_message is None:
            raise RuntimeError("process_message must be injected before start")
        if self._settings.kafka_dedup_enabled:
            from redis.asyncio import Redis

            self._redis = Redis.from_url(self._settings.redis_url, decode_responses=True)
        self._consumer = self._build_consumer()
        await self._consumer.start()
        await self._producer.start()
        logger.info(
            "Review Kafka consumer started group=%s topic=%s",
            self._settings.kafka_group_id,
            self._settings.kafka_review_tasks_topic,
        )

    async def stop(self) -> None:
        self._stop = True
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None
        await self._producer.stop()
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        await self._payload_client.aclose()
        logger.info("Review Kafka consumer stopped")

    async def run(self) -> None:
        """消费主循环：取批 → 并发处理 → 整批 commit。"""
        if self._consumer is None:
            raise RuntimeError("consumer not started")
        semaphore = asyncio.Semaphore(self._settings.kafka_max_concurrency)

        async def bounded(coro: Awaitable[None]) -> None:
            async with semaphore:
                await coro

        while not self._stop:
            try:
                batch = await self._consumer.getmany(
                    timeout_ms=1000,
                    max_records=self._settings.kafka_max_poll_records,
                )
                if not batch:
                    continue
                tasks: list[Awaitable[None]] = []
                for _topic_partition, records in batch.items():
                    for record in records:
                        tasks.append(self._handle(record.value))
                if tasks:
                    await asyncio.gather(*(bounded(t) for t in tasks), return_exceptions=True)
                await self._consumer.commit()
            except asyncio.CancelledError:
                logger.info("Review consumer cancelled")
                break
            except KafkaError as exc:
                logger.error("Kafka consumer error, retrying: %s", exc)
                await asyncio.sleep(1)
            except Exception:
                logger.exception("Unexpected consumer loop error")
                await asyncio.sleep(1)

    async def _handle(self, message: dict[str, Any]) -> None:
        task_id = str(message.get("taskId") or "")
        if not task_id:
            logger.warning("Message missing taskId, skipping: %s", str(message)[:200])
            return
        session_id = message.get("sessionId") or None
        trace_id = message.get("traceId") or task_id

        if self._settings.kafka_dedup_enabled and not await self._acquire_dedup(task_id):
            logger.debug("Duplicate task skipped taskId=%s", task_id)
            return

        # 1. 进度回执：用户端 SSE 从 QUEUED → PROCESSING 由 Java 收到本回调后触发
        await self._producer.send_callback(
            "PROCESSING", task_id, session_id=session_id, trace_id=trace_id
        )

        try:
            payload = await self._payload_client.fetch(task_id)
            request = self._build_request(message, payload)
            result = await asyncio.to_thread(self._process_message, request)
            await self._producer.send_callback(
                "RESULT",
                task_id,
                session_id=session_id,
                trace_id=trace_id,
                result=self._result_to_dict(result),
            )
        except (PayloadNotFoundError, PermanentFailure) as exc:
            code = exc.code if isinstance(exc, PermanentFailure) else "PAYLOAD_NOT_FOUND"
            logger.warning(
                "Permanent failure taskId=%s code=%s: %s", task_id, code, exc
            )
            await self._producer.send_callback(
                "DEAD_LETTER",
                task_id,
                session_id=session_id,
                trace_id=trace_id,
                error_code=code,
                error_message=str(exc),
            )
        except Exception as exc:
            # 瞬时失败：进程内重试，耗尽后进 DEAD_LETTER（避免无限重投）
            logger.warning(
                "Transient failure taskId=%s, will retry: %s", task_id, exc
            )
            error_code = "TRANSIENT_FAILURE"
            error_message = str(exc)
            retries = self._settings.kafka_transient_retries
            for attempt in range(1, retries + 1):
                await asyncio.sleep(
                    self._settings.kafka_transient_backoff_ms * attempt / 1000
                )
                try:
                    payload = await self._payload_client.fetch(task_id)
                    request = self._build_request(message, payload)
                    result = await asyncio.to_thread(self._process_message, request)
                    await self._producer.send_callback(
                        "RESULT",
                        task_id,
                        session_id=session_id,
                        trace_id=trace_id,
                        result=self._result_to_dict(result),
                    )
                    return
                except (PayloadNotFoundError, PermanentFailure) as permanent:
                    error_code = (
                        permanent.code
                        if isinstance(permanent, PermanentFailure)
                        else "PAYLOAD_NOT_FOUND"
                    )
                    error_message = str(permanent)
                    break
                except Exception as retry_exc:
                    logger.warning(
                        "Transient retry %d/%d failed taskId=%s: %s",
                        attempt,
                        retries,
                        task_id,
                        retry_exc,
                    )
                    error_code = "TRANSIENT_FAILURE"
                    error_message = str(retry_exc)
            await self._producer.send_callback(
                "DEAD_LETTER",
                task_id,
                session_id=session_id,
                trace_id=trace_id,
                error_code=error_code,
                error_message=error_message,
            )

    def _build_request(self, message: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        """瘦身消息 + 回源 payload 合并为可被 parse_async_payload 解析的完整字典。"""
        merged = {
            "taskId": message.get("taskId"),
            "traceId": message.get("traceId") or message.get("taskId"),
            "sessionId": message.get("sessionId"),
            "projectId": message.get("projectId"),
            "projectName": message.get("projectName"),
            "prUrl": message.get("prUrl"),
            "diffContent": payload.get("diffContent") or "",
            "mode": message.get("mode") or "ASYNC",
            "entities": payload.get("entities"),
            "relations": payload.get("relations"),
        }
        if not merged["diffContent"]:
            raise PermanentFailure("EMPTY_DIFF", "diffContent is empty")
        return merged

    @staticmethod
    def _result_to_dict(result: Any) -> dict[str, Any]:
        return {
            "taskId": str(result.taskId),
            "status": getattr(result, "status", "SUCCEEDED"),
            "riskScore": getattr(result, "riskScore", 0),
            "riskSummary": getattr(result, "riskSummary", None),
            "needHumanReview": bool(getattr(result, "needHumanReview", False)),
            "details": list(getattr(result, "details", []) or []),
        }

    async def _acquire_dedup(self, task_id: str) -> bool:
        """Redis SETNX 去重：仅首次看到该 taskId 时返回 True。"""
        if self._redis is None:
            return True
        try:
            return bool(
                await self._redis.set(
                    f"{DEDUP_KEY_PREFIX}{task_id}",
                    "1",
                    nx=True,
                    ex=self._settings.kafka_dedup_ttl_seconds,
                )
            )
        except Exception:
            # Redis 不可用时退化为不去重（结果 upsert 天然幂等，最多重复烧 token）
            logger.warning("Redis dedup unavailable, proceeding without dedup taskId=%s", task_id)
            return True
