"""Size-limited runtime support timeline that never carries protocol values."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

TRACE_EVENT_LIMIT = 128


@dataclass(frozen=True, slots=True)
class RuntimeTraceEvent:
    """One size-limited runtime event without protocol values."""

    timestamp: datetime
    event: str
    family: Literal["settings", "auto", "monitor"] | None = None
    result: str | None = None
    duration_ms: int | None = None


def trace_event(
    event: str,
    *,
    family: Literal["settings", "auto", "monitor"] | None = None,
    result: str | None = None,
    duration_ms: int | None = None,
    at: datetime | None = None,
) -> RuntimeTraceEvent:
    """Build one event with a UTC timestamp."""

    timestamp = at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return RuntimeTraceEvent(
        timestamp=timestamp.astimezone(UTC),
        event=event,
        family=family,
        result=result,
        duration_ms=duration_ms,
    )


def elapsed_ms(started_at: datetime, finished_at: datetime) -> int:
    return max(0, round((finished_at - started_at).total_seconds() * 1000))


def sanitized_trace(events: Iterable[RuntimeTraceEvent]) -> list[dict[str, Any]]:
    """Return a support timeline without protocol values."""

    return [
        {
            "timestamp": item.timestamp.isoformat(),
            "event": item.event,
            "family": item.family,
            "result": item.result,
            "duration_ms": item.duration_ms,
        }
        for item in events
    ]
