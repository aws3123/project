"""
LLM 客户端与工具模块
======================

作用：
    提供与大语言模型（LLM）交互的客户端，以及 Token 计数工具。

暴露的核心组件：
    - LLMClient: 封装了 OpenAI 兼容 API 的 LLM 客户端
    - count_tokens: 计算文本的 Token 数量
    - truncate_to_budget: 在 Token 预算内截断文本列表
"""

# 从 llm 子模块中导入核心组件
from llm.client import LLMClient
from llm.token_counter import count_tokens, truncate_to_budget

# 公开 API 声明
__all__ = ["LLMClient", "count_tokens", "truncate_to_budget"]
"""LLM client and token utilities for AI-powered code review."""

from llm.client import LLMClient
from llm.token_counter import count_tokens, truncate_to_budget

__all__ = ["LLMClient", "count_tokens", "truncate_to_budget"]
