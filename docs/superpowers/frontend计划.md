# Business Risk Frontend Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把业务风险提交入口从手工粘贴 `sourceBundle` JSON 改成上传最多 50 个 `.java` 文件，并保持任务创建、错误展示、任务跳转与结果观察链路可用。

**Architecture:** 保留 `POST /api/business-risk/source` 路径，前端改为 `multipart/form-data` 提交 `metadata + files[]`。前端只负责选择文件、基础校验、提交和状态展示，不做 AST、摘要、热点提取；所有源码精简统一由 Java 完成。

**Tech Stack:** React 19、TypeScript、Vite、现有 `http<T>()` 客户端、Zustand、Vitest、Testing Library、MSW。

---

## 并行边界

- 本计划 owner：上传页 UI、前端类型、HTTP 提交方式、前端校验、提交后导航/观察。
- 本计划不负责：源码 AST 解析、热点提取、结构化包构造、Python 审查逻辑。
- 对 Java 的固定依赖：
  - 接口仍为 `POST /api/business-risk/source`
  - Content-Type 为 `multipart/form-data`
  - part `metadata` 为 JSON 字符串
  - part `files[]` 为 1~50 个 `.java` 文件
  - 响应至少包含 `taskId`、`sessionId`、`traceId`、`status`
- 对 Python 无直接依赖；前端不感知 Java -> Python 的 `sourcePackage` 细节。

## 前后端冻结契约

### 请求

`multipart/form-data`

- `metadata`

```json
{
  "schemaVersion": "2.0",
  "projectId": "ticket-demo",
  "repo": "ticket-service",
  "branch": "main",
  "requestId": "optional",
  "sessionId": "optional",
  "traceId": "optional",
  "entryHint": "optional"
}
```

- `files[]`
  - 1~50 个文件
  - 每个文件扩展名必须为 `.java`
  - 前端不拼 `sourceBundle`

### 响应

```json
{
  "taskId": "biz-risk-123",
  "sessionId": "session-biz-risk-123",
  "traceId": "trace-123",
  "status": "PENDING"
}
```

### 前端必须处理的失败语义

- `422`：文件数超限、非 `.java`、metadata 缺失、后端校验失败
- `413` 或等价错误：上传体过大
- `500/502/503`：后端或 Python 链路暂不可用

---

## Critical Files to Modify

- `frontend/src/pages/BusinessRiskSourcePage.tsx`
- `frontend/src/types/businessRisk.ts`
- `frontend/src/api/businessRisk.ts`
- `frontend/src/api/client.ts`
- `frontend/src/pages/BusinessRiskSourcePage.test.tsx`
- `frontend/src/tests/msw/handlers.ts`
- 如当前测试拆分需要，可补：`frontend/src/api/businessRisk.test.ts`

---

### Task 1: 固定前端提交类型与 HTTP 行为

**Files:**
- Modify: `frontend/src/types/businessRisk.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/businessRisk.ts`
- Test: `frontend/src/api/businessRisk.test.ts` 或 `frontend/src/pages/BusinessRiskSourcePage.test.tsx`

- [ ] 定义新的前端提交类型，只保留 `metadata` 与 `files`，移除页面层对 `sourceBundle` 的依赖。
- [ ] 在 `frontend/src/types/businessRisk.ts` 中新增或改造：
  - `BusinessRiskSourceSubmitMetadata`
  - `BusinessRiskSourceUploadInput`
  - `BusinessRiskSourceSubmitResponse`
- [ ] 修改 `frontend/src/api/client.ts`：当 `body instanceof FormData` 时，不主动设置 `Content-Type: application/json`；仍保留 API key 和 `X-Trace-Id` 注入。
- [ ] 修改 `frontend/src/api/businessRisk.ts`：新增 `submitBusinessRiskSourceForm(input, traceId?)`，内部构造 `FormData`，把 `metadata` 序列化后放到 `metadata` part，把每个文件追加到 `files[]`。
- [ ] 添加测试覆盖：
  - `FormData` 提交时 header 中不出现 `Content-Type: application/json`
  - `metadata` 与 `files[]` 被正确追加
  - traceId 仍被透传

**Run:**
- `pnpm --dir frontend vitest run src/pages/BusinessRiskSourcePage.test.tsx`
- 若拆出 API 单测，再跑：`pnpm --dir frontend vitest run src/api/businessRisk.test.ts`

**Expected:**
- 测试通过
- `FormData` 请求不再被错误标成 JSON

---

### Task 2: 把业务风险页面改造成多文件上传页

**Files:**
- Modify: `frontend/src/pages/BusinessRiskSourcePage.tsx`
- Test: `frontend/src/pages/BusinessRiskSourcePage.test.tsx`

- [ ] 删除当前 JSON 文本框、`JSON.parse` 和 `sourceBundle` 必填校验。
- [ ] 页面改为显示：
  - 项目标识输入（`projectId`、`repo`、`branch`）
  - 可选输入（`requestId`、`sessionId`、`traceId`、`entryHint`）
  - `<input type="file" multiple accept=".java">`
  - 已选文件列表与数量展示
- [ ] 增加前端校验：
  - 没有文件时禁止提交
  - 文件数大于 50 时直接拦截
  - 任一文件不是 `.java` 时直接拦截
  - `projectId/repo/branch` 缺失时禁止提交
- [ ] 错误信息改为面向上传场景，例如“最多上传 50 个 .java 文件”。
- [ ] 测试覆盖：
  - 选 1 个 `.java` 文件可提交
  - 选 51 个文件被拦截
  - 选 `.txt` 文件被拦截
  - 页面不再渲染原始 JSON 输入区

**Run:**
- `pnpm --dir frontend vitest run src/pages/BusinessRiskSourcePage.test.tsx`

**Expected:**
- 页面测试通过
- 上传页不再依赖 `sourceBundle` 文本

---

### Task 3: 串上提交成功后的任务跳转与错误展示

**Files:**
- Modify: `frontend/src/pages/BusinessRiskSourcePage.tsx`
- Test: `frontend/src/pages/BusinessRiskSourcePage.test.tsx`
- 如已有任务详情跳转逻辑可复用，确认：`frontend/src/pages/TaskDetailPage.tsx`

- [ ] 提交时调用新的 `submitBusinessRiskSourceForm(...)`。
- [ ] 提交成功后展示 `taskId/sessionId/traceId`，并跳转到现有任务页或详情页。
- [ ] 提交失败时区分并展示：
  - 前端校验错误
  - 后端 `422` 校验错误
  - 链路不可用类错误（`500/502/503`）
- [ ] 保留现有 traceId 展示/透传习惯，避免丢失问题定位能力。
- [ ] 测试覆盖：
  - 成功提交后跳转或显示成功信息
  - 后端返回 422 时显示后端消息
  - 网络失败时显示通用失败提示

**Run:**
- `pnpm --dir frontend vitest run src/pages/BusinessRiskSourcePage.test.tsx`

**Expected:**
- 提交流程测试通过
- 成功与失败场景提示明确

---

### Task 4: 做前端回归验证，确保不影响现有任务观察体验

**Files:**
- Verify: `frontend/src/pages/BusinessRiskSourcePage.tsx`
- Verify: `frontend/src/pages/TaskDetailPage.tsx`
- Verify: `frontend/src/hooks/useBusinessRiskSse.ts`

- [ ] 跑一遍前端相关单测。
- [ ] 若本地 Java 已就绪，手工验证：上传 1~3 个小 `.java` 文件，确认能创建任务并跳到任务页。
- [ ] 若本地 Java 未就绪，至少通过 MSW 证明：页面可构造 multipart 请求、可处理成功响应、可显示错误。
- [ ] 手工检查任务详情页没有因为新提交入口而回归。

**Run:**
- `pnpm --dir frontend test:run`
- 可选手工验证：`pnpm --dir frontend dev`

**Expected:**
- `test:run` 通过
- 业务风险上传入口可用
- 任务观察页无明显回归

---

## 对其他终端的交付物

前端终端完成后，应明确向 Java 终端确认：
- 请求使用的是 `metadata + files[]`
- metadata 字段名没有漂移
- 前端已不再发送 `sourceBundle`

前端终端不需要等待 Python 终端完成即可提交自己的改动。

---

## Verification

- 1 个 `.java` 文件可成功提交
- 50 个 `.java` 文件可成功通过前端校验
- 51 个文件在前端被拦截
- 非 `.java` 文件在前端被拦截
- `FormData` 请求不带错误的 JSON Content-Type
- 成功提交后能看到 `taskId` / `traceId`
- 失败场景有明确提示

---

## Gotcha

前端最大的坑是“页面看起来改成上传了，但 HTTP 层仍偷偷发 JSON”。如果 `frontend/src/api/client.ts` 继续默认写死 `Content-Type: application/json`，后端即使已经支持 multipart，前端也会以很隐蔽的方式失败。