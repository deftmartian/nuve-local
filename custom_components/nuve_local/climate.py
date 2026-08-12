"""Climate entity for locally confirmed Nuve Samo state and control."""
# pyright: reportIncompatibleVariableOverride=false
# HA entity descriptors use cached_property and instance attributes while
# integrations conventionally override them with properties and class attrs.

from __future__ import annotations

import math
from typing import Any, ClassVar, Never

from homeassistant.components.climate import (
    ClimateEntity,
)
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    MAX_AUTO_TEMPERATURE,
    MAX_TARGET_TEMPERATURE,
    MIN_AUTO_TEMPERATURE,
    MIN_TARGET_TEMPERATURE,
    TARGET_TEMPERATURE_STEP,
)
from .entity import NuveEntity
from .models import NuveMode
from .runtime import NuveRuntime

NUVE_TO_HA_MODE: dict[NuveMode, HVACMode] = {
    NuveMode.COOL: HVACMode.COOL,
    NuveMode.HEAT: HVACMode.HEAT,
    NuveMode.AUTO: HVACMode.HEAT_COOL,
    NuveMode.OFF: HVACMode.OFF,
}

HA_TO_NUVE_MODE: dict[HVACMode, NuveMode] = {
    HVACMode.COOL: NuveMode.COOL,
    HVACMode.HEAT: NuveMode.HEAT,
    HVACMode.HEAT_COOL: NuveMode.AUTO,
    HVACMode.OFF: NuveMode.OFF,
}

NUVE_TO_HA_FAN_MODE = {0: "auto", 1: "on", 2: "off"}
HA_TO_NUVE_FAN_MODE = {value: key for key, value in NUVE_TO_HA_FAN_MODE.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nuve climate entity."""

    runtime: NuveRuntime = entry.runtime_data
    async_add_entities([NuveClimate(runtime)])


class NuveClimate(NuveEntity, ClimateEntity):
    """A thermostat entity that reports and changes only confirmed local state."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes: ClassVar[list[HVACMode]] = list(HA_TO_NUVE_MODE)
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        | ClimateEntityFeature.FAN_MODE
    )
    _attr_fan_modes: ClassVar[list[str]] = list(HA_TO_NUVE_FAN_MODE)
    _attr_target_temperature_step = TARGET_TEMPERATURE_STEP

    def __init__(self, runtime: NuveRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.serial}_climate"

    @property
    def current_temperature(self) -> float | None:
        return self._runtime.state.current_temperature

    @property
    def min_temp(self) -> float:
        """Expose the active firmware range for normal or Auto mode."""

        return (
            MIN_AUTO_TEMPERATURE if self.hvac_mode == HVACMode.HEAT_COOL else MIN_TARGET_TEMPERATURE
        )

    @property
    def max_temp(self) -> float:
        """Expose the active firmware range for normal or Auto mode."""

        return (
            MAX_AUTO_TEMPERATURE if self.hvac_mode == HVACMode.HEAT_COOL else MAX_TARGET_TEMPERATURE
        )

    @property
    def current_humidity(self) -> float | None:
        return self._runtime.state.current_humidity

    @property
    def target_temperature(self) -> float | None:
        if self.hvac_mode == HVACMode.HEAT_COOL:
            return None
        requested = self._runtime.requested_target_temperature
        return requested if requested is not None else self._runtime.state.target_temperature

    @property
    def target_temperature_low(self) -> float | None:
        return (
            self._runtime.state.auto_temperature_low
            if self.hvac_mode == HVACMode.HEAT_COOL
            else None
        )

    @property
    def target_temperature_high(self) -> float | None:
        return (
            self._runtime.state.auto_temperature_high
            if self.hvac_mode == HVACMode.HEAT_COOL
            else None
        )

    @property
    def hvac_mode(self) -> HVACMode | None:
        mode = self._runtime.state.mode
        return NUVE_TO_HA_MODE.get(mode) if mode is not None else None

    @property
    def hvac_action(self) -> HVACAction | None:
        state = self._runtime.state
        if state.cooling_stage is not None and state.cooling_stage > 0:
            return HVACAction.COOLING
        if state.heating_stage is not None and state.heating_stage > 0:
            return HVACAction.HEATING
        if state.mode == NuveMode.OFF:
            return HVACAction.OFF
        if state.fan_active is True:
            return HVACAction.FAN
        if (
            state.mode is not None
            and state.cooling_stage == 0
            and state.heating_stage == 0
            and state.fan_active is False
        ):
            return HVACAction.IDLE
        return None

    @property
    def fan_mode(self) -> str | None:
        fan_mode = self._runtime.fan_mode
        return NUVE_TO_HA_FAN_MODE.get(fan_mode) if fan_mode is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._runtime.state
        return {
            "control_enabled": self._runtime.control_enabled,
            "control_ready": self._runtime.control_ready,
            "control_block_reason": self._runtime.control_block_reason,
            "control_status": self._runtime.command_status,
            "nuve_mode": int(state.mode) if state.mode is not None else None,
            "cooling_stage": state.cooling_stage,
            "heating_stage": state.heating_stage,
            "fan_active": state.fan_active,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        requested_mode = kwargs.get(ATTR_HVAC_MODE)
        if requested_mode is not None and HVACMode(requested_mode) != self.hvac_mode:
            self._validation_error("combined_change_unsupported")

        if self.hvac_mode == HVACMode.HEAT_COOL:
            if ATTR_TEMPERATURE in kwargs:
                self._validation_error("invalid_auto_temperature")
            low = kwargs.get(ATTR_TARGET_TEMP_LOW, self.target_temperature_low)
            high = kwargs.get(ATTR_TARGET_TEMP_HIGH, self.target_temperature_high)
            if low is None or high is None:
                self._validation_error("auto_baseline_missing")
            low = self._validated_auto_temperature(low)
            high = self._validated_auto_temperature(high)
            if low >= high:
                self._validation_error("invalid_auto_range")
            await self._run_control(
                self._runtime.async_request_auto_mode_change(
                    {"auto_temp_low": low, "auto_temp_high": high}
                )
            )
            return

        if ATTR_TARGET_TEMP_LOW in kwargs or ATTR_TARGET_TEMP_HIGH in kwargs:
            self._validation_error("range_requires_auto")
        if ATTR_TEMPERATURE not in kwargs:
            self._validation_error("temperature_required")
        temperature = self._validated_temperature(kwargs[ATTR_TEMPERATURE])
        await self._run_control(self._runtime.async_request_settings_change({"temp": temperature}))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        try:
            mode = HA_TO_NUVE_MODE[HVACMode(hvac_mode)]
        except KeyError, ValueError:
            self._validation_error("unsupported_hvac_mode")
        await self._run_control(self._runtime.async_request_settings_change({"mode_id": int(mode)}))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        try:
            mode = HA_TO_NUVE_FAN_MODE[fan_mode]
        except KeyError:
            self._validation_error("unsupported_fan_mode")
        working_per_hour = self._runtime.fan_working_per_hour
        if working_per_hour is None:
            self._validation_error("control_not_ready")
        await self._run_control(
            self._runtime.async_request_settings_change(
                {"fan": {"mode": mode, "workingPerHour": working_per_hour}}
            )
        )

    @staticmethod
    def _validated_temperature(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            NuveClimate._validation_error("invalid_temperature")
        temperature = float(value)
        if (
            not math.isfinite(temperature)
            or temperature < MIN_TARGET_TEMPERATURE
            or temperature > MAX_TARGET_TEMPERATURE
            or not math.isclose(
                temperature / TARGET_TEMPERATURE_STEP,
                round(temperature / TARGET_TEMPERATURE_STEP),
                abs_tol=1e-7,
            )
        ):
            NuveClimate._validation_error("invalid_temperature")
        return temperature

    @staticmethod
    def _validated_auto_temperature(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            NuveClimate._validation_error("invalid_auto_temperature")
        temperature = float(value)
        if (
            not math.isfinite(temperature)
            or temperature < MIN_AUTO_TEMPERATURE
            or temperature > MAX_AUTO_TEMPERATURE
            or not math.isclose(
                temperature / TARGET_TEMPERATURE_STEP,
                round(temperature / TARGET_TEMPERATURE_STEP),
                abs_tol=1e-7,
            )
        ):
            NuveClimate._validation_error("invalid_auto_temperature")
        return temperature

    @staticmethod
    def _validation_error(key: str) -> Never:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key=key)
