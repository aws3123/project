#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 callsbacks/events 重建是否成功；如有问题补重建。"""
import subprocess
import time

BOOTSTRAP = "localhost:9092"
KT = "/opt/infra/kafka/bin/kafka-topics.sh"

def sh(cmd, timeout=60):
    p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout)
    return (p.stdout + p.stderr).strip()

print("== describe 各核心 topic ==")
for t in ["ai.review.tasks", "ai.review.callbacks", "ai.feedback.events"]:
    out = sh(f"{KT} --bootstrap-server {BOOTSTRAP} --describe --topic {t} 2>&1")
    match = [ln for ln in out.splitlines() if "Topic:" in ln]
    print(f"  {t}: {match[0] if match else 'NOT EXIST -> ' + out.splitlines()[0] if out else 'empty'}")

print("== 若无则补重建 ==")
for t in ["ai.review.callbacks", "ai.feedback.events"]:
    out = sh(f"{KT} --bootstrap-server {BOOTSTRAP} --describe --topic {t} 2>&1")
    if "Topic:" not in out:
        print(f"  recreating {t} ...")
        time.sleep(2)
        r = sh(f"{KT} --bootstrap-server {BOOTSTRAP} --create --topic {t} --partitions 1 --replication-factor 1 2>&1")
        print("  ", r.splitlines()[-1])
    else:
        print(f"  {t} 已存在，无需重建")