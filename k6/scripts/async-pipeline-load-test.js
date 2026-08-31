// k6 load test — 异步任务流水线（Outbox + SSE 流式推送 + Reconciliation 兜底）
// 模拟三组场景：
//   场景 1 asyncSubmit: 提交异步审查任务 → 轮询 task status → 验证全流程交付
//   场景 2 dispatchRoute: 提交自动路由任务 → 验证分发决策 → 跟踪终态
//   场景 3 concurrencyBurst: 突发高并发 → 验证 outbox 削峰 + 队列积压恢复
//
// 阈值目标:
//   - async task 终态到达率 > 99%
//   - outbox 投递延迟 (P95) < 5s (含 2s 轮询周期)
//   - pipeline 端到端延迟 (P95) < 60s
//   - 突发场景下零死信 (DEAD == 0)

import http from 'k6/http';
import { check, sleep, group, fail } from 'k6';
import { Rate, Trend, Counter, Gauge } from 'k6/metrics';

const config = JSON.parse(open('../config.js'));

// ======================== 自定义指标 ========================

const taskCompletionRate = new Rate('async_task_completion_rate');
const outboxLatency     = new Trend('outbox_dispatch_latency_ms');   // submit → 离开 PENDING
const pipelineLatency   = new Trend('pipeline_end_to_end_latency_ms'); // submit → 终态
const pollAttempts      = new Trend('poll_attempts_count');
const deadLetterCount   = new Counter('async_dead_letter_total');
const stuckTaskCount    = new Counter('stuck_task_recovered_total');
const activePendingGauge = new Gauge('active_pending_tasks');

// ======================== 测试数据 ========================

const diffSamples = [
  {
    projectId: 'proj-db',
    prUrl: 'https://github.com/org/repo/pull/201',
    diffContent: 'DELETE FROM users WHERE id = ?;\n-- Missing WHERE clause check\nfor (User u : users) { db.delete(u); }',
  },
  {
    projectId: 'proj-order',
    prUrl: 'https://github.com/org/repo/pull/202',
    diffContent: 'public void transfer(Account from, Account to, BigDecimal amount) {\n  from.setBalance(from.getBalance().subtract(amount));\n  to.setBalance(to.getBalance().add(amount));\n}',
  },
  {
    projectId: 'proj-gateway',
    prUrl: 'https://github.com/org/repo/pull/203',
    diffContent: 'timeout: 100\n# Reduced from 500ms without capacity assessment\nrateLimit: 1000',
  },
  {
    projectId: 'proj-auth',
    prUrl: 'https://github.com/org/repo/pull/204',
    diffContent: 'if (token.expireTime < System.currentTimeMillis()) { refreshToken(token); }\n-- No lock around refresh',
  },
  {
    projectId: 'proj-payment',
    prUrl: 'https://github.com/org/repo/pull/205',
    diffContent: 'UPDATE accounts SET balance = balance - ? WHERE id = ?\n-- No version check, no CAS',
  },
  {
    projectId: 'proj-search',
    prUrl: 'https://github.com/org/repo/pull/206',
    diffContent: 'Product p = cache.get(key);\nif (p == null) { p = db.query(key); }\n-- Cache penetration risk',
  },
];

function traceHeaders() {
  return {
    'X-Trace-Id': `k6-async-${__VU}-${__ITER}-${Date.now()}`,
    'X-API-Key': config.apiKey,
    'Content-Type': 'application/json',
  };
}

function pickSample() {
  return diffSamples[__ITER % diffSamples.length];
}

// ======================== 场景 1: 异步提交流程 ========================

export function scenarioAsyncSubmit() {
  group('Async Task Submit', function () {
    const sample = pickSample();
    const taskId = `k6-async-${__VU}-${__ITER}`;

    // 1. 提交异步任务
    const submitPayload = JSON.stringify({
      taskId: taskId,
      projectId: sample.projectId,
      projectName: sample.projectId,
      prUrl: sample.prUrl,
      diffContent: sample.diffContent,
      mode: 'ASYNC',
    });

    const submitStart = Date.now();
    const submitRes = http.post(`${config.baseUrl}/api/review/async`, submitPayload, {
      headers: traceHeaders(),
      timeout: '10s',
    });

    const submitPassed = check(submitRes, {
      'async submit status is 202': (r) => r.status === 202,
      'async submit returns taskId': (r) => {
        if (!r.body) return false;
        try {
          const body = JSON.parse(r.body);
          return body.taskId !== undefined && body.status === 'QUEUED';
        } catch { return false; }
      },
    });

    if (!submitPassed) {
      taskCompletionRate.add(false);
      return;
    }

    let pollCount = 0;
    let terminalStatus = null;
    let firstNonPendingTime = null;
    const maxPolls = 120; // 最多等 2 分钟

    // 2. 轮询 taskId 直到终态
    while (pollCount < maxPolls) {
      pollCount++;
      const pollRes = http.get(`${config.baseUrl}/api/review/tasks/${taskId}`, {
        headers: traceHeaders(),
        timeout: '5s',
      });

      if (pollRes.status !== 200 || !pollRes.body) {
        sleep(1);
        continue;
      }

      try {
        const body = JSON.parse(pollRes.body);
        const task = body.task;
        if (!task || !task.status) {
          sleep(1);
          continue;
        }

        const status = task.status;

        // 记录 outbox 投递延迟 (PENDING → 第一个非 PENDING)
        if (firstNonPendingTime === null && status !== 'PENDING') {
          firstNonPendingTime = Date.now();
          outboxLatency.add(firstNonPendingTime - submitStart);
        }

        if (['SUCCESS', 'FAILED', 'HUMAN_REVIEW'].includes(status)) {
          terminalStatus = status;
          break;
        }

        // 如果是 NEED_REVIEW，也视为终态（等待人工决策）
        if (status === 'NEED_REVIEW') {
          terminalStatus = status;
          break;
        }

        // 死信检查
        if (status === 'DEAD') {
          deadLetterCount.add(1);
          terminalStatus = status;
          break;
        }

      } catch (e) {
        // JSON parse error, retry
      }

      sleep(1); // 1s 轮询间隔
    }

    pollAttempts.add(pollCount);
    const totalLatency = Date.now() - submitStart;

    if (terminalStatus) {
      pipelineLatency.add(totalLatency);

      const completed = terminalStatus === 'SUCCESS' || terminalStatus === 'HUMAN_REVIEW';
      taskCompletionRate.add(completed);

      // 检查终态是否正确
      check({ status: terminalStatus, latency: totalLatency }, {
        'task reached terminal state': (obj) => ['SUCCESS', 'FAILED', 'NEED_REVIEW', 'DEAD'].includes(obj.status),
        'outbox dispatch under 5s': (obj) => firstNonPendingTime !== null
          && (firstNonPendingTime - submitStart) <= 5000,
        'pipeline completes within 120s': (obj) => obj.latency <= 120000,
      });

    } else {
      // 轮询超时 → 任务卡住了，需要 Reconciliation 兜底
      stuckTaskCount.add(1);
      taskCompletionRate.add(false);
      console.warn(`Task ${taskId} stuck after ${maxPolls * 1}s polling, expected Reconciliation recovery`);

      // 等 Reconciliation 跑一次 (60s) 后再检查一次
      sleep(65);
      const recoveryRes = http.get(`${config.baseUrl}/api/review/tasks/${taskId}`, {
        headers: traceHeaders(),
        timeout: '5s',
      });
      if (recoveryRes.status === 200 && recoveryRes.body) {
        try {
          const body = JSON.parse(recoveryRes.body);
          const recoveredStatus = body.task?.status;
          check({ recoveredStatus, taskId }, {
            'Reconciliation recovered stuck task': (obj) =>
              obj.recoveredStatus === 'FAILED' || obj.recoveredStatus === 'SUCCESS',
          });
        } catch { }
      }
    }
  });
}

// ======================== 场景 2: 自动路由分发 ========================

export function scenarioDispatchRoute() {
  group('Dispatch Auto-Route', function () {
    const sample = pickSample();
    const taskId = `k6-dispatch-${__VU}-${__ITER}`;

    const dispatchPayload = JSON.stringify({
      taskId: taskId,
      projectId: sample.projectId,
      projectName: sample.projectId,
      prUrl: sample.prUrl,
      diffContent: sample.diffContent,
      question: '请审查此变更是否存在数据安全或性能风险',
    });

    const dispatchStart = Date.now();
    const dispatchRes = http.post(`${config.baseUrl}/api/review/dispatch`, dispatchPayload, {
      headers: traceHeaders(),
      timeout: '10s',
    });

    const dispatchPassed = check(dispatchRes, {
      'dispatch status is 200': (r) => r.status === 200,
      'dispatch returns routing decision': (r) => {
        if (!r.body) return false;
        try {
          const body = JSON.parse(r.body);
          return body.route !== undefined;
        } catch { return false; }
      },
    });

    if (!dispatchPassed) return;

    // 跟踪分发后的任务终态
    const route = JSON.parse(dispatchRes.body).route;
    if (route === 'ASYNC') {
      let pollCount = 0;
      let dispatchedTerminal = null;

      while (pollCount < 60 && !dispatchedTerminal) {
        pollCount++;
        const pollRes = http.get(`${config.baseUrl}/api/review/tasks/${taskId}`, {
          headers: traceHeaders(),
          timeout: '5s',
        });

        if (pollRes.status === 200 && pollRes.body) {
          try {
            const status = JSON.parse(pollRes.body).task?.status;
            if (['SUCCESS', 'FAILED', 'HUMAN_REVIEW', 'NEED_REVIEW', 'DEAD'].includes(status)) {
              dispatchedTerminal = status;
            }
          } catch { }
        }
        sleep(2);
      }

      pipelineLatency.add(Date.now() - dispatchStart);
      taskCompletionRate.add(dispatchedTerminal === 'SUCCESS' || dispatchedTerminal === 'HUMAN_REVIEW');
    }
  });
}

// ======================== 场景 3: 突发高并发压测 ========================

export function scenarioConcurrencyBurst() {
  group('Concurrency Burst', function () {
    const samples = [];
    const batchSize = 5;

    // 批量提交，模拟突发流量
    for (let i = 0; i < batchSize; i++) {
      const sample = diffSamples[(__ITER + i) % diffSamples.length];
      const taskId = `k6-burst-${__VU}-${__ITER}-${i}`;
      samples.push({ taskId, ...sample });
    }

    const batchStart = Date.now();
    const batchRequests = samples.map(s => {
      return ['POST', `${config.baseUrl}/api/review/async`, JSON.stringify({
        taskId: s.taskId,
        projectId: s.projectId,
        projectName: s.projectId,
        prUrl: s.prUrl,
        diffContent: s.diffContent,
        mode: 'ASYNC',
      }), { headers: traceHeaders(), timeout: '10s' }];
    });

    // 批量请求
    const batchRes = http.batch(batchRequests);

    let accepted = 0;
    for (const res of batchRes) {
      if (res.status === 202) accepted++;
    }

    check(batchRes[0], {
      'burst submit accepted rate > 80%': () => (accepted / batchSize) > 0.8,
    });

    // 采样第一个任务轮询终态
    const probeTask = samples[0].taskId;
    let probePolls = 0;

    while (probePolls < 30) {
      probePolls++;
      const pollRes = http.get(`${config.baseUrl}/api/review/tasks/${probeTask}`, {
        headers: traceHeaders(),
        timeout: '5s',
      });

      if (pollRes.status === 200 && pollRes.body) {
        try {
          const status = JSON.parse(pollRes.body).task?.status;
          if (['SUCCESS', 'FAILED', 'HUMAN_REVIEW', 'DEAD'].includes(status)) {
            pipelineLatency.add(Date.now() - batchStart);
            taskCompletionRate.add(status === 'SUCCESS');
            break;
          }
        } catch { }
      }
      sleep(2);
    }
  });
}

// ======================== 全局配置 ========================

export const options = {
  scenarios: {
    asyncSubmit: {
      executor: 'constant-vus',
      vus: config.stages?.asyncSubmit?.vu || 30,
      duration: config.stages?.asyncSubmit?.duration || '5m',
      exec: 'scenarioAsyncSubmit',
      tags: { scenario: 'async-submit' },
      gracefulStop: '30s',
    },
    dispatchRoute: {
      executor: 'constant-vus',
      vus: config.stages?.dispatchRoute?.vu || 20,
      duration: config.stages?.dispatchRoute?.duration || '5m',
      exec: 'scenarioDispatchRoute',
      tags: { scenario: 'dispatch-route' },
      gracefulStop: '30s',
    },
    concurrencyBurst: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 80 },
        { duration: '1m', target: 80 },
        { duration: '30s', target: 0 },
      ],
      exec: 'scenarioConcurrencyBurst',
      tags: { scenario: 'concurrency-burst' },
      gracefulStop: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['avg<200', 'p(95)<500'],
    async_task_completion_rate: ['rate>0.99'],
    outbox_dispatch_latency_ms: ['p(95)<5000'],
    pipeline_end_to_end_latency_ms: ['p(95)<60000'],
    async_dead_letter_total: ['count<5'],
  },
};

export default function () {
  scenarioAsyncSubmit();
}
