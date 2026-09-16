#!/usr/bin/env python3
"""Verify one k6 async run against MySQL; optionally wait until its backlog drains."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import pymysql

TERMINAL = ("success", "failed", "human_review")


def scalar(cur, sql: str, params: tuple) -> int:
    cur.execute(sql, params)
    return int(cur.fetchone()[0] or 0)


def snapshot(conn, project_id: str, expected: int) -> dict:
    with conn.cursor() as cur:
        persisted = scalar(cur, "SELECT COUNT(*) FROM review_task WHERE project_id=%s", (project_id,))
        terminal = scalar(cur, "SELECT COUNT(*) FROM review_task WHERE project_id=%s AND status IN (%s,%s,%s)", (project_id, *TERMINAL))
        failed = scalar(cur, "SELECT COUNT(*) FROM review_task WHERE project_id=%s AND status='failed'", (project_id,))
        outbox = scalar(cur, """SELECT COUNT(*) FROM outbox_event o JOIN review_task t ON t.task_id=o.aggregate_id
            WHERE t.project_id=%s AND o.aggregate_type='review_task'""", (project_id,))
        outbox_pending = scalar(cur, """SELECT COUNT(*) FROM outbox_event o JOIN review_task t ON t.task_id=o.aggregate_id
            WHERE t.project_id=%s AND o.aggregate_type='review_task' AND o.status='PENDING'""", (project_id,))
        no_outbox = scalar(cur, """SELECT COUNT(*) FROM review_task t WHERE t.project_id=%s AND NOT EXISTS
            (SELECT 1 FROM outbox_event o WHERE o.aggregate_type='review_task' AND o.aggregate_id=t.task_id)""", (project_id,))
        terminal_without_result = scalar(cur, """SELECT COUNT(*) FROM review_task t WHERE t.project_id=%s
            AND t.status IN (%s,%s,%s) AND NOT EXISTS (SELECT 1 FROM review_result r WHERE r.task_id=t.task_id)""", (project_id, *TERMINAL))
        duplicate_result_tasks = scalar(cur, """SELECT COUNT(*) FROM (SELECT task_id FROM review_result
            WHERE task_id IN (SELECT task_id FROM review_task WHERE project_id=%s) GROUP BY task_id HAVING COUNT(*) > 1) d""", (project_id,))
        cur.execute("""SELECT MIN(created_at), MAX(CASE WHEN status IN (%s,%s,%s) THEN updated_at END)
            FROM review_task WHERE project_id=%s""", (*TERMINAL, project_id))
        first_created, last_terminal = cur.fetchone()

    drain_seconds = None
    if first_created and last_terminal:
        drain_seconds = round((last_terminal - first_created).total_seconds(), 3)
    return {
        "projectId": project_id, "expected": expected, "persisted": persisted, "terminal": terminal,
        "failed": failed, "outbox": outbox, "outboxPending": outbox_pending,
        "missingPersisted": max(0, expected - persisted), "missingOutbox": no_outbox,
        "terminalWithoutResult": terminal_without_result, "duplicateResultTasks": duplicate_result_tasks,
        "outboxTerminalDiff": outbox - terminal, "drainSeconds": drain_seconds,
        "firstCreatedAt": first_created.isoformat() if first_created else None,
        "lastTerminalAt": last_terminal.isoformat() if last_terminal else None,
    }


def passed(data: dict) -> bool:
    return (data["persisted"] == data["expected"] == data["terminal"] == data["outbox"]
            and data["outboxPending"] == data["missingOutbox"] == data["terminalWithoutResult"]
            == data["duplicateResultTasks"] == 0)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True, help="RUN_ID supplied to k6; maps to project_id perf-<run-id>")
    p.add_argument("--expected", type=int, required=True)
    p.add_argument("--wait-seconds", type=int, default=0)
    p.add_argument("--poll-seconds", type=float, default=5)
    p.add_argument("--host", default=os.getenv("MYSQL_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("MYSQL_PORT", "3307")))
    p.add_argument("--user", default=os.getenv("MYSQL_USER", "review"))
    p.add_argument("--password", default=os.getenv("MYSQL_PASSWORD", "reviewdb123"))
    p.add_argument("--database", default=os.getenv("MYSQL_DATABASE", "review"))
    args = p.parse_args()
    project_id = f"perf-{args.run_id}"
    conn = pymysql.connect(host=args.host, port=args.port, user=args.user, password=args.password,
                           database=args.database, autocommit=True)
    deadline = time.monotonic() + args.wait_seconds
    while True:
        data = snapshot(conn, project_id, args.expected)
        data["verifiedAt"] = datetime.now(timezone.utc).isoformat()
        if passed(data) or time.monotonic() >= deadline:
            data["passed"] = passed(data)
            print(json.dumps(data, ensure_ascii=False))
            return 0 if data["passed"] else 1
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
