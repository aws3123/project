#!/usr/bin/env bash
# 当前单机三Broker、双Python实例部署的测试故障注入脚本。
# 仅限测试环境；只操作一个消费者实例或一个Kafka Broker。
set -euo pipefail

MODE="${1:?usage: chaos_kill_single_host.sh consumer8000|consumer8001|broker1|broker2|broker3}"
RESULT_FILE="${RESULT_FILE:-chaos-result.env}"
KAFKA_BIN="${KAFKA_BIN:-/opt/infra/kafka/bin}"
KAFKA_CONFIG="${KAFKA_CONFIG:-/opt/infra/kafka/config}"
GROUP_ID="${KAFKA_GROUP_ID:-python-review-worker}"
EXPECTED_CONSUMERS="${EXPECTED_CONSUMERS:-2}"
BOOTSTRAP="${BOOTSTRAP_SERVER:-localhost:9092}"
KILL_SECONDS="${KILL_SECONDS:-5}"
RECOVERY_TIMEOUT_SECONDS="${RECOVERY_TIMEOUT_SECONDS:-120}"

now_ms() { date +%s%3N; }
group_ready() {
  "$KAFKA_BIN/kafka-consumer-groups.sh" --bootstrap-server "$BOOTSTRAP" \
    --describe --group "$GROUP_ID" 2>/dev/null \
    | awk -v expected="$EXPECTED_CONSUMERS" 'NR>1 && $7 != "-" {count++} END {exit count >= expected ? 0 : 1}'
}
wait_group() {
  local deadline=$(( $(now_ms) + RECOVERY_TIMEOUT_SECONDS * 1000 ))
  until group_ready; do
    [ "$(now_ms)" -lt "$deadline" ] || return 1
    sleep 1
  done
}
wait_pid() {
  local pid="$1" deadline=$(( $(now_ms) + 30000 ))
  while kill -0 "$pid" 2>/dev/null; do
    [ "$(now_ms)" -lt "$deadline" ] || return 1
    sleep 1
  done
}

started=$(now_ms)
case "$MODE" in
  consumer8000|consumer8001)
    port="${MODE#consumer}"
    pid=$(pgrep -f "uvicorn app.main:app --host 0.0.0.0 --port $port" | head -1)
    [ -n "$pid" ]
    kill -TERM "$pid"
    wait_pid "$pid"
    sleep "$KILL_SECONDS"
    cd /workspace/python
    nohup env LLM_MOCK_DELAY_SECONDS=2 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
      .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$port" \
      </dev/null >"/workspace/python/instance-$port.log" 2>&1 &
    ;;
  broker1|broker2|broker3)
    broker="${MODE#broker}"
    pid=$(pgrep -f "kafka.Kafka $KAFKA_CONFIG/server-$broker.properties" | head -1)
    [ -n "$pid" ]
    kill -TERM "$pid"
    wait_pid "$pid"
    sleep "$KILL_SECONDS"
    nohup "$KAFKA_BIN/kafka-server-start.sh" "$KAFKA_CONFIG/server-$broker.properties" \
      >/opt/infra/kafka/logs/broker-$broker-chaos.log 2>&1 &
    ;;
  *) echo "unsupported mode: $MODE" >&2; exit 2 ;;
esac

wait_group
recovered=$(now_ms)
printf 'mode=%s\nkill_started_ms=%s\nconsumer_group_ready_ms=%s\nrebalance_seconds=%.3f\n' \
  "$MODE" "$started" "$recovered" "$((recovered-started))e-3" | tee "$RESULT_FILE"
