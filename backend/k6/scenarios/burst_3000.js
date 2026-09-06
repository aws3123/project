/**
 * 场景1：3000 VU 单次尖峰突发 (POST /api/review/async)
 *
 * 验证目标（对应简历：k6 3000 VU 单次尖峰注入 3000 任务，受理层全量落库零丢失）：
 *   - 3000 个请求是否全部被受理：HTTP 202 = 3000，taskId = 3000，无失败
 *   - 受理接口响应时间分布（accept RT），判定受理层本身不是瓶颈
 *   - 每个受理成功的 taskId 以 JSON 行打印，供压测后与 DB/Hadoop 对账：
 *     对账口径 = k6 taskId 集合 vs DB review_task 集合（missing=0/duplicate=0）
 *
 * 执行模型：per-vu-iterations（每 VU 恰好提交 1 个任务，全部 VU 同时启动），
 * 即一次性尖峰注入，非持续施压。注入速率远高于消费速率(~140 条/s)，
 * 故 Kafka 峰值积压 ≈ 总注入数（Kafka Lag 由外部监控观察，见 header 说明）。
 *
 * Kafka / MySQL 侧指标（Lag、consumer rate、排空时间、Outbox 数量）不在 k6 内采集，
 * 需要配套 Prometheus/Grafana 监控消费组 Lag 与 DB 计数：
 *   - peak Lag ≈ 3000，drain 时间 ≤ 25s（消费速率 ≈ 140 条/s → 3000/140 ≈ 21.4s）
 *   - 任务表新增 = 3000，Outbox 新增 = 3000
 *
 * 运行：
 *   k6 run k6/scenarios/burst_3000.js
 *   k6 run --env VUS=3000 k6/scenarios/burst_3000.js
 *   k6 run --out json=results/burst_3000.json k6/scenarios/burst_3000.js
 */

import { check } from 'k6';
import http from 'k6/http';
import { Counter, Trend } from 'k6/metrics';
import { BASE_URL, HEADERS, makeAsyncPayload } from '../config.js';

const VUS = parseInt(__ENV.VUS || '3000', 10);            // 尖峰并发用户数
const DIFF_SIZE = __ENV.DIFF_SIZE || 'small';             // small | medium | large
const ACCEPT_TIMEOUT_S = __ENV.ACCEPT_TIMEOUT_S || '10s'; // 受理超时（受理应很快，超时即失败）
const LOG_TASK_IDS = (__ENV.LOG_TASK_IDS || 'true') === 'true'; // 打印 taskId 供集合对账

// ---------- 自定义指标 ----------
const acceptedTasks = new Counter('accepted_tasks');   // 受理成功任务数（202 且拿到 taskId）
const submitFailed = new Counter('submit_failed');     // 受理失败数（非 202 / 无 taskId / 异常）
const acceptDuration = new Trend('accept_duration');   // 受理接口响应时间(ms)

export const options = {
  scenarios: {
    burst: {
      executor: 'per-vu-iterations',
      vus: VUS,               // 3000 VU 同时启动
      iterations: 1,          // 每 VU 恰好提交 1 个任务
      maxDuration: '5m',      // VU 初始化兜底上限
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.005'],                        // 受理可用性
    // 受理成功数必须达到预期注入量的 99.5% 以上（留有极小容差）
    accepted_tasks: [`count>=${Math.ceil(VUS * 0.995)}`],
    submit_failed: [`count<=${Math.floor(VUS * 0.005)}`],
  },
  tags: { scenario: 'burst_3000', diffSize: DIFF_SIZE },
};

export default function () {
  const payload = makeAsyncPayload(DIFF_SIZE);

  let res;
  try {
    res = http.post(`${BASE_URL}/api/review/async`, payload, {
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
      // 每行一个 taskId，压测结束后与 DB 集合对账
      console.log(JSON.stringify({ taskId }));
    }
  } else {
    submitFailed.add(1);
    console.warn(`submit failed: status=${res.status} body=${String(res.body).slice(0, 200)}`);
  }
}