"""Nuve Local integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import ConfigEntryNotReady

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
    PLATFORMS,
)
from .contractor import ContractorLogoError, load_validated_contractor_logo
from .data import NuveConfigEntry, NuveRuntimeData
from .repairs import NuveRepairManager, delete_entry_issues
from .runtime import NuveRuntime
from .server import NuveApiServer
from .sources import ForecastRefresh, register_outdoor_updates
from .storage import NuveBaselineStore

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _runtime_from_config(config: dict[str, Any], *, paired: bool) -> NuveRuntime:
    """Build the runtime from one merged config-entry projection."""

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


def _own_cleanup(
    entry: NuveConfigEntry,
    cleanups: list[Callable[[], Any]],
    callback: Callable[[], Any],
) -> None:
    """Track one owned resource for both success unload and failed setup."""

    released = False

    def release_once() -> Any:
        nonlocal released
        if released:
            return None
        released = True
        return callback()

    cleanups.append(release_once)
    entry.async_on_unload(release_once)


async def _async_run_setup_cleanups(cleanups: list[Callable[[], Any]]) -> None:
    """Release owned setup resources in reverse order."""

    while cleanups:
        callback = cleanups.pop()
        result = callback()
        if asyncio.iscoroutine(result):
            await result


async def async_setup_entry(hass: HomeAssistant, entry: NuveConfigEntry) -> bool:
    """Set up Nuve Local from a config entry."""

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
    entry.runtime_data = NuveRuntimeData(runtime=runtime, server=server)
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
            for unsub in register_outdoor_updates(
                hass,
                runtime,
                outdoor_entity_id=outdoor_entity_id,
                weather_entity_id=weather_entity_id,
            ):
                _own_cleanup(entry, cleanups, unsub)

        if weather_entity_id:
            forecast_refresh = ForecastRefresh(
                hass,
                runtime,
                weather_entity_id=weather_entity_id,
            )
            entry.runtime_data.forecast_refresh = forecast_refresh
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

    repair_manager = NuveRepairManager(hass, entry.entry_id, runtime)
    repair_manager.start()
    entry.async_on_unload(repair_manager.shutdown)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NuveConfigEntry) -> bool:
    """Unload a Nuve Local config entry."""

    data: NuveRuntimeData | None = getattr(entry, "runtime_data", None)
    if data is None:
        return True
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    # The forecast refresh is closed by its async_on_unload cleanup.
    await data.server.async_stop()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: NuveConfigEntry) -> None:
    """Remove persistent Repairs issues owned by a deleted config entry."""

    delete_entry_issues(hass, entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: NuveConfigEntry) -> bool:
    """Keep existing configuration without guessing a proxy's external port."""

    if entry.version > 3:
        return False
    if entry.version == 3:
        return True
    # The internal listener port does not establish the external HTTPS port.
    # Telemetry and control remain available; optional logos wait for the user
    # to supply the exact port in network options.
    hass.config_entries.async_update_entry(entry, version=3)
    return True
