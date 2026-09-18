from prometheus_client import REGISTRY

from telemetry.async_resilience import (
    increment_task_processing_retry,
    observe_task_processing,
    task_processing_instance_id,
)


class Settings:
    performance_instance_id = "python-8000"
    app_port = 8000


def test_processing_metrics_use_only_instance_and_outcome_labels() -> None:
    assert task_processing_instance_id(Settings()) == "python-8000"
    labels = {"instance": "python-test", "outcome": "success"}
    before = REGISTRY.get_sample_value(
        "python_review_task_processing_seconds_count", labels
    ) or 0

    observe_task_processing(0.25, **labels)

    after = REGISTRY.get_sample_value(
        "python_review_task_processing_seconds_count", labels
    )
    assert after == before + 1


def test_retry_counter_increments_per_instance() -> None:
    labels = {"instance": "python-test"}
    before = REGISTRY.get_sample_value(
        "python_review_task_processing_retries_total", labels
    ) or 0

    increment_task_processing_retry("python-test")

    after = REGISTRY.get_sample_value(
        "python_review_task_processing_retries_total", labels
    )
    assert after == before + 1
