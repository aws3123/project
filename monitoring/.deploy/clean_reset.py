#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重置消费者组 offset 到最新，并最终锁定 MessageCount=0。"""
import subprocess

BOOTSTRAP = "localhost:9092"
KC = "/opt/infra/kafka/bin/kafka-consumer-groups.sh"
KT = "/opt/infra/kafka/bin/kafka-topics.sh"

GROUPS = ["python-review-worker", "java-orchestrator-callback", "java-feedback-analyzer"]
TOPICS = ["ai.review.tasks", "ai.review.callbacks", "ai.feedback.events"]

def sh(cmd, timeout=60):
    p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout)
    return (p.stdout + p.stderr).strip()

print("== 重置消费者组 offset (to-latest) ==")
for g in GROUPS:
    ok = sh(f"{KC} --bootstrap-server {BOOTSTRAP} --group {g} --topic {','.join(TOPICS)} --reset-offsets --to-latest --execute 2>&1")
    tail = ok.splitlines()[-1] if ok else ""
    print(f"  group {g}: {tail}")

print("== 各核心 topic MessageCount/分区 (应为 0) ==")
for t in TOPICS:
    out = sh(f"{KT} --bootstrap-server {BOOTSTRAP} --describe --topic {t} 2>&1")
    for ln in out.splitlines():
        if "Partition:" in ln and "Leader:" in ln:
            print(f"  {t} -> {ln.strip()}")
            break