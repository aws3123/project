/**
 * 异步审核全链路压测 (POST /api/review/async → 轮询 /api/review/tasks/{taskId} 至终态)
 *
 * 压测链路：
 *   k6 → Java BFF (AST 前置) → Outbox → Kafka ai.review.tasks
 *      → Python (含固定 6s LLM Mock) → Kafka ai.review.callbacks → Java
 *      → k6 轮询任务状态直至终态
 *
 * 压测模型（closed workload / 恒定并发等待式）：
 *   每个 VU 提交一个异步审核任务后，立即轮询任务状态直到终态
 *   （success / failed / human_review），随后马上发起下一个任务，期间无思考时间。
 *   因此每个 VU 始终恰好有 1 个在途任务，端到端延迟由自定义 Trend
 *   `review_task_e2e`（提交 → 首次观测到终态）记录，任务完成吞吐
 *   （review_tasks_completed / 时长）与端到端延迟满足 Little's Law：
 *
 *       吞吐 λ = N / W   (N = 1000 VU, W = 平均端到端延迟)
 */

import { check, sleep } from 'k6';
import http from 'k6/http';
import { Counter, Trend } from 'k6/metrics';
import { BASE_URL, HEADERS, makeAsyncPayload } from '../config.js';

// ---------- 可调参数（默认值与叙事对齐：1000 VU / 5 分钟） ----------
const VUS = parseInt(__ENV.VUS || '1000', 10);                      // 恒定并发虚拟用户数
const DURATION = __ENV.DURATION || '5m';                            // 压测持续时间
const DIFF_SIZE = __ENV.DIFF_SIZE || 'small';                       // small | medium | large
const POLL_INTERVAL_S = parseFloat(__ENV.POLL_INTERVAL_S || '0.5'); // 状态轮询间隔
const WAIT_TIMEOUT_S = parseInt(__ENV.WAIT_TIMEOUT_S || '60', 10);  // 单任务最长等待时间

const TERMINAL_STATUSES = ['success', 'failed', 'human_review'];

// ---------- 自定义指标（对接叙事中的吞吐 / 端到端延迟） ----------
const reviewTaskE2e = new Trend('review_task_e2e', true);            // 端到端延迟(ms)：提交→终态
const reviewTasksTotal = new Counter('review_tasks_total');          // 提交的任务总数
const reviewTasksCompleted = new Counter('review_tasks_completed');  // 到达终态的任务数（吞吐 = 该值 / 时长）
const reviewTasksFailed = new Counter('review_tasks_failed');        // 终态为 failed 的任务数
const reviewTasksTimeout = new Counter('review_tasks_timeout');      // 超过等待窗口仍未终态的任务数

// 质量门禁：仅当显式传入 FAIL_* 环境变量时启用
function buildThresholds() {
  const t = {};
  const e2eRules = [];
  if (__ENV.FAIL_AVG_MS) e2eRules.push(`avg<${__ENV.FAIL_AVG_MS}`);
  if (__ENV.FAIL_P95_MS) e2eRules.push(`p(95)<${__ENV.FAIL_P95_MS}`);
  if (__ENV.FAIL_P99_MS) e2eRules.push(`p(99)<${__ENV.FAIL_P99_MS}`);
  if (__ENV.FAIL_HTTP_RATE) t.http_req_failed = [`rate<${__ENV.FAIL_HTTP_RATE}`];
  if (e2eRules.length > 0) t.review_task_e2e = e2eRules;
  return t;
}

export const options = {
  scenarios: {
    async_load: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
      gracefulStop: '60s',
    },
  },
  thresholds: buildThresholds(),
  tags: { scenario: 'async', diffSize: DIFF_SIZE },
};

function parseStatus(res) {
  try {
    const body = JSON.parse(res.body);
    return body && body.task ? body.task.status : null;
  } catch {
    return null;
  }
}

export default function () {
  const startedAt = Date.now();

  // 1. 提交异步审核任务（202 Accepted，立即返回任务ID）
  const submitRes = http.post(`${BASE_URL}/api/review/async`, makeAsyncPayload(DIFF_SIZE), {
    headers: HEADERS,
    timeout: '10s',
    tags: { name: 'review_submit' },
  });

  let taskId = null;
  try {
    taskId = JSON.parse(submitRes.body).taskId;
  } catch { /* ignore */ }

  check(submitRes, {
    'async submit status 202': (r) => r.status === 202,
    'async submit has taskId': () => !!taskId,
  });

  reviewTasksTotal.add(1);

  if (!taskId) {
    reviewTasksFailed.add(1);
    return;
  }

  // 2. 轮询任务状态直到终态或超时（封闭式等待：VU 期间始终只有 1 个在途任务）
  const deadline = startedAt + WAIT_TIMEOUT_S * 1000;
  let status = null;

  while (Date.now() < deadline) {
    const pollRes = http.get(`${BASE_URL}/api/review/tasks/${taskId}`, {
      headers: HEADERS,
      timeout: '5s',
      tags: { name: 'review_status_poll' },
    });

    check(pollRes, { 'task poll status 200': (r) => r.status === 200 });

    const s = parseStatus(pollRes);
    if (s && TERMINAL_STATUSES.includes(s)) {
      status = s;
      break;
    }

    sleep(POLL_INTERVAL_S);
  }

  // 3. 记录端到端延迟（提交时刻 → 首次观测到终态的时刻）
  reviewTaskE2e.add(Date.now() - startedAt);

  if (status === 'failed') {
    reviewTasksCompleted.add(1); // 到达终态即计入吞吐
    reviewTasksFailed.add(1);
  } else if (TERMINAL_STATUSES.includes(status)) {
    reviewTasksCompleted.add(1); // success / human_review
  } else {
    reviewTasksTimeout.add(1);
  }
}