#!/usr/bin/env python3
"""Independent exact-1.5.8 equipment-performance-test model.

This is offline research tooling.  It models recovered scheduling, packet,
persistence, timer, and logical-relay behavior without importing Nuve Local or
contacting a thermostat or vendor service.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, time, timedelta
from enum import IntEnum, StrEnum
from typing import Any

CHECK_JITTER_SECONDS = 900
POSTPONE_SECONDS = 43_200
READING_INTERVAL_SECONDS = 15
RUN_SECONDS = 900
COMPLETE_SECONDS = 300
SAVED_RETRY_SECONDS = 300
COOLING_TARGET_C = 4.444444444444445
HEATING_TARGET_C = 32.22222222222222


class SystemType(IntEnum):
    CONVENTIONAL = 0
    HEAT_PUMP = 1
    COOLING_ONLY = 2
    HEATING_ONLY = 3
    DUAL_FUEL_HEATING = 4
    UNKNOWN = 5


class SystemMode(IntEnum):
    COOLING = 0
    HEATING = 1
    AUTO = 2
    VACATION = 3
    OFF = 4
    EMERGENCY_HEAT = 5
    EMERGENCY = 6
    UNKNOWN = 7


class TestState(IntEnum):
    __test__ = False

    IDLE = 0
    CHECKING = 1
    ELIGIBLE = 2
    WARMUP = 3
    RUNNING = 4
    COMPLETE = 5


class ResultType(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    FINISHED = "finished"


class RelayValue(IntEnum):
    ON = 1
    OFF = 2


@dataclass(frozen=True)
class EligibilityDisposition:
    outcome: str
    test_id: int = 0
    mode: SystemMode = SystemMode.OFF
    send_running: bool = False
    postpone_seconds: int | None = None


@dataclass(frozen=True)
class UploadDisposition:
    clear_saved_result: bool
    retry_saved_after_seconds: int | None
    start_hardware_test: bool


@dataclass(frozen=True)
class SavedResultDisposition:
    valid: bool
    remove_saved_keys: bool
    serial: str = ""
    expiry_days: int | None = None


@dataclass(frozen=True)
class RelaySnapshot:
    """The ten named physical terminals in ``RelayConfigs::printStr`` order."""

    g: RelayValue = RelayValue.OFF
    y1: RelayValue = RelayValue.OFF
    y2: RelayValue = RelayValue.OFF
    acc2: RelayValue = RelayValue.OFF
    w1: RelayValue = RelayValue.OFF
    w2: RelayValue = RelayValue.OFF
    w3: RelayValue = RelayValue.OFF
    ob: RelayValue = RelayValue.OFF
    acc1p: RelayValue = RelayValue.OFF
    acc1n: RelayValue = RelayValue.OFF


def _bounded_900(random32: int) -> int:
    if not 0 <= random32 <= 0xFFFF_FFFF:
        raise ValueError("random32 must be an unsigned 32-bit integer")
    return (random32 * CHECK_JITTER_SECONDS) >> 32


def schedule_next_check(now: datetime, requested: time, *, random32: int) -> datetime:
    """Model ``scheduleNextCheck`` and Qt ``QRandomGenerator::bounded(900)``."""

    requested = requested.replace(tzinfo=None)
    now_time = now.time().replace(tzinfo=None)
    if requested <= now_time:
        requested = (now + timedelta(seconds=10)).time().replace(tzinfo=None)

    target = datetime.combine(now.date(), requested, tzinfo=now.tzinfo)
    ten_am = datetime.combine(now.date(), time(10), tzinfo=now.tzinfo)
    cutoff = datetime.combine(now.date(), time(11, 45), tzinfo=now.tzinfo)
    jitter = timedelta(seconds=_bounded_900(random32))

    if target > cutoff:
        return ten_am + timedelta(days=1) + jitter
    if requested <= time(10):
        return ten_am + jitter
    return target


def _json_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def decode_eligibility(
    *,
    network_ok: bool,
    payload: dict[str, Any],
    system_type: SystemType,
    saved_test_id: int | None = None,
    postponed: bool = False,
) -> EligibilityDisposition:
    """Model the schedule callback's coercion, compatibility, and postpone gates."""

    if not network_ok:
        return EligibilityDisposition("network_error")

    test_id = _json_int(payload.get("perftest_id"))
    if saved_test_id is not None and saved_test_id == test_id:
        return EligibilityDisposition("saved_result_pending", test_id=test_id)

    action = payload.get("action") if isinstance(payload.get("action"), str) else ""
    mode = {
        "cooling": SystemMode.COOLING,
        "heating": SystemMode.HEATING,
    }.get(action, SystemMode.OFF)

    incompatible = (mode is SystemMode.HEATING and system_type is SystemType.COOLING_ONLY) or (
        mode is SystemMode.COOLING and system_type is SystemType.HEATING_ONLY
    )
    if incompatible:
        return EligibilityDisposition("incompatible", test_id=test_id, mode=mode)
    if mode is SystemMode.OFF or test_id <= 0:
        return EligibilityDisposition("none", test_id=test_id, mode=mode)
    if postponed:
        return EligibilityDisposition(
            "eligible_postponed",
            test_id=test_id,
            mode=mode,
            postpone_seconds=POSTPONE_SECONDS,
        )
    return EligibilityDisposition("eligible", test_id=test_id, mode=mode, send_running=True)


def target_temperature_c(mode: SystemMode) -> float:
    if mode is SystemMode.COOLING:
        return COOLING_TARGET_C
    if mode is SystemMode.HEATING:
        return HEATING_TARGET_C
    return 0.0


def build_result(
    *,
    test_id: int,
    serial: str,
    mode: SystemMode,
    result: ResultType,
    when: datetime,
    readings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the exact result member set.  The wire key is ``time``."""

    action = "cooling" if mode is SystemMode.COOLING else "heating"
    packet: dict[str, Any] = {
        "perftest_id": test_id,
        "sn": serial,
        "action": action,
        "result": result.value,
        "time": when.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
    }
    if result is ResultType.FINISHED:
        packet["data"] = [] if readings is None else readings
    return packet


def result_upload_disposition(
    *, result: ResultType, network_ok: bool, saved_retry_active: bool = False
) -> UploadDisposition:
    """Model the callback, including its acknowledgement-independent start."""

    return UploadDisposition(
        clear_saved_result=network_ok,
        retry_saved_after_seconds=(
            SAVED_RETRY_SECONDS
            if not network_ok and result is ResultType.FINISHED and not saved_retry_active
            else None
        ),
        start_hardware_test=result is ResultType.RUNNING,
    )


def inspect_saved_result(
    payload: Any,
    *,
    now: datetime,
    startup: bool,
    saved_test_id_present: bool,
) -> SavedResultDisposition:
    """Model saved-result validation and its 1-day/30-day retention split."""

    if startup and not saved_test_id_present:
        return SavedResultDisposition(False, False)
    if not isinstance(payload, dict):
        return SavedResultDisposition(False, True)

    serial = payload.get("sn") if isinstance(payload.get("sn"), str) else ""
    timestamp = payload.get("time") if isinstance(payload.get("time"), str) else ""
    try:
        saved_at = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return SavedResultDisposition(False, True)

    expiry_days = 30 if "data" in payload else 1
    # Qt 6.4 QDateTime::daysTo delegates to QDate::daysTo: it counts calendar
    # midnights, not complete 24-hour periods.  Both dates are firmware UTC
    # strings even though the parsed value carries no serialized zone marker.
    calendar_days = (now.astimezone(UTC).date() - saved_at.date()).days
    if calendar_days > expiry_days:
        return SavedResultDisposition(False, True, expiry_days=expiry_days)
    return SavedResultDisposition(True, False, serial=serial, expiry_days=expiry_days)


def cooling_stage(stage: int) -> RelaySnapshot:
    if stage == 1:
        return RelaySnapshot(y1=RelayValue.ON)
    if stage == 2:
        return RelaySnapshot(y1=RelayValue.ON, y2=RelayValue.ON)
    raise ValueError("cooling stage must be 1 or 2")


def heating_stage(stage: int, *, heat_pump: bool) -> RelaySnapshot:
    if stage == 1:
        return RelaySnapshot(y1=RelayValue.ON) if heat_pump else RelaySnapshot(w1=RelayValue.ON)
    if stage == 2:
        return (
            RelaySnapshot(y1=RelayValue.ON, y2=RelayValue.ON)
            if heat_pump
            else RelaySnapshot(w1=RelayValue.ON, w2=RelayValue.ON)
        )
    if stage == 3:
        return RelaySnapshot(w1=RelayValue.ON, w2=RelayValue.ON, w3=RelayValue.ON)
    raise ValueError("heating stage must be 1, 2, or 3")


def auxiliary_heating_stage(stage: int, *, argument: bool) -> RelaySnapshot:
    if stage == 1:
        return RelaySnapshot(w1=RelayValue.ON, w3=RelayValue.ON if argument else RelayValue.OFF)
    if stage == 2:
        value = RelayValue.ON if argument else RelayValue.OFF
        return RelaySnapshot(w1=value, w2=value)
    raise ValueError("auxiliary heating stage must be 1 or 2")


def finalize_relays(
    relays: RelaySnapshot,
    *,
    effective_mode: SystemMode,
    ob_on_mode: SystemMode,
    circulation: bool = False,
    dissipation: bool = False,
    thermostat_controls_heating_fan: bool = True,
    accessories_control_fan: bool = True,
) -> RelaySnapshot:
    """Apply the exact final O/B calculation and fan arbitration predicates."""

    heating_fan = thermostat_controls_heating_fan and (
        relays.w1 is RelayValue.ON or relays.w3 is RelayValue.ON
    )
    accessory_fan = accessories_control_fan and (
        relays.acc2 is RelayValue.ON
        or relays.acc1p is RelayValue.ON
        or relays.acc1n is RelayValue.ON
    )
    g_on = circulation or dissipation or relays.y1 is RelayValue.ON or heating_fan or accessory_fan
    ob_on = (
        effective_mode not in (SystemMode.UNKNOWN, SystemMode.OFF) and ob_on_mode is effective_mode
    )
    return replace(
        relays,
        g=RelayValue.ON if g_on else RelayValue.OFF,
        ob=RelayValue.ON if ob_on else RelayValue.OFF,
    )


@dataclass
class PerformanceTestRun:
    """Timer-level model of one already-authorized firmware test run."""

    test_id: int
    serial: str
    mode: SystemMode
    state: TestState = TestState.ELIGIBLE
    is_test_running: bool = False
    is_postponed: bool = False
    eligible_while_postponed: bool = False
    start_time_left: int = 0
    test_time_left: int = 0
    finish_time_left: int = 0
    readings: list[dict[str, Any]] = field(default_factory=list)

    def start_warmup(self) -> None:
        self.is_test_running = True
        self.state = TestState.WARMUP

    def countdown_start(self, delay_ms: int) -> None:
        self.start_time_left = delay_ms // 1000
        self.state = TestState.WARMUP

    def countdown_tick(self) -> None:
        if self.start_time_left > 0:
            self.start_time_left -= 1

    def start_running(self) -> None:
        if self.state is TestState.RUNNING:
            return
        self.start_time_left = 0
        self.test_time_left = RUN_SECONDS
        self.state = TestState.RUNNING

    def collect(self, *, temperature_f: float, when: datetime) -> bool:
        if self.state is not TestState.RUNNING:
            raise RuntimeError("readings are collected only while Running")
        self.test_time_left -= READING_INTERVAL_SECONDS
        self.readings.append(
            {
                "timestamp": when.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                "temperature": (temperature_f - 32.0) / 1.8,
            }
        )
        if self.test_time_left > 0:
            return False
        self.is_test_running = False
        self.finish_time_left = COMPLETE_SECONDS
        self.state = TestState.COMPLETE
        return True

    def finished_packet(self, *, when: datetime) -> dict[str, Any]:
        if self.state is not TestState.COMPLETE:
            raise RuntimeError("finished result is available only after collection completes")
        return build_result(
            test_id=self.test_id,
            serial=self.serial,
            mode=self.mode,
            result=ResultType.FINISHED,
            when=when,
            readings=self.readings,
        )

    def completion_tick(self) -> bool:
        if self.state is not TestState.COMPLETE:
            return False
        if self.finish_time_left < 1:
            self.state = TestState.IDLE
            return True
        self.finish_time_left -= 1
        return False

    def postpone(self) -> bool:
        if self.state >= TestState.WARMUP:
            return False
        self.is_postponed = True
        return True

    def resume(self) -> bool:
        if not self.is_postponed:
            return False
        self.is_postponed = False
        should_send_running = self.eligible_while_postponed
        self.eligible_while_postponed = False
        return should_send_running

    def cancel(self) -> dict[str, Any]:
        self.is_test_running = False
        self.readings.clear()
        self.state = TestState.IDLE
        return build_result(
            test_id=self.test_id,
            serial=self.serial,
            mode=self.mode,
            result=ResultType.STOPPED,
            when=datetime.now(UTC),
        )
