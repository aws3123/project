"""语义热点扫描节点 —— 用 LLM 深度分析可疑代码片段。

本模块负责对 Java 端预筛出的"热点"（hotspot）方法进行 LLM 深度分析：
- 热点：AST 预筛出的可疑代码片段（可能包含隐含的业务状态变更风险）
- 分析方式：把每个热点发给 LLM，让它判断是否存在业务风险

为什么需要 LLM 分析？
  Java 端的 AST 预筛只能发现"结构上可疑"的代码（如事务内调用远程服务），
  但有些风险需要理解业务语义才能发现（如"库存扣减后没有检查余额"）。
  LLM 能理解业务语义，弥补纯结构分析的不足。

执行流程：
  1. 从源码包中收集所有热点
  2. 用线程池并行发给 LLM（每个热点一次调用）
  3. 收集 LLM 的判断结果，过滤掉"无风险"的
  4. 对低置信度的发现降级处理

类比：
  Java 端 AST 预筛 = 体检中的"初筛"（指标异常的才需要复查）
  LLM 语义分析 = "专家复查"（针对初筛异常项深入分析）
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from config.settings import AppSettings
from graph.state import GraphState, NodeContext
from llm.client import LLMStructuredOutputError
from schemas.semantic_finding import SemanticFindingSchema

logger = logging.getLogger(__name__)

SETTINGS: AppSettings = AppSettings()

# LLM 系统提示词：告诉 LLM 扮演"Java 业务风险分析师"角色
SYSTEM_PROMPT = (
    "你是 Java 业务风险分析师。给定一个 hotspot 方法（BFF 层 AST 预筛出的可疑代码片段），"
    "判断它是否包含隐含的业务状态变更风险。"
    "关注：库存/余额/权益/数量等状态的非预期修改、缺少事务边界的状态变更、并发场景下的竞态、"
    "状态机非法转换、跨聚合副作用。"
    "输出 JSON，字段：has_risk(bool), category(str,可选), severity(high/medium/low), "
    "reason(str,中文), evidence(str), suggestion(str,中文), confidence(0-1)。"
    "若无业务风险，返回 has_risk=false。"
)


def _collect_hotspots(state: GraphState) -> list[dict[str, Any]]:
    """从源码包中收集所有热点方法。

    遍历每个文件的 hotspots 列表，连同文件级上下文（类摘要、注解、方法调用）
    一起收集，供后续 LLM 分析使用。

    参数:
        state: 共享状态，包含 source_package

    返回:
        热点列表，每项包含文件路径、类摘要、注解、热点详情
    """
    out: list[dict[str, Any]] = []
    raw_source = state.get("source_package")
    source_package: dict[str, Any] = raw_source if isinstance(raw_source, dict) else {}
    files = source_package.get("files") or []
    for file in files:
        if not isinstance(file, dict):
            continue
        path = file.get("path", "")
        class_summary = file.get("class_summary")
        file_annotations = file.get("annotations") or []
        # 构建方法签名 → 关键调用的索引（供 LLM 参考）
        key_calls_by_signature: dict[str, list[str]] = {}
        for skeleton in file.get("method_skeletons") or []:
            if isinstance(skeleton, dict):
                sig = skeleton.get("signature") or ""
                key_calls_by_signature[sig] = skeleton.get("key_calls") or []
        for hotspot in file.get("hotspots") or []:
            if not isinstance(hotspot, dict):
                continue
            out.append(
                {
                    "path": path,
                    "class_summary": class_summary,
                    "file_annotations": file_annotations,
                    "key_calls_index": key_calls_by_signature,
                    "hotspot": hotspot,
                }
            )
    return out


def _build_messages(entry: dict[str, Any]) -> list[dict[str, str]]:
    """为单个热点构建 LLM 消息。

    包含文件路径、类摘要、注解等上下文信息，帮助 LLM 理解代码的业务背景。
    """
    hotspot = entry["hotspot"]
    signature = hotspot.get("signature") or hotspot.get("method_id") or "unknown"
    reason = hotspot.get("reason") or ""
    snippet = hotspot.get("snippet") or hotspot.get("raw_snippet") or ""
    # 构建上下文信息
    context_bits = [f"file: {entry['path']}"]
    if entry.get("class_summary"):
        context_bits.append(f"class summary: {entry['class_summary']}")
    if entry.get("file_annotations"):
        context_bits.append(f"file annotations: {', '.join(entry['file_annotations'])}")
    context = "\n".join(context_bits)
    user_content = (
        f"{context}\n\n"
        f"method signature: {signature}\n"
        f"hotspot reason: {reason}\n"
        f"snippet:\n{snippet}\n"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _severity_downgrade(severity: str) -> str:
    """严重级别降级：high→medium, medium→low。

    当 LLM 的置信度低于阈值时，降低发现的严重级别（因为不太确定）。
    """
    return {"high": "medium", "medium": "low"}.get(severity, severity)


def _scan_one(llm_client: Any, entry: dict[str, Any]) -> dict[str, Any] | None:
    """对单个热点执行 LLM 语义分析。

    调用 LLM 判断热点是否存在业务风险，返回标准化的发现字典。
    如果 LLM 判断 has_risk=false，返回 None（表示无风险）。
    """
    messages = _build_messages(entry)
    # 调用 LLM 结构化输出
    parsed = llm_client.chat_structured(
        messages=messages,
        output_schema=SemanticFindingSchema,
        temperature=0.1,       # 低温度：减少随机性，结果更稳定
        max_tokens=512,
    )
    if not parsed.get("has_risk"):
        return None  # LLM 判断无业务风险
    hotspot = entry["hotspot"]
    severity = parsed.get("severity") or "low"
    confidence = float(parsed.get("confidence") or 0.7)
    # 置信度低于阈值 → 降级处理（不太确定就别报那么高）
    if confidence < SETTINGS.semantic_hotspot_confidence_threshold:
        severity = _severity_downgrade(severity)
    return {
        "path": entry["path"],
        "signature": hotspot.get("signature") or hotspot.get("method_id") or "unknown",
        "category": parsed.get("category") or "semantic_risk",
        "severity": severity,
        "reason": parsed.get("reason") or "",
        "evidence": parsed.get("evidence") or hotspot.get("snippet") or "",
        "suggestion": parsed.get("suggestion") or "",
        "confidence": confidence,
        "source": "llm_semantic",  # 标记来源为 LLM 语义分析
    }


def scan_semantic_hotspots(state: GraphState, ctx: NodeContext) -> GraphState:
    """语义热点扫描主函数 —— 用线程池并行调用 LLM 分析所有热点。

    执行策略：
    1. 功能未启用 → 返回空结果（status: disabled）
    2. 没有 LLM 客户端 → 跳过扫描（status: llm_skipped）
    3. 没有热点 → 返回空结果（status: READY）
    4. 有热点 → 线程池并行分析，收集结果

    参数:
        state: 共享状态，包含 source_package
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 semantic_findings 字段
    """
    hotspots = _collect_hotspots(state)

    # 功能未启用
    if not SETTINGS.semantic_hotspot_enabled:
        state["semantic_findings"] = {
            "items": [],
            "scanned_count": 0,
            "status": "disabled",
            "reason": None,
        }
        return state

    # 没有 LLM 客户端
    if ctx.llm_client is None:
        state["semantic_findings"] = {
            "items": [],
            "scanned_count": len(hotspots),
            "status": "llm_skipped",
            "reason": None,
        }
        return state

    # 没有热点需要分析
    if not hotspots:
        state["semantic_findings"] = {
            "items": [],
            "scanned_count": 0,
            "status": "READY",
            "reason": None,
        }
        return state

    # 线程池并行分析所有热点
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    max_workers = min(SETTINGS.semantic_hotspot_concurrency, len(hotspots))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_entry = {
            pool.submit(_scan_one, ctx.llm_client, entry): entry for entry in hotspots
        }
        for future in as_completed(future_to_entry):
            try:
                finding = future.result()
                if finding is not None:
                    items.append(finding)
            except (LLMStructuredOutputError, Exception) as exc:
                logger.warning("semantic_hotspot_scan failed for one hotspot: %s", exc)
                errors.append(str(exc)[:200])

    # 判断状态：有结果或没有错误 → READY，全部失败 → llm_failed
    if items or not errors:
        status = "READY"
    else:
        status = "llm_failed"
    state["semantic_findings"] = {
        "items": items,                     # 语义发现列表
        "scanned_count": len(hotspots),     # 扫描的热点总数
        "status": status,                   # 分析状态
        "reason": errors[-1] if errors else None,  # 最后一个错误信息（如有）
    }
    return state
