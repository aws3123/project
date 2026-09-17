#!/bin/bash
PID=${1:-290704}
echo "=== tools ==="
for t in py-spy gdb strace; do which $t 2>/dev/null || echo "$t MISSING"; done
ls /opt/review/python/.venv/bin/ | grep -i -E "spy|gdb" || echo "no spy in venv"
echo ""
echo "=== loaded native libs (unique) ==="
grep -E '\.so' /proc/$PID/maps | awk '{print $6}' | sort -u
echo ""
echo "=== which loaded lib contains tokio-rt-worker ==="
grep -E '\.so' /proc/$PID/maps | awk '{print $6}' | sort -u | while read -r f; do
  if [ -n "$f" ] && [ -f "$f" ]; then
    if strings "$f" 2>/dev/null | grep -q "tokio-rt-worker"; then
      echo "TOKIO: $f"
    fi
    if strings "$f" 2>/dev/null | grep -q "tokio-runtime-worker"; then
      echo "TOKIO-OLD: $f"
    fi
  fi
done
echo "=== done ==="
