"""Configuration selects for the Nuve display."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .data import NuveConfigEntry
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


@dataclass(frozen=True, kw_only=True)
class NuveSelectDescription(SelectEntityDescription):
    """Describe one zero-based enum stored as an integer in a settings section."""

    section: Literal["settings", "backlight"]
    field: str


SELECTS: tuple[NuveSelectDescription, ...] = (
    # Manual or ambient-adaptive display brightness.
    NuveSelectDescription(
        key="display_brightness_mode",
        translation_key="display_brightness_mode",
        options=list(BRIGHTNESS_MODES),
        entity_category=EntityCategory.CONFIG,
        section="settings",
        field="brightness_mode",
    ),
    # Exact six-way saturation model used by the Backlight page.
    NuveSelectDescription(
        key="display_backlight_shade",
        translation_key="display_backlight_shade",
        options=list(BACKLIGHT_SHADES),
        entity_category=EntityCategory.CONFIG,
        section="backlight",
        field="shadeIndex",
    ),
    # Twelve- or twenty-four-hour thermostat clock format.
    NuveSelectDescription(
        key="time_format",
        translation_key="time_format",
        options=list(TIME_FORMATS),
        entity_category=EntityCategory.CONFIG,
        section="settings",
        field="timeFormat",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NuveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nuve display selects."""

    runtime = entry.runtime_data.runtime
    async_add_entities([NuveIndexSelect(runtime, description) for description in SELECTS])


class NuveIndexSelect(NuveEntity, SelectEntity):
    """One saved display setting represented as a translated select."""

    entity_description: NuveSelectDescription

    def __init__(self, runtime: NuveRuntime, description: NuveSelectDescription) -> None:
        super().__init__(runtime)
        self.entity_description = description
        self._attr_unique_id = f"{runtime.serial}_{description.key}"

    @property
    def current_option(self) -> str | None:
        description = self.entity_description
        value = self._runtime.setting(description.section, description.field)
        options = self.options
        return options[value] if isinstance(value, int) and 0 <= value < len(options) else None

    @property
    def available(self) -> bool:
        return super().available and self.current_option is not None

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_display_option",
            )
        description = self.entity_description
        await self._run_control(
            self._runtime.async_request_settings_change(
                {description.section: {description.field: self.options.index(option)}}
            )
        )
