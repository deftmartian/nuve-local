"""Tests for the command validators shared by the runtime and the journal."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from custom_components.nuve_local.commands import (
    _SETTINGS_FIELD_CHECKS,
    valid_backlight,
    valid_device_settings,
    valid_fan,
    valid_mode_id,
    validated_settings_changes,
)
from custom_components.nuve_local.const import DISPLAY_SETTINGS_KEYS
from custom_components.nuve_local.errors import ControlNotReadyError
from custom_components.nuve_local.protocol import DEVICE_SETTINGS_KEYS, NuveProtocolError
from custom_components.nuve_local.storage import _validate_uncertain_desired
from tests.helpers import settings_upload

BACKLIGHT = {"on": True, "hue": 0.5, "value": 1, "shadeIndex": 5}


def test_settings_field_table_covers_every_device_setting() -> None:
    assert set(_SETTINGS_FIELD_CHECKS) == DEVICE_SETTINGS_KEYS
    assert DISPLAY_SETTINGS_KEYS <= DEVICE_SETTINGS_KEYS


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        (1, True),
        (2, True),
        (3, True),
        (5, True),
        (0, False),
        (4, False),
        (6, False),
        (True, False),
        (1.0, False),
        ("1", False),
    ],
)
def test_mode_id(value: Any, ok: bool) -> None:
    assert valid_mode_id(value) is ok


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ({"mode": 1, "workingPerHour": 40}, True),
        ({"mode": 3, "workingPerHour": 40}, False),
        ({"mode": 1, "workingPerHour": 9}, False),
        ({"mode": 1, "workingPerHour": 61}, False),
        ({"mode": True, "workingPerHour": 40}, False),
        ({"mode": 1, "workingPerHour": 40.0}, False),
        ({"mode": 1}, False),
        ({"mode": 1, "workingPerHour": 40, "extra": 1}, False),
        (None, False),
    ],
)
def test_fan_is_validated_identically_at_runtime_and_in_the_journal(value: Any, ok: bool) -> None:
    assert valid_fan(value) is ok
    if ok:
        validated_settings_changes({"fan": value})
        _validate_uncertain_desired("settings", {"fan": value})
    else:
        with pytest.raises(ControlNotReadyError):
            validated_settings_changes({"fan": value})
        with pytest.raises(NuveProtocolError):
            _validate_uncertain_desired("settings", {"fan": value})


def _backlight(**changes: Any) -> dict[str, Any]:
    return {**BACKLIGHT, **changes}


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        (_backlight(), True),
        (_backlight(hue=1.5), False),
        (_backlight(value=-0.1), False),
        (_backlight(value=float("nan")), False),
        (_backlight(on=1), False),
        (_backlight(shadeIndex=6), False),
        (_backlight(shadeIndex=True), False),
        ({k: v for k, v in BACKLIGHT.items() if k != "on"}, False),
    ],
)
def test_complete_backlight_matches_between_runtime_and_journal(value: Any, ok: bool) -> None:
    assert valid_backlight(value, complete=True) is ok
    if ok:
        _validate_uncertain_desired("settings", {"backlight": value})
    else:
        with pytest.raises(NuveProtocolError):
            _validate_uncertain_desired("settings", {"backlight": value})


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ({"on": False}, True),
        ({"hue": 1}, True),
        ({"shadeIndex": 0, "value": 0.25}, True),
        ({}, False),
        ({"unknown": 1}, False),
        ({"hue": 2}, False),
    ],
)
def test_partial_backlight_is_validated_and_coerced_at_runtime(value: Any, ok: bool) -> None:
    assert valid_backlight(value, complete=False) is ok
    if not ok:
        with pytest.raises(ControlNotReadyError):
            validated_settings_changes({"backlight": copy.deepcopy(value)})
        return
    validated = validated_settings_changes({"backlight": copy.deepcopy(value)})
    assert all(isinstance(validated["backlight"][k], float) for k in ("hue", "value") if k in value)


def test_device_settings_partial_and_complete() -> None:
    complete = copy.deepcopy(settings_upload("00-000-000000")["settings"])
    assert valid_device_settings(complete, complete=True)
    _validate_uncertain_desired("settings", {"settings": complete})
    assert not valid_device_settings(complete, complete=False)  # not a display subset

    assert valid_device_settings({"brightness": 50, "nightModeStart": "21:30"}, complete=False)
    for bad in (
        {"brightness": 101},
        {"brightness_mode": 2},
        {"timeFormat": True},
        {"tofEnabled": 1},
        {"nightModeEnd": "24:00"},
        {"speaker": 50},  # not a runtime-writable field
    ):
        assert not valid_device_settings(bad, complete=False)

    same_times = {**complete, "nightModeStart": "22:00", "nightModeEnd": "22:00:00"}
    assert not valid_device_settings(same_times, complete=True)
    with pytest.raises(NuveProtocolError):
        _validate_uncertain_desired("settings", {"settings": same_times})
    for key, bad in (("speaker", 101), ("temperatureUnit", 2), ("currentTimezone", 5)):
        with pytest.raises(NuveProtocolError):
            _validate_uncertain_desired("settings", {"settings": {**complete, key: bad}})
