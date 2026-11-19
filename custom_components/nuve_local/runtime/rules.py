"""Pure value, revision and monitor-freshness rules used by the runtime.

Every read of the monitor clock-skew and age bounds goes through this module,
so it is the single place tests patch ``MONITOR_FUTURE_SKEW_SECONDS``.
"""

from __future__ import annotations

import copy
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from ..const import (
    MAX_DEVICE_TEMPERATURE,
    MIN_DEVICE_TEMPERATURE,
    MONITOR_FUTURE_SKEW_SECONDS,
    MONITOR_MAX_AGE_SECONDS,
)
from ..models import NuveSystemType

ACTIVE_SCHEDULE_TYPES = frozenset({0, 1, 2, 3, 8})
NO_SCHEDULE_TYPE = 9

SYSTEM_TYPE_NAMES = {
    NuveSystemType.TRADITIONAL: "traditional",
    NuveSystemType.HEAT_PUMP: "heat_pump",
    NuveSystemType.COOLING_ONLY: "cooling",
    NuveSystemType.HEATING_ONLY: "heating",
    NuveSystemType.DUAL_FUEL_HEATING: "dual_fuel_heating",
}


def values_match(desired: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Return whether every desired value is present, numerically within 0.02."""

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


def changed_fields(desired: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Return only the desired fields that differ from the baseline."""

    return {
        key: copy.deepcopy(value)
        for key, value in desired.items()
        if not values_match({key: value}, baseline)
    }


def command_payload(baseline: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """Return a whole-snapshot command body with the changes applied."""

    payload = copy.deepcopy(baseline)
    payload.update(copy.deepcopy(changes))
    return payload


def latest_revision(first: str | None, second: str | None) -> str | None:
    """Return the later of two sortable revision strings."""

    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def valid_auto_pair(low: Any, high: Any) -> bool:
    """Return whether two Auto bounds are finite, in range and ordered."""

    values = (low, high)
    return all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and MIN_DEVICE_TEMPERATURE <= float(value) <= MAX_DEVICE_TEMPERATURE
        for value in values
    ) and float(low) < float(high)


def valid_humidity(value: Any) -> bool:
    """Return whether a value is a finite relative humidity percentage."""

    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0 <= float(value) <= 100
    )


def monitor_is_fresh(
    last_upload: datetime | None, sample_time: datetime | None, records_received: int
) -> bool:
    """Return whether telemetry was received recently enough to expose as live."""

    if last_upload is None or sample_time is None or records_received < 1:
        return False
    now = datetime.now(UTC)
    upload_age = (now - last_upload).total_seconds()
    sample_age = (now - sample_time).total_seconds()
    return (
        0 <= upload_age <= MONITOR_MAX_AGE_SECONDS
        and -MONITOR_FUTURE_SKEW_SECONDS <= sample_age <= MONITOR_MAX_AGE_SECONDS
    )


def monitor_gap_expired(previous_upload: datetime | None, received_at: datetime) -> bool:
    """Return whether a telemetry gap is long enough to expire monitor authority."""

    return previous_upload is not None and received_at - previous_upload > timedelta(
        seconds=MONITOR_MAX_AGE_SECONDS
    )


def current_monitor_sample_time(
    sample_time: datetime | None, received_at: datetime, previous_sample_time: datetime | None
) -> datetime | None:
    """Return the sample time, or None for missing, buffered, future, or stale samples."""

    if (
        sample_time is None
        or sample_time.tzinfo is None
        or sample_time > received_at + timedelta(seconds=MONITOR_FUTURE_SKEW_SECONDS)
        or sample_time < received_at - timedelta(seconds=MONITOR_MAX_AGE_SECONDS)
        or (previous_sample_time is not None and sample_time <= previous_sample_time)
    ):
        return None
    return sample_time


def monitor_sample_is_post_queue(sample_time: datetime, queued_at: datetime) -> bool:
    """Return whether device evidence is clearly newer than a queued command."""

    return sample_time > queued_at + timedelta(seconds=MONITOR_FUTURE_SKEW_SECONDS)
