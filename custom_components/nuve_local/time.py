"""Night-mode time controls for the Nuve display."""
# pyright: reportIncompatibleVariableOverride=false

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import NuveEntity
from .runtime import NuveRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nuve night-mode boundaries."""

    runtime: NuveRuntime = entry.runtime_data
    async_add_entities(
        [NuveNightModeTime(runtime, start=True), NuveNightModeTime(runtime, start=False)]
    )


class NuveNightModeTime(NuveEntity, TimeEntity):
    """One minute-resolution boundary of the overnight night-mode interval."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: NuveRuntime, *, start: bool) -> None:
        super().__init__(runtime)
        self._settings_key = "nightModeStart" if start else "nightModeEnd"
        self._attr_translation_key = "night_mode_start" if start else "night_mode_end"
        self._attr_unique_id = f"{runtime.serial}_{self._attr_translation_key}"

    @property
    def native_value(self) -> time | None:
        snapshot = self._runtime.settings_snapshot
        settings = snapshot.get("settings") if snapshot is not None else None
        value = settings.get(self._settings_key) if isinstance(settings, dict) else None
        try:
            return time.fromisoformat(value) if isinstance(value, str) else None
        except ValueError:
            return None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    async def async_set_value(self, value: time) -> None:
        if value.second or value.microsecond or value.tzinfo is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_night_mode_time",
            )
        await self._run_control(
            self._runtime.async_request_settings_change(
                {"settings": {self._settings_key: value.strftime("%H:%M:%S")}}
            )
        )
