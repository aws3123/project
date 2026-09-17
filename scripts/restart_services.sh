#!/bin/bash
# Restart java backend and both python consumers
echo "=== start java backend ==="
cd /opt/review/backend || exit 1
: > app.log
SPRING_DATASOURCE_URL='jdbc:mysql://localhost:3306/review?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=UTC&characterEncoding=UTF-8&connectionCollation=utf8mb4_unicode_ci' \
SPRING_DATASOURCE_USERNAME=review \
SPRING_DATASOURCE_PASSWORD=reviewdb123 \
nohup java -jar app.jar >> app.log 2>&1 &
disown
echo "java started"

echo "=== start python 8000 ==="
cd /opt/review/python || exit 1
nohup env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 </dev/null >> app.log 2>&1 &
disown
echo "py-8000 started"

echo "=== start python 8001 ==="
nohup env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001 </dev/null >> app2.log 2>&1 &
disown
echo "py-8001 started"
