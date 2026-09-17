#!/bin/bash
# Snapshot pipeline drain state N times every INTERVAL seconds
N="${1:-8}"
INTERVAL="${2:-10}"
for i in $(seq 1 "$N"); do
  TS=$(date +%H:%M:%S)
  read -r TASK PENDING PROC SUCCESS FAILED OUT_SENT OUT_PEND RESULT < <(mysql -ureview -previewdb123 review -N -e "select (select count(*) from review_task),(select count(*) from review_task where status='pending'),(select count(*) from review_task where status='processing'),(select count(*) from review_task where status='success'),(select count(*) from review_task where status='failed'),(select count(*) from outbox_event where status='SENT'),(select count(*) from outbox_event where status='PENDING'),(select count(*) from review_result);" 2>/dev/null)
  LAG0=$(/opt/infra/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group python-review-worker 2>/dev/null | awk '$3==0{print $6}' | head -1)
  LAG1=$(/opt/infra/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group python-review-worker 2>/dev/null | awk '$3==1{print $6}' | head -1)
  echo "$TS task=$TASK pend=$PENDING proc=$PROC succ=$SUCCESS fail=$FAILED outSent=$OUT_SENT outPend=$OUT_PEND result=$RESULT lag0=$LAG0 lag1=$LAG1"
  if [ "$i" -lt "$N" ]; then sleep "$INTERVAL"; fi
done
