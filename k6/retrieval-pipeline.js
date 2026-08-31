// Full retrieval pipeline load test (dispatch → parse → chunk → embed → search → rank)
// Run: k6 run --vus 5 --duration 30s k6/retrieval-pipeline.js

import http from 'k6/http';
import { check, sleep } from 'k6';

const TARGET_URL = __ENV.TARGET_URL || 'http://localhost:8000';

export const options = {
    stages: [
        { duration: '30s', target: 5 },
        { duration: '1m', target: 25 },
        { duration: '30s', target: 0 },
    ],
    thresholds: {
        http_req_duration: ['p(95)<3000'],
        http_req_failed: ['rate<0.02'],
    },
};

export default function () {
    const diffPayload = JSON.stringify({
        diff_content: `diff --git a/src/main/java/com/acme/review/service/UserService.java b/src/main/java/com/acme/review/service/UserService.java
index abc..def 100644
--- a/src/main/java/com/acme/review/service/UserService.java
+++ b/src/main/java/com/acme/review/service/UserService.java
@@ -15,6 +15,7 @@ public class UserService {
     public User getUser(Long id) {
+        if (id == null) {
+            throw new IllegalArgumentException("ID required");
+        }
         return repository.findById(id);
     }
 }
`,
        pr_url: "https://github.com/example/repo/pull/123",
        project_id: "test-project",
        question: "Check for NPE risk patterns",
    });

    const res = http.post(`${TARGET_URL}/dispatch-review`, diffPayload, {
        headers: { 'Content-Type': 'application/json' },
    });

    check(res, {
        'dispatch returns 200': (r) => r.status === 200,
        'dispatch body present': (r) => r.body && r.body.length > 0,
    });

    sleep(0.5);
}
