"""Binary telemetry entities for the Nuve thermostat."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,  # pyright: ignore[reportPrivateImportUsage]
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .data import NuveConfigEntry
from .entity import NuveEntity
from .runtime import NuveRuntime


@dataclass(frozen=True, kw_only=True)
class NuveBinarySensorDescription(BinarySensorEntityDescription):
    """Describe one binary value read from the runtime."""

    value_fn: Callable[[NuveRuntime], bool | None]
    # "device": available while the thermostat is live (pushed telemetry);
    # "value": available once the value is known; "always": health conditions.
    availability: Literal["device", "value", "always"] = "value"


def _hold_active(runtime: NuveRuntime) -> bool | None:
    schedule_type = runtime.state.schedule_type
    return None if schedule_type is None else schedule_type == 8


def _system_bool(runtime: NuveRuntime, key: str) -> bool | None:
    """Return one already protocol-validated installer boolean."""

    value = runtime.setting("system", key)
    return value if isinstance(value, bool) else None


def _system_binary_sensor(
    *, key: str, translation_key: str, system_key: str
) -> NuveBinarySensorDescription:
    """Describe one disabled, read-only installer boolean."""

    return NuveBinarySensorDescription(
        key=key,
        translation_key=translation_key,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda runtime: _system_bool(runtime, system_key),
    )


BINARY_SENSORS: tuple[NuveBinarySensorDescription, ...] = (
    NuveBinarySensorDescription(
        availability="device",
        key="fan_active",
        translation_key="fan_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda runtime: runtime.state.fan_active,
    ),
    NuveBinarySensorDescription(
        availability="device",
        key="hold_active",
        translation_key="hold_active",
        value_fn=lambda runtime: (
            None if runtime.state.schedule_type is None else runtime.state.schedule_type == 8
        ),
    ),
    NuveBinarySensorDescription(
        availability="device",
        key="status_led_active",
        translation_key="status_led_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda runtime: runtime.state.led_active,
    ),
    NuveBinarySensorDescription(
        availability="device",
        key="reported_online",
        translation_key="reported_online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda runtime: runtime.state.online,
    ),
)

RUNTIME_BINARY_SENSORS: tuple[NuveBinarySensorDescription, ...] = (
    NuveBinarySensorDescription(
        key="control_ready",
        translation_key="control_ready",
        availability="always",
        value_fn=lambda runtime: runtime.control_ready,
    ),
    NuveBinarySensorDescription(
        key="canonical_sync_ready",
        translation_key="canonical_sync_ready",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability="always",
        value_fn=lambda runtime: runtime.canonical_live_consistency_ready,
    ),
    NuveBinarySensorDescription(
        key="monitor_fresh",
        translation_key="monitor_fresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability="always",
        value_fn=lambda runtime: runtime.monitor_is_fresh,
    ),
    NuveBinarySensorDescription(
        key="persistence_healthy",
        translation_key="persistence_healthy",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability="always",
        value_fn=lambda runtime: runtime.persistence_healthy,
    ),
    NuveBinarySensorDescription(
        key="outdoor_temperature_fresh",
        translation_key="outdoor_temperature_fresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability="always",
        value_fn=lambda runtime: runtime.outdoor_is_fresh,
    ),
    NuveBinarySensorDescription(
        key="forecast_healthy",
        translation_key="forecast_healthy",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability="always",
        value_fn=lambda runtime: runtime.forecast_healthy,
    ),
    NuveBinarySensorDescription(
        key="uncertain_outcome",
        translation_key="uncertain_outcome",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability="always",
        value_fn=lambda runtime: runtime.uncertain_outcome,
    ),
    NuveBinarySensorDescription(
        key="contractor_info_ready",
        translation_key="contractor_info_ready",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        availability="always",
        value_fn=lambda runtime: runtime.contractor_info_ready,
    ),
    _system_binary_sensor(
        key="heat_pump_emergency_configured",
        translation_key="heat_pump_emergency_configured",
        system_key="heatPumpEmergency",
    ),
    _system_binary_sensor(
        key="automatic_auxiliary_heat",
        translation_key="automatic_auxiliary_heat",
        system_key="isAUXAuto",
    ),
    _system_binary_sensor(
        key="auxiliary_heating_configured",
        translation_key="auxiliary_heating_configured",
        system_key="auxiliaryHeating",
    ),
    _system_binary_sensor(
        key="parallel_auxiliary_heat",
        translation_key="parallel_auxiliary_heat",
        system_key="useAuxiliaryParallelHeatPump",
    ),
    _system_binary_sensor(
        key="aux1_and_emergency_together",
        translation_key="aux1_and_emergency_together",
        system_key="driveAux1AndETogether",
    ),
    _system_binary_sensor(
        key="auxiliary_as_emergency",
        translation_key="auxiliary_as_emergency",
        system_key="driveAuxAsEmergency",
    ),
    _system_binary_sensor(
        key="fan_with_auxiliary",
        translation_key="fan_with_auxiliary",
        system_key="runFanWithAuxiliary",
    ),
    _system_binary_sensor(
        key="thermostat_controls_fan",
        translation_key="thermostat_controls_fan",
        system_key="thermostatControlFan",
    ),
    _system_binary_sensor(
        key="heating_controlled_by_furnace",
        translation_key="heating_controlled_by_furnace",
        system_key="heatingControlByFurnace",
    ),
    _system_binary_sensor(
        key="compressor_lockout_configured",
        translation_key="compressor_lockout_configured",
        system_key="compressorLockout",
    ),
    _system_binary_sensor(
        key="fan_with_accessory",
        translation_key="fan_with_accessory",
        system_key="fanWithAccessory",
    ),
    _system_binary_sensor(
        key="auxiliary_lockout_configured",
        translation_key="auxiliary_lockout_configured",
        system_key="aux_lockout",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NuveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up confirmed Nuve binary telemetry."""

    runtime = entry.runtime_data.runtime
    async_add_entities(
        [
            *(
                NuveBinarySensor(runtime, description)
                for description in (*BINARY_SENSORS, *RUNTIME_BINARY_SENSORS)
            ),
        ]
    )


class NuveBinarySensor(NuveEntity, BinarySensorEntity):
    """A binary sensor backed by pushed telemetry or Nuve Local runtime state."""

    entity_description: NuveBinarySensorDescription

    def __init__(self, runtime: NuveRuntime, description: NuveBinarySensorDescription) -> None:
        super().__init__(runtime)
        self.entity_description = description
        self._attr_unique_id = f"{runtime.serial}_{description.key}"

    @property
    def available(self) -> bool:
        match self.entity_description.availability:
            case "device":
                return super().available
            case "always":
                return True
            case _:
                return self.is_on is not None

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self._runtime)

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Explain the enabled control gate without exposing private state."""

        if self.entity_description.key == "control_ready":
            return {"reason": self._runtime.control_block_reason}
        return None
