# Business Risk Java Control Plane Design

**Date:** 2026-05-29

## 背景

当前业务风险源码审查链路已经具备 Java 入口、任务表、outbox、callback、reconcile、SSE 等主骨架，但仍存在两个与目标架构不一致的问题：

1. Python 端仍保留进程内幂等缓存、请求重组和部分回调编排逻辑，不是严格无状态，不利于 1 Java : N Python 横向扩容。
2. Java 端尚未成为唯一的重预处理控制面，源码精简、预算控制、候选风险缩圈等重任务没有完全前置到 Java。

目标是把当前链路演进为行业主流的生产级模式：**Java 负责状态、预处理、预算、调度和审计；Python 负责无状态执行分析。**

---

## 目标

将业务风险源码审查链路重构为：

- **Java 是唯一控制面（control plane）**
  - 接收 multipart 源码上传
  - 进行 AST 预处理、候选风险缩圈、payload budget 控制
  - 负责任务状态、幂等、outbox、reconcile、SSE、回调验收、失败语义、审计与指标
- **Python 是纯执行器（stateless worker）**
  - 只接收 Java 生成的 prepared payload
  - 只做 schema 校验、风险分析 pipeline 执行、回调结果
  - 不保留进程内幂等状态、会话状态、任务状态
- **Python worker 支持多实例部署**
  - 通过定时 heartbeat 向 Java 注册活性与容量
  - Java 根据 heartbeat 注册表决定是否允许派发

---

## 设计原则

### 1. 控制面与执行面分离

这是当前行业主流 agent/AI code review 平台处理大型代码库时的落地方式：

- 大型源码与复杂状态问题留在控制面
- 大模型/分析执行留在无状态 worker
- 不使用“整仓源码直喂 LLM”作为主路径
- 采用“预处理缩圈 + 结构化证据包 + 异步任务”模式

### 2. Python 必须真正无状态

Python worker 重启、扩缩容、实例替换都不应影响业务正确性，因此不能依赖：

- 本地幂等缓存
- 本地 inflight 注册
- 基于源码内容推导任务主键
- 本地持久会话状态

### 3. Java 只在 preprocess 成功后推进任务

“上传成功”不等于“可派发”。

必须满足：

- upload accepted 之后先 preprocess
- preprocess 成功才允许进入 PROCESSING 与 outbox
- preprocess 失败直接终态 FAILED
- 不允许把脏任务推进到 Python 再靠 reconcile 收尾

---

## 目标架构

### Java 侧职责

Java 负责：

- `POST /api/business-risk/source` multipart 接收
- metadata 校验与文件校验
- Java AST 解析
- 关键方法/注解/事务边界/外部调用/热点提取
- payload budget 决策（accept / trim / reject）
- 生成 `prepared payload` / `source_package`
- 任务创建、trace/session/request/task id 分配
- outbox 入列与重试
- Python 回调验签与终态写回
- SSE 推送、审计日志、指标采集
- Python worker heartbeat 注册表维护

### Python 侧职责

Python 负责：

- 接收 Java prepared payload
- 校验 schema/version
- 将结构化证据包转换为当前业务风险分析 pipeline 所需输入
- 执行分析并产出结果
- 回调 Java
- 定时发送 heartbeat

Python 不再负责：

- 原始源码精简
- 本地幂等缓存
- 运行态任务创建
- 请求主键推导
- source bundle 主路径拼装

---

## Java → Python 新契约

### 顶层结构

Python 主输入改为 prepared payload only，不再以 `source_bundle` 为中心。

```json
{
  "schema_version": "3.0",
  "java_preprocess_version": "3.0",
  "task_id": "biz-risk-123",
  "request_id": "biz-risk-123",
  "session_id": "session-biz-risk-123",
  "trace_id": "trace-123",
  "project_id": "ticket-demo",
  "repo": "ticket-service",
  "branch": "main",
  "source_package": {
    "file_count": 12,
    "files": [],
    "call_graph": [],
    "budget": {},
    "preprocess_findings": []
  },
  "analysis_hints": {
    "candidate_risk_types": ["OVERSELL", "MISSING_TRANSACTION_BOUNDARY"],
    "focus_methods": ["ticketService.reserve", "inventoryRepository.decrease"],
    "focus_paths": [
      "TicketController.create -> TicketService.reserve -> InventoryRepository.decrease"
    ]
  },
  "callback": {
    "url": "http://java/api/internal/business-risk/callback",
    "token_header": "X-Callback-Token",
    "signature_header": "X-Callback-Signature",
    "timestamp_header": "X-Callback-Timestamp",
    "nonce_header": "X-Callback-Nonce"
  }
}
```

### source_package 结构

`source_package` 应包含可供规则和 LLM 混合推理的结构化证据：

- `files[]`
  - `path`
  - `package_name`
  - `class_name`
  - `class_annotations`
  - `interfaces`
  - `repository_dependencies`
  - `external_dependencies`
  - `methods[]`
    - `method_id`
    - `signature`
    - `annotations`
    - `line_map`
    - `key_calls`
    - `transaction_boundary`
    - `lock_semantics`
    - `snippet`
  - `hotspots[]`
    - `reason`
    - `risk_tags`
    - `line_map`
    - `snippet`
- `call_graph`
  - 只保留候选风险链路的轻量边
- `budget`
  - `decision`
  - `raw_total_bytes`
  - `prepared_total_bytes`
  - `dropped_files`
  - `dropped_methods`
- `preprocess_findings`
  - 例如：
    - `CHECK_THEN_ACT_CANDIDATE`
    - `MISSING_TRANSACTION_BOUNDARY`
    - `CACHE_DB_DUAL_WRITE`
    - `EXTERNAL_CALL_INSIDE_TRANSACTION`

### analysis_hints

`analysis_hints` 用于将 Java 侧规则和结构化抽取结果前置给 Python：

- candidate risk types
- focus methods
- focus call paths
- 已判定的高风险标签
- 推荐优先分析的 hotspots

这让 Python 能把算力集中在候选证据包，而不是重新理解整批源码。

---

## 任务生命周期

目标生命周期：

`UPLOAD_ACCEPTED -> PREPROCESSING -> PREPROCESS_FAILED | DISPATCH_PENDING -> PROCESSING -> SUCCESS | HUMAN_REVIEW | FAILED`

考虑当前任务表仍使用通用状态，外显状态保持：

- `PENDING`
- `PROCESSING`
- `SUCCESS`
- `HUMAN_REVIEW`
- `FAILED`

但内部审计/日志阶段固定为：

- `upload_accepted`
- `preprocess_started`
- `preprocess_trimmed`
- `preprocess_rejected`
- `dispatch_queued`
- `worker_heartbeat_seen`
- `callback_accepted`
- `callback_ignored_terminal`
- `task_closed`

关键约束：

- preprocess 成功前不得进入 `PROCESSING`
- Python 不得自行创建任务或推进中间状态
- callback 只能推进终态，不能回滚状态
- reconcile 不再尝试重建原始源码包

---

## 失败语义

### 上传/预处理层

- `SOURCE_FILE_COUNT_EXCEEDED`
- `SOURCE_LANGUAGE_UNSUPPORTED`
- `SOURCE_AST_PARSE_FAILED`
- `SOURCE_PREPROCESS_BUDGET_EXCEEDED`
- `SOURCE_PREPROCESS_FAILED`

### 派发/集群层

- `PYTHON_WORKER_UNAVAILABLE`
- `PYTHON_HEARTBEAT_STALE`
- `PYTHON_WORKER_VERSION_MISMATCH`
- `PYTHON_DISPATCH_FAILED`
- `PYTHON_DISPATCH_RETRY_EXHAUSTED`

### 执行/回调层

- `PYTHON_ANALYSIS_FAILED`
- `PYTHON_CALLBACK_INVALID`
- `PYTHON_CALLBACK_REJECTED`

错误码必须能够写入 `ReviewResult` 与 SSE payload，支持前端联调和排障。

---

## Python heartbeat 设计

### 目标

让 Java 知道当前是否存在可用 Python worker，以及 worker 是否具备处理当前 payload 的能力。

### 心跳机制

- 每个 Python 实例启动后生成 `instance_id`
- 每 15 秒向 Java 内部接口发送 heartbeat
- Java 将 heartbeat 写入 Redis TTL 注册表
- TTL 设为 45 秒

### heartbeat 内容

```json
{
  "instance_id": "worker-a-1",
  "worker_version": "2026.05.29",
  "started_at": "2026-05-29T11:20:00Z",
  "schema_versions_supported": ["3.0"],
  "java_preprocess_versions_supported": ["3.0"],
  "readiness": "UP",
  "inflight_count": 2,
  "max_concurrency": 8,
  "last_error": null
}
```

### Java 注册表

Redis key：

- `business-risk:worker:{instanceId}`

TTL：

- 45 秒

Java 侧应提供 worker registry service，负责：

- upsert heartbeat
- 聚合 active/ready worker 数
- 计算 available slots
- 判断 version compatibility

### 派发前置条件

`OutboxPoller` 派发 `BUSINESS_RISK_DISPATCH` 前必须满足：

- 至少 1 个 fresh worker heartbeat
- 至少 1 个 readiness=UP worker
- 至少 1 个 available slot
- 至少 1 个 worker 与 `schema_version/java_preprocess_version` 兼容

否则：

- 不调用 Python
- 按 outbox 重试策略退避
- 超过预算后写回对应错误码

---

## 健康检查调整

当前 `PythonHealthIndicator` 只探测单个 Python readiness URL，不足以表达 worker 集群状态。

调整后，Java 的 Python 健康应综合：

1. 最近是否有 fresh worker heartbeat
2. heartbeat 中是否至少有 1 个 readiness=UP worker
3. 可选：对 Python service 的 readiness URL 做兜底探活

只有满足 1+2，才认为 Python cluster 可派发。

---

## 观测指标

### Java 指标

预处理：
- `business_risk_preprocess_total`
- `business_risk_preprocess_failed_total`
- `business_risk_preprocess_duration_ms`
- `business_risk_preprocess_raw_bytes`
- `business_risk_preprocess_prepared_bytes`
- `business_risk_preprocess_trimmed_total`
- `business_risk_preprocess_rejected_total`
- `business_risk_preprocess_dropped_files_total`
- `business_risk_preprocess_dropped_methods_total`

派发：
- `business_risk_dispatch_attempt_total`
- `business_risk_dispatch_blocked_no_worker_total`
- `business_risk_dispatch_retry_total`
- `business_risk_dispatch_retry_exhausted_total`

回调/闭环：
- `business_risk_callback_total`
- `business_risk_callback_invalid_total`
- `business_risk_callback_latency_ms`
- `business_risk_pipeline_latency_ms`

心跳：
- `business_risk_worker_active`
- `business_risk_worker_ready`
- `business_risk_worker_available_slots`
- `business_risk_worker_heartbeat_age_ms`
- `business_risk_worker_version_mismatch_total`

### Python 指标

- `business_risk_worker_heartbeat_sent_total`
- `business_risk_worker_heartbeat_failed_total`
- `business_risk_analysis_total`
- `business_risk_analysis_failed_total`
- `business_risk_analysis_duration_ms`
- `business_risk_callback_sent_total`
- `business_risk_callback_failed_total`
- `business_risk_worker_inflight`

---

## 测试策略

### Java 单元测试

- heartbeat registry service
  - fresh heartbeat 可见
  - TTL 过期后不可见
  - capacity 聚合正确
  - 版本兼容判断正确
- preprocess/budget
  - accept / trim / reject
  - dropped files / methods 统计正确
- task service
  - preprocess 成功后才进 `PROCESSING`
  - 无 worker 时不派发
  - 版本不兼容直接失败
- outbox poller
  - 无 heartbeat 时重试退避
  - retry exhausted 后写回错误码

### Python 单元测试

- heartbeat payload 结构正确
- heartbeat 定时发送与失败日志
- prepared payload schema 校验
- 移除本地幂等缓存后重复请求仍能正常返回，由 Java 侧做最终收敛

### 契约测试

- Java `source_package` JSON 与 Python schema 一致
- `schema_version/java_preprocess_version` 不兼容时行为固定
- callback payload 字段固定

### 集成测试

- Java + Redis：heartbeat 写入、过期、聚合
- Java + Mock Python：有 heartbeat 才允许派发
- Python + Mock Java callback：正常回调、失败日志
- 1 Java + 2 Python E2E：
  - 杀掉 1 个 Python 后仍可处理
  - 全部 Python 下线后进入可诊断失败/退避
  - Python 重启不依赖本地状态恢复

---

## 迁移策略

### 阶段 0：铺路

- Python 先增加 heartbeat
- Java 先增加 worker registry 和 cluster health
- 这一步不改主业务输入契约

### 阶段 1：引入 prepared payload

- Java 新增 `source_package` 生成逻辑
- Python 新版本支持 prepared payload
- 旧链路只保留短期回退，不作为主路径继续增强

### 阶段 2：切换主路径

- Java 改成 preprocess 成功后再入 outbox 并置 `PROCESSING`
- `OutboxPoller` 只派发 prepared payload
- Python 删除 source bundle 主路径拼装职责

### 阶段 3：清理旧实现

- 删除 Python 本地幂等缓存与 inflight 状态
- 删除旧 `source_bundle` 主路径
- 删除原始源码全文透传逻辑
- 将 heartbeat 作为派发前置条件固化

### 上线策略

- 先 1 个 canary Python worker
- 验证 heartbeat、预处理指标、callback 闭环
- 再扩到 N 个 Python worker

---

## 对当前代码的直接影响

重点修改区域：

- Java
  - `backend/src/main/java/com/acme/review/controller/BusinessRiskController.java`
  - `backend/src/main/java/com/acme/review/service/BusinessRiskTaskService.java`
  - `backend/src/main/java/com/acme/review/mq/OutboxPoller.java`
  - `backend/src/main/java/com/acme/review/health/PythonHealthIndicator.java`
  - 新增 preprocess / budget / heartbeat registry 相关服务与 DTO
- Python
  - `python/app/routers/business_risk_source.py`
  - `python/app/routers/health.py`
  - `python/config/settings.py`
  - `python/schemas/business_risk_source.py`
  - 新增 heartbeat sender/service

---

## 验收标准

- Java 是唯一控制面
- Python worker 无本地幂等/会话/任务状态
- Java preprocess 成功前任务不进入 `PROCESSING`
- outbox payload 不含原始 50 个 `.java` 全文
- heartbeat 注册表可准确反映 Python worker 活性与容量
- 无可用 worker 时 Java 不盲派发
- callback/reconcile/SSE 不回归
- 1 Java : N Python 部署下任务可稳定闭环
