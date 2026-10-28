"""Home Assistant weather sources projected into the thermostat's outdoor data."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_state_report_event,
    async_track_time_interval,
)
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    FORECAST_REFRESH_MINUTES,
    FORECAST_REQUEST_TIMEOUT_SECONDS,
    MAX_OUTDOOR_TEMPERATURE,
    MIN_OUTDOOR_TEMPERATURE,
)
from .weather import build_forecast_payload, condition_weather, display_location_name

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .runtime import NuveRuntime

_LOGGER = logging.getLogger(__name__)


def validated_outdoor_temperature_c(value: Any, unit: Any) -> float:
    """Convert one explicitly unit-tagged outdoor observation to safe Celsius."""

    if not isinstance(unit, str) or not unit:
        raise ValueError("outdoor temperature is missing its unit")
    value_c = TemperatureConverter.convert(float(value), unit, UnitOfTemperature.CELSIUS)
    if (
        not math.isfinite(value_c)
        or not MIN_OUTDOOR_TEMPERATURE <= value_c <= MAX_OUTDOOR_TEMPERATURE
    ):
        raise ValueError("outdoor temperature is outside the validated range")
    return value_c


def validated_humidity(value: Any) -> float | None:
    """Return one finite relative-humidity percentage when present."""

    try:
        humidity = float(value) if value is not None else None
    except TypeError, ValueError:
        return None
    if humidity is None or not math.isfinite(humidity) or not 0 <= humidity <= 100:
        return None
    return humidity


UNUSABLE_STATES = frozenset({"unknown", "unavailable"})


def register_outdoor_updates(
    hass: HomeAssistant,
    runtime: NuveRuntime,
    *,
    outdoor_entity_id: str | None,
    weather_entity_id: str | None,
) -> list[Callable[[], None]]:
    """Project configured HA states into the thermostat's outdoor observation."""

    @callback
    def update_outdoor_temperature(*_: Any) -> None:
        weather_state = hass.states.get(weather_entity_id) if weather_entity_id else None
        weather_humidity = (
            validated_humidity(weather_state.attributes.get("humidity"))
            if weather_state is not None
            else None
        )
        weather_item = (
            condition_weather(weather_state.state)
            if weather_state is not None and weather_state.state not in UNUSABLE_STATES
            else None
        )
        weather_location = (
            display_location_name(weather_state.name) if weather_state is not None else None
        )
        # The override sensor wins; the weather entity is the fallback source.
        sources = []
        if outdoor_entity_id:
            sensor = hass.states.get(outdoor_entity_id)
            if sensor is not None:
                sources.append(
                    (
                        sensor,
                        sensor.state,
                        sensor.attributes.get(ATTR_UNIT_OF_MEASUREMENT),
                        "override_sensor",
                    )
                )
        if weather_entity_id and weather_state is not None:
            sources.append(
                (
                    weather_state,
                    weather_state.attributes.get("temperature"),
                    weather_state.attributes.get("temperature_unit"),
                    "weather_entity",
                )
            )
        for state, value, unit, source in sources:
            if state.state in UNUSABLE_STATES:
                continue
            try:
                value_c = validated_outdoor_temperature_c(value, unit)
            except HomeAssistantError, TypeError, ValueError:
                continue
            humidity = validated_humidity(state.attributes.get("humidity"))
            if humidity is None and source == "override_sensor":
                humidity = weather_humidity
            runtime.async_set_outdoor_temperature(
                value_c,
                weather_location or state.name,
                humidity_percent=humidity,
                weather=weather_item,
                observed_at=state.last_reported,
                source=source,
            )
            return
        runtime.async_set_outdoor_temperature(None, "Local weather unavailable")

    update_outdoor_temperature()
    source_entity_ids = [
        entity_id for entity_id in (outdoor_entity_id, weather_entity_id) if entity_id
    ]
    return [
        async_track_state_change_event(hass, source_entity_ids, update_outdoor_temperature),
        async_track_state_report_event(hass, source_entity_ids, update_outdoor_temperature),
    ]


class ForecastRefresh:
    """Bound, coalesced daily-forecast projection owned by one config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        runtime: NuveRuntime,
        *,
        weather_entity_id: str,
    ) -> None:
        self._hass = hass
        self._runtime = runtime
        self._weather_entity_id = weather_entity_id
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._repeat = False
        self._closed = False
        self._unsubs: list[Callable[[], None]] = []

    def listen(self) -> None:
        """Subscribe to source updates after the first bounded refresh."""

        @callback
        def refresh_forecast_from_source(*_: Any) -> None:
            self.schedule()

        self._unsubs.append(
            async_track_state_change_event(
                self._hass,
                [self._weather_entity_id],
                refresh_forecast_from_source,
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self._hass,
                refresh_forecast_from_source,
                timedelta(minutes=FORECAST_REFRESH_MINUTES),
                name="Nuve Local daily forecast refresh",
            )
        )

    def schedule(self) -> None:
        """Start or coalesce one in-flight refresh."""

        if self._closed:
            return
        if self._task is not None and not self._task.done():
            self._repeat = True
            return
        self._task = self._hass.async_create_task(
            self._run_until_quiet(),
            "Refresh Nuve Local daily forecast after source update",
        )

    async def _run_until_quiet(self) -> None:
        try:
            while not self._closed:
                self._repeat = False
                await self.async_refresh()
                if not self._repeat:
                    return
        finally:
            self._task = None

    async def async_refresh(self) -> None:
        """Fetch one bounded daily forecast without blocking the listener."""

        if self._closed:
            return
        async with self._lock:
            if self._closed:
                return
            source = self._hass.states.get(self._weather_entity_id)
            if source is None or source.state in {"unknown", "unavailable"}:
                self._runtime.async_set_forecast(None, status="source_unavailable")
                return
            try:
                async with asyncio.timeout(FORECAST_REQUEST_TIMEOUT_SECONDS):
                    response = await self._hass.services.async_call(
                        "weather",
                        "get_forecasts",
                        {"type": "daily"},
                        blocking=True,
                        target={"entity_id": self._weather_entity_id},
                        return_response=True,
                    )
                if not isinstance(response, dict):
                    raise TypeError("weather forecast service returned no response mapping")
                entity_response = response.get(self._weather_entity_id)
                forecasts = (
                    entity_response.get("forecast") if isinstance(entity_response, dict) else None
                )
                payload = build_forecast_payload(
                    forecasts,
                    temperature_unit=source.attributes.get("temperature_unit"),
                    time_zone=self._hass.config.time_zone,
                    city_name=display_location_name(source.name) or source.name,
                    country=getattr(self._hass.config, "country", None),
                    current_temperature_c=self._runtime.outdoor_temperature_c,
                    current_condition=source.state,
                    current_humidity=validated_humidity(source.attributes.get("humidity")),
                )
            except TimeoutError:
                _LOGGER.warning("Timed out refreshing the configured daily weather forecast")
                self._runtime.async_set_forecast(None, status="source_timeout")
                return
            except Exception:  # Source integrations can fail independently of Nuve.
                _LOGGER.warning("Unable to refresh the configured daily weather forecast")
                self._runtime.async_set_forecast(None, status="source_error")
                return
            self._runtime.async_set_forecast(
                payload,
                status="ok" if payload is not None else "invalid_or_empty",
            )

    async def async_close(self) -> None:
        """Cancel the in-flight refresh and release source subscriptions."""

        if self._closed:
            return
        self._closed = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._task = None
