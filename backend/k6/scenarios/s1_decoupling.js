/**
 * Java BFF async-admission benchmark. It intentionally makes no monitoring,
 * Kafka, or database request: those are handled by collect_scale_metrics.py.
 */
import http from 'k6/http';
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import { BASE_URL, HEADERS, makeAsyncPayload } from '../config.js';

const rate = Number(__ENV.RATE || 20);
const duration = __ENV.DURATION || '30m';
const runId = __ENV.RUN_ID || __ENV.PERF_RUN_ID || `decoupling-${Date.now()}`;
const admissionLatency = new Trend('decoupling_acceptance_latency_ms');
const accepted = new Counter('decoupling_admissions_accepted');
const rejected = new Counter('decoupling_admissions_rejected');

export const options = {
  scenarios: { admission: { executor: 'constant-arrival-rate', rate, timeUnit: '1s', duration,
    preAllocatedVUs: Number(__ENV.PRE_ALLOCATED_VUS || 50), maxVUs: Number(__ENV.MAX_VUS || 500) } },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    decoupling_acceptance_latency_ms: [`p(95)<${Number(__ENV.FAIL_P95_MS || 1000)}`],
    dropped_iterations: ['count==0'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)', 'count'],
  tags: { test_suite: 'decoupling-admission', run_id: runId },
};

export default function () {
  const response = http.post(`${BASE_URL}/api/review/async`, makeAsyncPayload(__ENV.DIFF_SIZE || 'small', runId), {
    headers: HEADERS, timeout: __ENV.REQUEST_TIMEOUT || '30s', tags: { name: 'async_admission' },
  });
  admissionLatency.add(response.timings.duration);
  let taskId = null;
  try { taskId = response.json('taskId'); } catch (_) { /* handled by check */ }
  const isAccepted = check(response, { 'accepted 202 with task id': (r) => r.status === 202 && Boolean(taskId) });
  if (isAccepted) accepted.add(1); else rejected.add(1);
}
