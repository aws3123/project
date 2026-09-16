#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确认: (1) python 当前4个 processing 任务是否属02:00后新批; (2) python 消化速率; (3) LLM 并发配额。"""
import subprocess
import re
from collections import Counter
from datetime import datetime

MYSQL = ["mysql", "-h127.0.0.1", "-P3306", "-ureview", "-previewdb123", "-N", "review"]

def q(sql):
    p = subprocess.run(MYSQL + ["-e", sql], capture_output=True, text=True)
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()] if p.returncode == 0 else ["ERR:"+p.stderr[:150]]

print("== 当前 processing/human 的任务及落库时间(是否02:00后新批) ==")
for r in q("SELECT task_id, status, DATE_FORMAT(created_at,'%m-%d %H:%i:%s') FROM review_task WHERE status IN ('processing','human_review');"):
    print("  ", r)

# python 日志里最近处理的 taskId（含 RESULT/PROCESSING 回调）
pat = re.compile(r'taskId=([a-zA-Z0-9-]+)')
recent = []
with open("/opt/review/python/app.log", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()
for ln in lines[-200:]:
    for t in pat.findall(ln):
        recent.append(t)
recent_unique = list(dict.fromkeys(recent))
print("== python 最近200行出现的 taskId(去重) 数 ==", len(recent_unique))

# 校验 python 最近的 taskId 是否都在 review_task 且创建时间
print("== 其中几个 taskId 的落库时间 ==")
for t in recent_unique[:6]:
    for r in q(f"SELECT CONCAT(task_id,' | ',status,' | ',DATE_FORMAT(created_at,'%m-%d %H:%i:%s')) FROM review_task WHERE task_id='{t}';"):
        print("  ", r)

print("== python 消化速率：日志中 RESULT 回调的 taskId 去重计数（近几个时间片） ==")
# 统计最近5分钟内 RESULT 回调数
from collections import Counter as C
result_times = []
with open("/opt/review/python/app.log", encoding="utf-8", errors="ignore") as f:
    for ln in f:
        if "Callback sent eventType=RESULT" in ln:
            m = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', ln)
            if m:
                result_times.append(m.group(1)[11:16])
cnt = C(result_times)
for k in sorted(cnt)[-8:]:
    print(f"   {k} 完成 RESULT 数: {cnt[k]}")
print("   RESULT 总数(全日志):", len(result_times))