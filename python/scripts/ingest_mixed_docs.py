#!/usr/bin/env python
"""
混合格式事故文档摄入脚本 —— 把各种格式的事故文档（HTML/PDF/MD/DOCX）处理后存入 ChromaDB + ES。

这个脚本和 ingest_incidents.py 有什么区别？
    - ingest_incidents.py: 处理简单的图片（OCR + 上传）
    - ingest_mixed_docs.py: 处理包含"自然语言 + 代码"的混合文档
      比如一份事故报告可能包含：文字描述 + Java 代码片段 + 架构图

完整流水线：
    1. 健康检查 BFF（BFF 是 Java 后端服务，提供 AST 解析能力）
    2. 加载文档（支持 HTML/PDF/Markdown/DOCX 等格式）
    3. 提取自然语言描述 + 代码块
    4. 通过 BFF 对代码块做 AST 解析（提取类、方法等结构化信息）
    5. 按类聚合（同一个类的多个方法合并成一个"类级别"的块）
    6. 生成嵌入向量
    7. 写入 ChromaDB（向量检索）+ Elasticsearch（关键词检索）
    8. 打印统计信息

使用方法：
    python -m scripts.ingest_mixed_docs [--docs-dir D:/IncidentDocs]
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict  # 带默认值的字典，访问不存在的 key 时自动创建默认值
from pathlib import Path

# 把项目根目录加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import AppSettings
from llm.client import LLMClient
from repositories.chroma import upsert_unified_chunks
from repositories.db import _fetch_query_embedding
from repositories.es_client import index_unified_chunks
from services.bff_ast_client import AstChunk, BffAstClient, BffUnavailableError
from services.code_extractor import extract_sections
from services.document_loader import LoadedDocument, load_documents_from_dir
from services.image_service import ImageService
from services.image_understanding import understand_image

logger = logging.getLogger(__name__)

# ── 风险类型分类关键词 ──
# 用于根据文本内容自动判断事故文档属于哪种风险类型
# 这些关键词会用于 RAG 检索时的风险类型过滤
_CODE_VULN_KEYWORDS = {
    "sql注入",
    "xss",
    "csrf",
    "越权",
    "漏洞",
    "注入",
    "跨站",
    "rce",
    "ssrf",
}
_BIZ_RISK_KEYWORDS = {
    "超卖",
    "资损",
    "数据一致",
    "事务",
    "并发",
    "竞态",
    "锁",
    "穿透",
    "雪崩",
}


def _classify_risk_type(text: str) -> str:
    """根据文本内容自动分类风险类型。

    分类逻辑：
        1. 如果文本包含代码安全漏洞关键词 → "code-vulnerability"（代码漏洞）
        2. 如果文本包含业务风险关键词 → "business-risk"（业务风险）
        3. 否则 → "general"（通用）

    参数:
        text: 待分类的文本

    返回:
        风险类型字符串
    """
    text_lower = text.lower()
    if any(kw in text_lower for kw in _CODE_VULN_KEYWORDS):
        return "code-vulnerability"
    if any(kw in text_lower for kw in _BIZ_RISK_KEYWORDS):
        return "business-risk"
    return "general"


def _aggregate_by_class(
    ast_chunks: list[AstChunk], preceding_nl: str, section_title: str, source_doc: str
) -> list[dict]:
    """把方法级别的代码块聚合成类级别的块。

    为什么要聚合？
        AST 解析会把每个方法作为一个独立的块。
        但检索时，我们更希望找到"整个类"而不是"某个方法"。
        比如搜索"用户认证逻辑"，返回 UserService 类（包含所有方法）
        比返回 UserService.authenticate() 单个方法更有用。

    聚合规则：
        - 同一个 parent_class 的多个方法 → 合并成一个类级别的块
        - 没有 parent_class 的独立函数 → 保持原样

    参数:
        ast_chunks: AST 解析后的方法级代码块列表
        preceding_nl: 代码块前面的自然语言描述
        section_title: 所在章节标题
        source_doc: 来源文档名

    返回:
        统一格式的块字典列表
    """
    # 按 parent_class 分组
    # defaultdict(list) 的妙用：访问不存在的 key 时自动创建空列表
    groups: dict[str | None, list[AstChunk]] = defaultdict(list)
    for chunk in ast_chunks:
        groups[chunk.parent_class].append(chunk)

    unified_chunks: list[dict] = []

    for parent_class, chunks in groups.items():
        if parent_class and len(chunks) > 1:
            # ── 类级别聚合 ──
            # 多个方法属于同一个类 → 合并成一个块

            # 按行号排序，保持代码的原始顺序
            chunks.sort(key=lambda c: c.start_line)

            # 合并代码内容（去重重叠的行）
            merged_lines: list[str] = []
            seen_lines: set[str] = set()  # 用集合去重
            for c in chunks:
                for line in c.content.split("\n"):
                    # 如果这行没见过，或者是空行（保留空行维持格式）
                    if line not in seen_lines or not line.strip():
                        merged_lines.append(line)
                        seen_lines.add(line)

            merged_code = "\n".join(merged_lines)

            # 使用第一个块的信息作为类的代表
            first = chunks[0]
            entity_name = parent_class
            entity_kind = "class"
            language = first.language
            # 全限定名（FQN）：如 "com.acme.UserService"
            # 取类名部分（去掉最后的方法名）
            fqn = (
                first.fully_qualified_name.rsplit(".", 1)[0]
                if "." in first.fully_qualified_name
                else parent_class
            )
            signature = f"public class {parent_class}"

            chunk_id = f"{source_doc}:class:{parent_class}"

            unified_chunks.append(
                {
                    "id": chunk_id,
                    "nl_description": preceding_nl,  # 自然语言描述
                    "code_content": merged_code,  # 合并后的代码
                    "embedding": None,  # 稍后生成
                    "ast_metadata": {
                        "entity_name": entity_name,
                        "entity_kind": entity_kind,
                        "fully_qualified_name": fqn,
                        "language": language,
                        "signature": signature,
                        "parent_class": None,  # 类级别没有父类
                        "line_start": chunks[0].start_line,
                        "line_end": chunks[-1].end_line,
                        "ast_status": "parsed",  # 已成功解析
                    },
                    "doc_metadata": {
                        "source_doc": source_doc,
                        "section_title": section_title,
                        "position_in_doc": chunks[0].start_line,
                        # 自动分类风险类型（根据 NL 描述 + 代码前200字符）
                        "risk_type": _classify_risk_type(
                            preceding_nl + " " + merged_code[:200]
                        ),
                        "image_urls": [],
                        "image_texts": [],
                    },
                }
            )
        else:
            # ── 方法/函数级别 ──
            # 没有父类，或者只有一个方法 → 保持原样
            for chunk in chunks:
                chunk_id = f"{source_doc}:method:{chunk.name}:{chunk.start_line}"

                unified_chunks.append(
                    {
                        "id": chunk_id,
                        "nl_description": preceding_nl,
                        "code_content": chunk.content,
                        "embedding": None,
                        "ast_metadata": {
                            "entity_name": chunk.name or "anonymous",
                            "entity_kind": chunk.chunk_type or "method",
                            "fully_qualified_name": chunk.fully_qualified_name,
                            "language": chunk.language,
                            "signature": chunk.signature,
                            "parent_class": chunk.parent_class,
                            "line_start": chunk.start_line,
                            "line_end": chunk.end_line,
                            "ast_status": chunk.ast_status,
                        },
                        "doc_metadata": {
                            "source_doc": source_doc,
                            "section_title": section_title,
                            "position_in_doc": chunk.start_line,
                            "risk_type": _classify_risk_type(
                                preceding_nl + " " + chunk.content[:200]
                            ),
                            "image_urls": [],
                            "image_texts": [],
                        },
                    }
                )

    return unified_chunks


def ingest_document(
    doc: LoadedDocument,
    bff_client: BffAstClient,
    settings: AppSettings,
) -> tuple[list[dict], dict[str, int]]:
    """处理单个文档，生成统一格式的代码块。

    流程：
        1. 用 code_extractor 分离文档中的自然语言和代码块
        2. 如果没有代码 → 创建一个纯文本块
        3. 如果有代码 → 通过 BFF 做 AST 解析 → 按类聚合
        4. 对于无法识别语言的代码 → 跳过 BFF，直接用回退方案

    参数:
        doc: 已加载的文档对象（包含文本内容和元信息）
        bff_client: BFF AST 解析客户端
        settings: 应用配置

    返回:
        (chunks, stats) 元组：
        - chunks: 统一格式的代码块列表
        - stats: 处理统计（解析数、回退数、边界不清数等）
    """
    # extract_sections 把文档分成：自然语言部分 + 代码块部分
    sections, code_blocks = extract_sections(doc.text)

    stats = {
        "ast_parsed": 0,  # AST 成功解析的块数
        "ast_fallback": 0,  # AST 回退（解析失败）的块数
        "ast_boundary_unclear": 0,  # 代码边界不清的块数
        "total_code_blocks": len(code_blocks),  # 总代码块数
    }

    if not code_blocks:
        # ── 纯文本文档（没有代码）──
        # 创建一个纯自然语言块
        nl_text = doc.text[:2000]  # 截断超长文本
        chunk = {
            "id": f"{doc.source_file}:nl-only",
            "nl_description": nl_text,
            "code_content": "",
            "embedding": None,
            "ast_metadata": {
                "entity_name": "",
                "entity_kind": "document",  # 类型标记为"文档"
                "fully_qualified_name": "",
                "language": "unknown",
                "signature": "",
                "parent_class": None,
                "line_start": 0,
                "line_end": 0,
                "ast_status": "no_code",  # 没有代码
            },
            "doc_metadata": {
                "source_doc": doc.source_file,
                "section_title": "",
                "position_in_doc": 0,
                "risk_type": _classify_risk_type(nl_text),
                "image_urls": [],
                "image_texts": [],
            },
        }
        return [chunk], stats

    # ── 有代码块的文档 ──
    all_unified: list[dict] = []

    for cb in code_blocks:
        if cb.language == "unknown":
            # 语言未知 → 跳过 BFF，直接用回退方案
            # 把整个代码块当作一个"fallback"块
            ast_chunks = [
                AstChunk(
                    content=cb.content,
                    language="unknown",
                    file_path=doc.source_file,
                    start_line=1,
                    end_line=cb.content.count("\n") + 1,
                    chunk_type="fallback",
                    name="",
                    fully_qualified_name="",
                    signature="",
                    parent_class=None,
                    ast_status="fallback",
                )
            ]
            stats["ast_fallback"] += 1
        else:
            # 语言已知 → 调用 BFF 做 AST 解析
            # parse_code_with_fallback: 如果 BFF 解析失败，自动回退到整块
            ast_chunks = bff_client.parse_code_with_fallback(
                code_text=cb.content,
                language=cb.language,
                file_path=doc.source_file,
            )

            # 统计各状态的数量
            for ac in ast_chunks:
                if ac.ast_status == "parsed":
                    stats["ast_parsed"] += 1
                elif ac.ast_status == "fallback":
                    stats["ast_fallback"] += 1
                elif ac.ast_status == "boundary_unclear":
                    stats["ast_boundary_unclear"] += 1

                # 如果 code_extractor 标记了边界不清，覆盖 AST 状态
                if cb.ast_status == "boundary_unclear":
                    ac.ast_status = "boundary_unclear"

        # 按类聚合方法级别的块
        unified = _aggregate_by_class(
            ast_chunks=ast_chunks,
            preceding_nl=cb.preceding_nl,
            section_title=cb.section_title,
            source_doc=doc.source_file,
        )
        all_unified.extend(unified)

    return all_unified, stats


def _build_diagram_chunks(
    figures: list,
    source_doc: str,
    settings: AppSettings,
    llm_client: LLMClient,
) -> tuple[list[dict], dict]:
    """把 PDF 图块（类图/架构图/截图）转成 unified chunk。

    每个图块经过「OCR 主 + VL 辅」理解，伪文本化为一个自然语言描述的 chunk，
    与现有 NL/代码 chunk 同构，一并入库。图片上传到 MinIO（失败不中断）。

    返回 (chunks, stats)；stats 含 count / vlm_used / vlm_failed。
    """
    chunks: list[dict] = []
    stats = {"count": 0, "vlm_used": 0, "vlm_failed": 0}

    if not figures:
        return chunks, stats

    try:
        image_service = ImageService(settings)
    except Exception:
        image_service = None

    for seq, fig in enumerate(figures):
        try:
            result = understand_image(fig, settings, llm_client)
        except Exception as exc:
            logger.warning("Image understanding failed for %s: %s", fig.image_path, exc)
            continue

        # ── 语义描述：VL summary 优先，OCR 文本兜底 ──
        summary = (
            result.structured.get("summary", "") if result.structured else ""
        )
        nl = summary or result.ocr_text or "图像，无可用描述"

        # ── 伪代码化：类关系行，便于 ES 按类名命中 ──
        relations = (
            result.structured.get("relations", []) if result.structured else []
        )
        code_lines = [
            f"{r.get('source', '')} --{r.get('kind', 'rel')}--> {r.get('target', '')}"
            for r in relations
            if r.get("source") or r.get("target")
        ]
        code_content = "\n".join(code_lines)

        # ── 上传到 MinIO（失败不中断）──
        image_urls: list[str] = []
        if image_service is not None:
            try:
                url = image_service.upload_image(fig.image_path, source_doc)
                image_urls = [url]
            except Exception as exc:
                logger.warning(
                    "Image upload failed for %s (will index without URL): %s",
                    fig.image_path,
                    exc,
                )

        entity_kind = "class_diagram" if result.is_class_diagram else "figure"

        chunk = {
            "id": f"{source_doc}:diagram:{fig.page_index}:{seq}",
            "nl_description": nl,
            "code_content": code_content,
            "embedding": None,  # 稍后由 generate_embeddings 生成
            "ast_metadata": {
                "entity_name": "",
                "entity_kind": entity_kind,
                "fully_qualified_name": "",
                "language": "diagram",
                "signature": "",
                "parent_class": None,
                "line_start": 0,
                "line_end": 0,
                "ast_status": result.status,
            },
            "doc_metadata": {
                "source_doc": source_doc,
                "section_title": "",
                "position_in_doc": fig.page_index,
                "risk_type": _classify_risk_type(nl),
                "image_urls": image_urls,
                "image_texts": [result.ocr_text] if result.ocr_text else [],
            },
        }
        chunks.append(chunk)

        stats["count"] += 1
        if result.vlm_used:
            stats["vlm_used"] += 1
        if result.status in ("vlm_failed", "vlm_unavailable"):
            stats["vlm_failed"] += 1

    return chunks, stats


def generate_embeddings(chunks: list[dict], settings: AppSettings) -> None:
    """为所有代码块生成嵌入向量（原地修改 chunks 列表中的字典）。

    嵌入文本 = 自然语言描述 + 代码内容
    这样向量同时包含了"这段代码做什么"和"代码长什么样"的信息。

    参数:
        chunks: 代码块列表（每个元素的 "embedding" 字段会被原地更新）
        settings: 应用配置
    """
    for chunk in chunks:
        # 拼接 NL 描述和代码内容作为嵌入输入
        embed_text = f"{chunk['nl_description']}\n{chunk['code_content']}"
        if not embed_text.strip():
            # 如果拼接后为空，至少用 NL 描述
            embed_text = chunk["nl_description"] or "empty"
        # 调用嵌入模型，把文本转成 1536 维向量
        chunk["embedding"] = _fetch_query_embedding(embed_text, settings)


def run_ingest(docs_dir: str, settings: AppSettings | None = None) -> None:
    """主摄入入口：执行完整的文档摄入流水线。

    参数:
        docs_dir: 事故文档目录路径
        settings: 应用配置（可选）
    """
    settings = settings or AppSettings()

    # ── 第 1 步：健康检查 BFF ──
    # BFF（Backend For Frontend）是 Java 后端，提供 AST 解析能力
    # 如果 BFF 不可用，AST 解析无法进行，直接退出
    bff_client = BffAstClient(settings)
    try:
        bff_client.health_check()
    except BffUnavailableError as e:
        logger.error("BFF health check failed: %s", e)
        logger.error("Aborting import — BFF must be available for AST parsing.")
        sys.exit(1)

    # ── 第 2 步：加载文档 ──
    # load_documents_from_dir 支持多种格式：HTML, PDF, Markdown, DOCX 等
    documents = load_documents_from_dir(docs_dir, settings)
    if not documents:
        logger.warning("No documents found in %s", docs_dir)
        return

    # ── 第 3 步：逐个处理文档 ──
    all_chunks: list[dict] = []
    # 累计统计
    total_stats = {
        "ast_parsed": 0,
        "ast_fallback": 0,
        "ast_boundary_unclear": 0,
        "total_code_blocks": 0,
    }
    total_class_chunks = 0
    total_diagram_chunks = 0
    total_vlm_used = 0
    total_vlm_failed = 0

    # LLM 客户端（供图块 VL 理解复用）
    llm_client = LLMClient(settings)

    for doc in documents:
        logger.info("Processing: %s (format=%s)", doc.source_file, doc.format)
        chunks, stats = ingest_document(doc, bff_client, settings)

        # PDF 图块：OCR 主 + VL 辅，伪文本化为图块 chunk（非 PDF 为空列表，零开销）
        diagram_chunks, d_stats = _build_diagram_chunks(
            getattr(doc, "figures", []), doc.source_file, settings, llm_client
        )

        all_chunks.extend(chunks)
        all_chunks.extend(diagram_chunks)

        # 累加统计
        for k in total_stats:
            total_stats[k] += stats[k]

        # 统计类级别的块数
        class_chunks = sum(
            1 for c in chunks if c.get("ast_metadata", {}).get("entity_kind") == "class"
        )
        total_class_chunks += class_chunks
        total_diagram_chunks += d_stats["count"]
        total_vlm_used += d_stats["vlm_used"]
        total_vlm_failed += d_stats["vlm_failed"]

        logger.info(
            "  %s: %d chunks (%d class-level, %d code blocks, %d parsed, %d fallback, %d diagram)",
            doc.source_file,
            len(chunks),
            class_chunks,
            stats["total_code_blocks"],
            stats["ast_parsed"],
            stats["ast_fallback"],
            d_stats["count"],
        )

    if not all_chunks:
        logger.warning("No chunks generated from any document.")
        return

    # ── 第 4 步：生成嵌入向量 ──
    logger.info("Generating embeddings for %d chunks...", len(all_chunks))
    generate_embeddings(all_chunks, settings)

    # ── 第 5 步：写入 ChromaDB ──
    logger.info("Writing %d chunks to ChromaDB...", len(all_chunks))
    upsert_unified_chunks(all_chunks, settings)

    # ── 第 6 步：写入 Elasticsearch ──
    logger.info("Writing %d chunks to Elasticsearch...", len(all_chunks))
    index_unified_chunks(all_chunks, settings)

    # ── 第 7 步：打印统计信息 ──
    total_ast = total_stats["total_code_blocks"]
    # 计算回退率（AST 解析失败的比例）
    fallback_rate = (
        (total_stats["ast_fallback"] / total_ast * 100) if total_ast > 0 else 0
    )

    print("\n" + "=" * 60)
    print("Import Statistics")
    print("=" * 60)
    print(f"  Documents processed:   {len(documents)}")
    print(f"  Total chunks:          {len(all_chunks)}")
    print(f"  Class-level chunks:    {total_class_chunks}")
    print(f"  Diagram chunks:        {total_diagram_chunks}")
    print(f"  Diagram VL used:       {total_vlm_used}")
    print(f"  Diagram VL failed:     {total_vlm_failed}")
    print(f"  Code blocks processed: {total_ast}")
    print(f"  AST parsed:            {total_stats['ast_parsed']}")
    print(f"  AST fallback:          {total_stats['ast_fallback']}")
    print(f"  Boundary unclear:      {total_stats['ast_boundary_unclear']}")
    print(f"  Fallback rate:         {fallback_rate:.1f}%")

    # 如果回退率超过 30%，给出警告
    if fallback_rate > 30:
        print("\n  [WARNING] Fallback rate > 30% — check BFF AST parsing quality.")

    # 打印前 10 个块的摘要（用于人工抽查质量）
    print("\n" + "-" * 60)
    print("Chunk Summaries (first 10):")
    print("-" * 60)
    for i, chunk in enumerate(all_chunks[:10]):
        ast = chunk.get("ast_metadata", {})
        doc = chunk.get("doc_metadata", {})
        # 截取前 80/60 个字符作为预览
        nl_preview = chunk["nl_description"][:80].replace("\n", " ")
        code_preview = (
            chunk["code_content"][:60].replace("\n", " ")
            if chunk["code_content"]
            else "(no code)"
        )
        print(f"  [{i+1}] {chunk['id']}")
        print(f"      NL:   {nl_preview}...")
        print(f"      Code: {code_preview}...")
        print(
            f"      Entity: {ast.get('entity_name', '?')} ({ast.get('entity_kind', '?')})"
        )
        print(
            f"      Lang: {ast.get('language', '?')} | Status: {ast.get('ast_status', '?')}"
        )
        print(f"      Risk: {doc.get('risk_type', '?')}")
        print()

    print("=" * 60)
    print("Import complete.")
    print("=" * 60)


def main():
    """脚本入口：解析参数，执行摄入。"""
    parser = argparse.ArgumentParser(
        description="Ingest mixed-format incident documents"
    )
    parser.add_argument(
        "--docs-dir", default=None, help="Directory containing incident documents"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    settings = AppSettings()
    # 如果命令行没指定目录，从配置中读取默认值
    docs_dir = args.docs_dir or settings.incident_docs_dir
    run_ingest(docs_dir, settings)


if __name__ == "__main__":
    main()
