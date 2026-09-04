from __future__ import annotations

import json
import logging
from typing import Any

from aiokafka import AIOKafkaProducer

from config.settings import AppSettings

logger = logging.getLogger(__name__)


class CallbackProducer:
    """Topic 2 回调生产者 —— Python 处理后回投事件给 Java 状态机。

    三类事件（靠 eventType 区分，Java 消费端据此分流）：
      PROCESSING   消费到任务、开始处理
      RESULT       处理完成（携带审查结果）
      DEAD_LETTER  永久失败 / 瞬时失败重试耗尽（携带错误码与信息）
    key 固定为 taskId，保证同一任务的三类事件落在同一分区、按序消费。
    """

    def __init__(self, settings: AppSettings | None = None) -> None:
        self._settings = settings or AppSettings()
        self._producer: AIOKafkaProducer | None = None

    def _build_producer(self) -> AIOKafkaProducer:
        kwargs: dict[str, Any] = {
            "bootstrap_servers": self._settings.kafka_bootstrap_servers,
            "value_serializer": lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            "key_serializer": lambda v: str(v).encode("utf-8"),
            "acks": "all",
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
        return AIOKafkaProducer(**kwargs)

    async def start(self) -> None:
        if self._producer is None:
            self._producer = self._build_producer()
            await self._producer.start()
            logger.info(
                "Callback producer started topic=%s",
                self._settings.kafka_review_callbacks_topic,
            )

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None
            logger.info("Callback producer stopped")

    async def send_callback(
        self,
        event_type: str,
        task_id: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if self._producer is None:
            raise RuntimeError("CallbackProducer not started")
        value: dict[str, Any] = {
            "messageId": f"{task_id}-{event_type.lower()}",
            "eventType": event_type,
            "taskId": task_id,
            "sessionId": session_id or "",
            "traceId": trace_id or task_id,
            "result": result,
            "errorCode": error_code,
            "errorMessage": error_message,
        }
        await self._producer.send_and_wait(
            self._settings.kafka_review_callbacks_topic,
            value=value,
            key=task_id,
        )
        logger.info(
            "Callback sent eventType=%s taskId=%s traceId=%s",
            event_type,
            task_id,
            trace_id,
        )
