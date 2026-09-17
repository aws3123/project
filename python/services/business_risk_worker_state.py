from __future__ import annotations

from contextlib import contextmanager
from threading import Lock

from app.utils import safe_detail


class BusinessRiskWorkerState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._inflight_count = 0
        self._last_error: str | None = None

    @contextmanager
    def track_run(self):
        with self._lock:
            self._inflight_count += 1
        try:
            yield
        except Exception as exc:
            with self._lock:
                self._last_error = safe_detail(exc)
            raise
        finally:
            with self._lock:
                self._inflight_count = max(0, self._inflight_count - 1)

    def snapshot(self) -> dict[str, int | str | None]:
        with self._lock:
            return {
                "inflight_count": self._inflight_count,
                "last_error": self._last_error,
            }
