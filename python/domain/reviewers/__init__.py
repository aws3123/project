"""审查专家领域逻辑 —— 纯函数 + 常量，可与流水线解耦独立测试。

每个模块（security_review / performance_review / scoring / report / …）
不含 graph.state 依赖：纯函数入参为原始数据，由 graph/nodes 的薄节点
适配器负责 state 读写与降级日志。

依赖方向：reviewers -> domain.shared / tools / schemas（不依赖 graph 编排层）。
"""
