from __future__ import annotations

from types import SimpleNamespace

import pytest

from mq.review_consumer import (
    COMPLETED_DEDUP_VALUE,
    DEDUP_KEY_PREFIX,
    ReviewKafkaConsumer,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def eval(self, _script: str, _numkeys: int, key: str, owner: str, *args: object) -> int:
        if self.values.get(key) == "1" and len(args) == 1:
            self.values[key] = owner
            return 1
        if self.values.get(key) != owner:
            return 0
        if len(args) == 2:  # 完成态转换：completed value + TTL
            self.values[key] = str(args[0])
        return 1


def consumer(redis: FakeRedis) -> ReviewKafkaConsumer:
    settings = SimpleNamespace(
        kafka_dedup_enabled=True,
        kafka_processing_lease_seconds=15,
        kafka_dedup_ttl_seconds=86400,
    )
    instance = ReviewKafkaConsumer(
        settings=settings,
        process_message=None,
        producer=object(),
        payload_client=object(),
    )
    instance._redis = redis
    return instance


@pytest.mark.asyncio
async def test_completed_task_is_skipped_but_processing_task_is_not() -> None:
    redis = FakeRedis()
    instance = consumer(redis)

    claimed, owner = await instance._claim_processing_lease("task-1")
    assert claimed is True
    assert owner is not None

    await instance._mark_completed("task-1", owner)
    assert redis.values[f"{DEDUP_KEY_PREFIX}task-1"] == COMPLETED_DEDUP_VALUE

    claimed_again, owner_again = await instance._claim_processing_lease("task-1")
    assert claimed_again is False
    assert owner_again is None


@pytest.mark.asyncio
async def test_expired_crashed_processing_lease_can_be_reclaimed() -> None:
    redis = FakeRedis()
    instance = consumer(redis)
    key = f"{DEDUP_KEY_PREFIX}task-crashed"
    redis.values[key] = "processing:crashed-worker"

    # 模拟 Redis 租约到期；真实场景中 Kafka 会重投尚未提交的消息。
    redis.values.pop(key)
    claimed, owner = await instance._claim_processing_lease("task-crashed")

    assert claimed is True
    assert owner is not None
    assert redis.values[key] == owner


@pytest.mark.asyncio
async def test_legacy_setnx_key_is_reclaimed_after_redelivery() -> None:
    redis = FakeRedis()
    instance = consumer(redis)
    key = f"{DEDUP_KEY_PREFIX}legacy-task"
    redis.values[key] = "1"

    claimed, owner = await instance._claim_processing_lease("legacy-task")

    assert claimed is True
    assert owner is not None
    assert redis.values[key] == owner
