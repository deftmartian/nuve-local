"""Base entity for Nuve Local."""
# pyright: reportIncompatibleVariableOverride=false
# HA's available descriptor is a cached_property; integrations conventionally
# override it with an ordinary property.

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
        except (ControlDisabledError, ControlNotReadyError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=(
                    "control_disabled"
                    if isinstance(err, ControlDisabledError)
                    else "control_not_ready"
                ),
            ) from err
        except ControlBusyError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="control_busy"
            ) from err
        except ControlStateChangedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="control_state_changed"
            ) from err
        except CommandTimeoutError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_timeout"
            ) from err
        except CommandOutcomeUncertainError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="outcome_uncertain"
            ) from err
        except RuntimeStoppedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="runtime_stopped"
            ) from err
        except NuveControlError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="control_failed"
            ) from err
