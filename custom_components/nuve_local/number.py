"""Writable, canonical Nuve fan-circulation and display settings."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    MAX_FAN_WORKING_PER_HOUR,
    MIN_FAN_WORKING_PER_HOUR,
)
from .data import NuveConfigEntry
from .entity import NuveEntity
from .runtime import NuveRuntime


@dataclass(frozen=True, kw_only=True)
class NuveNumberDescription(NumberEntityDescription):
    """Describe one writable integer setting."""

    value_fn: Callable[[NuveRuntime], Any]
    # Builds the settings change for a validated value, or None when the
    # prerequisite state (the fan mode) is not known.
    change_fn: Callable[[NuveRuntime, int], dict[str, Any] | None]
    invalid_translation_key: str


def _fan_change(runtime: NuveRuntime, value: int) -> dict[str, Any] | None:
    mode = runtime.fan_mode
    return None if mode is None else {"fan": {"mode": mode, "workingPerHour": value}}


NUMBERS: tuple[NuveNumberDescription, ...] = (
    # Configured fan circulation minutes in each hour.
    NuveNumberDescription(
        key="fan_working_per_hour",
        translation_key="fan_working_per_hour",
        native_min_value=MIN_FAN_WORKING_PER_HOUR,
        native_max_value=MAX_FAN_WORKING_PER_HOUR,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda runtime: runtime.fan_working_per_hour,
        change_fn=_fan_change,
        invalid_translation_key="invalid_fan_working_per_hour",
    ),
    # Saved display brightness, distinct from the backlight color value.
    NuveNumberDescription(
        key="display_brightness",
        translation_key="display_brightness",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda runtime: runtime.setting("settings", "brightness"),
        change_fn=lambda runtime, value: {"settings": {"brightness": value}},
        invalid_translation_key="invalid_display_brightness",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NuveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nuve fan circulation and display brightness numbers."""

    runtime = entry.runtime_data.runtime
    async_add_entities([NuveNumber(runtime, description) for description in NUMBERS])


class NuveNumber(NuveEntity, NumberEntity):
    """A writable integer owned by the device's saved settings."""

    entity_description: NuveNumberDescription

    def __init__(self, runtime: NuveRuntime, description: NuveNumberDescription) -> None:
        super().__init__(runtime)
        self.entity_description = description
        self._attr_unique_id = f"{runtime.serial}_{description.key}"

    @property
    def native_value(self) -> int | None:
        value = self.entity_description.value_fn(self._runtime)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    async def async_set_native_value(self, value: float) -> None:
        description = self.entity_description
        assert description.native_min_value is not None
        assert description.native_max_value is not None
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or not float(value).is_integer()
            or not description.native_min_value <= value <= description.native_max_value
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=description.invalid_translation_key,
            )
        change = description.change_fn(self._runtime, int(value))
        if change is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="control_not_ready",
            )
        await self._run_control(self._runtime.async_request_settings_change(change))
