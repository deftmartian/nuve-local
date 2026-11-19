"""Durable transaction coordinator and fail-closed persistence latch."""

from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, NoReturn

from ..errors import PersistenceUnavailableError
from .records import CommandKind
from .tracing import RuntimeTracer

PersistenceListener = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]

# Keep the historical logger name so existing Home Assistant logger filters
# for ``custom_components.nuve_local.runtime`` still apply.
_LOGGER = logging.getLogger(__package__)


@dataclass(slots=True)
class PersistenceTransactions:
    """Serialize durable writes and latch fail-closed on any ambiguous result.

    Once latched, no canonical response or transition is trusted again until a
    reload reconciles runtime state from disk.
    """

    tracer: RuntimeTracer = field(repr=False)
    on_fault: Callable[[], None] = field(repr=False)
    listener: PersistenceListener | None = field(default=None, repr=False)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    healthy: bool = True
    fault_latched: bool = False
    recovered_from_previous: bool = False

    def detached(
        self, *, tracer: RuntimeTracer, on_fault: Callable[[], None]
    ) -> PersistenceTransactions:
        """Return a copy with the same health flags, but no listener and its own lock."""

        return replace(self, tracer=tracer, on_fault=on_fault, listener=None, lock=asyncio.Lock())

    def latch_fault(self) -> None:
        """Latch persistence unhealthy and announce the state change."""

        self.healthy = False
        self.fault_latched = True
        self.on_fault()

    async def persist_candidate(
        self, candidate: dict[str, Any], *, family: CommandKind | None = None
    ) -> None:
        """Persist and latch any ambiguous storage failure fail-closed."""

        started_at = datetime.now(UTC)
        self.tracer.record("persistence", family=family, result="started", at=started_at)
        if self.listener is None:
            self.healthy = False
            self.fault_latched = True
            self.tracer.record_elapsed(
                "persistence", started_at, family=family, result="unavailable"
            )
            raise PersistenceUnavailableError("no persistence coordinator is available")
        task = asyncio.create_task(
            self.listener(copy.deepcopy(candidate)),
            name="Persist Nuve runtime transaction",
        )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as outer_cancel:
            if task.cancelled():
                self.latch_fault()
                self.tracer.record_elapsed(
                    "persistence", started_at, family=family, result="cancelled"
                )
                raise PersistenceUnavailableError(
                    "canonical persistence task was cancelled"
                ) from outer_cancel
            # The filesystem operation can continue after cancellation. Wait for
            # a definite result so runtime and disk cannot diverge silently.
            try:
                await task
            except asyncio.CancelledError as inner_cancel:
                self.latch_fault()
                self.tracer.record_elapsed(
                    "persistence", started_at, family=family, result="cancelled"
                )
                raise PersistenceUnavailableError(
                    "canonical persistence task was cancelled"
                ) from inner_cancel
            except Exception as err:
                self._fail(err, started_at, family)
            self.tracer.record_elapsed(
                "persistence", started_at, family=family, result="committed_after_cancel"
            )
            raise
        except Exception as err:
            self._fail(err, started_at, family)
        self.tracer.record_elapsed("persistence", started_at, family=family, result="committed")

    def _fail(self, err: Exception, started_at: datetime, family: CommandKind | None) -> NoReturn:
        """Latch, log and trace a storage failure, then raise the safe error."""

        self.latch_fault()
        _LOGGER.error(
            "Nuve canonical persistence transaction failed (%s): %s",
            type(err).__name__,
            err,
        )
        self.tracer.record_elapsed("persistence", started_at, family=family, result="failed")
        raise PersistenceUnavailableError from err

    async def persist_and_commit(
        self,
        candidate: dict[str, Any],
        commit: Callable[[], object],
        *,
        family: CommandKind | None,
    ) -> None:
        """Persist a prepared candidate, then expose its exact runtime transition."""

        if self.fault_latched:
            raise PersistenceUnavailableError("canonical persistence requires reload")
        cancelled = False
        try:
            await self.persist_candidate(candidate, family=family)
        except asyncio.CancelledError:
            cancelled = True
        try:
            commit()
        except Exception as err:
            # The candidate is durable but the in-memory transition is not. No
            # canonical response is safe until a reload reconciles from disk.
            self.latch_fault()
            raise PersistenceUnavailableError("canonical commit requires reload") from err
        if not self.fault_latched:
            self.healthy = True
        if cancelled:
            raise asyncio.CancelledError
