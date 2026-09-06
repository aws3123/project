/**
 * 场景3：300 个 SSE 长连接 + 10% 随机断线重连补偿验证
 *
 * 验证目标（对应简历：300 个 SSE 长连接，随机 10% 断线，重连后基于
 * Redis 事件快照增量追平，无事件丢失）：
 *   - 300 个并发 SSE 长连接全部建连成功
 *   - 其中 10%（每第 DROP_EVERY 个 VU，默认 300/10 = 30 个）在收到若干事件后
 *     主动断开（模拟断线），随后携带 lastEventId 重连
 *   - 重连后服务端基于 Redis Stream 事件快照（ReviewStreamEventStore）从
 *     断点之后重放 + 尾随，客户端校验三个一致性指标：
 *       Lost Events   = 0（断点之后重放必须严格衔接，且最终收到 run_finished）
 *       Duplicate     = 0（同一事件 ID 出现超过一次）
 *       Out-of-order  = 0（事件 ID 序列严格单调递增）
 *
 * 链路说明：
 *   首连：POST /api/review/sync/stream（mode=SYNC，taskId 由脚本预置，
 *         便于断线后重连寻址）；SSE 事件 ID = Redis Stream RecordId
 *         （任务维度严格单调递增）。
 *   重连：GET /api/review/tasks/{taskId}/stream?lastEventId=<anchor>，
 *         NotificationController 走 StreamResumeService：先重放 anchor 之后的
 *         历史事件（Redis 快照），再尾随实时新事件直至终态。
 *   心跳（heartbeat）事件不写入 Redis 缓存、不参与重放，故不纳入
 *   三个一致性指标的校验（仅计数总量）。
 *
 * 前置要求：
 *   - k6 ≥ v0.53（`k6/x/sse` 扩展自动解析），或用 xk6 构建：
 *     xk6 build --with github.com/phymbert/xk6-sse@latest
 *   - 后端 Redis 事件缓存已启用（review.stream.cache.enabled=true）
 *
 * 运行：
 *   k6 run k6/scenarios/sse_300.js
 *   k6 run --env VUS=300 --env DROP_EVERY=10 k6/scenarios/sse_300.js
 */

import sse from 'k6/x/sse';
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import { BASE_URL, HEADERS, makeSyncStreamPayload } from '../config.js';

const VUS = parseInt(__ENV.VUS || '300', 10);                      // SSE 长连接数
const DROP_EVERY = parseInt(__ENV.DROP_EVERY || '10', 10);         // 每第 N 个 VU 断线一次 → 10% 断线
const DROP_AFTER_EVENTS = parseInt(__ENV.DROP_AFTER_EVENTS || '3', 10); // 收到 N 个事件后主动断开
const DIFF_SIZE = __ENV.DIFF_SIZE || 'small';

const EXPECTED_DROPS = Math.floor(VUS / DROP_EVERY);               // 预期断线重连次数（300/10=30）

// ---------- 自定义指标 ----------
const sseConnectOk = new Counter('sse_connect_ok');        // 首连建连成功数
const sseEventTotal = new Counter('sse_event_total');      // 收到的 SSE 事件总数（含心跳）
const sseReconnectAttempt = new Counter('sse_reconnect_attempt'); // 主动断线重连尝试数
const sseReconnectOk = new Counter('sse_reconnect_ok');    // 重连建连成功数
const reconnectLatency = new Trend('sse_reconnect_latency'); // 断线→重连成功耗时(ms)
const sseLost = new Counter('sse_lost');                   // 丢失：断点未衔接 / 终态事件缺失
const sseDuplicate = new Counter('sse_duplicate');         // 重复：同一事件 ID 收到多次
const sseOutOfOrder = new Counter('sse_out_of_order');     // 乱序：事件 ID 未严格递增
const sseTerminalOk = new Counter('sse_terminal_ok');      // 最终收到 run_finished 的连接数

const STREAM_HEADERS = Object.assign({}, HEADERS, { Accept: 'text/event-stream' });

export const options = {
  scenarios: {
    sse_load: {
      executor: 'per-vu-iterations',
      vus: VUS,             // 300 VU 同时挂 300 条 SSE 长连接
      iterations: 1,        // 每 VU 一个任务流（首连 + 可选重连）
      maxDuration: '5m',
    },
  },
  thresholds: {
    sse_connect_ok: [`count>=${Math.max(1, VUS - 1)}`],           // 几乎全部建连成功
    sse_reconnect_ok: [`count>=${EXPECTED_DROPS}`],                // 断线的全部重连成功
    sse_terminal_ok: [`count>=${Math.max(1, VUS - 1)}`],           // 几乎全部收到终态
    sse_lost: ['count==0'],                                        // 零丢失
    sse_duplicate: ['count==0'],                                   // 零重复
    sse_out_of_order: ['count==0'],                                // 零乱序
  },
  tags: { scenario: 'sse_300' },
};

/**
 * 记录事件 ID 一致性视角的事件：
 * - 跳过 heartbeat（不写入 Redis 缓存、不参与重放，非对账口径）
 * - 同一 ID 重复出现 → sse_duplicate
 * - ID 序列未严格递增 → sse_out_of_order
 * 说明：事件 ID 为 Redis Stream RecordId（"毫秒-序号"，等宽数字），
 * 字符串比较即为时序比较；Redis 不可用时的降级 ID "taskId-N" 亦按此近似校验。
 */
function track(state, ev) {
  if (!ev.id) return;
  if (state.seen.has(ev.id)) {
    sseDuplicate.add(1);
    return;
  }
  state.seen.add(ev.id);
  if (state.ids.length > 0 && ev.id <= state.ids[state.ids.length - 1]) {
    sseOutOfOrder.add(1);
  }
  state.ids.push(ev.id);
}

export default function () {
  const taskId = `sse-${__VU}-${__ITER}-${Date.now()}`;
  const payload = makeSyncStreamPayload(taskId, DIFF_SIZE);
  const isDropVU = (__VU % DROP_EVERY) === 0; // 每第 DROP_EVERY 个 VU 注入一次断线

  const state = { ids: [], seen: new Set() };
  let terminal = false;    // 是否收到 run_finished
  let dropDone = false;    // 本次断线是否已执行
  let dropAt = null;       // 断线时刻（用于重连耗时）
  let trackCount = 0;      // 已记录的（非心跳）事件数，控制断线时机

  // ---------- 首连：任务触发 + 实时事件流 ----------
  const resA = sse.open(`${BASE_URL}/api/review/sync/stream`, {
    method: 'POST',
    headers: STREAM_HEADERS,
    body: payload,
    tags: { name: 'sse_stream_connect' },
  }, function (client) {
    client.on('open', function () {
      sseConnectOk.add(1);
    });
    client.on('event', function (ev) {
      sseEventTotal.add(1);
      if (ev.name === 'heartbeat') return;

      // 断线注入：收到 DROP_AFTER_EVENTS 个事件后在任务进行中主动掐断连接
      if (isDropVU && !dropDone) {
        trackCount += 1;
        if (trackCount >= DROP_AFTER_EVENTS) {
          dropDone = true;
          dropAt = Date.now();
          client.close(); // 模拟网络断线，后续事件不再到达
          return;
        }
      }
      if (ev.name === 'run_finished') terminal = true;
      track(state, ev);
    });
    client.on('error', function (e) {
      if (!dropDone) {
        // 非主动断线导致的首连错误才值得告警（主动 close 触发的 error 忽略）
        console.warn(`sse stream error taskId=${taskId}: ${e.error()}`);
      }
    });
  });
  check(resA, { 'stream connect status 200': (r) => r && r.status === 200 });

  // ---------- 断线 VU：携带 lastEventId 重连，校验增量追平 ----------
  if (isDropVU && dropDone) {
    sseReconnectAttempt.add(1);
    const anchor = state.ids.length > 0 ? state.ids[state.ids.length - 1] : null;
    const url = `${BASE_URL}/api/review/tasks/${taskId}/stream`
      + (anchor ? `?lastEventId=${encodeURIComponent(anchor)}` : '');

    const resB = sse.open(url, {
      method: 'GET',
      headers: STREAM_HEADERS,
      tags: { name: 'sse_reconnect' },
    }, function (client) {
      client.on('open', function () {
        sseReconnectOk.add(1);
        reconnectLatency.add(Date.now() - dropAt);
      });
      client.on('event', function (ev) {
        sseEventTotal.add(1);
        if (ev.name === 'heartbeat') return;

        // 断点衔接校验：重放/尾随的每个事件必须严格位于 anchor 之后，
        // 否则说明服务端未按快照增量追平（丢失或回溯）
        if (anchor !== null && ev.id && ev.id <= anchor) {
          sseLost.add(1);
        }
        if (ev.name === 'run_finished') terminal = true;
        track(state, ev);
      });
      client.on('error', function (e) {
        console.warn(`sse reconnect error taskId=${taskId}: ${e.error()}`);
      });
    });
    check(resB, { 'reconnect status 200': (r) => r && r.status === 200 });
  }

  // ---------- 终态校验：最终连接必须收到 run_finished，否则视为事件丢失 ----------
  if (terminal) {
    sseTerminalOk.add(1);
  } else {
    sseLost.add(1);
    console.warn(`taskId=${taskId} finished without run_finished`);
  }
}