"""Counters used to prove duplicate delivery behaviour in Kafka resilience tests."""

from prometheus_client import Counter

KAFKA_MESSAGES_RECEIVED = Counter(
    "review_kafka_messages_received_total",
    "Kafka review-task messages received by the Python consumer",
)
KAFKA_DUPLICATES_SKIPPED = Counter(
    "review_kafka_duplicates_skipped_total",
    "Duplicate review-task messages skipped by task-id deduplication",
)
