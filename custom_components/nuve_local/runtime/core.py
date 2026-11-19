"""The composed runtime for one thermostat."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from ..const import LIVENESS_TIMEOUT_SECONDS
from .persistence import PersistenceTransactions
from .polling import RuntimePolling


@dataclass(slots=True)
class NuveRuntime(RuntimePolling):
    """Mutable runtime container for one thermostat.

    Behaviour is layered, each layer building only on the ones below it:
    state -> readiness -> transactions -> bootstrap -> command_lifecycle ->
    snapshots -> monitor -> polling -> this class (liveness, outdoor and
    forecast updates, shutdown).
    """

    def __post_init__(self) -> None:
        """Wire the persistence latch, then start the state-transition timeline."""

        self._persistence = PersistenceTransactions(
            tracer=self._tracer, on_fault=self._notify_listeners
        )
        self._tracer.note_control_block_reason(self.control_block_reason)

    def async_note_authenticated_contact(self, seen_at: datetime) -> None:
        """Record an authenticated request and reset the liveness timer."""

        self.state = replace(self.state, available=True, last_seen=seen_at)
        self._notify_listeners()
        self._liveness_timer.start(LIVENESS_TIMEOUT_SECONDS, self._async_mark_unavailable)

    def _async_mark_unavailable(self) -> None:
        self._liveness_timer.forget()
        if not self.state.available:
            return
        self.authoritative_control_monitor_seen = False
        self.state = replace(self.state, available=False)
        self._notify_listeners()

    def async_set_outdoor_temperature(
        self,
        temperature_c: float | None,
        name: str,
        *,
        humidity_percent: float | None = None,
        weather: dict[str, str] | None = None,
        observed_at: datetime | None = None,
        source: str = "sensor",
    ) -> None:
        """Update the cached outdoor-temperature projection."""

        self._outdoor.update(
            temperature_c,
            name,
            humidity_percent=humidity_percent,
            weather=weather,
            observed_at=observed_at,
            source=source,
        )
        self._notify_listeners()

    def async_set_forecast(
        self,
        payload: dict[str, Any] | None,
        *,
        status: str,
        updated_at: datetime | None = None,
    ) -> None:
        """Cache one already validated forecast or select the firmware-safe no-op."""

        self._forecast.update(payload, status=status, updated_at=updated_at)
        self._notify_listeners()

    async def async_shutdown(self) -> None:
        """Cancel ephemeral callbacks without erasing durable safety journals."""

        async with self._persistence.lock:
            self._stopped = True
            if self._automatic_bootstrap_task is not None:
                self._automatic_bootstrap_task.cancel()
                self._automatic_bootstrap_task = None
            self._liveness_timer.cancel()
            self._bootstrap_timer.cancel()
            if self._pending_command is not None:
                self._complete_pending("stopped")
            self._listeners.clear()
