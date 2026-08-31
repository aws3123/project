"""去重节点 — 交叉验证并行 Agent 的发现，合并重复项，检测矛盾。

作用：
    在并行分析阶段结束后、评分之前执行。
    将 rules / security / performance 三个 Agent 的发现按"文件:行号"分组：
      - 同一位置被多个 Agent 发现 → 合并为一条，提升置信度
      - 记录被哪些 Agent 共同发现（cross_validated_by）
      - 检测 Agent 间矛盾（同一位置既有 HIGH 又有 LOW/INFO）→ 标记强制人工复核

为什么独立成节点？
    原来这段逻辑嵌入在 scoring 节点内部，导致：
      1. 去重和评分职责耦合
      2. LLM 评分路径下，LLM 看到的是去重前的原始发现，可能被重复项误导
    独立后，scoring 节点接收的是已去重、已交叉验证的干净数据。
"""

from __future__ import annotations

from graph.state import GraphState, NodeContext

# Agent 权重：不同 Agent 的发现重要性不同
# 安全问题权重最高（3），规则检查次之（2），性能问题再次之（1.5），RAG 关联最低（1）
AGENT_WEIGHT = {"security": 3, "rules": 2, "performance": 1.5, "rag": 1}
# 严重级别乘数：HIGH 问题权重是 LOW 的 3 倍
SEVERITY_MULTIPLIER = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0.5}


def _cross_validate(state: GraphState) -> tuple[list[dict], bool]:
    """交叉验证：合并同一位置被多个 Agent 同时发现的重复问题。

    工作原理：
      1. 收集规则、安全、性能三个 Agent 的发现
      2. 按"文件:行号"分组
      3. 如果同一位置有多个 Agent 的发现：
         - 选择严重级别最高的那条作为代表
         - 提升其置信度（乘以 1.3，上限 1.0）
         - 记录"被哪些 Agent 共同发现"
      4. 如果发现矛盾（同一位置既有 HIGH 又有 LOW），标记需要强制人工复核

    参数：
        state: 流水线全局状态
    返回：
        (合并后的发现列表, 是否强制人工复核)
    """
    # 收集三个 Agent 的发现
    sources = {
        "rules": state.get("rule_findings", []),
        "security": state.get("security_findings", []),
        "performance": state.get("performance_findings", []),
    }
    # 按"文件:行号"分组
    file_groups: dict[str, list[dict]] = {}
    for source, findings in sources.items():
        for f in findings:
            loc = f"{f.get('file','')}:{f.get('line','')}"
            # {**f, "_source": source} 复制原字典并添加 _source 字段标记来源
            file_groups.setdefault(loc, []).append({**f, "_source": source})

    merged: list[dict] = []  # 合并后的发现列表
    force_human = False      # 是否强制人工复核

    for loc, items in file_groups.items():
        # 如果该位置只有一条发现，直接保留
        if len(items) == 1:
            merged.append(items[0])
            continue

        # 多条发现 → 交叉验证
        # 计算加权分数：每个 Agent 的权重 × 严重级别乘数，求和
        weighted_score = sum(
            AGENT_WEIGHT.get(item["_source"], 1) *
            SEVERITY_MULTIPLIER.get(item.get("severity", "LOW"), 1)
            for item in items
        )
        # 选择严重级别最高的那条作为代表
        best = max(items, key=lambda x: SEVERITY_MULTIPLIER.get(x.get("severity", "LOW"), 0))
        # 提升置信度（被多个 Agent 验证过，更可信）
        best["confidence"] = min(best.get("confidence", 0.5) * 1.3, 1.0)
        # 记录被哪些 Agent 共同发现
        best["cross_validated_by"] = [item["_source"] for item in items]
        best["cross_validation_score"] = weighted_score
        merged.append(best)

        # 矛盾检测：同一位置既有 HIGH 又有 LOW/INFO → 需要人工介入
        severities = {item.get("severity") for item in items}
        if "HIGH" in severities and any(s in ("LOW", "INFO") for s in severities):
            force_human = True

    return merged, force_human


def deduplicate_findings(state: GraphState, ctx: NodeContext) -> GraphState:
    """去重节点的主函数 — 交叉验证并行 Agent 的发现。

    输入：state["rule_findings"], state["security_findings"], state["performance_findings"]
    输出：state["cross_validated_findings"] — 合并后的发现列表
          state["force_human_review"] — 是否强制人工复核（Agent 间矛盾）

    如果 state 中已有预计算结果（如平凡变更场景），直接跳过。
    """
    # 平凡变更 → 跳过（triviality_check 已预填充）
    if state.get("trivial"):
        return state

    merged, force_human = _cross_validate(state)
    state["cross_validated_findings"] = merged
    state["force_human_review"] = force_human
    return state
