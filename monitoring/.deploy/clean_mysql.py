#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清空 MySQL 压测业务表。"""
import subprocess

MYSQL = ["mysql", "-h127.0.0.1", "-P3306", "-ureview", "-previewdb123", "review"]

def q(sql):
    p = subprocess.run(MYSQL + ["-e", sql], capture_output=True, text=True)
    if p.returncode != 0:
        print("  ERR:", p.stderr.strip())
        return False
    return True

TABLES = ["consumed_message", "review_result", "outbox_event", "review_task_payload", "review_task"]

print("== TRUNCATE 业务表 ==")
for t in TABLES:
    ok = q(f"SET FOREIGN_KEY_CHECKS=0; TRUNCATE TABLE {t}; SET FOREIGN_KEY_CHECKS=1;")
    print(f"  {t}: {'OK' if ok else 'FAILED'}")

print("== 清理后行数 ==")
for t in TABLES:
    p = subprocess.run(MYSQL + ["-N", "-e", f"SELECT COUNT(*) FROM {t};"], capture_output=True, text=True)
    print(f"  {t}: {p.stdout.strip()}")