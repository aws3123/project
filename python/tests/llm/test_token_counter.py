"""Tests for tiktoken-based token counting."""

from llm.token_counter import count_tokens, truncate_to_budget


def test_count_tokens_english():
    n = count_tokens("hello world")
    assert n >= 2


def test_count_tokens_chinese():
    n = count_tokens("你好世界")
    assert n >= 2


def test_count_tokens_empty():
    assert count_tokens("") == 0


def test_truncate_to_budget_empty():
    result = truncate_to_budget([], max_tokens=100)
    assert result == []


def test_truncate_to_budget_within_limit():
    items = [
        {"snippet": "short text"},
        {"snippet": "another short text"},
    ]
    result = truncate_to_budget(items, max_tokens=1000)
    assert len(result) == 2


def test_truncate_to_budget_exceeds_limit():
    items = [{"snippet": "A" * 5000}]
    result = truncate_to_budget(items, max_tokens=100)
    assert len(result) == 0


def test_truncate_to_budget_partial():
    # 用大量互不相同的 token 构造第二条，确保其显著超出 1000 token 预算
    # （避免纯重复字符被 BPE 高度压缩，导致长度误判）
    long_snippet = " ".join(f"word{i}" for i in range(2000))
    items = [
        {"snippet": "hello world"},
        {"snippet": long_snippet},
    ]
    result = truncate_to_budget(items, max_tokens=1000)
    assert len(result) == 1
