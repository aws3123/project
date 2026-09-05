"""不变量检查节点 —— 检查业务规则是否被违反。

本模块负责检查代码中是否存在"业务不变量违反"：
- 不变量（Invariant）：代码中必须始终为真的条件（如"扣库存前必须有事务保护"）
- 违反（Violation）：检测到可能破坏这些条件的代码模式

检测逻辑：
  如果方法中调用了"状态变更"操作（如 reserve/deduct/decrease），
  但方法上没有 @Transactional 注解 → 可能存在事务缺失的风险

类比：
  就像检查"操作规范是否被遵守"——
  比如规定"带电操作必须戴绝缘手套"，如果发现有人带电操作但没戴手套，就是违反。
"""

from __future__ import annotations

from graph.state import GraphState, NodeContext


def check_invariants(state: GraphState, ctx: NodeContext) -> GraphState:
    """检查业务不变量是否被违反。

    从 business_invariants 中提取推断的方法列表，检查每个方法：
    - 如果方法有 @Transactional 注解且调用了 Repository → 安全（有事务保护）
    - 如果方法调用了 reserve/deduct/decrease 等状态变更操作但没有事务保护 → 违反

    参数:
        state: 共享状态，包含 business_invariants（由 business_extractor 节点产出）
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 invariant_violations 字段
    """
    invariants = state.get("business_invariants", {})
    items = invariants.get("items", []) if isinstance(invariants, dict) else []
    inferred_methods = (
        invariants.get("inferred_methods", []) if isinstance(invariants, dict) else []
    )

    violations = []
    for method in inferred_methods:
        annotations = method.get("annotations", []) or []
        key_calls = method.get("key_calls", []) or []
        # 如果方法有 @Transactional 注解且调用了 Repository → 有事务保护，安全
        if any(
            "Transactional" in str(annotation) for annotation in annotations
        ) and any(
            "Repository" in str(call) or ".save" in str(call) or ".update" in str(call)
            for call in key_calls
        ):
            continue
        # 如果方法调用了"状态变更"操作（如扣库存、扣余额）→ 检查是否有事务保护
        if any(
            "reserve" in str(call).lower()
            or "deduct" in str(call).lower()
            or "decrease" in str(call).lower()
            for call in key_calls
        ):
            violations.append(
                {
                    "path": method.get("path", ""),
                    "signature": method.get("signature", "unknown"),
                    "reason": "state-changing inventory flow without obvious transactional guard",
                }
            )

    # 将违反列表写入共享状态
    state["invariant_violations"] = {
        "violations": violations,  # 违反列表
        "checked_count": len(items) + len(inferred_methods),  # 检查的方法总数
        "status": "READY",
    }
    return state
