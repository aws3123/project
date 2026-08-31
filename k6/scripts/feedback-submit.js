// k6 load test — feedback submit
// Simulates 200 concurrent users submitting feedback for 3 minutes.
// Validates: success rate >= 99.5%, P99 duration <= 120ms

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import { SharedArray } from 'k6/data';

const config = JSON.parse(open('../config.js'));

// Custom metrics
const feedbackSuccess = new Rate('feedback_submit_success');
const feedbackDuration = new Trend('feedback_submit_duration_ms');

// Realistic feedback payloads
const feedbackSamples = new SharedArray('feedback-samples', function () {
  return [
    {
      feedbackType: 'thumbs_up',
      category: '结果准确',
      comment: '',
    },
    {
      feedbackType: 'thumbs_up',
      category: '',
      comment: '',
    },
    {
      feedbackType: 'thumbs_down',
      category: '结果不准确',
      comment: '审查结果没有覆盖到关键风险点',
    },
    {
      feedbackType: 'thumbs_down',
      category: '遗漏风险',
      comment: '这个 SQL 注入风险没有检测出来',
    },
    {
      feedbackType: 'thumbs_up',
      category: '结果准确',
      comment: '分析得很到位，特别是并发问题部分',
    },
    {
      feedbackType: 'thumbs_down',
      category: '误报',
      comment: '这个告警是误报，代码实际上是安全的',
    },
    {
      feedbackType: 'thumbs_up',
      category: '',
      comment: '很有帮助，谢谢',
    },
    {
      feedbackType: 'thumbs_down',
      category: '其他',
      comment: '界面加载太慢了',
    },
  ];
});

export const options = {
  scenarios: {
    feedbackSubmit: {
      executor: 'constant-vus',
      vus: 200,
      duration: '3m',
      exec: 'scenarioFeedbackSubmit',
      tags: { scenario: 'feedback-submit' },
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.005'],
    http_req_duration: ['avg<50', 'p(95)<100', 'p(99)<120'],
    feedback_submit_success: ['rate>=0.995'],
    feedback_submit_duration_ms: ['avg<50', 'p(95)<100', 'p(99)<120'],
  },
};

function traceHeaders() {
  return {
    'X-Trace-Id': `k6-fb-${__VU}-${__ITER}-${Date.now()}`,
    'X-API-Key': config.apiKey,
    'Content-Type': 'application/json',
  };
}

export function scenarioFeedbackSubmit() {
  group('Feedback Submit', function () {
    const sample = feedbackSamples[__ITER % feedbackSamples.length];
    const taskId = `k6-task-${__VU}-${__ITER}`;
    const sessionId = `k6-session-${__VU}`;

    const payload = JSON.stringify({
      taskId,
      sessionId,
      feedbackType: sample.feedbackType,
      category: sample.category || undefined,
      comment: sample.comment || undefined,
      source: __ITER % 4 === 0 ? 'business_risk' : 'review',
      metadata: sample.feedbackType === 'thumbs_up'
        ? JSON.stringify({ riskScore: 0.15, riskSummary: '模拟审查结果' })
        : undefined,
    });

    const start = Date.now();
    const res = http.post(`${config.baseUrl}/api/feedback/submit`, payload, {
      headers: traceHeaders(),
      timeout: '5s',
    });
    const elapsed = Date.now() - start;
    feedbackDuration.add(elapsed);

    const passed = check(res, {
      'status is 201': (r) => r.status === 201,
      'response has id and status': (r) => {
        if (!r.body) return false;
        try {
          const body = JSON.parse(r.body);
          return body.id !== undefined && body.status === 'accepted';
        } catch {
          return false;
        }
      },
    });

    feedbackSuccess.add(passed);

    // think time: 0.5-3s between submissions
    sleep(Math.random() * 2.5 + 0.5);
  });
}

export default function () {
  scenarioFeedbackSubmit();
}
