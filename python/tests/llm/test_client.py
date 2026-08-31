"""Tests for LLM client with structured output and defensive retry."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from llm.client import LLMClient, LLMStructuredOutputError


class TestSchema(BaseModel):
    name: str
    value: int = Field(ge=0, le=100)


def _mock_chat_response(content: str):
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message = MagicMock()
    mock.choices[0].message.content = content
    return mock


def test_chat_returns_content():
    client = LLMClient()
    with patch.object(client._client.chat.completions, "create") as mock_create:
        mock_create.return_value = _mock_chat_response("hello")
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "hello"


def test_chat_structured_success():
    client = LLMClient()
    valid_json = json.dumps({"name": "test", "value": 50})
    with patch.object(client._client.chat.completions, "create") as mock_create:
        mock_create.return_value = _mock_chat_response(valid_json)
        result = client.chat_structured(
            [{"role": "user", "content": "test"}],
            output_schema=TestSchema,
        )
    assert result == {"name": "test", "value": 50}


def test_chat_structured_retry_on_json_error():
    client = LLMClient()
    bad_json = "{invalid"
    valid_json = json.dumps({"name": "ok", "value": 80})
    with patch.object(client._client.chat.completions, "create") as mock_create:
        mock_create.side_effect = [
            _mock_chat_response(bad_json),
            _mock_chat_response(valid_json),
        ]
        result = client.chat_structured(
            [{"role": "user", "content": "test"}],
            output_schema=TestSchema,
        )
    assert result == {"name": "ok", "value": 80}
    assert mock_create.call_count == 2


def test_chat_structured_retry_on_validation_error():
    client = LLMClient()
    invalid_value = json.dumps({"name": "bad", "value": 999})
    valid_json = json.dumps({"name": "ok", "value": 42})
    with patch.object(client._client.chat.completions, "create") as mock_create:
        mock_create.side_effect = [
            _mock_chat_response(invalid_value),
            _mock_chat_response(valid_json),
        ]
        result = client.chat_structured(
            [{"role": "user", "content": "test"}],
            output_schema=TestSchema,
        )
    assert result == {"name": "ok", "value": 42}
    assert mock_create.call_count == 2


def test_chat_structured_exhausts_retries():
    client = LLMClient()
    with patch.object(client._client.chat.completions, "create") as mock_create:
        mock_create.return_value = _mock_chat_response("{invalid")
        with pytest.raises(LLMStructuredOutputError):
            client.chat_structured(
                [{"role": "user", "content": "test"}],
                output_schema=TestSchema,
                max_retries=2,
            )
    assert mock_create.call_count == 3


def test_chat_structured_validation_error_exhausts_retries():
    client = LLMClient()
    missing_field = json.dumps({"name": "no_value"})
    with patch.object(client._client.chat.completions, "create") as mock_create:
        mock_create.return_value = _mock_chat_response(missing_field)
        with pytest.raises(LLMStructuredOutputError):
            client.chat_structured(
                [{"role": "user", "content": "test"}],
                output_schema=TestSchema,
                max_retries=1,
            )
    assert mock_create.call_count == 2
