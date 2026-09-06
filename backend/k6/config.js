/**
 * k6 压测共享配置
 *
 * 用法：
 *   import { BASE_URL, API_KEY, HEADERS, THRESHOLDS, STAGES } from './config.js';
 */

// 目标服务地址（Java BFF）
export const BASE_URL = __ENV.TARGET_URL || 'http://localhost:8080';

// API 认证
export const API_KEY_HEADER = __ENV.API_KEY_HEADER || 'X-API-Key';
export const API_KEY = __ENV.API_KEY || 'dev-key';

export const HEADERS = {
  [API_KEY_HEADER]: API_KEY,
  'Content-Type': 'application/json',
};

// 质量门禁阈值（与架构设计目标对齐）
export const THRESHOLDS = {
  // 可用性 >= 99.5%
  http_req_failed: ['rate<0.005'],
  // P99 延迟 <= 2s（同步场景）
  http_req_duration: ['p(99)<2000'],
  // P95 延迟 <= 1s
  http_req_duration_p95: ['p(95)<1000'],
};

// 施压阶梯
// 默认：从 50 并发逐步爬升到 200 并发，持续 5 分钟
export const STAGES = [
  { duration: '1m', target: 50 },   // 热身：50 并发
  { duration: '2m', target: 100 },  // 爬升：100 并发
  { duration: '1m', target: 200 },  // 爬升：200 并发
  { duration: '3m', target: 200 },  // 持续：200 并发
  { duration: '1m', target: 0 },    // 冷却
];

/**
 * 生成模拟的 diff 内容（不同大小档位）
 */
export function generateDiff(size) {
  const small = `@@ -0,0 +1,3 @@
+package com.example;
+public class Hello {
+    private String name;
+}
`;

  const medium = `@@ -0,0 +1,20 @@
+package com.example.service;
+
+import com.example.model.User;
+import com.example.repository.UserRepository;
+import lombok.RequiredArgsConstructor;
+import org.springframework.stereotype.Service;
+
+@Service
+@RequiredArgsConstructor
+public class UserService {
+    private final UserRepository userRepository;
+
+    public User findById(Long id) {
+        return userRepository.findById(id)
+                .orElseThrow(() -> new RuntimeException("User not found: " + id));
+    }
+}
+`;

  const large = `@@ -0,0 +1,80 @@
+package com.example.controller;
+
+import com.example.dto.UserCreateRequest;
+import com.example.dto.UserResponse;
+import com.example.dto.UserUpdateRequest;
+import com.example.service.UserService;
+import jakarta.validation.Valid;
+import lombok.RequiredArgsConstructor;
+import org.springframework.http.ResponseEntity;
+import org.springframework.web.bind.annotation.*;
+
+import java.util.List;
+
+@RestController
+@RequestMapping("/api/users")
+@RequiredArgsConstructor
+public class UserController {
+    private final UserService userService;
+
+    @GetMapping
+    public ResponseEntity<List<UserResponse>> list() {
+        return ResponseEntity.ok(userService.findAll());
+    }
+
+    @GetMapping("/{id}")
+    public ResponseEntity<UserResponse> get(@PathVariable Long id) {
+        return ResponseEntity.ok(userService.findById(id));
+    }
+
+    @PostMapping
+    public ResponseEntity<UserResponse> create(@Valid @RequestBody UserCreateRequest req) {
+        return ResponseEntity.ok(userService.create(req));
+    }
+
+    @PutMapping("/{id}")
+    public ResponseEntity<UserResponse> update(@PathVariable Long id, @Valid @RequestBody UserUpdateRequest req) {
+        return ResponseEntity.ok(userService.update(id, req));
+    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable Long id) {
        userService.delete(id);
        return ResponseEntity.noContent().build();
    }
}
`;

  if (size === 'small') return small;
  if (size === 'large') return large;
  return medium;
}

/**
 * 生成模拟的审核请求体
 */
export function makeReviewPayload(diffSize) {
  const taskId = `perf-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return JSON.stringify({
    taskId: taskId,
    projectId: 'perf-test',
    projectName: 'Performance Test Project',
    prUrl: `https://github.com/perf-org/perf-repo/pull/${Math.floor(Math.random() * 1000)}`,
    diffContent: generateDiff(diffSize),
    mode: 'SYNC',
  });
}

/**
 * 生成异步审核请求体（mode=ASYNC，taskId 由后端生成）
 */
export function makeAsyncPayload(diffSize) {
  return JSON.stringify({
    projectId: 'perf-test',
    projectName: 'Performance Test Project',
    prUrl: `https://github.com/perf-org/perf-repo/pull/${Math.floor(Math.random() * 1000)}`,
    diffContent: generateDiff(diffSize),
    mode: 'ASYNC',
  });
}

/**
 * 生成流式同步审核请求体（mode=SYNC，taskId 由客户端预置，
 * 用于 SSE 测试中客户端预先知道任务 ID 以便断线后用其重连）
 */
export function makeSyncStreamPayload(taskId, diffSize) {
  return JSON.stringify({
    taskId: taskId,
    projectId: 'perf-test',
    projectName: 'Performance Test Project',
    prUrl: `https://github.com/perf-org/perf-repo/pull/${Math.floor(Math.random() * 1000)}`,
    diffContent: generateDiff(diffSize),
    mode: 'SYNC',
  });
}

export function makeDispatchPayload(diffSize) {
  return JSON.stringify({
    projectId: 'perf-test',
    projectName: 'Performance Test Project',
    prUrl: `https://github.com/perf-org/perf-repo/pull/${Math.floor(Math.random() * 1000)}`,
    diffContent: generateDiff(diffSize),
  });
}
