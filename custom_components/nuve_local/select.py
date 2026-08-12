"""Configuration selects for the Nuve display."""
# pyright: reportIncompatibleVariableOverride=false

from __future__ import annotations

from typing import ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import NuveEntity
from .runtime import NuveRuntime

BRIGHTNESS_MODES = ("manual", "adaptive")
TIME_FORMATS = ("12_hour", "24_hour")
BACKLIGHT_SHADES = (
    "white_0",
    "white_25",
    "white_50",
    "white_75",
    "white_100",
    "color",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nuve display selects."""

    runtime: NuveRuntime = entry.runtime_data
    async_add_entities(
        [
            NuveBrightnessMode(runtime),
            NuveBacklightShade(runtime),
            NuveTimeFormat(runtime),
        ]
    )


class NuveBrightnessMode(NuveEntity, SelectEntity):
    """Manual or ambient-adaptive display brightness."""

    _attr_translation_key = "display_brightness_mode"
    _attr_options: ClassVar[list[str]] = list(BRIGHTNESS_MODES)
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: NuveRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.serial}_display_brightness_mode"

    @property
    def current_option(self) -> str | None:
        snapshot = self._runtime.settings_snapshot
        settings = snapshot.get("settings") if snapshot is not None else None
        value = settings.get("brightness_mode") if isinstance(settings, dict) else None
        return BRIGHTNESS_MODES[value] if isinstance(value, int) and value in (0, 1) else None

    @property
    def available(self) -> bool:
        return super().available and self.current_option is not None

    async def async_select_option(self, option: str) -> None:
        if option not in BRIGHTNESS_MODES:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_display_option",
            )
        await self._run_control(
            self._runtime.async_request_settings_change(
                {"settings": {"brightness_mode": BRIGHTNESS_MODES.index(option)}}
            )
        )


class NuveBacklightShade(NuveEntity, SelectEntity):
    """Exact six-way saturation model used by the Backlight page."""

    _attr_translation_key = "display_backlight_shade"
    _attr_options: ClassVar[list[str]] = list(BACKLIGHT_SHADES)
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: NuveRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.serial}_display_backlight_shade"

    @property
    def current_option(self) -> str | None:
        snapshot = self._runtime.settings_snapshot
        backlight = snapshot.get("backlight") if snapshot is not None else None
        value = backlight.get("shadeIndex") if isinstance(backlight, dict) else None
        return BACKLIGHT_SHADES[value] if isinstance(value, int) and 0 <= value <= 5 else None

    @property
    def available(self) -> bool:
        return super().available and self.current_option is not None

    async def async_select_option(self, option: str) -> None:
        if option not in BACKLIGHT_SHADES:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_display_option",
            )
        await self._run_control(
            self._runtime.async_request_settings_change(
                {"backlight": {"shadeIndex": BACKLIGHT_SHADES.index(option)}}
            )
        )


class _NuveBinarySettingsSelect(NuveEntity, SelectEntity):
    """One zero-or-one setting represented as a translated select."""

    _settings_key: str

    @property
    def current_option(self) -> str | None:
        snapshot = self._runtime.settings_snapshot
        settings = snapshot.get("settings") if snapshot is not None else None
        value = settings.get(self._settings_key) if isinstance(settings, dict) else None
        return self.options[value] if isinstance(value, int) and value in (0, 1) else None

    @property
    def available(self) -> bool:
        return super().available and self.current_option is not None

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_display_option",
            )
        await self._run_control(
            self._runtime.async_request_settings_change(
                {"settings": {self._settings_key: self.options.index(option)}}
            )
        )


class NuveTimeFormat(_NuveBinarySettingsSelect):
    """Twelve- or twenty-four-hour thermostat clock format."""

    _attr_translation_key = "time_format"
    _attr_options: ClassVar[list[str]] = list(TIME_FORMATS)
    _attr_entity_category = EntityCategory.CONFIG
    _settings_key = "timeFormat"

    def __init__(self, runtime: NuveRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.serial}_time_format"
