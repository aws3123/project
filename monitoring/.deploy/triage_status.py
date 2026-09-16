#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""排查: 全库状态分布 + 02:00 后 outbox_event 事件 + k6批次时间窗。"""
import subprocess
from collections import Counter

MYSQL = ["mysql", "-h127.0.0.1", "-P3306", "-ureview", "-previewdb123", "-N", "review"]

def q(sql):
    p = subprocess.run(MYSQL + ["-e", sql], capture_output=True, text=True)
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()] if p.returncode == 0 else ["ERR:"+p.stderr[:120]]

print("== 全库 review_task 状态分布 ==")
for r in q("SELECT status, COUNT(*) FROM review_task GROUP BY status ORDER BY COUNT(*) DESC;"):
    print("  ", r)

print("== 02:00-03:00 落库的 task 状态分布 ==")
for r in q("SELECT status, COUNT(*) FROM review_task WHERE created_at>='2026-09-16 02:00:00' GROUP BY status ORDER BY COUNT(*) DESC;"):
    print("  ", r)

print("== outbox_event 02:00 后的状态与类型 ==")
for r in q("SELECT CONCAT(status,' | 类型') FROM outbox_event WHERE created_at>='2026-09-16 02:00:00' LIMIT 0;"):
    print(" ", r)
for r in q("SELECT status, COUNT(*) FROM outbox_event WHERE created_at>='2026-09-16 02:00:00' GROUP BY status;"):
    print("  status:", r)
for r in q("SELECT event_type, COUNT(*) FROM outbox_event WHERE created_at>='2026-09-16 02:00:00' GROUP BY event_type ORDER BY COUNT(*) DESC LIMIT 12;"):
    print("  type :", r)

print("== 02:00 落库 task 是否已有 review_result ==")
for r in q("SELECT COUNT(*) FROM review_task t JOIN review_result r ON t.task_id=r.task_id WHERE t.created_at>='2026-09-16 02:00:00';"):
    print("  有result:", r)

print("== 时间窗落库分布 ==")
for r in q("SELECT DATE_FORMAT(created_at,'%H:%i'), COUNT(*) FROM review_task WHERE created_at>='2026-09-16 01:40:00' GROUP BY DATE_FORMAT(created_at,'%H:%i') ORDER BY 1;"):
    print("  ", r)