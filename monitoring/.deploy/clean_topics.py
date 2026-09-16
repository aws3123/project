#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列出 kafka topics。"""
import subprocess

def sh(cmd):
    p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    return (p.stdout + p.stderr).strip()

print("== kafka topics ==")
print(sh("/opt/infra/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list 2>&1"))
print("== consumer groups ==")
print(sh("/opt/infra/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list 2>&1"))