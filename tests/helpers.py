"""Synthetic protocol fixtures with no household identifiers."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from custom_components.nuve_local.runtime import NuveRuntime


def attach_memory_persistence(runtime: NuveRuntime) -> list[dict[str, Any]]:
    """Attach a deterministic in-memory durability boundary for runtime tests."""

    saved: list[dict[str, Any]] = []

    async def persist(candidate: dict[str, Any]) -> None:
        saved.append(copy.deepcopy(candidate))

    runtime.async_set_persistence_listener(persist)
    return saved


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
