#!/usr/bin/env python3
"""Break down the 470ms retrieve(): embed / chroma / es / rerank each."""
import asyncio
import time

from config.settings import AppSettings
from repositories.db import _fetch_query_embedding
from repositories.chroma import search_by_embedding
from repositories.es_client import search_unified

Q = "Java 代码中缓存与数据库双写导致的数据一致性风险 UserService findById userRepository"
settings = AppSettings()

async def main():
    # warm up embedding
    _fetch_query_embedding(Q, settings)
    qe = _fetch_query_embedding(Q, settings)

    t0 = time.perf_counter()
    r = await asyncio.to_thread(search_by_embedding, qe, 15, settings)
    print(f"chroma search={ (time.perf_counter()-t0)*1000:.0f}ms n={len(r)}")

    t0 = time.perf_counter()
    r2 = await asyncio.to_thread(search_unified, Q, 15, [{"name": "UserService", "language": "java", "signature": "findById(Long)", "kind": "class"}], settings)
    print(f"es bm25      ={ (time.perf_counter()-t0)*1000:.0f}ms n={len(r2)}")

asyncio.run(main())
