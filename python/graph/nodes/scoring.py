"""风险评分节点 —— 给代码变更"打分"，决定风险等级和是否需要人工审查。

本模块负责综合所有分析结果（规则、安全、性能、RAG），计算一个 0~1 的风险分数。

核心功能：
1. 交叉验证：同一位置的代码被多个 Agent 同时标记 → 置信度提升
2. LLM 评分：让大模型综合所有信息给出风险评分（0-100）
3. 确定性评分（降级）：没有 LLM 时用加权公式计算

类比：
  就像高考阅卷——
  - 交叉验证 = 同一道题多个老师批阅，如果都扣分说明确实有问题
  - LLM 评分 = 资深专家综合评判
  - 确定性评分 = 按标准答案的评分规则自动打分（兜底方案）
"""
from __future__ import annotations

from graph.state import GraphState, NodeContext
from llm.client import LLMStructuredOutputError
from schemas.llm_output import ScoringOutput

# Agent 权重：不同 Agent 的发现对最终评分的贡献权重
# security 权重最高（3），因为安全问题通常最严重
AGENT_WEIGHT = {"security": 3, "rules": 2, "performance": 1.5, "rag": 1}
# 严重级别乘数：HIGH 的问题影响是 LOW 的 3 倍
SEVERITY_MULTIPLIER = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0.5}

# ===== 确定性评分（降级模式）的参数 =====
# 基础分：即使没有任何发现，也有 0.2 的基础风险分
_BASE_SCORE = 0.2
# 各类 HIGH 级别发现的权重和上限
_RULE_HIGH_WEIGHT = 0.2       # 每个规则 HIGH 发现加 0.2
_RULE_HIGH_CAP = 0.5          # 规则部分最多加 0.5
_SECURITY_HIGH_WEIGHT = 0.25  # 每个安全 HIGH 发现加 0.25
_SECURITY_HIGH_CAP = 0.5      # 安全部分最多加 0.5
_PERF_HIGH_WEIGHT = 0.15      # 每个性能 HIGH 发现加 0.15
_PERF_HIGH_CAP = 0.3          # 性能部分最多加 0.3
_RAG_CONTEXT_WEIGHT = 0.1     # 每条 RAG 关联加 0.1
_RAG_CONTEXT_CAP = 0.3        # RAG 部分最多加 0.3
_LOW_COVERAGE_BONUS = 0.2     # 低覆盖率额外加 0.2 风险分
_COVERAGE_THRESHOLD = 0.8     # 覆盖率低于 80% 视为"低覆盖"
_IMPACT_WEIGHT = 0.1          # 影响面评分权重
_IMPACT_CAP = 0.2             # 影响面部分最多加 0.2
_HUMAN_REVIEW_THRESHOLD = 0.7 # 风险分 >= 0.7 → 强制人工审查
_MAX_AFFECTED_FILES_FOR_AUTO_REVIEW = 10  # 影响文件 > 10 个 → 强制人工审查


def _cross_validate(state: GraphState) -> tuple[list[dict], bool]:
    """交叉验证 —— 找出被多个 Agent 同时标记的代码位置。

    如果同一个文件+行号被安全、性能、规则中的多个 Agent 同时发现问题，
    说明这个问题更可信 → 提升置信度，标记 cross_validated_by。

    矛盾检测：如果同一位置既有 HIGH 又有 LOW/INFO，说明 Agent 间有分歧 →
    强制人工审查（force_human = True）。

    参数:
        state: 共享状态，包含各 Agent 的发现列表

    返回:
        (merged_findings, force_human_review)
        - merged_findings: 合并后的发现列表（去重+增强）
        - force_human_review: 是否需要强制人工审查
    """
    # 按代码位置分组所有发现
    sources = {
        "rules": state.get("rule_findings", []),
        "security": state.get("security_findings", []),
        "performance": state.get("performance_findings", []),
    }
    file_groups: dict[str, list[dict]] = {}
    for source, findings in sources.items():
        for f in findings:
            loc = f"{f.get('file','')}:{f.get('line','')}"
            file_groups.setdefault(loc, []).append({**f, "_source": source})

    merged: list[dict] = []
    force_human = False

    for loc, items in file_groups.items():
        if len(items) == 1:
            merged.append(items[0])  # 只有一个 Agent 发现，直接保留
            continue

        # 多个 Agent 在同一位置发现问题 → 交叉验证
        # 计算加权分数（Agent 权重 × 严重级别乘数 的总和）
        weighted_score = sum(
            AGENT_WEIGHT.get(item["_source"], 1) *
            SEVERITY_MULTIPLIER.get(item.get("severity", "LOW"), 1)
            for item in items
        )
        # 取最严重的发现作为代表，提升其置信度（多人确认 = 更可信）
        best = max(items, key=lambda x: SEVERITY_MULTIPLIER.get(x.get("severity", "LOW"), 0))
        best["confidence"] = min(best.get("confidence", 0.5) * 1.3, 1.0)  # 置信度提升 30%，上限 1.0
        best["cross_validated_by"] = [item["_source"] for item in items]   # 记录哪些 Agent 确认了
        best["cross_validation_score"] = weighted_score
        merged.append(best)

        # 矛盾检测：同一位置既有 HIGH 又有 LOW/INFO → 需要人工判断
        severities = {item.get("severity") for item in items}
        if "HIGH" in severities and any(s in ("LOW", "INFO") for s in severities):
            force_human = True

    return merged, force_human


def _deterministic_fallback(state: GraphState) -> None:
    """确定性评分（降级模式）—— 没有 LLM 时用加权公式计算风险分。

    评分公式：
      基础分(0.2) + 规则HIGH加分 + 安全HIGH加分 + 性能HIGH加分
      + RAG关联加分 + 低覆盖率加分 + 影响面加分

    每个部分都有上限（cap），防止某一项主导总分。
    最终分数限制在 [0, 1] 范围内。
    """
    rule_findings = state.get("rule_findings", [])
    security_findings = state.get("security_findings", [])
    performance_findings = state.get("performance_findings", [])
    rag_context = state.get("rag_context", [])
    impact_radius = state.get("impact_radius", {})
    coverage = state.get("classification", {}).get("summary", {}).get("coverage", 1.0)

    # 从去重节点读取预计算结果（向后兼容：未运行时现场计算）
    force_human = state.get("force_human_review", False)
    if "force_human_review" not in state:
        _, force_human = _cross_validate(state)

    impact_score = impact_radius.get("total_impact_score", 0)
    affected_count = len(impact_radius.get("affected_files", []))

    # 加权求和，每部分有上限
    score = _BASE_SCORE
    score += min(len([f for f in rule_findings if f.get("severity") == "HIGH"]) * _RULE_HIGH_WEIGHT, _RULE_HIGH_CAP)
    score += min(len([f for f in security_findings if f.get("severity") == "HIGH"]) * _SECURITY_HIGH_WEIGHT, _SECURITY_HIGH_CAP)
    score += min(len([f for f in performance_findings if f.get("severity") == "HIGH"]) * _PERF_HIGH_WEIGHT, _PERF_HIGH_CAP)
    score += min(len(rag_context) * _RAG_CONTEXT_WEIGHT, _RAG_CONTEXT_CAP)
    score += _LOW_COVERAGE_BONUS if coverage < _COVERAGE_THRESHOLD else 0  # 低覆盖率额外加分
    score += min(impact_score * _IMPACT_WEIGHT, _IMPACT_CAP)
    score = min(score, 1.0)  # 总分上限 1.0

    state["risk_score"] = score
    # 生成各维度的细分评分（前端展示用）
    state["breakdown"] = [
        {"dimension": "规则检查", "score": min(len(rule_findings) * 10, 100), "count": len(rule_findings)},
        {"dimension": "安全审计", "score": min(len(security_findings) * 15, 100), "count": len(security_findings)},
        {"dimension": "性能分析", "score": min(len(performance_findings) * 10, 100), "count": len(performance_findings)},
        {"dimension": "历史关联", "score": min(len(rag_context) * 10, 100), "count": len(rag_context)},
        {"dimension": "影响范围", "score": min(affected_count * 10, 100), "count": affected_count},
        {"dimension": "测试覆盖", "score": int((1 - coverage) * 100)},
    ]
    # 判断是否需要人工审查
    state["need_human_review"] = score >= _HUMAN_REVIEW_THRESHOLD or force_human or affected_count > _MAX_AFFECTED_FILES_FOR_AUTO_REVIEW


def score_risks(state: GraphState, ctx: NodeContext) -> GraphState:
    """风险评分主函数 —— 综合所有分析结果计算风险分数。

    执行策略：
    1. 平凡变更（trivial=True）→ 直接跳过评分
    2. 交叉验证 → 合并多 Agent 发现，检测矛盾
    3. 没有 LLM → 确定性评分（降级）
    4. 有 LLM → 让大模型综合评判，失败时降级到确定性评分

    参数:
        state: 共享状态，包含所有前序节点的分析结果
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 risk_score、breakdown、need_human_review 等字段
    """
    # 平凡变更 → 直接返回预填充结果（triviality_check 已设置）
    if state.get("trivial"):
        return state

    # 读取去重节点的预计算结果（deduplicate 已运行时）
    cross_merged = state.get("cross_validated_findings", [])
    force_human = state.get("force_human_review", False)
    # 向后兼容：deduplicate 未运行时现场计算
    if "cross_validated_findings" not in state:
        cross_merged, force_human = _cross_validate(state)

    # 降级模式：没有 LLM 时用确定性公式评分
    if ctx.llm_client is None:
        _deterministic_fallback(state)
        if force_human:
            state["need_human_review"] = True
        return state

    # 收集各维度的分析结果
    rule_findings = state.get("rule_findings", [])
    security_findings = state.get("security_findings", [])
    performance_findings = state.get("performance_findings", [])
    rag_analysis = state.get("rag_analysis", "")
    classification = state.get("classification", {})
    diff_analysis = state.get("diff_analysis", {})
    coverage = classification.get("summary", {}).get("coverage", 1.0)
    impact_radius = state.get("impact_radius", {})
    impact_score = impact_radius.get("total_impact_score", 0)
    affected_count = len(impact_radius.get("affected_files", []))

    # 构建发现摘要文本（最多取前 15 条）
    all_findings_text = "\n".join(
        f"- [{f.get('severity','INFO')}] [{f.get('category','')}] {f.get('title','')}: {f.get('detail','')}"
        for f in (rule_findings + security_findings + performance_findings)[:15]
    )

    # 构建交叉验证文本（多 Agent 共识的发现）
    cross_text = ""
    if cross_merged:
        cross_items = [f for f in cross_merged if f.get("cross_validated_by")]
        if cross_items:
            cross_text = "## 交叉验证发现（多 Agent 共识）\n" + "\n".join(
                f"- [{f.get('severity','')}] {f.get('title','')} (验证方: {', '.join(f.get('cross_validated_by',[]))}, 加权分: {f.get('cross_validation_score',0):.1f})"
                for f in cross_items[:5]
            )
    if force_human:
        cross_text += "\n\n⚠️ 发现 Agent 间矛盾判定，建议强制人工复核。"

    # 构建影响范围文本
    impact_text = ""
    if impact_radius:
        impact_text = (
            f"## 变更影响范围\n"
            f"直接影响文件: {impact_radius.get('changed_files', [])}\n"
            f"间接影响文件: {impact_radius.get('affected_files', [])}\n"
            f"影响面评分: {impact_score:.1f} (0=无影响, 越高影响越大)\n"
        )

    # 构建 LLM 消息
    messages = [
        {
            "role": "system",
            "content": "你是代码审查风险评估专家。基于多 Agent 分析结果（规则检查、安全审计、性能分析、历史关联、变更影响范围），评估风险。输出 JSON 格式。",
        },
        {
            "role": "user",
            "content": (
                f"## 综合分析结果\n{all_findings_text or '无'}\n\n"
                f"{cross_text}\n\n"
                f"{impact_text}\n"
                f"## 历史事故关联\n{rag_analysis or '无'}\n\n"
                f"## 测试覆盖率\n{coverage:.0%}\n\n"
                "请评估风险，输出 risk_score (0-100整数)、breakdown (维度含安全/性能/稳定性/数据一致性/兼容性/影响范围，每项含dimension/score/reason)、"
                "need_human_review (bool) 和 risk_summary (一句话总结)。"
            ),
        },
    ]

    # 调用 LLM 进行结构化评分
    try:
        result = ctx.llm_client.chat_structured(
            messages=messages, output_schema=ScoringOutput, max_tokens=1024,
        )
        # LLM 返回 0-100 分，转换为 0-1 范围
        state["risk_score"] = result["risk_score"] / 100.0
        breakdown = result.get("breakdown", [])
        if 0 <= result["risk_score"] <= 100:
            state["breakdown"] = [
                {"dimension": item.get("dimension", "unknown"), "score": item.get("score", 0), "reason": item.get("reason", "")}
                for item in breakdown
            ]
        state["need_human_review"] = result.get("need_human_review", False) or force_human
        state["risk_summary"] = result.get("risk_summary", "")
    except LLMStructuredOutputError:
        # LLM 输出格式错误 → 降级到确定性评分
        _deterministic_fallback(state)
        if force_human:
            state["need_human_review"] = True

    return state
