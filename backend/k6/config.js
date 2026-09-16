/**
 * k6 压测共享配置 —— 板块1：分层架构解耦（AST 前置 / 水平扩展）
 *
 * 用法：
 *   import { BASE_URL, HEADERS, makeAsyncPayload } from './config.js';
 *
 * 环境变量：
 *   TARGET_URL      目标服务地址（Java BFF），默认 http://localhost:8080
 *   API_KEY         受理接口认证头，默认 dev-key
 */

export const BASE_URL = __ENV.TARGET_URL || 'http://localhost:8080';

const API_KEY_HEADER = __ENV.API_KEY_HEADER || 'X-API-Key';
const API_KEY = __ENV.API_KEY || 'dev-key';

export const HEADERS = {
  [API_KEY_HEADER]: API_KEY,
  'Content-Type': 'application/json',
};

/**
 * 生成模拟的 diff 内容（small / medium / large 三档，对应典型小中大 PR）
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
 * 生成异步受理请求体（mode=ASYNC，taskId 由后端生成）。
 * 受理链路：Java BFF 同步完成 AST 预处理 → Outbox 落库 → 返回 202。
 */
export function makeAsyncPayload(diffSize, runId = __ENV.PERF_RUN_ID) {
  // 每次验收使用唯一 RUN_ID，后续数据库对账只统计本次压测产生的任务。
  const projectId = runId ? `perf-${runId}` : 'perf-test';
  return JSON.stringify({
    projectId,
    projectName: runId ? `Performance Test ${runId}` : 'Performance Test Project',
    prUrl: `https://github.com/perf-org/perf-repo/pull/${Math.floor(Math.random() * 100000)}`,
    diffContent: generateDiff(diffSize),
    mode: 'ASYNC',
  });
}
