"""Support-timeline collaborator owned by one runtime."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from ..trace import (
    TRACE_EVENT_LIMIT,
    RuntimeTraceEvent,
    elapsed_ms,
    sanitized_trace,
    trace_event,
)

TraceFamily = Literal["settings", "auto", "monitor"]


@dataclass(slots=True)
class RuntimeTracer:
    """Record a bounded, value-free state-transition timeline.

    A disabled tracer records nothing; monitor shadows use one so a prepared
    but uncommitted transaction never reaches the support timeline.
    """

    enabled: bool = True
    _events: deque[RuntimeTraceEvent] = field(
        default_factory=lambda: deque(maxlen=TRACE_EVENT_LIMIT)
    )
    _last_control_block_reason: str | None = None

    def record(
        self,
        event: str,
        *,
        family: TraceFamily | None = None,
        result: str | None = None,
        duration_ms: int | None = None,
        at: datetime | None = None,
    ) -> None:
        """Append one event when tracing is enabled."""

        if not self.enabled:
            return
        self._events.append(
            trace_event(event, family=family, result=result, duration_ms=duration_ms, at=at)
        )

    def record_elapsed(
        self,
        event: str,
        started_at: datetime,
        *,
        family: TraceFamily | None,
        result: str,
    ) -> None:
        """Append one event stamped now, with its duration since ``started_at``."""

        finished_at = datetime.now(UTC)
        self.record(
            event,
            family=family,
            result=result,
            duration_ms=elapsed_ms(started_at, finished_at),
            at=finished_at,
        )

    def note_control_block_reason(self, reason: str) -> None:
        """Record the control block reason only when it changed."""

        if reason == self._last_control_block_reason:
            return
        self._last_control_block_reason = reason
        self.record("control_block_reason", result=reason)

    def sanitized(self) -> list[dict[str, Any]]:
        """Return the size-limited timeline without protocol values."""

        return sanitized_trace(self._events)
