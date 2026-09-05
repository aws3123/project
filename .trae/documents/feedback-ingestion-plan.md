# 前端反馈记录 → 事故文档入库 方案

## Context（背景与目标）

系统里用户对评审结果会提交「反馈」（thumbs_up/down + 分类 + 评论），后端落 MySQL `user_feedback` 表，前端记录页 `FeedbackDashboardPage` 按时间/来源分页展示。

目标：把「反馈记录」作为一批事故文档入库到 RAG，复用统一 chunk 检索体系（ChromaDB + ES），使后续评审能检索借鉴历史反馈。

### 已确认决策
1. **数据来源**：导出成文件再入库（JSONL）。
2. **入库范围**：全部反馈（正负都入）。
3. **入库格式**：unified chunk（`entity_kind="feedback"`），进 Chroma + ES。
4. **chunk 内容**：反馈文本 + 关联代码上下文（按 taskId 回源 diff）。

---

## 数据流

```
[后端] GET /api/feedback/export 分页全量 user_feedback
   ↓ 新增「导出文件」端点
D:/FeedbackExport/feedback_export_<ts>.jsonl   （每行一条反馈）
   ↓
[Python] scripts/ingest_feedback.py
   ├─ 读 JSONL
   ├─ 按 taskId 去重 → GET /api/internal/review/payload/{taskId} 取 diffContent（代码上下文，缓存去重）
   ├─ 每条反馈 → unified chunk（entity_kind="feedback"）
   ├─ generate_embeddings  (复用)
   ├─ upsert_unified_chunks → ChromaDB (复用)
   └─ index_unified_chunks → ES (复用，已容错)
```

---

## 后端改动（backend/）

1. **`application.yml` / 配置**：新增 `feedback.export-dir`（默认 `D:/FeedbackExport`）。
2. **`FeedbackService.java`** 新增 `exportAllToFile(dir)`：复用现有 `export(from,to,source,page,size)` 分页遍历全部记录，逐行写 JSONL；返回 `{path, count}`。
3. **`FeedbackController.java`** 新增 `GET /api/feedback/export-file`：调用 `exportAllToFile`，返回 `{path, count}`。

> 不改现有点分页 export（记录页仍用它）。

---

## Python 改动（python/）

1. **`config/settings.py`** 新增字段：
   ```python
   feedback_export_dir: str = "D:/FeedbackExport"
   ```

2. **新增 `scripts/ingest_feedback.py`**：
   - **CLI**：`--export-dir`（指定 JSONL 目录，默认取 settings）；可选 `--export` 时先调后端 `export-file` 端点生成文件再读。
   - `_fetch_code_context(task_id)`：复用 BFF 鉴权头（`X-API-Key` + `settings.bff_api_key`，见 [bff_ast_client.py](file:///d:/AIPRO/python/services/bff_ast_client.py#L42-L44)）调 `GET {bff_base_url}/api/internal/review/payload/{taskId}`，取 `diffContent`；**按 taskId 缓存去重**；404/失败返回空、不中断。
   - `_build_feedback_chunks(records, code_ctx_map)`：每条反馈 → unified chunk：
     | 字段 | 填充 |
     |---|---|
     | `id` | `feedback:{id}`（幂等，重跑覆盖不重复）|
     | `nl_description` | `[category] comment` + `source/feedbackType` 上下文；comment 空则用 category |
     | `code_content` | 该 taskId 的 `diffContent`，**截断到 3000 字符**防超大 embedding |
     | `ast_metadata.entity_kind` | `"feedback"`；`ast_status="export"`；`entity_name=category` |
     | `doc_metadata` | `taskId/sessionId/feedbackType/category/source/traceId/createdAt` + `risk_type=_classify_risk_type(nl)` + `image_urls=[]/image_texts=[]` |
   - 复用：`ingest_mixed_docs.generate_embeddings`、`ingest_mixed_docs._classify_risk_type`、`chroma.upsert_unified_chunks`、`es_client.index_unified_chunks`。
   - 打印统计：`count / code_ctx_fetched / code_ctx_failed`。

---

## 复用点（不改动）

- [ingest_mixed_docs.py](file:///d:/AIPRO/python/scripts/ingest_mixed_docs.py) 的 `generate_embeddings`、`_classify_risk_type`
- [chroma.py](file:///d:/AIPRO/python/repositories/chroma.py) 的 `upsert_unified_chunks`
- [es_client.py](file:///d:/AIPRO/python/repositories/es_client.py) 的 `index_unified_chunks`（已做 ES 不可达容错）
- `settings.bff_base_url` / `bff_api_key` / `bff_chunk_timeout`
- 鉴权头构造方式（[bff_ast_client.py L42-L44](file:///d:/AIPRO/python/services/bff_ast_client.py#L42-L44)）

`entity_kind="feedback"` 直接写入现有 Chroma metadata 与 ES `entity_kind` keyword，mapping 无需改（与之前 `class_diagram`/`figure` 同法）。

---

## 文件改动清单

**新增**
1. `backend/.../service/FeedbackService.java` — 新增 `exportAllToFile`（修改该类）
2. `backend/.../controller/FeedbackController.java` — 新增 `GET /api/feedback/export-file`（修改该类）
3. `backend/src/main/resources/application.yml` — `feedback.export-dir`
4. `python/config/settings.py` — `feedback_export_dir`
5. `python/scripts/ingest_feedback.py` — 新增脚本

**不动**：chroma.py、es_client.py、document_loader.py、pdf_processor.py、image_understanding.py（本次与 PDF 无关）。

---

## 边界情况

| 边界 | 处理 |
|---|---|
| 反馈无 taskId | 跳过代码回源，仅反馈文本入 chunk |
| task payload 404 / 后端未启 | code_content 空，不中断；统计 code_ctx_failed |
| 同 taskId 多条反馈 | 代码上下文按 taskId 缓存只取一次 |
| diff 超大 | code_content 截断到 3000 字符 |
| ES 不可达 | Chroma 先写成功，ES 路已容错 |
| 重跑 | `feedback:{id}` 幂等 upsert 覆盖 |
| 正负反馈混合 | 同样入库，按 feedbackType 记录 |

---

## 验证（端到端）

1. 启动后端；调用 `GET /api/feedback/export-file`，确认 `D:/FeedbackExport/` 下生成 JSONL，每行含 `id/taskId/sessionId/feedbackType/category/comment/source/traceId/createdAt`。
2. （可选起 ES）运行 `python -m scripts.ingest_feedback.py`，观察日志并确认不中断。
3. Chroma 按 `entity_kind=="feedback"` 查询命中；ES 按 comment 关键词命中；确认 `feedback:{id}` 幂等（重跑 count 不翻倍）。
4. 无 taskId 或 payload 404 的反馈降级为纯文本 chunk，正常入库。