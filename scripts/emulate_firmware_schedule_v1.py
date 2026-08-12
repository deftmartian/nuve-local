#!/usr/bin/env python3
"""Independent exact-1.5.8 legacy schedule contract model.

This research helper is separate from Nuve Local runtime code. It models the
recovered V1 packet, range, overlap, activation, migration, and reconciliation
rules without importing or changing Nuve Local runtime behavior.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from time import strptime
from typing import Any

DAY_ORDER = ("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")
END_SECOND_ADJUSTMENT = 59


class SystemMode(IntEnum):
    COOLING = 0
    HEATING = 1
    AUTO = 2
    VACATION = 3
    OFF = 4
    EMERGENCY_HEAT = 5
    EMERGENCY = 6
    UNKNOWN = 7


@dataclass(frozen=True)
class V1Reconciliation:
    rows: tuple[dict[str, Any], ...]
    preserved: bool
    removed_ids: tuple[Any, ...]


@dataclass(frozen=True)
class V1RangeSegment:
    """One range used by ``deviceCurrentSchedules`` after overnight splitting."""

    source_index: int
    source_id: Any
    start_second: int
    end_second: int
    running_days: tuple[str, ...]


@dataclass(frozen=True)
class V1Migration:
    """Observable state transition from the legacy-to-V2 migration popup."""

    rows: tuple[dict[str, Any], ...]
    destination: str
    deleting_queue: tuple[int, ...]
    native_clear_calls: tuple[tuple[int, int], ...]
    detached_rows: int
    saved: bool
    converted: bool


@dataclass(frozen=True)
class V1Activation:
    """Selected row, persisted row-side effects, and controller activation result."""

    selected_id: Any | None
    activated_id: Any | None
    rows: tuple[dict[str, Any], ...]
    disabled_ids: tuple[Any, ...]


def _time_24(value: str) -> str:
    parsed = strptime(value, "%I:%M %p")
    return f"{parsed.tm_hour:02}:{parsed.tm_min:02}"


def clock_second(value: str, *, end_time: bool = False) -> int:
    """Parse the controller's ``hh:mm AP`` form to seconds since local midnight.

    The controller explicitly calls ``endTime.setSeconds(59)``. That detail means
    identical start/end minute text is not passed to ``timeInRange`` as an equal
    pair: it becomes a 59-second range.
    """

    parsed = strptime(value, "%I:%M %p")
    return parsed.tm_hour * 3600 + parsed.tm_min * 60 + (END_SECOND_ADJUSTMENT if end_time else 0)


def next_day(day: str) -> str:
    """Return the exact two-letter successor, or the empty-string fallback."""

    try:
        return DAY_ORDER[(DAY_ORDER.index(day) + 1) % len(DAY_ORDER)]
    except ValueError:
        return ""


def previous_day(day: str) -> str:
    try:
        return DAY_ORDER[(DAY_ORDER.index(day) - 1) % len(DAY_ORDER)]
    except ValueError:
        return ""


def split_repeats(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(value.split(",")) if value else ()


def next_day_repeats(value: Any) -> tuple[str, ...]:
    return tuple(next_day(day) for day in split_repeats(value))


def time_in_range(time_second: int, start_second: int, end_second: int) -> bool:
    """Model the exact start-inclusive/end-exclusive helper comparison."""

    if start_second < end_second:
        return start_second <= time_second < end_second
    return time_second >= start_second or time_second < end_second


def _running_days(
    row: Mapping[str, Any], *, current_day: str | None, now_second: int | None
) -> tuple[str, ...]:
    repeats = split_repeats(row.get("repeats"))
    if repeats or current_day is None or now_second is None:
        return repeats
    day = current_day
    start = clock_second(str(row["startTime"]))
    end = clock_second(str(row["endTime"]), end_time=True)
    if bool(row.get("active")) and not time_in_range(now_second, start, end):
        if start < now_second:
            day = next_day(day)
        elif start > now_second:
            day = previous_day(day)
    return (day,)


def expand_v1_ranges(
    rows: Sequence[Mapping[str, Any]],
    *,
    current_day: str | None = None,
    now_second: int | None = None,
) -> tuple[V1RangeSegment, ...]:
    """Expand V1 rows as the controller's ``deviceCurrentSchedules`` array does."""

    expanded: list[V1RangeSegment] = []
    for index, row in enumerate(rows):
        start = clock_second(str(row["startTime"]))
        end = clock_second(str(row["endTime"]), end_time=True)
        days = _running_days(row, current_day=current_day, now_second=now_second)
        if end > start:
            expanded.append(V1RangeSegment(index, row.get("id"), start, end, days))
            continue
        expanded.extend(
            (
                V1RangeSegment(index, row.get("id"), start, 86_399, days),
                V1RangeSegment(
                    index,
                    row.get("id"),
                    0,
                    end,
                    tuple(next_day(day) for day in days),
                ),
            )
        )
    return tuple(expanded)


def _segments_overlap(left: V1RangeSegment, right: V1RangeSegment) -> bool:
    if not set(left.running_days).intersection(right.running_days):
        return False
    return (
        right.start_second < left.start_second < right.end_second
        or left.start_second < right.start_second < left.end_second
        or left.start_second == right.start_second
    )


def find_v1_overlaps(
    rows: Sequence[Mapping[str, Any]],
    candidate: Mapping[str, Any],
    *,
    exclude_id: Any | None = None,
) -> tuple[Any, ...]:
    """Return source ids colliding with a candidate, preserving model order."""

    candidate_segments = expand_v1_ranges((candidate,))
    result: list[Any] = []
    for segment in expand_v1_ranges(rows):
        if segment.source_id == exclude_id or segment.source_id in result:
            continue
        if any(_segments_overlap(segment, new) for new in candidate_segments):
            result.append(segment.source_id)
    return tuple(result)


def _activation_allowed(
    *,
    is_hold: bool,
    system_mode: SystemMode,
    system_shutoff: bool,
    performance_test_running: bool,
) -> bool:
    return not (
        is_hold
        or system_mode in {SystemMode.OFF, SystemMode.EMERGENCY_HEAT}
        or system_shutoff
        or performance_test_running
    )


def find_running_v1_schedule(
    rows: Sequence[Mapping[str, Any]],
    *,
    day: str,
    now_second: int,
    is_hold: bool = False,
    system_mode: SystemMode = SystemMode.AUTO,
    system_shutoff: bool = False,
    performance_test_running: bool = False,
) -> Mapping[str, Any] | None:
    """Return the first matching expanded row when control activation is allowed."""

    if not _activation_allowed(
        is_hold=is_hold,
        system_mode=system_mode,
        system_shutoff=system_shutoff,
        performance_test_running=performance_test_running,
    ):
        return None
    for segment in expand_v1_ranges(rows, current_day=day, now_second=now_second):
        row = rows[segment.source_index]
        if (
            bool(row.get("enable"))
            and day in segment.running_days
            and time_in_range(now_second, segment.start_second, segment.end_second)
        ):
            return row
    return None


def evaluate_v1_activation(
    rows: Sequence[Mapping[str, Any]],
    *,
    day: str,
    now_second: int,
    is_hold: bool = False,
    system_mode: SystemMode = SystemMode.AUTO,
    system_shutoff: bool = False,
    performance_test_running: bool = False,
) -> V1Activation:
    """Model first-match selection plus legacy ``active``/one-shot disable writes."""

    selected_index = _first_matching_index(rows, day=day, now_second=now_second)
    copied: list[dict[str, Any]] = []
    disabled: list[Any] = []
    for index, original in enumerate(rows):
        row = dict(original)
        is_selected = index == selected_index
        if not split_repeats(row.get("repeats")) and row.get("active") and not is_selected:
            row["enable"] = False
            disabled.append(row.get("id"))
        row["active"] = is_selected
        copied.append(row)
    selected_id = rows[selected_index].get("id") if selected_index is not None else None
    allowed = _activation_allowed(
        is_hold=is_hold,
        system_mode=system_mode,
        system_shutoff=system_shutoff,
        performance_test_running=performance_test_running,
    )
    return V1Activation(
        selected_id,
        selected_id if allowed else None,
        tuple(copied),
        tuple(disabled),
    )


def _first_matching_index(
    rows: Sequence[Mapping[str, Any]], *, day: str, now_second: int
) -> int | None:
    for segment in expand_v1_ranges(rows, current_day=day, now_second=now_second):
        row = rows[segment.source_index]
        if (
            bool(row.get("enable"))
            and day in segment.running_days
            and time_in_range(now_second, segment.start_second, segment.end_second)
        ):
            return segment.source_index
    return None


def migrate_v1_schedule_page(
    rows: Sequence[Mapping[str, Any]], *, accepted: bool, online: bool
) -> V1Migration:
    """Model the popup choice; acceptance deletes V1 rows and performs no conversion."""

    copied = tuple(dict(row) for row in rows)
    if not accepted:
        return V1Migration(copied, "v1", (), (), 0, False, False)
    should_clear_server = any(isinstance(row.get("id"), int) and row["id"] > 0 for row in copied)
    queue = (-2,) if should_clear_server else ()
    native_calls = ((-2, 1),) if should_clear_server and online else ()
    return V1Migration((), "v2", queue, native_calls, len(copied), True, False)


def serialize_v1_schedule(row: Mapping[str, Any]) -> dict[str, Any]:
    """Build the exact legacy JSON member set before native serial insertion."""

    mode = SystemMode(row["systemMode"])
    packet = {
        "is_enable": row["enable"],
        "name": row["name"],
        "type_id": row["type"],
        "start_time": _time_24(row["startTime"]),
        "end_time": _time_24(row["endTime"]),
        "mode_id": int(mode) + 1,
        "humidity": row["humidity"],
        "dataSource": row["dataSource"],
        "weekdays": row["repeats"].split(","),
    }
    if mode is SystemMode.COOLING:
        packet["temp"] = row["maximumTemperature"]
    elif mode is SystemMode.HEATING:
        packet["temp"] = row["minimumTemperature"]
    else:
        packet["auto_temp_low"] = row["minimumTemperature"]
        packet["auto_temp_high"] = row["maximumTemperature"]
    return packet


def _matches_server(local: Mapping[str, Any], server: Mapping[str, Any]) -> bool:
    return local.get("id") == server.get("schedule_id") or (
        isinstance(local.get("id"), int)
        and local["id"] < 0
        and local.get("name") == server.get("name")
    )


def reconcile_v1_identity(
    local_rows: Sequence[Mapping[str, Any]], server_value: Any, *, schedule_editing: bool
) -> V1Reconciliation:
    """Model V1 preserve/clear/removal and id/name identity selection.

    Field conversion is intentionally left to the separate parser evidence. This
    function exposes the identity behavior that determines destructive removal.
    """

    copied = tuple(dict(row) for row in local_rows)
    if schedule_editing or not isinstance(server_value, list):
        return V1Reconciliation(rows=copied, preserved=True, removed_ids=())
    if not server_value:
        return V1Reconciliation(
            rows=(), preserved=False, removed_ids=tuple(row.get("id") for row in copied)
        )

    retained = []
    removed = []
    for row in copied:
        if any(row.get("id") == server.get("schedule_id") for server in server_value):
            retained.append(row)
        else:
            removed.append(row.get("id"))
    for server in server_value:
        if not any(_matches_server(row, server) for row in retained):
            retained.append(
                {
                    "id": server.get("schedule_id"),
                    "name": server.get("name"),
                    "server_row_added": True,
                }
            )
    return V1Reconciliation(tuple(retained), preserved=False, removed_ids=tuple(removed))
