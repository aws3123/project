from __future__ import annotations

import tiktoken

_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def truncate_to_budget(
    items: list[dict],
    text_key: str = "snippet",
    max_tokens: int = 2000,
) -> list[dict]:
    kept: list[dict] = []
    used = 0
    for item in items:
        tok = count_tokens(item.get(text_key, ""))
        if used + tok > max_tokens:
            break
        kept.append(item)
        used += tok
    return kept
