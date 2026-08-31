/**
 * 自动路由分发场景 (POST /api/review/dispatch)
 *
 * 模拟用户调用自动路由分发接口，测试 DispatchStrategy 的
 * 特征提取 -> 直判/分类器 -> 执行路由的全流程决策能力。
 *
 * 运行：
 *   k6 run k6/scenarios/dispatch.js
 *   k6 run --env DIFF_SIZE=large k6/scenarios/dispatch.js
 */

import { check, sleep } from 'k6';
import http from 'k6/http';
import { BASE_URL, HEADERS, makeDispatchPayload } from '../config.js';

const DIFF_SIZE = __ENV.DIFF_SIZE || 'small'; // small | medium | large

export const options = {
  scenarios: {
    dispatch_load: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '1m', target: 50 },
        { duration: '2m', target: 100 },
        { duration: '1m', target: 200 },
        { duration: '3m', target: 200 },
        { duration: '1m', target: 0 },
      ],
      gracefulStop: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.005'],
    http_req_duration: ['p(99)<3000'],       // dispatch 可能异步，给更大容忍
    http_req_duration: ['p(95)<1500'],
  },
  tags: { scenario: 'dispatch', diffSize: DIFF_SIZE },
};

export default function () {
  const payload = makeDispatchPayload(DIFF_SIZE);

  const res = http.post(`${BASE_URL}/api/review/dispatch`, payload, {
    headers: HEADERS,
    timeout: '10s',
  });

  check(res, {
    'status is 200': (r) => r.status === 200,
    'response has route': (r) => {
      try { return JSON.parse(r.body).route !== undefined; }
      catch { return false; }
    },
    'response has dispatchReason': (r) => {
      try { return JSON.parse(r.body).dispatchReason !== undefined; }
      catch { return false; }
    },
  });

  sleep(Math.random() * 2 + 1);
}
