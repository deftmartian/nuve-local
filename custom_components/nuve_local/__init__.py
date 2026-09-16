"""Nuve Local integration."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .const import (
    CONF_AUTOMATIC_BASELINE_CAPTURE,
    CONF_BOOTSTRAP_FIRMWARE_VERSION,
    CONF_BOOTSTRAP_METADATA_CONFIRMED,
    CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED,
    CONF_BOOTSTRAP_TECHNICIAN_URL,
    CONF_CONTRACTOR_BRAND,
    CONF_CONTRACTOR_LOGO_PATH,
    CONF_CONTRACTOR_PHONE,
    CONF_CONTRACTOR_URL,
    CONF_CONTROL_ENABLED,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_SERIAL,
    CONF_TEMP_CORRECTION_VERSION,
    CONF_TOKEN_SHA256,
    CONF_WEATHER_ENTITY,
    DEFAULT_CONTROL_ENABLED,
    FORECAST_REFRESH_MINUTES,
    FORECAST_REQUEST_TIMEOUT_SECONDS,
    PLATFORMS,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .runtime import NuveRuntime

_LOGGER = logging.getLogger(__name__)


def _validated_outdoor_temperature_c(value: Any, unit: Any) -> float:
    """Convert one explicitly unit-tagged outdoor observation to safe Celsius."""

    from homeassistant.const import UnitOfTemperature
    from homeassistant.util.unit_conversion import TemperatureConverter

    if not isinstance(unit, str) or not unit:
        raise ValueError("outdoor temperature is missing its unit")
    value_c = TemperatureConverter.convert(float(value), unit, UnitOfTemperature.CELSIUS)
    if not math.isfinite(value_c) or not -90 <= value_c <= 65:
        raise ValueError("outdoor temperature is outside the validated range")
    return value_c


def _validated_humidity(value: Any) -> float | None:
    """Return one finite relative-humidity percentage when present."""

    try:
        humidity = float(value) if value is not None else None
    except TypeError, ValueError:
        return None
    if humidity is None or not math.isfinite(humidity) or not 0 <= humidity <= 100:
        return None
    return humidity


def _runtime_from_config(config: dict[str, Any], *, paired: bool) -> NuveRuntime:
    """Build the runtime from one merged config-entry projection."""

    from .runtime import NuveRuntime

    return NuveRuntime(
        serial=config[CONF_SERIAL],
        control_enabled=config.get(CONF_CONTROL_ENABLED, DEFAULT_CONTROL_ENABLED),
        paired=paired,
        automatic_baseline_capture=config.get(
            CONF_AUTOMATIC_BASELINE_CAPTURE,
            False,
        ),
        bootstrap_firmware_version=config.get(CONF_BOOTSTRAP_FIRMWARE_VERSION),
        bootstrap_technician_url=config.get(CONF_BOOTSTRAP_TECHNICIAN_URL),
        contractor_url=config.get(CONF_CONTRACTOR_URL),
        bootstrap_metadata_confirmed=config.get(CONF_BOOTSTRAP_METADATA_CONFIRMED, False),
        bootstrap_no_update_confirmed=config.get(CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED, False),
        temp_correction_version=config.get(CONF_TEMP_CORRECTION_VERSION),
    )


async def _async_load_contractor_logo(
    hass: HomeAssistant,
    config: dict[str, Any],
    runtime: NuveRuntime,
) -> bytes | None:
    """Load an all-or-none configured contractor logo without blocking HA."""

    from .contractor import ContractorLogoError, load_validated_contractor_logo

    contractor_values = (
        config.get(CONF_CONTRACTOR_BRAND),
        config.get(CONF_CONTRACTOR_PHONE),
        config.get(CONF_CONTRACTOR_LOGO_PATH),
    )
    if not all(isinstance(value, str) and value for value in contractor_values):
        return None
    try:
        logo = await hass.async_add_executor_job(
            load_validated_contractor_logo,
            config[CONF_CONTRACTOR_LOGO_PATH],
        )
    except ContractorLogoError, OSError:
        _LOGGER.warning("The configured contractor logo is unavailable or invalid")
        return None
    runtime.contractor_info_ready = True
    return logo


def _register_outdoor_updates(
    hass: HomeAssistant,
    runtime: NuveRuntime,
    *,
    outdoor_entity_id: str | None,
    weather_entity_id: str | None,
) -> list[Callable[[], None]]:
    """Project configured HA states into the thermostat's outdoor observation."""

    from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
    from homeassistant.core import callback
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers.event import (
        async_track_state_change_event,
        async_track_state_report_event,
    )

    from .weather import condition_weather, display_location_name

    @callback
    def update_outdoor_temperature(*_: Any) -> None:
        weather_state = hass.states.get(weather_entity_id) if weather_entity_id else None
        weather_humidity = (
            _validated_humidity(weather_state.attributes.get("humidity"))
            if weather_state is not None
            else None
        )
        weather_item = (
            condition_weather(weather_state.state)
            if weather_state is not None and weather_state.state not in {"unknown", "unavailable"}
            else None
        )
        weather_location = (
            display_location_name(weather_state.name) if weather_state is not None else None
        )
        if outdoor_entity_id:
            state = hass.states.get(outdoor_entity_id)
            if state is not None and state.state not in {"unknown", "unavailable"}:
                try:
                    value_c = _validated_outdoor_temperature_c(
                        state.state,
                        state.attributes.get(ATTR_UNIT_OF_MEASUREMENT),
                    )
                except HomeAssistantError, TypeError, ValueError:
                    pass
                else:
                    sensor_humidity = _validated_humidity(state.attributes.get("humidity"))
                    runtime.async_set_outdoor_temperature(
                        value_c,
                        weather_location or state.name,
                        humidity_percent=(
                            sensor_humidity if sensor_humidity is not None else weather_humidity
                        ),
                        weather=weather_item,
                        observed_at=getattr(state, "last_reported", datetime.now(UTC)),
                        source="override_sensor",
                    )
                    return
        if weather_entity_id:
            state = weather_state
            if state is not None and state.state not in {"unknown", "unavailable"}:
                try:
                    value_c = _validated_outdoor_temperature_c(
                        state.attributes.get("temperature"),
                        state.attributes.get("temperature_unit"),
                    )
                except HomeAssistantError, TypeError, ValueError:
                    pass
                else:
                    runtime.async_set_outdoor_temperature(
                        value_c,
                        weather_location or state.name,
                        humidity_percent=_validated_humidity(state.attributes.get("humidity")),
                        weather=weather_item,
                        observed_at=getattr(state, "last_reported", datetime.now(UTC)),
                        source="weather_entity",
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


class _ForecastRefresh:
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

        from homeassistant.core import callback
        from homeassistant.helpers.event import (
            async_track_state_change_event,
            async_track_time_interval,
        )

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

        from .weather import build_forecast_payload, display_location_name

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
                    current_humidity=_validated_humidity(source.attributes.get("humidity")),
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


def _own_cleanup(
    entry: ConfigEntry,
    cleanups: list[Callable[[], Any]],
    callback: Callable[[], Any],
) -> None:
    """Track one owned resource for both success unload and failed setup."""

    cleanups.append(callback)
    entry.async_on_unload(callback)


async def _async_run_setup_cleanups(cleanups: list[Callable[[], Any]]) -> None:
    """Release owned setup resources in reverse order."""

    while cleanups:
        callback = cleanups.pop()
        result = callback()
        if asyncio.iscoroutine(result):
            await result


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nuve Local from a config entry."""

    from homeassistant.const import EVENT_HOMEASSISTANT_STOP
    from homeassistant.exceptions import ConfigEntryNotReady

    from .server import NuveApiServer
    from .storage import NuveBaselineStore

    config: dict[str, Any] = {**entry.data, **entry.options}
    runtime = _runtime_from_config(config, paired=CONF_TOKEN_SHA256 in entry.data)
    baseline_store = NuveBaselineStore(hass, entry.entry_id, serial=config[CONF_SERIAL])
    runtime.async_restore_persistent_baselines(
        await baseline_store.async_load(serial=config[CONF_SERIAL])
    )
    contractor_logo_bytes = await _async_load_contractor_logo(hass, config, runtime)
    server = NuveApiServer(
        hass=hass,
        entry=entry,
        runtime=runtime,
        config=config,
        baseline_store=baseline_store,
        contractor_logo_bytes=contractor_logo_bytes,
    )
    runtime.server = server
    runtime.async_set_persistence_listener(server.async_save_candidate)
    entry.runtime_data = runtime
    cleanups: list[Callable[[], Any]] = []

    async def async_stop_listener(_: Any) -> None:
        await server.async_stop()

    try:
        try:
            await server.async_start()
        except OSError as err:
            raise ConfigEntryNotReady("Nuve Local listener could not start") from err

        outdoor_entity_id = config.get(CONF_OUTDOOR_TEMPERATURE_ENTITY)
        weather_entity_id = config.get(CONF_WEATHER_ENTITY)
        if outdoor_entity_id or weather_entity_id:
            for unsub in _register_outdoor_updates(
                hass,
                runtime,
                outdoor_entity_id=outdoor_entity_id,
                weather_entity_id=weather_entity_id,
            ):
                _own_cleanup(entry, cleanups, unsub)

        if weather_entity_id:
            forecast_refresh = _ForecastRefresh(
                hass,
                runtime,
                weather_entity_id=weather_entity_id,
            )
            runtime.forecast_refresh = forecast_refresh
            _own_cleanup(entry, cleanups, forecast_refresh.async_close)
            await forecast_refresh.async_refresh()
            forecast_refresh.listen()

        _own_cleanup(
            entry,
            cleanups,
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop_listener),
        )
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await _async_run_setup_cleanups(cleanups)
        await server.async_stop()
        raise

    from .repairs import NuveRepairManager

    repair_manager = NuveRepairManager(hass, entry.entry_id, runtime)
    repair_manager.start()
    entry.async_on_unload(repair_manager.shutdown)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Nuve Local config entry."""

    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return True
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    forecast_refresh = getattr(runtime, "forecast_refresh", None)
    if forecast_refresh is not None:
        await forecast_refresh.async_close()
        runtime.forecast_refresh = None
    server = getattr(runtime, "server", None)
    if server is not None:
        await server.async_stop()
    else:
        await runtime.async_shutdown()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove persistent Repairs issues owned by a deleted config entry."""

    from .repairs import delete_entry_issues

    delete_entry_issues(hass, entry.entry_id)
