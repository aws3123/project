#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探查待清理数据与 kafka 环境。"""
import subprocess

MYSQL = ["mysql", "-h127.0.0.1", "-P3306", "-ureview", "-previewdb123", "-N", "review"]

def q(sql):
    p = subprocess.run(MYSQL + ["-e", sql], capture_output=True, text=True)
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()] if p.returncode == 0 else ["ERR:"+p.stderr[:200]]

def sh(cmd):
    p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    return (p.stdout + p.stderr).strip()

print("== 1. MySQL 各表行数(清理前) ==")
for t in ["review_task", "review_result", "review_task_payload", "outbox_event", "consumed_message"]:
    print(f"   {t}:", q(f"SELECT COUNT(*) FROM {t};") or ["ERR"])

print("== 2. status 分布 ==")
for r in q("SELECT status, COUNT(*) FROM review_task GROUP BY status;"):
    print("  ", r)

print("== 3. Kafka 环境 ==")
print("  kafka 安装目录:", sh("ls -d /opt/kafka* /opt/infra/kafka* /data/kafka* 2>/dev/null"))
print("  运行目录线索:", sh("pgrep -fal kafka | head; ls /opt/infra 2>/dev/null"))
print("  找 kafka 脚本:", sh("find /opt -maxdepth 5 -iname 'kafka-server-start.sh' -o -maxdepth 5 -iname 'kafka-topics.sh' 2>/dev/null | head"))
print("  找 docker/compose 定义:", sh("ls /opt/infra/docker-compose* /opt/infra/*.yaml /opt/infra/*.yml 2>/dev/null; find /opt -maxdepth 4 -iname 'compose*.yml' -o -maxdepth 4 -iname 'compose*.yaml' 2>/dev/null | head"))
print("  9092 监听:", sh("ss -ltn 2>/dev/null | grep 9092 || echo 'no 9092'"))