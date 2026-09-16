#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最终验证：MySQL 表空 + Kafka topic LEO/MessageCount=0。"""
import subprocess

MYSQL = ["mysql", "-h127.0.0.1", "-P3306", "-ureview", "-previewdb123", "-N", "review"]
KT = "/opt/infra/kafka/bin/kafka-run-class.sh"
BOOTSTRAP = "localhost:9092"
TOPICS = ["ai.review.tasks", "ai.review.callbacks", "ai.feedback.events"]

def q(sql):
    p = subprocess.run(MYSQL + ["-e", sql], capture_output=True, text=True)
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]

def sh(cmd, timeout=90):
    p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout)
    return (p.stdout + p.stderr).strip()

print("== MySQL 表行数 ==")
for t in ["review_task", "review_result", "review_task_payload", "outbox_event", "consumed_message"]:
    print(f"   {t}:", q(f"SELECT COUNT(*) FROM {t};"))

print("== Kafka topic 末端偏移(LEO, 应为 0:0) ==")
# kafka-get-offsets 脚本
KO = "/opt/infra/kafka/bin/kafka-get-offsets.sh"
for t in TOPICS:
    out = sh(f"{KO} --bootstrap-server {BOOTSTRAP} --topic {t} 2>&1")
    tail = out.strip().splitlines()[-1] if out.strip() else "?"
    print(f"   {t}: {tail}")