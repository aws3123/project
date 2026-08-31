# Business Risk Python Stateless Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Python 业务风险审查链路改造成适配 1 Java : n Python 部署的无状态分析 worker：Java 负责控制面与源码精简，Python 只负责消费结构化 `source_package` 并返回结构化审查结果。

**Architecture:** 保留 `POST /ai/business-risk/source` 作为 Python 业务风险入口，但其语义改为纯计算接口：接收 Java 预处理后的结构化包，同步返回业务风险结果。业务风险链路不再把输入降级为通用 `ReviewRequest`，也不再承担 callback、幂等缓存、任务状态机或任务持久化；异步只是 Java 的调度模式，不是 Python 的状态模式。Python 继续保留 worker 注册与 heartbeat，用于 Java 的观测与实例摘除。

**Tech Stack:** FastAPI、Pydantic、现有 GraphBuilder/GraphRunner、现有 6 个业务风险节点、Redis heartbeat、pytest、uv。

---

## 并行边界

- 本计划 owner：Python 业务风险 request/result 模型、stateless runner、service façade、router、readiness/heartbeat 语义、Python 测试与文档对齐。
- 本计划不负责：前端上传体验、Java AST 预处理、budget 计算、Java 侧任务状态机/outbox/callback/SSE。
- 对 Java 的固定依赖：
  - Java 是唯一控制面：负责幂等、任务状态、异步编排、回调、结果落库、SSE。
  - Java 是唯一源码精简层：负责把原始 `.java` 文件处理成结构化 `source_package`。
  - Python 入口主字段冻结为 `source_package`，保留 `request_id/session_id/task_id/trace_id` 等关联字段。
- 对普通代码审查链路的要求：
  - `python/app/routers/review.py`
  - `python/graph/runner.py`
  - `python/schemas/request.py`
  - `python/schemas/result.py`
  这些现有路径继续服务普通代码审查链路，不允许被业务风险改造拖坏。

## 当前必须消除的耦合点

当前仍存在的主耦合：
- `python/app/routers/business_risk_source.py` 把结构化输入回压成 `ReviewRequest`
- `python/app/dependencies.py:get_business_risk_service()` 返回通用 `AIService(runner.run)`
- `python/graph/runner.py` 只有 `ReviewRequest -> ReviewResult` 主路径
- `python/app/routers/business_risk_source.py` 还承担 callback、idempotency、inflight 等控制面职责

本计划的完成标准之一就是：业务风险 Python 主路径不再依赖以上语义，且 Python 端只保留 stateless compute worker 职责。

---

## 冻结契约

### Java -> Python 输入

Python 主路径接收结构如下：

```json
{
  "schema_version": "2.0",
  "java_preprocess_version": "2.0",
  "project_id": "ticket-demo",
  "repo": "ticket-service",
  "branch": "main",
  "task_id": "biz-risk-123",
  "session_id": "session-biz-risk-123",
  "trace_id": "trace-123",
  "request_id": "biz-risk-123",
  "source_package": {
    "file_count": 12,
    "files": [
      {
        "path": "src/main/java/com/acme/FooService.java",
        "package_name": "com.acme",
        "class_name": "FooService",
        "annotations": ["Service"],
        "methods": [
          {
            "signature": "public void createOrder(CreateOrderCommand command)",
            "annotations": ["Transactional"],
            "key_calls": ["inventoryService.reserve", "orderRepository.save"],
            "snippet": "...",
            "start_line": 21,
            "end_line": 68
          }
        ],
        "hotspots": [
          {
            "reason": "transaction + external call",
            "snippet": "...",
            "start_line": 30,
            "end_line": 44
          }
        ]
      }
    ],
    "budget": {
      "decision": "ACCEPT_AS_IS",
      "raw_total_bytes": 120345,
      "prepared_total_bytes": 24567,
      "dropped_files": []
    }
  },
  "metadata": {},
  "memory_context": {},
  "user_feedback_signals": {}
}
```

说明：
- Python 主输入是 `source_package`，不是旧 `source_bundle` 文本摘要主路径。
- 为避免切换期立即断链，可短暂兼容 `source_bundle -> source_package` 的 schema alias，但内部处理必须统一走 `source_package`。
- Python 不再接收 `callback_*` 字段，也不再承诺 callback 发送。

### Python -> Java 输出

Python 返回结构如下：

```json
{
  "run_id": "biz-risk-123",
  "task_id": "biz-risk-123",
  "status": "completed",
  "report": {
    "overall_risk_level": "medium",
    "executive_summary": "Business risk hotspots require review",
    "invariant_violations": [],
    "method_issues": [],
    "items": []
  },
  "proposed_memory_updates": {
    "business_risk_level": "medium",
    "violation_count": 0,
    "method_issue_count": 1
  },
  "trace_id": "trace-123"
}
```

说明：
- `status` 只表示 Python 计算结果，不表示 Java 任务状态机语义。
- `completed / failed / human_review` 即可；Java 负责映射为自己的任务终态。
- callback 由 Java 负责，Python 不再主动回调。

### Python heartbeat / readiness

- Python 继续注册自己并发送 heartbeat，供 Java 做观测和实例摘除。
- heartbeat 不承载任务状态，也不承载幂等语义。
- `GET /ai/health/business-risk-source` 的 readiness 语义改为：
  - 路由已注册
  - LLM 配置可用
  - worker 为 stateless，无需 task/result persistence 才能接单

---

## Critical Files to Modify

- `python/app/routers/business_risk_source.py`
- `python/app/dependencies.py`
- `python/schemas/business_risk_source.py`
- `python/schemas/business_risk_source_result.py`
- 新增 `python/schemas/business_risk_review.py`
- 新增 `python/graph/business_risk_state.py`
- 新增 `python/graph/business_risk_runner.py`
- 新增 `python/graph/business_risk_result.py`
- 新增 `python/services/business_risk_source_service.py`
- `python/graph/runner.py`
- `python/graph/nodes/business_extractor.py`
- `python/graph/nodes/dataflow_tracer.py`
- `python/graph/nodes/invariant_checker.py`
- `python/graph/nodes/deep_reader.py`
- `python/graph/nodes/business_risk.py`
- `python/graph/nodes/self_verify.py`
- `python/services/registry.py`
- `python/app/main.py`
- `python/app/routers/health.py`
- 测试：
  - `python/tests/app/test_business_risk_source_route.py`
  - `python/tests/app/test_business_risk_source_readiness_route.py`
  - 新增 `python/tests/graph/test_business_risk_runner.py`
  - 如新增 service 测试：`python/tests/services/test_business_risk_source_service.py`

---

### Task 1: 为业务风险链路定义独立 request/result 模型

**Files:**
- Modify: `python/schemas/business_risk_source.py`
- Modify: `python/schemas/business_risk_source_result.py`
- Create: `python/schemas/business_risk_review.py`
- Test: `python/tests/app/test_business_risk_source_route.py`

- [ ] 保留外部 API 所需最小兼容性，但主字段切到 `source_package`。
- [ ] 允许切换期兼容 `source_bundle -> source_package`，但内部不再使用 `source_bundle` 语义。
- [ ] 新增内部模型：
  - `BusinessRiskReviewRequest`
  - `BusinessRiskReviewResult`
- [ ] 内部模型字段只表达 stateless compute 所需信息：文件、方法、热点、budget、memory context、trace/request/session/task 关联字段。
- [ ] 去掉 callback 输入字段的主路径职责。
- [ ] 测试覆盖：
  - `source_package` 输入可通过校验
  - `source_bundle` 兼容 alias 可被规范化
  - 缺关键字段返回 422
  - 非法结构不再意外落到通用 review schema

**Run:**
- `cd python && uv run pytest tests/app/test_business_risk_source_route.py -q`

**Expected:**
- route schema 测试通过
- 业务风险输入/输出模型独立存在

---

### Task 2: 把 business-risk 路由改成无状态计算入口

**Files:**
- Modify: `python/app/routers/business_risk_source.py`
- Test: `python/tests/app/test_business_risk_source_route.py`

- [ ] 删除 `_to_review_request(...)` 把结构化输入压回 `ReviewRequest` 的主路径。
- [ ] route 内部改为：
  - payload -> `BusinessRiskSourceRequest`
  - 再映射到 `BusinessRiskReviewRequest`
  - 调用专用 `BusinessRiskSourceService`
- [ ] 删除 Python 端控制面职责：
  - idempotency 缓存
  - inflight 语义
  - callback 发送
  - `MANUAL_STOPPED` 特判
- [ ] 保留：
  - readiness 检查
  - traceId 透传
  - 失败时返回明确 `failed` 响应
- [ ] 测试覆盖：
  - route 不再 import / 使用 `ReviewRequest` 主路径
  - 正常请求返回 `completed / failed / human_review`
  - legacy `source_bundle` 兼容不破坏入口
  - 失败时不再依赖 callback 分支

**Run:**
- `cd python && uv run pytest tests/app/test_business_risk_source_route.py -q`

**Expected:**
- route 测试通过
- Python 入口成为纯计算接口

---

### Task 3: 新增业务风险专用 state / runner / result assembler

**Files:**
- Create: `python/graph/business_risk_state.py`
- Create: `python/graph/business_risk_runner.py`
- Create: `python/graph/business_risk_result.py`
- Modify: `python/graph/runner.py`
- Test: `python/tests/graph/test_business_risk_runner.py`

- [ ] 在 `business_risk_state.py` 中定义业务风险专用状态结构，至少承载：
  - request 基础字段
  - source_package
  - invariants
  - data_flow
  - deep_read
  - assessment
  - verification
- [ ] 在 `business_risk_runner.py` 中定义专用 runner：
  - 输入 `BusinessRiskReviewRequest`
  - 输出 `BusinessRiskReviewResult`
- [ ] 在 `business_risk_result.py` 中定义结果装配逻辑，不再依赖 `GraphRunner._build_result()`。
- [ ] 在 `graph/runner.py` 中增加可复用的 `run_state(...)` 之类能力，用于业务风险链路共享执行骨架，但不污染普通 review result 语义。
- [ ] 测试覆盖：
  - runner 能按顺序/并行关系执行业务风险节点
  - 输出结果来自业务风险专用 assembler
  - 普通 `python/graph/runner.py` 对 review path 语义不变

**Run:**
- `cd python && uv run pytest tests/graph/test_business_risk_runner.py -q`

**Expected:**
- business-risk runner 测试通过
- 结果装配独立成立

---

### Task 4: 把 `get_business_risk_service()` 升级为专用 stateless façade

**Files:**
- Modify: `python/app/dependencies.py`
- Create: `python/services/business_risk_source_service.py`
- Test: `python/tests/services/test_business_risk_source_service.py` 或增强 route/runner 测试

- [ ] 保持 `get_ai_service()` 继续服务普通代码审查链路。
- [ ] `get_business_risk_service()` 改为返回专用 `BusinessRiskSourceService`，而不是通用 `AIService(runner.run)`。
- [ ] service façade 只负责：
  - 接收 `BusinessRiskReviewRequest`
  - 调用 business-risk runner
  - 返回 `BusinessRiskReviewResult`
- [ ] 业务风险 service 不再依赖 task/result persistence 才能运行。
- [ ] 如需保留日志/telemetry，可继续写 node-level logs，但不能把 Python 重新变回控制面。
- [ ] 测试覆盖：
  - 普通 review 路径仍可工作
  - business-risk 路径已切到专用 service

**Run:**
- `cd python && uv run pytest tests/app/test_business_risk_source_route.py tests/graph/test_business_risk_runner.py -q`

**Expected:**
- service 分流清晰
- 普通代码审查不回归

---

### Task 5: 保留现有 6 个业务风险节点，但让节点消费结构化上下文

**Files:**
- Modify: `python/graph/nodes/business_extractor.py`
- Modify: `python/graph/nodes/dataflow_tracer.py`
- Modify: `python/graph/nodes/invariant_checker.py`
- Modify: `python/graph/nodes/deep_reader.py`
- Modify: `python/graph/nodes/business_risk.py`
- Modify: `python/graph/nodes/self_verify.py`
- Test: `python/tests/graph/test_business_risk_runner.py`

- [ ] 不重写节点集合本身，继续使用当前 6 个业务风险节点。
- [ ] 让这些节点读取结构化 `source_package` / business-risk state，而不是从伪 diff 文本里反解析信息。
- [ ] 兼容 Java 新旧字段：
  - `methods` / `method_skeletons`
  - `snippet` / `raw_snippet`
  - `start_line/end_line` / `line_map`
- [ ] prompt/context 组装放到专用 service、runner 或节点内部 builder 中，不在 route 入口 flatten。
- [ ] 测试验证：
  - 节点仍是当前 6 个
  - 普通代码审查节点集合不受影响

**Run:**
- `cd python && uv run pytest tests/graph/test_business_risk_runner.py -q`

**Expected:**
- 节点仍是现有业务风险节点
- 运行模型已不再借壳普通 review path

---

### Task 6: 对齐 readiness / heartbeat 的 stateless worker 语义

**Files:**
- Modify: `python/app/dependencies.py`
- Modify: `python/app/routers/health.py`
- Verify: `python/services/registry.py`
- Verify: `python/app/main.py`
- Test: `python/tests/app/test_business_risk_source_readiness_route.py`

- [ ] readiness 的 `persistence` 字段语义改为：stateless worker 不依赖 task/result persistence。
- [ ] `llm` 与 `config` 继续表示此实例是否具备执行分析能力。
- [ ] 保留现有 worker heartbeat 循环与 Redis 注册，但在语义上明确：
  - heartbeat 只做观测 + 摘除
  - heartbeat 不承载任务状态
  - heartbeat 不承载幂等语义
- [ ] 如需要，可在 heartbeat 上报中追加轻量 worker 元信息，但不要引入 Python 调度状态。
- [ ] 测试覆盖：
  - llm key 缺失时 readiness 为 503
  - llm key 可用时 readiness 为 200
  - readiness 文案体现 stateless worker 语义

**Run:**
- `cd python && uv run pytest tests/app/test_business_risk_source_readiness_route.py -q`

**Expected:**
- readiness 测试通过
- heartbeat/readiness 语义与 1 Java : n Python 目标一致

---

### Task 7: 补齐 Python 侧回归并输出对 Java 的协作契约

**Files:**
- Verify: `python/app/routers/business_risk_source.py`
- Verify: `python/app/dependencies.py`
- Verify: `python/graph/business_risk_runner.py`
- Verify: `python/services/registry.py`
- Verify: `python/app/routers/review.py`

- [ ] 跑 Python 相关回归测试。
- [ ] 确认普通代码审查 sync 路径不受本次拆链影响。
- [ ] 向 Java 侧明确最终协作契约：
  - Python 主输入字段名：`source_package`
  - 切换期兼容：`source_bundle -> source_package` alias（如仍保留）
  - Python 返回字段：`run_id/task_id/status/report/proposed_memory_updates/trace_id`
  - Python 不再接收 `callback_*`
  - Python 不再负责 callback / idempotency / inflight / task state
- [ ] 如后续要彻底删除 alias，在 Java 切换完成后再做第二次清理。

**Run:**
- `cd python && uv run pytest tests/app/test_business_risk_source_route.py tests/graph -q`
- `cd python && uv run pytest -q`

**Expected:**
- Python 相关测试通过
- 双链路真正分开
- Java 与 Python 控制面边界固定

---

## 对其他终端的交付物

Python 终端完成后，需要向 Java 终端确认：
- Python 主输入字段名固定为 `source_package`
- 切换期是否仍保留 `source_bundle` alias
- Python 返回的 `status/report/proposed_memory_updates` 最终结构
- heartbeat/readiness 的 stateless worker 语义
- Python 不再承担 callback / idempotency / inflight / task state

Python 终端无需等待前端终端完成即可推进自己的链路拆分。

---

## Verification

- `business_risk_source.py` 主路径不再转 `ReviewRequest`
- `get_business_risk_service()` 不再是通用 `AIService(runner.run)` 薄包装
- business-risk 输出不再依赖通用 `GraphRunner._build_result()` 主路径
- 业务风险节点仍是当前 6 个节点
- Python 主输入为 `source_package`
- `source_bundle` 如保留，只是兼容 alias，不是主路径
- Python 不再发送 callback
- Python 不再维护 idempotency/inflight
- readiness 体现 stateless worker 语义
- worker heartbeat 仍可工作
- 普通代码审查路由、runner、result 不回归

---

## Gotcha

Python 最大的坑已经不再是“节点名字看起来独立，但其实还借住在 review path”，而是“表面上做成了 worker，实际上还偷偷保留控制面职责”。只要 Python 路由里还保存幂等缓存、维护 inflight、主动回调、或者依赖 task/result persistence 才能运行，它就不是真正适合 1 Java : n Python 的 stateless worker。