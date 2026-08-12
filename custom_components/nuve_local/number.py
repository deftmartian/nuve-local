"""Writable, canonical Nuve fan-circulation settings."""
# pyright: reportIncompatibleVariableOverride=false
# HA entity descriptors use cached_property while integrations override them
# with ordinary properties.

from __future__ import annotations

import math

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    MAX_FAN_WORKING_PER_HOUR,
    MIN_FAN_WORKING_PER_HOUR,
)
from .entity import NuveEntity
from .runtime import NuveRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nuve fan circulation number."""

    runtime: NuveRuntime = entry.runtime_data
    async_add_entities(
        [
            NuveFanWorkingPerHour(runtime),
            NuveDisplayBrightness(runtime),
        ]
    )


class NuveFanWorkingPerHour(NuveEntity, NumberEntity):
    """Configured fan circulation minutes in each hour."""

    _attr_translation_key = "fan_working_per_hour"
    _attr_native_min_value = MIN_FAN_WORKING_PER_HOUR
    _attr_native_max_value = MAX_FAN_WORKING_PER_HOUR
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: NuveRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.serial}_fan_working_per_hour"

    @property
    def native_value(self) -> int | None:
        return self._runtime.fan_working_per_hour

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    async def async_set_native_value(self, value: float) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or not float(value).is_integer()
            or not MIN_FAN_WORKING_PER_HOUR <= value <= MAX_FAN_WORKING_PER_HOUR
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_fan_working_per_hour",
            )
        mode = self._runtime.fan_mode
        if mode is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="control_not_ready",
            )
        await self._run_control(
            self._runtime.async_request_settings_change(
                {"fan": {"mode": mode, "workingPerHour": int(value)}}
            )
        )


class NuveDisplayBrightness(NuveEntity, NumberEntity):
    """Saved display brightness, distinct from the backlight color value."""

    _attr_translation_key = "display_brightness"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: NuveRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.serial}_display_brightness"

    @property
    def native_value(self) -> int | None:
        snapshot = self._runtime.settings_snapshot
        settings = snapshot.get("settings") if snapshot is not None else None
        value = settings.get("brightness") if isinstance(settings, dict) else None
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    async def async_set_native_value(self, value: float) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or not float(value).is_integer()
            or not 0 <= value <= 100
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_display_brightness",
            )
        await self._run_control(
            self._runtime.async_request_settings_change({"settings": {"brightness": int(value)}})
        )
