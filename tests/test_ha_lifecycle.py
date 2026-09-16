"""Lifecycle tests against real Home Assistant ConfigEntry objects."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntries, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.nuve_local import (
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.nuve_local.const import (
    CONF_API_HOSTNAME,
    CONF_DEPLOYMENT_PROFILE,
    CONF_LISTEN_HOST,
    CONF_LISTEN_PORT,
    CONF_SERIAL,
    CONF_THERMOSTAT_HTTPS_PORT,
    CONF_THERMOSTAT_IP,
    CONF_TRUSTED_PROXY_IP,
    DEPLOYMENT_PROFILE_DIRECT_TLS,
    DEPLOYMENT_PROFILE_REVERSE_PROXY,
    DOMAIN,
)
from custom_components.nuve_local.diagnostics import async_get_config_entry_diagnostics


def _config_entry(*, version: int = 3, **overrides: Any) -> ConfigEntry:
    data: dict[str, Any] = {
        CONF_SERIAL: "00-000-000000",
        CONF_THERMOSTAT_IP: "192.0.2.23",
        CONF_API_HOSTNAME: "nuve-local.example.net",
        CONF_LISTEN_HOST: "127.0.0.1",
        CONF_LISTEN_PORT: 18443,
        CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_REVERSE_PROXY,
        CONF_TRUSTED_PROXY_IP: "192.0.2.1",
    }
    data.update(overrides)
    kwargs: dict[str, Any] = {
        "data": data,
        "domain": DOMAIN,
        "minor_version": 1,
        "options": {},
        "source": SOURCE_USER,
        "title": "Nuve Samo",
        "unique_id": data[CONF_SERIAL],
        "version": version,
    }
    signature = inspect.signature(ConfigEntry.__init__)
    if "discovery_keys" in signature.parameters:
        kwargs["discovery_keys"] = MappingProxyType({})
    if "subentries_data" in signature.parameters:
        kwargs["subentries_data"] = None
    return ConfigEntry(**kwargs)


async def _hass(tmp_path: Any) -> HomeAssistant:
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = ConfigEntries(hass, {})

    async def async_forward_entry_setups(entry: ConfigEntry, platforms: list[str]) -> None:
        return None

    async def async_unload_platforms(entry: ConfigEntry, platforms: list[str]) -> bool:
        return True

    hass.config_entries.async_forward_entry_setups = async_forward_entry_setups  # type: ignore[method-assign]
    hass.config_entries.async_unload_platforms = async_unload_platforms  # type: ignore[method-assign]
    return hass


@dataclass
class FakeStore:
    def __init__(self, hass: Any, entry_id: str, *, serial: str) -> None:
        pass

    async def async_load(self, *, serial: str) -> dict[str, Any]:
        return {}


class FakeServer:
    def __init__(self, **kwargs: Any) -> None:
        self._runtime = kwargs["runtime"]
        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started

    async def async_save_candidate(self, candidate: dict[str, Any]) -> None:
        return None

    async def async_start(self) -> None:
        self._started = True

    async def async_stop(self) -> None:
        self._started = False
        await self._runtime.async_shutdown()


def _patch_component(monkeypatch: Any, server_cls: type[FakeServer] = FakeServer) -> None:
    monkeypatch.setattr("custom_components.nuve_local.storage.NuveBaselineStore", FakeStore)
    monkeypatch.setattr("custom_components.nuve_local.server.NuveApiServer", server_cls)
    monkeypatch.setattr(
        "custom_components.nuve_local.repairs.NuveRepairManager",
        lambda *args, **kwargs: type(
            "FakeRepairs",
            (),
            {"start": lambda self: None, "shutdown": lambda self: None},
        )(),
    )


def test_real_config_entry_setup_unload_and_on_unload(tmp_path: Any, monkeypatch: Any) -> None:
    async def scenario() -> None:
        _patch_component(monkeypatch)
        hass = await _hass(tmp_path)
        entry = _config_entry()
        hass.config_entries._entries[entry.entry_id] = entry
        released: list[str] = []
        entry.async_on_unload(lambda: released.append("operator"))

        assert await async_setup_entry(hass, entry) is True
        assert entry.runtime_data.server.is_running is True
        assert await async_unload_entry(hass, entry) is True
        await entry._async_process_on_unload(hass)
        assert "operator" in released
        assert entry.runtime_data._stopped is True
        await hass.async_stop()

    asyncio.run(scenario())


def test_real_config_entry_bind_failure_is_retryable(tmp_path: Any, monkeypatch: Any) -> None:
    class FailingServer(FakeServer):
        async def async_start(self) -> None:
            raise OSError("Address already in use")

    async def scenario() -> None:
        _patch_component(monkeypatch, FailingServer)
        hass = await _hass(tmp_path)
        entry = _config_entry()
        with pytest.raises(ConfigEntryNotReady, match="listener could not start"):
            await async_setup_entry(hass, entry)
        assert entry.runtime_data._stopped is True
        await hass.async_stop()

    asyncio.run(scenario())


def test_real_config_entry_migration_preserves_proxy_port(tmp_path: Any) -> None:
    async def scenario() -> None:
        hass = await _hass(tmp_path)
        entry = _config_entry(version=2)
        hass.config_entries._entries[entry.entry_id] = entry
        assert await async_migrate_entry(hass, entry) is True
        assert entry.version == 3
        assert entry.data[CONF_THERMOSTAT_HTTPS_PORT] == 18443

        direct = _config_entry(
            version=2,
            **{
                CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_DIRECT_TLS,
                "certificate": "/ssl/fullchain.pem",
                "private_key": "/ssl/privkey.pem",
            },
        )
        hass.config_entries._entries[direct.entry_id] = direct
        assert await async_migrate_entry(hass, direct) is True
        assert direct.version == 3
        assert CONF_THERMOSTAT_HTTPS_PORT not in direct.data
        await hass.async_stop()

    asyncio.run(scenario())


def test_real_config_entry_diagnostics_without_runtime(tmp_path: Any) -> None:
    async def scenario() -> None:
        hass = await _hass(tmp_path)
        entry = _config_entry()
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["runtime_available"] is False
        assert diagnostics["deployment"]["listener_running"] is False
        await hass.async_stop()

    asyncio.run(scenario())
