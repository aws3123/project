#!/usr/bin/env python3
"""Samples Prometheus during soak tests and reports DLQ delta, memory growth and async P99 jitter."""
from __future__ import annotations

import argparse
import json
import statistics
import time
from urllib.parse import urlencode
from urllib.request import urlopen

DEFAULTS = {
    "memory": 'sum(process_resident_memory_bytes{job="python-ai"})',
    "p99": 'histogram_quantile(0.99,sum by (le) (rate(review_async_latency_seconds_bucket[5m])))',
    "dlq": 'sum(kafka_topic_partition_current_offset{topic=~".*-dlq"}) or vector(0)',
}


def query(base: str, expression: str) -> float:
    with urlopen(f"{base.rstrip('/')}/api/v1/query?{urlencode({'query': expression})}", timeout=10) as r:
        data = json.load(r)
    values = data.get("data", {}).get("result", [])
    return sum(float(v["value"][1]) for v in values) if values else 0.0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--prometheus", default="http://localhost:9090")
    p.add_argument("--duration-seconds", type=int, required=True)
    p.add_argument("--interval-seconds", type=int, default=15)
    p.add_argument("--memory-query", default=DEFAULTS["memory"])
    p.add_argument("--p99-query", default=DEFAULTS["p99"])
    p.add_argument("--dlq-query", default=DEFAULTS["dlq"])
    args = p.parse_args()
    samples = []
    until = time.monotonic() + args.duration_seconds
    while True:
        samples.append({"at": time.time(), "memory": query(args.prometheus, args.memory_query),
                        "p99": query(args.prometheus, args.p99_query), "dlq": query(args.prometheus, args.dlq_query)})
        if time.monotonic() >= until:
            break
        time.sleep(min(args.interval_seconds, max(0, until - time.monotonic())))
    memory = [x["memory"] for x in samples]
    p99 = [x["p99"] for x in samples if x["p99"] > 0]
    result = {"samples": len(samples), "dlqDelta": samples[-1]["dlq"] - samples[0]["dlq"],
              "memoryGrowthBytes": memory[-1] - memory[0],
              "memoryMinBytes": min(memory), "memoryMaxBytes": max(memory),
              "p99JitterRatio": ((max(p99) - min(p99)) / statistics.mean(p99)) if p99 else None}
    print(json.dumps(result))
    return 0 if result["dlqDelta"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
