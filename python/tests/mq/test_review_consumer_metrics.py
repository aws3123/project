from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from mq.review_consumer import ReviewKafkaConsumer


class FakePayloadClient:
    async def fetch(self, _task_id: str) -> dict[str, object]:
        return {"diffContent": "diff --git a/a.py b/a.py\n+print('ok')"}


def valid_message() -> dict[str, str]:
    return {
        "taskId": str(uuid4()),
        "traceId": "trace-1",
        "sessionId": "session-1",
        "projectId": "project-1",
        "projectName": "project",
        "prUrl": "https://example.invalid/pr/1",
        "mode": "ASYNC",
    }


def make_consumer(
    producer: object,
    process_message: object,
    retries: int = 0,
) -> ReviewKafkaConsumer:
    settings = SimpleNamespace(
        kafka_dedup_enabled=False,
        kafka_transient_retries=retries,
        kafka_transient_backoff_ms=0,
        performance_instance_id="python-test",
        app_port=8000,
    )
    return ReviewKafkaConsumer(
        settings=settings,
        process_message=process_message,
        producer=producer,
        payload_client=FakePayloadClient(),
    )


@pytest.mark.asyncio
async def test_success_metric_is_observed_before_result_callback(monkeypatch) -> None:
    order: list[str] = []

    class Producer:
        async def send_callback(self, event_type: str, *_args: object, **_kwargs: object) -> None:
            if event_type == "RESULT":
                assert order == ["PROCESSING", "metric"]
            order.append(event_type)

    async def process_message(_request: object) -> object:
        return SimpleNamespace(taskId=uuid4())

    consumer = make_consumer(Producer(), process_message)
    monkeypatch.setattr(
        "mq.review_consumer.observe_task_processing",
        lambda seconds, instance, outcome: order.append("metric"),
    )

    await consumer._handle(valid_message())

    assert order == ["PROCESSING", "metric", "RESULT"]


@pytest.mark.asyncio
async def test_terminal_failure_metric_precedes_dead_letter_and_counts_retry(
    monkeypatch,
) -> None:
    order: list[str] = []

    class Producer:
        async def send_callback(self, event_type: str, *_args: object, **_kwargs: object) -> None:
            if event_type == "DEAD_LETTER":
                assert order == ["PROCESSING", "retry", "failure-metric"]
            order.append(event_type)

    async def process_message(_request: object) -> object:
        raise RuntimeError("transient failure")

    consumer = make_consumer(Producer(), process_message, retries=1)
    monkeypatch.setattr(
        "mq.review_consumer.increment_task_processing_retry",
        lambda instance: order.append("retry"),
    )
    monkeypatch.setattr(
        "mq.review_consumer.observe_task_processing",
        lambda seconds, instance, outcome: order.append(f"{outcome}-metric"),
    )

    await consumer._handle(valid_message())

    assert order == ["PROCESSING", "retry", "failure-metric", "DEAD_LETTER"]
