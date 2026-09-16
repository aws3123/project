/**
 * 板块1 · 场景一：受理层恒定到达率基线（open workload）
 *
 * 目标链路（只测受理，不含 LLM 审查）：
 *   k6 --(恒定到达率)--> POST /api/review/async
 *        Java BFF 同步完成 AST 预处理 → Outbox 落库 → 202 Accepted
 *
 * 为什么用恒定到达率而不是恒定 VU：
 *   受理接口是异步入口（落库即返回），吞吐由到达率驱动而非并发数驱动。
 *   constant-arrival-rate 才能保证「每秒恰好收到 RATE 个请求」这一自变量，
 *   据此测量受理 P95/P99 与错误率 —— 这正是「受理吞吐 + 受理延迟」叙事的口径。
 *
 * 用法：
 *   k6 run -e RATE=100 -e DURATION=5m scenarios/s1_admission.js
 *   分档基线：依次 RATE=100 / 300 / 500 各跑一轮，每档记录受理 P99 与错误率。
 *
 * 质量门禁（可选，环境变量触发）：
 *   FAIL_P95_MS / FAIL_P99_MS  受理延迟门禁（毫秒）
 *   FAIL_HTTP_RATE             HTTP 失败率门禁
 */

import { check } from 'k6';
import http from 'k6/http';
import { Counter } from 'k6/metrics';
import { BASE_URL, HEADERS, makeAsyncPayload } from '../config.js';

// ---------- 可调参数 ----------
const RATE = parseInt(__ENV.RATE || '100', 10);              // 目标到达率（req/s）
const DURATION = __ENV.DURATION || '5m';                     // 持续时间
const DIFF_SIZE = __ENV.DIFF_SIZE || 'small';                // small | medium | large
const PRE_ALLOCATED_VUS = parseInt(
  __ENV.PRE_ALLOCATED_VUS || String(Math.max(20, Math.ceil(RATE / 10))), 10);
const MAX_VUS = parseInt(__ENV.MAX_VUS || String(PRE_ALLOCATED_VUS * 3), 10);

const admissionsTotal = new Counter('admissions_total');      // 发起的受理请求总数
const admissionsAccepted = new Counter('admissions_accepted'); // 返回 202 且含 taskId 的请求数

// ---------- 质量门禁 ----------
function buildThresholds() {
  const t = { http_req_failed: ['rate<0.005'] };
  const rules = [];
  if (__ENV.FAIL_P95_MS) rules.push(`p(95)<${__ENV.FAIL_P95_MS}`);
  if (__ENV.FAIL_P99_MS) rules.push(`p(99)<${__ENV.FAIL_P99_MS}`);
  if (rules.length) t['http_req_duration{name:review_submit}'] = rules;
  return t;
}

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
  },
  thresholds: buildThresholds(),
  tags: { scenario: 's1_admission', diffSize: DIFF_SIZE },
};

export default function () {
  admissionsTotal.add(1);

  const res = http.post(`${BASE_URL}/api/review/async`, makeAsyncPayload(DIFF_SIZE), {
    headers: HEADERS,
    timeout: '10s',
    tags: { name: 'review_submit' },
  });

  let taskId = null;
  try {
    taskId = JSON.parse(res.body).taskId;
  } catch { /* ignore */ }

  const ok = check(res, {
    'admission status 202': (r) => r.status === 202,
    'admission has taskId': () => !!taskId,
  });

  if (ok) admissionsAccepted.add(1);
}

/** 收尾输出一行关键结果，便于分档基线汇总成表 */
export function handleSummary(data) {
  const tagged = data.metrics['http_req_duration{name:review_submit}'];
  const dur = (tagged && tagged.values) || {};
  const line = [
    `target_rate=${RATE}/s`,
    `achieved_rate=${(data.metrics.http_reqs.values.rate || 0).toFixed(2)}/s`,
    `p50=${(dur['p(50)'] || 0).toFixed(1)}ms`,
    `p95=${(dur['p(95)'] || 0).toFixed(1)}ms`,
    `p99=${(dur['p(99)'] || 0).toFixed(1)}ms`,
    `http_fail_rate=${((data.metrics.http_req_failed.values.rate || 0) * 100).toFixed(3)}%`,
    `admission_ok=${data.metrics.admissions_accepted.values.count}`,
  ].join('  ');

  console.log(`\n===== 板块1 受理基线（diff=${DIFF_SIZE}, duration=${DURATION}）=====\n${line}\n`);
  return {};
}
