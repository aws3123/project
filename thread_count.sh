#!/bin/bash
# Count threads of uvicorn processes by name
for pid in $(pgrep -f "uvicorn app.main"); do
  echo "=== PID $pid ==="
  echo "total threads: $(ls /proc/$pid/task | wc -l)"
  for t in /proc/$pid/task/*/comm; do
    cat "$t"
  done 2>/dev/null | sort | uniq -c | sort -rn | head -12
done
echo "=== total java threads ==="
for pid in $(pgrep -f "java -jar app.jar"); do
  echo "PID $pid: $(ls /proc/$pid/task | wc -l) threads"
done
