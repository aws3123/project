/**
 * 同步审核场景 (POST /api/review/sync)
 *
 * 模拟用户直接调用同步审核接口，阻塞等待结果返回。
 * 适用于测试 Java BFF 到 Python 的全链路同步响应能力。
 *
 * 运行：
 *   k6 run k6/scenarios/sync.js
 *   k6 run --env TARGET_URL=http://localhost:8080 k6/scenarios/sync.js
 *   k6 run --out csv=results/sync.csv k6/scenarios/sync.js
 */

import { check, sleep } from 'k6';
import http from 'k6/http';
import { BASE_URL, HEADERS, makeReviewPayload } from '../config.js';

const DIFF_SIZE = __ENV.DIFF_SIZE || 'small'; // small | medium | large

export const options = {
  scenarios: {
    sync_load: {
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
    http_req_failed: ['rate<0.005'],         // 可用性 >= 99.5%
    http_req_duration: ['p(99)<2000'],       // P99 <= 2s
    http_req_duration: ['p(95)<1000'],       // P95 <= 1s
    http_req_duration: ['avg<500'],           // 平均 <= 500ms
  },
  // 标签便于区分运行
  tags: { scenario: 'sync', diffSize: DIFF_SIZE },
};

export default function () {
  const payload = makeReviewPayload(DIFF_SIZE);

  const res = http.post(`${BASE_URL}/api/review/sync`, payload, {
    headers: HEADERS,
    timeout: '10s',
  });

  check(res, {
    'status is 200': (r) => r.status === 200,
    'response has taskId': (r) => {
      try { return JSON.parse(r.body).taskId !== undefined; }
      catch { return false; }
    },
    'response has result': (r) => {
      try { return JSON.parse(r.body).result !== undefined; }
      catch { return false; }
    },
  });

  // 用户思考间隔（模拟真实用户行为）
  sleep(Math.random() * 2 + 1);
}
