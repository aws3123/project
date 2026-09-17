#!/bin/bash
# Race: delete topics then aggressively retry creating them with 2 partitions.
K=/opt/infra/kafka/bin/kafka-topics.sh
B=localhost:9092

for t in ai.review.tasks ai.review.callbacks; do
  "$K" --bootstrap-server "$B" --delete --topic "$t" >/dev/null 2>&1 || true
done

for i in $(seq 1 60); do
  ok=1
  for t in ai.review.tasks ai.review.callbacks; do
    out=$("$K" --bootstrap-server "$B" --create --topic "$t" --partitions 2 --replication-factor 1 2>&1)
    rc=$?
    if [ $rc -ne 0 ]; then
      ok=0
      if ! echo "$out" | grep -q "already exists"; then
        echo "create $t unexpected: $out"
      fi
    fi
  done
  if [ "$ok" -eq 1 ]; then
    echo "both topics created with 2 partitions after ${i} tries"
    break
  fi
  sleep 1
done

echo "--- verify ---"
for t in ai.review.tasks ai.review.callbacks; do
  "$K" --bootstrap-server "$B" --describe --topic "$t" 2>/dev/null | grep "Topic: $t"
done
