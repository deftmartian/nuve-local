"""Synthetic protocol fixtures with no household identifiers."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from custom_components.nuve_local.runtime import NuveRuntime


def attach_memory_persistence(runtime: NuveRuntime) -> list[dict[str, Any]]:
    """Attach a deterministic in-memory durability boundary for runtime tests."""

    saved: list[dict[str, Any]] = []

    async def persist(candidate: dict[str, Any]) -> None:
        saved.append(copy.deepcopy(candidate))

    runtime.async_set_persistence_listener(persist)
    return saved


def accept_settings_snapshot(
    runtime: NuveRuntime, snapshot: dict[str, Any], *, received_at: datetime
) -> str:
    """Accept a full upload through the same prepare-then-commit path the listener uses."""

    revision, _ = runtime.prepare_settings_snapshot(snapshot, received_at=received_at)
    return runtime.async_accept_settings_snapshot(
        snapshot, received_at=received_at, prepared_revision=revision
    )


def accept_auto_mode_snapshot(
    runtime: NuveRuntime, snapshot: dict[str, Any], *, received_at: datetime
) -> str:
    """Accept an Auto upload through the same prepare-then-commit path the listener uses."""

    revision, _ = runtime.prepare_auto_mode_snapshot(snapshot, received_at=received_at)
    return runtime.async_accept_auto_mode_snapshot(
        snapshot, received_at=received_at, prepared_revision=revision
    )


def accept_partial_settings(
    runtime: NuveRuntime,
    section: Literal["settings", "system"],
    snapshot: dict[str, Any],
    *,
    received_at: datetime,
) -> str:
    """Accept a partial upload through the same prepare-then-commit path the listener uses."""

    revision, _, full = runtime.prepare_partial_settings(section, snapshot, received_at=received_at)
    return runtime.async_accept_partial_settings(full, prepared_revision=revision)


async def ready_runtime(
    *,
    timeout: float = 0.2,
    firmware_version: str = "1.5.7.4",
    temp_correction_version: int = 1,
    current_temperature: float = 21.2,
) -> NuveRuntime:
    """Return a control-ready runtime built entirely through the listener's prepared paths."""

    from custom_components.nuve_local.models import NuveMode, NuveState, NuveSystemType
    from custom_components.nuve_local.runtime import NuveRuntime

    runtime = NuveRuntime(
        serial="00-000-000000",
        control_enabled=True,
        paired=True,
        command_timeout_seconds=timeout,
        bootstrap_firmware_version=firmware_version,
        bootstrap_technician_url="https://contractor.invalid/preserved",
        bootstrap_metadata_confirmed=True,
        bootstrap_no_update_confirmed=True,
        temp_correction_version=temp_correction_version,
    )
    attach_memory_persistence(runtime)
    now = datetime.now(UTC)
    accept_settings_snapshot(
        runtime, settings_upload(runtime.serial, firmware_version=firmware_version), received_at=now
    )
    accept_auto_mode_snapshot(
        runtime,
        {"auto_temp_low": 19.0, "auto_temp_high": 23.0, "is_active": False, "mode": "heating"},
        received_at=now,
    )
    runtime.async_note_authenticated_contact(now)
    runtime.async_set_outdoor_temperature(10.0, "Test outdoor", observed_at=now)
    await runtime.async_process_monitor_state(
        NuveState(
            available=True,
            last_seen=now,
            sample_time=now,
            monitor_is_sync=True,
            current_temperature=current_temperature,
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


async def ready_runtime_158() -> NuveRuntime:
    """Return a control-ready runtime on firmware 1.5.8 (temp-correction version 2)."""

    return await ready_runtime(
        firmware_version="1.5.8", temp_correction_version=2, current_temperature=21.0
    )


def system_settings(serial: str) -> dict[str, object]:
    """Return every field emitted by the firmware's shared system constructor."""

    return {
        "sn": serial,
        "type": "heat_pump",
        "coolStage": 2,
        "heatStage": 2,
        "heatPumpOBState": 0,
        "heatPumpEmergency": True,
        "systemRunDelay": 5,
        "dualFuelThreshold": -2,
        "isAUXAuto": True,
        "dualFuelManualHeating": 2,
        "dualFuelHeatingModeDefault": 0,
        "emergencyMinimumTime": 2,
        "auxiliaryHeating": True,
        "useAuxiliaryParallelHeatPump": False,
        "driveAux1AndETogether": True,
        "driveAuxAsEmergency": True,
        "runFanWithAuxiliary": True,
        "turnAuxOnUnreaching": 30,
        "thermostatControlFan": True,
        "tempCorrection": 0.0,
        "heatingControlByFurnace": False,
        "compressorLockout": False,
        "overcool": 0.0,
        "diffToEngageAux": 5.0,
        "heat_dissipation_time": 1.0,
        "cool_dissipation_time": 0.0,
        "fanWithAccessory": False,
        "systemAccessories": {"wire": "None", "mode": 0},
        "heat_deadband": 1.0,
        "cool_deadband": 1.0,
        "aux_lockout": True,
        "aux_lockout_threshold": -2.0,
        "wifiName": "synthetic-test-network",
        "wifiStrength": "-50",
        "heat_min_on_time": 5.0,
        "cool_min_on_time": 5.0,
    }


def settings_upload(serial: str, *, firmware_version: str = "1.5.7.4") -> dict[str, object]:
    """Return a complete synthetic full settings upload."""

    return {
        "sn": serial,
        "temp": 21.5,
        "humidity": 40,
        "current_humidity": "42.5",
        "current_temp": "21.2",
        "co2_id": 1,
        "hold": False,
        "hold_period": "",
        "mode_id": 2,
        "fan": {"mode": 0, "workingPerHour": 30},
        "backlight": {"on": True, "hue": 0.0, "value": 1.0, "shadeIndex": 0},
        "settings": {
            "brightness": 100,
            "brightness_mode": 0,
            "speaker": 50,
            "temperatureUnit": 0,
            "timeFormat": 1,
            "currentTimezone": "Etc/UTC",
            "effectDst": True,
            "sleepModeLogo": True,
            "tofEnabled": True,
            "ledBlinkingEnabled": True,
            "setTimeAuto": True,
            "nightModeEnabled": False,
            "nightModeStart": "22:00:00",
            "nightModeEnd": "06:00:00",
        },
        "sensors": [],
        "messages": [],
        "system": system_settings(serial),
        "vacation": {
            "min_humidity": 30.0,
            "max_humidity": 50.0,
            "min_temp": 16.0,
            "max_temp": 22.0,
            "is_enable": "f",
        },
        "firmware": {"firmware-version": firmware_version},
    }


# System-settings keys exposed as sensors / binary sensors (the rest are not entities).
SYSTEM_SENSOR_FIELDS = frozenset(
    {
        "type",
        "coolStage",
        "heatStage",
        "heatPumpOBState",
        "systemRunDelay",
        "dualFuelThreshold",
        "dualFuelManualHeating",
        "dualFuelHeatingModeDefault",
        "emergencyMinimumTime",
        "turnAuxOnUnreaching",
        "tempCorrection",
        "overcool",
        "diffToEngageAux",
        "heat_dissipation_time",
        "cool_dissipation_time",
        "systemAccessories",
        "heat_deadband",
        "cool_deadband",
        "aux_lockout_threshold",
        "heat_min_on_time",
        "cool_min_on_time",
    }
)

SYSTEM_BINARY_SENSOR_FIELDS = frozenset(
    {
        "heatPumpEmergency",
        "isAUXAuto",
        "auxiliaryHeating",
        "useAuxiliaryParallelHeatPump",
        "driveAux1AndETogether",
        "driveAuxAsEmergency",
        "runFanWithAuxiliary",
        "thermostatControlFan",
        "heatingControlByFurnace",
        "compressorLockout",
        "fanWithAccessory",
        "aux_lockout",
    }
)
