"""Explicitly armed Nuve baseline-capture control."""
# pyright: reportIncompatibleVariableOverride=false
# HA entity descriptors use cached_property while integrations override them
# with ordinary properties.

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import NuveEntity
from .runtime import ControlNotReadyError, NuveRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the explicit baseline-capture button."""

    runtime: NuveRuntime = entry.runtime_data
    async_add_entities([NuveBaselineCaptureButton(runtime)])


class NuveBaselineCaptureButton(NuveEntity, ButtonEntity):
    """Arm a short, firmware-verified compatibility response window."""

    _attr_translation_key = "capture_settings_baseline"
    _attr_icon = "mdi:database-import"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, runtime: NuveRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.serial}_capture_settings_baseline"

    @property
    def available(self) -> bool:
        return super().available and self._runtime.can_arm_bootstrap

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "bootstrap_status": self._runtime.bootstrap_status,
            "armed_until": (
                self._runtime.bootstrap_armed_until.isoformat()
                if self._runtime.bootstrap_armed_until
                else None
            ),
        }

    async def async_press(self) -> None:
        try:
            await self._runtime.async_arm_baseline_bootstrap(armed_at=datetime.now(UTC))
        except ControlNotReadyError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="bootstrap_not_ready",
            ) from err
