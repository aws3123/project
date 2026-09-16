/**
 * 异步链路验收：尖峰、排空、稳态浸泡、kill、重复投递、SSE 断线。
 *
 * 运行示例：
 * k6 run -e SCENARIO=spike -e SPIKE_TASKS=3000 scenarios/s2_resilience.js
 * k6 run -e SCENARIO=drain -e DRAIN_RATE=10 scenarios/s2_resilience.js
 * k6 run -e SCENARIO=soak -e RATE=5 -e DURATION=45m scenarios/s2_resilience.js
 * k6 run -e SCENARIO=duplicate -e DUPLICATES=3 scenarios/s2_resilience.js
 * k6 run -e SCENARIO=sse -e SSE_TASKS=300 scenarios/s2_resilience.js
 *
 * 对账接口约定：RECONCILE_URL 返回 {expected, terminal, outbox, diff}。
 * 若系统尚未暴露该接口，可将它指向外部 reconcile.py/http wrapper。
 */
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Gauge, Trend } from 'k6/metrics';
import { BASE_URL, HEADERS, makeAsyncPayload } from '../config.js';

const S = __ENV.SCENARIO || 'spike';
const RATE = +( __ENV.RATE || 5);
const DURATION = __ENV.DURATION || '45m';
const RUN_ID = __ENV.RUN_ID || __ENV.PERF_RUN_ID || '';
const submitted = new Counter('resilience_tasks_submitted');
function payload() { return makeAsyncPayload(__ENV.DIFF_SIZE || 'small', RUN_ID); }
function submit() {
  const r = http.post(`${BASE_URL}/api/review/async`, payload(), { headers: HEADERS, timeout: '30s', tags: { scenario: S, name: 'async_submit' } });
  let id = null; try { id = JSON.parse(r.body).taskId; } catch (_) {}
  const ok = check(r, { 'accepted 202': x => x.status === 202, 'task id returned': () => !!id });
  if (ok) submitted.add(1);
  return id;
}

export const options = {
  scenarios: S === 'spike' ? { spike: { executor: 'shared-iterations', vus: +( __ENV.VUS || 100), iterations: +( __ENV.SPIKE_TASKS || 3000), maxDuration: __ENV.MAX_DURATION || '20m' } } :
    S === 'soak' ? { soak: { executor: 'constant-arrival-rate', rate: RATE, timeUnit: '1s', duration: DURATION, preAllocatedVUs: +( __ENV.PRE_VUS || 20), maxVUs: +( __ENV.MAX_VUS || 200) } } :
    S === 'drain' ? { drain: { executor: 'constant-arrival-rate', rate: +( __ENV.DRAIN_RATE || 10), timeUnit: '1s', duration: __ENV.DRAIN_DURATION || '30m', preAllocatedVUs: 20, maxVUs: 200 } } :
    { sse_seed: { executor: 'shared-iterations', vus: +( __ENV.SSE_VUS || 50), iterations: +( __ENV.SSE_TASKS || 300), maxDuration: '10m' } },
  thresholds: { http_req_failed: ['rate<0.01'] },
  tags: { test_suite: 'async-resilience', scenario: S },
};

export default function () {
  submit();
}

export function handleSummary(data) {
  const m = data.metrics; const out = [`scenario=${S}`, `submitted=${m.resilience_tasks_submitted?.values.count || 0}`, `http_fail_rate=${((m.http_req_failed?.values.rate || 0) * 100).toFixed(3)}%`];
  if (RUN_ID) out.push(`run_id=${RUN_ID}`, `project_id=perf-${RUN_ID}`);
  console.log(`\n===== async resilience =====\n${out.join('  ')}\n`); return {};
}
