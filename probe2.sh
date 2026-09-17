#!/bin/bash
SP=/opt/review/python/.venv/lib/python3.14/site-packages
echo "=== tokio strings in chromadb_rust_bindings ==="
strings $SP/chromadb_rust_bindings/chromadb_rust_bindings.abi3.so 2>/dev/null | grep -i -E "tokio|worker" | head -15
echo ""
echo "=== tokio strings in all loaded rust-ish libs ==="
for f in $SP/watchfiles/_rust_notify.cpython-314-x86_64-linux-gnu.so $SP/tiktoken/_tiktoken.cpython-314-x86_64-linux-gnu.so; do
  echo "--- $f ---"
  strings "$f" 2>/dev/null | grep -i -E "tokio" | head -5
done
echo ""
echo "=== ALL .py files creating ThreadPoolExecutor in site-packages ==="
grep -rln "ThreadPoolExecutor(" $SP --include=*.py 2>/dev/null | grep -v -E "test|benchmark|example|docs" | head -40
echo ""
echo "=== chromadb PersistentClient python source ==="
head -120 $SP/chromadb/api/client.py 2>/dev/null
