#!/usr/bin/env bash
# Test-only fault injector. Start the soak run first, then execute this script on the Docker host.
set -euo pipefail

MODE="${1:?usage: chaos_kill.sh consumer|broker}"
RESULT_FILE="${RESULT_FILE:-chaos-result.env}"
CONSUMER_SERVICE="${CONSUMER_SERVICE:-python-ai}"
BROKER_CONTAINER="${BROKER_CONTAINER:-review-kafka}"
GROUP_ID="${KAFKA_GROUP_ID:-python-review-worker}"

now_ms() { date +%s%3N; }
group_ready() {
  docker exec "$BROKER_CONTAINER" kafka-consumer-groups --bootstrap-server 127.0.0.1:29092 --describe --group "$GROUP_ID" 2>/dev/null \
    | awk 'NR>1 && $7 != "-" {ok=1} END {exit ok ? 0 : 1}'
}
wait_group() {
  local deadline=$(( $(now_ms) + ${RECOVERY_TIMEOUT_MS:-60000} ))
  until group_ready; do
    [ "$(now_ms)" -lt "$deadline" ] || return 1
    sleep 1
  done
}

started=$(now_ms)
if [ "$MODE" = "consumer" ]; then
  docker compose kill "$CONSUMER_SERVICE"
  sleep "${KILL_SECONDS:-3}"
  docker compose up -d "$CONSUMER_SERVICE"
elif [ "$MODE" = "broker" ]; then
  docker kill "$BROKER_CONTAINER"
  sleep "${KILL_SECONDS:-3}"
  docker start "$BROKER_CONTAINER"
else
  echo "MODE must be consumer or broker" >&2; exit 2
fi

wait_group
recovered=$(now_ms)
printf 'mode=%s\nkill_started_ms=%s\nconsumer_group_ready_ms=%s\nrebalance_seconds=%.3f\n' \
  "$MODE" "$started" "$recovered" "$((recovered-started))e-3" | tee "$RESULT_FILE"
