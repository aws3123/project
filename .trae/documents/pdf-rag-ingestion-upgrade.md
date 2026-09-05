# PDF 混合文档切分入库 + 图片/类图理解 升级方案

## Context（背景与目标）

当前 RAG 摄入流水线（`ingest_mixed_docs.py`）只能处理「文本层」内容：
- `document_loader._load_pdf` 用 pypdf 只提取 PDF 文本层，**丢弃内嵌图片/矢量图**。
- 代码块只能识别「文本形式的代码」；**PDF 里的类图/架构图（图片/矢量）完全无法提取**，也就进不了切片和入库。
- 入库现状：ChromaDB 只有 82 条 legacy 纯文本记录；新统一切片流水线从未真正跑通（ES 未启动、无 unified chunk 字段）。

目标：让 PDF 能真正「切片入库」，并对其中的类图/图片做理解后入库，形成与现有 NL/代码块同构的 unified chunk，写入 ChromaDB + Elasticsearch。

### 已确认决策
1. **图片理解方式**：OCR 为主（Tesseract），VL（qwen-vl）为辅。
2. **入库目标**：ChromaDB + Elasticsearch 双写（ES 不可达时优雅降级，不阻塞 Chroma）。
3. **旧数据**：保留共存，不动现有 82 条 legacy 数据，增量写入新 chunk。

---

## 架构与数据流

在 `run_ingest` 中为 PDF 插入一条并行的「图块」支线，图块与现有 NL/代码块各自独立成 unified chunk，共同入库：

```
load_documents_from_dir
  ├─ pdf_processor.PdfProcessor.load_and_render()  (新增, PyMuPDF) → 页文本 + 页渲染图 + 内嵌图 bbox + 图块候选
  ├─ extract_sections(text)                        (现有) → NL/代码
  ├─ image_understanding.understand(图块)          (新增) → OCR 主, 质量不足→VL 结构化
  ├─ _aggregate_by_class                           (现有) → class/method chunk
  ├─ _build_diagram_chunks(图块)                   (新增) → entity_kind="class_diagram"/"figure", 上传 MinIO
  ├─ generate_embeddings                           (现有, 复用于图块 nl_description)
  ├─ upsert_unified_chunks                         → ChromaDB（现有, 不改）
  └─ index_unified_chunks                          → ES（内部容错, 不可达不抛错）
```

---

## 依赖与前置安装

1. **pip**：在 `d:/AIPRO/python/pyproject.toml` 的 `dependencies` 增加 `"PyMuPDF>=1.24.0"`（自带 MuPDF wheel，负责渲染页/矢量图/内嵌图提取）。`pytesseract`、`Pillow` 已在依赖中。
2. **Tesseract 二进制（前置，当前未装）**：安装 [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki)（勾选 `chi_sim` 中文语言包）。将 `tesseract.exe` 路径配置到 `tesseract_data_path`（与现有 `_run_ocr` L85 用法一致）。缺失时 OCR 返回空、走 VL 兜底，不会崩。
3. **qwen-vl**：复用现有 `llm_api_base`（DashScope compatible-mode）与 `llm_api_key`，新增 `vlm_model="qwen-vl-max"` 字段即可，无需额外开通。

---

## 新增模块

### 1. `d:/AIPRO/python/services/pdf_processor.py`（新增）
`FigureBlock` dataclass：`page_index, bbox, image_path, kind("embedded_raster"|"region_render"|"page_render"), page_text, raw_ocr_text, is_class_diagram`。

`PdfProcessor.load_and_render(pdf_path, settings) -> (pages_text: list[str], figures: list[FigureBlock])`：
- 逐页 `get_text("text")` 取文本层；`get_pixmap(Matrix(dpi/72))` 渲染整页 PNG（`pdf_render_dpi=200`）。
- `get_images(full=True)` + `get_image_rects(xref)` 取内嵌位图与 bbox；`get_drawings()` 统计矢量线/框。
- `detect_figures()` 判定图块（见下图块识别策略）。

### 2. `d:/AIPRO/python/services/image_understanding.py`（新增）
`ImageUnderstanding` dataclass：`figure, ocr_text, is_class_diagram, structured:dict, vlm_used, status`。

- `run_ocr(figure, settings)` → 复用 [ingest_incidents._run_ocr](file:///d:/AIPRO/python/scripts/ingest_incidents.py#L58-L91)，`lang="chi_sim+eng"`，失败返回空不抛错。
- `needs_vlm(ocr_text, figure) -> (trigger_vlm, is_class_diagram)`：
  - OCR 为空或 `<10` token → 触发 VL；
  - OCR 含结构关键词（`-->` `<|--` `菱形` `继承` `聚合` `1..*` `class` `类图` `ER` 等）→ 触发 VL 且判为类图；
  - OCR 量大但无结构词且无矢量框线 → 判定普通截图，仅 OCR。
- `understand_vl(figure, settings, llm_client) -> dict`：调用新增视觉接口，输出 `{diagram_type, entities:[{name,type}], relations:[{source,target,kind}], summary}` JSON；异常/超时 → `status="vlm_unavailable"`。

---

## 配置字段（`d:/AIPRO/python/config/settings.py` 新增，不改既有字段）

```python
vlm_model: str = "qwen-vl-max"           # 类图多模态模型
pdf_render_dpi: int = 200                # 整页渲染分辨率
pdf_figure_min_area: int = 6000          # 内嵌图面积阈值(px²)，小的视为装饰忽略
pdf_figure_max_pages: int = 60           # 超大 PDF 拦截，仅处理前 60 页
image_vl_fallback_enabled: bool = True   # VL 总开关，false=纯 OCR 降级
image_vlm_timeout: float = 90.0          # VL 请求超时
es_enabled: bool = True                  # ES 写入门，false=只写 Chroma
```
（Tesseract 路径复用现有 `tesseract_data_path`，不新增。）

---

## 图块识别策略

按来源三类 `FigureBlock.kind`：
1. **embedded_raster**：内嵌位图，`get_image_rects` 面积 ≥ `pdf_figure_min_area`。
2. **region_render**：在内嵌图 bbox 对应的整页渲染图上裁剪（类图核心路径，尤其矢量类图无 raster）。
3. **page_render**：该页文本层为空（扫描型）或文本稀少且 `get_drawings()` 大量矢量框（矢量图页）→ 整页当图。

`is_class_diagram` 最终裁决交给 `needs_vlm` 的结构关键词，保守判定避免误烧 VL token。图块来源始终是「渲染图」，非文本层；`FigureBlock.page_text` 只进 `doc_metadata` 作补充，不入 embedding 主文本。

---

## LLM 视觉调用（`d:/AIPRO/python/llm/client.py` 小改，向后兼容）

1. `_create_completion(messages, ..., model=None, timeout=None)`：`model = model or self._model`；`timeout` 可覆盖。
2. `chat/chat_structured` 的 `messages` 类型放宽为 `list[dict[str, Any]]`。
3. 新增：
   - `chat_vision(messages, image_paths, ...)`：读 PNG → base64 → content 里 `{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}`。
   - `chat_vision_structured(messages, image_paths, output_schema, ...)`：复用 `chat_structured` 的 JSON 解析/重试，`response_format={"type":"json_object"}`。

---

## 图块转 unified chunk（`ingest_mixed_docs.py` 新增 `_build_diagram_chunks`）

| chunk 字段 | 图块填充 |
|---|---|
| `id` | `{source_doc}:diagram:{page_index}:{seq}`（不与 `:class:`/`:method:`/`:nl-only:` 冲突）|
| `nl_description` | VL `summary`；无则 OCR 文本；再空则 `"图像，无可用描述"` |
| `code_content` | 类关系行（`A --uses--> B` 每行一条，便于 ES 类名命中）；非类图为空 |
| `embedding` | 复用 `generate_embeddings`（拼 `nl_description + code_content`）|
| `ast_metadata.entity_kind` | `"class_diagram"` 或 `"figure"`；`ast_status="vlm_ok"/"ocr_only"/"vlm_unavailable"`；`language="diagram"` |
| `doc_metadata` | `image_urls=[uploaded_url]`（复用 [image_service.upload_image](file:///d:/AIPRO/python/services/image_service.py#L21-L42)），`image_texts=[ocr_text]`，`position_in_doc=page_index` |

集成点：
- `./scripts/ingest_mixed_docs.py` `run_ingest` 中对 `format=="pdf"` 的 doc 调 `PdfProcessor.load_and_render`；`ingest_document` 末尾把 figures 经 `_build_diagram_chunks` 追加到 `all_unified`。
- 上传前用 Pillow 转 PNG/压缩避免传超大图；上传失败 → `image_urls=[]`、`status="upload_failed"`，不中断。
- 统计新增 `diagram_chunks` / `vlm_used` / `vlm_failed`。

---

## ES 优雅降级（`repositories/es_client.py` + `ingest_mixed_docs.py`）

- `run_ingest` 顺序保持：Chroma 先写（第 5 步）→ ES 后写（第 6 步），**不调换**。
- `es_client.ensure_index`：`exists/analyze/create` 外层 `try/except` 捕获连接类异常，失败 log warning 并 `return False`。
- `index_unified_chunks`：开头 `if not settings.es_enabled: return`；整体包 `try/except` 捕获连接异常并 return。
- `run_ingest` 第 6 步包 try/except：`logger.warning("ES unavailable, chunk retained in Chroma: %s", e)`，**不 sys.exit**。
- ES 恢复后重跑脚本即可补齐（upsert 幂等，`_id` 相同覆盖）。

---

## 文件改动清单

**新增**
1. `services/pdf_processor.py` — 页渲染、内嵌图、矢量图、图块候选。
2. `services/image_understanding.py` — OCR 主/VL 辅、类图结构化。

**修改**
3. `llm/client.py` — `_create_completion` 加 `model/timeout` 覆盖；messages 类型放宽；新增 `chat_vision`、`chat_vision_structured`。
4. `config/settings.py` — 上表全部字段。
5. `services/document_loader.py` — `LoadedDocument` 加 `figures` 字段；`_load_pdf` PyMuPDF 主路径带回退（pymupdf 未装时回退现有 pypdf，`figures=[]`）。扫描型 PDF 页文本为空时用整页 OCR 拼接兜底。
6. `scripts/ingest_mixed_docs.py` — 新增 `_build_diagram_chunks`；`ingest_document` 接收 figures；`run_ingest` ES 容错；统计字段。
7. `repositories/es_client.py` — `ensure_index`/`index_unified_chunks` 连接级容错 + `es_enabled`。
8. `pyproject.toml` — 加 `PyMuPDF`。

**不动**：`repositories/chroma.py`、`repositories/db.py`、`services/image_service.py`（复用）、`services/code_extractor.py`。`entity_kind` 新值直接写入现有 Chroma metadata 与 ES `entity_kind` keyword 字段，mapping 无需改。

---

## 边界情况

| 边界 | 处理 |
|---|---|
| 扫描型 PDF（无文本层） | 整页渲染为 `page_render`；`doc.text` 用整页 OCR 兜底 |
| 纯文本 PDF（无图） | `figures=[]`，纯文本→代码路径，零额外开销 |
| 混合 PDF（代码+类图） | 代码走现有提取；类图走渲染+VL，两类 chunk 并存 |
| VL 不可用/超时 | `status="vlm_unavailable"`，用 OCR 填充，`entity_kind="figure"`，仍入库 |
| OCR 完全失败 | 触发 VL；VL 也失败 → `nl_description="图像，无可用描述"`，仍建档 |
| ES 不可达 | Chroma 先写成功，ES catch 不 abort |
| 图片上传失败 | `image_urls=[]`、`status="upload_failed"`，不中断 |
| 超大 PDF/海量图 | `pdf_figure_max_pages`、`pdf_figure_min_area` 拦截 |
| Legacy 82 条共存 | `:diagram:` 前缀不冲突，upsert 只增不改 |

---

## 验证（端到端）

1. `pip install PyMuPDF`；安装 tesseract 并配置 `tesseract_data_path`；确保 MinIO、Chroma、BFF 可用。
2. 启动 ES：`docker run -d -p 9200:9200 -e discovery.type=single-node -e xpack.security.enabled=false docker.io/library/elasticsearch:8.15.0`（无 IK 自动降级 standard analyzer）。
3. 造样本：`report1.pdf` 含「中文描述 + Java 代码段 + draw.io 导出类图（含 `class`/`-->` 关系）+ 纯文本段」。
4. 运行 `python -m scripts.ingest_mixed_docs --docs-dir D:/IncidentDocs`。
5. 校验：
   - 日志出现 `diagram-chunks=N`、`vlm_used=M`；ES 关闭时显示 `ES unavailable, chunk retained in Chroma` 且脚本正常结束（不 sys.exit）。
   - Chroma 按 `entity_kind=="class_diagram"` 查询到该块；`image_urls` 为 MinIO URL、`image_texts` 为 OCR 文本；旧 82 条仍在（count 增量）。
   - ES `GET /incident_keywords/_search` 按类名命中该 chunk 的 `code_content`（关系行）；`image_urls`/`image_texts` 已写入。
   - 纯文本 PDF 不新增图块；`IMAGE_VL_FALLBACK_ENABLED=false` 跑一遍确认降级 OCR-only 且不报错。