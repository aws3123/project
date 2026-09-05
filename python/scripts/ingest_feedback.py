"""反馈记录批量入库：把前端反馈（user_feedback 导出 JSONL）组为 unified chunk 写入 RAG。

链路：后端 GET /api/feedback/export-file 生成 JSONL → 本脚本读取 →
      按 taskId 回源代码上下文（/api/internal/review/payload/{taskId} 的 diffContent）→
      每条反馈一个 unified chunk（entity_kind="feedback"）→ ChromaDB + ES（复用现有写入）。

chunk_id 使用 feedback:{id}，upsert 幂等，重跑覆盖不重复新增。
ES 不可达时由 es_client 容错跳过，不影响 Chroma 写入。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# 把项目根目录加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from config.settings import AppSettings
from repositories.chroma import upsert_unified_chunks
from repositories.es_client import index_unified_chunks
from scripts.ingest_mixed_docs import _classify_risk_type, generate_embeddings

logger = logging.getLogger(__name__)

# 代码上下文（diff）放入 embedding 主文本的上限，防止超大向量
CODE_CONTEXT_MAX_CHARS = 3000
# 是否给 feedback chunk 携带 task_id 等关联字段（写入 doc_metadata）
EXTRA_META_KEYS = ("taskId", "sessionId", "feedbackType", "category", "source",
                   "traceId", "createdAt")


def _http_headers(settings: AppSettings) -> dict[str, str]:
    """构造调用后端内部端点的鉴权头（与 BffAstClient 一致）。"""
    headers: dict[str, str] = {}
    if settings.bff_api_key:
        headers["X-API-Key"] = settings.bff_api_key
    return headers


def _payload_url(settings: AppSettings, task_id: str) -> str:
    return f"{settings.bff_base_url.rstrip('/')}/api/internal/review/payload/{task_id}"


def _fetch_code_context(
    task_id: str, settings: AppSettings, cache: dict
) -> tuple[str, str]:
    """按 taskId 回源代码上下文（diffContent），按 taskId 缓存去重。

    返回 (code_content, status)，status ∈ ok/skipped/failed。
    """
    if not task_id:
        return "", "skipped"
    if task_id in cache:
        return cache[task_id]
    try:
        resp = httpx.get(
            _payload_url(settings, task_id),
            headers=_http_headers(settings),
            timeout=settings.bff_chunk_timeout,
        )
        if resp.status_code != 200:
            logger.warning("payload %s -> HTTP %s", task_id, resp.status_code)
            cache[task_id] = ("", "failed")
            return cache[task_id]
        diff = (resp.json().get("diffContent") or "")[:CODE_CONTEXT_MAX_CHARS]
        cache[task_id] = (diff, "ok")
        return cache[task_id]
    except Exception as exc:
        logger.warning("payload fetch failed for task %s: %s", task_id, exc)
        cache[task_id] = ("", "failed")
        return cache[task_id]


def _load_records(export_dir: str) -> list[dict]:
    """读取导出目录下所有 JSONL 文件，返回反馈记录列表。"""
    records: list[dict] = []
    for p in sorted(Path(export_dir).glob("*.jsonl")):
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("skip malformed jsonl line in %s", p)
    return records


def _build_feedback_chunks(
    records: list[dict], settings: AppSettings
) -> tuple[list[dict], dict]:
    """每条反馈组装为一个 unified chunk。

    返回 (chunks, stats)；stats 含 count/fetched/failed。
    """
    code_cache: dict = {}
    stats = {"count": len(records), "fetched": 0, "failed": 0}

    chunks: list[dict] = []
    for idx, rec in enumerate(records):
        task_id = rec.get("taskId") or ""
        code, status = _fetch_code_context(task_id, settings, code_cache)
        if status == "ok":
            stats["fetched"] += 1
        elif status == "failed":
            stats["failed"] += 1

        category = rec.get("category") or ""
        comment = rec.get("comment") or ""
        fb_type = rec.get("feedbackType") or ""
        source = rec.get("source") or ""

        # ── nl_description：类型 + 评论 + 来源 ──
        parts: list[str] = []
        if category:
            parts.append(f"[{category}]")
        if comment:
            parts.append(comment)
        if source:
            parts.append(f"(source={source})")
        nl = " ".join(parts).strip() or (category or comment or "用户反馈")

        rid = rec.get("id")
        chunk_id = f"feedback:{rid}" if rid else f"feedback:{rec.get('traceId','')}:{idx}"

        doc_meta = {
            "source_doc": "feedback",
            "section_title": "",
            "position_in_doc": 0,
            "risk_type": _classify_risk_type(nl),
            "image_urls": [],
            "image_texts": [],
        }
        for key in EXTRA_META_KEYS:
            doc_meta[key.lower()] = rec.get(key) or ""

        chunk = {
            "id": chunk_id,
            "nl_description": nl,
            "code_content": code,
            "embedding": None,  # 稍后由 generate_embeddings 生成
            "ast_metadata": {
                "entity_name": category or "",
                "entity_kind": "feedback",
                "fully_qualified_name": "",
                "language": "",
                "signature": "",
                "parent_class": None,
                "line_start": 0,
                "line_end": 0,
                "ast_status": "export",
            },
            "doc_metadata": doc_meta,
        }
        chunks.append(chunk)

    return chunks, stats


def run_ingest(export_dir: str, settings: AppSettings | None = None) -> None:
    """主入口：读取反馈 JSONL → 组 chunk → 入库。"""
    settings = settings or AppSettings()

    records = _load_records(export_dir)
    if not records:
        logger.warning("No feedback records found in %s", export_dir)
        return

    chunks, code_stats = _build_feedback_chunks(records, settings)
    logger.info("Loaded %d feedback records -> %d chunks", len(records), len(chunks))

    logger.info("Generating embeddings for %d chunks...", len(chunks))
    generate_embeddings(chunks, settings)

    logger.info("Writing %d chunks to ChromaDB...", len(chunks))
    upsert_unified_chunks(chunks, settings)

    logger.info("Writing %d chunks to Elasticsearch...", len(chunks))
    index_unified_chunks(chunks, settings)

    print("\n" + "=" * 60)
    print("Feedback Ingest Statistics")
    print("=" * 60)
    print(f"  Feedback records:   {len(records)}")
    print(f"  Chunks built:       {len(chunks)}")
    print(f"  Code ctx fetched:   {code_stats['fetched']}")
    print(f"  Code ctx failed:    {code_stats['failed']}")
    print("=" * 60)
    print("Import complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest feedback records into RAG")
    parser.add_argument(
        "--export-dir",
        default=None,
        help="反馈导出 JSONL 目录（默认取 settings.feedback_export_dir）",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="先调用后端 /api/feedback/export-file 生成 JSONL 再入库",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    settings = AppSettings()
    export_dir = args.export_dir or settings.feedback_export_dir

    if args.export:
        # 先让后端把全量反馈落盘为 JSONL
        export_url = f"{settings.bff_base_url.rstrip('/')}/api/feedback/export-file"
        try:
            resp = httpx.get(
                export_url, headers=_http_headers(settings), timeout=120.0
            )
            resp.raise_for_status()
        except Exception as exc:
            raise SystemExit(f"Backend export failed: {exc}") from exc
        path_info = resp.json()
        export_dir = str(Path(path_info["path"]).parent)
        logger.info(
            "Backend exported %s records to %s",
            path_info.get("count"),
            path_info.get("path"),
        )

    run_ingest(export_dir, settings)


if __name__ == "__main__":
    main()