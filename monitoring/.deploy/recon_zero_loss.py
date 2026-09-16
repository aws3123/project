#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零丢失对账（无第三方依赖）：k6 提交 taskId vs review_task DB，用 subprocess 调 mysql 客户端。"""
import re
import subprocess
from collections import Counter

LOG = "/opt/review/k6/run_burst_pool200.log"
MYSQL = ["mysql", "-h127.0.0.1", "-P3306", "-ureview", "-previewdb123", "-N", "review"]

def q(sql):
    p = subprocess.run(MYSQL + ["-e", sql], capture_output=True, text=True)
    if p.returncode != 0:
        return []
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]

# 1) 提取 taskId（处理 JSON 转义 \" ）
pat = re.compile(r'taskId\\":\\"([a-zA-Z0-9-]+)\\"')
ids = []
with open(LOG, encoding="utf-8", errors="ignore") as f:
    for line in f:
        ids.extend(pat.findall(line))
unique = list(dict.fromkeys(ids))
print("1) k6 提交次数(含重试):", len(ids))
print("1) k6 去重 taskId:", len(unique))

print("2) review_task 总行数:", q("SELECT COUNT(*) FROM review_task;") or ["ERR"])
print("   review_task task_id 重复组:", q("SELECT COUNT(*) FROM (SELECT task_id FROM review_task GROUP BY task_id HAVING COUNT(*)>1) t;") or ["ERR"])
print("   review_result task_id 重复组:", q("SELECT COUNT(*) FROM (SELECT task_id FROM review_result GROUP BY task_id HAVING COUNT(*)>1) t;") or ["ERR"])

# 3-5) 用永久表装载 k6 ids（跨会话），对账后删除
TBL = "k6_recon"
q(f"DROP TABLE IF EXISTS {TBL};")
q(f"CREATE TABLE {TBL}(task_id VARCHAR(128) PRIMARY KEY);")
for tid in unique:
    q(f"INSERT IGNORE INTO {TBL} VALUES('{tid}');")
q(f"DELETE FROM {TBL} WHERE task_id='';")
print("   k6_recon 装载行数:", q(f"SELECT COUNT(*) FROM {TBL};") or ["ERR"])

print("3) k6 提交但 DB 缺失(missing_in_db):",
      q(f"SELECT COUNT(*) FROM {TBL} k LEFT JOIN review_task t ON k.task_id=t.task_id WHERE t.task_id IS NULL;") or ["ERR"])
print("   DB 中不在 k6 批次(本次之外):",
      q(f"SELECT COUNT(*) FROM review_task t LEFT JOIN {TBL} k ON t.task_id=k.task_id WHERE k.task_id IS NULL;") or ["ERR"])

print("4) 本次 3000 批终态分布:")
for row in q(f"SELECT t.status, COUNT(*) c FROM {TBL} k JOIN review_task t ON k.task_id=t.task_id GROUP BY t.status ORDER BY c DESC;"):
    print("   ", row)
print("   NOT-at-terminal:", q(f"SELECT COUNT(*) FROM {TBL} k JOIN review_task t ON k.task_id=t.task_id WHERE t.status NOT IN ('SUCCESS','HUMAN_REVIEW','FAILED');") or ["ERR"])

miss = q(f"SELECT k.task_id FROM {TBL} k LEFT JOIN review_task t ON k.task_id=t.task_id WHERE t.task_id IS NULL;")
print("5) 缺失明细(taskId):", miss if miss else "无")
q(f"DROP TABLE IF EXISTS {TBL};")