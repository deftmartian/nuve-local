"""Automation-ready control of the Nuve display backlight."""
# pyright: reportIncompatibleVariableOverride=false

from __future__ import annotations

import math
from typing import Any, ClassVar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    LightEntity,
)
from homeassistant.components.light.const import ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import NuveEntity
from .runtime import NuveRuntime

FIXED_SHADE_HUE = 30.58823529411765


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nuve display-backlight light entity."""

    async_add_entities([NuveDisplayBacklight(entry.runtime_data)])


class NuveDisplayBacklight(NuveEntity, LightEntity):
    """Saved backlight model with its exact discrete-saturation behavior."""

    _attr_translation_key = "display_backlight"
    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {ColorMode.HS}
    _attr_color_mode = ColorMode.HS

    def __init__(self, runtime: NuveRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.serial}_display_backlight"

    @property
    def _backlight(self) -> dict[str, Any] | None:
        snapshot = self._runtime.settings_snapshot
        value = snapshot.get("backlight") if snapshot is not None else None
        return value if isinstance(value, dict) else None

    @property
    def available(self) -> bool:
        return super().available and self._backlight is not None

    @property
    def is_on(self) -> bool | None:
        value = self._backlight
        return value.get("on") if value is not None and isinstance(value.get("on"), bool) else None

    @property
    def brightness(self) -> int | None:
        value = self._backlight
        brightness = value.get("value") if value is not None else None
        if isinstance(brightness, bool) or not isinstance(brightness, (int, float)):
            return None
        return round(float(brightness) * 255)

    @property
    def hs_color(self) -> tuple[float, float] | None:
        value = self._backlight
        if value is None:
            return None
        shade_index = value.get("shadeIndex")
        hue = value.get("hue")
        if (
            isinstance(shade_index, bool)
            or not isinstance(shade_index, int)
            or isinstance(hue, bool)
            or not isinstance(hue, (int, float))
        ):
            return None
        if shade_index < 5:
            return (FIXED_SHADE_HUE, shade_index * 25.0)
        return (float(hue) * 360.0, 100.0)

    async def async_turn_on(self, **kwargs: Any) -> None:
        changes: dict[str, Any] = {"on": True}
        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
            if (
                isinstance(brightness, bool)
                or not isinstance(brightness, int | float)
                or not math.isfinite(float(brightness))
                or not 0 <= float(brightness) <= 255
            ):
                self._raise_invalid_value()
            changes["value"] = float(brightness) / 255.0
        if ATTR_HS_COLOR in kwargs:
            color = kwargs[ATTR_HS_COLOR]
            if not isinstance(color, tuple | list) or len(color) != 2:
                self._raise_invalid_value()
            hue, saturation = color
            if (
                isinstance(hue, bool)
                or not isinstance(hue, int | float)
                or not math.isfinite(float(hue))
                or not 0 <= float(hue) <= 360
                or isinstance(saturation, bool)
                or not isinstance(saturation, int | float)
                or not math.isfinite(float(saturation))
                or not 0 <= float(saturation) <= 100
            ):
                self._raise_invalid_value()
            if saturation >= 87.5:
                changes.update({"hue": (float(hue) % 360.0) / 360.0, "shadeIndex": 5})
            else:
                changes["shadeIndex"] = round(float(saturation) / 25.0)
        await self._run_control(self._runtime.async_request_settings_change({"backlight": changes}))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._run_control(
            self._runtime.async_request_settings_change({"backlight": {"on": False}})
        )

    @staticmethod
    def _raise_invalid_value() -> None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_display_option",
        )
