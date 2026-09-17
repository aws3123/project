#!/bin/bash
# Deterministic topic reset: stop all clients -> delete -> wait -> create 2 partitions
K=/opt/infra/kafka/bin/kafka-topics.sh
B=localhost:9092

echo "=== stop clients ==="
pkill -f "uvicorn app.main" ; pkill -f "java -jar app.jar" ; pkill -f "java -jar review-backend" 
sleep 5
echo "remaining java/uvicorn: $(ps aux | grep -E 'uvicorn app.main|java -jar' | grep -v grep | wc -l)"

echo "=== delete topics ==="
for t in ai.review.tasks ai.review.callbacks ai.review.tasks-dlq ai.review.callbacks-dlq; do
  "$K" --bootstrap-server "$B" --delete --topic "$t" >/dev/null 2>&1 || true
done

# wait until topics fully gone from the list
for i in $(seq 1 30); do
  gone=1
  for t in ai.review.tasks ai.review.callbacks; do
    if "$K" --bootstrap-server "$B" --list 2>/dev/null | grep -qx "$t"; then
      gone=0
    fi
  done
  if [ "$gone" -eq 1 ]; then break; fi
  sleep 2
done
echo "topics_gone=$gone after ${i} iterations"

echo "=== create 2-partition topics ==="
"$K" --bootstrap-server "$B" --create --topic ai.review.tasks --partitions 2 --replication-factor 1 2>&1 | tail -1
"$K" --bootstrap-server "$B" --create --topic ai.review.callbacks --partitions 2 --replication-factor 1 2>&1 | tail -1
"$K" --bootstrap-server "$B" --create --topic ai.review.tasks-dlq --partitions 2 --replication-factor 1 2>&1 | tail -1
"$K" --bootstrap-server "$B" --create --topic ai.review.callbacks-dlq --partitions 2 --replication-factor 1 2>&1 | tail -1

sleep 2
echo "=== verify ==="
for t in ai.review.tasks ai.review.callbacks; do
  "$K" --bootstrap-server "$B" --describe --topic "$t" 2>/dev/null | grep "Topic: $t"
done
