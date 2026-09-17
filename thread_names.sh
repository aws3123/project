#!/bin/bash
PID=${1:-290704}
echo "=== thread name distribution for PID $PID ==="
for t in /proc/$PID/task/*; do
  cat "$t/comm"
done | sort | uniq -c | sort -rn | head -25
echo ""
echo "=== total threads ==="
ls /proc/$PID/task | wc -l
