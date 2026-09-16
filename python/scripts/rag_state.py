#!/usr/bin/env python
"""RAG 导入链路校验：报告 Chroma 集合计数 + 指定 source 的 chunk + ES 索引文档数。"""
from __future__ import annotations

import os
import sys

import requests

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

sys.path.insert(0, "/opt/review/python")

from config.settings import AppSettings
from repositories.chroma import get_incident_collection


def main():
    sources = sys.argv[1:] or ["csdn_java_outage.md"]
    settings = AppSettings()

    # ── ChromaDB ──
    coll = get_incident_collection(settings)
    total = coll.count()
    print(f"[Chroma] collection={settings.chroma_collection} count={total}")

    where = {"source": sources[0]} if len(sources) == 1 else {"$or": [{"source": s} for s in sources]}
    try:
        got = coll.get(where=where, include=["metadatas"])
        ids = got.get("ids", [])
        metas = got.get("metadatas", [])
        print(f"[Chroma] filter source={sources} -> hits={len(ids)}")
        for i, (iid, m) in enumerate(zip(ids, metas), 1):
            print(f"    #{i} id={iid!r} entity={m.get('entity_name')} kind={m.get('entity_kind')} lang={m.get('language')}")
    except Exception as e:
        print(f"[Chroma] filter error: {e}")

    # ── Elasticsearch ──
    idx = settings.es_index_name
    try:
        stat = requests.get(f"{settings.elasticsearch_url}/{idx}/_count", timeout=10).json()
        es_total = stat.get("count")
        print(f"[ES] index={idx} docs={es_total}")
        body = {"query": {"terms": {"source": [s for s in sources]}}}
        resp = requests.post(
            f"{settings.elasticsearch_url}/{idx}/_search",
            json={"query": {"bool": {"filter": body["query"]}}, "size": 20},
            timeout=10,
        ).json()
        hits = resp.get("hits", {}).get("hits", [])
        print(f"[ES] filter source={sources} -> hits={len(hits)}")
        for h in hits:
            src = h["_source"]
            print(f"    id={h['_id']!r} source={src.get('source')} entity={src.get('entity_name')} lang={src.get('language')}")
    except Exception as e:
        print(f"[ES] error: {e}")


if __name__ == "__main__":
    main()