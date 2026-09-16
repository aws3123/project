#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""无损清理 Kafka topics：delete 后重建（含 dlq），清除存量消息与 offset。"""
import subprocess
import time

BOOTSTRAP = "localhost:9092"
KT = "/opt/infra/kafka/bin/kafka-topics.sh"
KC = "/opt/infra/kafka/bin/kafka-consumer-groups.sh"

TOPICS = [
    "ai.review.tasks",
    "ai.review.callbacks",
    "ai.feedback.events",
    "ai.review.tasks-dlq",
    "ai.review.callbacks-dlq",
    "ai.feedback.events-dlq",
]

def sh(cmd, timeout=120):
    p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout)
    return (p.stdout + p.stderr).strip()

print("== 删除 topics ==")
for t in TOPICS:
    out = sh(f"{KT} --bootstrap-server {BOOTSTRAP} --delete --topic {t} 2>&1")
    print(f"  delete {t}: {out.splitlines()[-1] if out else 'ok'}")

print("== 等待删除生效 ==")
time.sleep(3)

print("== 重建 topics (与原始一致: 1分区/1副本) ==")
for t in TOPICS:
    out = sh(f"{KT} --bootstrap-server {BOOTSTRAP} --create --topic {t} --partitions 1 --replication-factor 1 2>&1")
    print(f"  create {t}: {out.splitlines()[-1] if out else 'ok'}")

print("== 最终 topic 列表 ==")
print(sh(f"{KT} --bootstrap-server {BOOTSTRAP} --list 2>&1"))