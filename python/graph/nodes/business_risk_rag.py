"""业务风险 RAG 检索节点 —— 从历史事故库中检索与业务风险相关的案例。

本模块负责在业务风险分析流水线中执行 RAG（检索增强生成）：
1. 从检测到的风险模式中收集查询词
2. 调用统一检索服务，从历史事故知识库中检索相关案例
3. 将检索结果格式化供后续节点使用

RAG 是什么？
  RAG = Retrieval-Augmented Generation（检索增强生成）
  简单说就是：先"查资料"（检索），再"回答问题"（生成）
  类比：考试时允许翻书——先从书中找到相关内容，再结合书本内容答题

为什么需要历史事故关联？
  如果本次代码变更与过去出过的事故类似，就能提前预警
  比如：历史上"缓存和数据库双写"导致过数据不一致，
  那这次如果也有类似模式，就应该提醒开发者注意
"""
from __future__ import annotations

import logging

from config.settings import AppSettings
from graph.state import GraphState, NodeContext
from services.rag_retrieval_service import RagRetrievalService

logger = logging.getLogger(__name__)

# 风险标签 → 检索查询词映射
# 将 Java 端标记的风险标签转换为中文检索词，用于在知识库中搜索相关事故
_RISK_TAG_QUERY_MAP: dict[str, str] = {
    "EXTERNAL_CALL_INSIDE_TRANSACTION": "事务内调用远程服务 分布式事务不一致",
    "CHECK_THEN_ACT_CANDIDATE": "先查后写 竞态条件 并发数据不一致",
    "CACHE_DB_DUAL_WRITE": "缓存数据库双写不一致 缓存穿透 缓存雪崩",
    "LOCKING_PRESENT": "锁竞争 死锁 锁等待 并发控制",
    "MQ_INSIDE_TRANSACTION": "消息队列事务一致性 发消息失败 回滚",
    "TRANSACTIONAL": "事务边界 事务传播 事务超时",
    "SYNCHRONIZED_METHOD": "同步方法 锁竞争 性能瓶颈",
    "SYNCHRONIZED_BLOCK": "同步块 锁竞争 死锁",
    "EXPLICIT_LOCK": "显式锁 锁竞争 死锁",
    "DB_LOCK": "数据库锁 行锁 表锁 间隙锁 死锁",
}


def _collect_query_terms(state: GraphState) -> list[str]:
    """从业务风险热点和语义发现中收集检索词。

    从三个来源收集查询词：
    1. 源码包中的热点风险标签（riskTags）→ 映射为中文检索词
    2. 方法问题（deep_read_methods 的产出）→ 用 reason 作为检索词
    3. 语义发现（semantic_hotspot_scan 的产出）→ 用 category 和 reason

    参数:
        state: 共享状态

    返回:
        检索词列表（可能包含重复，后续会去重）
    """
    terms: list[str] = []
    seen_tags: set[str] = set()

    # 来源1：源码包中的热点风险标签
    source_package = state.get("source_package", {}) or {}
    for file in source_package.get("files", []) or []:
        if not isinstance(file, dict):
            continue
        for hotspot in file.get("hotspots", []) or []:
            if not isinstance(hotspot, dict):
                continue
            for tag in hotspot.get("riskTags", []) or []:
                if isinstance(tag, str) and tag not in seen_tags:
                    seen_tags.add(tag)
                    # 将风险标签映射为中文检索词
                    mapped = _RISK_TAG_QUERY_MAP.get(tag, tag.lower().replace("_", " "))
                    terms.append(mapped)

    # 来源2：方法问题（deep_read_methods 的产出）
    method_issues = state.get("method_issues", {}) or {}
    for issue in method_issues.get("issues", []) or []:
        if isinstance(issue, dict) and issue.get("reason"):
            terms.append(issue["reason"])

    # 来源3：语义发现（semantic_hotspot_scan 的产出）
    semantic_findings = state.get("semantic_findings", {}) or {}
    for item in semantic_findings.get("items", []) or []:
        if isinstance(item, dict):
            if item.get("category"):
                terms.append(item["category"])
            if item.get("reason"):
                terms.append(item["reason"])

    return terms


def _deduplicate(seq: list[str]) -> list[str]:
    """去除列表中的重复项，保持原始顺序。"""
    seen: set[str] = set()
    return [x for x in seq if not (x in seen or seen.add(x))]


def _build_code_metadata(state: GraphState) -> list[dict]:
    """从源码包中提取代码元数据（用于增强检索精度）。

    提取 Java 方法的名称、类型、语言、签名，作为检索的辅助信息。
    """
    source_package = state.get("source_package", {}) or {}
    code_metadata: list[dict] = []

    for file_info in source_package.get("files", []) or []:
        if not isinstance(file_info, dict):
            continue
        for method in file_info.get("methods", []) or []:
            if not isinstance(method, dict):
                continue
            code_metadata.append({
                "name": method.get("methodId", ""),
                "kind": "method",
                "language": "java",
                "signature": method.get("signature", ""),
            })

    return code_metadata or None


def business_risk_rag(state: GraphState, ctx: NodeContext) -> GraphState:
    """业务风险 RAG 检索 —— 从历史事故库中检索相关业务风险案例。

    执行流程：
    1. 收集查询词（从风险标签、方法问题、语义发现中）
    2. 提取代码元数据（用于增强检索）
    3. 调用统一检索服务（向量检索 + BM25 + RRF 融合 + 重排序）
    4. 格式化结果写入 state["rag_context"]

    参数:
        state: 共享状态
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 rag_context 和 rag_status 字段
    """
    settings = AppSettings()

    # 收集并去重查询词
    terms = _deduplicate(_collect_query_terms(state))
    # 拼接为自然语言查询（如果没有任何查询词，使用默认查询）
    nl_query = " ".join(terms) if terms else "业务风险 事务 并发 数据一致性 故障"
    logger.info("Business risk RAG query: %s", nl_query[:200])

    # 提取代码元数据（用于增强检索精度）
    code_metadata = _build_code_metadata(state)

    # 调用统一检索服务
    retrieval_service = RagRetrievalService(settings)
    try:
        fused, status, reason = retrieval_service.retrieve(
            nl_query, code_metadata, top_k=settings.top_k
        )
    except Exception as exc:
        logger.error("Business risk RAG retrieval failed: %s", exc)
        fused, status, reason = [], "DEGRADED", str(exc)[:200]  # 检索失败时降级

    # 格式化检索结果为 rag_context（向后兼容格式）
    rag_findings = [
        {
            "source": item.get("source", "unknown"),
            "topic": item.get("title", "unknown"),
            "snippet": (item.get("nl_description", "") or item.get("snippet", "")) + "\n" + (item.get("code_content", "") or "")[:200],
            "score": item.get("score", 0),
            "image_urls": item.get("image_urls", []),
            "image_texts": item.get("image_texts", []),
            "citation": {
                "source": item.get("source", "unknown"),
                "title": item.get("title", "unknown"),
                "snippet": item.get("nl_description", item.get("snippet", "")),
                "image_urls": item.get("image_urls", []),
                "entity_name": item.get("entity_name", ""),
                "code_content": item.get("code_content", ""),
            },
        }
        for item in fused
    ]

    # 将检索结果写入共享状态
    state["rag_context"] = rag_findings
    state["rag_status"] = status
    return state
