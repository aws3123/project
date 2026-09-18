# Python Scale Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Build reproducible 2-to-4 Python-instance benchmark instrumentation that reports BFF admission performance, Python-only processing P99, per-instance CPU, Kafka/Outbox health, Java resource health, and separately-derived sustainable-capacity scaling.

**Architecture:** Python emits a low-cardinality Histogram after \`PROCESSING\` succeeds and before a final callback is sent. k6 measures only HTTP admission; a separate collector samples operational metrics at low frequency and calculates percentiles after the run. A server-side orchestrator coordinates comparable 2- and 4-instance runs and preserves raw artifacts.

**Tech Stack:** Python 3 with \`prometheus_client\` and \`pytest\`; k6 JavaScript; Prometheus HTTP API; Kafka CLI; MySQL CLI; POSIX shell.

**Spec:** \`docs/superpowers/specs/2026-09-18-python-scale-observability-design.md\`

## Global Constraints

- Python processing timing starts only after the \`PROCESSING\` callback succeeds and stops before \`RESULT\` or \`DEAD_LETTER\` is sent.
- Histogram labels are exactly \`instance\` and \`outcome\`; task ID, project ID, and RunID must never be metric labels.
- k6 sends only business HTTP traffic and never queries Prometheus, Kafka, or MySQL.
- Prometheus polling is 15 seconds; Kafka CLI fallback sampling is 30 seconds and runs at low CPU/I/O priority.
- MySQL reconciliation runs only before and after each test window, never during the load window.
- Fixed 20 req/s runs compare stability only; the 2-to-4 multiplier comes only from the separate capacity staircase.
- Artifacts retain raw k6 JSON, Prometheus query output, Kafka samples, and RunID-scoped reconciliation.
- Scripts must not contain database passwords or SSH credentials.

---

## File structure

- \`python/telemetry/async_resilience.py\` — task-processing Histogram/Counter helpers.
- \`python/config/settings.py\` — optional fixed per-process metric instance ID.
- \`python/mq/review_consumer.py\` — one Python-only duration and retry count per terminal consumer outcome.
- \`python/tests/telemetry/test_async_resilience.py\` — telemetry label/observation tests.
- \`python/tests/mq/test_review_consumer_metrics.py\` — timing boundary tests.
- \`backend/k6/scenarios/s1_decoupling.js\` — new standalone 202-admission k6 scenario.
- \`backend/k6/tools/collect_scale_metrics.py\` — watcher and offline summary tool.
- \`backend/k6/tools/tests/test_collect_scale_metrics.py\` — collector tests.
- \`backend/k6/tools/run_scale_benchmark.sh\` — parameterized server runner.
- \`backend/k6/tools/python-ai-targets.yml\` — Prometheus file-SD target template.
- \`backend/k6/README_DECOUPLING.md\` — execution and evidence guide.

### Task 1: Define Python processing telemetry

**Files:**
- Modify: \`python/telemetry/async_resilience.py\`
- Modify: \`python/config/settings.py\`
- Create: \`python/tests/telemetry/test_async_resilience.py\`

**Interfaces:**
- Produces: \`task_processing_instance_id(settings: object) -> str\`.
- Produces: \`observe_task_processing(seconds: float, instance: str, outcome: str) -> None\`.
- Produces: \`increment_task_processing_retry(instance: str) -> None\`.

- [ ] **Step 1: Write the failing metric tests**

\`\`\`python
from prometheus_client import REGISTRY
from telemetry.async_resilience import (
    increment_task_processing_retry,
    observe_task_processing,
    task_processing_instance_id,
)

class Settings:
    performance_instance_id = "python-8000"
    app_port = 8000

def test_processing_metrics_use_only_instance_and_outcome_labels():
    assert task_processing_instance_id(Settings()) == "python-8000"
    labels = {"instance": "python-test", "outcome": "success"}
    before = REGISTRY.get_sample_value(
        "python_review_task_processing_seconds_count", labels
    ) or 0
    observe_task_processing(0.25, **labels)
    after = REGISTRY.get_sample_value(
        "python_review_task_processing_seconds_count", labels
    )
    assert after == before + 1

def test_retry_counter_increments_per_instance():
    labels = {"instance": "python-test"}
    before = REGISTRY.get_sample_value(
        "python_review_task_processing_retries_total", labels
    ) or 0
    increment_task_processing_retry("python-test")
    after = REGISTRY.get_sample_value(
        "python_review_task_processing_retries_total", labels
    )
    assert after == before + 1
\`\`\`

- [ ] **Step 2: Run the test to verify it fails**

Run: \`python -m pytest python/tests/telemetry/test_async_resilience.py -v\`

Expected: FAIL because the telemetry helpers and metric families do not exist.

- [ ] **Step 3: Add the setting and metric helpers**

Add this optional setting near runtime/telemetry settings in \`python/config/settings.py\`:

\`\`\`python
performance_instance_id: str = ""
\`\`\`

Add these definitions to \`python/telemetry/async_resilience.py\`:

\`\`\`python
from prometheus_client import Counter, Histogram

PYTHON_TASK_PROCESSING_SECONDS = Histogram(
    "python_review_task_processing_seconds",
    "Time from successful PROCESSING callback to local terminal processing result.",
    labelnames=("instance", "outcome"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 20, 30, 60, 120),
)
PYTHON_TASK_PROCESSING_RETRIES = Counter(
    "python_review_task_processing_retries",
    "Transient processing retries attempted by Python consumers.",
    labelnames=("instance",),
)

def task_processing_instance_id(settings: object) -> str:
    explicit = getattr(settings, "performance_instance_id", "")
    return str(explicit) if explicit else f"python-{getattr(settings, 'app_port', 8000)}"

def observe_task_processing(seconds: float, instance: str, outcome: str) -> None:
    PYTHON_TASK_PROCESSING_SECONDS.labels(instance=instance, outcome=outcome).observe(seconds)

def increment_task_processing_retry(instance: str) -> None:
    PYTHON_TASK_PROCESSING_RETRIES.labels(instance=instance).inc()
\`\`\`

- [ ] **Step 4: Run focused telemetry tests**

Run: \`python -m pytest python/tests/telemetry/test_async_resilience.py -v\`

Expected: PASS; count and retry samples increase exactly once.

- [ ] **Step 5: Commit**

\`\`\`bash
git add python/telemetry/async_resilience.py python/config/settings.py python/tests/telemetry/test_async_resilience.py
git commit -m "feat: expose Python task processing metrics"
\`\`\`

### Task 2: Instrument the Kafka consumer boundary

**Files:**
- Modify: \`python/mq/review_consumer.py\`
- Create: \`python/tests/mq/test_review_consumer_metrics.py\`

**Interfaces:**
- Consumes: Task 1 telemetry helpers.
- Produces: exactly one duration observation for every success or terminal failure handled by \`ReviewKafkaConsumer._handle\`.

- [ ] **Step 1: Write the failing callback-order test**

\`\`\`python
@pytest.mark.asyncio
async def test_success_metric_is_observed_before_result_callback(monkeypatch):
    order = []

    async def send_callback(event_type, **_kwargs):
        if event_type == "RESULT":
            assert order == ["metric"]
        order.append(event_type)

    consumer = make_consumer(
        producer=SimpleNamespace(send_callback=send_callback),
        settings=SimpleNamespace(
            kafka_dedup_enabled=False,
            kafka_transient_retries=0,
            performance_instance_id="python-test",
            app_port=8000,
        ),
    )
    monkeypatch.setattr(
        "mq.review_consumer.observe_task_processing",
        lambda seconds, instance, outcome: order.append("metric"),
    )
    await consumer._handle(valid_message())
    assert order == ["PROCESSING", "metric", "RESULT"]
\`\`\`

The fixture provides immediate fake payload/process services, and \`valid_message()\` includes the fields read by \`_build_request\`.

- [ ] **Step 2: Run the test to verify it fails**

Run: \`python -m pytest python/tests/mq/test_review_consumer_metrics.py::test_success_metric_is_observed_before_result_callback -v\`

Expected: FAIL because the metric is not emitted between \`PROCESSING\` and \`RESULT\`.

- [ ] **Step 3: Add terminal timing and retry instrumentation**

Import \`perf_counter\` and the Task 1 helpers. In \`_handle\`, set \`instance = task_processing_instance_id(self._settings)\` and set \`processing_started = perf_counter()\` immediately after this succeeds:

\`\`\`python
await self._producer.send_callback("PROCESSING", task_id=task_id, ...)
processing_started = perf_counter()
\`\`\`

Immediately after \`_process_message()\` returns, before composing or sending \`RESULT\`, record:

\`\`\`python
observe_task_processing(
    perf_counter() - processing_started,
    instance=instance,
    outcome="success",
)
\`\`\`

Call \`increment_task_processing_retry(instance)\` once for each scheduled transient retry. Immediately before a final \`DEAD_LETTER\` callback, record \`outcome="failure"\` when the timer exists. Do not record a timing if \`PROCESSING\` itself fails, and do not record after either final callback.

- [ ] **Step 4: Add and run retry/failure assertions**

Extend the test with a retrying fake service. Assert the retry helper is called once and a failure observation occurs before \`DEAD_LETTER\`.

Run: \`python -m pytest python/tests/mq/test_review_consumer_metrics.py python/tests/mq/test_review_consumer_dedup.py -v\`

Expected: PASS, including existing deduplication tests.

- [ ] **Step 5: Commit**

\`\`\`bash
git add python/mq/review_consumer.py python/tests/mq/test_review_consumer_metrics.py
git commit -m "feat: record Python-only consumer processing latency"
\`\`\`

### Task 3: Create the isolated k6 admission scenario

**Files:**
- Create: \`backend/k6/scenarios/s1_decoupling.js\`
- Modify: \`backend/k6/README_DECOUPLING.md\`

**Interfaces:**
- Consumes: \`BASE_URL\`, \`RATE\`, \`DURATION\`, \`PRE_ALLOCATED_VUS\`, \`MAX_VUS\`, \`RUN_ID\`, \`FAIL_P95_MS\`, \`DIFF_SIZE\`.
- Produces: \`decoupling_acceptance_latency_ms\`, \`decoupling_admissions_accepted\`, \`decoupling_admissions_rejected\`, checks, and \`--summary-export\` JSON.

- [ ] **Step 1: Implement the scenario**

Create \`backend/k6/scenarios/s1_decoupling.js\` using \`constant-arrival-rate\`, defaulting to 20 iterations/s for 30 minutes. Use \`makeAsyncPayload\` from \`../config.js\`; POST the current async endpoint; make a success check that requires HTTP 202 and a task ID.

Use these metrics and thresholds:

\`\`\`javascript
const admissionLatency = new Trend('decoupling_acceptance_latency_ms');
const accepted = new Counter('decoupling_admissions_accepted');
const rejected = new Counter('decoupling_admissions_rejected');

thresholds: {
  http_req_failed: ['rate<0.01'],
  decoupling_acceptance_latency_ms: [\`p(95)<\${Number(__ENV.FAIL_P95_MS || 1000)}\`],
  dropped_iterations: ['count==0'],
}
\`\`\`

Record only \`response.timings.duration\`. Do not import a Prometheus client, run shell commands, or access MySQL.

- [ ] **Step 2: Validate parsing and a test-only smoke run**

Run:

\`\`\`bash
k6 inspect backend/k6/scenarios/s1_decoupling.js
$env:RATE=1; $env:DURATION='5s'; $env:RUN_ID='local-smoke'; k6 run --summary-export backend/k6/results/local-smoke-summary.json backend/k6/scenarios/s1_decoupling.js
\`\`\`

Expected: \`k6 inspect\` shows the constant-arrival-rate executor and the summary JSON includes \`decoupling_acceptance_latency_ms\`. The smoke target is explicitly local/test-only, never the shared server.

- [ ] **Step 3: Rewrite the decoupling README**

Remove references to the deleted legacy sampler. Document the new scenario, raw summary output, the timing boundaries, environment variables, and the fact that 20 req/s cannot prove a scaling multiplier.

- [ ] **Step 4: Commit**

\`\`\`bash
git add backend/k6/scenarios/s1_decoupling.js backend/k6/README_DECOUPLING.md
git commit -m "feat: add isolated decoupling admission scenario"
\`\`\`

### Task 4: Implement low-frequency metric collection and offline calculations

**Files:**
- Create: \`backend/k6/tools/collect_scale_metrics.py\`
- Create: \`backend/k6/tools/tests/test_collect_scale_metrics.py\`

**Interfaces:**
- Produces: \`watch --run-id RUN_ID --output-dir DIR --duration-seconds N --kafka-bootstrap HOST:PORT --consumer-group GROUP\`.
- Produces: \`summarize --run-id RUN_ID --output-dir DIR --started-at ISO8601 --ended-at ISO8601 --prometheus-url URL --python-instances INSTANCE[,INSTANCE...]\`.
- Produces: \`kafka-lag.csv\`, \`prometheus-raw.json\`, and \`metrics-summary.json\`.

- [ ] **Step 1: Write failing parser/statistics tests**

\`\`\`python
from collect_scale_metrics import percentile, parse_kafka_describe, summarize_samples

def test_parse_kafka_describe_returns_partition_lag_rows():
    text = "group topic 0 42 50 8 consumer host client\\n"
    assert parse_kafka_describe(text) == [{"topic": "topic", "partition": 0, "lag": 8}]

def test_summarize_samples_reports_average_p95_max_and_standard_deviation():
    result = summarize_samples([10.0, 20.0, 30.0, 40.0])
    assert result["average"] == 25.0
    assert result["max"] == 40.0
    assert result["p95"] == percentile([10.0, 20.0, 30.0, 40.0], 95)
    assert result["stddev"] > 0
\`\`\`

- [ ] **Step 2: Run tests to verify they fail**

Run: \`python -m pytest backend/k6/tools/tests/test_collect_scale_metrics.py -v\`

Expected: FAIL because the collector module does not exist.

- [ ] **Step 3: Implement low-interference watcher**

Implement \`watch\` with only the standard library. Every 30 seconds invoke this static command through \`subprocess.run\` with a timeout, then append UTC timestamp/topic/partition/lag rows to \`kafka-lag.csv\`:

\`\`\`bash
nice -n 19 ionice -c3 kafka-consumer-groups.sh --bootstrap-server "$KAFKA_BOOTSTRAP" --describe --group "$CONSUMER_GROUP"
\`\`\`

Never invoke MySQL in \`watch\`. Record Kafka CLI errors in the artifact directory and mark the final report incomplete rather than treating missing data as zero lag.

- [ ] **Step 4: Implement offline Prometheus retrieval and calculations**

After load completes, query Prometheus at 15-second resolution and save every request/response in \`prometheus-raw.json\`. Query:

\`\`\`text
100 * rate(process_cpu_seconds_total{job="python-ai"}[1m])
histogram_quantile(0.99, sum by (le) (increase(python_review_task_processing_seconds_bucket{outcome="success"}[RUN_WINDOW])))
jvm_memory_used_bytes{area="heap"}
jvm_memory_max_bytes{area="heap"}
process_resident_memory_bytes{job="java-backend"}
process_cpu_usage{job="java-backend"}
jvm_gc_pause_seconds_sum
jvm_gc_pause_seconds_count
hikaricp_connections_active
review_outbox_pending
\`\`\`

Group Python CPU by the Prometheus \`instance\` label. Report core-equivalent percentage, optional host-normalized percentage when \`HOST_LOGICAL_CPUS\` is set, plus average/P95/max/population standard deviation. Use a deterministic linear-interpolation percentile. Derive Python P99 only from the Histogram query, not Java \`review_async_latency_seconds\`. Calculate Kafka max/P95/final lag and first-to-zero drain duration from the CSV.

- [ ] **Step 5: Run collector tests**

Run: \`python -m pytest backend/k6/tools/tests/test_collect_scale_metrics.py -v\`

Expected: PASS.

- [ ] **Step 6: Commit**

\`\`\`bash
git add backend/k6/tools/collect_scale_metrics.py backend/k6/tools/tests/test_collect_scale_metrics.py
git commit -m "feat: collect low-frequency scale benchmark metrics"
\`\`\`

### Task 5: Add server-safe target management and benchmark orchestration

**Files:**
- Create: \`backend/k6/tools/python-ai-targets.yml\`
- Create: \`backend/k6/tools/run_scale_benchmark.sh\`

**Interfaces:**
- Consumes: Task 3 scenario and Task 4 collector.
- Consumes required environment variables \`PYTHON_ROOT\`, \`K6_ROOT\`, \`PROMETHEUS_URL\`, \`KAFKA_BOOTSTRAP\`, \`KAFKA_CONSUMER_GROUP\`, \`PROM_TARGETS_FILE\`, \`PROM_RELOAD_COMMAND\`.
- Produces: \`artifacts/<run-id>/\` with k6 summary, raw collector files, reconciliation JSON, and process logs.

- [ ] **Step 1: Create the file-SD target template**

Create \`backend/k6/tools/python-ai-targets.yml\`:

\`\`\`yaml
- targets:
    - localhost:8000
    - localhost:8001
  labels:
    job: python-ai
\`\`\`

The runner adds ports 8002/8003 only for its four-instance phase, writes the configured target file atomically, then runs the supplied reload command. It must not edit Prometheus’s main YAML in place.

- [ ] **Step 2: Implement dry-run behavior**

Implement \`--dry-run\` to print the RunID, artifact directory, instance ports, k6 command, collector command, and Prometheus target file without starting a process or clearing data.

Validate with:

\`\`\`bash
PYTHON_ROOT=/opt/review/python K6_ROOT=/workspace/backend/k6 \
PROMETHEUS_URL=http://localhost:9090 KAFKA_BOOTSTRAP=localhost:9092 \
KAFKA_CONSUMER_GROUP=review-python-consumer PROM_TARGETS_FILE=/opt/monitoring/python-ai-targets.yml \
PROM_RELOAD_COMMAND='curl -fsS -X POST http://localhost:9090/-/reload' \
bash backend/k6/tools/run_scale_benchmark.sh --phase 2inst --dry-run
\`\`\`

Expected: exit 0 and no Uvicorn, k6, mysql, Kafka CLI, or reload process starts.

- [ ] **Step 3: Implement explicit lifecycle and cleanup**

Implement functions \`start_python_instance\`, \`stop_python_instance\`, \`write_prometheus_targets\`, \`run_reconciliation\`, and \`run_load_window\`. Functions receive explicit ports and PID-file paths. Never use a broad \`pkill -f\`.

\`start_python_instance\` exports \`APP_PORT="$port"\` and \`PERFORMANCE_INSTANCE_ID="python-$port"\` before launching the existing virtualenv Uvicorn command. \`stop_python_instance\` sends TERM, waits a bounded interval, then sends KILL only to its explicitly recorded still-alive PID. The cleanup trap restores two-instance targets and stops only PIDs created by the runner.

\`run_load_window\` starts the collector watcher, invokes k6 with \`--summary-export\`, writes UTC start/end timestamps, waits for the watcher, and calls \`summarize\`. All output belongs in the RunID artifact directory.

- [ ] **Step 4: Implement formal phases**

Implement \`--phase 2inst\`, \`4inst\`, \`overhead-off\`, \`overhead-on\`, and \`staircase\`. Formal 2/4 runs use RATE=20 and DURATION=30m; overhead phases use five minutes. \`--rates 20,30,40,50,60,80\` drives the staircase.

Reconcile submitted/success/failure/duplicate/unfinished counts by generated RunID after each run. The runner must not truncate business tables or reset Kafka offsets; cleanup is a separately documented manual server operation.

- [ ] **Step 5: Validate syntax and dry run**

Run:

\`\`\`bash
bash -n backend/k6/tools/run_scale_benchmark.sh
bash backend/k6/tools/run_scale_benchmark.sh --phase 2inst --dry-run
\`\`\`

Expected: both exit 0; dry run only prints commands and paths.

- [ ] **Step 6: Commit**

\`\`\`bash
git add backend/k6/tools/python-ai-targets.yml backend/k6/tools/run_scale_benchmark.sh
git commit -m "feat: orchestrate reproducible Python scale benchmarks"
\`\`\`

### Task 6: Document gates and verify deployment without load

**Files:**
- Modify: \`backend/k6/README_DECOUPLING.md\`
- Modify: \`docs/superpowers/specs/2026-09-18-python-scale-observability-design.md\`

**Interfaces:**
- Consumes: raw artifacts emitted by Tasks 3–5.
- Produces: documented result schema and acceptance checklist for \`2inst-result.json\`, \`4inst-result.json\`, and \`2-vs-4-comparison.md\`.

- [ ] **Step 1: Document report fields and multiplier formula**

Require each result JSON to contain \`run_id\`, \`instance_count\`, admission accepted/throughput/P95/P99, Python P99/retries/CPU-by-instance, tasks/callbacks lag/drain duration, Java heap/RSS/CPU/GC/Hikari, and RunID reconciliation counts.

Define multiplier exactly as:

\`\`\`text
four_instance_max_sustainable_rps / two_instance_max_sustainable_rps
\`\`\`

State that missing or failed metrics invalidate the associated résumé claim.

- [ ] **Step 2: Document monitoring-overhead gate**

Run two five-minute 20 req/s tests and calculate:

\`\`\`text
admission_p95_delta_percent = abs(on_p95_ms - off_p95_ms) / off_p95_ms * 100
python_cpu_delta_percentage_points = abs(on_cpu_average - off_cpu_average)
\`\`\`

Accept formal results only if admission delta is at most 5% and CPU delta is at most 2 percentage points.

- [ ] **Step 3: Run local verification**

Run:

\`\`\`bash
python -m pytest python/tests/telemetry/test_async_resilience.py python/tests/mq/test_review_consumer_metrics.py backend/k6/tools/tests/test_collect_scale_metrics.py -v
k6 inspect backend/k6/scenarios/s1_decoupling.js
bash -n backend/k6/tools/run_scale_benchmark.sh
\`\`\`

Expected: tests pass; k6 parses; shell syntax is valid.

- [ ] **Step 4: Stage and validate remote tools without load**

Copy changed Python source and \`backend/k6\` files to a timestamped server staging directory; create backups before replacement. Verify without load:

\`\`\`bash
curl -fsS http://localhost:8000/metrics | grep python_review_task_processing_seconds
curl -fsS http://localhost:8001/metrics | grep python_review_task_processing_seconds
curl -fsS http://localhost:8080/actuator/health
bash /workspace/backend/k6/tools/run_scale_benchmark.sh --phase 2inst --dry-run
\`\`\`

Expected: both Python metric endpoints expose the family, Java is UP, and dry-run causes no traffic or database mutation.

- [ ] **Step 5: Commit**

\`\`\`bash
git add backend/k6/README_DECOUPLING.md docs/superpowers/specs/2026-09-18-python-scale-observability-design.md
git commit -m "docs: define scale benchmark validation gates"
\`\`\`

## Plan self-review

### Spec coverage

- Admission throughput/P95: Task 3 and Task 6.
- Exact Python-only P99 boundary and retry evidence: Tasks 1 and 2.
- CPU, Kafka/Outbox, Java heap/RSS/CPU/GC/Hikari: Task 4.
- Monitoring isolation and overhead limit: Tasks 3–6.
- Comparable 2/4 runs, raw artifacts, reconciliation, and staircase multiplier: Tasks 5–6.
- Label cardinality and credential prohibition: global constraints and Task 1.

### Placeholder scan

No deferred-work markers, vague future-work instructions, or unspecified test steps appear in this plan. Every helper, CLI, metric, and artifact name is introduced in the task that produces it.

### Type consistency

Task 1 defines \`task_processing_instance_id\`, \`observe_task_processing\`, and \`increment_task_processing_retry\`; Task 2 consumes those exact names. Task 4 defines \`watch\`/ \`summarize\`; Task 5 invokes those exact commands. Task 4 queries the exact Prometheus family created in Task 1.
