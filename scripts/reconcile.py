#!/usr/bin/env python3
"""Reconcile k6 taskIds vs DB review_task set (run on server)."""
import json
import re
import subprocess

LOG = "/opt/review/k6/results/burst_3000_v3.log"

k6_ids = set()
with open(LOG, "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        m = re.search(r'taskId\\":\\"([^\\"]+)', line)
        if m:
            k6_ids.add(m.group(1))

out = subprocess.run(
    ["mysql", "-ureview", "-previewdb123", "review", "-N", "-e", "select task_id from review_task;"],
    capture_output=True, text=True, timeout=60,
)
db_ids = {l.strip() for l in out.stdout.splitlines() if l.strip()}

print(f"k6_unique_taskIds={len(k6_ids)}")
print(f"db_review_task={len(db_ids)}")
print(f"missing_in_db={len(k6_ids - db_ids)}")
print(f"extra_in_db={len(db_ids - k6_ids)}")
if k6_ids - db_ids:
    print("missing_sample:", list(k6_ids - db_ids)[:3])
if db_ids - k6_ids:
    print("extra_sample:", list(db_ids - k6_ids)[:3])
