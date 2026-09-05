// k6 load test — 指标1: 分层架构解耦端到端吞吐对比
//
// 对应简历口径：k6（1000 并发/5min）端到端审查吞吐 42→202 req/s（4.8×），平均延迟 24s→5s
// 数值口径：本脚本不写死 42/202/24/5，而是产出真实实测值：
//   - 吞吐     = summary 中 http_reqs 的 count ÷ duration（或直接看 http_reqs avg）
//   - 平均延迟 = http_req_duration 的 avg —— 并用 Little's Law 交叉验证：
//       平均延迟 ≈ VU 数 ÷ 吞吐（1000÷42≈24s / 1000÷202≈5s，实测与推算对得上=数据自洽）
//
// 分层语义：
//   baseline  → 直打 Python 聚合端点 /ai/review/sync（Python 单实例同时承担
//               AST 解析+上下文拼装+LLM IO，GIL 争用，在途调用天花板 ~250）
//   optimized → 走 Java BFF 同步入口（AST/上下文前置到 Java，Python 纯 IO 多实例，
//               信号量 4×250 对齐 LLM 并发配额）
//
// ⚠️ 前提：LLM 用延迟校准过的 mock（校准层 10 并发真实调用采样标定 ~5s/审查）。
//   对付费 API 直打 1000 并发既昂贵也不可控；排队延迟是架构造成的数学结果，
//   与 LLM 真假无关。
//
// 运行命令（两次；取 summary 中 http_reqs avg 与 http_req_duration avg）：
//   k6 run -e MODE=baseline  -e VUS=1000 -e DURATION=5m k6/scenarios/01-throughput.js --summary-trend-stats="avg,p(50),p(95)"
//   k6 run -e MODE=optimized -e VUS=1000 -e DURATION=5m k6/scenarios/01-throughput.js --summary-trend-stats="avg,p(50),p(95)"
//
// 结果解读：
//   提升倍数 = optimized http_reqs avg ÷ baseline http_reqs avg
//   Little's Law 自洽检查：baseline avg 延迟 ≈ 1000÷baseline吞吐；optimized 同理
//   （若对不上 → 压测未到稳态或有请求未走完整链路，数据不可用）

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const config = JSON.parse(open('../config.js'));

// 复用共享工具
let helpers;
try {
  helpers = eval('(' + open('../lib/helpers.js') + ')');
} catch (e) {
  helpers = null;
}

const MODE = __ENV.MODE || 'optimized'; // baseline | optimized
const VUS = Number(__ENV.VUS || config.stages.throughput.vu || 1000);
const DURATION = __ENV.DURATION || config.stages.throughput.duration || '5m';

const TARGET = MODE === 'baseline'
  ? `${config.pyBaseUrl}/ai/review/sync`              // Python 单实例（含 AST 解析）
  : `${config.baseUrl}${config.endpoints.sync}`;      // Java BFF（AST 前置）

// 端到端延迟（覆盖 Little's Law 校验：avg ≈ VU ÷ 吞吐）
const e2eLatency = new Trend('e2e_review_ms', true);
const okRate = new Rate('review_ok_rate');

export const options = {
  scenarios: {
    throughputCompare: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
      tags: { scenario: 'throughput-compare', mode: MODE },
      gracefulStop: '30s',
    },
  },
  thresholds: {
    // baseline 模式下排队严重、延迟高是预期（这正是要测的现象），只断言请求成功率
    http_req_failed: ['rate<0.02'],
  },
};

export default function () {
  const diffContent = helpers
    ? helpers.buildTypicalDiff(MODE)
    : ('diff --git a/A.java b/A.java\n- old\n+ new\n-- k6 placeholder\n');

  const payload = {
    taskId: `k6-layer-${MODE}-${__VU}-${__ITER}`,
    projectId: 'proj-thr',
    projectName: 'proj-thr',
    prUrl: 'https://github.com/org/repo/pull/1',
    diffContent,
    mode: 'SYNC',
  };

  const res = http.post(TARGET, JSON.stringify(payload), {
    headers: helpers ? helpers.traceHeaders(config.apiKey, 'k6-layer') : { 'Content-Type': 'application/json', 'X-API-Key': config.apiKey },
    timeout: '60s',
  });

  e2eLatency.add(res.timings.duration);
  okRate.add(check(res, {
    'request accepted (2xx)': (r) => r.status >= 200 && r.status < 300,
  }));

  // 吞吐测试：think time 极小，压力集中后端（排队行为由 VU 数量驱动）
  sleep(0.05);
}

// 结果摘要：把 Little's Law 自洽检查直接打进 summary
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.3/index.js';
export function handleSummary(data) {
  const reqs = data.metrics.http_reqs ? data.metrics.http_reqs.values : null;
  const dur = data.metrics.e2e_review_ms ? data.metrics.e2e_review_ms.values : null;
  const lines = [
    '\n===== 指标1 结果解读（MODE=' + MODE + '）=====',
    '实测吞吐    : ' + (reqs ? reqs.rate.toFixed(1) : 'n/a') + ' req/s',
    '实测平均延迟: ' + (dur ? (dur.avg / 1000).toFixed(1) : 'n/a') + ' s',
    'Little 推算 : ' + (reqs ? (VUS / reqs.rate).toFixed(1) : 'n/a') + ' s  (VU÷吞吐，应≈平均延迟)',
    '待验证锚点  : baseline 预期 ~42 req/s/~24s；optimized 预期 ~202 req/s/~5s',
    '提升倍数    : 需两次运行后手工计算 optimized÷baseline（预期 ~4.8×）',
  ];
  const summary = textSummary(data) + lines.join('\n') + '\n';
  return { stdout: summary };
}
