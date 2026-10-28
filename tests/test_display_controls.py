"""Tests for exact, field-owning Nuve display controls."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Coroutine
from datetime import UTC, datetime, time
from typing import Any

import pytest
from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_HS_COLOR
from homeassistant.exceptions import ServiceValidationError

from custom_components.nuve_local.errors import ControlNotReadyError, ControlStateChangedError
from custom_components.nuve_local.light import FIXED_SHADE_HUE, NuveDisplayBacklight
from custom_components.nuve_local.number import NuveDisplayBrightness
from custom_components.nuve_local.runtime import NuveRuntime
from custom_components.nuve_local.select import (
    NuveBacklightShade,
    NuveBrightnessMode,
    NuveTimeFormat,
)
from custom_components.nuve_local.switch import (
    NuveLedBlinking,
    NuveNightMode,
    NuveProximityDetection,
)
from custom_components.nuve_local.time import NuveNightModeTime
from tests.helpers import (
    accept_settings_snapshot,
    ready_runtime_158,
    settings_upload,
)


async def _deliver_and_confirm(
    runtime: NuveRuntime,
    operation: Coroutine[Any, Any, None],
) -> dict[str, Any]:
    """Deliver one command and confirm it only through a later full upload."""

    baseline = copy.deepcopy(runtime.settings_snapshot)
    assert baseline is not None
    task = asyncio.create_task(operation)
    await asyncio.sleep(0)
    pending = runtime._pending_command
    assert pending is not None
    desired = copy.deepcopy(pending.desired)

    response = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
    assert runtime.uncertain_command is not None
    assert not task.done()
    assert response["temp"] == baseline["temp"]
    assert response["mode_id"] == baseline["mode_id"]
    assert response["fan"] == baseline["fan"]
    assert response["system"] == baseline["system"]
    if "backlight" in desired:
        assert response["setting"]["backlight"] == desired["backlight"]
        assert response["setting"]["brightness"] == baseline["settings"]["brightness"]
    if "settings" in desired:
        expected_settings = copy.deepcopy(desired["settings"])
        expected_settings["brightness_mode"] = bool(expected_settings["brightness_mode"])
        for key, value in expected_settings.items():
            assert response["setting"][key] == value
        assert response["setting"]["backlight"] == baseline["backlight"]

    await asyncio.sleep(0.002)
    upload = baseline
    upload.update(desired)
    received_at = datetime.now(UTC)
    revision, candidate = runtime.prepare_settings_snapshot(upload, received_at=received_at)
    assert "uncertain_command" not in candidate
    runtime.async_accept_settings_snapshot(
        upload,
        received_at=received_at,
        prepared_revision=revision,
    )
    await task
    assert runtime.uncertain_command is None
    assert runtime.authoritative_control_monitor_seen is True
    assert runtime.control_ready is True
    return response


def test_display_controls_are_confirmed_nonoptimistic_and_hvac_preserving() -> None:
    async def scenario() -> None:
        runtime = await ready_runtime_158()
        light = NuveDisplayBacklight(runtime)
        brightness = NuveDisplayBrightness(runtime)
        brightness_mode = NuveBrightnessMode(runtime)
        shade = NuveBacklightShade(runtime)
        night_mode = NuveNightMode(runtime)
        led_blinking = NuveLedBlinking(runtime)
        night_start = NuveNightModeTime(runtime, start=True)
        night_end = NuveNightModeTime(runtime, start=False)
        time_format = NuveTimeFormat(runtime)
        proximity = NuveProximityDetection(runtime)

        assert light.is_on is True
        assert light.brightness == 255
        assert light.hs_color == (FIXED_SHADE_HUE, 0.0)
        assert brightness.native_value == 100
        assert brightness_mode.current_option == "manual"
        assert shade.current_option == "white_0"
        assert night_mode.is_on is False
        assert led_blinking.is_on is True
        assert night_start.native_value == time(22, 0)
        assert night_end.native_value == time(6, 0)
        assert time_format.current_option == "24_hour"
        assert proximity.is_on is True
        assert time_format.entity_registry_enabled_default is True
        assert proximity.entity_registry_enabled_default is True

        await _deliver_and_confirm(
            runtime,
            light.async_turn_on(**{ATTR_BRIGHTNESS: 128, ATTR_HS_COLOR: (180.0, 100.0)}),
        )
        assert light.is_on is True
        assert light.brightness == 128
        assert light.hs_color == (180.0, 100.0)

        await _deliver_and_confirm(runtime, shade.async_select_option("white_50"))
        assert shade.current_option == "white_50"
        assert light.hs_color == (FIXED_SHADE_HUE, 50.0)

        await _deliver_and_confirm(runtime, brightness.async_set_native_value(65))
        assert brightness.native_value == 65
        await _deliver_and_confirm(runtime, brightness_mode.async_select_option("adaptive"))
        assert brightness_mode.current_option == "adaptive"
        await _deliver_and_confirm(runtime, night_mode.async_turn_on())
        assert night_mode.is_on is True
        response = await _deliver_and_confirm(runtime, night_start.async_set_value(time(23, 15)))
        assert response["setting"]["nightModeStart"] == "23:15:00"
        assert night_start.native_value == time(23, 15)
        await _deliver_and_confirm(runtime, night_end.async_set_value(time(7, 0)))
        assert night_end.native_value == time(7, 0)
        await _deliver_and_confirm(runtime, led_blinking.async_turn_off())
        assert led_blinking.is_on is False
        await _deliver_and_confirm(runtime, time_format.async_select_option("12_hour"))
        assert time_format.current_option == "12_hour"
        await _deliver_and_confirm(runtime, proximity.async_turn_off())
        assert proximity.is_on is False

        await _deliver_and_confirm(runtime, light.async_turn_off())
        assert light.is_on is False
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_display_command_rejection_revokes_authority_and_does_not_use_partial_upload() -> None:
    async def scenario() -> None:
        runtime = await ready_runtime_158()
        command = asyncio.create_task(
            runtime.async_request_settings_change({"settings": {"brightness": 75}})
        )
        await asyncio.sleep(0)
        await runtime.async_get_settings_response(requested_at=datetime.now(UTC))

        assert runtime.settings_snapshot is not None
        partial = copy.deepcopy(runtime.settings_snapshot["settings"])
        partial["brightness"] = 75
        partial_at = datetime.now(UTC)
        revision, candidate, merged = runtime.prepare_partial_settings(
            "settings", partial, received_at=partial_at
        )
        runtime.async_accept_partial_settings(merged, prepared_revision=revision)
        assert candidate["settings"]["settings"]["brightness"] == 75
        assert not command.done()
        assert runtime.uncertain_command is not None

        await asyncio.sleep(0.002)
        rejected = settings_upload(runtime.serial, firmware_version="1.5.8")
        rejected_at = datetime.now(UTC)
        accept_settings_snapshot(runtime, rejected, received_at=rejected_at)

        with pytest.raises(ControlStateChangedError):
            await command
        assert runtime.authoritative_control_monitor_seen is False
        assert runtime.last_settings_upload == rejected_at
        assert runtime.control_ready is False
        await runtime.async_shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize("value", [-1, 1.5, 101, float("nan")])
def test_display_brightness_rejects_invalid_values(value: float) -> None:
    async def scenario() -> None:
        runtime = await ready_runtime_158()
        with pytest.raises(ServiceValidationError):
            await NuveDisplayBrightness(runtime).async_set_native_value(value)
        await runtime.async_shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kwargs",
    [
        {ATTR_BRIGHTNESS: -1},
        {ATTR_BRIGHTNESS: 256},
        {ATTR_HS_COLOR: (-1.0, 50.0)},
        {ATTR_HS_COLOR: (120.0, 101.0)},
        {ATTR_HS_COLOR: (float("nan"), 50.0)},
    ],
)
def test_display_backlight_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    async def scenario() -> None:
        runtime = await ready_runtime_158()
        with pytest.raises(ServiceValidationError):
            await NuveDisplayBacklight(runtime).async_turn_on(**kwargs)
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_night_mode_time_rejects_subminute_and_timezone_values() -> None:
    async def scenario() -> None:
        runtime = await ready_runtime_158()
        entity = NuveNightModeTime(runtime, start=True)
        with pytest.raises(ServiceValidationError):
            await entity.async_set_value(time(22, 0, 1))
        with pytest.raises(ServiceValidationError):
            await entity.async_set_value(time(22, 0, tzinfo=UTC))
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_night_mode_rejects_equal_boundaries_across_firmware_time_formats() -> None:
    async def scenario() -> None:
        runtime = await ready_runtime_158()
        with pytest.raises(ControlNotReadyError):
            await runtime.async_request_settings_change({"settings": {"nightModeStart": "06:00"}})
        await runtime.async_shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "settings",
    [
        {"currentTimezone": "America/Halifax"},
        {"effectDst": False},
        {"setTimeAuto": False},
        {"sleepModeLogo": False},
        {"speaker": 60},
        {"temperatureUnit": 1},
    ],
)
def test_disqualified_advanced_preferences_remain_unexposed(
    settings: dict[str, object],
) -> None:
    async def scenario() -> None:
        runtime = await ready_runtime_158()
        with pytest.raises(ControlNotReadyError):
            await runtime.async_request_settings_change({"settings": settings})
        await runtime.async_shutdown()

    asyncio.run(scenario())
