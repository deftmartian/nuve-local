"""Sensor entities for Nuve Local."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .data import NuveConfigEntry
from .entity import NuveEntity
from .models import NuveSystemType
from .runtime import NuveRuntime

AIR_QUALITY_OPTIONS = ("none", "level_0", "level_1", "level_2")
SYSTEM_TYPE_OPTIONS = (
    "none",
    "traditional",
    "heat_pump",
    "cooling_only",
    "heating_only",
    "dual_fuel_heating",
)
SCHEDULE_TYPE_OPTIONS = {
    0: "sleep",
    1: "wake",
    2: "home",
    3: "away",
    8: "hold",
    9: "none",
}


def _air_quality_value(runtime: NuveRuntime) -> str | None:
    """Return the firmware's category without guessing its direction."""

    level = runtime.state.air_quality_level
    if level is None:
        return None
    try:
        return AIR_QUALITY_OPTIONS[level]
    except IndexError:
        return None


def _system_type_value(runtime: NuveRuntime) -> str | None:
    """Return the firmware's exact equipment category."""

    system_type = runtime.state.system_type
    if system_type is None:
        return None
    try:
        return SYSTEM_TYPE_OPTIONS[NuveSystemType(system_type)]
    except IndexError, ValueError:
        return None


def _schedule_type_value(runtime: NuveRuntime) -> str | None:
    """Return the exact schedule category declared by the protobuf."""

    schedule_type = runtime.state.schedule_type
    if schedule_type is None:
        return None
    return SCHEDULE_TYPE_OPTIONS.get(schedule_type)


@dataclass(frozen=True, kw_only=True)
class NuveSensorEntityDescription(SensorEntityDescription):
    """Describe one value read from the runtime."""

    value_fn: Callable[[NuveRuntime], bool | float | int | str | datetime | None]
    # Pushed telemetry is available while the thermostat is live; canonical
    # settings diagnostics are available once their value is known.
    telemetry: bool = False


def _system_value(runtime: NuveRuntime, key: str) -> bool | float | int | str | None:
    """Return one already protocol-validated, non-private system value."""

    value = runtime.setting("system", key)
    return value if isinstance(value, bool | float | int | str) else None


def _accessory_value(runtime: NuveRuntime, key: str) -> int | str | None:
    """Return one exact member of the validated accessory configuration."""

    accessories = runtime.setting("system", "systemAccessories")
    value = accessories.get(key) if isinstance(accessories, dict) else None
    return value if isinstance(value, int | str) and not isinstance(value, bool) else None


def _firmware_version(runtime: NuveRuntime) -> str | None:
    value = runtime.setting("firmware", "firmware-version")
    return value if isinstance(value, str) and value else None


def _wifi_strength(runtime: NuveRuntime) -> str | None:
    value = runtime.setting("system", "wifiStrength")
    return value if isinstance(value, str) and value else None


def _system_sensor(
    *,
    key: str,
    translation_key: str,
    system_key: str,
    device_class: SensorDeviceClass | None = None,
    unit: str | None = None,
    precision: int | None = None,
) -> NuveSensorEntityDescription:
    """Describe one disabled, read-only installer diagnostic."""

    return NuveSensorEntityDescription(
        key=key,
        translation_key=translation_key,
        device_class=device_class,
        native_unit_of_measurement=unit,
        suggested_display_precision=precision,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda runtime: _system_value(runtime, system_key),
    )


SENSORS: tuple[NuveSensorEntityDescription, ...] = (
    NuveSensorEntityDescription(
        telemetry=True,
        key="current_temperature",
        translation_key="current_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda runtime: runtime.state.current_temperature,
    ),
    NuveSensorEntityDescription(
        telemetry=True,
        key="current_humidity",
        translation_key="current_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda runtime: runtime.state.current_humidity,
    ),
    NuveSensorEntityDescription(
        telemetry=True,
        key="air_quality_level",
        translation_key="air_quality_level",
        device_class=SensorDeviceClass.ENUM,
        options=list(AIR_QUALITY_OPTIONS),
        value_fn=_air_quality_value,
    ),
    NuveSensorEntityDescription(
        telemetry=True,
        key="air_pressure",
        translation_key="air_pressure",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda runtime: runtime.state.air_pressure,
    ),
    NuveSensorEntityDescription(
        telemetry=True,
        key="target_temperature",
        translation_key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda runtime: runtime.state.target_temperature,
    ),
    NuveSensorEntityDescription(
        telemetry=True,
        key="target_humidity",
        translation_key="target_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda runtime: runtime.state.target_humidity,
    ),
    NuveSensorEntityDescription(
        telemetry=True,
        key="auto_temperature_low",
        translation_key="auto_temperature_low",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        suggested_display_precision=1,
        value_fn=lambda runtime: runtime.state.auto_temperature_low,
    ),
    NuveSensorEntityDescription(
        telemetry=True,
        key="auto_temperature_high",
        translation_key="auto_temperature_high",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        suggested_display_precision=1,
        value_fn=lambda runtime: runtime.state.auto_temperature_high,
    ),
    NuveSensorEntityDescription(
        telemetry=True,
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda runtime: runtime.state.last_seen,
    ),
    NuveSensorEntityDescription(
        telemetry=True,
        key="cooling_stage",
        translation_key="cooling_stage",
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda runtime: runtime.state.cooling_stage,
    ),
    NuveSensorEntityDescription(
        telemetry=True,
        key="heating_stage",
        translation_key="heating_stage",
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda runtime: runtime.state.heating_stage,
    ),
    NuveSensorEntityDescription(
        telemetry=True,
        key="system_type",
        translation_key="system_type",
        device_class=SensorDeviceClass.ENUM,
        options=list(SYSTEM_TYPE_OPTIONS),
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_system_type_value,
    ),
    NuveSensorEntityDescription(
        telemetry=True,
        key="schedule_type",
        translation_key="schedule_type",
        device_class=SensorDeviceClass.ENUM,
        options=list(SCHEDULE_TYPE_OPTIONS.values()),
        value_fn=_schedule_type_value,
    ),
    NuveSensorEntityDescription(
        telemetry=True,
        key="mcu_temperature",
        translation_key="mcu_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=1,
        value_fn=lambda runtime: runtime.state.mcu_temperature,
    ),
)

RUNTIME_SENSORS: tuple[NuveSensorEntityDescription, ...] = (
    NuveSensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_firmware_version,
    ),
    NuveSensorEntityDescription(
        key="wifi_strength",
        translation_key="wifi_strength",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_wifi_strength,
    ),
    NuveSensorEntityDescription(
        key="configured_equipment_type",
        translation_key="configured_equipment_type",
        device_class=SensorDeviceClass.ENUM,
        options=["traditional", "heat_pump", "cooling", "heating", "dual_fuel_heating"],
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda runtime: _system_value(runtime, "type"),
    ),
    _system_sensor(
        key="configured_cooling_stages",
        translation_key="configured_cooling_stages",
        system_key="coolStage",
        precision=0,
    ),
    _system_sensor(
        key="configured_heating_stages",
        translation_key="configured_heating_stages",
        system_key="heatStage",
        precision=0,
    ),
    _system_sensor(
        key="heat_pump_reversing_valve_code",
        translation_key="heat_pump_reversing_valve_code",
        system_key="heatPumpOBState",
        precision=0,
    ),
    _system_sensor(
        key="system_run_delay",
        translation_key="system_run_delay",
        system_key="systemRunDelay",
        device_class=SensorDeviceClass.DURATION,
        unit=UnitOfTime.MINUTES,
        precision=0,
    ),
    _system_sensor(
        key="dual_fuel_threshold",
        translation_key="dual_fuel_threshold",
        system_key="dualFuelThreshold",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        precision=1,
    ),
    _system_sensor(
        key="dual_fuel_manual_heating_code",
        translation_key="dual_fuel_manual_heating_code",
        system_key="dualFuelManualHeating",
        precision=0,
    ),
    _system_sensor(
        key="dual_fuel_default_heating_mode_code",
        translation_key="dual_fuel_default_heating_mode_code",
        system_key="dualFuelHeatingModeDefault",
        precision=0,
    ),
    _system_sensor(
        key="emergency_minimum_time",
        translation_key="emergency_minimum_time",
        system_key="emergencyMinimumTime",
        device_class=SensorDeviceClass.DURATION,
        unit=UnitOfTime.MINUTES,
        precision=0,
    ),
    _system_sensor(
        key="auxiliary_unreached_delay",
        translation_key="auxiliary_unreached_delay",
        system_key="turnAuxOnUnreaching",
        device_class=SensorDeviceClass.DURATION,
        unit=UnitOfTime.MINUTES,
        precision=0,
    ),
    _system_sensor(
        key="temperature_correction",
        translation_key="temperature_correction",
        system_key="tempCorrection",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        precision=1,
    ),
    _system_sensor(
        key="overcool",
        translation_key="overcool",
        system_key="overcool",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        precision=1,
    ),
    _system_sensor(
        key="auxiliary_engagement_difference",
        translation_key="auxiliary_engagement_difference",
        system_key="diffToEngageAux",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        precision=1,
    ),
    _system_sensor(
        key="heat_dissipation_time",
        translation_key="heat_dissipation_time",
        system_key="heat_dissipation_time",
        device_class=SensorDeviceClass.DURATION,
        unit=UnitOfTime.MINUTES,
        precision=1,
    ),
    _system_sensor(
        key="cool_dissipation_time",
        translation_key="cool_dissipation_time",
        system_key="cool_dissipation_time",
        device_class=SensorDeviceClass.DURATION,
        unit=UnitOfTime.MINUTES,
        precision=1,
    ),
    NuveSensorEntityDescription(
        key="accessory_wire",
        translation_key="accessory_wire",
        device_class=SensorDeviceClass.ENUM,
        options=["T1PWRD", "T1Short", "T2PWRD", "None"],
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda runtime: _accessory_value(runtime, "wire"),
    ),
    NuveSensorEntityDescription(
        key="accessory_mode_code",
        translation_key="accessory_mode_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
        value_fn=lambda runtime: _accessory_value(runtime, "mode"),
    ),
    _system_sensor(
        key="heat_deadband",
        translation_key="heat_deadband",
        system_key="heat_deadband",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        precision=1,
    ),
    _system_sensor(
        key="cool_deadband",
        translation_key="cool_deadband",
        system_key="cool_deadband",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        precision=1,
    ),
    _system_sensor(
        key="auxiliary_lockout_threshold",
        translation_key="auxiliary_lockout_threshold",
        system_key="aux_lockout_threshold",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        precision=1,
    ),
    _system_sensor(
        key="heat_minimum_on_time",
        translation_key="heat_minimum_on_time",
        system_key="heat_min_on_time",
        device_class=SensorDeviceClass.DURATION,
        unit=UnitOfTime.MINUTES,
        precision=1,
    ),
    _system_sensor(
        key="cool_minimum_on_time",
        translation_key="cool_minimum_on_time",
        system_key="cool_min_on_time",
        device_class=SensorDeviceClass.DURATION,
        unit=UnitOfTime.MINUTES,
        precision=1,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NuveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nuve Local sensors."""

    runtime = entry.runtime_data.runtime
    async_add_entities(
        [
            *(NuveSensor(runtime, description) for description in (*SENSORS, *RUNTIME_SENSORS)),
        ]
    )


class NuveSensor(NuveEntity, SensorEntity):
    """A sensor backed by pushed telemetry or a validated canonical settings field."""

    entity_description: NuveSensorEntityDescription

    def __init__(self, runtime: NuveRuntime, description: NuveSensorEntityDescription) -> None:
        super().__init__(runtime)
        self.entity_description = description
        self._attr_unique_id = f"{runtime.serial}_{description.key}"

    @property
    def available(self) -> bool:
        if self.entity_description.telemetry:
            return super().available
        return self.native_value is not None

    @property
    def native_value(self) -> bool | float | int | str | datetime | None:
        return self.entity_description.value_fn(self._runtime)
