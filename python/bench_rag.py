#!/usr/bin/env python3
"""Benchmark per-task RAG CPU cost: model load, embedding encode, rerank predict."""
import time

Q = "Java 代码中缓存与数据库双写导致的数据一致性风险 UserService findById userRepository"
DOC = "某次线上事故：缓存与数据库双写不一致，UserService 查询旧数据导致订单状态错乱，回滚方案为缓存重建。"

# 1. embedding encode (model cached at module level after first load)
from repositories.db import _fetch_query_embedding
from config.settings import AppSettings

settings = AppSettings()
t0 = time.perf_counter()
_fetch_query_embedding(Q, settings)
t_first_embed = time.perf_counter() - t0
t0 = time.perf_counter()
_fetch_query_embedding(Q, settings)
t_embed = time.perf_counter() - t0
print(f"embedding first(load+encode)={t_first_embed*1000:.0f}ms  steady_encode={t_embed*1000:.0f}ms")

# 2. reranker load + predict
from sentence_transformers import CrossEncoder

t0 = time.perf_counter()
reranker = CrossEncoder(settings.rerank_model_name)
t_load = time.perf_counter() - t0
print(f"reranker model load={t_load*1000:.0f}ms")

pairs = [(Q, DOC + f" 实体{i}") for i in range(15)]
t0 = time.perf_counter()
scores = reranker.predict(pairs)
t_predict = time.perf_counter() - t0
print(f"rerank predict(15 pairs)={t_predict*1000:.0f}ms")

# 3. full retrieve() one-shot (models warm)
from services.rag_retrieval_service import RagRetrievalService

svc = RagRetrievalService(settings)
t0 = time.perf_counter()
res, status, reason = svc.retrieve.__wrapped__ if hasattr(svc.retrieve, "__wrapped__") else None, None, None
import asyncio

async def one():
    t0 = time.perf_counter()
    r, s, why = await svc.retrieve(Q, [{"name": "UserService", "language": "java", "signature": "findById(Long)", "kind": "class"}], top_k=5)
    dt = time.perf_counter() - t0
    print(f"full retrieve(one task)={dt*1000:.0f}ms status={s} results={len(r)}")
    return dt

asyncio.run(one())
