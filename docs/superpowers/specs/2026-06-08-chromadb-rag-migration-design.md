# ChromaDB RAG Migration Design

**Date:** 2026-06-08

## 背景

当前项目的 incident RAG 向量召回依赖 pgvector，核心检索和初始化逻辑位于：

- `python/config/settings.py`
- `python/repositories/db.py`
- `python/tools/incident_search.py`
- `python/graph/nodes/rag.py`
- `python/scripts/seed_incidents.py`
- `python/app/routers/health.py`

现状的 RAG 结构不是单一路径，而是混合召回：

- 向量召回
- 关键词召回
- 代码图谱召回
- RRF 融合
- LLM 风险关联分析

本次目标不是重写 RAG，而是把**向量召回后端从 pgvector 替换为 ChromaDB**，同时尽量保持：

- RAG 结果格式不变
- 召回策略不变
- Java / 前端接口不变
- Python 上层节点行为尽量不变

用户已确认：

- 全环境替换为 ChromaDB
- 使用嵌入式持久化 Chroma
- 本地持久化目录固定为 `D:\Chroma`
- 保留历史 incident 数据，并从现有 pgvector 数据迁移到 Chroma
- 接受在 `D:\Chroma` 下额外保存轻量本地关键词索引，以维持现有关键词召回能力

---

## 目标

将当前 incident RAG 的向量后端切换为 ChromaDB，并满足以下要求：

1. `incident_search` 的输出格式保持兼容。
2. `run_rag` 继续保留“向量召回 + 关键词召回 + 图谱召回 + RRF 融合”的结构。
3. Java 后端与前端接口不做改动。
4. Python 服务对上层节点暴露的字段不变，包括：
   - `rag_context`
   - `rag_analysis`
   - `rag_status`
   - 最终 `ReviewResult` 中的相关字段
5. `D:\Chroma` 成为唯一的 Chroma 持久化目录。
6. 历史 `incident_vectors` 数据能够迁移到 Chroma，并同步生成关键词索引。
7. `/ai/health` 的 `vector` 组件继续可观测，但探测逻辑改为面向 Chroma。

---

## 非目标

本次不做以下事情：

- 不重写 `python/graph/nodes/rag.py` 的整体结构
- 不改变 RRF 融合算法
- 不改变图谱召回逻辑
- 不改变 LLM 风险关联分析 prompt 和输出结构
- 不改 Java 的 `/api/review/*` 接口契约
- 不改前端 API 调用逻辑
- 不在本次引入独立 Chroma HTTP 服务
- 不在本次设计中实现运行时双写或双读
- 不在切换当天立即删除历史 pgvector 表或旧脚本

---

## 设计原则

### 1. 只替换向量后端，不重构上层协议

本次改造要像“换发动机，不换方向盘”。

需要尽量保持：

- `python/tools/incident_search.py` 的工具契约
- `python/graph/nodes/rag.py` 的调用顺序
- `python/graph/nodes/report.py` 对 `rag_analysis` 的消费方式
- `python/graph/runner.py` 对最终 `ReviewResult` 的封装方式

### 2. 保留混合召回，而不是把一切塞进 Chroma

当前系统不是纯向量 RAG，而是：

- 向量召回负责历史 incident 的语义相似性
- 关键词召回负责文本兜底和字面命中
- 图谱召回负责代码结构证据
- RRF 负责跨召回源融合

因此本次采用“**Chroma 负责向量召回 + 轻量本地索引负责关键词召回**”的方案，而不是把关键词召回也改写成 Chroma 的非严格等价实现。

### 3. 输出兼容优先于底层实现纯度

对外应继续返回与当前实现兼容的结果结构：

```python
{
  "title": ...,
  "snippet": ...,
  "source": ...,
  "service": ...,
  "tags": ...,
  "score": ...,
}
```

允许底层 score 语义与 pgvector 不完全同义，但必须保证：

- 可比较
- 可排序
- 不破坏现有 RRF 和调试体验

### 4. 切换完成前不销毁旧资产

虽然目标是全环境替换，但正式切流前不立即删除：

- pgvector 表
- 旧 seed 逻辑
- 旧测试基线

这样可以降低迁移窗口中的回滚风险。

---

## 方案选择

评估过 3 种方案：

1. **方案 A（推荐）**：Chroma 负责向量召回，轻量本地索引负责关键词召回
2. 方案 B：Chroma 负责向量召回，关键词召回直接从 Chroma documents/metadata 扫描
3. 方案 C：围绕 Chroma 重写统一 incident 检索层

最终选择 **方案 A**，理由：

- 最符合“结果格式不变 / 召回策略不变 / 接口尽量稳”的目标
- 最小侵入地替换 `incident_search` 底层实现
- 可以保留当前 `run_rag` 中向量召回与关键词召回分离的职责边界
- 避免借切库机会重写检索层，降低回归风险

---

## 目标架构

```text
run_rag
  ├─ 向量召回：incident_search -> ChromaDB (D:\Chroma)
  ├─ 关键词召回：本地轻量索引 (D:\Chroma 下)
  ├─ 图谱召回：沿用 code_graph / impact_radius
  └─ RRF 融合：保持不变
```

### 保持不变的部分

- `python/graph/nodes/rag.py` 的主流程
- `rag_context / rag_analysis / rag_status` 字段
- Java `ReviewController` / `PythonComputeClient`
- 前端 API 与最终 `ReviewResult` 输出
- 图谱召回逻辑
- RRF 融合逻辑
- 报告生成逻辑

### 替换的部分

- `python/tools/incident_search.py` 的底层向量召回实现
- `python/repositories/db.py` 中 pgvector 检索相关函数
- `python/repositories/db.py` 中 PostgreSQL 关键词检索实现
- `python/scripts/seed_incidents.py` 的写入目标
- `python/app/routers/health.py` 的 vector 健康探测逻辑

### 新的数据边界

`D:\Chroma` 目录下包含两类数据：

1. **Chroma 主数据**
   - documents
   - embeddings
   - metadatas
2. **轻量关键词索引**
   - 用于维持当前关键词召回能力
   - 保存 title/snippet/source/service/tags 等可文本查询字段

---

## 配置设计

当前 `python/config/settings.py` 与向量后端相关的字段包括：

- `vector_db_url`
- `vector_backend`
- `pgvector_table`
- `pgvector_top_k`

目标配置调整如下。

### 必改项

- `vector_backend` 从 `Literal["pgvector", "stub"]` 改为 `Literal["chromadb", "stub"]`
- 新增 `chroma_path: str = "D:/Chroma"`
- 新增 `chroma_collection: str = "incident_vectors"`
- 新增 `chroma_keyword_index_path`

### 命名兼容策略

`pgvector_top_k` 建议演进为中性名称 `vector_top_k`，但为了降低首轮改动范围，第一版可以：

- 先保留原字段名 `pgvector_top_k`
- 继续沿用其语义为“向量召回 top-k”
- 在后续清理阶段再统一重命名

这样可减少测试和上层改动量。

---

## 仓储层设计

当前 pgvector 逻辑集中在 `python/repositories/db.py` 的以下职责：

- 建连
- schema 初始化
- 向量检索
- 关键词检索

本次不建议继续把 Chroma 逻辑堆进同一组 pgvector 函数中。建议新增独立的 Chroma 仓储职责，例如：

- `get_chroma_client(settings)`
- `get_incident_collection(settings)`
- `bootstrap_chromadb(settings)`
- `search_incidents_chromadb(query, top_k, settings)`
- `search_incidents_keyword_local(query, top_k, settings)`

### 向量检索返回结构

`search_incidents_chromadb()` 必须保持返回结构与当前 pgvector 近似一致：

```python
[
  {
    "title": "incident-a",
    "snippet": "...",
    "source": "incident-review-001",
    "service": "review-service",
    "tags": ["cache", "transaction"],
    "score": 0.91,
  }
]
```

这样 `python/tools/incident_search.py` 的上层格式转换可继续沿用。

### score 语义

需要明确：

- Chroma 原生返回的 distance/score 语义可能与当前 pgvector 的 `1 - distance` 不同
- 对外仍然输出数值型 `score`
- 不承诺与 pgvector 数值完全同义
- 承诺排序稳定、结构兼容、RRF 可继续使用

设计上应显式定义一套分数映射策略，用于将 Chroma 返回值转换为当前系统可接受的 score。

---

## 工具层设计

当前 `python/tools/incident_search.py` 的逻辑是：

- `pgvector`：真实检索
- 其他：stub 占位
- 异常：返回 `DEGRADED`

改造后逻辑调整为：

- `chromadb`：调用 `search_incidents_chromadb()`
- `stub`：返回占位结果
- 异常：继续返回 `DEGRADED`

### 契约保持不变

以下内容保持不变：

- `ToolResult(name=self.name, payload=...)`
- `payload["findings"]` 的字段结构
- `payload["status"]`
- `payload["reason"]`
- 上层 `run_rag` 调用方式

也就是说，本次只替换实现分支，不改变工具契约。

---

## RAG 节点设计

`python/graph/nodes/rag.py` 的整体职责保持不变：

1. 向量召回
2. 关键词召回
3. 图谱召回
4. RRF 融合
5. LLM 风险关联分析

### 向量召回

`ctx.registry.run("incident_search", ...)` 继续作为入口，不改工具名，不改调用方式。

### 关键词召回

当前逻辑直接调用 PostgreSQL 查询函数；改造后保持节点职责不变，只替换为本地轻量索引查询函数。

### 图谱召回

不改 `code_graph` / `impact_radius` 相关逻辑。

### RRF 融合

不改 `_rrf_fusion()` 逻辑与参数来源。

### 输出

继续输出：

- `state["rag_context"]`
- `state["tool_logs"]`
- `state["rag_analysis"]`
- `state["rag_status"]`

上层 `python/graph/nodes/report.py` 和 `python/graph/runner.py` 无需感知底层数据库变化。

---

## 关键词召回设计

当前关键词召回依赖 PostgreSQL 文本查询。切换到 Chroma 后，设计为在 `D:\Chroma` 下维护一个轻量本地索引。

### 索引内容

至少保存：

- `id`
- `title`
- `snippet`
- `source`
- `service`
- `tags`

### 查询语义

查询目标不是构建一个复杂全文检索系统，而是维持当前系统对“字面命中”和“关键词兜底”的能力。

因此本地关键词索引实现应满足：

- 关键字段可被分词或直接字符串匹配
- 可以按 top-k 返回结果
- 返回结构与向量召回兼容
- 当索引不可用时可受控降级

### 为什么不直接从 Chroma 扫 documents

因为这样会让“关键词召回”退化为对 Chroma 存储结构的二次利用，查询语义和效果不稳定，也不利于保持当前策略边界。

---

## 数据迁移与 seed 设计

当前 `python/scripts/seed_incidents.py` 负责：

- 初始化 pgvector schema
- 从 JSON 读取 incident 数据
- 调 embedding API
- 将记录写入 `incident_vectors`

本次要拆成两类明确职责。

### 1. 从 JSON 建 Chroma

新的 seed 流程负责：

- 初始化 `D:\Chroma`
- 创建/获取 Chroma collection
- 从源 JSON 读取 incidents
- 生成或读取 embedding
- 将记录写入 Chroma collection
- 同步构建本地关键词索引

### 2. 从 pgvector 迁移到 Chroma

新增一次性迁移脚本，职责：

- 连接现有 pgvector 数据源
- 读取 `incident_vectors` 中已有记录和 embedding
- 将其写入 Chroma collection
- 同步生成本地关键词索引

### 幂等性要求

迁移和 seed 均应满足：

- 重复执行不会导致脏重复数据
- 可以通过稳定 id 覆盖更新
- 可以在本地删目录后完整重建

---

## 健康检查设计

当前 `/ai/health` 中 `vector` 探针直接检查 pgvector 连接。改造后需要保持组件名不变，但探针对象改为 Chroma。

### 新的 vector 健康定义

当 `vector_backend == "chromadb"` 时：

- 能打开 `PersistentClient(path="D:/Chroma")`
- 能访问目标 collection
- 必要时可检查 collection 元信息读取是否正常

当 `vector_backend == "stub"` 时：

- 维持当前轻量通过或跳过语义

### 对外语义

继续保留健康报告中的 `vector` 组件，避免上层健康消费方因字段变化受影响。

---

## 迁移流程

推荐迁移步骤如下：

1. 准备 `D:\Chroma` 持久化目录。
2. 初始化 Chroma collection 与关键词索引结构。
3. 执行一次性迁移：从 pgvector 的 `incident_vectors` 读数据并导入 Chroma。
4. 验证迁移数量、抽样召回结果与关键词索引完整性。
5. 将 Python 配置切换到：
   - `VECTOR_BACKEND=chromadb`
   - `CHROMA_PATH=D:\Chroma`
6. 运行测试和真实链路验证。
7. 验证稳定后，将旧 pgvector 路径保留为历史资产，暂不立即删除。

---

## 回滚策略

虽然目标是全环境替换，但首轮切换需要保守处理。

### 切换前

- 保留 pgvector 表
- 保留旧 seed 逻辑
- 保留旧测试基线

### 切换失败时

最稳妥回滚方式为：

1. 恢复到切换前代码版本
2. 恢复旧配置
3. 继续使用原 pgvector 数据

### 为什么不首轮删除旧资产

因为本次是底层召回存储的替换，风险集中在：

- score 映射
- 本地索引语义
- Chroma 嵌入式目录读写行为

在新链路经过一段稳定观察之前，不应把回滚路径主动销毁。

---

## 验证与测试策略

验证分 4 层。

### A. 仓储层

验证 `search_incidents_chromadb()`：

- 能按 query_embedding 返回 top-k 结果
- 返回结构与旧实现兼容
- 分数可用于排序和调试
- `D:\Chroma` 不存在、损坏或 collection 不可访问时能受控失败

### B. 工具层

验证 `IncidentSearchTool.run()`：

- `vector_backend=chromadb` 时走真实 Chroma 检索
- 返回 findings 格式与现状兼容
- 异常时仍返回 `DEGRADED`
- secret 脱敏逻辑保留

### C. 图节点层

验证 `python/graph/nodes/rag.py`：

- 向量召回源切换后，`rag_context` 结构不变
- `tool_logs` 中 method/status/reason 仍符合现有结构
- `rag_status` 的正常和降级逻辑不变
- `rag_analysis` 仍可被报告节点消费

### D. 健康与真实链路

验证：

- `/ai/health` 的 `vector` 组件正常
- 一次真实 `/ai/review/sync` 请求能跑完整链路
- 最终 `ReviewResult` 字段不变

### 测试文件对齐

当前需要替换或扩展的测试关注点包括：

- `python/tests/tools/test_incident_search_pgvector.py`
- `python/tests/repositories/test_db_pgvector_search.py`
- `python/tests/repositories/test_pgvector_bootstrap.py`
- `python/app/routers/health.py` 对应的健康检查测试

新的测试设计应覆盖：

- Chroma 仓储检索测试
- 本地关键词索引测试
- incident_search 的 chromadb 分支测试
- bootstrap / migration 测试
- vector 健康探针测试
- degraded fallback 测试

---

## 成功标准

本次改造完成后，至少要满足：

1. `incident_search` 输出格式与现状兼容。
2. `run_rag` 仍然保留“向量召回 + 关键词召回 + 图谱召回 + RRF”。
3. `ReviewResult` 输出字段不变。
4. `D:\Chroma` 成为 Chroma 唯一持久化路径。
5. 历史 `incident_vectors` 数据已迁移并可用于检索。
6. 关键词召回仍然存在，不因切库而消失。
7. `/ai/health` 中 `vector` 组件继续可观测。
8. 异常情况下，RAG 仍可通过 `DEGRADED` 语义受控降级。

---

## 风险与 gotchas

### 1. Chroma 嵌入式目录的并发写限制

Chroma 嵌入式持久化官方建议不要让多个进程同时写同一路径。

因此本设计默认：

- Python AI 服务负责读
- seed / migration 在离线窗口执行
- 不设计成服务运行时高频并发写 `D:\Chroma`

### 2. score 语义差异

Chroma 的 distance/score 与 pgvector 当前 `1 - distance` 不一定完全等价。

需要显式定义分数映射策略，确保：

- 排序稳定
- 对外仍有数值型 `score`
- 不破坏 RRF 与调试体验

### 3. 关键词召回不是可随意删除的“附属能力”

如果只完成 Chroma 向量迁移而没有同步维护本地关键词索引，就会实质改变当前召回策略。

因此本地关键词索引不是可选优化，而是本设计的一部分。

---

## 实施顺序建议

建议按以下顺序实施：

1. 增加 Chroma 配置项与 client/provider
2. 实现 Chroma 向量仓储查询
3. 实现本地关键词索引与关键词查询
4. 调整 `incident_search` 的 backend 分支
5. 调整 `/ai/health` 的 vector probe
6. 新增/替换测试
7. 编写迁移脚本与新 seed 脚本
8. 执行数据迁移
9. 切换环境配置并做全链路验证
10. 稳定后再考虑清理旧 pgvector 资产
