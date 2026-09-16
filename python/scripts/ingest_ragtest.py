#!/usr/bin/env python
"""RAG 导入链路测试驱动：复用 ingest_mixed_docs 的加载/AST/嵌入/落库逻辑，
跳过 BFF 聚合 health 门禁（该门禁因 python worker 停机而 503，但 BFF AST 接口独立可用）。
"""
from __future__ import annotations

import logging
import os
import sys

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

sys.path.insert(0, "/opt/review/python")

from config.settings import AppSettings
from services.bff_ast_client import BffAstClient
from services.document_loader import load_documents_from_dir
from repositories.chroma import upsert_unified_chunks
from repositories.es_client import index_unified_chunks
from scripts.ingest_mixed_docs import (
    ingest_document,
    _build_diagram_chunks,
    generate_embeddings,
)
from llm.client import LLMClient


def main():
    docs_dir = sys.argv[1] if len(sys.argv) > 1 else "/opt/review/python/data/ragtest"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    settings = AppSettings()

    bff = BffAstClient(settings)
    docs = load_documents_from_dir(docs_dir, settings)
    print(f"[ingest-driver] loaded {len(docs)} doc(s) from {docs_dir}")

    all_chunks = []
    total_code = 0
    total_parsed = 0
    total_fallback = 0
    llm = LLMClient(settings)

    for doc in docs:
        print(f"  processing: {doc.source_file} (format={doc.format})")
        chunks, stats = ingest_document(doc, bff, settings)
        diagram, d_stats = _build_diagram_chunks(getattr(doc, "figures", []), doc.source_file, settings, llm)
        all_chunks.extend(chunks + diagram)
        total_code += stats["total_code_blocks"]
        total_parsed += stats["ast_parsed"]
        total_fallback += stats["ast_fallback"]
        for c in chunks:
            a = c.get("ast_metadata", {})
            print(f"    chunk_id={c['id']!r} entity={a.get('entity_name')!r} kind={a.get('entity_kind')} "
                  f"lang={a.get('language')} status={a.get('ast_status')}")
        print(f"    -> {len(chunks)} unified + {d_stats['count']} diagram; "
              f"code_blocks={stats['total_code_blocks']} parsed={stats['ast_parsed']} fallback={stats['ast_fallback']}")

    if not all_chunks:
        print("[ingest-driver] no chunks generated")
        return

    # ── 测试用去重：Fallback 块 id 可能重复（name='' + start_line=1），
    #    否则 Chroma upsert 抛 DuplicateIDError。生产代码需修复该聚合逻辑。──
    seen = set()
    for i, c in enumerate(all_chunks):
        cid = c["id"]
        if cid in seen:
            c["id"] = f"{cid}#{i}"
        seen.add(c["id"])
    dup = len(all_chunks) - len(seen)
    if dup:
        print(f"[ingest-driver] NOTE: deduped {dup} duplicate chunk id(s) (ingest aggregation bug)")

    print(f"\n[ingest-driver] generating embeddings for {len(all_chunks)} chunks ...")
    generate_embeddings(all_chunks, settings)

    print(f"[ingest-driver] writing {len(all_chunks)} chunks to ChromaDB ...")
    upsert_unified_chunks(all_chunks, settings)

    print(f"[ingest-driver] writing {len(all_chunks)} chunks to Elasticsearch ...")
    index_unified_chunks(all_chunks, settings)

    print("\n[ingest-driver] DONE.")
    print(f"  documents={len(docs)} chunks={len(all_chunks)} code_blocks={total_code} "
          f"ast_parsed={total_parsed} ast_fallback={total_fallback}")


if __name__ == "__main__":
    main()