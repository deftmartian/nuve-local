"""Tests for the canonical fan-circulation number entity."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from homeassistant.const import EntityCategory
from homeassistant.exceptions import ServiceValidationError

from custom_components.nuve_local.models import NuveMode, NuveState, NuveSystemType
from custom_components.nuve_local.number import NuveFanWorkingPerHour
from custom_components.nuve_local.runtime import NuveRuntime
from tests.helpers import attach_memory_persistence, settings_upload


async def _runtime() -> NuveRuntime:
    runtime = NuveRuntime(
        serial="00-000-000000",
        control_enabled=True,
        paired=True,
        command_timeout_seconds=0.2,
        bootstrap_firmware_version="1.5.8",
        bootstrap_technician_url="https://contractor.invalid/preserved",
        bootstrap_metadata_confirmed=True,
        bootstrap_no_update_confirmed=True,
        temp_correction_version=2,
    )
    attach_memory_persistence(runtime)
    now = datetime.now(UTC)
    settings = settings_upload(runtime.serial)
    settings["firmware"]["firmware-version"] = "1.5.8"
    runtime.async_accept_settings_snapshot(settings, received_at=now)
    runtime.async_accept_auto_mode_snapshot(
        {
            "auto_temp_low": 19.0,
            "auto_temp_high": 23.0,
            "is_active": False,
            "mode": "heating",
        },
        received_at=now,
    )
    runtime.async_set_outdoor_temperature(10.0, "Test outdoor", observed_at=now)
    await runtime.async_process_monitor_state(
        NuveState(
            available=True,
            last_seen=now,
            sample_time=now,
            monitor_is_sync=True,
            current_temperature=21.0,
            target_temperature=21.5,
            target_humidity=40.0,
            auto_temperature_low=19.0,
            auto_temperature_high=23.0,
            system_type=NuveSystemType.HEAT_PUMP,
            mode=NuveMode.HEAT,
            schedule_type=9,
            records_received=1,
        )
    )
    await runtime.async_get_settings_response(requested_at=now)
    return runtime


def test_fan_minutes_per_hour_is_not_optimistic() -> None:
    async def scenario() -> None:
        runtime = await _runtime()
        entity = NuveFanWorkingPerHour(runtime)
        assert entity.entity_category == EntityCategory.CONFIG
        assert entity.native_value == 30

        task = asyncio.create_task(entity.async_set_native_value(40))
        await asyncio.sleep(0)
        response = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        assert response["fan"] == {"mode": 0, "workingPerHour": 40}
        baseline = settings_upload(runtime.serial)
        assert response["temp"] == baseline["temp"]
        assert response["mode_id"] == baseline["mode_id"]
        assert response["system"] == baseline["system"]
        assert entity.native_value == 30

        await asyncio.sleep(0.002)
        upload = settings_upload(runtime.serial)
        upload["firmware"]["firmware-version"] = "1.5.8"
        upload["fan"] = {"mode": 0, "workingPerHour": 40}
        runtime.async_accept_settings_snapshot(upload, received_at=datetime.now(UTC))
        await task
        assert entity.native_value == 40
        await runtime.async_shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize("value", [9, 10.5, 61, float("nan")])
def test_fan_minutes_per_hour_rejects_invalid_values(value: float) -> None:
    async def scenario() -> None:
        runtime = await _runtime()
        entity = NuveFanWorkingPerHour(runtime)
        with pytest.raises(ServiceValidationError):
            await entity.async_set_native_value(value)
        await runtime.async_shutdown()

    asyncio.run(scenario())
