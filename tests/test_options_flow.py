"""Drive every options-flow step through Home Assistant's real OptionsFlow base class."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.data_entry_flow import FlowResultType

from custom_components.nuve_local.config_flow import NuveLocalConfigFlow, NuveLocalOptionsFlow
from custom_components.nuve_local.const import (
    CONF_API_HOSTNAME,
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
    CONF_DEPLOYMENT_PROFILE,
    CONF_LISTEN_HOST,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PAIRING_DEADLINE,
    CONF_SERIAL,
    CONF_TEMP_CORRECTION_VERSION,
    CONF_THERMOSTAT_HTTPS_PORT,
    CONF_THERMOSTAT_IP,
    CONF_TOKEN_SHA256,
    CONF_TRUSTED_PROXY_IP,
    CONF_WEATHER_ENTITY,
    DEPLOYMENT_PROFILE_REVERSE_PROXY,
)
from custom_components.nuve_local.data import NuveRuntimeData
from custom_components.nuve_local.models import NuveMode, NuveState
from custom_components.nuve_local.runtime import NuveRuntime
from tests.helpers import attach_memory_persistence

SERIAL = "00-000-000000"
NETWORK = {
    CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_REVERSE_PROXY,
    CONF_THERMOSTAT_IP: "192.0.2.23",
    CONF_SERIAL: SERIAL,
    CONF_API_HOSTNAME: "nuve-local.example.net",
    CONF_LISTEN_HOST: "192.0.2.10",
    CONF_TRUSTED_PROXY_IP: "192.0.2.1",
    CONF_THERMOSTAT_HTTPS_PORT: 443,
}


@dataclass
class FakeServer:
    is_running: bool = True


@dataclass
class FakeEntry:
    data: dict[str, Any]
    options: dict[str, Any] = field(default_factory=dict)
    runtime_data: NuveRuntimeData | None = None
    entry_id: str = "test-entry"
    domain: str = "nuve_local"


@dataclass
class FakeConfigEntries:
    entry: FakeEntry

    def async_get_known_entry(self, entry_id: str) -> FakeEntry:
        assert entry_id == self.entry.entry_id
        return self.entry

    def async_update_entry(self, entry: FakeEntry, *, data: dict[str, Any]) -> None:
        entry.data = data


@dataclass
class FakeHass:
    config_entries: FakeConfigEntries


def _flow(entry: FakeEntry) -> NuveLocalOptionsFlow:
    flow = NuveLocalConfigFlow.async_get_options_flow(entry)  # type: ignore[arg-type]
    flow.hass = FakeHass(FakeConfigEntries(entry))  # type: ignore[assignment]
    flow.handler = entry.entry_id
    return flow


def _entry(*, runtime: NuveRuntime | None = None, **data: Any) -> FakeEntry:
    entry = FakeEntry(data={**NETWORK, CONF_CONTROL_ENABLED: False, **data})
    if runtime is not None:
        entry.runtime_data = NuveRuntimeData(runtime=runtime, server=FakeServer())  # type: ignore[arg-type]
    return entry


def _runtime(*, ready: bool) -> NuveRuntime:
    runtime = NuveRuntime(
        serial=SERIAL,
        paired=True,
        bootstrap_firmware_version="1.5.7.4",
        bootstrap_technician_url="https://contractor.invalid/preserved",
        bootstrap_metadata_confirmed=True,
        bootstrap_no_update_confirmed=True,
        temp_correction_version=1,
    )
    if not ready:
        return runtime
    attach_memory_persistence(runtime)
    now = datetime.now(UTC)
    runtime.settings_snapshot = {
        "temp": 21.5,
        "mode_id": 2,
        "firmware": {"firmware-version": "1.5.7.4"},
    }
    runtime.settings_revision = "2026-08-09 05:00:00"
    runtime.auto_mode_snapshot = {"auto_temp_low": 19.0, "auto_temp_high": 23.0}
    runtime.auto_mode_revision = "2026-08-09 05:00:01"
    runtime.last_settings_poll = now
    runtime.last_monitor_upload = now
    runtime.state = NuveState(
        available=True,
        sample_time=now,
        current_temperature=21.0,
        target_temperature=21.5,
        auto_temperature_low=19.0,
        auto_temperature_high=23.0,
        mode=NuveMode.HEAT,
        records_received=1,
    )
    runtime.authoritative_control_monitor_seen = True
    return runtime


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_menu_lists_every_options_step() -> None:
    result = _run(_flow(_entry()).async_step_init())

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == [
        "status",
        "control",
        "pairing",
        "sources",
        "contractor",
        "commissioning",
        "network",
    ]


def test_status_without_a_runtime_reports_unavailable_and_returns_to_the_menu() -> None:
    open_window = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    flow = _flow(_entry(**{CONF_PAIRING_DEADLINE: open_window}))

    result = _run(flow.async_step_status())
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {
        "profile": DEPLOYMENT_PROFILE_REVERSE_PROXY,
        "listener": "unavailable",
        "pairing": "window open",
        "settings": "waiting",
        "auto": "waiting",
        "monitor": "waiting or stale",
        "control": "runtime_unavailable",
    }

    assert _run(flow.async_step_status({}))["type"] is FlowResultType.MENU


def test_status_with_a_ready_runtime_reports_live_state() -> None:
    entry = _entry(runtime=_runtime(ready=True))
    assert entry.runtime_data is not None
    entry.runtime_data.server.is_running = False

    placeholders = _run(_flow(entry).async_step_status())["description_placeholders"]

    assert placeholders["listener"] == "stopped"
    assert placeholders["pairing"] == "paired"
    assert placeholders["settings"] == "ready"
    assert placeholders["auto"] == "ready"
    assert placeholders["monitor"] == "fresh"
    assert placeholders["control"] == entry.runtime_data.runtime.control_block_reason


def test_enabling_control_requires_a_ready_runtime() -> None:
    blocked = _run(_flow(_entry()).async_step_control({CONF_CONTROL_ENABLED: True}))
    assert blocked["type"] is FlowResultType.FORM
    assert blocked["errors"] == {"base": "control_not_ready"}

    not_ready = _entry(runtime=_runtime(ready=False))
    blocked = _run(_flow(not_ready).async_step_control({CONF_CONTROL_ENABLED: True}))
    assert blocked["errors"] == {"base": "control_not_ready"}

    ready = _entry(runtime=_runtime(ready=True))
    ready.options = {CONF_WEATHER_ENTITY: "weather.home"}
    saved = _run(_flow(ready).async_step_control({CONF_CONTROL_ENABLED: True}))
    assert saved["type"] is FlowResultType.CREATE_ENTRY
    # Saving merges into, rather than replaces, the existing options.
    assert saved["data"] == {CONF_WEATHER_ENTITY: "weather.home", CONF_CONTROL_ENABLED: True}


def test_disabling_control_never_needs_readiness() -> None:
    entry = _entry(**{CONF_CONTROL_ENABLED: True})
    flow = _flow(entry)

    form = _run(flow.async_step_control())
    assert form["type"] is FlowResultType.FORM and form["errors"] == {}

    saved = _run(flow.async_step_control({CONF_CONTROL_ENABLED: False}))
    assert saved["type"] is FlowResultType.CREATE_ENTRY
    assert saved["data"] == {CONF_CONTROL_ENABLED: False}


def test_pairing_reopens_the_window_and_forgets_the_paired_token() -> None:
    entry = _entry(**{CONF_TOKEN_SHA256: "f" * 64, CONF_PAIRING_DEADLINE: "2026-01-01T00:00:00"})
    flow = _flow(entry)

    assert _run(flow.async_step_pairing())["step_id"] == "pairing"
    # Declining leaves the token in place.
    assert _run(flow.async_step_pairing({}))["type"] is FlowResultType.MENU
    assert entry.data[CONF_TOKEN_SHA256] == "f" * 64

    flow_field = next(str(key) for key in _run(flow.async_step_pairing())["data_schema"].schema)
    saved = _run(flow.async_step_pairing({flow_field: True}))
    assert saved["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_TOKEN_SHA256 not in entry.data
    assert CONF_PAIRING_DEADLINE not in entry.data
    deadline = datetime.fromisoformat(saved["data"][CONF_PAIRING_DEADLINE])
    assert datetime.now(UTC) < deadline <= datetime.now(UTC) + timedelta(minutes=5)


def test_sources_store_cleared_selectors_as_none() -> None:
    entry = _entry()
    entry.options = {
        CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor",
        CONF_WEATHER_ENTITY: "weather.home",
    }
    flow = _flow(entry)

    assert _run(flow.async_step_sources())["step_id"] == "sources"
    saved = _run(flow.async_step_sources({}))
    assert saved["data"] == {CONF_OUTDOOR_TEMPERATURE_ENTITY: None, CONF_WEATHER_ENTITY: None}


def test_contractor_details_are_all_or_nothing() -> None:
    flow = _flow(_entry())

    assert _run(flow.async_step_contractor())["step_id"] == "contractor"
    partial = _run(flow.async_step_contractor({CONF_CONTRACTOR_BRAND: "Example HVAC"}))
    assert partial["type"] is FlowResultType.FORM
    assert partial["errors"] == {CONF_CONTRACTOR_BRAND: "contractor_fields_incomplete"}

    complete = {
        CONF_CONTRACTOR_BRAND: "Example HVAC",
        CONF_CONTRACTOR_PHONE: "555-0100",
        CONF_CONTRACTOR_LOGO_PATH: "/config/example.png",
        CONF_CONTRACTOR_URL: "https://example.com",
    }
    saved = _run(flow.async_step_contractor(complete))
    assert saved["type"] is FlowResultType.CREATE_ENTRY
    assert saved["data"][CONF_CONTRACTOR_BRAND] == "Example HVAC"


def test_commissioning_options_validate_like_the_initial_flow() -> None:
    valid = {
        CONF_BOOTSTRAP_FIRMWARE_VERSION: "1.5.8",
        CONF_BOOTSTRAP_TECHNICIAN_URL: "",
        CONF_BOOTSTRAP_METADATA_CONFIRMED: True,
        CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED: True,
        CONF_TEMP_CORRECTION_VERSION: 2,
        CONF_AUTOMATIC_BASELINE_CAPTURE: True,
    }
    flow = _flow(_entry(**valid))

    assert _run(flow.async_step_commissioning())["step_id"] == "commissioning"
    rejected = _run(
        flow.async_step_commissioning({**valid, CONF_BOOTSTRAP_METADATA_CONFIRMED: False})
    )
    assert rejected["type"] is FlowResultType.FORM
    assert rejected["errors"]

    saved = _run(flow.async_step_commissioning(valid))
    assert saved["type"] is FlowResultType.CREATE_ENTRY
    assert saved["data"][CONF_BOOTSTRAP_FIRMWARE_VERSION] == "1.5.8"


def test_network_options_validate_and_never_change_the_serial() -> None:
    flow = _flow(_entry())

    assert _run(flow.async_step_network())["step_id"] == "network"
    rejected = _run(flow.async_step_network({**NETWORK, CONF_THERMOSTAT_IP: "bad"}))
    assert rejected["type"] is FlowResultType.FORM
    assert rejected["errors"] == {CONF_THERMOSTAT_IP: "invalid_ip"}

    saved = _run(flow.async_step_network({**NETWORK, CONF_SERIAL: "99-999-999999"}))
    assert saved["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_SERIAL not in saved["data"]
    assert saved["data"][CONF_THERMOSTAT_IP] == "192.0.2.23"
