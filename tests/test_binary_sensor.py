"""Tests for confirmed binary Nuve telemetry."""

from __future__ import annotations

from homeassistant.const import EntityCategory

from custom_components.nuve_local.binary_sensor import (
    BINARY_SENSORS,
    RUNTIME_BINARY_SENSORS,
    SYSTEM_BINARY_SENSOR_FIELDS,
    NuveRuntimeBinarySensor,
)
from custom_components.nuve_local.models import NuveState
from custom_components.nuve_local.runtime import NuveRuntime


def test_binary_sensor_values_are_not_inferred() -> None:
    fan = next(item for item in BINARY_SENSORS if item.key == "fan_active")
    hold = next(item for item in BINARY_SENSORS if item.key == "hold_active")
    led = next(item for item in BINARY_SENSORS if item.key == "status_led_active")
    online = next(item for item in BINARY_SENSORS if item.key == "reported_online")

    assert fan.value_fn(NuveState(fan_active=True)) is True
    assert fan.value_fn(NuveState()) is None
    assert hold.value_fn(NuveState(schedule_type=8)) is True
    assert hold.value_fn(NuveState(schedule_type=2)) is False
    assert hold.value_fn(NuveState()) is None
    assert led.value_fn(NuveState(led_active=True)) is True
    assert led.value_fn(NuveState()) is None
    assert online.value_fn(NuveState(online=False)) is False
    assert online.value_fn(NuveState()) is None


def test_runtime_health_entities_report_fail_closed_state() -> None:
    descriptions = {item.key: item for item in RUNTIME_BINARY_SENSORS}
    runtime = NuveRuntime(serial="00-000-000000", control_enabled=True)

    assert descriptions["control_ready"].value_fn(runtime) is False
    assert descriptions["forecast_healthy"].value_fn(runtime) is False
    assert descriptions["persistence_healthy"].value_fn(runtime) is True
    assert descriptions["uncertain_outcome"].value_fn(runtime) is False

    entity = NuveRuntimeBinarySensor(runtime, descriptions["control_ready"])
    assert entity.extra_state_attributes == {"reason": "not_paired"}


def test_installer_booleans_are_disabled_read_only_diagnostics() -> None:
    from tests.helpers import settings_upload

    runtime = NuveRuntime(serial="00-000-000000")
    runtime.settings_snapshot = settings_upload(runtime.serial)
    descriptions = {item.key: item for item in RUNTIME_BINARY_SENSORS}

    assert descriptions["automatic_auxiliary_heat"].value_fn(runtime) is True
    assert descriptions["parallel_auxiliary_heat"].value_fn(runtime) is False
    assert descriptions["compressor_lockout_configured"].value_fn(runtime) is False
    assert len(SYSTEM_BINARY_SENSOR_FIELDS) == 12
    for description in RUNTIME_BINARY_SENSORS:
        if description.key in {
            "heat_pump_emergency_configured",
            "automatic_auxiliary_heat",
            "auxiliary_heating_configured",
            "parallel_auxiliary_heat",
            "aux1_and_emergency_together",
            "auxiliary_as_emergency",
            "fan_with_auxiliary",
            "thermostat_controls_fan",
            "heating_controlled_by_furnace",
            "compressor_lockout_configured",
            "fan_with_accessory",
            "auxiliary_lockout_configured",
        }:
            assert description.entity_registry_enabled_default is False
            assert description.entity_category == EntityCategory.DIAGNOSTIC
            assert description.always_available is False
