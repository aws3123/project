"""业务不变量提取节点 —— 从源码包中提取业务规则和约束。

本模块负责从 Java 端预处理的源码包中提取"业务不变量"（Business Invariants）：
- 业务不变量：代码中必须始终为真的业务规则（如"库存不能为负"、"订单金额必须大于0"）
- 提取方式：扫描方法骨架（method skeletons），找出带注解或有特定调用的方法

类比：
  就像从一本操作手册中提取"安全守则"——
  先找出哪些章节包含了安全规则，后续检查这些规则是否被违反。
"""

from __future__ import annotations

from graph.state import GraphState, NodeContext


def extract_business_invariants(state: GraphState, ctx: NodeContext) -> GraphState:
    """从源码包中提取业务不变量。

    扫描源码包中每个文件的方法骨架，找出带注解（如 @Transactional）
    或有关键调用（如 repository.save）的方法，这些方法可能涉及业务状态变更。

    参数:
        state: 共享状态，包含 request 和 source_package
        ctx:   节点上下文（工具箱）

    返回:
        更新后的 state，新增了 business_invariants 字段
    """
    request = state.get("request", {})
    metadata = request.get("metadata", {}) if isinstance(request, dict) else {}
    source_package = (
        state.get("source_package", {})
        if isinstance(state.get("source_package", {}), dict)
        else {}
    )
    files = source_package.get("files", []) if isinstance(source_package, dict) else []

    # 从方法骨架中推断可能涉及业务状态变更的方法
    inferred = []
    for source_file in files:
        if not isinstance(source_file, dict):
            continue
        path = source_file.get("path", "")
        methods = (
            source_file.get("methods") or source_file.get("method_skeletons") or []
        )
        for method in methods:
            if not isinstance(method, dict):
                continue
            annotations = method.get("annotations", []) or []
            key_calls = method.get("key_calls", []) or []
            # 只提取有注解或关键调用的方法（这些方法更可能涉及业务逻辑）
            if annotations or key_calls:
                inferred.append(
                    {
                        "path": path,
                        "signature": method.get("signature", "unknown"),
                        "annotations": annotations,  # 方法注解（如 @Transactional）
                        "key_calls": key_calls,  # 关键调用（如 repository.save）
                    }
                )

    # 将提取结果写入共享状态
    state["business_invariants"] = {
        "source": "source_package",
        "items": metadata.get("business_invariants", [])
        or [],  # 请求中显式声明的不变量
        "inferred_methods": inferred,  # 从源码推断的不变量方法
        "status": "READY",
    }
    return state
