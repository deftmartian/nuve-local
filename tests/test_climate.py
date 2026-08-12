"""Tests for the Home Assistant Nuve climate entity."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from homeassistant.components.climate import ATTR_TEMPERATURE
from homeassistant.components.climate.const import HVACAction, HVACMode
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

import custom_components.nuve_local.runtime as runtime_module
from custom_components.nuve_local.climate import NuveClimate
from custom_components.nuve_local.models import NuveMode, NuveState, NuveSystemType
from custom_components.nuve_local.runtime import NuveRuntime
from tests.helpers import attach_memory_persistence, settings_upload


def _settings() -> dict[str, object]:
    return settings_upload("00-000-000000")


async def _runtime() -> NuveRuntime:
    runtime = NuveRuntime(
        serial="00-000-000000",
        control_enabled=True,
        paired=True,
        command_timeout_seconds=0.2,
        bootstrap_firmware_version="1.5.7.4",
        bootstrap_technician_url="https://contractor.invalid/preserved",
        bootstrap_metadata_confirmed=True,
        bootstrap_no_update_confirmed=True,
        temp_correction_version=1,
    )
    attach_memory_persistence(runtime)
    now = datetime.now(UTC)
    runtime.async_accept_settings_snapshot(_settings(), received_at=now)
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
            current_temperature=21.2,
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


def test_climate_reports_confirmed_mode_and_equipment_action() -> None:
    async def scenario() -> None:
        runtime = await _runtime()
        now = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                current_temperature=21.25,
                current_humidity=43.0,
                target_temperature=21.5,
                mode=NuveMode.HEAT,
                heating_stage=1,
                records_received=1,
            )
        )
        entity = NuveClimate(runtime)

        assert entity.hvac_mode == HVACMode.HEAT
        assert entity.hvac_action == HVACAction.HEATING
        assert entity.current_temperature == 21.25
        assert entity.target_temperature == 21.5
        assert entity.fan_mode == "auto"
        assert entity.extra_state_attributes["control_status"] == "idle"
        assert entity.extra_state_attributes["control_block_reason"] == "ready"
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_climate_does_not_infer_idle_from_mode_without_output_authority() -> None:
    runtime = NuveRuntime(serial="00-000-000000")
    entity = NuveClimate(runtime)

    runtime.state = NuveState(mode=NuveMode.COOL)
    assert entity.hvac_action is None

    runtime.state = NuveState(
        mode=NuveMode.COOL,
        cooling_stage=0,
        heating_stage=0,
        fan_active=False,
    )
    assert entity.hvac_action == HVACAction.IDLE


def test_climate_fan_mode_waits_for_post_delivery_settings_upload() -> None:
    async def scenario() -> None:
        runtime = await _runtime()
        entity = NuveClimate(runtime)
        task = asyncio.create_task(entity.async_set_fan_mode("on"))
        await asyncio.sleep(0)

        response = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        assert response["fan"] == {"mode": 1, "workingPerHour": 30}
        baseline = _settings()
        assert response["hold_period"] == baseline["hold_period"]
        assert response["temp"] == baseline["temp"]
        assert response["mode_id"] == baseline["mode_id"]
        assert response["system"] == baseline["system"]
        assert entity.fan_mode == "auto"

        await asyncio.sleep(0.002)
        upload = _settings()
        upload["fan"] = {"mode": 1, "workingPerHour": 30}
        runtime.async_accept_settings_snapshot(upload, received_at=datetime.now(UTC))
        await task
        assert entity.fan_mode == "on"
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_climate_rejects_unknown_fan_mode() -> None:
    async def scenario() -> None:
        runtime = await _runtime()
        entity = NuveClimate(runtime)
        with pytest.raises(ServiceValidationError):
            await entity.async_set_fan_mode("circulate")
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_climate_projects_requested_temperature_until_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _runtime()
        entity = NuveClimate(runtime)
        original = entity.target_temperature
        task = asyncio.create_task(entity.async_set_temperature(**{ATTR_TEMPERATURE: 22.0}))
        await asyncio.sleep(0)
        assert runtime.state.target_temperature == original
        assert entity.target_temperature == 22.0
        assert entity.extra_state_attributes["control_status"] == "queued"

        response = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        assert response["temp"] == 22.0
        assert runtime.state.target_temperature == original
        assert entity.target_temperature == 22.0
        assert entity.extra_state_attributes["control_status"] == "delivered"

        await asyncio.sleep(0.002)
        confirmed_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=confirmed_at,
                sample_time=confirmed_at,
                target_temperature=22.0,
                mode=NuveMode.HEAT,
                records_received=1,
            )
        )
        await task
        assert runtime.state.target_temperature == 22.0
        assert entity.target_temperature == 22.0
        assert entity.extra_state_attributes["control_status"] == "idle"
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_climate_requested_temperature_reverts_after_undelivered_timeout() -> None:
    async def scenario() -> None:
        runtime = await _runtime()
        runtime.command_timeout_seconds = 0.01
        entity = NuveClimate(runtime)
        confirmed = entity.target_temperature

        with pytest.raises(HomeAssistantError):
            task = asyncio.create_task(entity.async_set_temperature(**{ATTR_TEMPERATURE: 22.0}))
            await asyncio.sleep(0)
            assert entity.target_temperature == 22.0
            await task

        assert runtime.state.target_temperature == confirmed
        assert entity.target_temperature == confirmed
        assert entity.extra_state_attributes["control_status"] == "idle"
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_climate_rejects_out_of_range_temperature() -> None:
    async def scenario() -> None:
        runtime = await _runtime()
        entity = NuveClimate(runtime)
        assert entity.min_temp == 18.0
        assert entity.max_temp == 30.0
        with pytest.raises(ServiceValidationError):
            await entity.async_set_temperature(**{ATTR_TEMPERATURE: 17.5})
        with pytest.raises(ServiceValidationError):
            await entity.async_set_temperature(**{ATTR_TEMPERATURE: 100.0})
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_climate_exposes_only_the_active_mode_target_model() -> None:
    async def scenario() -> None:
        runtime = await _runtime()
        entity = NuveClimate(runtime)

        assert entity.target_temperature == 21.5
        assert entity.target_temperature_low is None
        assert entity.target_temperature_high is None

        runtime.state = replace(runtime.state, mode=NuveMode.AUTO)
        assert entity.target_temperature is None
        assert entity.target_temperature_low == 19.0
        assert entity.target_temperature_high == 23.0
        assert entity.min_temp == 4.0
        assert entity.max_temp == 32.0
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_climate_rejects_off_grid_temperature() -> None:
    async def scenario() -> None:
        runtime = await _runtime()
        entity = NuveClimate(runtime)
        assert entity.target_temperature_step == 1.0
        with pytest.raises(ServiceValidationError):
            await entity.async_set_temperature(**{ATTR_TEMPERATURE: 21.5})
        with pytest.raises(ServiceValidationError):
            await entity.async_set_temperature(**{ATTR_TEMPERATURE: 21.23})
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_emergency_heat_is_reported_read_only_and_never_aliased_to_heat() -> None:
    async def scenario() -> None:
        runtime = await _runtime()
        runtime.async_update_state(
            NuveState(
                available=True,
                last_seen=datetime.now(UTC),
                current_temperature=21.0,
                target_temperature=21.5,
                mode=NuveMode.EMERGENCY_HEAT,
                records_received=1,
            )
        )
        entity = NuveClimate(runtime)
        assert entity.hvac_mode is None
        with pytest.raises(ServiceValidationError):
            await entity.async_set_hvac_mode(HVACMode.HEAT)
        assert runtime.command_status == "idle"
        await runtime.async_shutdown()

    asyncio.run(scenario())
