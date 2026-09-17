/**
 * 分层架构解耦：Java BFF 受理层恒定到达率压测。
 *
 * 只测同步受理路径：POST /api/review/async -> AST 预处理 -> Outbox -> 202。
 * Python 的 CPU、Java AST 指标和 1/4 实例线性度由 Prometheus 在压测期间采集。
 */
import { check } from 'k6';
import http from 'k6/http';
import { Counter, Trend } from 'k6/metrics';
import exec from 'k6/execution';
import { BASE_URL, HEADERS, makeAsyncPayload } from '../config.js';

const RATE = parseInt(__ENV.RATE || '20', 10);
const DURATION = __ENV.DURATION || '5m';
const DIFF_SIZE = __ENV.DIFF_SIZE || 'small';
const PRE_ALLOCATED_VUS = parseInt(__ENV.PRE_ALLOCATED_VUS || String(Math.max(20, RATE)), 10);
const MAX_VUS = parseInt(__ENV.MAX_VUS || String(Math.max(PRE_ALLOCATED_VUS * 4, 100)), 10);
const PROMETHEUS_URL = __ENV.PROMETHEUS_URL || 'http://127.0.0.1:9090';

const accepted = new Counter('decoupling_admissions_accepted');
const admissionLatency = new Trend('decoupling_admission_latency', true);
const taskCompletionP99 = new Trend('decoupling_task_completion_p99', true);
const pythonCpuAverage = new Trend('decoupling_python_cpu_average', true);

export const options = {
  scenarios: {
    admission: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: PRE_ALLOCATED_VUS,
      maxVUs: MAX_VUS,
      gracefulStop: '10s',
    },
    python_cpu_sampler: {
      executor: 'constant-arrival-rate',
      rate: 1,
      timeUnit: '10s',
      duration: DURATION,
      preAllocatedVUs: 1,
      maxVUs: 1,
      gracefulStop: '10s',
    },
  },
  thresholds: {
    http_req_failed: [`rate<${__ENV.FAIL_HTTP_RATE || 0.01}`],
    'http_req_duration{name:decoupling_admission}': [
      `p(99)<${__ENV.FAIL_P99_MS || 1000}`,
    ],
  },
  tags: { test_suite: 's1-decoupling', diff_size: DIFF_SIZE },
};

export default function () {
  if (exec.scenario.name === 'python_cpu_sampler') {
    samplePythonCpu();
    return;
  }

  const res = http.post(`${BASE_URL}/api/review/async`, makeAsyncPayload(DIFF_SIZE), {
    headers: HEADERS,
    timeout: __ENV.HTTP_TIMEOUT || '30s',
    tags: { name: 'decoupling_admission' },
  });

  let taskId = null;
  try {
    taskId = JSON.parse(res.body).taskId;
  } catch (_) {
    // The check below reports malformed responses as failed admissions.
  }

  const ok = check(res, {
    'admission status 202': (r) => r.status === 202,
    'admission has taskId': () => Boolean(taskId),
  });
  admissionLatency.add(res.timings.duration);
  if (ok) {
    accepted.add(1);
  }
}

function samplePythonCpu() {
  const query = encodeURIComponent('100 * sum(rate(process_cpu_seconds_total{job="python-ai"}[1m]))');
  const res = http.get(`${PROMETHEUS_URL}/api/v1/query?query=${query}`, {
    tags: { name: 'python_cpu_query' },
    timeout: '10s',
  });
  if (res.status !== 200) return;
  try {
    const results = JSON.parse(res.body).data.result || [];
    const values = results.map((item) => Number(item.value[1])).filter(Number.isFinite);
    if (values.length) pythonCpuAverage.add(values.reduce((a, b) => a + b, 0));
  } catch (_) {
    // Missing Prometheus samples are ignored; the summary reports sample count.
  }

  const p99Query = encodeURIComponent('1000 * histogram_quantile(0.99, sum by (le) (rate(review_async_latency_seconds_bucket[5m])))');
  const p99 = http.get(`${PROMETHEUS_URL}/api/v1/query?query=${p99Query}`, {
    tags: { name: 'task_completion_p99_query' },
    timeout: '10s',
  });
  if (p99.status !== 200) return;
  try {
    const value = Number(JSON.parse(p99.body).data.result[0].value[1]);
    if (Number.isFinite(value)) taskCompletionP99.add(value);
  } catch (_) {
    // Missing histogram samples are ignored.
  }
}

export function handleSummary(data) {
  const duration = data.metrics.decoupling_admission_latency?.values || {};
  const completion = data.metrics.decoupling_task_completion_p99?.values || {};
  const cpu = data.metrics.decoupling_python_cpu_average?.values || {};
  const failed = data.metrics.http_req_failed?.values?.rate || 0;
  const ok = data.metrics.decoupling_admissions_accepted?.values?.count || 0;
  const elapsedSeconds = data.state?.testRunDurationMs ? data.state.testRunDurationMs / 1000 : 0;
  const reqs = elapsedSeconds > 0 ? ok / elapsedSeconds : 0;
  console.log([
    `target_rate=${RATE}/s`,
    `achieved_rate=${reqs.toFixed(2)}/s`,
    `p50=${(duration['p(50)'] || 0).toFixed(1)}ms`,
    `p95=${(duration['p(95)'] || 0).toFixed(1)}ms`,
    `p99=${(duration['p(99)'] || duration['p(99.0)'] || 0).toFixed(1)}ms`,
    `task_completion_p99_prom_avg=${(completion.avg || 0).toFixed(1)}ms`,
    `python_cpu_avg=${(cpu.avg || 0).toFixed(2)}%`,
    `python_cpu_samples=${cpu.count || 0}`,
    `http_fail_rate=${(failed * 100).toFixed(3)}%`,
    `accepted=${ok}`,
  ].join('  '));
  return {};
}
