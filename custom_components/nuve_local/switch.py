"""Configuration switches for Nuve display and HVAC LED preferences."""
# pyright: reportIncompatibleVariableOverride=false

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import NuveEntity
from .runtime import NuveRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nuve preference switches."""

    runtime: NuveRuntime = entry.runtime_data
    async_add_entities(
        [
            NuveNightMode(runtime),
            NuveLedBlinking(runtime),
            NuveProximityDetection(runtime),
        ]
    )


class _NuveSettingsSwitch(NuveEntity, SwitchEntity):
    """One boolean owned by the complete device-settings subsection."""

    _settings_key: str

    @property
    def is_on(self) -> bool | None:
        snapshot = self._runtime.settings_snapshot
        settings = snapshot.get("settings") if snapshot is not None else None
        value = settings.get(self._settings_key) if isinstance(settings, dict) else None
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
            self._runtime.async_request_settings_change({"settings": {self._settings_key: value}})
        )


class NuveNightMode(_NuveSettingsSwitch):
    """Enable the configured overnight display-light suppression window."""

    _attr_translation_key = "night_mode"
    _attr_entity_category = EntityCategory.CONFIG
    _settings_key = "nightModeEnabled"

    def __init__(self, runtime: NuveRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.serial}_night_mode"


class NuveLedBlinking(_NuveSettingsSwitch):
    """Permit the HVAC activity LED to blink; not its physical output state."""

    _attr_translation_key = "hvac_led_blinking"
    _attr_entity_category = EntityCategory.CONFIG
    _settings_key = "ledBlinkingEnabled"

    def __init__(self, runtime: NuveRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.serial}_hvac_led_blinking"


class NuveProximityDetection(_NuveSettingsSwitch):
    """Wake the display using the time-of-flight proximity sensor."""

    _attr_translation_key = "proximity_detection"
    _attr_entity_category = EntityCategory.CONFIG
    _settings_key = "tofEnabled"

    def __init__(self, runtime: NuveRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.serial}_proximity_detection"
