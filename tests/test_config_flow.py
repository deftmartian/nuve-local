"""Tests for the staged deployment and fail-closed control flows."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
import voluptuous as vol
import voluptuous_serialize
from homeassistant.helpers import config_validation as cv

from custom_components.nuve_local.commissioning import (
    deployment_profile,
    new_pairing_deadline,
    pairing_window_is_open,
)
from custom_components.nuve_local.config_flow import (
    NuveLocalConfigFlow,
    _commissioning_schema,
    _contractor_schema,
    _control_is_being_enabled,
    _control_ready,
    _network_schema,
    _normalize_api_hostname,
    _normalize_temp_correction_version,
    _prepare_network_config,
    _sources_schema,
    _validate_bootstrap_config,
    _validate_contractor_config,
    _validate_network_config,
    _validate_profile_network,
)
from custom_components.nuve_local.const import (
    CONF_API_HOSTNAME,
    CONF_AUTOMATIC_BASELINE_CAPTURE,
    CONF_BOOTSTRAP_FIRMWARE_VERSION,
    CONF_BOOTSTRAP_METADATA_CONFIRMED,
    CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED,
    CONF_BOOTSTRAP_TECHNICIAN_URL,
    CONF_CERTIFICATE,
    CONF_CONTRACTOR_BRAND,
    CONF_CONTRACTOR_LOGO_PATH,
    CONF_CONTRACTOR_PHONE,
    CONF_CONTRACTOR_URL,
    CONF_DEPLOYMENT_PROFILE,
    CONF_LISTEN_HOST,
    CONF_LISTEN_PORT,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PAIRING_DEADLINE,
    CONF_PRIVATE_KEY,
    CONF_SERIAL,
    CONF_TEMP_CORRECTION_VERSION,
    CONF_THERMOSTAT_IP,
    CONF_TRUSTED_PROXY_IP,
    CONF_WEATHER_ENTITY,
    DEPLOYMENT_PROFILE_DIRECT_TLS,
    DEPLOYMENT_PROFILE_REVERSE_PROXY,
)
from custom_components.nuve_local.models import NuveMode, NuveState
from custom_components.nuve_local.runtime import NuveRuntime
from tests.helpers import attach_memory_persistence


@dataclass
class FakeEntry:
    runtime_data: NuveRuntime | None


def _valid_commissioning(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        CONF_BOOTSTRAP_FIRMWARE_VERSION: "1.5.8",
        CONF_BOOTSTRAP_TECHNICIAN_URL: "",
        CONF_BOOTSTRAP_METADATA_CONFIRMED: True,
        CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED: True,
        CONF_TEMP_CORRECTION_VERSION: 2,
        CONF_AUTOMATIC_BASELINE_CAPTURE: True,
    }
    values.update(changes)
    return values


def test_user_flow_routes_to_small_profile_specific_forms() -> None:
    assert NuveLocalConfigFlow.VERSION == 2

    async def scenario() -> None:
        reverse = NuveLocalConfigFlow()
        reverse_result = await reverse.async_step_user(
            {CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_REVERSE_PROXY}
        )
        assert reverse_result["type"] == "form"
        assert reverse_result["step_id"] == DEPLOYMENT_PROFILE_REVERSE_PROXY
        reverse_fields = {marker.schema for marker in reverse_result["data_schema"].schema}
        assert reverse_fields == {
            "thermostat_ip",
            "serial",
            "api_hostname",
            "listen_host",
            "trusted_proxy_ip",
        }
        reverse_api_hostname = next(
            marker
            for marker in reverse_result["data_schema"].schema
            if marker.schema == CONF_API_HOSTNAME
        )
        assert reverse_api_hostname.default() == ""

        direct = NuveLocalConfigFlow()
        direct_result = await direct.async_step_user(
            {CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_DIRECT_TLS}
        )
        assert direct_result["step_id"] == DEPLOYMENT_PROFILE_DIRECT_TLS
        direct_fields = {marker.schema for marker in direct_result["data_schema"].schema}
        assert direct_fields == {
            "thermostat_ip",
            "serial",
            "api_hostname",
            "listen_host",
            "certificate",
            "private_key",
        }

    asyncio.run(scenario())


def test_reverse_proxy_step_returns_independent_network_errors() -> None:
    async def scenario() -> None:
        flow = NuveLocalConfigFlow()
        result = await flow.async_step_reverse_proxy(
            {
                "thermostat_ip": "not-an-ip",
                "serial": "   ",
                "api_hostname": "https://invalid.example/path",
                "listen_host": "also-not-an-ip",
                "trusted_proxy_ip": "proxy.invalid",
            }
        )

        assert result["type"] == "form"
        assert result["step_id"] == DEPLOYMENT_PROFILE_REVERSE_PROXY
        assert result["errors"] == {
            "thermostat_ip": "invalid_ip",
            "listen_host": "invalid_ip",
            "trusted_proxy_ip": "invalid_ip",
            "serial": "invalid_serial",
            "api_hostname": "invalid_api_hostname",
        }

    asyncio.run(scenario())


def test_profile_network_preparation_is_explicit_and_normalized() -> None:
    reverse, errors = _prepare_network_config(
        DEPLOYMENT_PROFILE_REVERSE_PROXY,
        {
            "thermostat_ip": "192.0.2.23",
            "serial": " 00-000-000000 ",
            "api_hostname": "NUVE-Local.Example.Net.",
            "listen_host": "192.0.2.10",
            "trusted_proxy_ip": "192.0.2.1",
        },
    )
    assert not errors
    assert reverse[CONF_SERIAL] == "00-000-000000"
    assert reverse[CONF_API_HOSTNAME] == "nuve-local.example.net"
    assert reverse[CONF_LISTEN_PORT] == 18443
    assert reverse[CONF_DEPLOYMENT_PROFILE] == DEPLOYMENT_PROFILE_REVERSE_PROXY
    assert reverse[CONF_CERTIFICATE] == ""
    assert reverse[CONF_PRIVATE_KEY] == ""

    direct, errors = _prepare_network_config(
        DEPLOYMENT_PROFILE_DIRECT_TLS,
        {
            "thermostat_ip": "192.0.2.23",
            "serial": "00-000-000000",
            "api_hostname": "nuve-local.example.net",
            "listen_host": "192.0.2.10",
            "certificate": "/ssl/fullchain.pem",
            "private_key": "/ssl/privkey.pem",
        },
    )
    assert not errors
    assert direct[CONF_TRUSTED_PROXY_IP] == ""
    assert direct[CONF_DEPLOYMENT_PROFILE] == DEPLOYMENT_PROFILE_DIRECT_TLS


def test_profile_validation_rejects_ambiguous_tls_topologies() -> None:
    assert _validate_profile_network(
        {CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_REVERSE_PROXY}
    ) == {CONF_TRUSTED_PROXY_IP: "trusted_proxy_required"}
    assert _validate_profile_network(
        {
            CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_DIRECT_TLS,
            CONF_TRUSTED_PROXY_IP: "192.0.2.1",
        }
    ) == {CONF_TRUSTED_PROXY_IP: "direct_profile_disallows_proxy"}
    assert _validate_profile_network({CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_DIRECT_TLS}) == {
        CONF_CERTIFICATE: "direct_profile_requires_certificate"
    }


def test_control_readiness_is_checked_only_when_enabling() -> None:
    assert _control_is_being_enabled({"control_enabled": False}, {"control_enabled": True})
    assert not _control_is_being_enabled({"control_enabled": True}, {"control_enabled": True})
    assert not _control_is_being_enabled({"control_enabled": True}, {"control_enabled": False})


def test_control_option_requires_all_live_safety_evidence() -> None:
    runtime = NuveRuntime(
        serial="00-000-000000",
        paired=True,
        bootstrap_firmware_version="1.5.7.4",
        bootstrap_technician_url="https://contractor.invalid/preserved",
        bootstrap_metadata_confirmed=True,
        bootstrap_no_update_confirmed=True,
        temp_correction_version=1,
    )
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

    assert _control_ready(FakeEntry(runtime)) is True  # type: ignore[arg-type]
    assert _control_ready(FakeEntry(None)) is False  # type: ignore[arg-type]


def test_control_option_rejects_missing_auto_baseline_and_special_modes() -> None:
    runtime = NuveRuntime(
        serial="00-000-000000",
        paired=True,
        bootstrap_firmware_version="1.5.7.4",
        bootstrap_technician_url="https://contractor.invalid/preserved",
        bootstrap_metadata_confirmed=True,
        bootstrap_no_update_confirmed=True,
        temp_correction_version=1,
    )
    attach_memory_persistence(runtime)
    now = datetime.now(UTC)
    runtime.settings_snapshot = {
        "temp": 21.5,
        "mode_id": 2,
        "firmware": {"firmware-version": "1.5.7.4"},
    }
    runtime.settings_revision = "2026-08-09 05:00:00"
    runtime.last_settings_poll = now
    runtime.last_monitor_upload = now
    runtime.state = NuveState(
        available=True,
        sample_time=now,
        current_temperature=21.0,
        target_temperature=21.5,
        mode=NuveMode.HEAT,
        records_received=1,
    )
    assert _control_ready(FakeEntry(runtime)) is False  # type: ignore[arg-type]

    runtime.auto_mode_snapshot = {"auto_temp_low": 19.0, "auto_temp_high": 23.0}
    runtime.auto_mode_revision = "2026-08-09 05:00:01"
    for mode in (NuveMode.NONE, NuveMode.VACATION, NuveMode.EMERGENCY_HEAT):
        runtime.state = NuveState(
            available=True,
            sample_time=now,
            current_temperature=21.0,
            target_temperature=21.5,
            auto_temperature_low=19.0,
            auto_temperature_high=23.0,
            mode=mode,
            records_received=1,
        )
        assert _control_ready(FakeEntry(runtime)) is False  # type: ignore[arg-type]


def test_commissioning_requires_exact_confirmed_metadata() -> None:
    assert not _validate_bootstrap_config(_valid_commissioning())

    unconfirmed = _valid_commissioning(
        **{
            CONF_BOOTSTRAP_METADATA_CONFIRMED: False,
            CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED: False,
        }
    )
    assert _validate_bootstrap_config(unconfirmed) == {
        CONF_BOOTSTRAP_METADATA_CONFIRMED: "commissioning_confirmation_required",
        CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED: "commissioning_confirmation_required",
    }

    invalid_correction = _valid_commissioning(**{CONF_TEMP_CORRECTION_VERSION: 3})
    assert _validate_bootstrap_config(invalid_correction)[CONF_TEMP_CORRECTION_VERSION] == (
        "invalid_temp_correction_version"
    )


def test_commissioning_schema_is_http_flow_serializable() -> None:
    schema = _commissioning_schema({CONF_TEMP_CORRECTION_VERSION: 1})
    serialized = voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer)
    marker = next(field for field in serialized if field["name"] == CONF_TEMP_CORRECTION_VERSION)
    assert marker["default"] == "1"
    assert marker["selector"]["select"]["options"] == ["1", "2", "3"]

    user_input = {CONF_TEMP_CORRECTION_VERSION: "2"}
    assert not _normalize_temp_correction_version(user_input)
    assert user_input[CONF_TEMP_CORRECTION_VERSION] == 2


def test_source_selectors_are_optional_and_preserve_suggestions() -> None:
    schema = _sources_schema(
        {
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature",
            CONF_WEATHER_ENTITY: "weather.local",
        }
    )
    assert schema({}) == {}
    outdoor = next(
        marker for marker in schema.schema if marker.schema == CONF_OUTDOOR_TEMPERATURE_ENTITY
    )
    weather = next(marker for marker in schema.schema if marker.schema == CONF_WEATHER_ENTITY)
    assert outdoor.description == {"suggested_value": "sensor.outdoor_temperature"}
    assert weather.description == {"suggested_value": "weather.local"}


def test_advanced_network_schema_contains_raw_fields_only() -> None:
    schema = _network_schema(
        {
            CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_REVERSE_PROXY,
            CONF_THERMOSTAT_IP: "192.0.2.23",
            CONF_TRUSTED_PROXY_IP: "192.0.2.1",
            CONF_LISTEN_HOST: "192.0.2.10",
            CONF_LISTEN_PORT: 18443,
            CONF_API_HOSTNAME: "nuve-local.example.net",
        }
    )
    assert {marker.schema for marker in schema.schema} == {
        CONF_DEPLOYMENT_PROFILE,
        CONF_THERMOSTAT_IP,
        CONF_TRUSTED_PROXY_IP,
        CONF_LISTEN_HOST,
        CONF_LISTEN_PORT,
        CONF_API_HOSTNAME,
        CONF_CERTIFICATE,
        CONF_PRIVATE_KEY,
    }


def test_network_and_contractor_validation_remain_strict() -> None:
    assert _validate_network_config(
        {
            CONF_THERMOSTAT_IP: "bad",
            CONF_LISTEN_HOST: "also-bad",
            CONF_API_HOSTNAME: "https://invalid/path",
        }
    ) == {
        CONF_THERMOSTAT_IP: "invalid_ip",
        CONF_LISTEN_HOST: "invalid_ip",
        CONF_API_HOSTNAME: "invalid_api_hostname",
    }
    assert _validate_network_config(
        {
            CONF_THERMOSTAT_IP: "192.0.2.23",
            CONF_LISTEN_HOST: "192.0.2.10",
        }
    ) == {CONF_API_HOSTNAME: "invalid_api_hostname"}
    assert not _validate_network_config(
        {
            CONF_THERMOSTAT_IP: "192.0.2.23",
            CONF_LISTEN_HOST: "192.0.2.10",
            CONF_API_HOSTNAME: "devapi.nuvehvac.com",
        }
    )

    complete = {
        CONF_CONTRACTOR_BRAND: "Example HVAC",
        CONF_CONTRACTOR_PHONE: "555-0100",
        CONF_CONTRACTOR_LOGO_PATH: "/config/example.png",
        CONF_CONTRACTOR_URL: "https://example.com",
    }
    assert not _validate_contractor_config(complete)
    assert _validate_contractor_config({CONF_CONTRACTOR_BRAND: "Example HVAC"}) == {
        CONF_CONTRACTOR_BRAND: "contractor_fields_incomplete"
    }
    with pytest.raises(vol.Invalid):
        _commissioning_schema()({**_valid_commissioning(), CONF_TEMP_CORRECTION_VERSION: True})


@pytest.mark.parametrize(
    "value",
    [
        "http://example.com",
        "https://user@example.com",
        "https://example.com:not-a-port",
        "https://example.com/has a space",
        "deftmartian.dev",
    ],
)
def test_technician_access_qr_url_requires_a_safe_absolute_https_url(value: str) -> None:
    assert _validate_contractor_config({CONF_CONTRACTOR_URL: value})[CONF_CONTRACTOR_URL] == (
        "invalid_contractor_url"
    )


def test_pairing_window_is_explicit_bounded_and_profile_classifies_cleanly() -> None:
    now = datetime.now(UTC)
    deadline = new_pairing_deadline(now=now)
    config = {CONF_PAIRING_DEADLINE: deadline}
    assert pairing_window_is_open(config, now=now)
    assert not pairing_window_is_open({}, now=now)
    assert not pairing_window_is_open({CONF_PAIRING_DEADLINE: "invalid"}, now=now)
    assert (
        deployment_profile({CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_DIRECT_TLS})
        == DEPLOYMENT_PROFILE_DIRECT_TLS
    )


def test_translations_match_the_staged_flow() -> None:
    integration_dir = Path(__file__).parents[1] / "custom_components" / "nuve_local"
    for relative in ("strings.json", "translations/en.json"):
        content = json.loads((integration_dir / relative).read_text())
        assert set(content["config"]["step"]) == {
            "user",
            "reverse_proxy",
            "direct_tls",
            "commissioning",
        }
        assert set(content["options"]["step"]) == {
            "init",
            "status",
            "control",
            "pairing",
            "sources",
            "contractor",
            "commissioning",
            "network",
        }
        assert set(content["options"]["step"]["init"]["menu_options"]) == {
            "status",
            "control",
            "pairing",
            "sources",
            "contractor",
            "commissioning",
            "network",
        }
        assert "menu" not in content["options"]
        assert "allow_token_learning" not in repr(content["config"])
        assert "allow_token_learning" not in repr(content["options"])


def test_api_hostname_normalization_is_stable() -> None:
    assert _normalize_api_hostname("NUVE-Local.Example.Net.") == "nuve-local.example.net"


def test_contractor_schema_keeps_all_optional_fields_visible() -> None:
    schema = _contractor_schema({})
    assert {marker.schema for marker in schema.schema} == {
        CONF_CONTRACTOR_BRAND,
        CONF_CONTRACTOR_PHONE,
        CONF_CONTRACTOR_URL,
        CONF_CONTRACTOR_LOGO_PATH,
    }
