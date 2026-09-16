/**
 * 板块1 · 场景二：水平扩展阶梯压测（open workload）
 *
 * 协议：以同一份阶梯到达率（BASE_RATE → 2×BASE_RATE → 4×BASE_RATE）分别对
 * 1 / 2 / 4 实例各跑一轮，对比同一阶段下的受理 P99 与错误率：
 *   - 各实例数下「不破门禁的最高稳态档」即该规模的可持续吞吐；
 *   - 每实例吞吐 = 稳态档到达率 / 实例数，跨实例数近似恒定（线性度 ≥90%）即为
 *     「具备水平扩展基础」的直接证据。
 *
 * 每个请求都打上 stage 标签（x1 / x2 / x4），配合 k6 Prometheus remote write，
 * Grafana 可按 stage 画扩展曲线；本地跑则看 handleSummary 的汇总行。
 *
 * 用法（每个实例数一轮，INSTANCES 仅作为标签便于区分轮次）：
 *   docker compose up -d --scale java-backend=1 java-backend
 *   k6 run -e BASE_RATE=100 -e INSTANCES=1 --tag test_run=s1x1 scenarios/s1_scaling.js
 *   docker compose up -d --scale java-backend=4 java-backend
 *   k6 run -e BASE_RATE=100 -e INSTANCES=4 --tag test_run=s1x4 scenarios/s1_scaling.js
 *
 * 可选门禁：
 *   FAIL_P99_MS      各阶段受理 P99 门禁（毫秒）
 *   FAIL_HTTP_RATE   HTTP 失败率门禁
 */

import exec from 'k6/execution';
import { check } from 'k6';
import http from 'k6/http';
import { Counter } from 'k6/metrics';
import { BASE_URL, HEADERS, makeAsyncPayload } from '../config.js';

// ---------- 阶梯参数 ----------
const BASE_RATE = parseInt(__ENV.BASE_RATE || '100', 10);  // 阶梯起点（req/s）
const STEPS = parseInt(__ENV.STEPS || '3', 10);            // 阶梯数：x1, x2, x4
const STEP_DURATION = __ENV.STEP_DURATION || '2m';         // 每档稳态时长
const RAMP_DURATION = __ENV.RAMP_DURATION || '30s';        // 档间爬坡时长
const WARMUP_DURATION = __ENV.WARMUP_DURATION || '30s';    // 热身时长
const DIFF_SIZE = __ENV.DIFF_SIZE || 'small';
const INSTANCES = __ENV.INSTANCES || '1';                  // 仅作标签
const MAX_VUS = parseInt(__ENV.MAX_VUS || '300', 10);

// ---------- 组装阶梯（30s 热身 + [爬坡 + 稳态] × STEPS） ----------
const stageRates = [];
const stages = [{ duration: WARMUP_DURATION, target: BASE_RATE }];
for (let i = 0; i < STEPS; i++) {
  const rate = BASE_RATE * Math.pow(2, i);
  stageRates.push(rate);
  stages.push({ duration: RAMP_DURATION, target: rate });
  stages.push({ duration: STEP_DURATION, target: rate });
}

const admissionsTotal = new Counter('admissions_total');
const admissionsAccepted = new Counter('admissions_accepted');

// ---------- 质量门禁 ----------
function buildThresholds() {
  const t = { http_req_failed: ['rate<0.005'] };
  if (__ENV.FAIL_P99_MS) {
    t['http_req_duration{name:review_submit}'] = [`p(99)<${__ENV.FAIL_P99_MS}`];
  }
  return t;
}

export const options = {
  scenarios: {
    scaling: {
      executor: 'ramping-arrival-rate',
      startRate: BASE_RATE,
      timeUnit: '1s',
      stages,
      preAllocatedVUs: 50,
      maxVUs: MAX_VUS,
      gracefulStop: '10s',
    },
  },
  thresholds: buildThresholds(),
  tags: { scenario: 's1_scaling', diffSize: DIFF_SIZE, instances: INSTANCES },
};

// 稳态档的起止时刻（相对场景启动，毫秒），用于给请求打 stage 标签
function durationToMs(d) {
  const m = /^([\d.]+)(ms|s|m|h)?$/.exec(String(d).trim());
  if (!m) return 0;
  return parseFloat(m[1]) * { ms: 1, s: 1000, m: 60000, h: 3600000 }[m[2] || 's'];
}

const steadyWindows = (() => {
  let cursor = durationToMs(WARMUP_DURATION);
  const windows = [];
  for (let i = 0; i < STEPS; i++) {
    const from = cursor + durationToMs(RAMP_DURATION);
    cursor = from + durationToMs(STEP_DURATION);
    windows.push({ from, to: cursor, tag: `x${Math.pow(2, i)}` });
  }
  return windows;
})();

function currentStageTag() {
  const elapsed = Date.now() - exec.scenario.startTime;
  const win = steadyWindows.find((w) => elapsed >= w.from && elapsed < w.to);
  return win ? win.tag : 'ramp';
}

export default function () {
  admissionsTotal.add(1);

  const res = http.post(`${BASE_URL}/api/review/async`, makeAsyncPayload(DIFF_SIZE), {
    headers: HEADERS,
    timeout: '10s',
    tags: { name: 'review_submit', stage: currentStageTag() },
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

export function handleSummary(data) {
  const tagged = data.metrics['http_req_duration{name:review_submit}'];
  const dur = (tagged && tagged.values) || {};
  const line = [
    `instances=${INSTANCES}`,
    `ladder=${stageRates.join('->')}/s`,
    `steady_step=${STEP_DURATION}`,
    `overall_p99=${(dur['p(99)'] || 0).toFixed(1)}ms`,
    `http_fail_rate=${((data.metrics.http_req_failed.values.rate || 0) * 100).toFixed(3)}%`,
    `admission_ok=${data.metrics.admissions_accepted.values.count}`,
  ].join('  ');

  console.log(`\n===== 板块1 扩展阶梯（diff=${DIFF_SIZE}）=====\n${line}`);
  console.log('分档 P99 请在 Grafana「扩展阶梯」行按 stage 标签查看，或对 remote write 数据按 stage 聚合。\n');
  return {};
}
