"""Unit tests for Redis-backed session memory service."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from services.memory_service import MemoryService


def _make_memory_service(mock_redis: MagicMock | None = None) -> MemoryService:
    svc = MemoryService()
    if mock_redis is not None:
        svc._settings.redis_url = "redis://localhost:6379/0"
    return svc


@patch("services.memory_service.get_redis_client")
def test_load_session_memory_returns_empty_when_no_key(mock_get_redis):
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    mock_get_redis.return_value = mock_redis

    svc = _make_memory_service(mock_redis)
    result = svc.load_session_memory("session-1")

    assert result == {}
    mock_redis.get.assert_called_once_with("memory:session-1")


@patch("services.memory_service.get_redis_client")
def test_load_session_memory_returns_context_when_key_exists(mock_get_redis):
    mock_redis = MagicMock()
    snapshot = {
        "memory_context": {"business_risk_level": "high", "violation_count": 3},
        "memory_version": "v2",
        "updated_at": "2026-06-27T10:00:00",
    }
    mock_redis.get.return_value = json.dumps(snapshot)
    mock_get_redis.return_value = mock_redis

    svc = _make_memory_service(mock_redis)
    result = svc.load_session_memory("session-1")

    assert result == {"business_risk_level": "high", "violation_count": 3}


@patch("services.memory_service.get_redis_client")
def test_load_session_memory_returns_empty_for_none_session(mock_get_redis):
    svc = _make_memory_service()
    assert svc.load_session_memory(None) == {}
    assert svc.load_session_memory("") == {}
    mock_get_redis.assert_not_called()


@patch("services.memory_service.get_redis_client")
def test_save_session_memory_writes_to_redis(mock_get_redis):
    mock_redis = MagicMock()
    mock_get_redis.return_value = mock_redis

    svc = _make_memory_service(mock_redis)
    svc.save_session_memory(
        "session-1",
        {"business_risk_level": "medium", "violation_count": 1},
        version="v3",
    )

    mock_redis.setex.assert_called_once()
    call_args = mock_redis.setex.call_args
    key = call_args[0][0]
    assert key == "memory:session-1"
    ttl = call_args[0][1]
    assert ttl == 7200
    payload = json.loads(call_args[0][2])
    assert payload["memory_context"] == {
        "business_risk_level": "medium",
        "violation_count": 1,
    }
    assert payload["memory_version"] == "v3"
    assert "updated_at" in payload


@patch("services.memory_service.get_redis_client")
def test_save_session_memory_skips_empty_updates(mock_get_redis):
    mock_redis = MagicMock()
    mock_get_redis.return_value = mock_redis

    svc = _make_memory_service(mock_redis)
    svc.save_session_memory("session-1", {})
    mock_redis.setex.assert_not_called()

    svc.save_session_memory("session-1", None)  # type: ignore[arg-type]
    mock_redis.setex.assert_not_called()


@patch("services.memory_service.get_redis_client")
def test_save_session_memory_skips_none_session(mock_get_redis):
    svc = _make_memory_service()
    svc.save_session_memory(None, {"key": "val"})
    mock_get_redis.assert_not_called()


@patch("services.memory_service.get_redis_client")
def test_delete_session_memory(mock_get_redis):
    mock_redis = MagicMock()
    mock_get_redis.return_value = mock_redis

    svc = _make_memory_service(mock_redis)
    svc.delete_session_memory("session-1")

    mock_redis.delete.assert_called_once_with("memory:session-1")


@patch("services.memory_service.get_redis_client")
def test_load_gracefully_handles_redis_down(mock_get_redis):
    mock_redis = MagicMock()
    mock_redis.get.side_effect = ConnectionError("redis is down")
    mock_get_redis.return_value = mock_redis

    svc = _make_memory_service(mock_redis)
    result = svc.load_session_memory("session-1")

    assert result == {}


@patch("services.memory_service.get_redis_client")
def test_save_gracefully_handles_redis_down(mock_get_redis):
    mock_redis = MagicMock()
    mock_redis.setex.side_effect = ConnectionError("redis is down")
    mock_get_redis.return_value = mock_redis

    svc = _make_memory_service(mock_redis)
    # Should not raise
    svc.save_session_memory("session-1", {"key": "val"})
