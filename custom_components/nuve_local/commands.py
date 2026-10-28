"""Pure validators for the Home Assistant command surface."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from .const import (
    BACKLIGHT_KEYS,
    DISPLAY_SETTINGS_KEYS,
    FAN_MODE_IDS,
    MAX_FAN_WORKING_PER_HOUR,
    MIN_FAN_WORKING_PER_HOUR,
    TARGET_TEMPERATURE_STEP,
)
from .models import NuveMode
from .protocol import DEVICE_SETTINGS_KEYS, NuveProtocolError, normalize_night_mode_time

CONTROL_SAFE_MODES = frozenset({NuveMode.COOL, NuveMode.HEAT, NuveMode.AUTO, NuveMode.OFF})
_SAFE_MODE_IDS = frozenset(int(mode) for mode in CONTROL_SAFE_MODES)


def validated_command_celsius(
    value: Any,
    *,
    minimum: float,
    maximum: float,
) -> float:
    """Return one whole-degree Celsius command value inside an exact range."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid command temperature")
    temperature = float(value)
    if (
        not math.isfinite(temperature)
        or temperature < minimum
        or temperature > maximum
        or not math.isclose(
            temperature / TARGET_TEMPERATURE_STEP,
            round(temperature / TARGET_TEMPERATURE_STEP),
            abs_tol=1e-7,
        )
    ):
        raise ValueError("invalid command temperature")
    return temperature


def _int_in(value: Any, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _unit_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0 <= float(value) <= 1
    )


def _night_time(value: Any) -> bool:
    try:
        normalize_night_mode_time(value, name="time")
    except NuveProtocolError:
        return False
    return True


_SETTINGS_FIELD_CHECKS: dict[str, Callable[[Any], bool]] = {
    "brightness": lambda v: _int_in(v, 0, 100),
    "speaker": lambda v: _int_in(v, 0, 100),
    "brightness_mode": lambda v: _int_in(v, 0, 1),
    "temperatureUnit": lambda v: _int_in(v, 0, 1),
    "timeFormat": lambda v: _int_in(v, 0, 1),
    "currentTimezone": lambda v: isinstance(v, str),
    "nightModeStart": _night_time,
    "nightModeEnd": _night_time,
    **{
        key: lambda v: isinstance(v, bool)
        for key in (
            "effectDst",
            "sleepModeLogo",
            "tofEnabled",
            "ledBlinkingEnabled",
            "setTimeAuto",
            "nightModeEnabled",
        )
    },
}
_BACKLIGHT_FIELD_CHECKS: dict[str, Callable[[Any], bool]] = {
    "on": lambda v: isinstance(v, bool),
    "hue": _unit_number,
    "value": _unit_number,
    "shadeIndex": lambda v: _int_in(v, 0, 5),
}


def valid_mode_id(value: Any) -> bool:
    """Return whether a mode id names a mode HA may command."""

    return isinstance(value, int) and not isinstance(value, bool) and value in _SAFE_MODE_IDS


def valid_fan(value: Any) -> bool:
    """Return whether a fan object is the exact mode/circulation pair."""

    return (
        isinstance(value, dict)
        and set(value) == {"mode", "workingPerHour"}
        and isinstance(value["mode"], int)
        and not isinstance(value["mode"], bool)
        and value["mode"] in FAN_MODE_IDS
        and _int_in(value["workingPerHour"], MIN_FAN_WORKING_PER_HOUR, MAX_FAN_WORKING_PER_HOUR)
    )


def valid_backlight(value: Any, *, complete: bool) -> bool:
    """Return whether a backlight object is valid, whole when ``complete``."""

    if not isinstance(value, dict) or not value:
        return False
    keys = set(value)
    if not (keys == BACKLIGHT_KEYS if complete else keys <= BACKLIGHT_KEYS):
        return False
    return all(_BACKLIGHT_FIELD_CHECKS[key](item) for key, item in value.items())


def valid_device_settings(value: Any, *, complete: bool) -> bool:
    """Return whether a settings subsection is valid, whole when ``complete``."""

    if not isinstance(value, dict) or not value:
        return False
    keys = set(value)
    if not (keys == DEVICE_SETTINGS_KEYS if complete else keys <= DISPLAY_SETTINGS_KEYS):
        return False
    if not all(_SETTINGS_FIELD_CHECKS[key](item) for key, item in value.items()):
        return False
    # A whole subsection must keep distinct night-mode times; partial changes are
    # checked after merging into the baseline.
    return not complete or (
        normalize_night_mode_time(value["nightModeStart"], name="nightModeStart")
        != normalize_night_mode_time(value["nightModeEnd"], name="nightModeEnd")
    )
