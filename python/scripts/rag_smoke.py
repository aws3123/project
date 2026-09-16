#!/usr/bin/env python
"""RAG 使用链路 smoke test：构造查询，跑完整检索（embedding→Chroma向量+ES BM25→RRF→rerank）。"""
from __future__ import annotations

import asyncio
import os
import sys

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

sys.path.insert(0, "/opt/review/python")

from config.settings import AppSettings
from repositories.db import _fetch_query_embedding
from services.rag_retrieval_service import RagRetrievalService


async def _run(query: str, settings: AppSettings) -> None:
    """单条查询完整检索链路：embedding→Chroma向量+ES BM25→RRF→rerank。"""
    svc = RagRetrievalService(settings)
    res, status, reason = await svc.retrieve(query, top_k=5)
    print(f"\n[retrieve] query={query!r}")
    print(f"  status={status} reason={reason} results={len(res)}")
    for i, r in enumerate(res, 1):
        title = r.get("title") or r.get("nl_description", "")[:50]
        print(
            f"  #{i} source={r.get('source')!r} title={title!r} "
            f"lang={r.get('language') or r.get('programming_language')} score={round(r.get('score', 0), 4)}"
        )
    print()


async def _run_all(queries: list[str], settings: AppSettings) -> None:
    for q in queries:
        v = _fetch_query_embedding(q, settings)
        print(f"[embedding] query={q!r} dim={len(v)}")
        await _run(q, settings)


def main():
    settings = AppSettings()
    print("embedding_model =", settings.embedding_model)
    print("rerank_model    =", settings.rerank_model_name)
    print("es_url          =", settings.elasticsearch_url)
    print("es_enabled      =", settings.es_enabled)
    print()

    asyncio.run(_run_all(sys.argv[1:], settings))


if __name__ == "__main__":
    main()