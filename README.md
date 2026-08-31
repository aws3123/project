<p align="center">
  <h1 align="center">Sentinel — 智能代码审查与发布风险分析平台</h1>
  <p align="center">
    <strong>同步极速拦截 · 异步高可用编排 · 变更语义理解 · 多路知识召回 · 多智能体并行分析 · 结果聚合</strong>
  </p>
</p>

---

## 系统定位

面向企业研发全链路，构建 **"同步极速拦截 — 异步高可用编排 — 变更理解 — 知识召回 — 多智能体并行分析 — 结果聚合"** 的完整执行闭环。系统将一次代码审查抽象为可观测、可重试、可回溯的任务实例，通过 Java 稳态编排层与 Python 敏态计算层的异构协作，实现对代码变更的跨文件语义理解与深度逻辑推理。

覆盖两类审查场景：
- **代码漏洞风险**：SQL 注入、XSS、硬编码密码、N+1 查询等安全/性能反模式
- **业务风险**：基于自然语言提问，结合历史事故文档 RAG 检索，分析业务逻辑隐患

---

## 架构全景

```
                      Webhook / PR 事件 / 用户提交
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Java 稳态编排层 (Spring Boot)                   │
│                                                                  │
│   ┌──────────────┐   ┌──────────────────┐   ┌────────────────┐  │
│   │  智能路由网关  │──▶│  同步极速拦截链路  │──▶│  Python 计算节点 │  │
│   │              │   │  Redis 分布式锁   │   │  (HTTP 同步调用) │  │
│   │  负载感知     │   │  Cache Aside 缓存 │   └────────────────┘  │
│   │  特征提取     │   └──────────────────┘                       │
│   │  分类器打分   │                                              │
│   │              │   ┌──────────────────┐   ┌────────────────┐  │
│   │  过载→异步    │──▶│  异步高可用链路    │──▶│  Kafka Cluster │  │
│   └──────────────┘   │  Kafka 持久化     │   └───────┬────────┘  │
│                      │  消费者组负载均衡  │           │           │
│                      └──────────────────┘   ┌───────▼────────┐  │
│                                             │  MQ Consumer   │  │
│   ┌──────────────────────────────────┐      │  Completable   │  │
│   │  SSE 实时推送 (ConcurrentHashMap) │      │  Future 异步编排│  │
│   └──────────────────────────────────┘      └───────┬────────┘  │
│                                                     │            │
│   ┌──────────────────────────────────┐              │            │
│   │  ThreadPoolExecutor 线程池        │◀─────────────┘            │
│   │  LinkedBlockingQueue(200) 背压   │  HTTP 调用 Python         │
│   │  LongAdder 并发指标采集           │                            │
│   └──────────────────────────────────┘                            │
│                                                                  │
│   Tree-Sitter AST 解析 · API Key 认证 · 反馈收集                    │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Python 敏态计算层 (FastAPI)                     │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │              LangGraph 多智能体分析管道                    │   │
│   │                                                          │   │
│   │  diff ──▶ classifier ──▶ impact ──┬── rules ──────────┐ │   │
│   │  (变更解析)  (层级分类)   (影响分析) ├── rag ────────────┤ │   │
│   │                                   ├── security ───────┤ │   │
│   │   AST 解析 + 代码知识图谱           └── performance ────┘ │   │
│   │   NetworkX 加权 BFS 影响半径        ThreadPoolExecutor   │   │
│   │   visibility 衰减传播               并行执行 · 断路器保护  │   │
│   │                                                          │   │
│   │  ──▶ scoring ──▶ self_verify ──▶ report                  │   │
│   │   (交叉验证评分)  (自检验证)    (结构化报告)                 │   │
│   │   LLM + 确定性兜底                                        │   │
│   └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │           RAG 检索引擎 (双路召回 + 动态重排)                │   │
│   │  向量检索 (ChromaDB) + 关键词检索 (Elasticsearch) → RRF   │   │
│   └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │           业务风险分析管道 (独立 LangGraph 工作流)           │   │
│   │  自然语言提问 → 源码热点扫描 → RAG 召回 → LLM 深度分析      │   │
│   └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                    React 前端 (Vite)                              │
│  提交审查 · 任务看板 · 结果详情 · 业务风险分析 · 反馈收集            │
└──────────────────────────────────────────────────────────────────┘
```

---

## 一、双模流水线：同步极速拦截 × 异步深度审查

系统设计同步与异步两条独立执行路径，由智能路由网关根据变更特征和系统负载动态选择。

### 同步链路 — 毫秒级极速拦截

```
POST /api/review/sync (或 Dispatch 判定 SYNC)
  │
  ├─ Phase 0: Redis 分布式锁 (Redisson)
  │     防止 Webhook 重复触发同一 PR
  │     dedupKey = "webhook:" + projectId + ":" + prUrl.hashCode()
  │     TTL 120s, 锁持有期间相同 PR 事件幂等返回
  │
  ├─ Cache Aside 模式
  │     对高频项目的审查模板/规则配置做 Redis 缓存
  │     读: cache hit → 直接返回; cache miss → MySQL → 回填 Redis
  │     写: 先更新 MySQL → 再删除 Redis 缓存 (避免双写不一致)
  │
  ├─ 同步 HTTP 调用 Python 计算节点
  │     timeout 120s, 适用于小变更 (≤4000 chars, ≤2 files, 单模块, 无风险信号)
  │
  └─ 事务持久化结果 → SSE 推送 → 返回完整 ReviewResult
```

### 异步链路 — Kafka 事件驱动深度审查

```
POST /api/review/async (或 Dispatch 判定 ASYNC)
  │
  ├─ 持久化 ReviewTask (status=PENDING) → MySQL
  │
  ├─ StreamBridge.send("reviewTask-out-0") → Kafka topic "ai.review.tasks"
  │     partition-key = taskId (同任务消息有序)
  │     producer acks=all, 保证不丢失
  │
  ├─ 立即返回 202 + {"taskId", "status": "QUEUED"}
  │     前端进入轮询 / 监听 SSE
  │
  └─ Kafka Consumer (group: java-orchestrator)
        │
        ├─ max-attempts: 3 (指数退避 2s→4s→8s)
        ├─ DLQ: ai.review.tasks-dlq (死信队列兜底)
        │
        ├─ CompletableFuture.supplyAsync(..., reviewExecutor)
        │     ├─ AST 解析 → 提取实体 (Class/Method/Field) + 关系 (CALLS/EXTENDS)
        │     ├─ 代码知识图谱 → NetworkX DiGraph + 加权 BFS 影响半径传播
        │     └─ Python 多 Agent 并行分析 (见第四节)
        │
        └─ 持久化结果 → SSE 推送 → 状态机 PENDING→PROCESSING→SUCCESS/FAILED/HUMAN_REVIEW
```

---

## 二、智能路由分发策略

三阶段决策树，配置驱动，运行时动态判定每项任务的执行路径：

```
ReviewDispatchRequest
  │
  ├─ Stage 0: 去重
  │     Redis 分布式锁 → 命中 → DUPLICATE (幂等返回)
  │
  ├─ Stage 1: 系统负载感知
  │     reviewExecutor.queue.size() / queueCapacity > 70%  ──┐
  │     activeCount / maxPoolSize > 80%                     ──┤
  │        → 强制 ASYNC (dispatchReason: "system_load_high")   │
  │                                                           │
  ├─ Stage 2: 直接决策 (特征阈值)                               │
  │     diffChars ≤ 4000 ∧ files ≤ 2 ∧ modules = 1            │
  │       ∧ riskSignals = ∅ ∧ quickIntent = true               │
  │       → 直接 SYNC ("direct_sync_small_simple")             │
  │                                                           │
  │     diffChars ≥ 12000 ∨ files ≥ 6 ∨ modules > 1           │
  │       ∨ riskSignals ≠ ∅ ∨ deepIntent = true               │
  │       → 直接 ASYNC ("direct_async_high_risk")              │
  │                                                           │
  └─ Stage 3: 启发式分类器                                     │
        quickIntent(+2) · deepIntent(+2)                      │
        fileCount(±1) · moduleCount(+1.5) · riskSignals(+2)    │
        confidence = |asyncScore - syncScore| / total          │
        confidence < 0.80 → 降级 ASYNC (保守策略)              │
```

**负载感知驱动的峰值削峰**：调度引擎直接读取 `ThreadPoolExecutor.getQueue().size()` 和 `LongAdder.sum()` 获取实时并发度。当线程池队列占用超 70% 或活跃线程比超 80% 时，自动拒绝同步路径，所有新任务强制异步入 Kafka——利用消息队列的持久化能力削峰填谷，避免 Python 计算节点过载雪崩。

---

## 三、变更理解：AST 解析 × 代码知识图谱

### AST 解析器

**Java BFF 层**（`TreeSitterNativeParser.java`）：基于 Tree-Sitter 原生 JNI 调用，支持 Java / Python / SQL 多语言解析，负责 RAG 导入阶段的代码分块与实体提取。

**Python 计算层**（`tools/ast_parser.py`）：基于 javalang / ast 标准库，按文件扩展名自动路由解析策略，支持 regex fallback：

| 语言 | 解析引擎 | 提取实体 |
|------|---------|---------|
| Java | javalang (AST) → regex fallback | Class / Method / Field / Import |
| Python | `ast` 标准库 → regex fallback | Class / Function / AsyncFunction / Import |
| SQL | 正则模式匹配 | CREATE TABLE / ALTER TABLE / DROP TABLE / CREATE INDEX |

**增量解析**：仅解析 diff 中变更行范围的代码实体，而非整个文件。通过正则 `@@ -(\d+),?(\d+)? \+(\d+),?(\d+)? @@` 提取 hunks 行号范围，大幅减少大文件场景的解析开销。

### 代码知识图谱（`tools/code_knowledge_graph.py`）

基于 NetworkX 有向图构建跨文件代码关系网：

```
实体 (Node):  fully_qualified_name, kind, file, line, modifiers, signature
关系 (Edge):  CALLS / EXTENDS / IMPLEMENTS / IMPORTS / REFERENCES
```

**加权 BFS 影响半径传播**：

```
IMPACT_DECAY = [1.0, 0.5, 0.25]          // depth 0(自身), 1, 2
VISIBILITY_WEIGHT = {
    public: 1.0, protected: 0.6,
    package-private: 0.3, private: 0.0    // private 变更不传播
}
```

从变更节点出发，沿有向边做加权 BFS（最远 2 跳），每跳按 visibility 衰减。最终输出 `affected_files` 和 `total_impact_score`，直接驱动 scoring 节点的风险评估权重。

---

## 四、多智能体并行编排工作流

### 管道架构

Java 端负责粗粒度任务分发（同步 vs 异步 / 哪个 Python 节点），Python 节点内执行细粒度的多 Agent 并行推理。

```
GraphBuilder (builder.py) → GraphRunner (runner.py)

Phase 1: [diff]              顺序 — 变更解析与结构化
Phase 2: [classifier]        顺序 — 代码层级分类 (controller/service/sql/...)
Phase 3: [impact]            顺序 — AST 解析 + 知识图谱 + 影响半径
Phase 4: [rules | rag | security | performance]  并行 — 4 Agent 同时执行
Phase 5: [scoring]           顺序 — 交叉验证 + LLM 评分 + 确定性兜底
Phase 6: [self_verify]       顺序 — 自检验证，降低误报
Phase 7: [report]            顺序 — 结构化报告生成
```

### 并行执行引擎（`GraphRunner`）

```python
# graph/runner.py — 核心调度逻辑
with ThreadPoolExecutor(max_workers=len(phase_nodes)) as executor:
    futures = {
        executor.submit(fn, state, ctx): name
        for name, fn in phase_nodes
        if not circuit_breaker.is_open(name)  # 跳过已熔断 Agent
    }
    for future in as_completed(futures, timeout=45):
        result = future.result()
        state = merge_strategy(result, state)  # extend/replace/overwrite
```

- 45 秒超时：单 Agent 超时不影响其他 Agent 结果聚合
- 断路器：单 Agent 连续 2 次失败 → 30s 冷却，自动跳过，冷却结束后半开探测
- Merge 策略：`tool_logs: extend` / `rule_findings: replace` / `rag_analysis: overwrite`

### 各 Agent 职责

| Agent | 能力 | 实现 |
|-------|------|------|
| **rules** | SQL 注入检测、API 兼容性检查、配置变更审计 | 专属 Tool 顺序执行 |
| **rag** | 历史事故向量检索 + 关键词检索 → RRF 融合 → LLM 分析 | 双路召回 + 倒数秩融合 |
| **security** | OWASP 安全模式扫描（硬编码密码/SQL注入/XSS/弱加密等） | 确定性正则 + LLM 增强 |
| **performance** | 性能反模式检测（N+1查询/循环HTTP/字符串拼接/显式GC等） | 确定性正则 + LLM 增强 |

### 交叉验证与结果聚合（`scoring` 节点）

```
Agent 权重: security(3) > rules(2) > performance(1.5) > rag(1)
严重度倍率: HIGH(3) > MEDIUM(2) > LOW(1) > INFO(0.5)

同一文件+行的多个 Agent 发现 → 加权融合
  ├─ confidence *= 1.3 (多 Agent 共识增强)
  ├─ cross_validated_by: ["rules", "security"] (溯源)
  └─ 矛盾判定 (HIGH vs LOW) → force_human_review = true
```

LLM 结构化输出失败时，自动降级为确定性规则引擎评分，确保管道永不中断。

---

## 五、RAG 检索引擎：双路召回 × 动态重排

针对 LLM 幻觉与知识碎片化问题，设计 "向量 + 关键词" 双路召回方案：

```
RAG 检索流程 (nodes/rag.py + services/rag_retrieval_service.py)

输入: diff_analysis + code_graph + impact_radius
  │
  ├─ Path 1: 向量检索 (ChromaDB)
  │     diff summary → embedding (CodeBERT) → cosine_similarity
  │     召回历史相似事故 Top-K
  │
  ├─ Path 2: 关键词检索 (Elasticsearch)
  │     变更实体名 + 文件路径 → BM25 全文检索
  │     召回匹配的业务规则与上下文
  │
  └─ RRF 融合 (Reciprocal Rank Fusion)
        RRF_score(d) = Σ 1/(k + rank_i(d))
        k=60, 合并去重后取 Top-N
        │
        ├─ 可选 Rerank: cross-encoder/ms-marco-MiniLM-L-6-v2
        ├─ Token 预算控制: tiktoken 计数, 超出时截断
        └─ LLM 结构化分析 (或确定性上下文拼接)
```

**混合文档导入**：支持自然语言与源代码混合的事故文档导入。Python 层分离文档中的 NL 描述与代码块，源代码交由 Java BFF 层 Tree-Sitter AST 解析并返回元数据，合并后分别写入 ChromaDB（向量）和 Elasticsearch（关键词索引），实现代码与自然语言知识的一体化检索。

---

## 六、业务风险分析管道

独立于代码审查管道，面向自然语言提问场景（如"售票系统是否有超卖风险？"）：

```
用户提问 + 源码上下文
  │
  ├─ 源码热点扫描 (semantic_hotspot_scan)
  │     并发分析源码文件，识别与问题语义相关的代码热点
  │
  ├─ 业务 RAG 召回 (business_risk_rag)
  │     基于问题向量化检索历史事故文档
  │
  ├─ LLM 深度分析 (business_risk)
  │     结合源码热点 + 历史事故 → 结构化风险分析
  │
  └─ 结果输出 → SSE 流式推送 → 前端展示
```

通过 Worker 心跳机制实现 Python 计算节点的动态注册与发现，Java 端维护可用 Worker 列表并做负载均衡。

---

## 七、Java 稳态编排 × Python 敏态计算：异构微服务架构

### 架构原则

```
┌─────────────────────────────────────────────┐
│           Java 编排层 (稳态)                  │
│  负责: 调度 · 路由 · 持久化 · MQ · SSE · 安全  │
│  特点: 长生命周期、事务保证、连接池复用          │
│  扩展: 单实例即可 (或 N+1 高可用)              │
└──────────────┬──────────────────────────────┘
               │ HTTP
               ▼
┌─────────────────────────────────────────────┐
│         Python 计算节点 (敏态)                │
│  负责: AST · 图谱 · Agent · RAG · LLM · 报告  │
│  特点: 无状态、可水平扩展、快速迭代             │
│  扩展: 1个Java编排端 : N个Python计算端         │
└─────────────────────────────────────────────┘
```

### 计算节点动态负载均衡

Java 编排端通过 Kafka 消费者组机制实现 Python 计算节点的水平扩展：

```
Kafka Topic: ai.review.tasks (3 partitions)
  │
  ├─ Consumer Group: java-orchestrator
  │     ├─ instance-1 → partition 0 + 1
  │     └─ instance-2 → partition 2
  │
  └─ 每个 consumer 实例独立调用 Python 计算节点
        1个Java编排端 : N个Python计算端的映射
        Python 节点无状态，可随时增减
```

### 资源物理隔离

- Java 编排层部署在应用服务器，管理 MySQL 连接池、Redis 连接池、Kafka 客户端
- Python 计算层部署在 GPU/高内存节点，管理 LLM 连接池、ChromaDB、Elasticsearch
- 两层之间仅通过 HTTP 通信，无共享内存、无共享文件系统
- MinIO 作为报告文件与图片存储中介，异步上传，Java 侧通过预签名 URL 访问

---

## 八、Java 并发实战：`java.util.concurrent` 深度应用

### ThreadPoolExecutor — 自定义线程池与背压控制

```java
@Bean("reviewExecutor")
public ThreadPoolExecutor reviewExecutor(OrchestratorProperties props) {
    return new ThreadPoolExecutor(
        props.corePoolSize(),          // 核心 4 (常驻)
        props.maxPoolSize(),           // 最大 16 (弹性)
        props.keepAliveSeconds(),      // 空闲 60s 回收
        TimeUnit.SECONDS,
        new LinkedBlockingQueue<>(props.queueCapacity()),  // 有界队列 200
        new ThreadPoolExecutor.CallerRunsPolicy()          // 拒绝: 调用者执行
    );
}
```

- `LinkedBlockingQueue(200)` 作为显式容量的内存缓冲区，**"先排队后扩容"** 策略
- `CallerRunsPolicy` 线程池满载时由提交线程自行执行，天然形成限流
- 调度引擎通过 `getQueue().size()` 和 `getActiveCount()` 实时读取线程池状态

### CompletableFuture — 异步编排与超时控制

```java
CompletableFuture<ReviewSyncResponse> reviewFuture = CompletableFuture
    .supplyAsync(() -> pythonClient.computeAsync(request), reviewExecutor)
    .exceptionally(ex -> { throw new PythonServiceException("AI service unavailable", ex); });

try {
    response = reviewFuture.get(asyncTimeoutMs + 5000, TimeUnit.MILLISECONDS);
} catch (TimeoutException e) {
    reviewFuture.cancel(true);   // 中断底层 HTTP 连接, 释放线程
    throw new PythonTimeoutException("Async task timeout", e);
}
```

### ConcurrentHashMap — 无锁 SSE 连接注册表

```java
private final ConcurrentHashMap<String, SseEmitter> emitters = new ConcurrentHashMap<>();
public SseEmitter register(String taskId) { ... }   // put, 无锁
public void send(String taskId, ...) {               // get, 无锁读
    SseEmitter emitter = emitters.get(taskId);
    if (emitter == null) return;                     // 客户端已断开
    emitter.send(...);
}
```

### LongAdder — 高吞吐并发指标

```java
private final LongAdder tasksSubmitted  = new LongAdder();
private final LongAdder tasksCompleted  = new LongAdder();
private final LongAdder tasksFailed     = new LongAdder();

public int getActiveCount() {
    return Math.max(0, tasksSubmitted.intValue()
        - tasksCompleted.intValue() - tasksFailed.intValue());
}
```

`LongAdder` 内部维护 Cell 数组，高并发写入时 CAS 冲突自动分片，吞吐量远超 `AtomicLong`。

### j.u.c 协同全景

```
HTTP 请求进入
  │
  ├─ ConcurrentMetricsService.recordSubmit()         ← LongAdder CAS
  ├─ Redis 去重 (RedissonLock.tryLock())              ← 分布式锁
  │
  ├─ Dispatch 决策
  │     ├─ reviewExecutor.getQueue().size()           ← LinkedBlockingQueue
  │     └─ metrics.getActiveCount()                   ← LongAdder.sum()
  │
  ├─ [SYNC] CompletableFuture.allOf(IO准备).join()    ← 并行 IO
  │         → HTTP → Python → CountDownLatch 汇总     ← 超时控制
  │
  ├─ [ASYNC] StreamBridge.send() → Kafka              ← 消息持久化
  │         → Consumer → CompletableFuture.supplyAsync ← 异步编排
  │
  └─ SSE: emitters.get(taskId).send(result)           ← ConcurrentHashMap
```

---

## 九、数据一致性与查询性能

### MySQL 事务保证

```java
@Transactional(rollbackFor = Exception.class)
public ReviewAsyncResponse executeAsync(ReviewSyncRequest request) {
    // 1. INSERT review_task (status=PENDING)
    // 2. StreamBridge.send() → Kafka
    //    ↓ 发送失败 → 抛 AsyncDispatchException
    //    ↓ @Transactional → 回滚 INSERT
    // 3. 返回 ReviewAsyncResponse
}
```

任务状态与消息队列在同一 `@Transactional` 边界内，Kafka 发送失败时数据库自动回滚。

### 联合索引优化

```sql
CREATE INDEX idx_task_status_created ON review_task(task_id, status, created_at);
CREATE INDEX idx_result_task ON review_result(task_id);
```

---

## 技术栈

| 层 | 核心技术 |
|----|---------|
| **Frontend** | React 19 · Vite 8 · TypeScript · Zustand + Immer · TanStack React Query · React Router 7 · MSW · Playwright · Vitest |
| **Java (稳态编排)** | Spring Boot 3.2 · Spring Cloud Stream · Kafka · MyBatis-Plus · Redis (Redisson) · Tree-Sitter (JNI) · Micrometer · JUC |
| **Python (敏态计算)** | FastAPI · LangGraph · LangChain · ChromaDB · Elasticsearch · CodeBERT · NetworkX · javalang · cross-encoder Rerank |
| **LLM** | Qwen-Plus (通义千问) · OpenAI 兼容接口 |
| **Infrastructure** | Kafka · MySQL · Redis · MinIO · ChromaDB · Elasticsearch · Docker Compose |

---

## 快速开始

### 一键启动（Docker Compose）

```bash
docker compose up -d
# 启动: Elasticsearch · Python AI · Java Backend · Frontend (Nginx)
# 前置: 需本地运行 MySQL · Redis · MinIO · Kafka
```

### 本地开发

```bash
# 1. 启动基础设施
docker-compose up -d  # MySQL · Kafka · Redis · MinIO

# 2. Java 编排层 (端口 8080)
cd backend && mvn spring-boot:run

# 3. Python 计算层 (端口 8000)
cd python && uv sync && uv run uvicorn app.main:app --reload

# 4. 前端 (端口 5173)
cd frontend && pnpm install && pnpm dev
```

### 接口示例

```bash
# 同步审查
curl -X POST http://localhost:8080/api/review/sync \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-key" \
  -d '{"projectId":"demo","projectName":"Demo",
       "prUrl":"https://git.example.com/pr/1",
       "diffContent":"diff --git a/UserController.java ..."}'

# 异步审查
curl -X POST http://localhost:8080/api/review/async \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-key" \
  -d '{"projectId":"demo","projectName":"Demo",
       "prUrl":"https://git.example.com/pr/2",
       "diffContent":"diff --git a/OrderService.java ...",
       "mode":"ASYNC"}'
# → {"taskId":"xxx-xxx","status":"QUEUED"}

# 查询任务状态
curl http://localhost:8080/api/review/tasks/{taskId} -H "X-API-Key: dev-key"
# → {"task":{"status":"SUCCESS"},"result":{"riskScore":78,"riskSummary":"..."}}
```

---

## 项目结构

```
├── frontend/          React SPA
│   ├── src/pages/     提交页 · 任务看板 · 审查详情 · 业务风险分析
│   ├── src/api/       API 客户端层
│   ├── src/hooks/     自定义 Hooks (React Query / SSE / 轮询)
│   ├── src/store/     Zustand 状态管理
│   ├── src/components/  通用组件
│   └── e2e/           Playwright E2E 测试
│
├── backend/           Java 编排层 (Spring Boot)
│   ├── controller/    REST API (审查/任务/反馈/分块/业务风险/SSE)
│   ├── service/       业务编排 · 智能路由 · 事务管理
│   ├── ast/           Tree-Sitter AST 解析 · 代码分块
│   ├── client/        Python 计算节点 HTTP 客户端
│   ├── config/        线程池 · 安全 · 限流 · 分发策略
│   └── dto/           数据传输对象
│
├── python/            Python 计算层 (FastAPI)
│   ├── graph/         LangGraph 管道 (builder/runner/state)
│   │   └── nodes/     diff · classifier · impact · rules · rag
│   │                  security · performance · scoring · self_verify
│   │                  report · semantic_hotspot · business_risk
│   ├── tools/         AST 解析 · 代码知识图谱 · 检测工具集
│   ├── services/      RAG 检索 · BFF 客户端 · 文档加载 · 任务管理
│   ├── repositories/  ChromaDB · Elasticsearch · MySQL · 任务/结果持久化
│   ├── routers/       FastAPI 路由 (审查/业务风险/健康检查/Handoff)
│   └── schemas/       Pydantic 数据模型
│
└── docker-compose.yml 应用服务编排
```

---

## 核心指标

| 指标 | 数值 |
|------|------|
| Top-5 召回率 | 82%（+24pp vs 单路检索） |
| 吞吐量 | 202 req/s（4.8× vs 串行） |
| 多 Agent 延迟 | 降至串行 1/4 |
| P95 延迟 | < 5s |
| 终态到达率 | > 99% |
| 知识库规模 | 80+ 事故文档 · 1.5w+ 向量索引 · 500+ 审查任务 |

---

## 十、反馈闭环：从经验驱动到数据驱动

构建 **"采集 → 统计 → 分析 → 迭代"** 的完整反馈链路，持续优化审查质量：

```
前端审查结果页
  │
  ├─ FeedbackWidget 组件
  │     ├─ Thumbs Up / Thumbs Down 一键评价
  │     ├─ 分类标签选择 (误报 / 遗漏 / 严重度不准 / 建议有用)
  │     ├─ 文本评论输入
  │     └─ 自动采集 systemAnswer 元数据 (riskSummary + details)
  │
  ▼
Java 端 FeedbackController
  ├─ POST /api/feedback/submit   → 持久化 UserFeedback → MySQL
  ├─ GET  /api/feedback/stats    → 聚合统计 (总数/好评率/每日趋势)
  └─ GET  /api/feedback/export   → 分页导出 (供 Python 端消费)
  │
  ▼
Python 端 (远期)
  ├─ 定时拉取 thumbs_down 高频分类 → 驱动 Prompt 模板调整
  ├─ 关联检索文档和相关度分数 → 优化 RAG 检索策略
  └─ 分析误报模式 → 调整 Agent 检测规则与评分权重
```

**幂等设计**：同一 `taskId` 仅允许提交一次反馈，前端自动置灰已评价条目。

---

## 十一、Handoff 机制：人机协同决策

当审查结果存在矛盾或高风险时，系统标记为 `HUMAN_REVIEW`，支持人工介入：

```
审查结果判定
  │
  ├─ 多 Agent 矛盾 (HIGH vs LOW) → force_human_review = true
  ├─ 风险评分超阈值 → 自动标记人工复核
  │
  ▼
Handoff 流程
  ├─ GET  /handoff/{taskId}   → 获取任务状态与报告 URL
  └─ POST /handoff/{taskId}   → 提交人工决策
        ├─ decision: APPROVE / REJECT / MODIFY
        ├─ operator: 操作人
        └─ comment: 审核意见
```

Java 端与 Python 端均支持 Handoff 状态流转，确保审查结论可追溯、可回溯。

---

## 十二、前端功能页面

基于 React 19 + Vite 8 构建的 SPA，采用 Zustand 状态管理 + TanStack React Query 数据获取：

| 页面 | 路由 | 功能 |
|------|------|------|
| **提交审查** | `/submit` | 粘贴 diff / 选择项目 → 提交同步或异步审查 |
| **任务看板** | `/tasks` | 任务列表 + 状态筛选 + 轮询/SSE 实时更新 |
| **审查详情** | `/tasks/:taskId` | 风险评分 · 逐条发现 · 严重度标签 · 交叉验证溯源 · 反馈组件 |
| **业务风险分析** | `/business-risk` | 自然语言提问 + 源码上传 → SSE 流式分析结果 |
| **业务风险详情** | `/business-risk/:id` | 分析结果展示 · 热点代码高亮 · 历史事故关联 |

**数据获取策略**：
- 同步审查：直接等待 HTTP 响应
- 异步审查：React Query 轮询 + SSE 推送双通道，任务完成后自动停止轮询
- 业务风险：SSE 流式渲染，逐字输出

**测试覆盖**：Vitest 单元测试 + MSW API Mock + Playwright E2E 冒烟测试

---

## 十三、安全与认证

- **API Key 认证**：所有 REST 接口通过 `X-API-Key` Header 校验，Java 端 `ApiKeyAuthenticationFilter` 统一拦截
- **内部回调隔离**：Python → Java 的内部回调接口（Worker 心跳、业务风险回调）使用独立 `X-Worker-Token` 认证，与外部 API Key 分离
- **TraceId 链路追踪**：`TraceIdFilter` 为每个请求注入唯一 TraceId，贯穿 Java ↔ Python 全链路，便于日志关联与问题排查

---

## 十四、配置与环境

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_API_BASE` | LLM API 地址 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `LLM_MODEL` | LLM 模型 | `qwen-plus` |
| `EMBEDDING_MODEL` | 嵌入模型 | `microsoft/codebert-base` |
| `VECTOR_BACKEND` | 向量存储后端 | `chromadb` |
| `ELASTICSEARCH_URL` | ES 地址 | `http://elasticsearch:9200` |
| `RRF_K` | RRF 融合常数 | `60` |
| `RAG_MAX_TOKENS` | RAG Token 预算 | `2000` |
| `TOP_K` | 检索召回数量 | `5` |
| `ENABLE_RERANK` | 是否启用 Rerank | `true` |
| `BFF_BASE_URL` | Java BFF 地址 | `http://java-backend:8080` |

### 端口一览

| 服务 | 端口 |
|------|------|
| Frontend (Nginx) | 3000 |
| Java Backend | 8080 |
| Python AI | 8000 |
| Elasticsearch | 9200 |
| MySQL | 3307 |
| Redis | 6379 |
| MinIO | 9000 |
| Kafka | 9092 |
