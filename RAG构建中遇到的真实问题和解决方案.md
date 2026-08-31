# RAG 构建中遇到的真实问题和解决方案

> 本文档总结了在 Sentinel 项目 RAG 系统重构过程中遇到的真实风险点和对应解决方案，涵盖数据导入、检索质量、系统可靠性、兼容性和业界对齐五个维度。

---

## 一、数据导入阶段

### 问题 1：NL 与代码块的关联错误

**场景**：事故文档由自然语言描述和源代码交替组成。导入时需要把每段代码和它对应的 NL 描述关联起来，否则检索时会出现"代码找到了但描述对不上"的错误匹配。

**真实风险**：
- 代码块后面紧跟的段落才是它的解释（"上述代码存在漏洞因为…"），而非前面的段落。
- 一段 NL 描述可能关联多个代码块。
- 代码块出现在章节开头，前面没有 NL 段落。

**解决方案**：保序遍历 + 前置 NL 关联
- 按文档线性顺序遍历，每遇到代码块，取前一个 NL 段落作为关联描述。
- Markdown 标题（`##`/`###`）或空行作为分节边界，跨节不关联。
- 一段 NL 后紧跟多个代码块时，共享同一段 NL 描述。
- 在 metadata 中存储 `position_in_doc`（位置索引），保留原始顺序信息。

---

### 问题 2：PDF/DOCX 格式下代码块边界丢失

**场景**：从网上收集的事故文档格式多样（HTML、PDF、MD、DOCX）。PDF 经 PyPDFLoader 转纯文本后，代码和 NL 混在一起，没有 ``` 围栏标记，无法确定代码从哪行开始到哪行结束。

**解决方案**：三层代码块边界识别策略

| 层次 | 适用场景 | 识别方式 |
|---|---|---|
| Layer 1 | Markdown / HTML | 检测 ``` 围栏语法和 `<pre><code>` 标签 |
| Layer 2 | PDF / DOCX 转纯文本后 | 段落级启发式评分：行尾 `;`/`{`/`}` 频率高 +2 分，含 `public`/`class`/`def` 关键字 +1 分，缩进一致 +1 分，含中文标点 -2 分，评分 ≥3 判定为代码 |
| Layer 3 | 无法确定边界 | 整段发 BFF，BFF 的 fallbackChunk 按字符数分块，标记 `ast_status: "boundary_unclear"` |

- 导入后打印每个 chunk 的 NL 和 code 摘要，供人工 spot-check。

---

### 问题 3：事故文档中的代码本身不完整

**场景**：事故文档展示的是有漏洞的代码，经常省略 import 语句、用 `// ...` 表示省略，或者代码本身语法不完整。BFF 的 AST 解析器可能解析失败。

**解决方案**：降级 + 上下文补偿
- BFF 解析失败时降级为 fallback chunk（无 AST 元数据），标记 `ast_status: "fallback"`。
- 查询时对 `ast_status != "parsed"` 的 chunk 降低权重（score × 0.8）。
- 保留 `// ...` 省略标记在 `code_content` 中，让向量化时上下文参与 embedding。

---

### 问题 4：AST 过度分块稀释 NL 语义

**场景**：一段 200 行的 Java 类代码包含 15 个方法。BFF 的 AST 解析将其切成 15 个 chunk，每个方法一个。但只有一段 NL 描述关联这段代码。15 个 chunk 共享同一段 NL，向量化后 15 个向量高度相似，在检索时挤占 top-k 名额，导致其他相关事故被挤出。

**解决方案**：导入时类级聚合
- 同一 `parentClass` 的所有方法 chunk 在导入时合并为一个类级别 chunk。
- `entity_name` = 类名，`entity_kind` = `"class"`，`code_content` = 完整类代码（按 line_start 排序拼接，去重重叠行）。
- 聚合后一个类只产生一个向量，不再挤占 top-k 名额。
- 无 `parentClass` 的独立函数/方法 chunk 不做聚合，保持方法级别。
- **业界依据**：cAST 论文（CMU + Augment Code, 2025）验证 AST 结构感知分块优于固定大小分块，类级聚合进一步保持语义完整性。

---

### 问题 5：图片引用断裂

**场景**：当前事故文档已有图片处理流程（OCR + MinIO 上传 + URL 替换）。新的混合文档导入流程中，如果文档同时包含代码和图片，图片处理逻辑可能遗漏。

**解决方案**：导入时保留图片处理
- `ingest_mixed_docs.py` 在提取代码块后，仍调用现有 `ImageService` 处理文档中的图片。
- chunk 的 `doc_metadata` 中包含 `image_urls` 和 `image_texts` 字段，保持与现有 schema 兼容。

---

## 二、检索质量

### 问题 6：语言过滤过度收窄召回范围

**场景**：用户提交了一段 Java 代码做审查。如果向量查询用 `where={"language": {"$in": ["java"]}}` 硬过滤，会排除所有 Python/TypeScript 的事故。但一个 Python 的 SQL 注入事故与 Java 的 SQL 注入事故在风险模式上是高度相关的，不应被排除。

**解决方案**：语言 Boost 而非硬过滤
- 向量召回不设 `where` 过滤条件。
- ES 关键词召回中语言匹配使用 `should` + `boost` 而非 `filter`。
- RRF 融合后做语言 boost 排序（同语言 +20%），但不排除其他语言。

---

### 问题 7：实体名碰撞导致误召回

**场景**：用户提交的代码中有 `save()` 方法。ES 用 `entity_name: save` 做关键词匹配，命中了 10 个事故中所有包含 `save()` 的代码块——但这些事故可能完全不相关（一个是 SQL 注入，一个是缓存失效）。

**解决方案**：降低实体名权重
- ES 查询中 `entity_name` 字段不单独做匹配。
- 代码匹配主要依赖 `code_content` 全文匹配（权重 ×1.5）。
- NL 匹配权重最高（`nl_description` ×3），让 NL 语义主导排序。

---

### 问题 8：缺少精排导致 top-k 质量不足

**场景**：RRF 融合只基于排名做简单合并，缺乏 query-document 交互建模。对于"事故文档 + 代码"这种需要判断语义相关性的场景，缺少精排会导致 top-5 中混入低相关结果。

**解决方案**：Cross-Encoder 精排
- 在 RRF 融合 + 语言 boost 后增加 Cross-Encoder 精排阶段。
- 使用 `cross-encoder/ms-marco-MiniLM-L-6-v2`（~80MB），对 top_k×3 候选精排，输出 top_k。
- Cross-Encoder 分数直接覆盖 RRF 分数，因为 cross-encoder 分数反映 query-doc 真实相关性。
- 精排失败时降级为 RRF 排序。
- **业界依据**：Production Hybrid RAG 项目实测 +27% nDCG@10；ZeroEntropy 指南显示精排可提升检索质量达 48%、减少 LLM 幻觉 35%。

---

### 问题 9：embedding 模型对 NL+代码混合文本的语义偏移

**场景**：当前 embedding 模型是 `microsoft/codebert-base`，专为代码理解训练。但统一 chunk 的向量化文本是 `NL描述 + 代码`。CodeBERT 对中文 NL 的编码能力可能不足，导致向量相似度不能准确反映 NL 语义相关性。

**解决方案**：短期 + 长期分阶段
- 短期：向量化时 NL 在前、代码在后（CodeBERT 对前缀文本更敏感）。通过 ES 关键词召回（IK 分词器）补充中文 NL 的匹配能力。
- 长期：评估更换为 `bge-large-zh` 或 `m3e-base` 等中英双语 embedding 模型。

---

### 问题 10：无相关结果时 LLM 幻觉

**场景**：知识库中无相关事故时，所有检索结果分数都低，但 LLM 仍可能基于低质量上下文生成幻觉内容。

**解决方案**：分数阈值兜底
- 设置 `min_retrieval_score=0.15`。
- 所有候选分数低于阈值时返回空 `rag_context` + 状态 `"NO_RELEVANT_INCIDENTS"`。
- **业界依据**：Production Hybrid RAG 项目明确指出"if top-10 docs all miss the answer, the LLM will happily hallucinate. Always include a 'no answer found' fallback."

---

## 三、系统可靠性

### 问题 11：导入时 BFF 未启动

**场景**：执行导入脚本时 Java BFF 服务未启动。所有代码块的 AST 解析都失败，全部降级为无元数据 chunk。导入"成功"但所有 chunk 都没有 `ast_metadata`，后续查询的元数据过滤完全失效。

**解决方案**：健康检查 + 统计告警
- 导入脚本启动时先 ping BFF（`GET /actuator/health`），不可用时直接报错退出。
- 导入完成后打印统计：`AST 成功 chunk 数 / 降级 chunk 数`。
- 降级比例 > 30% 时打印警告，提示检查 BFF 服务状态。

---

### 问题 12：ChromaDB 并发写入冲突

**场景**：在 Python 服务运行（读取 ChromaDB）的同时，执行导入脚本写入 ChromaDB。Chroma 嵌入式模式不支持并发写，可能锁死或数据损坏。

**解决方案**：离线窗口执行
- 导入脚本在离线窗口执行（停止 Python AI 服务后运行）。
- 文档中明确标注此约束。

---

### 问题 13：LangChain 依赖在 Docker 环境中的兼容性

**场景**：LangChain 及其 loader 依赖体积大，`unstructured` 需要系统级库（`libmagic`、`poppler`）。可能污染主 Python AI 服务的 Docker 镜像。

**解决方案**：依赖隔离
- LangChain 依赖放在 `pyproject.toml` 的 `optional-dependencies` 中。
- 导入脚本通过 `pip install -e ".[ingest]"` 单独安装。
- 或者将导入脚本设计为独立容器（`python-ingest` 服务）。

---

### 问题 14：Cross-Encoder 模型依赖

**场景**：`sentence-transformers` 库和 Cross-Encoder 模型需要在 Python 环境中预装。模型首次加载时从 HuggingFace 下载，如果网络不可用则无法精排。

**解决方案**：降级开关
- 模型首次加载后缓存在本地，后续直接使用。
- 网络不可用时可关闭 `enable_rerank` 降级运行，退回 RRF 排序。

---

## 四、兼容性

### 问题 15：旧事故数据与新 chunk 混存的 schema 冲突

**场景**：现有 80+ 事故记录是纯文本（无 `has_code`、`entity_name` 等新字段）。新的混合 chunk 存入同一 collection 后，旧记录的 metadata 缺少这些字段。查询时如果用 `where={"has_code": True}` 过滤，旧记录全部被排除。

**解决方案**：迁移脚本 + 不做硬过滤
- 新增迁移脚本 `migrate_chroma_metadata.py`：遍历现有 collection，为每条记录补充默认值（`has_code=False, entity_name="", entity_kind="text", ast_status="legacy"`）。
- 查询时不做 `has_code` 硬过滤，旧记录仍参与召回。
- ES 旧索引数据也需迁移到新 mapping（重建索引）。

---

### 问题 16：工具调用链断裂

**场景**：当前 `rag.py` 通过 `ctx.registry.run("incident_search", ...)` 调用工具注册表。新的统一检索服务直接调用 `RagRetrievalService.retrieve()`，绕过了工具注册表，`tool_logs` 中缺少调用记录。

**解决方案**：包装为 tool_log
- `RagRetrievalService.retrieve()` 返回 `(results, status, reason)` 三元组。
- 在 `rag.py` 中将检索服务调用包装为 tool_log 记录，保持可观测性。

---

### 问题 17：前端响应格式变化

**场景**：统一检索服务返回的 chunk 结构包含 `nl_description`、`code_content`、`ast_metadata` 等新字段。但前端和报告生成节点期望的是 `snippet`、`title`、`source` 等旧字段。

**解决方案**：格式适配层
- `rag.py` 和 `business_risk_rag.py` 中做字段映射：
  - `title` ← `section_title`
  - `snippet` ← `nl_description + code_content[:200]`（截断）
  - `source` ← `source_doc`
- 新字段（`code_content`、`entity_name`）作为 `citation` 的扩展字段，前端可选消费。

---

## 五、业界对齐

### 问题 18：Chunk Size 未定义导致分块质量不一致

**场景**：调用 BFF 的 `/api/internal/chunk` 时传入 `maxChars` 和 `overlap`，但未指定具体值，分块大小可能过大或过小。

**解决方案**：配置明确值
- `bff_chunk_max_chars=1500`（约 512 token，业界混合内容最优值）。
- `bff_chunk_overlap=300`（约 20% overlap，业界标准）。
- **业界依据**：Production Hybrid RAG 项目 grid-search 确认 512 token 为混合内容 sweet spot；cAST 论文建议按非空白字符数而非行数衡量。

---

### 问题 19：无检索质量评估框架

**场景**：无法量化评估 RAG 改造前后检索质量的变化。简历中提到的"Top-5 recall 58%→82%"无法在本次改造后复现验证。

**解决方案**：评估脚本
- 新增 `eval_retrieval.py`，对手工标注的测试查询集计算 precision@5、recall@5、nDCG@5。
- 对比改造前后的指标变化（需保留改造前的基线数据）。
- **业界依据**：Production Hybrid RAG 项目内置 LLM-as-Judge 评估（faithfulness / relevance / coverage），是生产级 RAG 的标配。

---

### 问题 20：查询改写的延迟-质量 trade-off

**场景**：LLM 查询改写（HyDE / Multi-Query）可提升召回率，但增加 ~500ms 延迟，且生成质量不稳定。

**解决方案**：可选开关
- 默认关闭（`enable_query_rewrite=False`），避免增加延迟。
- 开启后生成 2-3 个变体查询，多路查询结果合并后进入 RRF 融合。
- LLM 调用失败时静默降级为原始查询。
- **业界依据**：HyDE/Multi-Query 是成熟技术，但需评估延迟-质量 trade-off 后决定是否启用。

---

## 总结：风险严重程度矩阵

| # | 问题 | 阶段 | 严重程度 | 解决方案核心 |
|---|---|---|---|---|
| 1 | NL-代码关联错误 | 导入 | 高 | 保序遍历 + 前置 NL 关联 |
| 2 | PDF 代码块边界丢失 | 导入 | 高 | 三层边界识别策略 |
| 3 | 事故代码不完整 | 导入 | 中 | 降级 + 上下文补偿 |
| 4 | AST 过度分块稀释 NL | 导入 | 高 | 导入时类级聚合 |
| 5 | 图片引用断裂 | 导入 | 中 | 保留 ImageService 调用 |
| 6 | 语言过滤过度收窄 | 检索 | 高 | Boost 而非硬过滤 |
| 7 | 实体名碰撞误召回 | 检索 | 中 | 降低 entity_name 权重 |
| 8 | 缺少精排 | 检索 | 高 | Cross-Encoder Rerank |
| 9 | embedding 语义偏移 | 检索 | 中 | NL 前置 + 长期换模型 |
| 10 | 无结果时 LLM 幻觉 | 检索 | 低 | 分数阈值兜底 |
| 11 | 导入时 BFF 未启动 | 可靠性 | 中 | 健康检查 + 统计告警 |
| 12 | ChromaDB 并发写冲突 | 可靠性 | 中 | 离线窗口执行 |
| 13 | LangChain Docker 兼容性 | 可靠性 | 中 | 依赖隔离 |
| 14 | Cross-Encoder 模型依赖 | 可靠性 | 低 | 降级开关 |
| 15 | 新旧数据 schema 冲突 | 兼容性 | 高 | 迁移脚本 + 不做硬过滤 |
| 16 | 工具调用链断裂 | 兼容性 | 低 | 包装为 tool_log |
| 17 | 前端响应格式变化 | 兼容性 | 中 | 格式适配层 |
| 18 | Chunk Size 未定义 | 业界对齐 | 中 | 配置明确值 |
| 19 | 无评估框架 | 业界对齐 | 中 | eval_retrieval.py |
| 20 | 查询改写延迟 trade-off | 业界对齐 | 低 | 可选开关 |

---

## 业界参考来源

| 来源 | 关键结论 |
|---|---|
| cAST 论文（CMU + Augment Code, 2025） | AST 结构感知分块在 Precision +1.2~3.3、Recall +1.8~4.3，优于固定大小分块 |
| Production Hybrid RAG（GitHub） | BM25 + Dense + RRF + Cross-Encoder Rerank 实测 +27% nDCG@10，精排是"最大杠杆" |
| ZeroEntropy Reranking Guide（2026） | 精排可提升检索质量达 48%、减少 LLM 幻觉 35% |
| RAG Query Transformation 实践 | HyDE/Multi-Query 是成熟技术，但需评估延迟-质量 trade-off |
