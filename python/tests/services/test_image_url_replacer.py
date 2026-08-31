"""Tests for markdown image URL replacement logic (pure functions, no MinIO needed)."""

from __future__ import annotations

from services.image_url_replacer import extract_image_references, replace_markdown_image_urls

ENDPOINT = "http://localhost:9000"
BUCKET = "incident-images"


def test_no_image_no_change() -> None:
    text = "纯文本没有图片引用"
    assert replace_markdown_image_urls(text, ENDPOINT, BUCKET) == text


def test_placeholder_replaced() -> None:
    text = "如图所示 ![架构图](PLACEHOLDER:incident-001/arch.png)"
    expected = "如图所示 ![架构图](http://localhost:9000/incident-images/images/incident-001/arch.png)"
    assert replace_markdown_image_urls(text, ENDPOINT, BUCKET) == expected


def test_multiple_placeholders() -> None:
    text = (
        "图1: ![架构](PLACEHOLDER:incident-001/arch.png)\n"
        "图2: ![监控](PLACEHOLDER:incident-002/dashboard.jpg)"
    )
    result = replace_markdown_image_urls(text, ENDPOINT, BUCKET)
    assert "incident-images/images/incident-001/arch.png" in result
    assert "incident-images/images/incident-002/dashboard.jpg" in result


def test_external_urls_unchanged() -> None:
    text = "外部图片 ![logo](https://example.com/logo.png)"
    assert replace_markdown_image_urls(text, ENDPOINT, BUCKET) == text


def test_mixed_content() -> None:
    text = (
        "概要: 此处有风险\n"
        "详情: 参考历史事故 ![堆栈](PLACEHOLDER:incident-001/stack.png)\n"
        "外部: ![logo](https://example.com/logo.png)"
    )
    result = replace_markdown_image_urls(text, ENDPOINT, BUCKET)
    assert "incident-images/images/incident-001/stack.png" in result
    assert "https://example.com/logo.png" in result


def test_empty_and_none() -> None:
    assert replace_markdown_image_urls("", ENDPOINT, BUCKET) == ""
    assert replace_markdown_image_urls(None, ENDPOINT, BUCKET) is None  # type: ignore


def test_extract_image_references() -> None:
    text = "![a](url1) 和 ![b](url2) 和外部![c](https://ext.com/img.png)"
    urls = extract_image_references(text)
    assert "url1" in urls
    assert "url2" in urls
    assert "https://ext.com/img.png" in urls


def test_no_images() -> None:
    assert extract_image_references("纯文本无图片") == []


def test_replacer_with_endpoint_trailing_slash() -> None:
    text = "![图](PLACEHOLDER:inc-001/x.png)"
    result = replace_markdown_image_urls(text, "http://localhost:9000/", BUCKET)
    assert "http://localhost:9000/incident-images" in result
    assert "//incident-images" not in result
