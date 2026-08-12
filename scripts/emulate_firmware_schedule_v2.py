#!/usr/bin/env python3
"""Independent exact-1.5.8 schedule-v2 contract model.

This is research tooling, not Home Assistant runtime code. It intentionally models
the firmware's observable packet/coercion rules without importing Nuve Local.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from time import strptime
from typing import Any

MAX_ACTIVITIES_PER_DAY = 12
C_VERSION_1 = 1
C_VERSION_2 = 2
DAY_TOKEN_BY_WEEKDAY = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
KNOWN_EXPLICIT_HOLD_PERIOD_CALLERS = (
    "DeviceController Settings handler",
    "HoldScheduleV2Popup acceptance handler",
)


class HoldType(IntEnum):
    """Exact native bit values."""

    NONE = 0
    TEMPERATURE = 1
    FAN = 2
    ALL = 3


class HoldPeriod(IntEnum):
    """Exact declarative AppSpec.qml values."""

    TWO_HOURS = 0
    FOUR_HOURS = 1
    UNTIL_NEXT_ACTIVITY = 2
    UNTIL_CHANGED = 3
    UNKNOWN = 4


class DeliveryState(StrEnum):
    """What the client knows about an attempted request."""

    NOT_DELIVERED = "not_delivered"
    DELIVERED = "delivered"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FetchReply:
    accepted: bool
    schedules: tuple[Any, ...]


@dataclass(frozen=True)
class AddReply:
    accepted: bool
    server_id: Any | None
    has_server_id: bool


@dataclass(frozen=True)
class ClearReply:
    accepted: bool
    malformed_errors_accepted: bool


@dataclass(frozen=True)
class SerializedSchedule:
    packet: dict[str, Any]
    normalized_local: dict[str, Any]


@dataclass(frozen=True)
class ExpandedSchedules:
    accepted: tuple[dict[str, Any], ...]
    capacity_rejected_days: tuple[str, ...]


@dataclass(frozen=True)
class ActivityMatch:
    schedule: Mapping[str, Any]
    start: datetime
    day_offset: int


@dataclass(frozen=True)
class NativeClearCall:
    schedule_id: int
    version: int
    route_generation: str
    intended_generation: str

    @property
    def wrong_route(self) -> bool:
        return self.route_generation != self.intended_generation


@dataclass(frozen=True)
class HoldAddCall:
    hold_bits: int
    native_hold_written: bool
    period_value: HoldPeriod | None
    period_changed: bool
    start_time_written: bool
    next_activity_recomputed: bool
    server_push_attempted: bool
    settings_saved: bool


@dataclass(frozen=True)
class RestoredHoldState:
    hold_type: int
    hold_period: dict[str, Any]
    hold_start_time: dict[str, Any]
    cleared_for_no_enabled_activity: bool


def _json_object(payload: Any) -> Mapping[str, Any]:
    return payload if isinstance(payload, Mapping) else {}


def decode_fetch_reply(*, network_ok: bool, payload: Any) -> FetchReply:
    """Model Sync::getSchedules2 completion coercion.

    A non-empty outer object plus network success is accepted. The ``data`` member
    is coerced with QJsonValue::toArray(), so missing or wrong-type data is an
    accepted empty array.
    """

    outer = _json_object(payload)
    if not network_ok or not outer:
        return FetchReply(accepted=False, schedules=())
    data = outer.get("data")
    return FetchReply(
        accepted=True,
        schedules=tuple(data) if isinstance(data, list) else (),
    )


def decode_add_reply(*, network_ok: bool, payload: Any) -> AddReply:
    """Model Sync::addSchedule2 completion and its missing-id weakness."""

    outer = _json_object(payload)
    accepted = network_ok and bool(outer)
    has_server_id = accepted and "id" in outer
    return AddReply(
        accepted=accepted,
        server_id=outer.get("id") if has_server_id else None,
        has_server_id=has_server_id,
    )


def decode_clear_reply(*, network_ok: bool, payload: Any) -> ClearReply:
    """Model clearSchedule2's permissive ``errors`` array coercion."""

    outer = _json_object(payload)
    if not network_ok:
        return ClearReply(accepted=False, malformed_errors_accepted=False)
    if "errors" not in outer:
        return ClearReply(accepted=True, malformed_errors_accepted=False)
    errors = outer["errors"]
    if isinstance(errors, list):
        return ClearReply(accepted=not errors, malformed_errors_accepted=False)
    return ClearReply(accepted=True, malformed_errors_accepted=True)


def split_repeats(value: Any) -> tuple[str, ...]:
    """Return the firmware-equivalent non-empty comma-separated day tokens."""

    if not isinstance(value, str):
        return ()
    return tuple(day.strip() for day in value.split(",") if day.strip())


def normalize_restored_holds(
    *,
    schedules_v2: Sequence[Mapping[str, Any]],
    hold_type: int,
    hold_period: Mapping[str, Any],
    hold_start_time: Mapping[str, Any],
) -> RestoredHoldState:
    """Model findCurrentSchedules clearing holds with no enabled V2 activity."""

    if not any(bool(row.get("enable")) for row in schedules_v2):
        return RestoredHoldState(0, {}, {}, True)
    return RestoredHoldState(
        hold_type,
        dict(hold_period),
        dict(hold_start_time),
        False,
    )


def convert_12_to_24(value: str) -> str:
    """Convert the schedule UI's exact ``hh:mm AP`` form to a 24-hour string."""

    parsed = strptime(value, "%I:%M %p")
    return f"{parsed.tm_hour:02}:{parsed.tm_min:02}"


def serialize_v2_schedule(row: Mapping[str, Any], *, weekday_index: int) -> SerializedSchedule:
    """Build the exact V2 JSON member set and expose first-day normalization."""

    repeats = split_repeats(row.get("repeats"))
    if not repeats:
        raise ValueError("a V2 schedule requires at least one repeat day")
    normalized = dict(row)
    normalized["repeats"] = repeats[0]
    packet = {
        "is_enable": row["enable"],
        "type": row["type"],
        "start_time": convert_12_to_24(row["startTime"]),
        "heat_to": row["minimumTemperature"],
        "cool_to": row["maximumTemperature"],
        "fan_on": row["fanMode"] == 1,
        "fan_hours": row["fanWorkingPerHour"],
        "weekday": weekday_index,
    }
    return SerializedSchedule(packet=packet, normalized_local=normalized)


def day_activity_count(rows: Sequence[Mapping[str, Any]], day: str) -> int:
    """Count activities using the controller's trimmed, case-insensitive day match."""

    target = day.strip().casefold()
    return sum(
        target in {repeat.casefold() for repeat in split_repeats(row.get("repeats"))}
        for row in rows
    )


def expand_new_schedule(
    row: Mapping[str, Any], existing: Sequence[Mapping[str, Any]]
) -> ExpandedSchedules:
    """Clone one UI row per selected day, skipping days already at the 12-row limit."""

    accepted = []
    rejected = []
    for day in split_repeats(row.get("repeats")):
        if day_activity_count(existing, day) >= MAX_ACTIVITIES_PER_DAY:
            rejected.append(day)
            continue
        clone = dict(row)
        clone["repeats"] = day
        accepted.append(clone)
    return ExpandedSchedules(tuple(accepted), tuple(rejected))


def _local_start(now: datetime, *, day_offset: int, value: str) -> datetime:
    parsed = strptime(value, "%I:%M %p")
    day = now + timedelta(days=day_offset)
    return day.replace(
        hour=parsed.tm_hour,
        minute=parsed.tm_min,
        second=0,
        microsecond=0,
    )


def _activities_for_day(
    rows: Sequence[Mapping[str, Any]], *, day_token: str
) -> tuple[Mapping[str, Any], ...]:
    target = day_token.casefold()
    matching = [
        row
        for row in rows
        if bool(row.get("enable"))
        and target in {day.casefold() for day in split_repeats(row.get("repeats"))}
    ]
    return tuple(sorted(matching, key=lambda row: convert_12_to_24(str(row["startTime"]))))


def find_running_activity(
    rows: Sequence[Mapping[str, Any]], *, now: datetime
) -> ActivityMatch | None:
    """Return the latest enabled activity at or before now within the seven-day walk."""

    for days_back in range(8):
        day = now - timedelta(days=days_back)
        schedules = _activities_for_day(rows, day_token=DAY_TOKEN_BY_WEEKDAY[day.weekday()])
        for row in reversed(schedules):
            start = _local_start(now, day_offset=-days_back, value=str(row["startTime"]))
            if start <= now:
                return ActivityMatch(row, start, -days_back)
    return None


def find_next_activity(
    rows: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    current_schedule: Mapping[str, Any] | None = None,
) -> ActivityMatch | None:
    """Return the first future enabled activity in the controller's eight-day walk."""

    for days_ahead in range(8):
        day = now + timedelta(days=days_ahead)
        schedules = _activities_for_day(rows, day_token=DAY_TOKEN_BY_WEEKDAY[day.weekday()])
        for row in schedules:
            start = _local_start(now, day_offset=days_ahead, value=str(row["startTime"]))
            if row is not current_schedule and start > now:
                return ActivityMatch(row, start, days_ahead)
    return None


def initial_v2_clear_call(schedule_id: int) -> NativeClearCall:
    """Model the explicit two-argument V2 delete call."""

    return NativeClearCall(schedule_id, C_VERSION_2, "v2", "v2")


def retry_v2_clear_call(schedule_id: int) -> NativeClearCall:
    """Model Qt's generated one-argument wrapper used by the retry callback.

    The wrapper supplies integer ``1``. Exact AppSpec QML declares V1 as 1 and V2
    as 2, so the retry is callable but targets the legacy route generation.
    """

    return NativeClearCall(schedule_id, C_VERSION_1, "v1", "v2")


def add_hold(current: int, requested: HoldType) -> int:
    return current | int(requested)


def remove_hold(current: int, requested: HoldType) -> int:
    return current & ~int(requested)


def emulate_add_hold_call(
    current: int,
    requested: HoldType,
    *,
    period: HoldPeriod | None,
    existing_period: HoldPeriod | None = None,
    can_push: bool = True,
) -> HoldAddCall:
    """Model ``addHoldType`` and the misspelled default in ``updateHoldPeriod``.

    ``None`` represents JavaScript ``undefined``. All exact known callers supply a
    real period, but this exposes the dormant omitted-argument behavior.
    """

    bit_was_absent = current & int(requested) == 0
    hold_bits = add_hold(current, requested)
    if existing_period == period:
        return HoldAddCall(
            hold_bits,
            bit_was_absent,
            existing_period,
            False,
            False,
            False,
            False,
            False,
        )
    writes_start = period not in {HoldPeriod.UNKNOWN, HoldPeriod.UNTIL_CHANGED}
    return HoldAddCall(
        hold_bits,
        bit_was_absent,
        period,
        True,
        writes_start,
        period is HoldPeriod.UNTIL_NEXT_ACTIVITY,
        can_push,
        True,
    )


def hold_expired(
    period: HoldPeriod,
    *,
    now: datetime,
    started: datetime | None,
    next_activity: datetime | None = None,
) -> bool:
    """Model the four exact hold-period branches, excluding Qt DST parsing."""

    if period is HoldPeriod.UNTIL_CHANGED:
        return False
    if started is None:
        return False
    if period is HoldPeriod.TWO_HOURS:
        return now - started >= timedelta(hours=2)
    if period is HoldPeriod.FOUR_HOURS:
        return now - started >= timedelta(hours=4)
    if period is HoldPeriod.UNTIL_NEXT_ACTIVITY:
        if next_activity is None:
            return True
        return started < next_activity <= now
    return False


def may_automatically_retry(delivery: DeliveryState) -> bool:
    """Nuve Local safety policy: retry only when non-delivery is established."""

    return delivery is DeliveryState.NOT_DELIVERED
