# RAG 混合文档导入与统一检索服务设计

**Date:** 2026-07-02

## 背景

当前项目的 RAG 知识库存在两个结构性问题：

### 问题 1：事故文档不含代码

现有事故数据（`incidents.json` / `generate_incidents.py`）只有纯文本 snippet（自然语言描述），不含源代码。知识库中没有任何代码与事故的关联信息，RAG 检索只能做纯文本语义匹配。

### 问题 2：BFF 代码元数据不参与 RAG 检索

两条审查流程的 RAG 节点（`rag.py` 和 `business_risk_rag.py`）都搜索同一个纯文本事故库。BFF 的 AST 预处理结果（entities / relations / chunks）只被下游 Agent 分析节点使用，RAG 层完全不知代码的存在。

- **代码审查流程**：`rag.py` 用分类层名 + diff 文件路径拼接 NL 查询，搜事故文本 snippet。
- **业务风险审查流程**：`business_risk_rag.py` 将 BFF 检测到的 hotspot 风险标签翻译成 NL 搜索词，再搜事故文本。

### 目标状态

用户期望的 RAG 流程：

**导入阶段**：导入多格式事故文档（HTML/PDF/MD/DOCX），Python 端分离自然语言与源代码，源代码交由 Java BFF 层进行 AST 解析并返回元数据，Python 将元数据与对应自然语言描述合并后写入 ChromaDB 向量库及 Elasticsearch 索引。

**查询阶段**：前端传入的自然语言问题与源代码，源代码经 BFF AST 处理后，其结果与 NL 问题在 Python 层联合执行 RAG 检索。

**统一化**：两个审查流程的 RAG 节点统一调用同一套检索服务。

---

## 目标

1. 支持导入自然语言与源代码混合的多格式事故文档（HTML/PDF/MD/DOCX）。
2. Python 端按文档线性顺序分离 NL 与代码块，保证语义关联正确。
3. 源代码经 BFF `/api/internal/chunk` 做 AST 解析，返回结构化元数据。
4. NL 描述 + 代码内容 + AST 元数据合并为统一 chunk，存入 ChromaDB 和 ES。
5. 查询阶段，BFF 处理后的代码元数据 + NL 问题联合构建查询，执行向量 + 关键词双路召回 + RRF 融合。
6. `rag.py` 和 `business_risk_rag.py` 统一调用 `RagRetrievalService`。
7. 移除图谱召回路径。

---

## 非目标

- 不改变 BFF 的 `/api/internal/chunk` 端点接口契约（Java 端不新增代码）。
- 不改变前端 API 调用逻辑和响应格式契约。
- 不改变 LangGraph 流水线的节点编排和执行顺序。
- 不改变 Agent 分析节点（安全、性能、规则等）的逻辑。
- 不在本次引入独立向量数据库服务。
- 不在运行时做并发写入 ChromaDB（导入在离线窗口执行）。

---

## 总体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        数据导入阶段                                   │
│                                                                     │
│  多格式文档        Python 端                BFF 层            存储层    │
│  (HTML/PDF/       ┌────────────────┐      ┌──────────────┐  ┌────────┐│
│   MD/DOCX)──→     │ document_      │      │              │  │ChromaDB││
│                   │ loader.py      │──→   │ /api/internal│→ │统一     ││
│                   │ (LangChain)    │      │ /chunk       │  │collection││
│                   └───────┬────────┘      │ (已存在)     │  └────────┘│
│                           │               └──────────────┘  ┌────────┐│
│                   ┌───────▼────────┐                        │  ES    ││
│                   │ code_          │                        │统一索引 ││
│                   │ extractor.py   │                        └────────┘│
│                   │ (保序关联)      │                                  │
│                   └───────┬────────┘                                  │
│                           │                                           │
│                   ┌───────▼────────┐                                  │
│                   │ ingest_        │                                  │
│                   │ pipeline.py    │                                  │
│                   │ (类级聚合       │──→ ChromaDB + ES                │
│                   │  +合并+向量化)  │                                  │
│                   └────────────────┘                                  │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                        查询阶段                                      │
│                                                                     │
│  前端              BFF 层              Python 端                       │
│  NL问题 ─────────────────────→  ┌────────────────────┐             │
│  + 源代码 ──→  AST 预处理  ──→  │ rag_retrieval_    │             │
│             (entities/chunks)   │ service.py        │             │
│                               ┌┤                    │             │
│                          查询改写│ (可选,默认关闭)     │             │
│                          (LLM)  └┐                   │             │
│                               ││  ┌──────────┐      │             │
│                          向量召回│  关键词召回│      │             │
│                          (Chroma)│  (ES BM25)│      │             │
│                               └┘  └────┬─────┘      │             │
│                               └──RRF融合────────────┘             │
│                                       │                            │
│                                  语言 Boost                          │
│                                       │                            │
│                              Cross-Encoder Rerank                   │
│                              (top-15 → top-5)                       │
│                                       │                            │
│                                分数阈值兜底                          │
│                                       │                            │
│                                rag.py / business_risk_rag.py       │
│                                (统一调用，差异在查询构建)              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 数据导入流水线设计

### 1. 文档加载（`python/services/document_loader.py`）

使用 LangChain 的 DocumentLoaders 将多格式文档统一转为文本。

**Loader 映射**：

| 格式 | LangChain Loader | 依赖 |
|---|---|---|
| `.md` | `TextLoader` | 无额外依赖 |
| `.html` | `UnstructuredHTMLLoader` | `unstructured` |
| `.pdf` | `PyPDFLoader` | `pypdf` |
| `.docx` | `UnstructuredWordDocumentLoader` | `python-docx` |
| 其他 | 纯文本读取 | 无 |

**设计要点**：
- 未知格式按纯文本读取，不阻断导入流程。
- 转换后统一为纯文本（非 Markdown），由后续 `code_extractor` 统一处理。
- LangChain 依赖放在 `pyproject.toml` 的 `optional-dependencies` 中，不污染主 AI 服务的运行时依赖。

### 2. 代码块提取（`python/services/code_extractor.py`）

**核心逻辑：保序遍历 + 前置 NL 关联 + 启发式代码边界识别**

#### 2.1 关联规则

按文档线性顺序遍历，每遇到代码块，将其与前一个 NL 段落建立关联关系，确保语义一致性。用 Markdown 标题（`##`/`###`）或空行分隔的段落作为文档分节边界。如果一个 NL 段落后紧跟多个代码块，共享同一段 NL 描述。

#### 2.2 代码块边界识别策略

采用三层策略，逐层降级：

**Layer 1 — 结构化标记识别**（Markdown 文档优先）：
- 检测 ``` 代码块围栏语法，提取围栏内的代码内容和语言标记。
- 检测 HTML `<pre><code>` 标签。

**Layer 2 — 段落级启发式识别**（PDF/DOCX 转纯文本后）：
- 对每个文本段落做代码特征评分：
  - 行尾 `;`、`{`、`}` 出现频率高 → +2 分
  - 包含 `public`、`private`、`class`、`def`、`function`、`SELECT` 等关键字 → +1 分
  - 缩进一致（前导空格 ≥ 4）→ +1 分
  - 包含中文标点（`，`、`。`、`？`）→ -2 分
- 评分 ≥ 3 的段落判定为代码块。

**Layer 3 — 整段降级**：
- 无法确定边界的文本段，整段发 BFF，BFF 的 `fallbackChunk` 按字符数分块。
- 降级 chunk 的 metadata 中标记 `"ast_status": "boundary_unclear"`。

#### 2.3 语言检测

优先用 Markdown 围栏语言标记（如 ```java）。无标记时按代码特征推断：

| 特征 | 推断语言 |
|---|---|
| `public class` / `void ` / `@Override` | java |
| `def ` / `import ` + `:` 缩进 | python |
| `interface ` / `=> ` / `export ` | typescript |
| `SELECT ` / `CREATE TABLE ` | sql |
| 无法判断 | unknown（仍可向量化，不发 BFF） |

#### 2.4 输出结构

```python
@dataclass
class CodeBlock:
    content: str           # 代码原文（含注释）
    language: str          # java/python/typescript/sql/unknown
    position_in_doc: int   # 在文档中的位置索引（从 1 开始）
    preceding_nl: str       # 前一个 NL 段落（关联描述）
    section_title: str      # 所属章节标题
    ast_status: str         # "pending" / "parsed" / "fallback" / "boundary_unclear"
```

### 3. BFF AST 解析调用（`python/services/bff_ast_client.py`）

调用 BFF 已存在的 `/api/internal/chunk` 端点。

**接口契约**（已存在，不修改）：
- 请求：`{ sourceCode, language, filePath, maxChars, overlap }`
- 响应：`CodeChunkResult { chunks[], totalChunks, language, filePath }`
- 每个 `CodeChunk` 包含：`filePath, startLine, endLine, content, chunkType, name, fullyQualifiedName, metadata{language, signature, parentClass}`

**调用参数**：
- `maxChars` = `settings.bff_chunk_max_chars`（默认 1500，约 512 token，业界混合内容最优值）
- `overlap` = `settings.bff_chunk_overlap`（默认 300，约 20% overlap）

**降级逻辑**：
- BFF 不可用或解析异常时，返回原始代码块作为单个 fallback chunk（无元数据）。
- 降级 chunk 的 metadata 标记 `"ast_status": "fallback"`。

**健康检查**：
- 导入脚本启动时先 ping BFF（`GET /actuator/health`），不可用时直接报错退出，而非静默降级。
- 导入完成后打印统计：`AST 成功 chunk 数 / 降级 chunk 数`，降级比例 > 30% 时打印警告。

**认证**：
- 请求头携带 `X-API-Key`（值来自 `settings.bff_api_key`）。

### 4. 统一导入流水线（`python/scripts/ingest_mixed_docs.py`）

完整流程：

```
1. 加载文档（LangChain loaders → 纯文本）
2. 分离 NL 和代码块（保序关联 + 启发式边界识别）
3. 图片处理（调用现有 ImageService 做 OCR + MinIO 上传）
4. 代码块逐个发 BFF 做 AST 解析（含降级）
5. 类级聚合：同一 parentClass 的多个方法 chunk 合并为类级别 chunk
6. 合并 NL 描述 + 代码 chunk → 统一 chunk
7. 向量化（NL + 代码拼接 → embedding）
8. 写入 ChromaDB + ES
9. 打印导入统计（成功率、降级率、聚合数）
```

**步骤 5 — 类级聚合规则**：

BFF 对一段代码做 AST 解析后可能返回多个 chunk（如一个类含 15 个方法 → 15 个 chunk）。在导入时按 `parentClass` 聚合：

- 同一 `parentClass` 的所有方法 chunk 合并为**一个类级别 chunk**。
- `entity_name` = 类名（`parentClass`）
- `entity_kind` = `"class"`
- `code_content` = 该类的完整代码（按 line_start 排序拼接，去重重叠行）
- `fully_qualified_name` = 类的 FQN
- `signature` = 类的签名（如 `public class UserService`）
- `nl_description` = 共享的前置 NL 描述

聚合后，一个类只产生**一个向量**，不再挤占 top-k 名额。无 `parentClass` 的独立函数/方法 chunk 不做聚合，保持原样。

**纯文本文档处理**：无代码块的文档走原有 `seed_incidents.py` 逻辑，存入同一 collection 但 `has_code=False`。

**图片处理保留**：导入时仍调用 `ImageService` 处理文档中的图片，chunk 的 `doc_metadata` 中包含 `image_urls` 和 `image_texts`，保持与现有 schema 兼容。

---

## 统一 Chunk Schema

每个存入知识库的 chunk 包含四个核心字段：

```json
{
  "id": "sql-injection-incident:code-1:UserService",

  "nl_description": "该漏洞发生在用户输入直接拼接到SQL语句中，未使用参数化查询。",

  "code_content": "public class UserService {\n    public User findByUsername(String username) {\n        String sql = \"SELECT * FROM users WHERE username = '\" + username + \"'\";\n        return jdbcTemplate.queryForObject(sql, User.class);\n    }\n    public User findById(Long id) {\n        return userRepository.findById(id).orElse(null);\n    }\n}",

  "ast_metadata": {
    "entity_name": "UserService",
    "entity_kind": "class",
    "fully_qualified_name": "com.acme.review.UserService",
    "language": "java",
    "signature": "public class UserService",
    "parent_class": null,
    "line_start": 1,
    "line_end": 12,
    "ast_status": "parsed"
  },

  "doc_metadata": {
    "source_doc": "sql-injection-incident",
    "section_title": "SQL 注入漏洞",
    "position_in_doc": 1,
    "risk_type": "code-vulnerability",
    "image_urls": [],
    "image_texts": []
  }
}
```

**类级聚合说明**：上例中 `UserService` 类含 `findByUsername` 和 `findById` 两个方法，BFF 分别返回两个 chunk，导入时聚合为一个类级别 chunk。`entity_kind` 为 `"class"`，`code_content` 为完整类代码。独立函数（无 `parentClass`）保持方法级别，`entity_kind` 为 `"method"`。

**向量化文本**：`nl_description + "\n" + code_content` 拼接后做 embedding。

**风险类型自动标注**：`_classify_risk_type()` 通过关键词匹配标注事故类型：
- 代码漏洞关键词：`sql注入`、`xss`、`csrf`、`越权`、`漏洞`、`注入`、`跨站` → `code-vulnerability`
- 业务风险关键词：`超卖`、`资损`、`数据一致`、`事务`、`并发`、`竞态` → `business-risk`
- 均不匹配 → `general`

---

## ChromaDB 索引设计

复用现有 `incident_vectors` collection，**不新建 collection**。统一 chunk 与旧数据共存。

### 写入

```python
def upsert_unified_chunks(chunks: list[dict], settings: AppSettings) -> None:
    collection = get_incident_collection(settings)

    for chunk in chunks:
        embed_text = f"{chunk['nl_description']}\n{chunk['code_content']}"
        embedding = _fetch_query_embedding(embed_text, settings)

        metadata = {
            "title": chunk["doc_metadata"]["section_title"],
            "source": chunk["doc_metadata"]["source_doc"],
            "risk_type": chunk["doc_metadata"]["risk_type"],
            "entity_name": chunk["ast_metadata"]["entity_name"],
            "entity_kind": chunk["ast_metadata"]["entity_kind"],
            "language": chunk["ast_metadata"]["language"],
            "has_code": True,
            "ast_status": chunk["ast_metadata"]["ast_status"],
        }
        # 图片元数据（JSON 序列化，与现有逻辑一致）
        if chunk["doc_metadata"].get("image_urls"):
            metadata["image_urls"] = json.dumps(chunk["doc_metadata"]["image_urls"], ensure_ascii=False)
            metadata["has_images"] = True
        if chunk["doc_metadata"].get("image_texts"):
            metadata["image_texts"] = json.dumps(chunk["doc_metadata"]["image_texts"], ensure_ascii=False)

        collection.upsert(
            ids=[chunk["id"]],
            documents=[embed_text],
            embeddings=[embedding],
            metadatas=[metadata],
        )
```

### 查询

向量召回**不做语言硬过滤**。语言匹配作为 RRF 后排序的 boost 因子（见查询阶段设计）。

---

## Elasticsearch 索引设计

### Mapping 扩展

```json
{
  "mappings": {
    "properties": {
      "title":           { "type": "text", "analyzer": "ik_max_word" },
      "nl_description":  { "type": "text", "analyzer": "ik_max_word" },
      "code_content":    { "type": "text", "analyzer": "standard" },
      "entity_name":     { "type": "text", "analyzer": "standard", "fields": { "keyword": { "type": "keyword" }}},
      "entity_kind":     { "type": "keyword" },
      "fully_qualified_name": { "type": "keyword" },
      "language":        { "type": "keyword" },
      "signature":       { "type": "text", "analyzer": "standard" },
      "source_doc":      { "type": "keyword" },
      "section_title":   { "type": "text", "analyzer": "ik_max_word" },
      "risk_type":       { "type": "keyword" },
      "position_in_doc": { "type": "integer" },
      "ast_status":      { "type": "keyword" },
      "image_urls":      { "type": "keyword", "index": false },
      "image_texts":     { "type": "text", "index": false }
    }
  }
}
```

**关键设计**：
- `code_content` 使用 `standard` analyzer（不做中文分词），确保代码关键词可精确匹配。
- `entity_name` 索引保留但查询中不单独做匹配（避免 `save()`、`findById` 等常见名误召回）。
- `nl_description` 权重 ×3，`code_content` 权重 ×1.5（NL 语义优先）。
- 旧数据兼容：旧记录缺少新字段时，ES 自动补 `null`，不影响查询。

### 索引重建

ES mapping 变更需要重建索引。步骤：
1. 创建新索引 `incident_keywords_v2`。
2. 运行迁移脚本将旧数据导入新索引并补充默认值。
3. 切换 alias 或更新 `es_index_name` 配置。
4. 验证后删除旧索引。

---

## 查询阶段 — 统一检索服务

### 新建 `python/services/rag_retrieval_service.py`

```python
class RagRetrievalService:
    """统一 RAG 检索服务，供 rag.py 和 business_risk_rag.py 共用。"""

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self._reranker = None  # 延迟加载

    def retrieve(
        self,
        nl_query: str,
        code_metadata: list[dict] | None = None,
        top_k: int = 5,
    ) -> tuple[list[dict], str, str | None]:
        """
        联合检索：NL 问题 + 代码元数据。

        Returns:
            (results, status, reason)
            status: "NORMAL" | "DEGRADED" | "NO_RELEVANT_INCIDENTS"
        """
        # 1. 可选：查询改写（LLM 扩展，默认关闭）
        queries = self._maybe_rewrite_query(nl_query)

        # 2. 构建增强查询
        enhanced_query = self._build_enhanced_query(queries[0], code_metadata)
        query_embedding = _fetch_query_embedding(enhanced_query, self.settings)

        # 3. 向量召回（ChromaDB，不做语言硬过滤）
        vector_results = self._vector_recall(query_embedding, top_k)

        # 4. 关键词召回（ES BM25，代码全文匹配 + 语言加权）
        keyword_results = self._keyword_recall(enhanced_query, top_k, code_metadata)

        # 5. RRF 融合
        fused = self._rrf_fusion(vector_results, keyword_results, k=self.settings.rrf_k)

        # 6. 语言 boost 排序（非硬过滤）
        if code_metadata:
            fused = self._apply_language_boost(fused, code_metadata)

        # 7. Cross-Encoder 精排（top_k*3 → top_k）
        fused = self._rerank(fused, queries[0], top_k)

        # 8. 分数阈值兜底
        if not fused or all(item.get("score", 0) < self.settings.min_retrieval_score for item in fused):
            return [], "NO_RELEVANT_INCIDENTS", "所有候选分数低于阈值"

        return fused[:top_k], "NORMAL", None
```

### 查询改写（可选，默认关闭）

```python
def _maybe_rewrite_query(self, nl_query: str) -> list[str]:
    """可选的 LLM 查询改写，生成变体查询。默认关闭。"""
    if not self.settings.enable_query_rewrite:
        return [nl_query]

    try:
        prompt = f"将以下问题改写为3个不同角度的检索查询（用于事故知识库搜索），每行一个：\n{nl_query}"
        response = llm_client.chat(prompt, max_tokens=200)
        variants = [line.strip() for line in response.split("\n") if line.strip()][:3]
        return [nl_query] + variants
    except Exception:
        return [nl_query]  # 降级为原始查询
```

**设计要点**：
- 默认关闭（`enable_query_rewrite=False`），避免增加 ~500ms 延迟。
- 开启后生成 2-3 个变体查询，多路查询结果合并后进入 RRF 融合。
- LLM 调用失败时静默降级为原始查询。

### 增强查询构建

```python
def _build_enhanced_query(self, nl_query: str, code_metadata: list[dict] | None) -> str:
    """将 NL 问题与代码实体名/签名拼接为增强查询。"""
    if not code_metadata:
        return nl_query

    entity_terms = []
    for entity in code_metadata[:5]:  # 限制最多 5 个实体，避免查询过长
        if entity.get("name"):
            entity_terms.append(entity["name"])
        if entity.get("signature"):
            entity_terms.append(entity["signature"])

    return f"{nl_query} {' '.join(entity_terms)}"
```

### 向量召回（无语言硬过滤）

```python
def _vector_recall(self, embedding, top_k):
    """ChromaDB 向量召回，不做语言过滤。"""
    collection = get_incident_collection(self.settings)
    response = collection.query(
        query_embeddings=[embedding],
        n_results=top_k * 3,  # 多召回，融合后截断
        include=["documents", "metadatas", "distances"],
    )
    # 转换为统一格式...
```

**关键设计**：向量召回不设 `where` 过滤条件。语言匹配在 RRF 融合后做 boost 排序，避免漏召回跨语言的语义相关事故。

### 关键词召回（语言加权而非排除）

```python
def _keyword_recall(self, query, top_k, code_metadata):
    """ES BM25 关键词召回，语言匹配作为 should boost。"""
    should_clauses = [
        # NL 匹配（高权重）
        {"multi_match": {"query": query, "fields": ["nl_description^3", "title^2", "section_title"], "type": "best_fields"}},
        # 代码全文匹配
        {"multi_match": {"query": query, "fields": ["code_content^1.5", "signature^0.5"], "type": "best_fields"}},
    ]

    # 语言 boost（should，不排除其他语言）
    if code_metadata:
        languages = list({e.get("language") for e in code_metadata if e.get("language")})
        if languages:
            should_clauses.append({"terms": {"language": languages, "boost": 2}})

    body = {
        "size": top_k * 3,
        "query": {"bool": {"should": should_clauses}},
    }
    # 执行查询...
```

**关键设计**：
- `entity_name` 不单独做匹配（权重已降至 0），避免 `save()`、`findById` 等常见名误召回。
- 语言匹配是 `should` + `boost`，不是 `filter`，不会排除其他语言的事故。
- `code_content` 全文索引确保即使 AST 元数据不完整，ES 仍能通过代码全文匹配召回。

### 语言 Boost 排序

```python
def _apply_language_boost(self, results, code_metadata):
    """对与用户代码同语言的结果做分数 boost，但不排除其他语言。"""
    target_langs = {e.get("language") for e in code_metadata if e.get("language")}
    if not target_langs:
        return results

    for item in results:
        if item.get("language") in target_langs:
            item["score"] = item.get("score", 0) * 1.2  # 同语言 +20%

    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results
```

### Cross-Encoder 精排

```python
def _rerank(self, results, query, top_k):
    """用 Cross-Encoder 对 RRF 融合后的候选做精排。"""
    candidates = results[:top_k * 3]  # 精排 top_k*3 个候选

    if not self.settings.enable_rerank or not candidates:
        return candidates[:top_k]

    try:
        reranker = self._get_reranker()
        # 构建 query-document 对
        pairs = [(query, item.get("nl_description", "") + " " + item.get("code_content", "")) for item in candidates]
        scores = reranker.predict(pairs)

        # 用 cross-encoder 分数覆盖 RRF 分数
        for item, score in zip(candidates, scores):
            item["score"] = float(score)

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:top_k]
    except Exception as e:
        logger.warning("Reranking failed, using RRF order: %s", e)
        return candidates[:top_k]

def _get_reranker(self):
    """延迟加载 Cross-Encoder 模型。"""
    if self._reranker is None:
        from sentence_transformers import CrossEncoder
        self._reranker = CrossEncoder(self.settings.rerank_model_name)
    return self._reranker
```

**设计要点**：
- 使用 `cross-encoder/ms-marco-MiniLM-L-6-v2`（~80MB，延迟 ~200ms for 15 candidates）。
- 对 RRF 融合后的 top_k×3 个候选用 `[query, doc]` 联合编码精排，输出 top_k。
- Cross-Encoder 分数直接覆盖 RRF 分数，因为 cross-encoder 分数反映 query-doc 真实相关性。
- 模型加载失败或精排异常时，降级为 RRF 排序结果（不中断流程）。
- 可通过 `enable_rerank=False` 关闭（调试或性能压测时使用）。

---

## 审查流程统一化

### rag.py 改造

```python
def run_rag(state: GraphState, ctx: NodeContext) -> GraphState:
    settings = AppSettings()
    classification = state.get("classification", {})

    # 构建 NL 查询（保持原有逻辑）
    nl_query = " ".join(classification.get("layers", []))
    if diff := state.get("diff_analysis", {}):
        if paths := diff.get("summary", {}).get("paths", []):
            nl_query = nl_query + " " + " ".join(paths)

    # 提取 BFF 已处理的代码元数据
    code_metadata = state.get("request", {}).get("entities", [])

    # 调用统一检索服务（替换原有三路召回，移除图谱召回）
    retrieval_service = RagRetrievalService(settings)
    fused, status, reason = retrieval_service.retrieve(
        nl_query, code_metadata, top_k=settings.top_k
    )

    # 格式适配（保持 rag_context 输出结构兼容）
    rag_findings = [
        {
            "source": item.get("source", "unknown"),
            "topic": item.get("title", "unknown"),
            "snippet": item.get("nl_description", "") + "\n" + item.get("code_content", "")[:200],
            "score": item.get("score", 0),
            "image_urls": item.get("image_urls", []),
            "image_texts": item.get("image_texts", []),
            "citation": {
                "source": item.get("source", "unknown"),
                "title": item.get("title", "unknown"),
                "snippet": item.get("nl_description", ""),
                "image_urls": item.get("image_urls", []),
                "entity_name": item.get("entity_name", ""),
                "code_content": item.get("code_content", ""),
            },
        }
        for item in fused
    ]

    state["rag_context"] = rag_findings
    state["rag_status"] = status
    state.setdefault("tool_logs", []).append({
        "findings": rag_findings,
        "status": status,
        "reason": reason,
        "method": "vector+bm25+rrf",
    })

    # LLM 分析逻辑保持不变...
    return state
```

### business_risk_rag.py 改造

```python
def business_risk_rag(state: GraphState, ctx: NodeContext) -> GraphState:
    settings = AppSettings()

    # 构建 NL 查询（从 hotspot 标签翻译，保持原有逻辑）
    terms = _deduplicate(_collect_query_terms(state))
    nl_query = " ".join(terms) if terms else "业务风险 事务 并发 数据一致性 故障"

    # 提取 BFF 已处理的代码元数据
    source_package = state.get("source_package", {}) or {}
    code_metadata = []
    for file_info in source_package.get("files", []) or []:
        for method in file_info.get("methods", []) or []:
            code_metadata.append({
                "name": method.get("methodId", ""),
                "kind": "method",
                "language": "java",
                "signature": method.get("signature", ""),
            })

    # 调用统一检索服务
    retrieval_service = RagRetrievalService(settings)
    fused, status, reason = retrieval_service.retrieve(
        nl_query, code_metadata, top_k=settings.top_k
    )

    # 格式适配（同 rag.py）...
    state["rag_context"] = rag_findings
    state["rag_status"] = status
    return state
```

### 移除的内容

- `rag.py` 中的 `_graph_recall()` 函数和图谱召回逻辑。
- `rag.py` 中通过 `ctx.registry.run("incident_search", ...)` 的工具调用（改为直接调用 `RagRetrievalService`）。
- `business_risk_rag.py` 中的 `_rrf_fusion()` 重复定义（改为调用统一服务）。

---

## BFF 接口变更

**Java 端无需新增代码。** 现有 `/api/internal/chunk` 端点已满足需求。

Python 端调用时需携带认证头：
```python
headers = {"X-API-Key": settings.bff_api_key}
```

---

## 配置变更

```python
# config/settings.py 新增字段

# BFF 调用配置
bff_base_url: str = "http://localhost:8080"
bff_api_key: str = ""
bff_chunk_timeout: int = 30
bff_chunk_max_chars: int = 1500       # ~512 token, 业界混合内容最优值
bff_chunk_overlap: int = 300          # ~20% overlap

# 文档导入配置
incident_docs_input_dir: str = "D:/IncidentDocs/raw"
incident_docs_processed_dir: str = "D:/IncidentDocs/processed"

# 风险类型分类关键词
code_vulnerability_keywords: str = "sql注入,xss,csrf,越权,漏洞,注入,跨站"
business_risk_keywords: str = "超卖,资损,数据一致,事务,并发,竞态"

# 查询阶段配置
enable_rerank: bool = True             # Cross-Encoder 精排开关
rerank_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
enable_query_rewrite: bool = False     # LLM 查询改写开关（默认关闭）
min_retrieval_score: float = 0.15      # 低于此分数视为无相关结果
```

---

## 风险缓解措施

### 风险 1：PDF/DOCX 代码块边界丢失

**场景**：PyPDFLoader 转纯文本后，代码和 NL 混在一起，无法确定代码块边界。

**缓解措施**：
- 三层代码块识别策略（结构化标记 → 段落级启发式评分 → 整段降级）。
- 段落级启发式：连续多行包含 `;`、`{`、`}`、`()` 的段落判定为代码块。
- 降级时整段发 BFF，BFF 的 `fallbackChunk` 做按字符数分块。
- 降级 chunk 标记 `"ast_status": "boundary_unclear"`。
- 导入后打印每个 chunk 的 NL 和 code 摘要供人工 spot-check。

### 风险 2：事故文档中的代码本身不完整

**场景**：事故文档展示有漏洞的代码，可能省略了 import 或用 `// ...` 表示省略。

**缓解措施**：
- BFF 解析失败时降级为 fallback chunk，标记 `"ast_status": "fallback"`。
- 查询时可对 `ast_status != "parsed"` 的 chunk 降低权重（score × 0.8）。
- 对不完整代码（检测到 `// ...` 或 `/* ... */` 省略标记），在 `code_content` 中保留省略标记，向量化时上下文参与 embedding。

### 风险 3：AST 过度分块稀释 NL 语义

**场景**：一段 200 行代码被切成 15 个 chunk，15 个向量高度相似，挤占 top-k 名额。

**缓解措施**：
- **导入时类级聚合**：同一 `parentClass` 的所有方法 chunk 在导入时合并为一个类级别 chunk（类名作为 entity_name，完整类代码作为 code_content）。
- 聚合后一个类只产生一个向量，不再挤占 top-k 名额。
- 无 `parentClass` 的独立函数/方法 chunk 不做聚合，保持方法级别。
- 业界依据：cAST 论文（CMU + Augment Code, 2025）验证 AST 结构感知分块优于固定大小分块，类级聚合进一步保持语义完整性。

### 风险 4：图片引用断裂

**场景**：混合文档同时包含代码和图片，图片处理逻辑遗漏。

**缓解措施**：
- `ingest_mixed_docs.py` 在提取代码块后，仍调用现有 `ImageService` 处理文档中的图片。
- chunk 的 `doc_metadata` 中包含 `image_urls` 和 `image_texts` 字段。
- 格式适配时将 `image_urls` 和 `image_texts` 传递到 `rag_context` 输出。

### 风险 5：语言过滤过度收窄召回范围

**场景**：用户提交 Java 代码，向量查询过滤为 Java-only，漏掉 Python 的同类风险事故。

**缓解措施**：
- 向量召回**不做语言硬过滤**（不设 `where` 条件）。
- ES 关键词召回中语言匹配使用 `should` + `boost` 而非 `filter`。
- RRF 融合后做语言 boost 排序（同语言 +20%），但不排除其他语言。

### 风险 7：实体名碰撞导致误召回

**场景**：`save()`、`findById()` 等常见方法名导致 ES 误召回。

**缓解措施**：
- ES 查询中 `entity_name` 字段不单独做匹配（权重降为 0）。
- 代码匹配主要依赖 `code_content` 全文匹配（权重 ×1.5）。
- 要求代码匹配必须同时有 NL 或 `code_content` 的语义匹配（`should` 组合，最低应匹配 1 条）。

### 风险 8：embedding 模型对 NL+代码混合文本的语义偏移

**场景**：`microsoft/codebert-base` 对中文 NL 的编码能力可能不足。

**缓解措施**：
- 向量化时 NL 在前、代码在后，利用 CodeBERT 对前缀文本更敏感的特性。
- 长期评估：考虑更换为 `bge-large-zh` 或 `m3e-base` 等中英双语 embedding 模型。
- 短期不做模型更换，通过 ES 关键词召回（`ik_max_word` 分词器）补充中文 NL 的匹配能力。

### 风险 9：导入时 BFF 未启动

**场景**：执行导入脚本时 Java BFF 未启动，所有 AST 解析降级。

**缓解措施**：
- 导入脚本启动时先 ping BFF（`GET /actuator/health`），不可用时直接报错退出。
- 导入完成后打印统计：`AST 成功 chunk 数 / 降级 chunk 数`。
- 降级比例 > 30% 时打印警告，提示检查 BFF 服务状态。

### 风险 11：ChromaDB 并发写入冲突

**场景**：Python 服务运行时执行导入脚本，Chroma 嵌入式模式不支持并发写。

**缓解措施**：
- 导入脚本在离线窗口执行（停止 Python AI 服务后运行）。
- 文档中明确标注此约束。

### 风险 12：LangChain 依赖在 Docker 环境中的兼容性

**场景**：LangChain 及 loader 依赖体积大，`unstructured` 需要系统级库。

**缓解措施**：
- LangChain 依赖放在 `pyproject.toml` 的 `optional-dependencies` 中（`[project.optional-dependencies] ingest = [...]`）。
- 导入脚本通过 `pip install -e ".[ingest]"` 单独安装。
- 或者将导入脚本设计为独立容器（`python-ingest` 服务），不污染主 AI 服务镜像。

### 风险 13：旧事故数据与新 chunk 混存的 schema 冲突

**场景**：现有 80+ 事故记录缺少 `has_code`、`entity_name` 等新字段。

**缓解措施**：
- 新增迁移脚本 `python/scripts/migrate_chroma_metadata.py`：遍历现有 collection，为每条记录补充默认值：
  ```python
  defaults = {
      "has_code": False,
      "entity_name": "",
      "entity_kind": "text",
      "language": "",
      "ast_status": "legacy",
      "risk_type": "general",
  }
  ```
- 查询时不做 `has_code` 硬过滤，旧记录（`has_code=False`）仍参与召回。
- ES 旧索引数据同样需要迁移到新 mapping（重建索引）。

### 风险 14：工具调用链断裂

**场景**：统一检索服务绕过了 `incident_search` 工具注册表。

**缓解措施**：
- `RagRetrievalService.retrieve()` 返回 `(results, status, reason)` 三元组。
- 在 `rag.py` 中将检索服务调用包装为 tool_log 记录，保持可观测性。
- `IncidentSearchTool` 保留但不再被 RAG 节点调用（可供其他场景使用）。

### 风险 15：前端响应格式变化

**场景**：统一检索服务返回新字段，前端和报告节点期望旧字段。

**缓解措施**：
- `rag.py` 和 `business_risk_rag.py` 中做格式适配：
  - `title` ← `section_title`
  - `snippet` ← `nl_description + code_content[:200]`（截断）
  - `source` ← `source_doc`
  - `image_urls` / `image_texts` ← 保持传递
- 新字段（`code_content`、`entity_name`）作为 `citation` 的扩展字段，前端可选消费。

### 风险 16：缺少精排导致 top-k 质量不足（业界差距 1）

**场景**：RRF 融合只基于排名做简单合并，缺乏 query-document 交互建模，top-5 中可能混入低相关结果。

**缓解措施**：
- 在 RRF 融合 + 语言 boost 后增加 Cross-Encoder 精排阶段。
- 使用 `cross-encoder/ms-marco-MiniLM-L-6-v2`（~80MB），对 top_k×3 候选精排，输出 top_k。
- 业界依据：Production Hybrid RAG 项目实测 +27% nDCG@10；ZeroEntropy 指南显示精排可提升检索质量达 48%、减少 LLM 幻觉 35%。
- 延迟代价：~200ms（15 candidates），可接受。
- 精排失败时降级为 RRF 排序（不中断流程）。
- 可通过 `enable_rerank=False` 关闭。

### 风险 17：查询改写引入额外延迟和不确定性（业界差距 2）

**场景**：LLM 查询改写可提升召回率，但增加 ~500ms 延迟，且生成质量不稳定。

**缓解措施**：
- 默认关闭（`enable_query_rewrite=False`），仅在召回率不达标时开启评估。
- 开启后生成 2-3 个变体查询，多路查询结果合并后进入 RRF 融合。
- LLM 调用失败时静默降级为原始查询。
- 业界依据：HyDE/Multi-Query 是成熟技术，但需评估延迟-质量 trade-off 后决定是否启用。

### 风险 18：Chunk Size 未定义导致分块质量不一致（业界差距 3）

**场景**：BFF 的 `maxChars` 和 `overlap` 未指定，分块大小可能过大或过小。

**缓解措施**：
- 配置中明确 `bff_chunk_max_chars=1500`（~512 token，业界混合内容最优值）。
- 配置中明确 `bff_chunk_overlap=300`（~20% overlap，业界标准）。
- 业界依据：Production Hybrid RAG 项目 grid-search 确认 512 token 为混合内容 sweet spot；cAST 论文建议按非空白字符数而非行数衡量。

### 风险 19：无检索质量评估框架（业界差距 4）

**场景**：无法量化评估 RAG 改造前后检索质量的变化。

**缓解措施**：
- 新增 `python/scripts/eval_retrieval.py` 评估脚本。
- 对一组手工标注的测试查询计算 precision@5、recall@5、nDCG@5。
- 业界依据：Production Hybrid RAG 项目内置 LLM-as-Judge 评估（faithfulness / relevance / coverage），是生产级 RAG 的标配。

### 风险 20：无相关结果时 LLM 幻觉（业界差距 5）

**场景**：知识库中无相关事故时，所有检索结果分数都低，但 LLM 仍可能基于低质量上下文生成幻觉内容。

**缓解措施**：
- 设置 `min_retrieval_score=0.15` 分数阈值。
- 所有候选分数低于阈值时返回空 `rag_context` + 状态 `"NO_RELEVANT_INCIDENTS"`。
- 业界依据：Production Hybrid RAG 项目明确指出"if top-10 docs all miss the answer, the LLM will happily hallucinate. Always include a 'no answer found' fallback."

---

## 新增/修改文件清单

### 新增文件

| 文件 | 职责 |
|---|---|
| `python/services/document_loader.py` | 多格式文档加载，LangChain loaders 统一转文本 |
| `python/services/code_extractor.py` | 保序遍历提取代码块，三层边界识别 + 启发式语言检测 |
| `python/services/bff_ast_client.py` | HTTP 客户端调用 BFF `/api/internal/chunk`，含降级 + 健康检查 |
| `python/services/rag_retrieval_service.py` | 统一 RAG 检索服务（查询改写 + 向量 + 关键词 + RRF + 语言 boost + Cross-Encoder 精排 + 分数阈值） |
| `python/scripts/ingest_mixed_docs.py` | 完整导入流水线脚本（含类级聚合） |
| `python/scripts/migrate_chroma_metadata.py` | 旧数据 metadata 迁移脚本（补充默认值） |
| `python/scripts/eval_retrieval.py` | 检索质量评估脚本（precision@k / recall@k / nDCG@k） |

### 修改文件

| 文件 | 改动内容 |
|---|---|
| `python/config/settings.py` | 新增 BFF URL、API Key、文档目录、风险关键词、精排模型、查询改写、分数阈值、chunk size 等配置项 |
| `python/repositories/chroma.py` | 新增 `upsert_unified_chunks()`；查询时不做语言硬过滤 |
| `python/repositories/es_client.py` | 扩展 mapping（新增代码字段）；`search_documents()` 支持代码全文匹配 + 语言加权 |
| `python/repositories/keyword_index.py` | `write_keyword_index()` 支持写入代码字段 |
| `python/graph/nodes/rag.py` | 替换三路召回为调用 `RagRetrievalService`；移除图谱召回；格式适配 |
| `python/graph/nodes/business_risk_rag.py` | 替换两路召回为调用 `RagRetrievalService`；格式适配 |
| `python/pyproject.toml` | 新增 `optional-dependencies.ingest`（LangChain + loaders）；新增 `sentence-transformers` 依赖（Cross-Encoder） |

### Java 端

无需新增或修改文件。`ChunkController` 已存在且满足需求。

---

## 实施顺序

```
Task 1:  新增配置项 (settings.py)
Task 2:  实现 document_loader.py (LangChain 文档加载)
Task 3:  实现 code_extractor.py (三层边界识别 + 保序关联)
Task 4:  实现 bff_ast_client.py (BFF 调用 + 降级 + 健康检查)
Task 5:  实现 ingest_mixed_docs.py (完整导入流水线 + 类级聚合)
Task 6:  扩展 chroma.py (统一 chunk 写入 + 查询适配)
Task 7:  扩展 es_client.py (代码字段索引 + 加权查询)
Task 8:  实现 migrate_chroma_metadata.py (旧数据迁移)
Task 9:  执行旧数据迁移
Task 10: 实现 rag_retrieval_service.py (统一检索服务 + Cross-Encoder 精排)
Task 11: 改造 rag.py (调用统一服务 + 格式适配)
Task 12: 改造 business_risk_rag.py (调用统一服务 + 格式适配)
Task 13: 实现 eval_retrieval.py (检索质量评估)
Task 14: 端到端验证 + 检索质量评估
```

**并行机会**：Task 2-4 可并行开发；Task 6-7 可并行开发。

---

## 验证与测试策略

### A. 文档加载与代码提取验证

- Markdown 文档：验证 ``` 代码块正确提取，NL 关联正确。
- HTML 文档：验证 `<pre><code>` 标签内容提取。
- PDF 文档：验证段落级启发式识别代码块。
- DOCX 文档：验证代码块识别和语言检测。
- 纯文本文档：验证降级为整段处理。

### B. BFF 调用验证

- BFF 正常时：验证 AST chunk 返回正确，元数据完整。
- BFF 不可用时：验证降级为 fallback chunk，导入不中断。
- 健康检查：验证 BFF 不可用时导入脚本报错退出。
- 统计报告：验证 AST 成功率和降级率统计输出。

### C. ChromaDB 索引验证

- 统一 chunk 写入：验证 metadata 字段完整。
- 旧数据迁移：验证迁移后旧记录有默认值。
- 向量召回：验证查询结果不因语言缺失字段报错。

### D. ES 索引验证

- Mapping 重建：验证新索引 mapping 正确。
- 代码全文匹配：验证 `code_content` 字段可被搜索。
- 语言加权：验证同语言结果分数更高但未排除其他语言。

### E. 统一检索服务验证

- 纯 NL 查询（无代码）：验证退化为 NL-only 检索。
- NL + 代码元数据查询：验证增强查询构建正确。
- 精排效果：验证 Cross-Encoder 精排后 top-5 排序优于 RRF 原始排序。
- 语言 boost：验证同语言结果排序靠前。
- 分数阈值兜底：验证所有候选低于阈值时返回 `NO_RELEVANT_INCIDENTS`。
- 格式适配：验证返回值兼容旧字段（title、snippet、source）。

### F. 审查流程验证

- 代码审查流程：验证 `rag.py` 调用统一服务，输出 `rag_context` 格式兼容。
- 业务风险流程：验证 `business_risk_rag.py` 调用统一服务，输出格式兼容。
- 图谱召回移除：验证移除后流水线不报错。
- DEGRADED 传递：验证检索服务降级状态正确传递到 `rag_status`。
- NO_RELEVANT_INCIDENTS：验证无相关结果时返回空 `rag_context` + 正确状态。

### G. 精排验证

- Cross-Encoder 加载：验证模型正确加载，预测分数合理。
- 精排效果：对比开启/关闭 rerank 的 top-5 结果差异。
- 精排降级：验证模型加载失败时降级为 RRF 排序。
- 延迟测试：验证精排延迟 < 500ms（15 candidates）。

### H. 端到端验证

- 导入一个含代码的混合格式事故文档 → 验证 ChromaDB + ES 数据完整。
- 验证类级聚合：同一类的多个方法在 ChromaDB 中只存为一个类级别 chunk。
- 提交代码审查请求 → 验证 RAG 检索返回相关事故（含代码元数据）。
- 提交业务风险审查请求 → 验证 RAG 检索返回相关事故。
- 验证前端展示正常，报告生成节点正常消费 `rag_context`。

### I. 检索质量评估

- 运行 `eval_retrieval.py`，对手工标注的测试查询集计算 precision@5、recall@5、nDCG@5。
- 对比改造前后的指标变化（需保留改造前的基线数据）。
- 评估查询改写开启/关闭对 recall 的影响。

---

## 成功标准

1. 支持导入 HTML/PDF/MD/DOCX 格式的混合事故文档。
2. 代码块经 BFF AST 解析后，元数据（entity_name、kind、signature 等）存入 ChromaDB + ES。
3. NL 描述与代码块按文档线性顺序正确关联。
4. 旧数据迁移后与新 chunk 共存，查询不报错。
5. 两个审查流程统一调用 `RagRetrievalService`，输出格式兼容。
6. 向量召回不做语言硬过滤，同语言结果通过 boost 排序靠前。
7. 同一类的方法 chunk 在导入时聚合为类级别 chunk，不再挤占 top-k 名额。
8. BFF 不可用时导入脚本报错退出（而非静默降级）。
9. 图谱召回已移除，流水线不报错。
10. 前端展示和报告生成不受影响。
11. Cross-Encoder 精排对 RRF 融合结果做二次排序，精排失败时降级为 RRF 排序。
12. 无相关事故时返回空 `rag_context` + `NO_RELEVANT_INCIDENTS` 状态，避免 LLM 幻觉。
13. BFF chunk size 配置为 `maxChars=1500, overlap=300`，保持分块质量一致。
14. `eval_retrieval.py` 可计算 precision@5 / recall@5 / nDCG@5，支持改造前后对比。

---

## 风险与注意事项

### 1. 导入必须在离线窗口执行

ChromaDB 嵌入式模式不支持并发写。导入脚本执行前需停止 Python AI 服务。

### 2. ES 索引重建需要停机

Mapping 变更需要创建新索引 + 数据迁移 + 切换。建议在低峰期执行。

### 3. embedding 模型可能需要后续评估

`microsoft/codebert-base` 对中文 NL + 代码混合文本的编码效果需在真实数据上验证。如果召回质量不达标，后续考虑更换为双语模型。

### 4. LangChain 依赖需隔离

LangChain 及 loader 依赖体积大，放在 `optional-dependencies` 中，不污染主 AI 服务运行时。

### 5. 代码块边界识别无法 100% 准确

PDF/DOCX 格式转换后可能丢失代码块标记。三层策略尽量覆盖，但无法保证 100% 准确。导入后的人工校验环节是必要的补充。

### 6. Cross-Encoder 模型依赖

`sentence-transformers` 库和 `cross-encoder/ms-marco-MiniLM-L-6-v2` 模型（~80MB）需在 Python 环境中预装。模型首次加载时从 HuggingFace 下载，后续缓存在本地。如网络不可用，可关闭 `enable_rerank` 降级运行。

### 7. 类级聚合可能过度合并

某些事故文档中同一类的不同方法涉及不同风险点（如 `UserService.save()` 有 SQL 注入，`UserService.findById()` 有缓存穿透）。类级聚合后这些方法合并为一个 chunk。如果发现此类问题，可在导入脚本中增加"按方法风险标签拆分"的逻辑，或对超过 N 个方法的大类做按方法组聚合。

### 8. 业界依据参考

本设计中 AST 分块、混合检索、RRF 融合、Cross-Encoder 精排等关键决策均参考业界最佳实践：
- **cAST 论文**（CMU + Augment Code, 2025）：验证 AST 结构感知分块优于固定大小分块。
- **Production Hybrid RAG**（GitHub 高星项目）：BM25 + Dense + RRF + Cross-Encoder Rerank 的生产级实践，实测 +27% nDCG@10。
- **ZeroEntropy Reranking Guide**（2026）：Reranking 可提升检索质量达 48%，减少 LLM 幻觉 35%。
