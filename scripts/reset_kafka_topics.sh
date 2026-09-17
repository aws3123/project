#!/bin/bash
# Reset the two pipeline Kafka topics to 2 partitions each
K=/opt/infra/kafka/bin/kafka-topics.sh
B=localhost:9092

for t in ai.review.tasks ai.review.callbacks; do
  "$K" --bootstrap-server "$B" --delete --topic "$t" >/dev/null 2>&1 || true
done

# wait until both topics are actually gone (auto-create by clients may race)
for i in $(seq 1 15); do
  gone=1
  for t in ai.review.tasks ai.review.callbacks; do
    if "$K" --bootstrap-server "$B" --list 2>/dev/null | grep -qx "$t"; then
      gone=0
    fi
  done
  if [ "$gone" -eq 1 ]; then
    break
  fi
  sleep 2
done
echo "topics_deleted=$gone"

"$K" --bootstrap-server "$B" --create --topic ai.review.tasks --partitions 2 --replication-factor 1 2>&1 | tail -1
"$K" --bootstrap-server "$B" --create --topic ai.review.callbacks --partitions 2 --replication-factor 1 2>&1 | tail -1

sleep 2
echo "--- verify ---"
"$K" --bootstrap-server "$B" --describe --topic ai.review.tasks 2>/dev/null | grep PartitionCount
"$K" --bootstrap-server "$B" --describe --topic ai.review.callbacks 2>/dev/null | grep PartitionCount
