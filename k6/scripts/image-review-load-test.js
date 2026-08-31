// k6 load test — image review scenarios
// Simulates 100 concurrent users querying with image references for 3 minutes.
// Validates: image URL replacement success rate >= 99.8%, avg response <= 180ms, P95 <= 500ms

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { SharedArray } from 'k6/data';

const config = JSON.parse(open('../config.js'));

// Custom metrics
const imageUrlReplaceSuccess = new Rate('image_url_replace_success');
const responseTime = new Trend('response_time_ms');
const imageReplaceErrors = new Counter('image_replace_errors');

// Sample diff snippets that trigger image-related incident retrieval
const diffSamples = new SharedArray('diffs', function () {
  return [
    {
      projectId: 'proj-db',
      prLink: 'https://github.com/org/repo/pull/101',
      diffContent: 'DELETE FROM users WHERE id = ?;\n-- Missing WHERE clause check\n',
      question: '这个 DELETE 操作有风险吗？参考历史事故中的类似案例。',
    },
    {
      projectId: 'proj-gateway',
      prLink: 'https://github.com/org/repo/pull/102',
      diffContent: 'timeout: 100\n# Reduced from 500ms without capacity assessment',
      question: '超时配置变更有什么风险？',
    },
    {
      projectId: 'proj-order',
      prLink: 'https://github.com/org/repo/pull/103',
      diffContent: 'for (Order o : orders) { User u = userRepo.findById(o.getUserId()); }',
      question: '这个循环查询会导致 N+1 问题吗？',
    },
    {
      projectId: 'proj-auth',
      prLink: 'https://github.com/org/repo/pull/104',
      diffContent: 'if (token.expireTime < System.currentTimeMillis()) { refreshToken(token); }',
      question: 'Token 刷新逻辑是否正确？',
    },
    {
      projectId: 'proj-payment',
      prLink: 'https://github.com/org/repo/pull/105',
      diffContent: 'UPDATE accounts SET balance = balance - ? WHERE id = ?\n-- No version check',
      question: '并发扣款会有问题吗？',
    },
    {
      projectId: 'proj-cache',
      prLink: 'https://github.com/org/repo/pull/106',
      diffContent: 'Product p = cache.get(key);\nif (p == null) { p = db.query(key); }',
      question: '缓存策略有穿透风险吗？',
    },
  ];
});

export const options = {
  scenarios: {
    imageReview: {
      executor: 'constant-vus',
      vus: config.stages.imageReview.vu,
      duration: config.stages.imageReview.duration,
      exec: 'scenarioImageReview',
      tags: { scenario: 'image-review' },
    },
    imageDense: {
      executor: 'constant-vus',
      vus: config.stages.imageDense.vu,
      duration: config.stages.imageDense.duration,
      exec: 'scenarioImageDense',
      tags: { scenario: 'image-dense' },
    },
    codeSearch: {
      executor: 'constant-vus',
      vus: config.stages.codeSearch.vu,
      duration: config.stages.codeSearch.duration,
      exec: 'scenarioCodeSearch',
      tags: { scenario: 'code-search' },
    },
    mixed: {
      executor: 'constant-vus',
      vus: config.stages.mixed.vu,
      duration: config.stages.mixed.duration,
      exec: 'scenarioMixed',
      tags: { scenario: 'mixed' },
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['avg<200', 'p(95)<500'],
    image_url_replace_success: ['rate>0.998'],
    response_time_ms: ['avg<180', 'p(95)<500'],
  },
};

function checkImageUrls(response) {
  if (!response || !response.body) return false;

  const body = response.body;
  // Check for any remaining placeholder URLs
  const hasPlaceholder = body.includes('PLACEHOLDER:');
  // Check for properly replaced URLs
  const hasReplaced = body.includes('incident-images/images/');

  if (hasPlaceholder) {
    imageReplaceErrors.add(1);
    imageUrlReplaceSuccess.add(false);
    return false;
  }

  if (hasReplaced) {
    imageUrlReplaceSuccess.add(true);
  } else {
    // Not an image-related response, count as success
    imageUrlReplaceSuccess.add(true);
  }

  return true;
}

function traceHeaders() {
  return {
    'X-Trace-Id': `k6-${__VU}-${__ITER}-${Date.now()}`,
    'X-API-Key': config.apiKey,
    'Content-Type': 'application/json',
  };
}

// Scenario 1: Image review — concurrent review requests that trigger image retrieval
export function scenarioImageReview() {
  group('Image Review', function () {
    const sample = diffSamples[__ITER % diffSamples.length];
    const payload = JSON.stringify({
      projectId: sample.projectId,
      projectName: sample.projectId,
      prUrl: sample.prLink,
      diffContent: sample.diffContent + '\n/* additional context for image retrieval */',
      question: sample.question + ' 请引用相关图片说明。',
      mode: 'SYNC',
    });

    const start = Date.now();
    const res = http.post(`${config.baseUrl}/api/review/sync`, payload, {
      headers: traceHeaders(),
      timeout: '30s',
    });
    const elapsed = Date.now() - start;
    responseTime.add(elapsed);

    const passed = check(res, {
      'status is 200': (r) => r.status === 200,
      'image URLs replaced': () => checkImageUrls(res),
      'response contains risk info': (r) => r.body && (r.body.includes('riskScore') || r.body.includes('riskSummary')),
    });

    if (!passed) {
      imageReplaceErrors.add(1);
    }

    sleep(Math.random() * 2 + 0.5);
  });
}

// Scenario 2: Image-dense queries — specifically asking about incidents that have images
export function scenarioImageDense() {
  group('Image Dense Query', function () {
    const imageQueries = [
      { projectId: 'proj-db', diffContent: 'DELETE TABLE IF EXISTS temp', question: '这个删除操作的风险？请查看历史截图。' },
      { projectId: 'proj-monitor', diffContent: 'timeout: 50', question: '超时配置问题，查看历史监控图。' },
      { projectId: 'proj-payment', diffContent: 'balance - amount', question: '并发问题分析，参考架构图。' },
    ];

    const q = imageQueries[__ITER % imageQueries.length];
    const payload = JSON.stringify({
      projectId: q.projectId,
      projectName: q.projectId,
      prUrl: `https://github.com/org/repo/pull/${100 + __ITER}`,
      diffContent: q.diffContent,
      question: q.question,
      mode: 'SYNC',
    });

    const start = Date.now();
    const res = http.post(`${config.baseUrl}/api/review/sync`, payload, {
      headers: traceHeaders(),
      timeout: '30s',
    });
    responseTime.add(Date.now() - start);

    check(res, {
      'status is 200': (r) => r.status === 200,
      'image URLs processed': () => checkImageUrls(res),
    });

    sleep(Math.random() * 1.5 + 0.3);
  });
}

// Scenario 3: Code search — mixed queries some with images
export function scenarioCodeSearch() {
  group('Code Search', function () {
    const searchQueries = [
      { diffContent: 'SELECT * FROM orders', question: 'SQL 性能问题' },
      { diffContent: 'public void transfer()', question: '事务处理是否有风险？' },
      { diffContent: 'cache.get(key)', question: '缓存使用是否正确？请结合历史数据分析。' },
      { diffContent: 'try { api.call() } catch (Exception e)', question: '异常处理是否完善？' },
      { diffContent: '@Transactional public void createOrder()', question: '事务边界是否正确？' },
    ];

    const q = searchQueries[__ITER % searchQueries.length];
    const payload = JSON.stringify({
      projectId: 'proj-search',
      projectName: 'search-test',
      prUrl: `https://github.com/org/repo/pull/${200 + __ITER}`,
      diffContent: q.diffContent,
      question: q.question,
      mode: 'SYNC',
    });

    const start = Date.now();
    const res = http.post(`${config.baseUrl}/api/review/sync`, payload, {
      headers: traceHeaders(),
      timeout: '30s',
    });
    responseTime.add(Date.now() - start);

    check(res, {
      'status is 200': (r) => r.status === 200,
      'image URLs safe': () => checkImageUrls(res),
    });

    sleep(Math.random() * 1 + 0.2);
  });
}

// Scenario 4: Mixed workload — varied request types
export function scenarioMixed() {
  group('Mixed Workload', function () {
    const scenarios = ['review', 'search', 'task-status'];
    const choice = scenarios[__ITER % scenarios.length];

    if (choice === 'review') {
      const sample = diffSamples[__ITER % diffSamples.length];
      const payload = JSON.stringify({
        projectId: sample.projectId,
        projectName: sample.projectId,
        prUrl: sample.prLink,
        diffContent: sample.diffContent,
        question: sample.question,
        mode: __ITER % 3 === 0 ? 'ASYNC' : 'SYNC',
      });

      const endpoint = __ITER % 3 === 0 ? `${config.baseUrl}/api/review/async` : `${config.baseUrl}/api/review/sync`;
      const res = http.post(endpoint, payload, {
        headers: traceHeaders(),
        timeout: '30s',
      });
      check(res, { 'status is 200 or 202': (r) => r.status === 200 || r.status === 202 });
      checkImageUrls(res);
    } else if (choice === 'search') {
      const res = http.get(`${config.baseUrl}/api/review/tasks/k6-task-${__ITER}`, {
        headers: traceHeaders(),
      });
      check(res, { 'search responded': (r) => r.status < 500 });
    } else {
      const res = http.get(`${config.baseUrl}/api/review/tasks/k6-demo-001`, {
        headers: traceHeaders(),
      });
      check(res, { 'task status responded': (r) => r.status < 500 });
    }

    sleep(Math.random() * 1.5 + 0.3);
  });
}

export default function () {
  // Default entry point — run mixed workload
  scenarioMixed();
}
