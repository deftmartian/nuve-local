"""The mutable state container behind one thermostat runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from ..const import COMMAND_TIMEOUT_SECONDS
from ..models import NuveState
from .outdoor import ForecastCache, OutdoorConditions
from .persistence import PersistenceTransactions
from .records import PendingCommand, UncertainCommand
from .timers import OneShotTimer
from .tracing import RuntimeTracer


@dataclass(slots=True)
class RuntimeState:
    """Fields and plain accessors shared by every runtime layer.

    Collaborators own self-contained state: the tracer, the persistence latch,
    the liveness and bootstrap-expiry timers, and the outdoor/forecast caches.
    """

    serial: str
    control_enabled: bool = False
    paired: bool = False
    automatic_baseline_capture: bool = False
    command_timeout_seconds: float = COMMAND_TIMEOUT_SECONDS
    bootstrap_firmware_version: str | None = None
    bootstrap_technician_url: str | None = None
    contractor_url: str | None = None
    bootstrap_metadata_confirmed: bool = False
    bootstrap_no_update_confirmed: bool = False
    temp_correction_version: int | None = None
    state: NuveState = field(default_factory=NuveState)
    endpoint_counts: dict[str, int] = field(default_factory=dict)
    rejected_requests: int = 0
    contractor_info_ready: bool = False
    settings_snapshot: dict[str, Any] | None = None
    settings_revision: str | None = None
    settings_revision_floor: str | None = None
    auto_mode_snapshot: dict[str, Any] | None = None
    auto_mode_revision: str | None = None
    auto_revision_floor: str | None = None
    last_settings_poll: datetime | None = None
    last_settings_upload: datetime | None = None
    last_auto_mode_upload: datetime | None = None
    live_data_command_time: str | None = None
    last_monitor_upload: datetime | None = None
    current_temperature_observed_at: datetime | None = None
    current_temperature_source: Literal["monitor", "current_sensors", "settings"] | None = None
    uncertain_command: UncertainCommand | None = None
    bootstrap_armed_at: datetime | None = None
    bootstrap_armed_until: datetime | None = None
    bootstrap_revision: str | None = None
    bootstrap_settings_served: bool = False
    bootstrap_auto_served: bool = False
    authoritative_control_monitor_seen: bool = False
    outdoor_sources_configured: bool = False
    _listeners: set[Callable[[], None]] = field(default_factory=set)
    _liveness_timer: OneShotTimer = field(default_factory=OneShotTimer, init=False, repr=False)
    _bootstrap_timer: OneShotTimer = field(default_factory=OneShotTimer, init=False, repr=False)
    _automatic_bootstrap_task: asyncio.Task[None] | None = field(
        default=None, init=False, repr=False
    )
    _automatic_bootstrap_attempted: bool = field(default=False, init=False, repr=False)
    _pending_command: PendingCommand | None = None
    _monitor_resync_next: Literal["reset", "wake"] = "reset"
    _monitor_wake_command_time: str | None = None
    _monitor_resync_auto_companion_revision: str | None = None
    _tracer: RuntimeTracer = field(default_factory=RuntimeTracer, init=False, repr=False)
    _outdoor: OutdoorConditions = field(default_factory=OutdoorConditions, init=False, repr=False)
    _forecast: ForecastCache = field(default_factory=ForecastCache, init=False, repr=False)
    _persistence: PersistenceTransactions = field(init=False, repr=False)
    _stopped: bool = False

    @property
    def persistence_healthy(self) -> bool:
        """Return whether the last durable transaction completed cleanly."""

        return self._persistence.healthy

    @persistence_healthy.setter
    def persistence_healthy(self, value: bool) -> None:
        self._persistence.healthy = value

    @property
    def persistence_fault_latched(self) -> bool:
        """Return whether an ambiguous storage result requires a reload."""

        return self._persistence.fault_latched

    @persistence_fault_latched.setter
    def persistence_fault_latched(self, value: bool) -> None:
        self._persistence.fault_latched = value

    @property
    def persistence_recovered_from_previous(self) -> bool:
        """Return whether restored baselines came from the previous storage copy."""

        return self._persistence.recovered_from_previous

    @persistence_recovered_from_previous.setter
    def persistence_recovered_from_previous(self, value: bool) -> None:
        self._persistence.recovered_from_previous = value

    @property
    def has_settings_baseline(self) -> bool:
        """Return whether a complete device-originated settings snapshot exists."""

        return self.settings_snapshot is not None and self.settings_revision is not None

    @property
    def has_auto_mode_baseline(self) -> bool:
        """Return whether a complete device-originated auto-mode snapshot exists."""

        return self.auto_mode_snapshot is not None and self.auto_mode_revision is not None

    def settings_section(self, section: str) -> dict[str, Any] | None:
        """Return one object section of the device-originated settings baseline."""

        if self.settings_snapshot is None:
            return None
        value = self.settings_snapshot.get(section)
        return value if isinstance(value, dict) else None

    def setting(self, section: str, key: str) -> Any:
        """Return one raw value from a settings section, or None when absent."""

        values = self.settings_section(section)
        return values.get(key) if values is not None else None

    @property
    def baseline_firmware_version(self) -> str | None:
        """Return the firmware version reported inside the full device upload."""

        version = self.setting("firmware", "firmware-version")
        return version if isinstance(version, str) else None

    @property
    def command_status(self) -> str:
        """Return a non-secret status string for diagnostics and entity attributes."""

        if self._pending_command is not None:
            return "delivered" if self._pending_command.delivered else "queued"
        if self.uncertain_command is not None:
            return "outcome_uncertain"
        return "idle"

    @property
    def sanitized_event_trace(self) -> list[dict[str, Any]]:
        """Return a size-limited support timeline without protocol values."""

        return self._tracer.sanitized()

    @property
    def uncertain_outcome(self) -> bool:
        """Return whether a delivered command still has an unknown outcome."""

        return self.uncertain_command is not None

    @property
    def uncertain_kind(self) -> Literal["settings", "auto"] | None:
        """Return the unresolved command family without exposing desired values."""

        return self.uncertain_command.kind if self.uncertain_command is not None else None

    @property
    def requested_target_temperature(self) -> float | None:
        """Return an in-flight HA target without treating it as confirmed state."""

        pending = self._pending_command
        if pending is None or pending.kind != "settings":
            return None
        value = pending.desired.get("temp")
        return (
            float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
        )

    @property
    def outdoor_is_fresh(self) -> bool:
        """Return whether the projected outdoor temperature is safe to serve."""

        return self._outdoor.is_fresh

    @property
    def outdoor_temperature_c(self) -> float | None:
        """Return the last valid outdoor temperature in degrees Celsius."""

        return self._outdoor.temperature_c

    @property
    def outdoor_observed_at(self) -> datetime | None:
        """Return when the outdoor temperature was observed."""

        return self._outdoor.observed_at

    @property
    def outdoor_humidity_percent(self) -> float | None:
        """Return the last valid outdoor relative humidity."""

        return self._outdoor.humidity_percent

    @property
    def outdoor_weather(self) -> dict[str, str] | None:
        """Return the last valid outdoor weather icon and description."""

        return self._outdoor.weather

    @property
    def outdoor_location_name(self) -> str:
        """Return the outdoor source name shown on the thermostat."""

        return self._outdoor.location_name

    @property
    def outdoor_source(self) -> str:
        """Return the outdoor source kind, or ``unavailable``."""

        return self._outdoor.source

    @property
    def forecast_healthy(self) -> bool:
        """Return whether a validated forecast is available for the device."""

        return self._forecast.healthy

    @property
    def forecast_payload(self) -> dict[str, Any] | None:
        """Return the cached validated forecast payload."""

        return self._forecast.payload

    @property
    def forecast_updated_at(self) -> datetime | None:
        """Return when the forecast status last changed."""

        return self._forecast.updated_at

    @property
    def forecast_status(self) -> str:
        """Return the non-secret forecast status."""

        return self._forecast.status

    @property
    def fan_mode(self) -> int | None:
        """Return the configured FanMode enum from the saved device state."""

        value = self.setting("fan", "mode")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def fan_working_per_hour(self) -> int | None:
        """Return configured circulation minutes per hour."""

        value = self.setting("fan", "workingPerHour")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def persistence_lock(self) -> asyncio.Lock:
        """Return the lock that serializes durable baseline and journal writes."""

        return self._persistence.lock

    def async_subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to pushed state changes."""

        self._listeners.add(listener)

        def unsubscribe() -> None:
            self._listeners.discard(listener)

        return unsubscribe

    def count_endpoint(self, method: str, path: str) -> None:
        """Count an endpoint invocation without recording its values."""

        key = f"{method} {path}"
        self.endpoint_counts[key] = self.endpoint_counts.get(key, 0) + 1
