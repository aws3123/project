#!/usr/bin/env python3
"""Publish the exact same Kafka task message repeatedly, then use verify_async_run.py for the DB assertion."""
from __future__ import annotations

import argparse
import asyncio
import json
import os

import pymysql
from aiokafka import AIOKafkaProducer


def latest_task_id(args) -> str:
    if args.task_id:
        return args.task_id
    conn = pymysql.connect(host=args.mysql_host, port=args.mysql_port, user=args.mysql_user,
                           password=args.mysql_password, database=args.mysql_database)
    with conn.cursor() as cur:
        cur.execute("SELECT task_id FROM review_task WHERE project_id=%s ORDER BY created_at DESC LIMIT 1", (f"perf-{args.run_id}",))
        row = cur.fetchone()
    conn.close()
    if not row:
        raise SystemExit("No task found for run; submit one task before duplicate injection.")
    return str(row[0])


async def publish(args, task_id: str) -> None:
    producer = AIOKafkaProducer(bootstrap_servers=args.bootstrap)
    await producer.start()
    try:
        message = {"taskId": task_id, "traceId": task_id, "mode": "ASYNC"}
        raw = json.dumps(message).encode()
        for _ in range(args.count):
            await producer.send_and_wait(args.topic, raw, key=task_id.encode())
    finally:
        await producer.stop()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--task-id")
    p.add_argument("--count", type=int, default=3)
    p.add_argument("--topic", default=os.getenv("KAFKA_REVIEW_TASKS_TOPIC", "ai.review.tasks"))
    p.add_argument("--bootstrap", default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    p.add_argument("--mysql-host", default=os.getenv("MYSQL_HOST", "127.0.0.1"))
    p.add_argument("--mysql-port", type=int, default=int(os.getenv("MYSQL_PORT", "3307")))
    p.add_argument("--mysql-user", default=os.getenv("MYSQL_USER", "review"))
    p.add_argument("--mysql-password", default=os.getenv("MYSQL_PASSWORD", "reviewdb123"))
    p.add_argument("--mysql-database", default=os.getenv("MYSQL_DATABASE", "review"))
    args = p.parse_args()
    task_id = latest_task_id(args)
    asyncio.run(publish(args, task_id))
    print(json.dumps({"taskId": task_id, "duplicateMessagesPublished": args.count}))


if __name__ == "__main__":
    main()
