"""Base entity for Nuve Local."""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .runtime import (
    CommandOutcomeUncertainError,
    CommandTimeoutError,
    ControlBusyError,
    ControlDisabledError,
    ControlNotReadyError,
    ControlStateChangedError,
    NuveControlError,
    NuveRuntime,
    RuntimeStoppedError,
)

_CONTROL_ERRORS: dict[type[NuveControlError], tuple[type[HomeAssistantError], str]] = {
    ControlDisabledError: (ServiceValidationError, "control_disabled"),
    ControlNotReadyError: (ServiceValidationError, "control_not_ready"),
    ControlBusyError: (ServiceValidationError, "control_busy"),
    ControlStateChangedError: (HomeAssistantError, "control_state_changed"),
    CommandTimeoutError: (HomeAssistantError, "command_timeout"),
    CommandOutcomeUncertainError: (HomeAssistantError, "outcome_uncertain"),
    RuntimeStoppedError: (HomeAssistantError, "runtime_stopped"),
}


class NuveEntity(Entity):
    """Common entity behavior for a Nuve thermostat."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: NuveRuntime) -> None:
        self._runtime = runtime
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.serial)},
            manufacturer="Nuve",
            model="Samo",
            name=f"Nuve Samo {runtime.serial}",
        )

    @property
    def available(self) -> bool:
        return self._runtime.state.available and self._runtime.monitor_is_fresh

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._runtime.async_subscribe(self.async_write_ha_state))

    @staticmethod
    async def _run_control(operation: Any) -> None:
        """Translate runtime control outcomes into HA service errors."""

        try:
            await operation
        except NuveControlError as err:
            error_class, translation_key = next(
                (mapped for kind, mapped in _CONTROL_ERRORS.items() if isinstance(err, kind)),
                (HomeAssistantError, "control_failed"),
            )
            raise error_class(translation_domain=DOMAIN, translation_key=translation_key) from err
