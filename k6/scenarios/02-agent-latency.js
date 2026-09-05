// k6 load test — 指标2: 多Agent 并行 vs 串行延迟对比
//
// 对应简历口径：三路 Agent 并发（规则/安全/性能）+ 动态裁剪，相比串行编排平均延迟降低约 40%
// 数值口径：SSE 流式事件实测 端到端延迟 vs Σ各节点耗时(≈串行估算)，
//          并行收益 = (串行估算 − 端到端) / 串行估算（目标 ≈40%；全并行理论上限 66.7%）。
//
// 两档延迟锚点（口径分层，勿混用）：
//   - 典型 diff（~5文件/300行，真实 LLM）：串行估算 ~16s → 并行 ~9.5s（40%）
//   - mock 校准档（小 diff，用于指标1 同套环境）：~8s → ~5s
//   百分比收益两档一致，绝对值随 diff 规模缩放。
//
// 实现思路：
//   触发 /api/review/sync/stream → 解析 SSE 帧进度：
//     - run_started(totalSteps)   ：识别有多少个 Agent 节点
//     - step_finished(durationMs) ：各节点自己的执行耗时
//     - run_finished              ：端到端终态
//   串行估算 = Σ(各 step durationMs)；并行收益 = (串行估算 − 端到端) / 串行估算。
//
// 运行:
//   k6 run -e VUS=30 -e DURATION=5m k6/scenarios/02-agent-latency.js --summary-trend-stats="avg,p(95)"

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const config = JSON.parse(open('../config.js'));
let helpers;
try { helpers = eval('(' + open('../lib/helpers.js') + ')'); } catch (e) { helpers = null; }

const VUS = Number(__ENV.VUS || config.stages.latencyCompare.vu || 30);
const DURATION = __ENV.DURATION || config.stages.latencyCompare.duration || '5m';

const e2eLatency = new Trend('pipeline_e2e_ms');
const serialEstimate = new Trend('serial_estimate_ms');
const parallelSavings = new Trend('parallel_savings_pct');
const totalStepsGauge = new Trend('agent_node_count');

export const options = {
  scenarios: {
    latencyCompare: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
      tags: { scenario: 'latency-compare' },
      gracefulStop: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
  },
};

export default function () {
  group('Multi-Agent Parallel Latency', function () {
    const diffContent = helpers
      ? helpers.buildTypicalDiff('agents')
      : ('diff --git a/A.java b/A.java\n- old\n+ new\n-- placeholder');

    const payload = JSON.stringify({
      taskId: `k6-agent-${__VU}-${__ITER}`,
      projectId: 'proj-agent',
      projectName: 'proj-agent',
      prUrl: 'https://github.com/org/repo/pull/2',
      diffContent,
      mode: 'SYNC',
    });

    const start = Date.now();
    const res = http.post(
      `${config.baseUrl}${config.endpoints.syncStream}`,
      payload,
      {
        headers: helpers ? helpers.traceHeaders(config.apiKey, 'k6-agent') : { 'Content-Type': 'application/json', 'X-API-Key': config.apiKey },
        timeout: '120s',
      }
    );
    const e2e = Date.now() - start;
    e2eLatency.add(e2e);

    let frames = [];
    if (helpers && res.body) {
      frames = helpers.parseSse(res.body);
    }

    let totalSteps = 0;
    let sumStepMs = 0;
    let sawRunFinished = false;
    for (const f of frames) {
      if (f.event === 'run_started') {
        try { totalSteps = JSON.parse(f.data).totalSteps || 0; } catch (e) {}
      } else if (f.event === 'step_finished') {
        try { sumStepMs += JSON.parse(f.data).durationMs || 0; } catch (e) {}
      } else if (f.event === 'run_finished') {
        sawRunFinished = true;
      }
    }
    totalStepsGauge.add(Math.max(totalSteps, 1));

    // 串行估算：各节点耗时之和（若三路 Agent 真并行，端到端显著小于该和）
    serialEstimate.add(sumStepMs);
    if (sumStepMs > 0 && e2e > 0) {
      const savings = ((sumStepMs - e2e) / sumStepMs) * 100;
      // 收益可能为负（e2e 含 HTTP 往返与排队，小负载下骨架段占比高）——如实记录，
      // summary 取 avg；40% 是典型 diff 下的预期均值，不是逐请求下限。
      parallelSavings.add(Math.min(Math.max(savings, -100), 100));
    }

    check({ status: res.status, sawRunFinished, totalSteps }, {
      'stream returns 200': (o) => o.status === 200,
      'pipeline reaches terminal run_finished': (o) => o.sawRunFinished,
      'multi-stage pipeline detected (totalSteps>=1)': (o) => o.totalSteps >= 1,
    });
  });

  sleep(0.2);
}
