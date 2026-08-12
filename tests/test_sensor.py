"""Tests for Nuve telemetry sensor presentation."""

from __future__ import annotations

from homeassistant.const import EntityCategory

from custom_components.nuve_local.models import NuveState, NuveSystemType
from custom_components.nuve_local.protocol import SYSTEM_SETTINGS_KEYS
from custom_components.nuve_local.runtime import NuveRuntime
from custom_components.nuve_local.sensor import RUNTIME_SENSORS, SENSORS, SYSTEM_SENSOR_FIELDS
from tests.helpers import settings_upload


def test_air_quality_sensor_preserves_unlabelled_firmware_categories() -> None:
    description = next(item for item in SENSORS if item.key == "air_quality_level")

    assert description.options == ["none", "level_0", "level_1", "level_2"]
    assert description.value_fn(NuveState(air_quality_level=0)) == "none"
    assert description.value_fn(NuveState(air_quality_level=1)) == "level_0"
    assert description.value_fn(NuveState(air_quality_level=3)) == "level_2"
    assert description.value_fn(NuveState()) is None


def test_proven_diagnostic_telemetry_has_dedicated_sensors() -> None:
    descriptions = {item.key: item for item in SENSORS}
    state = NuveState(
        air_pressure=1008.0,
        cooling_stage=2,
        heating_stage=0,
        mcu_temperature=31.5,
        system_type=NuveSystemType.HEAT_PUMP,
        schedule_type=8,
        target_humidity=45.0,
    )

    assert descriptions["air_pressure"].value_fn(state) == 1008.0
    assert descriptions["air_pressure"].entity_registry_enabled_default is True
    assert descriptions["cooling_stage"].value_fn(state) == 2
    assert descriptions["heating_stage"].value_fn(state) == 0
    assert descriptions["mcu_temperature"].value_fn(state) == 31.5
    assert descriptions["system_type"].value_fn(state) == "heat_pump"
    assert descriptions["schedule_type"].value_fn(state) == "hold"
    assert descriptions["target_humidity"].value_fn(state) == 45.0


def test_enum_sensors_reject_unknown_wire_values() -> None:
    descriptions = {item.key: item for item in SENSORS}

    assert descriptions["system_type"].value_fn(NuveState()) is None
    assert descriptions["schedule_type"].value_fn(NuveState(schedule_type=99)) is None


def test_private_settings_diagnostics_expose_firmware_and_raw_strength_only() -> None:
    runtime = NuveRuntime(serial="00-000-000000")
    runtime.settings_snapshot = settings_upload(runtime.serial)
    descriptions = {item.key: item for item in RUNTIME_SENSORS}

    assert descriptions["firmware_version"].value_fn(runtime) == "1.5.7.4"
    assert descriptions["wifi_strength"].value_fn(runtime) == "-50"
    assert "wifi_name" not in descriptions


def test_installer_sensors_are_complete_read_only_diagnostics() -> None:
    runtime = NuveRuntime(serial="00-000-000000")
    runtime.settings_snapshot = settings_upload(runtime.serial)
    descriptions = {item.key: item for item in RUNTIME_SENSORS}

    assert descriptions["configured_equipment_type"].value_fn(runtime) == "heat_pump"
    assert descriptions["configured_cooling_stages"].value_fn(runtime) == 2
    assert descriptions["dual_fuel_manual_heating_code"].value_fn(runtime) == 2
    assert descriptions["accessory_wire"].value_fn(runtime) == "None"
    assert descriptions["accessory_mode_code"].value_fn(runtime) == 0
    for description in RUNTIME_SENSORS:
        if description.key not in {"firmware_version", "wifi_strength"}:
            assert description.entity_registry_enabled_default is False
            assert description.entity_category == EntityCategory.DIAGNOSTIC

    from custom_components.nuve_local.binary_sensor import SYSTEM_BINARY_SENSOR_FIELDS

    assert SYSTEM_SENSOR_FIELDS | SYSTEM_BINARY_SENSOR_FIELDS | {"wifiStrength"} == (
        SYSTEM_SETTINGS_KEYS - {"sn", "wifiName"}
    )
    assert "sn" not in SYSTEM_SENSOR_FIELDS
    assert "wifiName" not in SYSTEM_SENSOR_FIELDS
