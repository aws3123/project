"""审查共享逻辑 —— 跨多个审查器复用的无状态纯函数。

例如 diff_extractor（从 unified diff 提取完整方法体），
被安全/性能/rag 等多个评审节点共享，故提升到 domain.shared。
"""