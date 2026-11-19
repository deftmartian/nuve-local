"""Command journal records shared by the runtime layers."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

CommandKind = Literal["settings", "auto"]
ResponseSender = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(slots=True)
class PendingCommand:
    """One single-flight server-to-device synchronization change."""

    kind: CommandKind
    desired: dict[str, Any]
    payload: dict[str, Any]
    future: asyncio.Future[str]
    queued_at: datetime
    queued_baseline: dict[str, Any]
    revision: str | None = None
    delivered: bool = False
    delivered_at: datetime | None = None
    coherent_echo_received_at: datetime | None = None


@dataclass(slots=True)
class UncertainCommand:
    """A delivered command whose result still needs authoritative evidence."""

    kind: CommandKind
    desired: dict[str, Any]
    # None is the durable write-ahead state: a response may be in flight, but
    # no server-clock boundary has yet been established after its body was sent.
    delivered_at: datetime | None
    revision: str | None = None


def serialize_uncertainty(uncertain: UncertainCommand) -> dict[str, Any]:
    """Return the durable journal form of an unresolved command."""

    return {
        "kind": uncertain.kind,
        "desired": copy.deepcopy(uncertain.desired),
        "delivered_at": (
            uncertain.delivered_at.astimezone(UTC).isoformat()
            if uncertain.delivered_at is not None
            else None
        ),
        "revision": uncertain.revision,
    }
