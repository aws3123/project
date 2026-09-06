/**
 * 场景2：140 req/s × 30min 稳态压测 (POST /api/review/async)
 *
 * 验证目标（对应简历：稳态 140 req/s 持续 30min 零死信、全链路消息对账一致）：
 *   - 恒定 140 req/s 提交速率下受理层错误率 = 0、接受任务数 ≈ 252,000
 *   - constant-arrival-rate 保证注入速率恒定，若中途能力不足则 dropped_iterations > 0
 *   - 每个受理成功的 taskId 可选打印（LOG_TASK_IDS=all），供测试后与 DB 全量集合对账
 *
 * 压测模型说明：
 *   本场景只测"受理层吞吐"，请求即发即走（不等待任务完成），与场景1 的
 *   burst_3000 / 之前的 async.js 封闭式等待模型不同。任务消费侧的完成
 *   速率约 140 条/s（与注入持平或略低），Kafka Lag 应在低位稳定波动而非
 *   持续上涨——Lag 趋势、DLQ 增量、Producer≈Consumer 均由 Kafka 监控侧验证。
 *
 * 全链路消息对账（压测结束后执行，非本脚本内）：
 *   k6 提交数 = DB review_task 新增 = Outbox 新增 = Topic A 消息数
 *            = Python 处理数 = Topic B 消息数 = 终态任务数，DLQ 新增 = 0
 *   140 req/s × 1800s = 252,000 tasks（本脚本以 accepted_tasks 计数提供
 *   k6 侧基准，DB/Kafka 侧以监控与 SQL 计数核对）。
 *
 * 运行：
 *   k6 run k6/scenarios/steady_140.js
 *   k6 run --env RATE=140 --env DURATION=30m k6/scenarios/steady_140.js
 *   LOG_TASK_IDS=all 会打印 25 万行 JSON，仅在对账需要时开启（默认 off）。
 */

import { check } from 'k6';
import http from 'k6/http';
import { Counter, Trend } from 'k6/metrics';
import { BASE_URL, HEADERS, makeAsyncPayload } from '../config.js';

const RATE = parseInt(__ENV.RATE || '140', 10);          // 恒定提交速率 req/s
const DURATION = __ENV.DURATION || '30m';                // 持续时间
const DIFF_SIZE = __ENV.DIFF_SIZE || 'small';            // small | medium | large
const LOG_TASK_IDS = (__ENV.LOG_TASK_IDS || 'none') === 'all'; // 全量对账时才打开
const ACCEPT_TIMEOUT_S = __ENV.ACCEPT_TIMEOUT_S || '10s';

// 解析 30m / 600s 之类的时长，计算期望受理总量的容差阈值
function durationSeconds(d) {
  const m = /^(\d+)m$/.exec(d);
  if (m) return parseInt(m[1], 10) * 60;
  const s = /^(\d+)s$/.exec(d);
  if (s) return parseInt(s[1], 10);
  return 0;
}
const EXPECTED_TOTAL = RATE * durationSeconds(DURATION); // 理论总提交数

// ---------- 自定义指标 ----------
const acceptedTasks = new Counter('accepted_tasks');  // 受理成功任务数
const submitFailed = new Counter('submit_failed');    // 受理失败数
const acceptDuration = new Trend('accept_duration');  // 受理接口响应时间(ms)

export const options = {
  scenarios: {
    steady: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: Math.max(20, Math.ceil(RATE * 0.2)), // 受理 RT 很小，VU 需求少
      maxVUs: Math.max(50, RATE),                          // 允许受理抖动时的弹性
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.001'],                 // 受理错误率 ≈ 0
    dropped_iterations: ['count==0'],                // 到达率必须全程保持（容量不足会在此显形）
    accept_duration: ['p(99)<3000'],                 // 受理 P99 不超过 3s
    // 受理总数与理论值偏差 < 0.5%（注入节奏容差）
    accepted_tasks: [`count>=${Math.floor(EXPECTED_TOTAL * 0.995)}`],
    submit_failed: [`count<=${Math.max(1, Math.ceil(EXPECTED_TOTAL * 0.001))}`],
  },
  tags: { scenario: 'steady_140', diffSize: DIFF_SIZE },
};

export default function () {
  let res;
  try {
    res = http.post(`${BASE_URL}/api/review/async`, makeAsyncPayload(DIFF_SIZE), {
      headers: HEADERS,
      timeout: ACCEPT_TIMEOUT_S,
      tags: { name: 'review_submit' },
    });
  } catch (e) {
    submitFailed.add(1);
    console.warn(`submit exception: ${e}`);
    return;
  }
  acceptDuration.add(res.timings.duration);

  let taskId = null;
  try {
    taskId = JSON.parse(res.body).taskId;
  } catch { /* ignore */ }

  const ok = check(res, {
    'async submit status 202': (r) => r.status === 202,
    'async submit has taskId': (r) => {
      try { return JSON.parse(r.body).taskId !== undefined; }
      catch { return false; }
    },
  });

  if (ok && taskId) {
    acceptedTasks.add(1);
    if (LOG_TASK_IDS) {
      console.log(JSON.stringify({ taskId }));
    }
  } else {
    submitFailed.add(1);
  }
}