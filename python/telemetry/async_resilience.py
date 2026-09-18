"""Prometheus metrics used by Kafka resilience and scaling benchmarks."""

from prometheus_client import Counter, Histogram

KAFKA_MESSAGES_RECEIVED = Counter(
    "review_kafka_messages_received_total",
    "Kafka review-task messages received by the Python consumer",
)
KAFKA_DUPLICATES_SKIPPED = Counter(
    "review_kafka_duplicates_skipped_total",
    "Duplicate review-task messages skipped by task-id deduplication",
)

PYTHON_TASK_PROCESSING_SECONDS = Histogram(
    "python_review_task_processing_seconds",
    "Time from a successful PROCESSING callback to local terminal processing.",
    labelnames=("instance", "outcome"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 20, 30, 60, 120),
)
PYTHON_TASK_PROCESSING_RETRIES = Counter(
    "python_review_task_processing_retries",
    "Transient processing retries attempted by Python consumers.",
    labelnames=("instance",),
)


def task_processing_instance_id(settings: object) -> str:
    """Return a stable, low-cardinality metric label for one worker process."""
    explicit = getattr(settings, "performance_instance_id", "")
    if explicit:
        return str(explicit)
    return f"python-{getattr(settings, 'app_port', 8000)}"


def observe_task_processing(seconds: float, instance: str, outcome: str) -> None:
    """Observe one local task outcome without task-level metric labels."""
    PYTHON_TASK_PROCESSING_SECONDS.labels(
        instance=instance, outcome=outcome
    ).observe(seconds)


def increment_task_processing_retry(instance: str) -> None:
    """Count one scheduled in-process transient retry."""
    PYTHON_TASK_PROCESSING_RETRIES.labels(instance=instance).inc()
