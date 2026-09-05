// k6 load test — 指标4: 流式输出（SSE）与异步高可用（全量对账版）
//
// 对应简历口径：
//   - 基于 SSE 实现 Agent 节点结果流式推送与断线重连（Last-Event-ID 快照+增量追平）
//   - 异步链路（Outbox → Kafka → Python 消费 → 回调）稳态/突发下任务零丢失、零死信
//   - 500 并发突发造成积压后，消费侧按设计能力（~200 task/s = 4×250信号量÷5s）消化恢复
//
// 场景设计（与 config.js 统一口径）：
//   asyncStable      constant-arrival-rate 200 req/s × 30m（消费能力设计值）
//                    每次迭代：提交异步任务 → 轮询至终态（逐任务对账）
//                    采样：SSE 流式 run_finished 可达；任务流 Last-Event-ID 断线重连追平
//   concurrencyBurst ramping-vus 0→500→保持1m→0（叠加在稳态之上）
//                    每次迭代：批量提交 5 个任务 → 全部轮询至终态（批量全量对账）
//
// 零丢失对账（k6 跨 VU 无法共享 ID 列表，采用"迭代内全量确认 + 计数对账"）：
//   - 每个任务在提交它的迭代内被轮询到终态（或超时计入缺口），样本无遗漏
//   - async_submitted_total(202受理) vs async_terminal_total(终态，含DEAD)
//   - 缺口 async_reconcile_gap = 提交 − 终态（阈值 count<1 即零丢失）
//   - 死信 async_dead_letter_total（阈值 count<1）
//   - 突发段 async_task_e2e_s 的 max ≈ 积压消化（恢复）耗时
//
// 运行:
//   冒烟:  k6 run -e STABLE_DURATION=5m k6/scenarios/04-streaming-availability.js
//   全量:  k6 run k6/scenarios/04-streaming-availability.js    # 200 req/s × 30m + 500 并发突发
//   自定义: k6 run -e STABLE_RATE=100 -e BURST_TARGET=300 -e STABLE_DURATION=10m ...
//   注意: 200 req/s 稳态下在途 VU 约 1200+，突发叠加段峰值可达 ~5000，压测机需预留内存；
//          机器不足时用 -e STABLE_RATE=50 降档。

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.3/index.js';

const config = JSON.parse(open('../config.js'));
let helpers;
try { helpers = eval('(' + open('../lib/helpers.js') + ')'); } catch (e) { helpers = null; }

const STABLE_RATE = Number(__ENV.STABLE_RATE || config.stages.asyncStableRate || 200);
const STABLE_DURATION = __ENV.STABLE_DURATION || config.stages.asyncStableDuration || '30m';
const BURST_TARGET = Number(__ENV.BURST_TARGET || config.stages.asyncBurstTarget || 500);

// 终态集合（DEAD 单独处理：到达终态但计入死信）
const TERMINAL = ['SUCCESS', 'FAILED', 'HUMAN_REVIEW', 'NEED_REVIEW'];

const submitOk = new Rate('async_submit_ok');
const taskTerminalRate = new Rate('async_task_terminal_rate');
const deadLetter = new Counter('async_dead_letter_total');
const submittedTotal = new Counter('async_submitted_total');
const terminalTotal = new Counter('async_terminal_total');
const reconcileGap = new Counter('async_reconcile_gap');
const taskE2e = new Trend('async_task_e2e_s');
const sseStreamOk = new Rate('sse_stream_ok');
const sseReconnectOk = new Rate('sse_reconnect_ok');

export const options = {
  scenarios: {
    asyncStable: {
      executor: 'constant-arrival-rate',
      rate: STABLE_RATE,
      timeUnit: '1s',
      duration: STABLE_DURATION,
      preAllocatedVUs: 50,
      maxVUs: 5000,
      exec: 'scenarioStable',
      tags: { scenario: 'async-stable' },
      gracefulStop: '150s', // 覆盖最长对账窗口(60轮×2s)，避免收尾截断造成误判丢失
    },
    concurrencyBurst: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: BURST_TARGET },
        { duration: '1m', target: BURST_TARGET },
        { duration: '30s', target: 0 },
      ],
      exec: 'scenarioBurst',
      tags: { scenario: 'concurrency-burst' },
      gracefulStop: '120s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
    async_submit_ok: ['rate>=0.99'],
    async_task_terminal_rate: ['rate>0.99'],
    async_dead_letter_total: ['count<1'],   // 零死信
    async_reconcile_gap: ['count<1'],       // 零缺口 = 任务零丢失
  },
};

function headers(tag) {
  return helpers
    ? helpers.traceHeaders(config.apiKey, tag)
    : { 'Content-Type': 'application/json', 'X-API-Key': config.apiKey };
}

function submitAsync(taskId, tag) {
  const diffContent = helpers
    ? helpers.buildTypicalDiff(tag)
    : ('diff --git a/A.java b/A.java\n- old\n+ new\n-- placeholder');
  const payload = JSON.stringify({
    taskId,
    projectId: `proj-${tag}`,
    projectName: `proj-${tag}`,
    prUrl: 'https://github.com/org/repo/pull/4',
    diffContent,
    mode: 'ASYNC',
  });
  const res = http.post(
    `${config.baseUrl}${config.endpoints.async}`,
    payload,
    { headers: headers(tag), timeout: '10s' }
  );
  const ok = check(res, { 'async accepted (202)': (r) => r.status === 202 });
  submitOk.add(ok);
  if (res.status === 202) submittedTotal.add(1); // 只有受理成功的任务才进入对账分母
  return ok;
}

// 批量对账：round-robin 轮询，直到全部终态或超时轮数耗尽。
// 返回 { ok, dead, gap }；gap>0 表示受理后未到达终态（疑似丢失），计入 reconcileGap。
function reconcileBatch(tasks, scenarioTag, maxRounds, pollSecs) {
  const pending = tasks.slice();
  let dead = 0;
  for (let round = 0; round < maxRounds && pending.length > 0; round++) {
    for (let i = pending.length - 1; i >= 0; i--) {
      const t = pending[i];
      const r = http.get(
        `${config.baseUrl}${config.endpoints.taskById}/${t.id}`,
        { headers: headers('k6-async'), timeout: '5s' }
      );
      let st = null;
      if (r.status === 200 && r.body) {
        try { st = JSON.parse(r.body).task?.status; } catch (e) {}
      }
      if (st === 'DEAD' || TERMINAL.includes(st)) {
        taskTerminalRate.add(true);
        terminalTotal.add(1);
        taskE2e.add((Date.now() - t.submittedAt) / 1000, { scenario: scenarioTag });
        if (st === 'DEAD') { dead += 1; deadLetter.add(1); }
        pending.splice(i, 1);
      }
    }
    if (pending.length > 0) sleep(pollSecs);
  }
  for (let i = 0; i < pending.length; i++) taskTerminalRate.add(false); // 超时未终态
  const gap = pending.length;
  if (gap > 0) reconcileGap.add(gap);
  return { ok: tasks.length - gap, dead, gap };
}

// SSE 流式采样：POST /sync/stream 全量读Body，断言 run_finished 可达
function sseStreamProbe() {
  const diffContent = helpers ? helpers.buildTypicalDiff('sse') : ('x');
  const res = http.post(
    `${config.baseUrl}${config.endpoints.syncStream}`,
    JSON.stringify({
      taskId: `k6-sse-${__VU}-${__ITER}`,
      projectId: 'proj-sse', projectName: 'proj-sse',
      prUrl: 'https://github.com/org/repo/pull/5', diffContent, mode: 'SYNC',
    }),
    { headers: headers('k6-sse'), timeout: '120s' }
  );
  let reached = false;
  if (helpers && res.body) {
    reached = helpers.parseSse(res.body).some((f) => f.event === 'run_finished');
  }
  sseStreamOk.add(reached && res.status === 200);
}

// 断线重连采样（复用本迭代已终态的任务，不额外制造到达率）：
//   1) 全量拉一次任务流（Redis 快照+增量），取中点事件 id 作为断线锚点
//   2) 带 Last-Event-ID 重连，校验追平语义：收到的事件 seq 均大于锚点（不重复旧事件）
//   观测项，不计入硬门禁（服务端语义若不同会在此暴露）
function sseReconnectProbe(taskId) {
  const streamUrl = `${config.baseUrl}${config.endpoints.taskStream}/${taskId}/stream`;
  const r1 = http.get(streamUrl, { headers: headers('k6-sse'), timeout: '15s' });
  const frames1 = (r1.status === 200 && r1.body && helpers) ? helpers.parseSse(r1.body) : [];
  if (frames1.length < 2) { sseReconnectOk.add(false); return; }
  const anchor = frames1[Math.floor(frames1.length / 2)].id;
  if (anchor === null || anchor === undefined) { sseReconnectOk.add(false); return; }
  const anchorSeq = Number(String(anchor).split('-').pop());
  if (Number.isNaN(anchorSeq)) { sseReconnectOk.add(false); return; }

  const r2 = http.get(streamUrl, {
    headers: Object.assign(headers('k6-sse'), { 'Last-Event-ID': String(anchor) }),
    timeout: '15s',
  });
  const frames2 = (r2.status === 200 && r2.body && helpers) ? helpers.parseSse(r2.body) : [];
  const seqs = frames2
    .map((f) => (f.id === null || f.id === undefined ? NaN : Number(String(f.id).split('-').pop())));
  const ok = seqs.length > 0 && seqs.every((s) => !Number.isNaN(s) && s > anchorSeq);
  sseReconnectOk.add(ok);
}

// 稳态：固定到达速率提交 → 逐任务对账到终态；周期性采样 SSE 可达性/断线重连
export function scenarioStable() {
  group('Stable Async (arrival-rate)', function () {
    const taskId = `k6-stable-${__VU}-${__ITER}`;
    if (submitAsync(taskId, 'k6-stable')) {
      const submittedAt = Date.now();
      reconcileBatch([{ id: taskId, submittedAt }], 'async-stable', 60, 2);
      if (__ITER % 50 === 25) sseReconnectProbe(taskId);
    }
    if (__ITER % 20 === 7) sseStreamProbe(); // 错开 __ITER=0，避免 VU 启动期采样集中触发
  });
}

// 突发：批量提交 5 个 → 全量对账（等待过程即削峰后的消化过程，e2e 反映积压恢复耗时）
export function scenarioBurst() {
  group('Concurrency Burst (batch + full reconcile)', function () {
    const batchSize = 5;
    const tasks = [];
    const submittedAt = Date.now();
    for (let i = 0; i < batchSize; i++) {
      const taskId = `k6-burst-${__VU}-${__ITER}-${i}`;
      if (submitAsync(taskId, 'k6-burst')) tasks.push({ id: taskId, submittedAt });
    }
    reconcileBatch(tasks, 'concurrency-burst', 90, 1);
  });
}

// 所有 scenario 均已通过 exec 指定执行函数，default 不会被执行（保留兜底）
export default function () {
  scenarioStable();
}

// 结果摘要：零丢失对账报告
export function handleSummary(data) {
  const m = data.metrics || {};
  const cnt = (name) => (m[name] && m[name].values ? (m[name].values.count || 0) : 0);
  const submitted = cnt('async_submitted_total');
  const terminal = cnt('async_terminal_total');
  const dead = cnt('async_dead_letter_total');
  const gap = cnt('async_reconcile_gap');
  const dropped = cnt('dropped_iterations');
  const burstE2e = m['async_task_e2e_s{scenario:concurrency-burst}']
    ? m['async_task_e2e_s{scenario:concurrency-burst}'].values : null;
  const rate = (name) => (m[name] ? (m[name].values.rate * 100).toFixed(1) + '%' : 'n/a');
  const lines = [
    '\n===== 指标4 零丢失对账报告 =====',
    '提交受理(202)     : ' + submitted,
    '到达终态(含DEAD)  : ' + terminal,
    '死信 DEAD         : ' + dead,
    '对账缺口(疑似丢失): ' + gap + '  （' + (gap === 0 ? '零丢失 PASS' : '存在丢失 FAIL') + '）',
    '突发段任务e2e     : max=' + (burstE2e && burstE2e.max ? burstE2e.max.toFixed(1) : 'n/a')
      + 's p(95)=' + (burstE2e && burstE2e['p(95)'] ? burstE2e['p(95)'].toFixed(1) : 'n/a')
      + 's （≈积压消化/恢复耗时）',
    'SSE 流式可达率    : ' + rate('sse_stream_ok'),
    'SSE 重连追平率    : ' + rate('sse_reconnect_ok') + '（观测项，不计入门禁）',
    '丢弃迭代         : ' + dropped + (dropped > 0 ? '  ← 到达率未满足（压测机/maxVUs不足，非任务丢失）' : ''),
  ];
  return { stdout: textSummary(data) + lines.join('\n') + '\n' };
}
