"""ResultService unit tests."""

from __future__ import annotations

from repositories.result_repository import InMemoryResultRepository
from services.result_service import ResultService


def test_save_and_get_result():
    repo = InMemoryResultRepository()
    service = ResultService(repo)

    default = service.build_default_result("task-1")
    service.save(default)

    stored = service.get("task-1")
    assert stored is not None
    assert stored.riskScore == default.riskScore
