import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collect_scale_metrics import (
    host_normalized_cpu_summary,
    python_task_cpu_efficiency,
    percentile,
    parse_kafka_describe,
    summarize_samples,
)


def test_parse_kafka_describe_returns_partition_lag_rows() -> None:
    text = "group topic 0 42 50 8 consumer host client\n"
    assert parse_kafka_describe(text) == [{"topic": "topic", "partition": 0, "lag": 8}]


def test_summarize_samples_reports_average_p95_max_and_standard_deviation() -> None:
    result = summarize_samples([10.0, 20.0, 30.0, 40.0])
    assert result["average"] == 25.0
    assert result["max"] == 40.0
    assert result["p95"] == percentile([10.0, 20.0, 30.0, 40.0], 95)
    assert result["stddev"] > 0


def test_host_normalized_cpu_summary_converts_multi_core_process_percent() -> None:
    cpu = {
        "localhost:8000": {"average": 2651.64},
        "localhost:8001": {"average": 2493.36},
    }

    assert host_normalized_cpu_summary(cpu, 152) == {
        "localhost:8000": {"average": 17.445},
        "localhost:8001": {"average": 16.404},
    }


def test_python_task_cpu_efficiency_reports_cpu_cost_and_time_share() -> None:
    before = {
        "http://localhost:8000/metrics": {
            "processing_completed": 100,
            "processing_seconds_total": 500,
            "process_cpu_seconds_total": 25,
        },
        "http://localhost:8001/metrics": {
            "processing_completed": 200,
            "processing_seconds_total": 800,
            "process_cpu_seconds_total": 50,
        },
    }
    after = {
        "http://localhost:8000/metrics": {
            "processing_completed": 140,
            "processing_seconds_total": 820,
            "process_cpu_seconds_total": 41,
        },
        "http://localhost:8001/metrics": {
            "processing_completed": 260,
            "processing_seconds_total": 1280,
            "process_cpu_seconds_total": 70,
        },
    }

    result = python_task_cpu_efficiency(before, after)

    assert result["aggregate"] == {
        "completed_tasks": 100.0,
        "processing_seconds": 800.0,
        "cpu_seconds": 36.0,
        "processing_seconds_per_task": 8.0,
        "cpu_seconds_per_task": 0.36,
        "cpu_time_percent_of_processing": 4.5,
    }
    assert result["instances"]["localhost:8000"] == {
        "completed_tasks": 40.0,
        "processing_seconds": 320.0,
        "cpu_seconds": 16.0,
        "processing_seconds_per_task": 8.0,
        "cpu_seconds_per_task": 0.4,
        "cpu_time_percent_of_processing": 5.0,
    }
