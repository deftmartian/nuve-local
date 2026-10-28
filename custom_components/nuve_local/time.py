"""Night-mode time controls for the Nuve display."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .data import NuveConfigEntry
from .entity import NuveEntity
from .runtime import NuveRuntime


@dataclass(frozen=True, kw_only=True)
class NuveTimeDescription(TimeEntityDescription):
    """Describe one minute-resolution boundary of the night-mode interval."""

    settings_key: str


NIGHT_MODE_TIMES: tuple[NuveTimeDescription, ...] = (
    NuveTimeDescription(
        key="night_mode_start",
        translation_key="night_mode_start",
        entity_category=EntityCategory.CONFIG,
        settings_key="nightModeStart",
    ),
    NuveTimeDescription(
        key="night_mode_end",
        translation_key="night_mode_end",
        entity_category=EntityCategory.CONFIG,
        settings_key="nightModeEnd",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NuveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nuve night-mode boundaries."""

    runtime = entry.runtime_data.runtime
    async_add_entities(
        [NuveNightModeTime(runtime, description) for description in NIGHT_MODE_TIMES]
    )


class NuveNightModeTime(NuveEntity, TimeEntity):
    """One minute-resolution boundary of the overnight night-mode interval."""

    entity_description: NuveTimeDescription

    def __init__(self, runtime: NuveRuntime, description: NuveTimeDescription) -> None:
        super().__init__(runtime)
        self.entity_description = description
        self._attr_unique_id = f"{runtime.serial}_{description.key}"

    @property
    def native_value(self) -> time | None:
        value = self._runtime.setting("settings", self.entity_description.settings_key)
        return time.fromisoformat(value) if isinstance(value, str) else None

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
                {"settings": {self.entity_description.settings_key: value.strftime("%H:%M:%S")}}
            )
        )
