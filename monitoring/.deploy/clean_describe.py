#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询现有 kafka topic 分区配置，供重建保持一致性。"""
import subprocess

BOOTSTRAP = "localhost:9092"
KT = "/opt/infra/kafka/bin/kafka-topics.sh"

def sh(cmd, timeout=60):
    p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout)
    return (p.stdout + p.stderr).strip()

print("== 现有 topic 分区/副本配置 ==")
out = sh(f"{KT} --bootstrap-server {BOOTSTRAP} --describe 2>&1")
for line in out.splitlines():
    if "Topic:" in line and "PartitionCount" in line:
        print(" ", line.strip())
        print("  ReplicationFactor 行如下：")
    if "ReplicationFactor" in line and "Configs" in line and "\t" in line:
        print("   ", line.strip())