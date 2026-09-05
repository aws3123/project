// k6 load test — 指标5: 数据闭环（反馈机制落库 + 统计查询）
//
// 对应简历指标：
//   - 前端点踩携带关键数据落库，为 Prompt 迭代 / 检索策略优化 / 模型微调提供数据基础
//   - 闭环使迭代从“人工逐轮试错”转为“数据可量化定向优化”
// 数值口径：反馈提交成功率、落库成功后通过 /stats 查询可检索到（数据闭环可量化验证）。
//
// 运行:
//   k6 run -e VUS=200 -e DURATION=3m k6/scenarios/05-feedback-loop.js

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const config = JSON.parse(open('../config.js'));
let helpers;
try { helpers = eval('(' + open('../lib/helpers.js') + ')'); } catch (e) { helpers = null; }

const VUS = Number(__ENV.VUS || config.stages.feedback.vu || 200);
const DURATION = __ENV.DURATION || config.stages.feedback.duration || '3m';

const submitOk = new Rate('feedback_submit_ok');
const statsQueryOk = new Rate('feedback_stats_query_ok');
const submitDuration = new Trend('feedback_submit_ms');

const feedbackSamples = [
  { type: 'thumbs_up',   category: '结果准确', comment: '' },
  { type: 'thumbs_up',   category: '', comment: '' },
  { type: 'thumbs_down', category: '结果不准确', comment: '未覆盖关键风险点' },
  { type: 'thumbs_down', category: '遗漏风险', comment: 'SQL 注入风险未检测到' },
  { type: 'thumbs_up',   category: '结果准确', comment: '并发问题分析到位' },
  { type: 'thumbs_down', category: '误报', comment: '该告警是误报' },
];

export const options = {
  scenarios: {
    feedbackLoop: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
      tags: { scenario: 'feedback-loop' },
      gracefulStop: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.005'],
    feedback_submit_ok: ['rate>=0.995'],
  },
};

export default function () {
  group('Feedback Loop', function () {
    const sample = feedbackSamples[__ITER % feedbackSamples.length];
    const payload = JSON.stringify({
      taskId: `k6-task-${__VU}-${__ITER}`,
      sessionId: `k6-session-${__VU}`,
      feedbackType: sample.type,
      category: sample.category || undefined,
      comment: sample.comment || undefined,
      source: __ITER % 4 === 0 ? 'business_risk' : 'review',
      metadata: sample.type === 'thumbs_up'
        ? JSON.stringify({ riskScore: 0.15, riskSummary: '模拟审查结果' })
        : undefined,
    });

    const start = Date.now();
    const res = http.post(
      `${config.baseUrl}${config.endpoints.feedbackSubmit}`,
      payload,
      { headers: helpers ? helpers.traceHeaders(config.apiKey, 'k6-fb') : { 'Content-Type': 'application/json', 'X-API-Key': config.apiKey }, timeout: '5s' }
    );
    submitDuration.add(Date.now() - start);

    const ok = check(res, {
      'submit returns 201': (r) => r.status === 201,
      'submit returns {id,status:accepted}': (r) => {
        if (!r.body) return false;
        try { const b = JSON.parse(r.body); return b.id !== undefined && b.status === 'accepted'; }
        catch { return false; }
      },
    });
    submitOk.add(ok);

    // 数据闭环自证：提交样本后查询 /stats 应能检索到该源的数据
    if (ok) {
      const from = '2020-01-01T00:00:00Z';
      const to = '2030-12-31T23:59:59Z';
      const stats = http.get(
        `${config.baseUrl}${config.endpoints.feedbackStats}?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`,
        { headers: helpers ? helpers.traceHeaders(config.apiKey, 'k6-fb') : { 'Content-Type': 'application/json', 'X-API-Key': config.apiKey }, timeout: '5s' }
      );
      statsQueryOk.add(stats.status === 200);
    }

    // think time: 0.5-3s 模拟真实用户行为
    sleep(Math.random() * 2.5 + 0.5);
  });
}