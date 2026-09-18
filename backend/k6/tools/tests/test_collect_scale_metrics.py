import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collect_scale_metrics import (
    host_normalized_cpu_summary,
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
