# RAG 分块与检索机制

---

## 一、一句话总纲

> 系统采用**混合检索**架构：ChromaDB 负责语义向量检索（cosine 相似度），Elasticsearch 负责关键词检索（BM25 分词匹配），两路结果通过 **RRF（Reciprocal Rank Fusion）** 融合排序，再由 **Cross-Encoder 重排序模型**精排，最终输出 Top-5 最相关事故。分块采用 **AST 感知的智能切分**，按类聚合方法级代码块。

---

## 二、为什么需要分块

原始事故文档是一篇完整的 Markdown 或 HTML，可能包含：

- 事故背景的自然语言描述（如 "2025年12月5日，Cloudflare 网络发生故障..."）
- Java、Python、Go 等多种语言的代码片段
- 架构图、监控截图等图片

如果整篇文档作为一个向量检索，问题很大：
1. **语义稀释**：一篇长文档可能涉及数据库、缓存、网络多个主题，query 只匹配其中一段，但整篇向量被其他内容"平均化"了
2. **精确度低**：BM25 关键词匹配需要精确命中，长文档的关键词密度低
3. **代码和自然语言混在一起**：代码检索和自然语言检索的行为不同，不能共用同一套切分策略

**所以需要分块**：把文档切成语义连贯的小块，每个块单独生成向量，检索时按块匹配。

---

## 三、分块策略

### 3.1 切分流程

```
原始文档（.md / .html / .pdf）
    │
    ▼
    code_extractor.extract_sections()
    ┌─────────────────────────────┐
    │  分离 NL 段落和 Code 块      │
    │  - NL 描述: "用户认证模块... " │
    │  - Code块1: Java (50行)     │
    │  - NL 描述: "数据库层..."    │
    │  - Code块2: Python (30行)   │
    └─────────────────────────────┘
    │
    ▼
    对每个 Code 块 → BFF AST 解析（Java 后端提供）
    ┌─────────────────────────────┐
    │  识别类、方法、签名          │
    │  - UserService.java         │
    │    ├── login()              │
    │    ├── logout()             │
    │    └── resetPassword()      │
    └─────────────────────────────┘
    │
    ▼
    _aggregate_by_class()
    ┌─────────────────────────────┐
    │  方法级 → 类级聚合          │
    │  - login + logout + reset   │
    │    → 合并为 UserService 类  │
    │  - 独立函数保持原样         │
    └─────────────────────────────┘
    │
    ▼
    Chunk 完成（含 NL + Code + 元数据）
```

### 3.2 聚合策略

> **为什么聚合？** 检索时找到"整个 UserService 类"比分别找到 `login()` 和 `logout()` 两个方法更有意义。面试官如果问"那为什么不直接全类级别的块"，回答：因为有些独立函数没有类结构（如 Python 模块级函数），对这些方法级块不聚合。

```python
# 聚合逻辑的核心
groups: dict[str | None, list[AstChunk]] = defaultdict(list)
for chunk in ast_chunks:
    groups[chunk.parent_class].append(chunk)
# → 同一个 parent_class 的多个方法合并为一个类级块
# → 没有 parent_class 的方法保持独立
```

### 3.3 纯文本降级

没有代码的纯文本文档 → 一个 `entity_kind="document"` 的块，`ast_status="no_code"`。

语言未知的代码块 → 跳过 BFF AST 解析，`ast_status="fallback"`，整块作为文本处理。

---

## 四、块结构（Chunk 的字段组成）

每个 chunk 是一个 dict，包含 5 个部分：

```python
chunk = {
    # ── 1. 唯一标识 ──
    "id": "cloudflare_outage.md:class:WAFService:42",
    # 格式: "{source_doc}:{entity_kind}:{entity_name}:{line_start}"

    # ── 2. 自然语言描述（来自文档中代码块的上文） ──
    "nl_description": "Cloudflare 的 WAF 模块在处理 HTTP body 时使用了固定128KB的缓冲区...",

    # ── 3. 代码内容（纯文本） ──
    "code_content": "public class WAFService { private int bufferSize = 131072; ... }",

    # ── 4. 嵌入向量（1536 维） ──
    "embedding": [0.0123, -0.0456, ..., 0.0789],
    # 嵌入文本 = nl_description + "\n" + code_content 拼接后生成

    # ── 5. 两层元数据 ──
    "ast_metadata": {         # 代码解析信息
        "entity_name": "WAFService",        # 实体名
        "entity_kind": "class",             # class / method / document / fallback
        "fully_qualified_name": "com.cloudflare.WAFService",
        "language": "java",                 # 编程语言
        "signature": "public class WAFService",
        "parent_class": None,               # 类级别为 null
        "line_start": 42,
        "line_end": 89,
        "ast_status": "parsed",             # parsed / fallback / no_code
    },
    "doc_metadata": {         # 文档来源信息
        "source_doc": "cloudflare_2025-12-05_outage.md",
        "section_title": "Root Cause Analysis",
        "position_in_doc": 34,
        "risk_type": "business-risk",       # 自动分类：code-vulnerability / business-risk / general
        "image_urls": ["http://minio:9000/incident-images/graph.png"],
        "image_texts": ["CPU usage spike to 98%"],
    },
}
```

嵌入文本拼接公式：

```python
embed_text = f"{chunk['nl_description']}\n{chunk['code_content']}"
```

这样向量同时包含了"这个代码是做什么的"（NL）和"代码长什么样"（Code）的信息。

---

## 五、分块的元数据有哪些

### 5.1 ChromaDB metadata（扁平化存储）

写入 ChromaDB 时，两层元数据被拍平：

| 字段 | 来源 | 类型 | 举例 |
|------|------|------|------|
| `title` | doc_meta.section_title | string | "Root Cause Analysis" |
| `source` | doc_meta.source_doc | string | "cloudflare_2025-12-05_outage.md" |
| `service` | doc_meta.service | string | "waf" |
| `tags` | doc_meta.tags | list[string] | ["cloud", "dns"] |
| `image_urls` | doc_meta.image_urls | string(JSON) | '["http://..."]' |
| `image_texts` | doc_meta.image_texts | string(JSON) | '["CPU 98%"]' |
| `has_images` | 是否有图 | bool | True |
| `nl_description` | 自然语言 | string | 同上 |
| `code_content` | 代码内容 | string | 同上 |
| `entity_name` | ast_meta.entity_name | string | "WAFService" |
| `entity_kind` | ast_meta.entity_kind | string | "class" |
| `language` | ast_meta.language | string | "java" |
| `programming_language` | ast_meta.language | string | "java" |
| `has_code` | 是否有代码 | bool | True |
| `ast_status` | ast_meta.ast_status | string | "parsed" |

### 5.2 ES mapping（关键词索引）

```json
{
  "nl_description":    {"type": "text", "analyzer": "ik_max_word"},  // 中文分词
  "code_content":      {"type": "text", "analyzer": "standard"},     // 英文/代码 token
  "title":             {"type": "text", "analyzer": "ik_max_word"},
  "section_title":     {"type": "text", "analyzer": "ik_max_word"},
  "entity_name":       {"type": "text", "analyzer": "standard",
                         "fields": {"keyword": {"type": "keyword"}}},
  "signature":         {"type": "text", "analyzer": "standard"},
  // 精确匹配（keyword 类型）
  "entity_kind":       {"type": "keyword"},
  "language":          {"type": "keyword"},
  "programming_language": {"type": "keyword"},
  "source_doc":        {"type": "keyword"},
  "risk_type":         {"type": "keyword"},
}
```

---

## 六、关键词匹配用的是哪些字段

### 6.1 完整检索流程

```python
def retrieve(nl_query, code_metadata, top_k=5):
    # 1. 向量召回（ChromaDB，top_k × 3 候选）
    vector_results = search_by_embedding(query_embedding, top_k * 3)
    #   → cosine 相似度，匹配 nl_description + code_content

    # 2. 关键词召回（ES BM25，top_k × 3 候选）
    keyword_results = search_unified(enhanced_query, top_k * 3)
    #   → 多字段分词匹配

    # 3. RRF 融合排序
    fused = rrf_fusion(vector_results, keyword_results, k=60)

    # 4. 语言增强（同语言加分 20%）
    fused = apply_language_boost(fused, code_metadata)

    # 5. Cross-Encoder 重排（top_k × 3 → top_k）
    fused = rerank(fused, query, top_k)

    # 6. 分数阈值过滤
    return fused[:top_k]
```

### 6.2 关键词匹配字段及权重

ES 的 `search_unified()` 查询体：

```json
{
  "query": {
    "bool": {
      "should": [
        // NL 匹配（权重最高）
        { "multi_match": {
            "query": "SQL注入用户认证",
            "fields": [
              "nl_description^3",     // 权重 3 — 自然语言描述
              "title^2",             // 权重 2 — 文档标题
              "section_title"        // 权重 1 — 章节标题
            ],
            "type": "best_fields"
        }},
        // 代码匹配
        { "multi_match": {
            "query": "UserService login",
            "fields": [
              "code_content^1.5",    // 权重 1.5 — 代码内容
              "signature^0.5"        // 权重 0.5 — 方法签名
            ],
            "type": "best_fields"
        }},
        // 语言增强（非硬过滤，加分）
        { "terms": { "language": ["java"], "boost": 2 }}
      ]
    }
  }
}
```

| 字段 | 权重 | 匹配目标 | 分词器 |
|------|------|---------|--------|
| `nl_description^3` | **3** | 自然语言描述的语义匹配 | ik_max_word（中文） |
| `title^2` | **2** | 事故文档标题 | ik_max_word |
| `section_title` | 1 | 文档章节标题 | ik_max_word |
| `code_content^1.5` | **1.5** | 代码内容关键词匹配 | standard（代码token） |
| `signature^0.5` | 0.5 | 方法签名 | standard |
| `language`（boost 2） | 加分 | 同语言结果加分 | keyword |

### 6.3 **向量检索**匹配的字段

向量检索不涉及字段权重，cosine 相似度直接基于 **1536 维嵌入向量**。向量由拼接文本生成：

```python
embed_text = f"{chunk['nl_description']}\n{chunk['code_content']}"
```

所以向量同时编码了自然语言含义和代码结构信息。

### 6.4 RRF 融合公式

两个召回路径的候选结果通过 RRF（Reciprocal Rank Fusion）融合：

```python
def _rrf_fusion(vector_results, keyword_results, k=60):
    scores = {}
    for rank, item in enumerate(vector_results, start=1):
        key = f"{item['title']}:{item['source']}"
        scores[key] += 1 / (k + rank)       # 向量路径排名贡献

    for rank, item in enumerate(keyword_results, start=1):
        key = f"{item['title']}:{item['source']}"
        scores[key] += 1 / (k + rank)       # 关键词路径排名贡献

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
    # → 同一份事故在两个路径中都排名靠前 → RRF 分数最高 → 排最前面
```

- 只在一个路径中排第 1：RRF 分数 = `1/(60+1)` ≈ 0.016
- 在两个路径中都排第 10：RRF 分数 = `1/(60+10) + 1/(60+10)` ≈ 0.029
- 在两个路径中都排第 1：RRF 分数 = `1/(60+1) + 1/(60+1)` ≈ 0.033

---

## 七、Cross-Encoder 重排序如何缓解英文文档排名靠后的问题

### 7.1 RRF 不跨语言，这是它的局限

RRF 只看排名，不看语义，不看语言。中文 Query 检索时：

```
向量召回路径：
  中文文档 → 排名 2  (cosine=0.85)
  英文文档 → 排名 5  (cosine=0.72) ← embedding 跨语言能力有限，排名偏低

关键词召回路径（BM25）：
  中文文档 → 排名 1  (精准命中中文 token)
  英文文档 → 排名 50+ (几乎没命中) ← BM25 token 不匹配，排名极低或未召回

RRF 融合后：
  中文文档：1/62 + 1/61 ≈ 0.033  ← 两路都靠前
  英文文档：1/65 + 1/110 ≈ 0.025 ← 关键词排名太靠后，分数被拉低
```

**RRF 在这里的局限**：它只能融合已有的排名，不能补偿关键词路径没召回的英文文档。英文文档即使语义相关度很高，在关键词路径中排名过低，RRF 分数依然被拉低。

### 7.2 Cross-Encoder 怎么解决

Cross-Encoder 把 Query 和文档**逐对拼接**输入模型，直接计算语义相关度分数：

```python
# Reranker 的输入：Query + 候选文档逐对拼接
pairs = [
    ("数据库连接池超时", "Druid connection pool exhausted due to slow queries..."),
    ("数据库连接池超时", "数据库连接池耗尽导致服务不可用..."),
    ("数据库连接池超时", "Redis cache miss rate increased to 80%..."),
]
scores = reranker.predict(pairs)
# → 返回每对的语义相关度分数，例如 [0.92, 0.95, 0.12]
```

**Cross-Encoder 为什么能跨语言**：
- 输入是 `(Query, 文档)` 对，模型同时看到 Query 和文档原文
- 经过跨语言语料（如中英平行语料）训练的模型，能理解"数据库连接池超时"和"Druid connection pool exhausted"在语义上高度相关
- 它不依赖 token 精确匹配，也不依赖向量空间的各向同性

### 7.3 具体效果

```
RRF 融合后（top_k × 3 = 15 个候选）：
─────────────────────────────────────
rank 1: "数据库连接池耗尽" (RRF=0.033)
rank 5: "Druid connection pool exhausted" (RRF=0.025)  ← 被 BM25 排名拖累
rank 8: "Redis 缓存穿透" (RRF=0.018)

Cross-Encoder 重排序后（取 top_k = 5）：
─────────────────────────────────────
rank 1: "数据库连接池耗尽" (CE=0.95)       ← 本来就是中文，语义高度匹配
rank 2: "Druid connection pool exhausted" (CE=0.92)  ← CE 判断它语义高度相关，从第5提到第2
rank 3: "Redis 缓存穿透" (CE=0.65)
rank 4: "Nginx 502 bad gateway" (CE=0.31)
rank 5: "Kubernetes pod OOM" (CE=0.22)
```

**英文文档从 RRF 的第 5 位提升到 CE 的第 2 位**，因为 Cross-Encoder 直接判断 Query 和文档的语义相关度，绕过了 BM25 token 不匹配的问题。

### 7.4 为什么不是直接用 CE 替换 RRF

| 阶段 | 做什么 | 处理的候选数 | 耗时 |
|------|--------|-------------|------|
| 向量+BM25召回 | 从几十万文档中粗筛 | ∞ → top_k×3（15个） | 毫秒级 |
| RRF 融合 | 合并两路排名 | 15 个 | 微秒级 |
| Cross-Encoder 重排 | 逐对计算语义 | 15 对 | 百毫秒级 |
| **如果 CE 直接召回** | 遍历全量文档逐对算 | 几十万对 | **不可接受** |

**RRF 负责广撒网**（不让任何一个路径的候选漏掉），**CE 负责精排**（在少量候选中做语义重排序）。RRF 不跨语言，但 CE 跨语言，两者配合完成"广撒网 + 准重排"。

### 7.5 面试话术

> 中文 Query 检索时，英文文档在关键词路径中几乎无法被召回（BM25 token 不匹配），RRF 融合后排名仍然偏低。但 Cross-Encoder 重排序阶段，因为它在语义层面直接匹配 Query 和文档原文，经过跨语言训练的模型能理解中文 Query 和英文文档在语义上是相关的，从而把英文文档从靠后的位置提升到最终 Top-5 结果中。RRF 负责"不漏"，CE 负责"跨语言"。

---

## 八、面试背诵要点表

| 面试官问 | 回答要点 |
|---------|---------|
| 分块怎么做的？ | code_extractor 分离 NL 和 Code → BFF AST 解析 → 按类聚合 |
| 为什么按类聚合？ | 检索时找到整个类比找到单个方法更有意义 |
| 没代码怎么办？ | 纯文本降级为 document 类型块，ast_status=no_code |
| 语言未知怎么办？ | 跳过 AST 解析，ast_status=fallback，整块当文本处理 |
| chunk 有哪些字段？ | id, nl_description, code_content, embedding, ast_metadata, doc_metadata |
| 嵌入向量怎么生成的？ | nl_description + code_content 拼接后输入 embedding 模型，1536 维 |
| 关键词检索用哪些字段？ | nl_description^3, title^2, section_title, code_content^1.5, signature^0.5 |
| 向量检索用哪些字段？ | 拼接后的 nl_description + code_content 的 1536 维向量 |
| 中文怎么分词？ | 优先 ik_max_word 分词器，不可用回退 standard |
| 两路检索怎么融合？ | RRF（Reciprocal Rank Fusion），k=60，两路径排名贡献相加 |
| RRF 能跨语言吗？ | 不能，RRF 只看排名不看语义。中文 Query 时英文文档在 BM25 路径排名极低，RRF 分数被拉低 |
| 那怎么弥合跨语言差距？ | Cross-Encoder 重排序。它把 Query 和文档逐对输入模型计算语义相关度，经过跨语言训练的模型能理解中文 Query 和英文文档语义相关 |
| RRF + CE 怎么分工？ | RRF 广撒网不漏召回，CE 从少量候选中做跨语言精排。一个不让漏，一个能跨语言 |
| Cross-Encoder 输入是什么？ | Query + 文档逐对拼接，直接算语义相关度分数，不依赖 token 精确匹配 |
| 怎么保证跨语言检索？ | language 字段做 should boost（+20%），不是硬过滤。真正的跨语言能力来自 CE 重排序 |
