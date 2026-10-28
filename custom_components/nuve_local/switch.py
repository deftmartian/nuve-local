"""Configuration switches for Nuve display and HVAC LED preferences."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .data import NuveConfigEntry
from .entity import NuveEntity
from .runtime import NuveRuntime


@dataclass(frozen=True, kw_only=True)
class NuveSwitchDescription(SwitchEntityDescription):
    """Describe one boolean owned by the complete device-settings subsection."""

    settings_key: str


SWITCHES: tuple[NuveSwitchDescription, ...] = (
    # Enable the configured overnight display-light suppression window.
    NuveSwitchDescription(
        key="night_mode",
        translation_key="night_mode",
        entity_category=EntityCategory.CONFIG,
        settings_key="nightModeEnabled",
    ),
    # Permit the HVAC activity LED to blink; not its physical output state.
    NuveSwitchDescription(
        key="hvac_led_blinking",
        translation_key="hvac_led_blinking",
        entity_category=EntityCategory.CONFIG,
        settings_key="ledBlinkingEnabled",
    ),
    # Wake the display using the time-of-flight proximity sensor.
    NuveSwitchDescription(
        key="proximity_detection",
        translation_key="proximity_detection",
        entity_category=EntityCategory.CONFIG,
        settings_key="tofEnabled",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NuveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nuve preference switches."""

    runtime = entry.runtime_data.runtime
    async_add_entities([NuveSettingsSwitch(runtime, description) for description in SWITCHES])


class NuveSettingsSwitch(NuveEntity, SwitchEntity):
    """One boolean owned by the complete device-settings subsection."""

    entity_description: NuveSwitchDescription

    def __init__(self, runtime: NuveRuntime, description: NuveSwitchDescription) -> None:
        super().__init__(runtime)
        self.entity_description = description
        self._attr_unique_id = f"{runtime.serial}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        value = self._runtime.setting("settings", self.entity_description.settings_key)
        return value if isinstance(value, bool) else None

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._set_value(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._set_value(False)

    async def _set_value(self, value: bool) -> None:
        await self._run_control(
            self._runtime.async_request_settings_change(
                {"settings": {self.entity_description.settings_key: value}}
            )
        )
