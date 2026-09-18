#!/usr/bin/env python3
"""Low-frequency operational collector for the Python scaling benchmark."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROM_QUERIES = {
    "python_cpu_core_percent": '100 * rate(process_cpu_seconds_total{job="python-ai"}[1m])',
    "python_processing_p99_seconds": 'histogram_quantile(0.99, sum by (le) (increase(python_review_task_processing_seconds_bucket{outcome="success"}[RUN_WINDOW])))',
    "java_heap_used_bytes": 'jvm_memory_used_bytes{area="heap"}',
    "java_heap_max_bytes": 'jvm_memory_max_bytes{area="heap"}',
    "java_rss_bytes": 'process_resident_memory_bytes{job="java-backend"}',
    "java_cpu_ratio": 'process_cpu_usage{job="java-backend"}',
    "java_gc_pause_seconds_sum": "jvm_gc_pause_seconds_sum",
    "java_gc_pause_seconds_count": "jvm_gc_pause_seconds_count",
    "hikari_active": "hikaricp_connections_active",
    "outbox_pending": "review_outbox_pending",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_prometheus_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=15) as response:
        return response.read().decode("utf-8")


def metric_counter(text: str, name: str) -> float:
    prefix = name + " "
    return sum(
        float(line[len(prefix):].split()[0])
        for line in text.splitlines()
        if line.startswith(prefix)
    )


def write_python_snapshot(output: Path, urls: list[str], label: str) -> None:
    snapshot = {}
    for url in urls:
        text = fetch_prometheus_text(url)
        snapshot[url] = {
            "processing_completed": metric_counter(text, "python_review_task_processing_seconds_count"),
            "kafka_received": metric_counter(text, "review_kafka_messages_received_total"),
        }
    (output / f"python-metrics-{label}.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")


def parse_timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize_samples(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"average": None, "p95": None, "max": None, "stddev": None}
    average = sum(values) / len(values)
    return {
        "average": average,
        "p95": percentile(values, 95),
        "max": max(values),
        "stddev": math.sqrt(sum((value - average) ** 2 for value in values) / len(values)),
    }


def average_sample(values: list[float]) -> dict[str, float | None]:
    return {"average": sum(values) / len(values) if values else None}


def parse_kafka_describe(text: str) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    for raw in text.splitlines():
        columns = raw.split()
        if len(columns) < 6 or not columns[2].isdigit() or not columns[5].isdigit():
            continue
        rows.append({"topic": columns[1], "partition": int(columns[2]), "lag": int(columns[5])})
    return rows


def run_kafka_describe(bootstrap: str, group: str) -> tuple[list[dict[str, int | str]], str | None]:
    kafka_command = os.environ.get(
        "KAFKA_CONSUMER_GROUPS_COMMAND",
        "/opt/infra/kafka/bin/kafka-consumer-groups.sh",
    )
    command = [
        "nice", "-n", "19", "ionice", "-c3", kafka_command,
        "--bootstrap-server", bootstrap, "--describe", "--group", group,
    ]
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=25, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], str(exc)
    if completed.returncode:
        return [], completed.stderr.strip() or f"kafka command exited {completed.returncode}"
    return parse_kafka_describe(completed.stdout), None


def watch(args: argparse.Namespace) -> None:
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "kafka-lag.csv"
    error_path = output / "kafka-watch-errors.jsonl"
    deadline = time.monotonic() + args.duration_seconds
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("timestamp", "topic", "partition", "lag"))
        writer.writeheader()
        while True:
            timestamp = utc_now()
            rows, error = run_kafka_describe(args.kafka_bootstrap, args.consumer_group)
            if error:
                with error_path.open("a", encoding="utf-8") as errors:
                    errors.write(json.dumps({"timestamp": timestamp, "error": error}) + "\n")
            for row in rows:
                writer.writerow({"timestamp": timestamp, **row})
            handle.flush()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(args.interval_seconds, remaining))


def prom_query_range(url: str, query: str, start: float, end: float, step: int) -> dict[str, Any]:
    params = urllib.parse.urlencode({"query": query, "start": start, "end": end, "step": step})
    request = urllib.request.Request(f"{url.rstrip('/')}/api/v1/query_range?{params}")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def series_values(response: dict[str, Any]) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for item in response.get("data", {}).get("result", []):
        labels = item.get("metric", {})
        key = labels.get("instance", "aggregate")
        result.setdefault(key, []).extend(
            float(value)
            for _timestamp, value in item.get("values", [])
            if math.isfinite(float(value))
        )
    return result


def kafka_summary(csv_path: Path) -> dict[str, Any]:
    if not csv_path.exists():
        return {"complete": False, "error": "kafka-lag.csv missing"}
    per_topic: dict[str, list[tuple[float, int]]] = {}
    with csv_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            per_topic.setdefault(row["topic"], []).append((parse_timestamp(row["timestamp"]), int(row["lag"])))
    result: dict[str, Any] = {"complete": True}
    for topic, samples in per_topic.items():
        totals: dict[float, int] = {}
        for timestamp, lag in samples:
            totals[timestamp] = totals.get(timestamp, 0) + lag
        points = sorted(totals.items())
        first = points[0][0] if points else None
        first_zero = next((timestamp for timestamp, lag in points if lag == 0), None)
        result[topic] = {
            "max_lag": max((lag for _timestamp, lag in points), default=None),
            "p95_lag": percentile([lag for _timestamp, lag in points], 95),
            "final_lag": points[-1][1] if points else None,
            "drain_seconds": first_zero - first if first and first_zero else None,
        }
    return result


def summarize(args: argparse.Namespace) -> None:
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    start, end = parse_timestamp(args.started_at), parse_timestamp(args.ended_at)
    window = max(1, round(end - start))
    raw: dict[str, Any] = {}
    summary: dict[str, Any] = {"run_id": args.run_id, "started_at": args.started_at, "ended_at": args.ended_at}
    if args.baseline_dir and args.load_ended_at and args.load_started_at:
        before_path = Path(args.baseline_dir) / "python-metrics-before.json"
        after_path = Path(args.baseline_dir) / "python-metrics-after.json"
        if before_path.exists() and after_path.exists():
            before = json.loads(before_path.read_text(encoding="utf-8"))
            after = json.loads(after_path.read_text(encoding="utf-8"))
            elapsed = max(0.001, parse_timestamp(args.load_ended_at) - parse_timestamp(args.load_started_at))
            completed = sum(after[url]["processing_completed"] - before.get(url, {}).get("processing_completed", 0) for url in after)
            received = sum(after[url]["kafka_received"] - before.get(url, {}).get("kafka_received", 0) for url in after)
            summary["throughput"] = {
                "window_seconds": elapsed,
                "python_processing_completed": completed,
                "python_processing_throughput_rps": completed / elapsed,
                "kafka_messages_received": received,
                "kafka_consume_throughput_rps": received / elapsed,
            }
    for name, template in PROM_QUERIES.items():
        query_window = max(window, 300) if name == "python_processing_p99_seconds" else window
        query = template.replace("RUN_WINDOW", f"{query_window}s")
        try:
            response = prom_query_range(args.prometheus_url, query, start, end, args.prometheus_step_seconds)
            raw[name] = {"query": query, "response": response}
            values = series_values(response)
            summary[name] = {
                instance: (
                    average_sample(series)
                    if name == "python_cpu_core_percent"
                    else summarize_samples(series)
                )
                for instance, series in values.items()
            }
        except Exception as exc:  # Keep partial evidence and make absence explicit.
            raw[name] = {"query": query, "error": str(exc)}
            summary[name] = {"error": str(exc)}
    cpu = summary.get("python_cpu_core_percent", {})
    host_cpus = os.environ.get("HOST_LOGICAL_CPUS")
    if host_cpus and isinstance(cpu, dict):
        cores = float(host_cpus)
        summary["python_cpu_host_normalized_percent"] = {
            instance: {
                "average": (
                    stats["average"] / cores
                    if stats.get("average") is not None
                    else None
                )
            }
            for instance, stats in cpu.items() if isinstance(stats, dict)
        }
    summary["kafka"] = kafka_summary(output / "kafka-lag.csv")
    (output / "prometheus-raw.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    (output / "metrics-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    watcher = commands.add_parser("watch")
    watcher.add_argument("--run-id", required=True)
    watcher.add_argument("--output-dir", required=True)
    watcher.add_argument("--duration-seconds", type=int, required=True)
    watcher.add_argument("--kafka-bootstrap", required=True)
    watcher.add_argument("--consumer-group", required=True)
    watcher.add_argument("--interval-seconds", type=int, default=30)
    watcher.set_defaults(func=watch)
    report = commands.add_parser("summarize")
    report.add_argument("--run-id", required=True)
    report.add_argument("--output-dir", required=True)
    report.add_argument("--started-at", required=True)
    report.add_argument("--ended-at", required=True)
    report.add_argument("--load-started-at", default=None)
    report.add_argument("--load-ended-at", default=None)
    report.add_argument("--baseline-dir", default=None)
    report.add_argument("--prometheus-url", required=True)
    report.add_argument("--python-instances", required=True)
    report.add_argument("--prometheus-step-seconds", type=int, default=15)
    report.set_defaults(func=summarize)
    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("--output-dir", required=True)
    snapshot.add_argument("--label", required=True)
    snapshot.add_argument("--python-metrics-url", required=True)
    snapshot.set_defaults(func=lambda parsed: write_python_snapshot(Path(parsed.output_dir), parsed.python_metrics_url.split(","), parsed.label))
    return parser


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    parsed.func(parsed)
