# Business Risk Java Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 只通过 Java 端改造，把业务风险源码审查链路升级为唯一控制面：完成源码上传、AST 预处理、budget 控制、任务状态推进、worker 可用性门禁与 prepared payload 派发。

**Architecture:** 保留现有 `POST /api/business-risk/source`、任务表、outbox、callback、reconcile、SSE 主骨架，但主路径改为 `multipart upload -> Java preprocess -> worker availability gate -> outbox dispatch`。本计划只做 Java 端编码，不修改 Python 代码，也不编写/执行测试；Python prepared payload 适配与 heartbeat 上报视为后续协作项。

**Tech Stack:** Spring Boot 3.2、Java 17、MyBatis-Plus、Redis、Jackson、JavaParser。

---

## 范围说明

### 本计划只做

- Java multipart 上传入口改造
- Java AST 预处理与源码精简
- Java budget 决策与裁剪
- Java prepared payload DTO 与派发客户端改造
- Java worker heartbeat 接收与 Redis 注册表
- Java 任务状态推进顺序调整
- Java outbox 派发门禁
- Java health / 审计 / 错误码 / 指标补齐

### 本计划明确不做

- Python 路由、schema、heartbeat sender 改造
- 任何测试代码编写
- 任何单元测试、集成测试、E2E 执行
- 前端改造

### 对 Python 侧的协作前提

Java 本轮会先把目标契约和入口定好，但不在本计划内落地 Python 配套代码。后续 Python 需要按 Java 输出能力补齐：

- 接收新的 prepared payload
- 定时向 Java heartbeat 内部接口上报
- 保持回调字段兼容

---

## 文件结构与职责

### 现有 Java 文件

- `backend/src/main/java/com/acme/review/controller/BusinessRiskController.java`
  - 业务风险源码上传入口；改为 multipart + metadata 主路径。
- `backend/src/main/java/com/acme/review/service/BusinessRiskTaskService.java`
  - 任务创建、预处理调度、状态推进、失败写回。
- `backend/src/main/java/com/acme/review/mq/OutboxPoller.java`
  - 出站派发器；增加 worker 可用性门禁。
- `backend/src/main/java/com/acme/review/health/PythonHealthIndicator.java`
  - Python worker cluster 可用性视图。
- `backend/src/main/java/com/acme/review/client/BusinessRiskPythonClient.java`
  - prepared payload HTTP 派发。
- `backend/src/main/java/com/acme/review/dto/BusinessRiskPythonSourceRequest.java`
  - Java -> Python 新 prepared payload DTO。
- `backend/src/main/java/com/acme/review/service/BusinessRiskMetricsService.java`
  - 业务风险指标埋点扩展。
- `backend/src/main/resources/application.yml`
  - budget、heartbeat TTL、版本兼容等配置。

### 新增 Java 文件

- `backend/src/main/java/com/acme/review/service/BusinessRiskSourcePreprocessService.java`
  - 读取 multipart 源码，解析 AST，提取 source package。
- `backend/src/main/java/com/acme/review/service/BusinessRiskPayloadBudgetService.java`
  - prepared payload budget 决策：accept / trim / reject。
- `backend/src/main/java/com/acme/review/service/BusinessRiskWorkerRegistryService.java`
  - Redis heartbeat 注册表与可用 worker 聚合视图。
- `backend/src/main/java/com/acme/review/controller/InternalBusinessRiskWorkerHeartbeatController.java`
  - Python worker heartbeat 内部入口。
- `backend/src/main/java/com/acme/review/dto/BusinessRiskSourceMetadataRequest.java`
  - multipart metadata DTO。
- `backend/src/main/java/com/acme/review/dto/BusinessRiskSourcePackage.java`
  - prepared payload 顶层 source package。
- `backend/src/main/java/com/acme/review/dto/BusinessRiskPreparedSourceFile.java`
- `backend/src/main/java/com/acme/review/dto/BusinessRiskPreparedMethod.java`
- `backend/src/main/java/com/acme/review/dto/BusinessRiskPreparedHotspot.java`
- `backend/src/main/java/com/acme/review/dto/BusinessRiskPreparedCallEdge.java`
- `backend/src/main/java/com/acme/review/dto/BusinessRiskBudgetDecision.java`
- `backend/src/main/java/com/acme/review/dto/BusinessRiskAnalysisHints.java`
- `backend/src/main/java/com/acme/review/dto/BusinessRiskWorkerHeartbeatRequest.java`
- `backend/src/main/java/com/acme/review/dto/BusinessRiskWorkerRegistrySnapshot.java`

---

### Task 1: 固定 multipart 主路径与 metadata 契约

**Files:**
- Modify: `backend/src/main/java/com/acme/review/controller/BusinessRiskController.java`
- Create: `backend/src/main/java/com/acme/review/dto/BusinessRiskSourceMetadataRequest.java`
- Modify: `backend/src/main/java/com/acme/review/dto/BusinessRiskSourceSubmitRequest.java`

- [ ] 把业务风险源码入口固定为 `multipart/form-data` 主路径：
  - `@RequestPart("metadata") BusinessRiskSourceMetadataRequest`
  - `@RequestPart("files") List<MultipartFile>`
- [ ] metadata 只保留控制面需要的元字段：
  - `schemaVersion`
  - `projectId`
  - `repo`
  - `branch`
  - `requestId`
  - `sessionId`
  - `traceId`
  - `entryHint`
- [ ] 在 controller 中补齐基础校验：
  - 文件数 1~50
  - 扩展名必须为 `.java`
  - `projectId/repo/branch` 必填
- [ ] 旧 JSON/source bundle 路径只保留短期兼容入口，不再作为主路径继续增强。

**Expected:**
- Java 入口契约切到 multipart
- 前端与后续 Python 的边界从入口处固定

---

### Task 2: 引入 Java AST 预处理与 prepared source package DTO

**Files:**
- Modify: `backend/pom.xml`
- Create: `backend/src/main/java/com/acme/review/service/BusinessRiskSourcePreprocessService.java`
- Create: `backend/src/main/java/com/acme/review/dto/BusinessRiskSourcePackage.java`
- Create: `backend/src/main/java/com/acme/review/dto/BusinessRiskPreparedSourceFile.java`
- Create: `backend/src/main/java/com/acme/review/dto/BusinessRiskPreparedMethod.java`
- Create: `backend/src/main/java/com/acme/review/dto/BusinessRiskPreparedHotspot.java`
- Create: `backend/src/main/java/com/acme/review/dto/BusinessRiskPreparedCallEdge.java`
- Create: `backend/src/main/java/com/acme/review/dto/BusinessRiskAnalysisHints.java`

- [ ] 在 `pom.xml` 中加入 JavaParser 依赖。
- [ ] 新建 `BusinessRiskSourcePreprocessService`，负责：
  - 读取 `MultipartFile`
  - 解析 package/class/method/annotation
  - 提取事务边界、锁语义、关键外部调用、repository 依赖
  - 提取风险 hotspots 与轻量 call graph
  - 产出 `source_package` 与 `analysis_hints`
- [ ] 预处理结果要面向“超卖/事务/竞态”类业务风险，不只输出通用方法骨架。
- [ ] `analysis_hints` 至少包含：
  - 候选风险类型
  - focus methods
  - focus call paths
  - 高风险 hotspots

**Expected:**
- Java 已具备大源码缩圈与结构化证据提取能力
- 后续 Python 可直接消费 prepared payload

---

### Task 3: 增加 budget 决策与可解释裁剪策略

**Files:**
- Create: `backend/src/main/java/com/acme/review/service/BusinessRiskPayloadBudgetService.java`
- Create: `backend/src/main/java/com/acme/review/dto/BusinessRiskBudgetDecision.java`
- Modify: `backend/src/main/java/com/acme/review/service/BusinessRiskSourcePreprocessService.java`
- Modify: `backend/src/main/resources/application.yml`

- [ ] 设计 budget 结果：
  - `ACCEPT_AS_IS`
  - `TRIMMED`
  - `REJECTED`
- [ ] 预算维度至少包括：
  - `raw_total_bytes`
  - `prepared_total_bytes`
  - `dropped_files`
  - `dropped_methods`
  - `dropped_hotspots`
- [ ] 裁剪优先保留：
  - 带事务注解的方法
  - 涉及库存/订单/repository 的方法
  - 外部调用热点
  - cache / MQ / API / DB 双写热点
- [ ] 在 `application.yml` 补齐预算配置：
  - 最大上传文件数
  - 最大 prepared payload bytes
  - trim 策略阈值
  - preprocess 版本号
- [ ] 无法裁剪到预算内时，Java 直接失败，不入 Python。

**Expected:**
- Java 能在进入 outbox 前完成预算控制
- prepared payload 体积与质量可控

---

### Task 4: 重构 Java -> Python prepared payload 契约

**Files:**
- Modify: `backend/src/main/java/com/acme/review/dto/BusinessRiskPythonSourceRequest.java`
- Modify: `backend/src/main/java/com/acme/review/client/BusinessRiskPythonClient.java`
- Modify: `backend/src/main/resources/application.yml`

- [ ] 把 `BusinessRiskPythonSourceRequest` 改成 prepared payload only：
  - 顶层 task/request/session/trace metadata
  - `source_package`
  - `analysis_hints`
  - `callback`
- [ ] `source_package` 至少包含：
  - files
  - call graph
  - budget
  - preprocess findings
- [ ] `BusinessRiskPythonClient` 改为只派发 prepared payload，不再假设 Python 端会接收原始 source bundle 主路径。
- [ ] 在配置中显式固定：
  - `schema_version`
  - `java_preprocess_version`
  - prepared payload 派发 URL

**Expected:**
- Java 对 Python 的目标契约已经固定
- 后续 Python 只需按此契约适配

---

### Task 5: 加入 Java worker heartbeat 接收与 Redis 注册表

**Files:**
- Create: `backend/src/main/java/com/acme/review/service/BusinessRiskWorkerRegistryService.java`
- Create: `backend/src/main/java/com/acme/review/controller/InternalBusinessRiskWorkerHeartbeatController.java`
- Create: `backend/src/main/java/com/acme/review/dto/BusinessRiskWorkerHeartbeatRequest.java`
- Create: `backend/src/main/java/com/acme/review/dto/BusinessRiskWorkerRegistrySnapshot.java`
- Modify: `backend/src/main/resources/application.yml`

- [ ] 新增 Python worker heartbeat 内部接收接口。
- [ ] heartbeat 请求体至少包含：
  - `instance_id`
  - `worker_version`
  - `started_at`
  - `schema_versions_supported`
  - `java_preprocess_versions_supported`
  - `readiness`
  - `inflight_count`
  - `max_concurrency`
  - `last_error`
- [ ] `BusinessRiskWorkerRegistryService` 使用 Redis TTL 注册表：
  - key: `business-risk:worker:{instanceId}`
  - TTL: 45 秒
- [ ] service 提供聚合视图：
  - active worker count
  - ready worker count
  - available slots
  - version compatibility
- [ ] 在 `application.yml` 中补齐 heartbeat TTL、freshness 窗口、兼容版本配置。

**Expected:**
- Java 能独立维护 Python worker 集群视图
- 之后 Python 只需按该接口上报 heartbeat

---

### Task 6: 把任务主路径改成 preprocess 成功后再入 outbox

**Files:**
- Modify: `backend/src/main/java/com/acme/review/service/BusinessRiskTaskService.java`
- Modify: `backend/src/main/java/com/acme/review/controller/BusinessRiskController.java`

- [ ] `BusinessRiskTaskService` 改为：
  1. create task -> `PENDING`
  2. preprocess
  3. budget 决策
  4. preprocess 成功后写 prepared payload 到 outbox
  5. 再推进到 `PROCESSING`
  6. 发 `task_processing`
- [ ] preprocess 失败时：
  - task 直接 `FAILED`
  - 写错误码
  - 发 `task_failed`
  - 不调用 Python
- [ ] 确保 outbox payload 中不再出现原始 50 个 `.java` 全文。

**Expected:**
- Java 成为唯一控制面
- preprocess 失败不会制造伪处理中任务

---

### Task 7: 在 OutboxPoller 中加入 worker availability gate

**Files:**
- Modify: `backend/src/main/java/com/acme/review/mq/OutboxPoller.java`
- Modify: `backend/src/main/java/com/acme/review/service/BusinessRiskMetricsService.java`

- [ ] `OutboxPoller` 派发 `BUSINESS_RISK_DISPATCH` 前先检查 worker registry：
  - 至少 1 个 fresh heartbeat
  - 至少 1 个 readiness=UP worker
  - 至少 1 个 available slot
  - 至少 1 个兼容版本 worker
- [ ] 不满足条件时：
  - 不调用 Python
  - 走 outbox 重试/退避
  - 超过预算后写回：
    - `PYTHON_WORKER_UNAVAILABLE`
    - `PYTHON_HEARTBEAT_STALE`
    - `PYTHON_WORKER_VERSION_MISMATCH`
- [ ] 在指标里记录：
  - dispatch attempt
  - blocked no worker
  - retry exhausted

**Expected:**
- Java 不再盲打 Python URL
- worker 可用性成为派发前置条件

---

### Task 8: 把 Python 健康检查升级为 cluster health 视图

**Files:**
- Modify: `backend/src/main/java/com/acme/review/health/PythonHealthIndicator.java`
- Modify: `backend/src/main/resources/application.yml`

- [ ] `PythonHealthIndicator` 从单点 readiness 探测升级为 cluster-aware：
  - 最近有 fresh heartbeat
  - 至少 1 个 readiness=UP worker
  - 可选保留单点 readiness 兜底探活
- [ ] 健康详情至少输出：
  - `activeWorkers`
  - `readyWorkers`
  - `availableSlots`
  - `staleWorkers`
- [ ] 将 Java health 语义改成“可派发的 Python worker cluster 是否存在”，而不是“单个 URL 是否存活”。

**Expected:**
- Java health 能反映 Python 集群真实可派发状态

---

### Task 9: 补齐错误码、审计点与关键指标

**Files:**
- Modify: `backend/src/main/java/com/acme/review/service/BusinessRiskTaskService.java`
- Modify: `backend/src/main/java/com/acme/review/service/BusinessRiskMetricsService.java`
- Modify: `backend/src/main/resources/application.yml`

- [ ] 固定错误码集合：
  - `SOURCE_FILE_COUNT_EXCEEDED`
  - `SOURCE_LANGUAGE_UNSUPPORTED`
  - `SOURCE_AST_PARSE_FAILED`
  - `SOURCE_PREPROCESS_BUDGET_EXCEEDED`
  - `SOURCE_PREPROCESS_FAILED`
  - `PYTHON_WORKER_UNAVAILABLE`
  - `PYTHON_HEARTBEAT_STALE`
  - `PYTHON_WORKER_VERSION_MISMATCH`
  - `PYTHON_DISPATCH_FAILED`
  - `PYTHON_DISPATCH_RETRY_EXHAUSTED`
  - `PYTHON_ANALYSIS_FAILED`
  - `PYTHON_CALLBACK_INVALID`
  - `PYTHON_CALLBACK_REJECTED`
- [ ] 审计日志节点补齐：
  - `upload_accepted`
  - `preprocess_started`
  - `preprocess_trimmed`
  - `preprocess_rejected`
  - `dispatch_queued`
  - `dispatch_blocked_no_worker`
  - `heartbeat_seen`
  - `callback_accepted`
  - `callback_ignored_terminal`
  - `task_closed`
- [ ] 指标补齐：
  - preprocess
  - dispatch
  - callback
  - pipeline latency
  - worker metrics

**Expected:**
- Java 侧失败语义可诊断
- 联调和线上排障具备足够观测点

---

### Task 10: 代码收口与协作交付

**Files:**
- Verify: `backend/src/main/java/com/acme/review/controller/BusinessRiskController.java`
- Verify: `backend/src/main/java/com/acme/review/service/BusinessRiskTaskService.java`
- Verify: `backend/src/main/java/com/acme/review/mq/OutboxPoller.java`
- Verify: `backend/src/main/java/com/acme/review/health/PythonHealthIndicator.java`

- [ ] 统一 Java 侧 prepared payload 字段命名，避免后续 Python 对接漂移。
- [ ] 统一 heartbeat 接口字段命名与 Redis key 规范。
- [ ] 清理 Java 侧残留的 source bundle 主路径假设。
- [ ] 输出给 Python 的协作交付物：
  - prepared payload JSON 字段名
  - heartbeat 请求字段名
  - callback 继续沿用的字段
  - schema/version 兼容要求

**Expected:**
- Java 侧编码范围闭合
- 后续 Python 端可按固定契约单独适配

---

## 验收清单

- multipart 接口稳定接收 1~50 个 `.java` 文件
- Java 预处理成功前任务不进入 `PROCESSING`
- Java 输出 `source_package` + `analysis_hints`
- budget 能 accept / trim / reject
- outbox payload 不含原始 50 个 `.java` 全文
- Java 已具备 heartbeat 注册表与 worker 可用性门禁
- 无 worker / stale worker / version mismatch 时不会继续盲派发
- Java health 改为 cluster-aware 语义
- Java 侧 prepared payload、heartbeat、callback 协作契约已经固定
- 本轮仅完成 Java 端编码，测试与 Python 配套改造留待后续阶段
