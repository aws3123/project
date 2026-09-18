#!/usr/bin/env bash
set -euo pipefail

: "${PYTHON_ROOT:?PYTHON_ROOT is required}"
: "${K6_ROOT:?K6_ROOT is required}"
: "${PROMETHEUS_URL:?PROMETHEUS_URL is required}"
: "${KAFKA_BOOTSTRAP:?KAFKA_BOOTSTRAP is required}"
: "${KAFKA_CONSUMER_GROUP:?KAFKA_CONSUMER_GROUP is required}"
: "${PROM_TARGETS_FILE:?PROM_TARGETS_FILE is required}"
: "${PROM_RELOAD_COMMAND:?PROM_RELOAD_COMMAND is required}"

PHASE=""
DRY_RUN=false
RATES="20,30,40,50,60,80"
INSTANCE_COUNT="2"
RATE="${RATE:-20}"
DURATION="${DURATION:-30m}"
RUN_PREFIX="${RUN_PREFIX:-python-scale}"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-$K6_ROOT/artifacts}"
PYTHON_COMMAND="${PYTHON_COMMAND:-$PYTHON_ROOT/.venv/bin/uvicorn app.main:app}"
CREATED_PIDS=()

usage() { echo "Usage: $0 --phase 2inst|4inst|overhead-off|overhead-on|staircase [--instances 2|4] [--rates csv] [--dry-run]"; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase) PHASE="$2"; shift 2 ;;
    --instances) INSTANCE_COUNT="$2"; shift 2 ;;
    --rates) RATES="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) usage; exit 2 ;;
  esac
done
[[ -n "$PHASE" ]] || { usage; exit 2; }

run() {
  if "$DRY_RUN"; then printf '+ '; printf '%q ' "$@"; printf '\n'
  else "$@"; fi
}

write_prometheus_targets() {
  local ports=("$@") target_tmp
  target_tmp="${PROM_TARGETS_FILE}.tmp.$$"
  if "$DRY_RUN"; then
    echo "+ write targets ${ports[*]} -> $PROM_TARGETS_FILE; reload Prometheus"
    return
  fi
  {
    echo "- targets:"
    for port in "${ports[@]}"; do echo "    - localhost:$port"; done
    echo "  labels:"
    echo "    job: python-ai"
  } > "$target_tmp"
  mv "$target_tmp" "$PROM_TARGETS_FILE"
  bash -lc "$PROM_RELOAD_COMMAND"
}

start_python_instance() {
  local port="$1" pid_file="$2" log_file="$3"
  if "$DRY_RUN"; then echo "+ start Python instance python-$port -> $pid_file"; return; fi
  (
    cd "$PYTHON_ROOT"
    export APP_PORT="$port" PERFORMANCE_INSTANCE_ID="python-$port"
    nohup $PYTHON_COMMAND --host 0.0.0.0 --port "$port" >"$log_file" 2>&1 &
    echo $! > "$pid_file"
  )
  CREATED_PIDS+=("$pid_file")
}

stop_python_instance() {
  local pid_file="$1" pid
  [[ -f "$pid_file" ]] || return 0
  pid="$(cat "$pid_file")"
  kill -0 "$pid" 2>/dev/null || { rm -f "$pid_file"; return 0; }
  kill -TERM "$pid"
  for _ in {1..20}; do kill -0 "$pid" 2>/dev/null || { rm -f "$pid_file"; return 0; }; sleep 1; done
  kill -KILL "$pid" 2>/dev/null || true
  rm -f "$pid_file"
}

cleanup() {
  for pid_file in "${CREATED_PIDS[@]}"; do stop_python_instance "$pid_file"; done
  write_prometheus_targets 8000 8001 || true
}
trap cleanup EXIT INT TERM

duration_seconds() {
  local value="$1"
  case "$value" in
    *m) echo "$((${value%m} * 60))" ;;
    *s) echo "${value%s}" ;;
    *h) echo "$((${value%h} * 3600))" ;;
    *) echo "$value" ;;
  esac
}

run_reconciliation() {
  local output="$1"
  if [[ -z "${MYSQL_RECONCILE_COMMAND:-}" ]]; then
    printf '{"status":"not-run","reason":"MYSQL_RECONCILE_COMMAND is not set"}\n' > "$output/reconciliation.json"
  else
    bash -lc "$MYSQL_RECONCILE_COMMAND" > "$output/reconciliation.json"
  fi
}

run_load_window() {
  local run_id="$1" instances="$2"
  local output="$ARTIFACT_ROOT/$run_id"
  local started ended watcher_pid seconds
  seconds="$(duration_seconds "$DURATION")"
  mkdir -p "$output"
  run_reconciliation "$output"
  if "$DRY_RUN"; then
    echo "+ collect_scale_metrics.py watch --run-id $run_id --duration-seconds $seconds"
    echo "+ k6 run --summary-export $output/k6-summary.json scenarios/s1_decoupling.js"
    echo "+ collect_scale_metrics.py summarize --python-instances $instances"
    return
  fi
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  python3 "$K6_ROOT/tools/collect_scale_metrics.py" watch --run-id "$run_id" --output-dir "$output" --duration-seconds "$seconds" --kafka-bootstrap "$KAFKA_BOOTSTRAP" --consumer-group "$KAFKA_CONSUMER_GROUP" >"$output/collector.log" 2>&1 &
  watcher_pid=$!
  RUN_ID="$run_id" RATE="$RATE" DURATION="$DURATION" k6 run --summary-export "$output/k6-summary.json" "$K6_ROOT/scenarios/s1_decoupling.js" >"$output/k6.log" 2>&1
  ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  wait "$watcher_pid" || true
  sleep "${PROM_SCRAPE_SETTLE_SECONDS:-20}"
  python3 "$K6_ROOT/tools/collect_scale_metrics.py" summarize --run-id "$run_id" --output-dir "$output" --started-at "$started" --ended-at "$ended" --prometheus-url "$PROMETHEUS_URL" --python-instances "$instances" >"$output/summary.log" 2>&1
  run_reconciliation "$output"
}

case "$PHASE" in
  2inst|overhead-off|overhead-on)
    [[ "$PHASE" == overhead-* ]] && DURATION="${OVERHEAD_DURATION:-5m}"
    write_prometheus_targets 8000 8001
    run_load_window "$RUN_PREFIX-$PHASE-$(date -u +%Y%m%dT%H%M%SZ)" "localhost:8000,localhost:8001"
    ;;
  4inst)
    output="$ARTIFACT_ROOT/$RUN_PREFIX-4inst-bootstrap"
    mkdir -p "$output"
    start_python_instance 8002 "$output/python-8002.pid" "$output/python-8002.log"
    start_python_instance 8003 "$output/python-8003.pid" "$output/python-8003.log"
    write_prometheus_targets 8000 8001 8002 8003
    run_load_window "$RUN_PREFIX-4inst-$(date -u +%Y%m%dT%H%M%SZ)" "localhost:8000,localhost:8001,localhost:8002,localhost:8003"
    ;;
  staircase)
    IFS=',' read -r -a rate_list <<< "$RATES"
    if [[ "$INSTANCE_COUNT" == 4 ]]; then
      output="$ARTIFACT_ROOT/$RUN_PREFIX-staircase-4inst-bootstrap"
      mkdir -p "$output"
      start_python_instance 8002 "$output/python-8002.pid" "$output/python-8002.log"
      start_python_instance 8003 "$output/python-8003.pid" "$output/python-8003.log"
      write_prometheus_targets 8000 8001 8002 8003
      instances="localhost:8000,localhost:8001,localhost:8002,localhost:8003"
    else
      [[ "$INSTANCE_COUNT" == 2 ]] || { echo "--instances must be 2 or 4"; exit 2; }
      write_prometheus_targets 8000 8001
      instances="localhost:8000,localhost:8001"
    fi
    for RATE in "${rate_list[@]}"; do
      run_load_window "$RUN_PREFIX-${INSTANCE_COUNT}inst-staircase-${RATE}rps-$(date -u +%Y%m%dT%H%M%SZ)" "$instances"
    done
    ;;
  *) usage; exit 2 ;;
esac
