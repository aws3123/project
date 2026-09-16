#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单独处理 python-review-worker 组的 offset 重置。"""
import subprocess

BOOTSTRAP = "localhost:9092"
KC = "/opt/infra/kafka/bin/kafka-consumer-groups.sh"

def sh(cmd, timeout=60):
    p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout)
    return (p.stdout + p.stderr).strip()

print("== python-review-worker 组当前状态 ==")
print(sh(f"{KC} --bootstrap-server {BOOTSTRAP} --group python-review-worker --describe 2>&1"))

print("== 重置到 latest (全 topic) ==")
r = sh(f"{KC} --bootstrap-server {BOOTSTRAP} --group python-review-worker --reset-offsets --to-latest --all-topics --execute 2>&1")
print(r.splitlines()[-1])

print("== 复核 ==")
print(sh(f"{KC} --bootstrap-server {BOOTSTRAP} --group python-review-worker --describe 2>&1"))