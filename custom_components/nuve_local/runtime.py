"""Runtime state shared by the Nuve listener and Home Assistant entities."""

from __future__ import annotations

import asyncio
import copy
import logging
import math
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from .const import (
    BACKLIGHT_KEYS,
    BOOTSTRAP_FIRMWARE_ALLOWLIST,
    BOOTSTRAP_WINDOW_SECONDS,
    COMMAND_TIMEOUT_SECONDS,
    DISPLAY_SETTINGS_KEYS,
    FAN_MODE_IDS,
    LIVENESS_TIMEOUT_SECONDS,
    MAX_AUTO_TEMPERATURE,
    MAX_DEVICE_TEMPERATURE,
    MAX_FAN_WORKING_PER_HOUR,
    MAX_TARGET_TEMPERATURE,
    MIN_AUTO_TEMPERATURE,
    MIN_DEVICE_TEMPERATURE,
    MIN_FAN_WORKING_PER_HOUR,
    MIN_TARGET_TEMPERATURE,
    MONITOR_FUTURE_SKEW_SECONDS,
    MONITOR_MAX_AGE_SECONDS,
    OUTDOOR_MAX_AGE_SECONDS,
    TARGET_TEMPERATURE_STEP,
    TEMP_CORRECTION_VERSIONS_BY_FIRMWARE,
)
from .models import NuveMode, NuveState, NuveSystemType
from .protocol import (
    NuveProtocolError,
    next_revision,
    normalize_night_mode_time,
    parse_auto_mode_baseline,
    render_auto_mode_bootstrap_response,
    render_auto_mode_response,
    render_monitor_reset_response,
    render_monitor_wake_response,
    render_settings_bootstrap_response,
    render_settings_response,
)

CONTROL_SAFE_MODES = frozenset({NuveMode.COOL, NuveMode.HEAT, NuveMode.AUTO, NuveMode.OFF})
ACTIVE_SCHEDULE_TYPES = frozenset({0, 1, 2, 3, 8})
NO_SCHEDULE_TYPE = 9
SYSTEM_TYPE_NAMES = {
    NuveSystemType.TRADITIONAL: "traditional",
    NuveSystemType.HEAT_PUMP: "heat_pump",
    NuveSystemType.COOLING_ONLY: "cooling",
    NuveSystemType.HEATING_ONLY: "heating",
    NuveSystemType.DUAL_FUEL_HEATING: "dual_fuel_heating",
}
ResponseSender = Callable[[dict[str, Any]], Awaitable[None]]
TRACE_EVENT_LIMIT = 128
_LOGGER = logging.getLogger(__name__)


class NuveControlError(Exception):
    """Base class for safe control failures."""


class ControlDisabledError(NuveControlError):
    """Control was not explicitly enabled."""


class ControlNotReadyError(NuveControlError):
    """The device has not provided enough fresh state for control."""


class ControlBusyError(NuveControlError):
    """Another device command is already active."""


class ControlStateChangedError(NuveControlError):
    """A local edit superseded a queued command before delivery."""


class CommandTimeoutError(NuveControlError):
    """The device did not fetch the command before the deadline."""


class CommandOutcomeUncertainError(NuveControlError):
    """The device fetched the command but did not confirm its result."""


class RuntimeStoppedError(NuveControlError):
    """The integration stopped while a command was active."""


class PersistenceUnavailableError(NuveControlError):
    """Canonical state cannot be trusted after a persistence failure."""


@dataclass(slots=True)
class PendingCommand:
    """One single-flight server-to-device synchronization change."""

    kind: Literal["settings", "auto"]
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

    kind: Literal["settings", "auto"]
    desired: dict[str, Any]
    # None is the durable write-ahead state: a response may be in flight, but
    # no server-clock boundary has yet been established after its body was sent.
    delivered_at: datetime | None
    revision: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeTraceEvent:
    """One size-limited runtime event without protocol values."""

    timestamp: datetime
    event: str
    family: Literal["settings", "auto", "monitor"] | None = None
    result: str | None = None
    duration_ms: int | None = None


@dataclass(slots=True)
class NuveRuntime:
    """Mutable runtime container for one thermostat."""

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
    server: Any = None
    endpoint_counts: dict[str, int] = field(default_factory=dict)
    rejected_requests: int = 0
    outdoor_temperature_c: float | None = None
    outdoor_observed_at: datetime | None = None
    outdoor_humidity_percent: float | None = None
    outdoor_weather: dict[str, str] | None = None
    outdoor_location_name: str = "Local outdoor sensor"
    outdoor_source: str = "unavailable"
    forecast_payload: dict[str, Any] | None = None
    forecast_updated_at: datetime | None = None
    forecast_status: str = "not_configured"
    contractor_info_ready: bool = False
    settings_snapshot: dict[str, Any] | None = None
    settings_revision: str | None = None
    settings_revision_floor: str | None = None
    auto_mode_snapshot: dict[str, Any] | None = None
    auto_mode_revision: str | None = None
    auto_revision_floor: str | None = None
    last_settings_poll: datetime | None = None
    last_auto_mode_poll: datetime | None = None
    last_settings_upload: datetime | None = None
    last_auto_mode_upload: datetime | None = None
    live_data_command_time: str | None = None
    last_monitor_upload: datetime | None = None
    current_temperature_observed_at: datetime | None = None
    current_temperature_source: Literal["monitor", "current_sensors", "settings"] | None = None
    uncertain_command: UncertainCommand | None = None
    persistence_healthy: bool = True
    persistence_fault_latched: bool = False
    persistence_recovered_from_previous: bool = False
    bootstrap_armed_at: datetime | None = None
    bootstrap_armed_until: datetime | None = None
    bootstrap_revision: str | None = None
    bootstrap_settings_served: bool = False
    bootstrap_auto_served: bool = False
    authoritative_control_monitor_seen: bool = False
    _listeners: set[Callable[[], None]] = field(default_factory=set)
    _liveness_timer: asyncio.TimerHandle | None = None
    _bootstrap_timer: asyncio.TimerHandle | None = None
    _automatic_bootstrap_task: asyncio.Task[None] | None = field(
        default=None, init=False, repr=False
    )
    _automatic_bootstrap_attempted: bool = field(default=False, init=False, repr=False)
    _pending_command: PendingCommand | None = None
    _monitor_resync_next: Literal["reset", "wake"] = "reset"
    _monitor_wake_command_time: str | None = None
    _monitor_resync_auto_companion_revision: str | None = None
    _persistence_listener: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None
    _transaction_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _event_trace: deque[RuntimeTraceEvent] = field(
        default_factory=lambda: deque(maxlen=TRACE_EVENT_LIMIT), init=False, repr=False
    )
    _last_traced_control_block_reason: str | None = field(default=None, init=False, repr=False)
    _trace_enabled: bool = field(default=True, init=False, repr=False)
    _stopped: bool = False

    def __post_init__(self) -> None:
        """Start the state-transition timeline at construction."""

        reason = self.control_block_reason
        self._last_traced_control_block_reason = reason
        self._trace_event("control_block_reason", result=reason)

    @property
    def has_settings_baseline(self) -> bool:
        """Return whether a complete device-originated settings snapshot exists."""

        return self.settings_snapshot is not None and self.settings_revision is not None

    @property
    def has_auto_mode_baseline(self) -> bool:
        """Return whether a complete device-originated auto-mode snapshot exists."""

        return self.auto_mode_snapshot is not None and self.auto_mode_revision is not None

    @property
    def baseline_firmware_version(self) -> str | None:
        """Return the firmware version reported inside the full device upload."""

        if self.settings_snapshot is None:
            return None
        firmware = self.settings_snapshot.get("firmware")
        if not isinstance(firmware, dict):
            return None
        version = firmware.get("firmware-version")
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

        return [
            {
                "timestamp": item.timestamp.isoformat(),
                "event": item.event,
                "family": item.family,
                "result": item.result,
                "duration_ms": item.duration_ms,
            }
            for item in self._event_trace
        ]

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
    def bootstrap_status(self) -> str:
        """Return the non-secret initial-baseline bootstrap state."""

        if self.has_settings_baseline:
            return "complete"
        if self.bootstrap_armed_until is None:
            return "idle"
        if self.bootstrap_auto_served:
            return "fetch_unlocked"
        if self.bootstrap_settings_served:
            return "settings_served"
        return "armed"

    @property
    def can_arm_bootstrap(self) -> bool:
        """Return whether every explicit compatibility-bridge precondition is met."""

        return (
            not self._stopped
            and self.paired
            and self.persistence_healthy
            and self._persistence_listener is not None
            and self.state.available
            and self.monitor_is_fresh
            and not self.has_settings_baseline
            and not self.control_enabled
            and self.bootstrap_armed_until is None
            and self._pending_command is None
            and self.bootstrap_metadata_confirmed
            and self.bootstrap_no_update_confirmed
            and self._valid_technician_url(self.bootstrap_technician_url)
            and self.bootstrap_firmware_version in BOOTSTRAP_FIRMWARE_ALLOWLIST
        )

    @property
    def can_enable_control(self) -> bool:
        """Return whether fresh canonical and monitor evidence permits control."""

        return self.control_authority_block_reason is None

    @property
    def control_authority_block_reason(self) -> str | None:
        """Return the first non-secret reason canonical writes are unsafe."""

        if canonical_reason := self.canonical_response_block_reason:
            return canonical_reason
        if not self.state.available:
            return "device_unavailable"
        if not self.has_auto_mode_baseline:
            return "auto_baseline_missing"
        if not self.authoritative_control_monitor_seen:
            return "monitor_authority_missing"
        if not self.monitor_is_fresh:
            return "monitor_stale"
        if self.state.records_received < 1:
            return "monitor_records_missing"
        if self.state.current_temperature is None:
            return "current_temperature_missing"
        if self.state.target_temperature is None:
            return "target_temperature_missing"
        if self.state.mode not in CONTROL_SAFE_MODES:
            return "unsupported_mode"
        assert self.last_monitor_upload is not None
        if (
            self.last_settings_upload is not None
            and self.last_monitor_upload < self.last_settings_upload
        ):
            return "settings_newer_than_monitor"
        assert self.settings_snapshot is not None
        assert self.auto_mode_snapshot is not None
        if not self._live_state_matches_baselines():
            return "baseline_mismatch"
        return None

    @property
    def control_block_reason(self) -> str:
        """Return why Home Assistant control is closed or ``ready``."""

        if not self.control_enabled:
            return "control_disabled"
        pending = self._pending_command
        if pending is not None:
            return (
                "command_delivered_awaiting_confirmation"
                if pending.delivered
                else "command_queued_awaiting_fetch"
            )
        if self.uncertain_command is not None:
            return "command_outcome_uncertain"
        return self.control_authority_block_reason or "ready"

    @property
    def control_ready(self) -> bool:
        """Return whether the integration can accept a new HVAC write now."""

        return (
            self.control_enabled
            and self.can_enable_control
            and self._pending_command is None
            and self.uncertain_command is None
        )

    @property
    def canonical_live_consistency_ready(self) -> bool:
        """Return whether a normal whole-snapshot echo is current, not restored."""

        return (
            self.state.available
            and self.has_settings_baseline
            and self.has_auto_mode_baseline
            and self.authoritative_control_monitor_seen
            and self.monitor_is_fresh
            and self._live_state_matches_baselines()
        )

    @property
    def canonical_metadata_ready(self) -> bool:
        """Return whether every non-uploaded canonical setting is exact."""

        firmware_version = self.bootstrap_firmware_version
        if firmware_version is None:
            return False
        allowed = TEMP_CORRECTION_VERSIONS_BY_FIRMWARE.get(firmware_version)
        if allowed is None:
            return False
        value = self.temp_correction_version
        return isinstance(value, int) and not isinstance(value, bool) and value in allowed

    @property
    def canonical_response_safe(self) -> bool:
        """Return whether a whole desired-state echo is firmware-safe."""

        return self.canonical_response_block_reason is None

    @property
    def canonical_response_block_reason(self) -> str | None:
        """Return the exact non-secret prerequisite blocking a canonical echo."""

        if not self.paired:
            return "not_paired"
        if self.persistence_fault_latched:
            return "persistence_fault_latched"
        if not self.persistence_healthy:
            return "persistence_unhealthy"
        if self._persistence_listener is None:
            return "persistence_listener_missing"
        if not self.has_settings_baseline:
            return "settings_baseline_missing"
        if not self.bootstrap_metadata_confirmed:
            return "metadata_not_confirmed"
        if not self.bootstrap_no_update_confirmed:
            return "update_state_not_confirmed"
        if not self._valid_technician_url(self.bootstrap_technician_url):
            return "technician_url_invalid"
        if self.bootstrap_firmware_version not in BOOTSTRAP_FIRMWARE_ALLOWLIST:
            return "firmware_unsupported"
        if self.baseline_firmware_version != self.bootstrap_firmware_version:
            return "firmware_baseline_mismatch"
        if not self.canonical_metadata_ready:
            return "canonical_metadata_invalid"
        return None

    @property
    def monitor_is_fresh(self) -> bool:
        """Return whether telemetry was received recently enough to expose as live."""

        if (
            self.last_monitor_upload is None
            or self.state.sample_time is None
            or self.state.records_received < 1
        ):
            return False
        now = datetime.now(UTC)
        upload_age = (now - self.last_monitor_upload).total_seconds()
        sample_age = (now - self.state.sample_time).total_seconds()
        return (
            0 <= upload_age <= MONITOR_MAX_AGE_SECONDS
            and -MONITOR_FUTURE_SKEW_SECONDS <= sample_age <= MONITOR_MAX_AGE_SECONDS
        )

    @property
    def outdoor_is_fresh(self) -> bool:
        """Return whether the projected outdoor temperature is safe to serve."""

        if self.outdoor_temperature_c is None or self.outdoor_observed_at is None:
            return False
        age = (datetime.now(UTC) - self.outdoor_observed_at).total_seconds()
        return 0 <= age <= OUTDOOR_MAX_AGE_SECONDS

    @property
    def forecast_healthy(self) -> bool:
        """Return whether a validated forecast is available for the device."""

        return self.forecast_payload is not None and self.forecast_status == "ok"

    @property
    def fan_mode(self) -> int | None:
        """Return the configured FanMode enum from the saved device state."""

        fan = self.settings_snapshot.get("fan") if self.settings_snapshot is not None else None
        value = fan.get("mode") if isinstance(fan, dict) else None
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def fan_working_per_hour(self) -> int | None:
        """Return configured circulation minutes per hour."""

        fan = self.settings_snapshot.get("fan") if self.settings_snapshot is not None else None
        value = fan.get("workingPerHour") if isinstance(fan, dict) else None
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def async_set_paired(self) -> None:
        """Mark token pairing complete without retaining the bearer token."""

        self.paired = True
        self._notify_listeners()

    def async_set_persistence_listener(
        self, listener: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a callback used when uncertainty changes outside a request."""

        self._persistence_listener = listener
        self._schedule_automatic_bootstrap_if_ready()

    @property
    def automatic_bootstrap_attempted(self) -> bool:
        """Return whether this runtime already started its one automatic attempt."""

        return self._automatic_bootstrap_attempted

    def _schedule_automatic_bootstrap_if_ready(self) -> None:
        """Start at most one proven bootstrap window when every gate is ready."""

        if (
            not self.automatic_baseline_capture
            or self._automatic_bootstrap_attempted
            or self._automatic_bootstrap_task is not None
            or not self.can_arm_bootstrap
        ):
            return
        self._automatic_bootstrap_attempted = True
        self._automatic_bootstrap_task = asyncio.create_task(
            self._async_automatic_bootstrap(),
            name="Arm automatic Nuve baseline capture",
        )

    async def _async_automatic_bootstrap(self) -> None:
        """Run one non-retrying automatic baseline-capture attempt."""

        try:
            await self.async_arm_baseline_bootstrap(armed_at=datetime.now(UTC))
        except ControlNotReadyError:
            _LOGGER.debug("Nuve automatic baseline capture lost readiness before arming")
        except PersistenceUnavailableError:
            _LOGGER.warning("Nuve automatic baseline capture could not be persisted")
        finally:
            self._automatic_bootstrap_task = None

    async def _async_persist_candidate(self, candidate: dict[str, Any]) -> None:
        """Persist and latch any ambiguous storage failure fail-closed."""

        started_at = datetime.now(UTC)
        family = self._pending_command.kind if self._pending_command is not None else None
        self._trace_event("persistence", family=family, result="started", at=started_at)
        if self._persistence_listener is None:
            self.persistence_healthy = False
            self.persistence_fault_latched = True
            self._trace_elapsed_event(
                "persistence", started_at, family=family, result="unavailable"
            )
            raise PersistenceUnavailableError("no persistence coordinator is available")
        task = asyncio.create_task(
            self._persistence_listener(copy.deepcopy(candidate)),
            name="Persist Nuve runtime transaction",
        )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as outer_cancel:
            if task.cancelled():
                self._latch_persistence_fault()
                self._trace_elapsed_event(
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
                self._latch_persistence_fault()
                self._trace_elapsed_event(
                    "persistence", started_at, family=family, result="cancelled"
                )
                raise PersistenceUnavailableError(
                    "canonical persistence task was cancelled"
                ) from inner_cancel
            except Exception as err:
                self._latch_persistence_fault()
                _LOGGER.error(
                    "Nuve canonical persistence transaction failed (%s): %s",
                    type(err).__name__,
                    err,
                )
                self._trace_elapsed_event("persistence", started_at, family=family, result="failed")
                raise PersistenceUnavailableError from err
            self._trace_elapsed_event(
                "persistence", started_at, family=family, result="committed_after_cancel"
            )
            raise
        except Exception as err:
            self._latch_persistence_fault()
            _LOGGER.error(
                "Nuve canonical persistence transaction failed (%s): %s",
                type(err).__name__,
                err,
            )
            self._trace_elapsed_event("persistence", started_at, family=family, result="failed")
            raise PersistenceUnavailableError from err
        self._trace_elapsed_event("persistence", started_at, family=family, result="committed")

    async def _async_persist_and_commit(
        self, candidate: dict[str, Any], commit: Callable[[], None]
    ) -> None:
        """Persist a prepared candidate, then expose its exact runtime transition."""

        if self.persistence_fault_latched:
            raise PersistenceUnavailableError("canonical persistence requires reload")
        cancelled = False
        try:
            await self._async_persist_candidate(candidate)
        except asyncio.CancelledError:
            cancelled = True
        try:
            commit()
        except Exception as err:
            # The candidate is durable but the in-memory transition is not. No
            # canonical response is safe until a reload reconciles from disk.
            self._latch_persistence_fault()
            raise PersistenceUnavailableError("canonical commit requires reload") from err
        if not self.persistence_fault_latched:
            self.persistence_healthy = True
        if cancelled:
            raise asyncio.CancelledError

    def _latch_persistence_fault(self) -> None:
        self.persistence_healthy = False
        self.persistence_fault_latched = True
        self._notify_listeners()

    async def async_arm_baseline_bootstrap(self, *, armed_at: datetime) -> None:
        """Durably arm the explicitly requested one-shot compatibility bridge."""

        async with self._transaction_lock:
            if self.has_settings_baseline:
                return
            if not self.can_arm_bootstrap:
                raise ControlNotReadyError
            prior = self._latest_revision(
                self._latest_revision(self.settings_revision, self.settings_revision_floor),
                self._latest_revision(self.auto_mode_revision, self.auto_revision_floor),
            )
            revision = next_revision(prior, now=armed_at)
            expires_at = armed_at + timedelta(seconds=BOOTSTRAP_WINDOW_SECONDS)
            candidate = self.persistent_baselines()
            candidate["settings_revision_floor"] = revision
            candidate["auto_revision_floor"] = revision
            candidate["bootstrap"] = {
                "revision": revision,
                "armed_at": armed_at.astimezone(UTC).isoformat(),
                "expires_at": expires_at.astimezone(UTC).isoformat(),
                "settings_served": False,
                "auto_served": False,
            }

            def commit() -> None:
                self._clear_bootstrap()
                self.bootstrap_armed_at = armed_at
                self.bootstrap_armed_until = expires_at
                self.bootstrap_revision = revision
                self.settings_revision_floor = revision
                self.auto_revision_floor = revision
                self._schedule_bootstrap_expiry(expires_at)
                self._notify_listeners()

            await self._async_persist_and_commit(candidate, commit)

    def _bootstrap_active(self, now: datetime) -> bool:
        return (
            not self.has_settings_baseline
            and self.bootstrap_armed_until is not None
            and now <= self.bootstrap_armed_until
        )

    def _schedule_bootstrap_expiry(self, expires_at: datetime) -> None:
        if self._bootstrap_timer is not None:
            self._bootstrap_timer.cancel()
        delay = max(0.0, (expires_at - datetime.now(UTC)).total_seconds())
        self._bootstrap_timer = asyncio.get_running_loop().call_later(
            delay,
            lambda: asyncio.create_task(
                self._async_expire_bootstrap(), name="Expire Nuve bootstrap journal"
            ),
        )

    async def _async_expire_bootstrap(self) -> None:
        async with self._transaction_lock:
            self._bootstrap_timer = None
            if self._stopped or self.has_settings_baseline or self.bootstrap_armed_until is None:
                return
            if datetime.now(UTC) < self.bootstrap_armed_until:
                self._schedule_bootstrap_expiry(self.bootstrap_armed_until)
                return
            candidate = self.persistent_baselines()
            candidate.pop("bootstrap", None)

            def commit() -> None:
                self._clear_bootstrap(cancel_timer=False)
                self._notify_listeners()

            await self._async_persist_and_commit(candidate, commit)

    async def _async_clear_expired_bootstrap_locked(self, now: datetime) -> None:
        """Remove an expired durable journal while the transaction lock is held."""

        if (
            self.has_settings_baseline
            or self.bootstrap_armed_until is None
            or now <= self.bootstrap_armed_until
        ):
            return
        candidate = self.persistent_baselines()
        candidate.pop("bootstrap", None)

        def commit() -> None:
            self._clear_bootstrap()
            self._notify_listeners()

        await self._async_persist_and_commit(candidate, commit)

    def _clear_bootstrap(self, *, cancel_timer: bool = True) -> None:
        if cancel_timer and self._bootstrap_timer is not None:
            self._bootstrap_timer.cancel()
        self._bootstrap_timer = None
        self.bootstrap_armed_until = None
        self.bootstrap_armed_at = None
        self.bootstrap_revision = None
        self.bootstrap_settings_served = False
        self.bootstrap_auto_served = False

    def _notify_listeners(self) -> None:
        self._trace_control_block_transition()
        for listener in tuple(self._listeners):
            listener()
        self._schedule_automatic_bootstrap_if_ready()

    def async_update_state(self, state: NuveState) -> None:
        """Replace state and notify entities from the Home Assistant event loop."""

        self.state = state
        self._notify_listeners()

    def _note_monitor_upload(self, received_at: datetime) -> None:
        """Advance monitor liveness and expire authority after a telemetry gap."""

        previous_monitor_upload = self.last_monitor_upload
        self.last_monitor_upload = received_at
        if (
            previous_monitor_upload is not None
            and received_at - previous_monitor_upload > timedelta(seconds=MONITOR_MAX_AGE_SECONDS)
        ):
            self.authoritative_control_monitor_seen = False

    def _monitor_sample_is_current(self, state: NuveState, received_at: datetime) -> bool:
        """Reject missing, buffered, future, and out-of-order monitor samples."""

        sample_time = state.sample_time
        return not (
            sample_time is None
            or sample_time.tzinfo is None
            or sample_time > received_at + timedelta(seconds=MONITOR_FUTURE_SKEW_SECONDS)
            or sample_time < received_at - timedelta(seconds=MONITOR_MAX_AGE_SECONDS)
            or (self.state.sample_time is not None and sample_time <= self.state.sample_time)
        )

    def _monitor_fields(
        self, state: NuveState, *, sample_time: datetime
    ) -> tuple[dict[str, Any], bool]:
        """Build a full or incremental monitor merge without mutating state."""

        current = self.state
        monitor_fields = {
            "sample_time": sample_time,
            "current_temperature": state.current_temperature,
            "current_humidity": state.current_humidity,
            "target_temperature": state.target_temperature,
            "target_humidity": state.target_humidity,
            "auto_temperature_low": state.auto_temperature_low,
            "auto_temperature_high": state.auto_temperature_high,
            "mcu_temperature": state.mcu_temperature,
            "air_pressure": state.air_pressure,
            "air_quality_level": state.air_quality_level,
            "cooling_stage": state.cooling_stage,
            "heating_stage": state.heating_stage,
            "fan_active": state.fan_active,
            "led_active": state.led_active,
            "system_type": state.system_type,
            "mode": state.mode,
            "online": state.online,
            "schedule_type": state.schedule_type,
        }
        preserve_newer_temperature = (
            self.current_temperature_observed_at is not None
            and sample_time <= self.current_temperature_observed_at
        )
        if preserve_newer_temperature:
            # Settings and current-sensor uploads carry the same rounded room
            # value as monitor f4, but have no embedded device timestamp. A
            # buffered monitor packet must not roll either newer observation
            # back merely because it arrived later over HTTP.
            monitor_fields["current_temperature"] = current.current_temperature
        if not state.monitor_is_sync:
            for key, value in tuple(monitor_fields.items()):
                if value is None:
                    monitor_fields[key] = getattr(current, key)
        return monitor_fields, preserve_newer_temperature

    def _update_full_monitor_authority(self, state: NuveState) -> None:
        """Recompute whole-snapshot control authority only for a full monitor."""

        if not state.monitor_is_sync:
            return
        self.authoritative_control_monitor_seen = bool(
            state.available
            and state.target_temperature is not None
            and self._valid_humidity(state.target_humidity)
            and state.mode is not None
            and self._valid_auto_pair(state.auto_temperature_low, state.auto_temperature_high)
            and state.system_type in SYSTEM_TYPE_NAMES
        )

    def _merge_monitor_state_in_place(self, state: NuveState) -> bool:
        """Merge one monitor payload into this runtime or an isolated shadow."""

        current = self.state
        received_at = state.last_seen or datetime.now(UTC)
        self._note_monitor_upload(received_at)
        if not self._monitor_sample_is_current(state, received_at):
            # Authentication/liveness is independent from telemetry authority.
            self.async_update_state(
                replace(
                    current,
                    available=state.available or current.available,
                    last_seen=received_at,
                )
            )
            return False

        sample_time = state.sample_time
        assert sample_time is not None
        monitor_fields, preserve_newer_temperature = self._monitor_fields(
            state, sample_time=sample_time
        )
        raw_fixed32 = (
            state.raw_fixed32
            if state.monitor_is_sync
            else {**current.raw_fixed32, **state.raw_fixed32}
        )
        raw_varints = (
            state.raw_varints
            if state.monitor_is_sync
            else {**current.raw_varints, **state.raw_varints}
        )
        self.async_update_state(
            replace(
                current,
                available=state.available,
                last_seen=state.last_seen or current.last_seen,
                **monitor_fields,
                monitor_is_sync=state.monitor_is_sync,
                raw_fixed32=raw_fixed32,
                raw_varints=raw_varints,
                records_received=current.records_received + state.records_received,
            )
        )
        if not preserve_newer_temperature and state.current_temperature is not None:
            self.current_temperature_observed_at = sample_time
            self.current_temperature_source = "monitor"
        self._update_full_monitor_authority(state)
        confirmed = self._confirm_from_monitor(state)
        persistent_changed = self._merge_monitor_into_baselines(state)
        uncertainty_cleared = self._resolve_uncertainty_from_monitor(state)
        return confirmed or persistent_changed or uncertainty_cleared

    def _monitor_shadow(self) -> tuple[NuveRuntime, asyncio.Future[str] | None]:
        """Build an isolated copy for preparing a monitor transaction."""

        shadow = copy.copy(self)
        shadow.state = copy.deepcopy(self.state)
        shadow.settings_snapshot = copy.deepcopy(self.settings_snapshot)
        shadow.auto_mode_snapshot = copy.deepcopy(self.auto_mode_snapshot)
        shadow.uncertain_command = copy.deepcopy(self.uncertain_command)
        shadow._listeners = set()
        shadow._liveness_timer = None
        shadow._bootstrap_timer = None
        shadow._persistence_listener = None
        shadow._transaction_lock = asyncio.Lock()
        shadow._event_trace = deque(maxlen=TRACE_EVENT_LIMIT)
        shadow._trace_enabled = False
        dummy_future: asyncio.Future[str] | None = None
        pending = self._pending_command
        if pending is None:
            shadow._pending_command = None
        else:
            dummy_future = asyncio.get_running_loop().create_future()
            shadow._pending_command = PendingCommand(
                kind=pending.kind,
                desired=copy.deepcopy(pending.desired),
                payload=copy.deepcopy(pending.payload),
                future=dummy_future,
                queued_at=pending.queued_at,
                queued_baseline=copy.deepcopy(pending.queued_baseline),
                revision=pending.revision,
                delivered=pending.delivered,
                delivered_at=pending.delivered_at,
                coherent_echo_received_at=pending.coherent_echo_received_at,
            )
        return shadow, dummy_future

    def _commit_monitor_shadow(
        self,
        shadow: NuveRuntime,
        *,
        shadow_future: asyncio.Future[str] | None,
    ) -> None:
        """Expose a verified monitor plan and resolve its waiter last."""

        real_pending = self._pending_command
        shadow_pending = shadow._pending_command
        pending_result = (
            shadow_future.result() if shadow_future is not None and shadow_future.done() else None
        )

        self.state = copy.deepcopy(shadow.state)
        self.last_monitor_upload = shadow.last_monitor_upload
        self.settings_snapshot = copy.deepcopy(shadow.settings_snapshot)
        self.settings_revision = shadow.settings_revision
        self.settings_revision_floor = shadow.settings_revision_floor
        self.auto_mode_snapshot = copy.deepcopy(shadow.auto_mode_snapshot)
        self.auto_mode_revision = shadow.auto_mode_revision
        self.auto_revision_floor = shadow.auto_revision_floor
        self.live_data_command_time = shadow.live_data_command_time
        self.uncertain_command = copy.deepcopy(shadow.uncertain_command)
        self.authoritative_control_monitor_seen = shadow.authoritative_control_monitor_seen
        self.current_temperature_observed_at = shadow.current_temperature_observed_at
        self.current_temperature_source = shadow.current_temperature_source

        if real_pending is not None:
            if shadow_pending is None:
                self._pending_command = None
            else:
                real_pending.payload = copy.deepcopy(shadow_pending.payload)
                real_pending.revision = shadow_pending.revision
                real_pending.delivered = shadow_pending.delivered
                real_pending.delivered_at = shadow_pending.delivered_at

        self._notify_listeners()
        if (
            pending_result is not None
            and real_pending is not None
            and not real_pending.future.done()
        ):
            real_pending.future.set_result(pending_result)

    async def async_process_monitor_state(self, state: NuveState) -> None:
        """Persist any canonical monitor merge before exposing telemetry or success."""

        async with self._transaction_lock:
            pending = self._pending_command
            pending_kind = pending.kind if pending is not None else None
            self._trace_event(
                "monitor_upload",
                family="monitor",
                result="full" if state.monitor_is_sync else "sparse",
                at=state.last_seen,
            )
            shadow, shadow_future = self._monitor_shadow()
            shadow._merge_monitor_state_in_place(state)
            if self.persistence_fault_latched:
                # Keep read-only live telemetry available, but do not trust or
                # expose any canonical mutation after an ambiguous disk result.
                self.state = replace(
                    copy.deepcopy(shadow.state),
                    settings_revision=self.state.settings_revision,
                )
                self.last_monitor_upload = shadow.last_monitor_upload
                self.current_temperature_observed_at = shadow.current_temperature_observed_at
                self.current_temperature_source = shadow.current_temperature_source
                self._notify_listeners()
                self._trace_event(
                    "monitor_confirmation", family=pending_kind, result="persistence_latched"
                )
                return

            before = self.persistent_baselines()
            candidate = shadow.persistent_baselines()
            if candidate == before:
                self._commit_monitor_shadow(shadow, shadow_future=shadow_future)
                self._trace_monitor_result(pending, pending_kind)
                return
            await self._async_persist_and_commit(
                candidate,
                lambda: self._commit_monitor_shadow(shadow, shadow_future=shadow_future),
            )
            self._trace_monitor_result(pending, pending_kind)

    def async_accept_settings_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        received_at: datetime,
        prepared_revision: str | None = None,
    ) -> str:
        """Store a complete device-originated settings snapshot and return its ack revision."""

        incoming = copy.deepcopy(snapshot)
        pending = self._pending_command
        settings_result = self._settings_owned_upload_result(incoming, received_at)
        revision = prepared_revision or self._settings_snapshot_revision(incoming, received_at)
        permitted_changes = self._delivered_settings_echo_changes(
            incoming,
            received_at=received_at,
        )
        canonical_echo = self._settings_snapshot_is_canonical_echo(
            incoming,
            permitted_changes=permitted_changes,
        )
        if settings_result == "state_changed":
            canonical_echo = False
        if canonical_echo and permitted_changes and pending is not None:
            pending.coherent_echo_received_at = received_at
        complete_pending = (
            pending is not None and pending.kind == "settings" and not pending.delivered
        )

        self.settings_snapshot = incoming
        self.settings_revision = revision
        self.settings_revision_floor = self._latest_revision(self.settings_revision_floor, revision)
        self._clear_bootstrap()
        if self.live_data_command_time is None:
            self.live_data_command_time = revision
        # DeviceController's Settings GET handler calls saveSettings()
        # unconditionally, even after an exact no-op echo. That creates a full
        # /sync/update upload. Preserve post-start monitor authority only when
        # every desired/control field is byte-for-JSON equivalent to the
        # baseline we just served. A post-delivery upload may differ only by
        # the exact queued fields; it proves a coherent echo but does not
        # confirm a temperature or mode command, which still requires newer
        # monitor telemetry. Observational room values are intentionally
        # excluded. Any local/clamped/configuration change still fails closed
        # until newer monitor evidence arrives.
        if not canonical_echo:
            self.last_settings_upload = received_at
            self.authoritative_control_monitor_seen = False
        self._trace_event(
            "upload_echo",
            family="settings",
            result=(
                "expected_command"
                if canonical_echo and permitted_changes
                else "canonical"
                if canonical_echo
                else "changed"
            ),
            at=received_at,
        )
        self._merge_settings_into_state(incoming, revision, observed_at=received_at)
        if settings_result is not None:
            self.uncertain_command = None
            if pending is not None and pending.kind == "settings":
                self._complete_pending(settings_result)
            else:
                self._notify_listeners()
        elif complete_pending:
            self._complete_pending("state_changed")
        else:
            self._notify_listeners()
        return revision

    def async_accept_auto_mode_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        received_at: datetime,
        prepared_revision: str | None = None,
    ) -> str:
        """Store a complete device-originated auto-mode snapshot and return its ack revision."""

        # The device uploads four fields, all of which are validated at the
        # request boundary.  Only the two temperature bounds are consumed by
        # the firmware's Auto GET response, so keep one canonical projection
        # for runtime state, monitor-derived baselines, hashing, and restore.
        incoming = parse_auto_mode_baseline(snapshot)
        pending = self._pending_command
        revision = prepared_revision or self._auto_snapshot_revision(incoming, received_at)
        permitted_changes = self._delivered_auto_echo_changes(
            incoming,
            received_at=received_at,
        )
        canonical_echo = self._auto_snapshot_is_canonical_echo(
            incoming,
            permitted_changes=permitted_changes,
        )
        if canonical_echo and permitted_changes and pending is not None:
            pending.coherent_echo_received_at = received_at
        complete_pending = pending is not None and pending.kind == "auto" and not pending.delivered

        self.auto_mode_snapshot = incoming
        self.auto_mode_revision = revision
        self.auto_revision_floor = self._latest_revision(self.auto_revision_floor, revision)
        if not canonical_echo:
            self.last_auto_mode_upload = received_at
            self.authoritative_control_monitor_seen = False
        self._trace_event(
            "upload_echo",
            family="auto",
            result=(
                "expected_command"
                if canonical_echo and permitted_changes
                else "canonical"
                if canonical_echo
                else "changed"
            ),
            at=received_at,
        )
        self._merge_auto_into_state(incoming, revision)
        if complete_pending:
            self._complete_pending("state_changed")
        else:
            self._notify_listeners()
        return revision

    def prepare_settings_snapshot(
        self, snapshot: dict[str, Any], *, received_at: datetime
    ) -> tuple[str, dict[str, Any]]:
        """Build the exact persistent candidate before acknowledging an upload."""

        incoming = copy.deepcopy(snapshot)
        revision = self._settings_snapshot_revision(incoming, received_at)
        candidate = self.persistent_baselines()
        candidate.pop("bootstrap", None)
        candidate["settings"] = incoming
        candidate["settings_revision"] = revision
        candidate["settings_revision_floor"] = self._latest_revision(
            self.settings_revision_floor, revision
        )
        if self._settings_owned_upload_result(incoming, received_at) is not None:
            candidate.pop("uncertain_command", None)
        if candidate.get("live_data_command_time") is None:
            candidate["live_data_command_time"] = revision
        return revision, candidate

    def prepare_auto_mode_snapshot(
        self, snapshot: dict[str, Any], *, received_at: datetime
    ) -> tuple[str, dict[str, Any]]:
        """Build the exact persistent Auto candidate before acknowledging an upload."""

        incoming = parse_auto_mode_baseline(snapshot)
        revision = self._auto_snapshot_revision(incoming, received_at)
        candidate = self.persistent_baselines()
        candidate["auto_mode"] = incoming
        candidate["auto_mode_revision"] = revision
        candidate["auto_revision_floor"] = self._latest_revision(self.auto_revision_floor, revision)
        return revision, candidate

    def _settings_snapshot_revision(self, incoming: dict[str, Any], received_at: datetime) -> str:
        prior = self._latest_revision(
            self._latest_revision(
                self._latest_revision(self.settings_revision, self.settings_revision_floor),
                self.bootstrap_revision,
            ),
            self._pending_command.revision if self._pending_command is not None else None,
        )
        return next_revision(prior, now=received_at)

    def _auto_snapshot_revision(self, incoming: dict[str, Any], received_at: datetime) -> str:
        # The one-shot Auto bootstrap shares the settings bootstrap timestamp.
        # The first canonical Auto response must therefore also advance beyond
        # the accepted settings revision, even when both uploads occur in one second.
        prior = self._latest_revision(
            self._latest_revision(self.settings_revision, self.settings_revision_floor),
            self._latest_revision(
                self._latest_revision(self.auto_mode_revision, self.auto_revision_floor),
                self._pending_command.revision if self._pending_command is not None else None,
            ),
        )
        return next_revision(prior, now=received_at)

    def async_accept_partial_settings(
        self,
        section: Literal["settings", "system"],
        snapshot: dict[str, Any],
        *,
        received_at: datetime,
        prepared_snapshot: dict[str, Any] | None = None,
        prepared_revision: str | None = None,
    ) -> str:
        """Merge a complete device-preferences or HVAC-system subsection."""

        if prepared_snapshot is None or prepared_revision is None:
            revision, _, prepared_snapshot = self.prepare_partial_settings(
                section, snapshot, received_at=received_at
            )
        else:
            revision = prepared_revision
        self.settings_snapshot = copy.deepcopy(prepared_snapshot)
        self.settings_revision = revision
        self.settings_revision_floor = self._latest_revision(self.settings_revision_floor, revision)
        pending = self._pending_command
        if pending is not None and pending.kind == "settings" and not pending.delivered:
            pending.payload = self._settings_payload(self.settings_snapshot, pending.desired)
        self.settings_revision = revision
        self.async_update_state(replace(self.state, settings_revision=revision))
        return revision

    def prepare_partial_settings(
        self,
        section: Literal["settings", "system"],
        snapshot: dict[str, Any],
        *,
        received_at: datetime,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        """Prepare a complete subsection merge without exposing it in runtime."""

        if self.settings_snapshot is None:
            raise ControlNotReadyError
        full = copy.deepcopy(self.settings_snapshot)
        value = copy.deepcopy(snapshot)
        value.pop("sn", None)
        existing = full.get(section)
        if isinstance(existing, dict):
            merged = copy.deepcopy(existing)
            merged.update(value)
            value = merged
        full[section] = value
        revision = next_revision(
            self._latest_revision(self.settings_revision, self.settings_revision_floor),
            now=received_at,
        )
        candidate = self.persistent_baselines()
        candidate["settings"] = full
        candidate["settings_revision"] = revision
        candidate["settings_revision_floor"] = revision
        return revision, candidate, full

    def async_accept_current_sensors(
        self, snapshot: dict[str, Any], *, received_at: datetime
    ) -> None:
        """Merge a current room-sensor partial report."""

        if (
            self.current_temperature_observed_at is None
            or received_at >= self.current_temperature_observed_at
        ):
            self.current_temperature_observed_at = received_at
            self.current_temperature_source = "current_sensors"
            current_temperature = float(snapshot["current_temp"])
        else:
            current_temperature = self.state.current_temperature
        self.async_update_state(
            replace(
                self.state,
                current_temperature=current_temperature,
                current_humidity=float(snapshot["current_humidity"]),
                air_quality_level=int(snapshot["co2_id"]),
            )
        )

    def async_accept_current_stages(self, snapshot: dict[str, Any]) -> None:
        """Merge a current HVAC relay-stage partial report."""

        self.async_update_state(
            replace(
                self.state,
                fan_active=bool(snapshot["current_fan_status"]),
                heating_stage=int(snapshot["current_heating_stage"]),
                cooling_stage=int(snapshot["current_cooling_stage"]),
            )
        )

    def async_restore_persistent_baselines(self, data: Mapping[str, Any]) -> None:
        """Restore previously validated private baselines without marking the device online."""

        self.persistence_recovered_from_previous = data.get("recovered_from_previous") is True
        if data.get("persistence_fault") is True or self.persistence_recovered_from_previous:
            # A later durable transaction may have contained a delivered-write
            # journal. Recovery is useful for read-only telemetry, but it is not
            # proof that no command was delivered, so writes remain latched off.
            self.persistence_healthy = False
            self.persistence_fault_latched = True

        settings = data.get("settings")
        settings_revision = data.get("settings_revision")
        if settings is not None and settings_revision is not None:
            self.settings_snapshot = copy.deepcopy(settings)
            self.settings_revision = settings_revision
            self.live_data_command_time = data.get("live_data_command_time", settings_revision)
            # Room observations in a persisted settings baseline are a
            # historical upload, not live state after a Home Assistant restart.
            self._merge_settings_into_state(settings, settings_revision)

        self.settings_revision_floor = data.get("settings_revision_floor")

        auto_mode = data.get("auto_mode")
        auto_mode_revision = data.get("auto_mode_revision")
        if auto_mode is not None and auto_mode_revision is not None:
            self.auto_mode_snapshot = copy.deepcopy(auto_mode)
            self.auto_mode_revision = auto_mode_revision
            self._merge_auto_into_state(auto_mode, auto_mode_revision)

        self.auto_revision_floor = data.get("auto_revision_floor")

        bootstrap = data.get("bootstrap")
        if isinstance(bootstrap, dict):
            expires_at = bootstrap.get("expires_at")
            if isinstance(expires_at, datetime):
                self.bootstrap_revision = bootstrap["revision"]
                self.bootstrap_armed_at = bootstrap["armed_at"]
                self.bootstrap_armed_until = expires_at
                self.bootstrap_settings_served = bootstrap["settings_served"]
                self.bootstrap_auto_served = bootstrap["auto_served"]
                self._schedule_bootstrap_expiry(expires_at)

        uncertain = data.get("uncertain_command")
        if isinstance(uncertain, dict):
            kind = uncertain.get("kind")
            desired = uncertain.get("desired")
            delivered_at = uncertain.get("delivered_at")
            if (
                kind in ("settings", "auto")
                and isinstance(desired, dict)
                and (delivered_at is None or isinstance(delivered_at, datetime))
            ):
                self.uncertain_command = UncertainCommand(
                    kind=kind,
                    desired=copy.deepcopy(desired),
                    delivered_at=delivered_at,
                    revision=uncertain.get("revision"),
                )

    def persistent_baselines(self) -> dict[str, Any]:
        """Return the private, versioned device baselines that survive HA restarts."""

        data: dict[str, Any] = {}
        if self.has_settings_baseline:
            data["settings"] = copy.deepcopy(self.settings_snapshot)
            data["settings_revision"] = self.settings_revision
        if self.has_auto_mode_baseline:
            data["auto_mode"] = copy.deepcopy(self.auto_mode_snapshot)
            data["auto_mode_revision"] = self.auto_mode_revision
        if self.settings_revision_floor is not None:
            data["settings_revision_floor"] = self.settings_revision_floor
        if self.auto_revision_floor is not None:
            data["auto_revision_floor"] = self.auto_revision_floor
        if self.live_data_command_time is not None:
            data["live_data_command_time"] = self.live_data_command_time
        if (
            not self.has_settings_baseline
            and self.bootstrap_revision is not None
            and self.bootstrap_armed_at is not None
            and self.bootstrap_armed_until is not None
        ):
            data["bootstrap"] = {
                "revision": self.bootstrap_revision,
                "armed_at": self.bootstrap_armed_at.isoformat(),
                "expires_at": self.bootstrap_armed_until.isoformat(),
                "settings_served": self.bootstrap_settings_served,
                "auto_served": self.bootstrap_auto_served,
            }
        if self.uncertain_command is not None:
            data["uncertain_command"] = self._serialize_uncertainty(self.uncertain_command)
        return data

    def _canonical_settings_response(self) -> dict[str, Any]:
        """Render the saved device state after the metadata checks pass."""

        assert self.settings_revision is not None
        assert self.settings_snapshot is not None
        technician_url = self._effective_technician_url()
        assert technician_url is not None
        assert self.temp_correction_version is not None
        return render_settings_response(
            serial=self.serial,
            revision=self.settings_revision,
            settings=self._with_live_data_command(self.settings_snapshot),
            technician_url=technician_url,
            temp_correction_version=self.temp_correction_version,
        )

    def _schedule_preserving_settings_response(self) -> dict[str, Any]:
        """Keep a local schedule intact without replaying server-owned schedule state."""

        assert self.settings_revision is not None
        assert self.settings_snapshot is not None
        technician_url = self._effective_technician_url()
        assert technician_url is not None
        return render_monitor_wake_response(
            serial=self.serial,
            revision=self.settings_revision,
            technician_url=technician_url,
            messages=self.settings_snapshot["messages"],
            command_time=self.live_data_command_time or self.settings_revision,
        )

    async def _async_monitor_resync_response(
        self,
        *,
        requested_at: datetime,
        response_sender: ResponseSender | None,
    ) -> dict[str, Any]:
        """Cycle monitor offline then online without supplying HVAC state."""

        assert self.settings_snapshot is not None
        assert self.settings_revision is not None
        technician_url = self._effective_technician_url()
        assert technician_url is not None

        if self._monitor_resync_next == "reset":
            response = render_monitor_reset_response(
                serial=self.serial,
                revision=self.settings_revision,
                technician_url=technician_url,
                messages=self.settings_snapshot["messages"],
            )
            next_phase: Literal["reset", "wake"] = "wake"
        else:
            prior = self._latest_revision(
                self._latest_revision(self.settings_revision, self.settings_revision_floor),
                self._latest_revision(
                    self._latest_revision(
                        self.live_data_command_time,
                        (
                            self.uncertain_command.revision
                            if self.uncertain_command is not None
                            else None
                        ),
                    ),
                    self._monitor_wake_command_time,
                ),
            )
            command_time = next_revision(prior, now=requested_at)
            self._monitor_wake_command_time = command_time
            response = render_monitor_wake_response(
                serial=self.serial,
                revision=self.settings_revision,
                technician_url=technician_url,
                messages=self.settings_snapshot["messages"],
                command_time=command_time,
            )
            next_phase = "reset"

        if response_sender is not None:
            await response_sender(copy.deepcopy(response))
        # fetchSettings immediately chains fetchAutoModeSetings. Returning an
        # empty Auto body marks the whole fetch unsuccessful and doubles the
        # firmware retry interval up to 60 seconds. Arm one exact-revision,
        # object-valued companion only after the non-applying Settings body was
        # delivered. The native Auto callback treats the response as a
        # successful fetch, while the QML numeric-difference guards apply no
        # bounds. This keeps the proven 5-second healthy polling cadence without
        # replaying a restored Auto baseline.
        self._monitor_resync_auto_companion_revision = (
            self.auto_mode_revision if self.has_auto_mode_baseline else None
        )
        self._monitor_resync_next = next_phase
        return response

    async def async_get_settings_response(
        self,
        *,
        requested_at: datetime,
        response_sender: ResponseSender | None = None,
    ) -> dict[str, Any]:
        """Return a durable no-op echo or whole settings command for a device poll."""

        async with self._transaction_lock:
            if self.persistence_fault_latched:
                raise PersistenceUnavailableError("canonical persistence requires reload")
            self.last_settings_poll = requested_at
            self._trace_event("poll", family="settings", result="received", at=requested_at)
            await self._async_clear_expired_bootstrap_locked(requested_at)
            if not self.has_settings_baseline:
                if not self.bootstrap_settings_served and self._bootstrap_active(requested_at):
                    assert self.bootstrap_revision is not None
                    assert self.bootstrap_technician_url is not None
                    candidate = self.persistent_baselines()
                    bootstrap = copy.deepcopy(candidate["bootstrap"])
                    bootstrap["settings_served"] = True
                    candidate["bootstrap"] = bootstrap

                    def commit_bootstrap() -> None:
                        self.bootstrap_settings_served = True
                        self._notify_listeners()

                    await self._async_persist_and_commit(candidate, commit_bootstrap)
                    return render_settings_bootstrap_response(
                        serial=self.serial,
                        revision=self.bootstrap_revision,
                        technician_url=self.bootstrap_technician_url,
                    )
                return {}
            if not self.canonical_response_safe:
                return {}
            if not self.canonical_live_consistency_ready:
                return await self._async_monitor_resync_response(
                    requested_at=requested_at,
                    response_sender=response_sender,
                )

            pending = self._pending_command
            if pending is not None and pending.kind == "settings":
                if self.state.schedule_type != NO_SCHEDULE_TYPE:
                    self._complete_pending("not_ready")
                    return self._schedule_preserving_settings_response()
                if not self.can_enable_control:
                    self._complete_pending(
                        "outcome_uncertain" if pending.delivered else "not_ready"
                    )
                    return {}
                if not pending.delivered:
                    prior = self._latest_revision(
                        self._latest_revision(self.settings_revision, self.settings_revision_floor),
                        pending.revision,
                    )
                    revision = next_revision(prior, now=requested_at)
                    uncertainty = UncertainCommand(
                        kind="settings",
                        desired=copy.deepcopy(pending.desired),
                        delivered_at=None,
                        revision=revision,
                    )
                    candidate = self.persistent_baselines()
                    candidate["settings_revision_floor"] = revision
                    candidate["uncertain_command"] = self._serialize_uncertainty(uncertainty)

                    def commit_delivery() -> None:
                        pending.revision = revision
                        pending.delivered = True
                        pending.delivered_at = None
                        self.settings_revision_floor = revision
                        self.uncertain_command = uncertainty
                        self._notify_listeners()

                    await self._async_persist_and_commit(candidate, commit_delivery)
                    if not self.can_enable_control:
                        # The write-ahead journal is durable, but a readiness
                        # dependency changed while storage I/O was in flight.
                        # Do not expose desired state; retain uncertainty because
                        # the HTTP delivery boundary is now ambiguous.
                        self._complete_pending("outcome_uncertain")
                        return {}
                assert pending.revision is not None
                technician_url = self._effective_technician_url()
                assert technician_url is not None
                temp_correction_version = self.temp_correction_version
                assert temp_correction_version is not None
                response = render_settings_response(
                    serial=self.serial,
                    revision=pending.revision,
                    settings=self._with_live_data_command(
                        pending.payload, command_time=pending.revision
                    ),
                    technician_url=technician_url,
                    temp_correction_version=temp_correction_version,
                )
                return await self._async_deliver_pending_response(
                    pending,
                    response,
                    requested_at=requested_at,
                    response_sender=response_sender,
                )
            if self.state.schedule_type != NO_SCHEDULE_TYPE:
                return self._schedule_preserving_settings_response()
            return self._canonical_settings_response()

    async def async_get_auto_mode_response(
        self,
        *,
        requested_at: datetime,
        response_sender: ResponseSender | None = None,
    ) -> dict[str, Any]:
        """Return a durable no-op echo or whole Auto command for a device poll."""

        async with self._transaction_lock:
            if self.persistence_fault_latched:
                raise PersistenceUnavailableError("canonical persistence requires reload")
            self.last_auto_mode_poll = requested_at
            self._trace_event("poll", family="auto", result="received", at=requested_at)
            await self._async_clear_expired_bootstrap_locked(requested_at)
            # Once the settings trap has been served, its non-applying Auto
            # companion must win over monitor-derived or restored Auto data.
            if (
                self.bootstrap_settings_served
                and not self.bootstrap_auto_served
                and self._bootstrap_active(requested_at)
            ):
                assert self.bootstrap_revision is not None
                candidate = self.persistent_baselines()
                bootstrap = copy.deepcopy(candidate["bootstrap"])
                bootstrap["auto_served"] = True
                candidate["bootstrap"] = bootstrap

                def commit_bootstrap() -> None:
                    self.bootstrap_auto_served = True
                    self._notify_listeners()

                await self._async_persist_and_commit(candidate, commit_bootstrap)
                return render_auto_mode_bootstrap_response(revision=self.bootstrap_revision)
            if not self.has_settings_baseline or not self.has_auto_mode_baseline:
                return {}
            if not self.canonical_response_safe:
                return {}
            if not self.canonical_live_consistency_ready:
                companion_revision = self._monitor_resync_auto_companion_revision
                self._monitor_resync_auto_companion_revision = None
                if companion_revision is None:
                    return {}
                return render_auto_mode_bootstrap_response(revision=companion_revision)
            self._monitor_resync_auto_companion_revision = None
            pending = self._pending_command
            if pending is not None and pending.kind == "auto":
                if not self.can_enable_control:
                    self._complete_pending(
                        "outcome_uncertain" if pending.delivered else "not_ready"
                    )
                    return {}
                if not pending.delivered:
                    prior = self._latest_revision(
                        self._latest_revision(self.auto_mode_revision, self.auto_revision_floor),
                        pending.revision,
                    )
                    revision = next_revision(prior, now=requested_at)
                    uncertainty = UncertainCommand(
                        kind="auto",
                        desired=copy.deepcopy(pending.desired),
                        delivered_at=None,
                        revision=revision,
                    )
                    candidate = self.persistent_baselines()
                    candidate["auto_revision_floor"] = revision
                    candidate["uncertain_command"] = self._serialize_uncertainty(uncertainty)

                    def commit_delivery() -> None:
                        pending.revision = revision
                        pending.delivered = True
                        pending.delivered_at = None
                        self.auto_revision_floor = revision
                        self.uncertain_command = uncertainty
                        self._notify_listeners()

                    await self._async_persist_and_commit(candidate, commit_delivery)
                    if not self.can_enable_control:
                        self._complete_pending("outcome_uncertain")
                        return {}
                assert pending.revision is not None
                response = render_auto_mode_response(
                    revision=pending.revision,
                    settings=pending.payload,
                )
                return await self._async_deliver_pending_response(
                    pending,
                    response,
                    requested_at=requested_at,
                    response_sender=response_sender,
                )
            assert self.auto_mode_revision is not None
            assert self.auto_mode_snapshot is not None
            return render_auto_mode_response(
                revision=self.auto_mode_revision,
                settings=self.auto_mode_snapshot,
            )

    async def _async_deliver_pending_response(
        self,
        pending: PendingCommand,
        response: dict[str, Any],
        *,
        requested_at: datetime,
        response_sender: ResponseSender | None,
    ) -> dict[str, Any]:
        """Send a command before establishing its durable confirmation boundary.

        Production passes a sender that writes the HTTP body while the runtime
        transaction lock is held. A nullable write-ahead boundary is already
        durable before that write. Only after the body has been sent do we
        persist the server time from which device-clock skew is measured.
        """

        if response_sender is not None:
            await response_sender(copy.deepcopy(response))
            delivered_at = datetime.now(UTC)
        else:
            # Direct runtime callers are tests and internal probes; model an
            # immediate response at the supplied request boundary.
            delivered_at = requested_at
        self._trace_event(
            "command_delivery",
            family=pending.kind,
            result="body_sent",
            duration_ms=self._elapsed_ms(pending.queued_at, delivered_at),
            at=delivered_at,
        )

        if pending.delivered_at is None:
            uncertainty = UncertainCommand(
                kind=pending.kind,
                desired=copy.deepcopy(pending.desired),
                delivered_at=delivered_at,
                revision=pending.revision,
            )
            candidate = self.persistent_baselines()
            candidate["uncertain_command"] = self._serialize_uncertainty(uncertainty)

            def commit_delivery_boundary() -> None:
                pending.delivered_at = delivered_at
                self.uncertain_command = uncertainty
                self._notify_listeners()

            await self._async_persist_and_commit(candidate, commit_delivery_boundary)

        # The body may already have reached the thermostat. If any safety gate
        # changed during the send/final journal write, resolve the HA caller as
        # uncertain and retain the durable lockout.
        if not self.can_enable_control:
            self._complete_pending("outcome_uncertain")
        return response

    async def async_request_settings_change(self, changes: dict[str, Any]) -> None:
        """Queue settings changes and wait for matching monitor telemetry."""

        async with self._transaction_lock:
            self._assert_ready("settings")
            if self.state.schedule_type != NO_SCHEDULE_TYPE:
                raise ControlNotReadyError
            assert self.settings_snapshot is not None
            desired = self._validated_settings_changes(changes)
            desired = self._expand_settings_changes(self.settings_snapshot, desired)
            desired = self._changed_fields(desired, self.settings_snapshot)
            if not desired:
                return
            payload = self._settings_payload(self.settings_snapshot, desired)
            pending = self._queue_command_locked("settings", desired, payload)
        await self._wait_for_command(pending)

    async def async_request_auto_mode_change(self, changes: dict[str, Any]) -> None:
        """Queue auto-range changes and wait for matching device state."""

        async with self._transaction_lock:
            self._assert_ready("auto")
            assert self.auto_mode_snapshot is not None
            desired = self._validated_auto_changes(changes)
            desired = self._changed_fields(desired, self.auto_mode_snapshot)
            if not desired:
                return
            payload = self._auto_payload(self.auto_mode_snapshot, desired)
            if float(payload["auto_temp_low"]) >= float(payload["auto_temp_high"]):
                raise ControlNotReadyError
            pending = self._queue_command_locked("auto", desired, payload)
        await self._wait_for_command(pending)

    def _queue_command_locked(
        self,
        kind: Literal["settings", "auto"],
        desired: dict[str, Any],
        payload: dict[str, Any],
    ) -> PendingCommand:
        if self._pending_command is not None:
            raise ControlBusyError
        future = asyncio.get_running_loop().create_future()
        baseline = self.settings_snapshot if kind == "settings" else self.auto_mode_snapshot
        assert baseline is not None
        pending = PendingCommand(
            kind=kind,
            desired=copy.deepcopy(desired),
            payload=copy.deepcopy(payload),
            future=future,
            queued_at=datetime.now(UTC),
            queued_baseline={key: copy.deepcopy(baseline[key]) for key in desired},
        )
        self._pending_command = pending
        self._trace_event("command", family=kind, result="queued", at=pending.queued_at)
        self._notify_listeners()
        return pending

    async def _wait_for_command(self, pending: PendingCommand) -> None:
        """Wait outside the coordinator lock, then clean up under it."""

        future = pending.future
        try:
            result = await asyncio.wait_for(
                asyncio.shield(future), timeout=self.command_timeout_seconds
            )
        except TimeoutError:
            async with self._transaction_lock:
                if future.done():
                    result = future.result()
                else:
                    if self._pending_command is pending:
                        self._pending_command = None
                        self._notify_listeners()
                    result = "outcome_uncertain" if pending.delivered else "timeout"
        except asyncio.CancelledError:
            async with self._transaction_lock:
                if self._pending_command is pending:
                    self._pending_command = None
                    self._notify_listeners()
            raise

        if result == "confirmed":
            return
        if result == "timeout":
            raise CommandTimeoutError
        if result == "state_changed":
            raise ControlStateChangedError
        if result == "stopped":
            raise RuntimeStoppedError
        if result == "not_ready":
            raise ControlNotReadyError
        if result == "outcome_uncertain":
            raise CommandOutcomeUncertainError
        raise CommandOutcomeUncertainError

    def _assert_ready(self, kind: Literal["settings", "auto"]) -> None:
        if not self.control_enabled:
            raise ControlDisabledError
        if self.uncertain_command is not None:
            raise CommandOutcomeUncertainError
        if self._pending_command is not None:
            raise ControlBusyError
        if not self.can_enable_control:
            raise ControlNotReadyError
        if kind == "auto" and not self.has_auto_mode_baseline:
            raise ControlNotReadyError

    @staticmethod
    def _matches(desired: dict[str, Any], actual: dict[str, Any]) -> bool:
        for key, value in desired.items():
            candidate = actual.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if (
                    not isinstance(candidate, (int, float))
                    or isinstance(candidate, bool)
                    or not math.isclose(float(candidate), float(value), abs_tol=0.02)
                ):
                    return False
            elif candidate != value:
                return False
        return True

    @classmethod
    def _changed_fields(cls, desired: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
        return {
            key: copy.deepcopy(value)
            for key, value in desired.items()
            if not cls._matches({key: value}, baseline)
        }

    @staticmethod
    def _validated_settings_changes(changes: dict[str, Any]) -> dict[str, Any]:
        if not changes or not set(changes).issubset(
            {"temp", "mode_id", "fan", "backlight", "settings"}
        ):
            raise ControlNotReadyError
        if "fan" in changes and len(changes) != 1:
            raise ControlNotReadyError
        if ({"backlight", "settings"} & set(changes)) and len(changes) != 1:
            raise ControlNotReadyError
        validated = copy.deepcopy(changes)
        if "temp" in validated:
            value = validated["temp"]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not MIN_TARGET_TEMPERATURE <= float(value) <= MAX_TARGET_TEMPERATURE
                or not math.isclose(
                    float(value) / TARGET_TEMPERATURE_STEP,
                    round(float(value) / TARGET_TEMPERATURE_STEP),
                    abs_tol=1e-7,
                )
            ):
                raise ControlNotReadyError
            validated["temp"] = float(value)
        if "mode_id" in validated:
            value = validated["mode_id"]
            if isinstance(value, bool) or not isinstance(value, int) or value not in (1, 2, 3, 5):
                raise ControlNotReadyError
        if "fan" in validated:
            NuveRuntime._validate_fan_change(validated["fan"])
        if "backlight" in validated:
            NuveRuntime._validate_backlight_change(validated["backlight"])
        if "settings" in validated:
            NuveRuntime._validate_device_settings_change(validated["settings"])
        return validated

    @staticmethod
    def _validate_fan_change(value: Any) -> None:
        if not isinstance(value, dict) or set(value) != {"mode", "workingPerHour"}:
            raise ControlNotReadyError
        mode = value["mode"]
        working_per_hour = value["workingPerHour"]
        if (
            isinstance(mode, bool)
            or not isinstance(mode, int)
            or mode not in FAN_MODE_IDS
            or isinstance(working_per_hour, bool)
            or not isinstance(working_per_hour, int)
            or not MIN_FAN_WORKING_PER_HOUR <= working_per_hour <= MAX_FAN_WORKING_PER_HOUR
        ):
            raise ControlNotReadyError

    @staticmethod
    def _validate_backlight_change(value: Any) -> None:
        if not isinstance(value, dict) or not value or not set(value).issubset(BACKLIGHT_KEYS):
            raise ControlNotReadyError
        if "on" in value and not isinstance(value["on"], bool):
            raise ControlNotReadyError
        for key in ("hue", "value"):
            if key not in value:
                continue
            candidate = value[key]
            if (
                isinstance(candidate, bool)
                or not isinstance(candidate, (int, float))
                or not math.isfinite(float(candidate))
                or not 0 <= float(candidate) <= 1
            ):
                raise ControlNotReadyError
            value[key] = float(candidate)
        if "shadeIndex" in value:
            shade_index = value["shadeIndex"]
            if (
                isinstance(shade_index, bool)
                or not isinstance(shade_index, int)
                or not 0 <= shade_index <= 5
            ):
                raise ControlNotReadyError

    @staticmethod
    def _validate_device_settings_change(value: Any) -> None:
        if (
            not isinstance(value, dict)
            or not value
            or not set(value).issubset(DISPLAY_SETTINGS_KEYS)
        ):
            raise ControlNotReadyError
        NuveRuntime._validate_device_settings_integers(value)
        NuveRuntime._validate_device_settings_booleans(value)
        NuveRuntime._validate_device_settings_times(value)

    @staticmethod
    def _validate_device_settings_integers(value: dict[str, Any]) -> None:
        if "brightness" in value:
            brightness = value["brightness"]
            if (
                isinstance(brightness, bool)
                or not isinstance(brightness, int)
                or not 0 <= brightness <= 100
            ):
                raise ControlNotReadyError
        if "brightness_mode" in value:
            mode = value["brightness_mode"]
            if isinstance(mode, bool) or not isinstance(mode, int) or mode not in (0, 1):
                raise ControlNotReadyError
        if "timeFormat" in value:
            candidate = value["timeFormat"]
            if (
                isinstance(candidate, bool)
                or not isinstance(candidate, int)
                or candidate not in (0, 1)
            ):
                raise ControlNotReadyError

    @staticmethod
    def _validate_device_settings_booleans(value: dict[str, Any]) -> None:
        for key in (
            "tofEnabled",
            "ledBlinkingEnabled",
            "nightModeEnabled",
        ):
            if key in value and not isinstance(value[key], bool):
                raise ControlNotReadyError

    @staticmethod
    def _validate_device_settings_times(value: dict[str, Any]) -> None:
        for key in ("nightModeStart", "nightModeEnd"):
            if key not in value:
                continue
            try:
                normalize_night_mode_time(value[key], name=key)
            except NuveProtocolError as err:
                raise ControlNotReadyError from err

    @staticmethod
    def _expand_settings_changes(
        baseline: dict[str, Any], changes: dict[str, Any]
    ) -> dict[str, Any]:
        """Expand a display subsection into the complete field-owning object."""

        expanded = copy.deepcopy(changes)
        for section in ("backlight", "settings"):
            if section not in expanded:
                continue
            current = baseline.get(section)
            if not isinstance(current, dict):
                raise ControlNotReadyError
            merged = copy.deepcopy(current)
            merged.update(expanded[section])
            expanded[section] = merged
        settings = expanded.get("settings")
        if isinstance(settings, dict):
            try:
                start = normalize_night_mode_time(
                    settings.get("nightModeStart"), name="nightModeStart"
                )
                end = normalize_night_mode_time(settings.get("nightModeEnd"), name="nightModeEnd")
            except NuveProtocolError as err:
                raise ControlNotReadyError from err
            if start == end:
                raise ControlNotReadyError
        return expanded

    def _settings_owned_upload_result(
        self, incoming: dict[str, Any], received_at: datetime
    ) -> str | None:
        """Resolve Settings-owned fields from the post-GET complete upload."""

        desired: dict[str, Any] | None = None
        delivered_at: datetime | None = None
        pending = self._pending_command
        if (
            pending is not None
            and pending.kind == "settings"
            and pending.delivered
            and self._settings_upload_owns(pending.desired)
        ):
            desired = pending.desired
            delivered_at = pending.delivered_at
        elif (
            self.uncertain_command is not None
            and self.uncertain_command.kind == "settings"
            and self._settings_upload_owns(self.uncertain_command.desired)
        ):
            desired = self.uncertain_command.desired
            delivered_at = self.uncertain_command.delivered_at
        if delivered_at is None or desired is None or received_at <= delivered_at:
            return None
        return "confirmed" if self._matches(desired, incoming) else "state_changed"

    @staticmethod
    def _settings_upload_owns(desired: dict[str, Any]) -> bool:
        keys = set(desired)
        return ("fan" in keys and keys.issubset({"fan", "hold_period"})) or keys in (
            {"backlight"},
            {"settings"},
        )

    def _delivered_settings_echo_changes(
        self,
        incoming: dict[str, Any],
        *,
        received_at: datetime,
    ) -> frozenset[str]:
        """Return exact queued fields in a coherent post-delivery Settings echo."""

        pending = self._pending_command
        if (
            pending is None
            or pending.kind != "settings"
            or not pending.delivered
            or pending.delivered_at is None
            or received_at <= pending.delivered_at
            or not self._matches(pending.desired, incoming)
        ):
            return frozenset()
        return frozenset(pending.desired)

    def _delivered_auto_echo_changes(
        self,
        incoming: dict[str, Any],
        *,
        received_at: datetime,
    ) -> frozenset[str]:
        """Return exact queued fields in a coherent post-delivery Auto echo."""

        pending = self._pending_command
        if (
            pending is None
            or pending.kind != "auto"
            or not pending.delivered
            or pending.delivered_at is None
            or received_at <= pending.delivered_at
            or not self._matches(pending.desired, incoming)
        ):
            return frozenset()
        return frozenset(pending.desired)

    def _auto_snapshot_is_canonical_echo(
        self,
        incoming: dict[str, Any],
        *,
        permitted_changes: frozenset[str],
    ) -> bool:
        """Allow only the exact delivered Auto fields to differ from baseline."""

        if self.auto_mode_snapshot is None:
            return False
        expected = copy.deepcopy(self.auto_mode_snapshot)
        for key in permitted_changes:
            expected[key] = copy.deepcopy(incoming[key])
        return incoming == expected

    @staticmethod
    def _validated_auto_changes(changes: dict[str, Any]) -> dict[str, Any]:
        if not changes or not set(changes).issubset({"auto_temp_low", "auto_temp_high"}):
            raise ControlNotReadyError
        validated: dict[str, Any] = {}
        for key, value in changes.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not MIN_AUTO_TEMPERATURE <= float(value) <= MAX_AUTO_TEMPERATURE
                or not math.isclose(
                    float(value) / TARGET_TEMPERATURE_STEP,
                    round(float(value) / TARGET_TEMPERATURE_STEP),
                    abs_tol=1e-7,
                )
            ):
                raise ControlNotReadyError
            validated[key] = float(value)
        return validated

    @staticmethod
    def _latest_revision(first: str | None, second: str | None) -> str | None:
        if first is None:
            return second
        if second is None:
            return first
        return max(first, second)

    @staticmethod
    def _settings_payload(baseline: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
        payload = copy.deepcopy(baseline)
        payload.update(copy.deepcopy(changes))
        return payload

    def _settings_snapshot_is_canonical_echo(
        self,
        incoming: dict[str, Any],
        *,
        permitted_changes: frozenset[str] = frozenset(),
    ) -> bool:
        """Return whether a full upload is the firmware's no-op GET echo."""

        if self.settings_snapshot is None:
            return False

        def control_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
            projected = copy.deepcopy(snapshot)
            # These fields report room observations rather than state supplied
            # by Settings GET. They can legitimately drift between the GET and
            # the firmware's unconditional follow-up saveSettings() upload.
            for key in ("current_temp", "current_humidity", "co2_id"):
                projected.pop(key, None)
            for key in permitted_changes:
                projected.pop(key, None)
            system = projected.get("system")
            if isinstance(system, dict):
                # Exact 1.5.8 live traffic proved RSSI can drift across an
                # otherwise identical echo. No other system field is exempt.
                system.pop("wifiStrength", None)
            return projected

        return control_projection(incoming) == control_projection(self.settings_snapshot)

    def _with_live_data_command(
        self, settings: dict[str, Any], *, command_time: str | None = None
    ) -> dict[str, Any]:
        payload = copy.deepcopy(settings)
        payload["command"] = "push_live_data"
        payload["command_time"] = (
            command_time or self.live_data_command_time or self.settings_revision or "local"
        )
        return payload

    @staticmethod
    def _auto_payload(baseline: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
        payload = copy.deepcopy(baseline)
        payload.update(copy.deepcopy(changes))
        return payload

    def _merge_settings_into_state(
        self,
        settings: dict[str, Any],
        revision: str,
        *,
        observed_at: datetime | None = None,
    ) -> None:
        current = self.state
        accept_temperature = observed_at is not None and (
            self.current_temperature_observed_at is None
            or observed_at >= self.current_temperature_observed_at
        )
        if accept_temperature:
            self.current_temperature_observed_at = observed_at
            self.current_temperature_source = "settings"
        target_temperature = float(settings["temp"])
        if (
            current.schedule_type in ACTIVE_SCHEDULE_TYPES
            and current.target_temperature is not None
        ):
            # With a synced local schedule and no temperature hold, exact QML
            # uploads the active schedule's temperature. An invalid
            # server schedule sentinel marks activity refresh as needed; during
            # that interval the same upload falls back to requestedTemp. Monitor
            # telemetry remains the authority for the effective scheduled target.
            target_temperature = current.target_temperature
        self.async_update_state(
            replace(
                current,
                target_temperature=target_temperature,
                current_temperature=(
                    float(settings["current_temp"])
                    if accept_temperature
                    else current.current_temperature
                ),
                current_humidity=(
                    float(settings["current_humidity"])
                    if observed_at is not None
                    else current.current_humidity
                ),
                mode=NuveMode(settings["mode_id"]),
                settings_revision=revision,
            )
        )

    def _merge_auto_into_state(self, settings: dict[str, Any], revision: str) -> None:
        self.async_update_state(
            replace(
                self.state,
                auto_temperature_low=float(settings["auto_temp_low"]),
                auto_temperature_high=float(settings["auto_temp_high"]),
                settings_revision=revision,
            )
        )

    def _live_state_matches_baselines(self) -> bool:
        """Require whole-snapshot baselines to agree with fresh telemetry."""

        assert self.settings_snapshot is not None
        assert self.auto_mode_snapshot is not None
        system = self.settings_snapshot.get("system")
        expected_system_type = system.get("type") if isinstance(system, dict) else None
        state_system_type = self.state.system_type
        actual_system_type = (
            SYSTEM_TYPE_NAMES.get(state_system_type) if state_system_type is not None else None
        )
        return (
            self._matches(
                {
                    "temp": self.state.target_temperature,
                    "humidity": self.state.target_humidity,
                    "mode_id": int(self.state.mode) if self.state.mode is not None else None,
                },
                {
                    "temp": self.settings_snapshot.get("temp"),
                    "humidity": self.settings_snapshot.get("humidity"),
                    "mode_id": self.settings_snapshot.get("mode_id"),
                },
            )
            and actual_system_type == expected_system_type
            and self._matches(
                {
                    "auto_temp_low": self.state.auto_temperature_low,
                    "auto_temp_high": self.state.auto_temperature_high,
                },
                self.auto_mode_snapshot,
            )
        )

    @staticmethod
    def _pending_blocks_monitor_field(
        pending: PendingCommand | None,
        *,
        kind: Literal["settings", "auto"],
        field: str,
        evidence_is_post_queue: bool,
    ) -> bool:
        """Keep pre-command monitor evidence from replacing a queued field."""

        return bool(
            pending is not None
            and pending.kind == kind
            and field in pending.desired
            and not evidence_is_post_queue
        )

    def _merge_monitor_settings_baseline(
        self,
        state: NuveState,
        *,
        seen_at: datetime,
        pending: PendingCommand | None,
        evidence_is_post_queue: bool,
    ) -> bool:
        """Merge Settings-owned monitor fields into the durable baseline."""

        snapshot = self.settings_snapshot
        if snapshot is None:
            return False
        candidates = {
            "temp": state.target_temperature,
            "mode_id": int(state.mode) if state.mode is not None else None,
        }
        updates = {
            key: value
            for key, value in candidates.items()
            if value is not None
            and not self._pending_blocks_monitor_field(
                pending,
                kind="settings",
                field=key,
                evidence_is_post_queue=evidence_is_post_queue,
            )
        }
        if self._valid_humidity(state.target_humidity):
            updates["humidity"] = state.target_humidity

        changed = False
        for key, value in updates.items():
            if snapshot.get(key) == value:
                continue
            snapshot[key] = value
            if pending is not None and pending.kind == "settings" and not pending.delivered:
                pending.payload[key] = value
            changed = True
        if not changed:
            return False

        self.settings_revision = next_revision(
            self._latest_revision(self.settings_revision, self.settings_revision_floor),
            now=seen_at,
        )
        self.settings_revision_floor = self.settings_revision
        self.state = replace(self.state, settings_revision=self.settings_revision)
        return True

    def _merge_monitor_auto_baseline(
        self,
        state: NuveState,
        *,
        seen_at: datetime,
        pending: PendingCommand | None,
        evidence_is_post_queue: bool,
    ) -> bool:
        """Merge Auto-owned monitor fields into the durable baseline."""

        snapshot = self.auto_mode_snapshot
        if snapshot is None and (
            state.monitor_is_sync
            and state.auto_temperature_low is not None
            and state.auto_temperature_high is not None
            and self._valid_auto_pair(state.auto_temperature_low, state.auto_temperature_high)
        ):
            self.auto_mode_snapshot = {
                "auto_temp_low": state.auto_temperature_low,
                "auto_temp_high": state.auto_temperature_high,
            }
            snapshot = self.auto_mode_snapshot
            changed = True
        elif snapshot is None:
            return False
        else:
            candidates = {
                "auto_temp_low": state.auto_temperature_low,
                "auto_temp_high": state.auto_temperature_high,
            }
            updates = {
                key: value
                for key, value in candidates.items()
                if value is not None
                and not self._pending_blocks_monitor_field(
                    pending,
                    kind="auto",
                    field=key,
                    evidence_is_post_queue=evidence_is_post_queue,
                )
            }
            prospective = copy.deepcopy(snapshot)
            prospective.update(updates)
            if not self._valid_auto_pair(
                prospective.get("auto_temp_low"), prospective.get("auto_temp_high")
            ):
                return False
            changed = False
            for key, value in updates.items():
                if snapshot.get(key) == value:
                    continue
                snapshot[key] = value
                if pending is not None and pending.kind == "auto" and not pending.delivered:
                    pending.payload[key] = value
                changed = True
        if not changed:
            return False

        self.auto_mode_revision = next_revision(
            self._latest_revision(
                self._latest_revision(self.settings_revision, self.settings_revision_floor),
                self._latest_revision(self.auto_mode_revision, self.auto_revision_floor),
            ),
            now=seen_at,
        )
        self.auto_revision_floor = self.auto_mode_revision
        return True

    def _merge_monitor_into_baselines(self, state: NuveState) -> bool:
        """Keep future whole-snapshot writes aligned with device-local changes."""

        assert state.sample_time is not None
        seen_at = state.sample_time
        pending = self._pending_command
        evidence_is_post_queue = bool(
            pending is not None
            and not pending.delivered
            and state.sample_time
            > pending.queued_at + timedelta(seconds=MONITOR_FUTURE_SKEW_SECONDS)
        )
        changed = self._merge_monitor_settings_baseline(
            state,
            seen_at=seen_at,
            pending=pending,
            evidence_is_post_queue=evidence_is_post_queue,
        )
        if self._merge_monitor_auto_baseline(
            state,
            seen_at=seen_at,
            pending=pending,
            evidence_is_post_queue=evidence_is_post_queue,
        ):
            changed = True

        if self._reconcile_undelivered_pending_from_monitor(state):
            changed = True

        if changed:
            self._notify_listeners()
        return changed

    def _reconcile_undelivered_pending_from_monitor(self, state: NuveState) -> bool:
        """Resolve a queued write when later device evidence changes its baseline."""

        pending = self._pending_command
        if (
            pending is None
            or pending.delivered
            or state.sample_time is None
            or state.sample_time
            <= pending.queued_at + timedelta(seconds=MONITOR_FUTURE_SKEW_SECONDS)
        ):
            return False

        actual: dict[str, Any] = {}
        if pending.kind == "settings":
            if "temp" in pending.desired and state.target_temperature is not None:
                actual["temp"] = state.target_temperature
            if "mode_id" in pending.desired and state.mode is not None:
                actual["mode_id"] = int(state.mode)
        else:
            if "auto_temp_low" in pending.desired and state.auto_temperature_low is not None:
                actual["auto_temp_low"] = state.auto_temperature_low
            if "auto_temp_high" in pending.desired and state.auto_temperature_high is not None:
                actual["auto_temp_high"] = state.auto_temperature_high

        if not actual:
            return False
        if set(actual) == set(pending.desired) and self._matches(pending.desired, actual):
            self._complete_pending("confirmed")
            return True
        if any(
            not self._matches({key: pending.queued_baseline[key]}, {key: value})
            for key, value in actual.items()
        ):
            self._complete_pending("state_changed")
            return True
        return False

    def _resolve_uncertainty_from_monitor(self, state: NuveState) -> bool:
        """Clear uncertainty only from a complete field-owning monitor snapshot."""

        uncertain = self.uncertain_command
        pending = self._pending_command
        if (
            uncertain is None
            or uncertain.delivered_at is None
            or (pending is not None and pending.delivered and pending.kind == uncertain.kind)
            or not state.monitor_is_sync
            or state.sample_time is None
            or state.sample_time <= uncertain.delivered_at
        ):
            return False
        # A full monitor owns the active temperature/mode and Auto bounds, but
        # not the configured fan mode, circulation minutes, or hold map. Those
        # fan fields can be resolved only by a later complete Settings upload.
        # Keep unknown future Settings fields fail-closed for the same reason.
        if uncertain.kind == "settings":
            if not set(uncertain.desired).issubset({"temp", "mode_id"}):
                return False
            complete_family = state.target_temperature is not None and state.mode is not None
        else:
            complete_family = (
                uncertain.kind == "auto"
                and state.auto_temperature_low is not None
                and state.auto_temperature_high is not None
            )
        if complete_family:
            self.uncertain_command = None
            self._notify_listeners()
            return True
        return False

    @staticmethod
    def _serialize_uncertainty(uncertain: UncertainCommand) -> dict[str, Any]:
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

    def _confirm_from_monitor(self, state: NuveState) -> bool:
        pending = self._pending_command
        if (
            pending is None
            or not pending.delivered
            or pending.delivered_at is None
            or state.sample_time is None
            or not self._monitor_evidence_is_post_delivery(state, pending)
        ):
            return False
        if pending.kind == "settings":
            actual: dict[str, Any] = {}
            if state.target_temperature is not None:
                actual["temp"] = state.target_temperature
            if state.mode is not None:
                actual["mode_id"] = int(state.mode)
            if not self._matches(pending.desired, actual):
                return False
            confirmed_revision = next_revision(
                self._latest_revision(
                    self.settings_revision_floor,
                    self._latest_revision(self.settings_revision, pending.revision),
                ),
                now=state.sample_time,
            )
            assert self.settings_snapshot is not None
            confirmed_settings = copy.deepcopy(self.settings_snapshot)
            confirmed_settings.update(copy.deepcopy(pending.desired))
            self.settings_snapshot = confirmed_settings
            self.settings_revision = confirmed_revision
            self.settings_revision_floor = confirmed_revision
            self.live_data_command_time = pending.revision
            self.state = replace(self.state, settings_revision=confirmed_revision)
        else:
            actual = {}
            if state.auto_temperature_low is not None:
                actual["auto_temp_low"] = state.auto_temperature_low
            if state.auto_temperature_high is not None:
                actual["auto_temp_high"] = state.auto_temperature_high
            if not self._matches(pending.desired, actual):
                return False
            confirmed_revision = next_revision(
                self._latest_revision(
                    self.auto_revision_floor,
                    self._latest_revision(self.auto_mode_revision, pending.revision),
                ),
                now=state.sample_time,
            )
            assert self.auto_mode_snapshot is not None
            confirmed_auto = copy.deepcopy(self.auto_mode_snapshot)
            confirmed_auto.update(copy.deepcopy(pending.desired))
            self.auto_mode_snapshot = confirmed_auto
            self.auto_mode_revision = confirmed_revision
            self.auto_revision_floor = confirmed_revision
        self.uncertain_command = None
        self._complete_pending("confirmed")
        return True

    @staticmethod
    def _monitor_evidence_is_post_delivery(
        state: NuveState,
        pending: PendingCommand,
    ) -> bool:
        """Order monitor evidence across device-second and server-subsecond clocks."""

        assert pending.delivered_at is not None
        assert state.sample_time is not None
        if state.sample_time > pending.delivered_at:
            return True

        echo_received_at = pending.coherent_echo_received_at
        if (
            echo_received_at is None
            or state.last_seen is None
            or echo_received_at <= pending.delivered_at
            or state.last_seen <= echo_received_at
        ):
            return False

        # Firmware emits protobuf Timestamp seconds without a useful
        # subsecond component. A matching monitor record from the delivery
        # second can therefore sort before the server's microsecond boundary.
        # Accept it only after a coherent post-delivery full Settings echo and
        # a later monitor HTTP receipt establish the missing causal order.
        delivery_second = pending.delivered_at.replace(microsecond=0)
        return state.sample_time >= delivery_second

    def _complete_pending(self, result: str) -> None:
        pending = self._pending_command
        if pending is None:
            return
        self._pending_command = None
        self._trace_event(
            "command",
            family=pending.kind,
            result=result,
            duration_ms=self._elapsed_ms(pending.queued_at, datetime.now(UTC)),
        )
        self._notify_listeners()
        if not pending.future.done():
            pending.future.set_result(result)

    def _trace_monitor_result(
        self,
        pending: PendingCommand | None,
        pending_kind: Literal["settings", "auto"] | None,
    ) -> None:
        """Record whether one monitor transaction resolved the active command."""

        if pending is None:
            return
        result = (
            pending.future.result()
            if pending.future.done() and not pending.future.cancelled()
            else "not_confirmed"
        )
        self._trace_event("monitor_confirmation", family=pending_kind, result=result)
        if result != "not_confirmed":
            self._trace_event(
                "command",
                family=pending_kind,
                result=result,
                duration_ms=self._elapsed_ms(pending.queued_at, datetime.now(UTC)),
            )

    @staticmethod
    def _elapsed_ms(started_at: datetime, finished_at: datetime) -> int:
        return max(0, round((finished_at - started_at).total_seconds() * 1000))

    def _trace_elapsed_event(
        self,
        event: str,
        started_at: datetime,
        *,
        family: Literal["settings", "auto", "monitor"] | None,
        result: str,
    ) -> None:
        finished_at = datetime.now(UTC)
        self._trace_event(
            event,
            family=family,
            result=result,
            duration_ms=self._elapsed_ms(started_at, finished_at),
            at=finished_at,
        )

    def _trace_event(
        self,
        event: str,
        *,
        family: Literal["settings", "auto", "monitor"] | None = None,
        result: str | None = None,
        duration_ms: int | None = None,
        at: datetime | None = None,
    ) -> None:
        if not self._trace_enabled:
            return
        timestamp = at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        self._event_trace.append(
            RuntimeTraceEvent(
                timestamp=timestamp.astimezone(UTC),
                event=event,
                family=family,
                result=result,
                duration_ms=duration_ms,
            )
        )

    def _trace_control_block_transition(self) -> None:
        if not self._trace_enabled:
            return
        reason = self.control_block_reason
        if reason == self._last_traced_control_block_reason:
            return
        self._last_traced_control_block_reason = reason
        self._trace_event("control_block_reason", result=reason)

    @staticmethod
    def _valid_technician_url(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) <= 2048
            and not any(ord(character) < 32 for character in value)
        )

    def _effective_technician_url(self) -> str | None:
        """Use a configured QR target only after baseline capture is complete."""

        if self.has_settings_baseline and self._valid_technician_url(self.contractor_url):
            return self.contractor_url
        return self.bootstrap_technician_url

    @staticmethod
    def _valid_auto_pair(low: Any, high: Any) -> bool:
        values = (low, high)
        return all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and MIN_DEVICE_TEMPERATURE <= float(value) <= MAX_DEVICE_TEMPERATURE
            for value in values
        ) and float(low) < float(high)

    @staticmethod
    def _valid_humidity(value: Any) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and 0 <= float(value) <= 100
        )

    def async_note_authenticated_contact(self, seen_at: datetime) -> None:
        """Record an authenticated request and reset the liveness timer."""

        self.state = replace(self.state, available=True, last_seen=seen_at)
        self._notify_listeners()
        if self._liveness_timer is not None:
            self._liveness_timer.cancel()
        self._liveness_timer = asyncio.get_running_loop().call_later(
            LIVENESS_TIMEOUT_SECONDS, self._async_mark_unavailable
        )

    def _async_mark_unavailable(self) -> None:
        self._liveness_timer = None
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

        if (
            temperature_c is None
            or not math.isfinite(temperature_c)
            or not -90 <= temperature_c <= 65
        ):
            self.outdoor_temperature_c = None
            self.outdoor_observed_at = None
            self.outdoor_humidity_percent = None
            self.outdoor_weather = None
            self.outdoor_location_name = name
            self.outdoor_source = "unavailable"
            self._notify_listeners()
            return
        if humidity_percent is not None and (
            not math.isfinite(humidity_percent) or not 0 <= humidity_percent <= 100
        ):
            humidity_percent = None
        if (
            not isinstance(weather, dict)
            or set(weather) != {"icon", "description"}
            or not all(isinstance(value, str) and value for value in weather.values())
        ):
            weather = None
        self.outdoor_temperature_c = temperature_c
        self.outdoor_observed_at = observed_at or datetime.now(UTC)
        self.outdoor_humidity_percent = humidity_percent
        self.outdoor_weather = copy.deepcopy(weather)
        self.outdoor_location_name = name
        self.outdoor_source = source
        self._notify_listeners()

    def async_set_forecast(
        self,
        payload: dict[str, Any] | None,
        *,
        status: str,
        updated_at: datetime | None = None,
    ) -> None:
        """Cache one already validated forecast or select the firmware-safe no-op."""

        self.forecast_payload = copy.deepcopy(payload) if payload is not None else None
        self.forecast_status = status
        self.forecast_updated_at = updated_at or datetime.now(UTC)
        self._notify_listeners()

    async def async_shutdown(self) -> None:
        """Cancel ephemeral callbacks without erasing durable safety journals."""

        async with self._transaction_lock:
            self._stopped = True
            if self._automatic_bootstrap_task is not None:
                self._automatic_bootstrap_task.cancel()
                self._automatic_bootstrap_task = None
            if self._liveness_timer is not None:
                self._liveness_timer.cancel()
                self._liveness_timer = None
            if self._bootstrap_timer is not None:
                self._bootstrap_timer.cancel()
                self._bootstrap_timer = None
            if self._pending_command is not None:
                self._complete_pending("stopped")
            self._listeners.clear()

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
