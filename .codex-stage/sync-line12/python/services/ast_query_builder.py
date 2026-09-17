"""Build deterministic incident-search queries from a submitted diff and AST."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


_RISK_TERMS: dict[str, tuple[str, ...]] = {
    "EXTERNAL_CALL_INSIDE_TRANSACTION": (
        "事务内远程调用",
        "分布式事务不一致",
        "remote call in transaction",
        "distributed transaction inconsistency",
    ),
    "CHECK_THEN_ACT_CANDIDATE": (
        "先查后写",
        "竞态条件",
        "并发数据不一致",
        "check then act race condition",
    ),
    "CACHE_DB_DUAL_WRITE": (
        "缓存数据库双写不一致",
        "cache database dual write inconsistency",
    ),
    "MQ_INSIDE_TRANSACTION": (
        "消息队列事务一致性",
        "消息发送回滚",
        "message transaction consistency",
    ),
    "TRANSACTIONAL": ("事务边界", "事务回滚", "transaction boundary", "rollback"),
    "LOCKING_PRESENT": ("锁竞争", "死锁", "lock contention", "deadlock"),
    "SYNCHRONIZED_METHOD": ("同步锁", "锁竞争", "synchronized lock"),
    "SYNCHRONIZED_BLOCK": ("同步锁", "锁竞争", "synchronized lock"),
    "EXPLICIT_LOCK": ("显式锁", "死锁", "explicit lock", "deadlock"),
    "DB_LOCK": ("数据库锁", "行锁", "死锁", "database lock", "deadlock"),
}

_CODE_SIGNAL_TERMS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("@transactional", "transactiontemplate"), _RISK_TERMS["TRANSACTIONAL"]),
    (("kafka", "rabbitmq", ".publish(", ".send("), _RISK_TERMS["MQ_INSIDE_TRANSACTION"]),
    (("redis", "cache", "evict", "put("), _RISK_TERMS["CACHE_DB_DUAL_WRITE"]),
    (("synchronized", "reentrantlock", ".lock("), _RISK_TERMS["LOCKING_PRESENT"]),
    (("resttemplate", "webclient", "feign", "httpclient"), _RISK_TERMS["EXTERNAL_CALL_INSIDE_TRANSACTION"]),
)


def _append_unique(terms: list[str], seen: set[str], value: object) -> None:
    if not isinstance(value, str):
        return
    normalized = " ".join(value.split()).strip()
    if normalized and normalized not in seen:
        seen.add(normalized)
        terms.append(normalized)


def _path_terms(path: str) -> list[str]:
    pure = PurePosixPath(path.replace("\\", "/"))
    values = [pure.name, pure.stem]
    values.extend(part for part in pure.parts if part not in {"src", "main", "java", "python"})
    return values


def _collect_hotspot_terms(state: dict[str, Any], terms: list[str], seen: set[str]) -> None:
    source_package = state.get("source_package", {}) or {}
    for file_info in source_package.get("files", []) or []:
        if not isinstance(file_info, dict):
            continue
        _append_unique(terms, seen, file_info.get("path") or file_info.get("filePath"))
        for method in file_info.get("methods", []) or []:
            if isinstance(method, dict):
                _append_unique(terms, seen, method.get("methodId"))
                _append_unique(terms, seen, method.get("signature"))
        for hotspot in file_info.get("hotspots", []) or []:
            if not isinstance(hotspot, dict):
                continue
            for tag in hotspot.get("riskTags", []) or []:
                for term in _RISK_TERMS.get(str(tag), (str(tag).replace("_", " "),)):
                    _append_unique(terms, seen, term)


def _collect_code_signals(value: object, terms: list[str], seen: set[str], budget: list[int]) -> None:
    if budget[0] <= 0:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"diff", "patch", "content", "code", "sourceCode", "after", "before"}:
                _collect_code_signals(child, terms, seen, budget)
    elif isinstance(value, list):
        for child in value:
            _collect_code_signals(child, terms, seen, budget)
    elif isinstance(value, str):
        budget[0] -= 1
        lowered = value.lower()
        for markers, mapped_terms in _CODE_SIGNAL_TERMS:
            if any(marker in lowered for marker in markers):
                for term in mapped_terms:
                    _append_unique(terms, seen, term)


def build_ast_retrieval_query(state: dict[str, Any], fallback: str = "") -> str:
    """Create a multilingual retrieval profile without requiring an LLM.

    The output mixes exact identifiers for keyword recall with stable risk
    concepts for semantic recall against the incident-document corpus.
    """
    terms: list[str] = []
    seen: set[str] = set()

    _append_unique(terms, seen, fallback)
    for layer in (state.get("classification", {}) or {}).get("layers", []) or []:
        _append_unique(terms, seen, layer)

    paths = ((state.get("diff_analysis", {}) or {}).get("summary", {}) or {}).get("paths", []) or []
    for path in paths:
        if isinstance(path, str):
            for term in _path_terms(path):
                _append_unique(terms, seen, term)

    for entity in (state.get("request", {}) or {}).get("entities", []) or []:
        if isinstance(entity, dict):
            _append_unique(terms, seen, entity.get("name"))
            _append_unique(terms, seen, entity.get("signature"))

    _collect_hotspot_terms(state, terms, seen)
    for issue in ((state.get("method_issues", {}) or {}).get("issues", []) or []):
        if isinstance(issue, dict):
            _append_unique(terms, seen, issue.get("reason"))
    for finding in ((state.get("semantic_findings", {}) or {}).get("items", []) or []):
        if isinstance(finding, dict):
            _append_unique(terms, seen, finding.get("category"))
            _append_unique(terms, seen, finding.get("reason"))

    _collect_code_signals(state.get("diff_analysis", {}), terms, seen, [12])
    return " ".join(terms[:80]) or "historical incident failure risk"
