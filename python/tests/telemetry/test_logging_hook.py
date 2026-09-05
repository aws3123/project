from unittest.mock import Mock

from schemas.domain.log import NodeLog
from telemetry.hooks import LoggingTelemetryHook


def make_log(status: str = "SUCCEEDED") -> NodeLog:
    from datetime import UTC, datetime

    return NodeLog(
        task_id="t1",
        node="diff",
        input={"a": 1},
        output={"b": 2},
        duration_ms=10,
        status=status,
        timestamp=datetime.now(UTC),
    )


def test_logging_hook_records_node():
    logger = Mock()
    hook = LoggingTelemetryHook(logger=logger)
    hook.record_node(make_log())
    assert logger.info.called


def test_logging_hook_records_error():
    logger = Mock()
    hook = LoggingTelemetryHook(logger=logger)
    hook.record_error(make_log(status="FAILED"), RuntimeError("boom"))
    assert logger.error.called
