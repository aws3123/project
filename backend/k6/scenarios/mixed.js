/**
 * 混合场景：模拟真实用户行为
 *
 * 混合调用同步审核、自动分发、任务查询三种接口，
 * 模拟真实用户在系统中的操作序列。
 *
 * 运行：
 *   k6 run k6/scenarios/mixed.js
 *   k6 run --env VUS=150 --env DURATION=5m k6/scenarios/mixed.js
 */

import { check, sleep, group } from 'k6';
import http from 'k6/http';
import { BASE_URL, HEADERS, makeReviewPayload, makeDispatchPayload } from '../config.js';

// 并发数与持续时间可通过环境变量覆盖
const TARGET_VUS = parseInt(__ENV.VUS || '200');
const DURATION = __ENV.DURATION || '5m';

export const options = {
  scenarios: {
    mixed_load: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '1m', target: Math.floor(TARGET_VUS * 0.25) },
        { duration: '2m', target: Math.floor(TARGET_VUS * 0.6) },
        { duration: '1m', target: TARGET_VUS },
        { duration: '3m', target: TARGET_VUS },
        { duration: '1m', target: 0 },
      ],
      gracefulStop: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.005'],
    http_req_duration: ['p(99)<5000'],
    http_req_duration: ['p(95)<2000'],
  },
  tags: { scenario: 'mixed' },
};

// 权重：sync 30% / dispatch 50% / 任务查询 20%
const WEIGHTS = [
  { type: 'sync', weight: 0.3 },
  { type: 'dispatch', weight: 0.5 },
  { type: 'task_list', weight: 0.2 },
];

function pickEndpoint() {
  const r = Math.random();
  let cum = 0;
  for (const item of WEIGHTS) {
    cum += item.weight;
    if (r <= cum) return item.type;
  }
  return 'dispatch';
}

// 共享的任务 ID 池（便于查询）
const taskIdPool = [];

export default function () {
  group('review_workflow', () => {
    const endpoint = pickEndpoint();

    if (endpoint === 'sync') {
      const payload = makeReviewPayload('small');
      const res = http.post(`${BASE_URL}/api/review/sync`, payload, {
        headers: HEADERS,
        timeout: '15s',
      });
      check(res, {
        'sync status 200': (r) => r.status === 200,
      });
      if (res.status === 200) {
        try {
          const taskId = JSON.parse(res.body).taskId;
          if (taskId) taskIdPool.push(taskId);
        } catch { /* ignore */ }
      }

    } else if (endpoint === 'dispatch') {
      const size = Math.random() < 0.7 ? 'small' : 'large';
      const payload = makeDispatchPayload(size);
      const res = http.post(`${BASE_URL}/api/review/dispatch`, payload, {
        headers: HEADERS,
        timeout: '10s',
      });
      check(res, {
        'dispatch status 200': (r) => r.status === 200,
      });
      if (res.status === 200) {
        try {
          const taskId = JSON.parse(res.body).taskId;
          if (taskId) taskIdPool.push(taskId);
        } catch { /* ignore */ }
      }

    } else if (endpoint === 'task_list') {
      const res = http.get(`${BASE_URL}/api/review/tasks`, {
        headers: HEADERS,
        timeout: '5s',
      });
      check(res, {
        'task list status 200': (r) => r.status === 200,
      });

      // 随机查询一个已知任务详情
      if (taskIdPool.length > 0 && Math.random() < 0.3) {
        const tid = taskIdPool[Math.floor(Math.random() * taskIdPool.length)];
        const detailRes = http.get(`${BASE_URL}/api/review/tasks/${tid}`, {
          headers: HEADERS,
          timeout: '5s',
        });
        check(detailRes, {
          'task detail status 200': (r) => r.status === 200,
        });
      }
    }
  });

  sleep(Math.random() * 3 + 1);
}
