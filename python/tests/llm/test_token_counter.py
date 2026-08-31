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
    items = [
        {"snippet": "hello world"},
        {"snippet": "A" * 5000},
    ]
    result = truncate_to_budget(items, max_tokens=1000)
    assert len(result) == 1
