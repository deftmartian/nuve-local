"""Diagnostics support for Nuve Local."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .commissioning import deployment_profile, pairing_window_is_open
from .const import (
    CONF_AUTOMATIC_BASELINE_CAPTURE,
    CONF_BOOTSTRAP_FIRMWARE_VERSION,
    CONF_BOOTSTRAP_METADATA_CONFIRMED,
    CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED,
    CONF_CERTIFICATE,
    CONF_CONTROL_ENABLED,
    CONF_LISTEN_PORT,
    CONF_PRIVATE_KEY,
    CONF_TEMP_CORRECTION_VERSION,
    CONF_TRUSTED_PROXY_IP,
    CONF_WEATHER_ENTITY,
)
from .runtime import NuveRuntime


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return non-secret diagnostics for a config entry."""

    runtime: NuveRuntime = entry.runtime_data
    from .repairs import repair_conditions

    source_config = {**entry.data, **entry.options}
    config = {
        key: source_config.get(key)
        for key in (
            CONF_LISTEN_PORT,
            CONF_CONTROL_ENABLED,
            CONF_AUTOMATIC_BASELINE_CAPTURE,
            CONF_BOOTSTRAP_FIRMWARE_VERSION,
            CONF_BOOTSTRAP_METADATA_CONFIRMED,
            CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED,
            CONF_TEMP_CORRECTION_VERSION,
        )
    }
    state = asdict(runtime.state)
    state.pop("raw_fixed32", None)
    state.pop("raw_varints", None)
    for key in ("last_seen", "sample_time"):
        if state[key] is not None:
            state[key] = state[key].isoformat()
    return {
        "config": config,
        "deployment": {
            "profile": deployment_profile(source_config),
            "listener_running": bool(getattr(runtime.server, "is_running", False)),
            "listener_port": source_config.get(CONF_LISTEN_PORT),
            "trusted_proxy_configured": bool(source_config.get(CONF_TRUSTED_PROXY_IP)),
            "direct_certificate_configured": bool(
                source_config.get(CONF_CERTIFICATE) and source_config.get(CONF_PRIVATE_KEY)
            ),
            "pairing_window_open": pairing_window_is_open(source_config),
            "paired": runtime.paired,
            "authenticated_contact_seen": runtime.state.last_seen is not None,
            "settings_baseline_ready": runtime.has_settings_baseline,
            "auto_baseline_ready": runtime.has_auto_mode_baseline,
            "monitor_fresh": runtime.monitor_is_fresh,
            "control_activation_ready": runtime.can_enable_control,
        },
        "state": state,
        "protocol": {
            "trusted_proxy_configured": bool(source_config.get(CONF_TRUSTED_PROXY_IP)),
            "paired": runtime.paired,
            "settings_baseline": runtime.has_settings_baseline,
            "auto_mode_baseline": runtime.has_auto_mode_baseline,
            "private_baseline_storage_enabled": True,
            "persistence_healthy": runtime.persistence_healthy,
            "persistence_fault_latched": runtime.persistence_fault_latched,
            "persistence_recovered_from_previous": (runtime.persistence_recovered_from_previous),
            "canonical_metadata_ready": runtime.canonical_metadata_ready,
            "canonical_response_safe": runtime.canonical_response_safe,
            "canonical_response_block_reason": runtime.canonical_response_block_reason,
            "canonical_live_consistency_ready": runtime.canonical_live_consistency_ready,
            "configured_firmware_matches_baseline": (
                runtime.baseline_firmware_version == runtime.bootstrap_firmware_version
            ),
            "authoritative_control_monitor_seen": (runtime.authoritative_control_monitor_seen),
            "monitor_fresh": runtime.monitor_is_fresh,
            "outdoor_temperature_fresh": runtime.outdoor_is_fresh,
            "outdoor_source": runtime.outdoor_source,
            "weather_source_configured": bool(source_config.get(CONF_WEATHER_ENTITY)),
            "forecast_healthy": runtime.forecast_healthy,
            "forecast_status": runtime.forecast_status,
            "forecast_updated_at": (
                runtime.forecast_updated_at.isoformat() if runtime.forecast_updated_at else None
            ),
            "control_activation_ready": runtime.can_enable_control,
            "contractor_info_ready": runtime.contractor_info_ready,
            "control_ready": runtime.control_ready,
            "control_block_reason": runtime.control_block_reason,
            "bootstrap_status": runtime.bootstrap_status,
            "bootstrap_settings_served": runtime.bootstrap_settings_served,
            "bootstrap_auto_served": runtime.bootstrap_auto_served,
            "command_status": runtime.command_status,
            "uncertain_kind": runtime.uncertain_kind,
            "active_repair_conditions": sorted(repair_conditions(runtime)),
            "last_settings_poll": (
                runtime.last_settings_poll.isoformat() if runtime.last_settings_poll else None
            ),
            "last_settings_upload": (
                runtime.last_settings_upload.isoformat() if runtime.last_settings_upload else None
            ),
            "last_monitor_upload": (
                runtime.last_monitor_upload.isoformat() if runtime.last_monitor_upload else None
            ),
            "current_temperature_source": runtime.current_temperature_source,
            "current_temperature_observed_at": (
                runtime.current_temperature_observed_at.isoformat()
                if runtime.current_temperature_observed_at
                else None
            ),
        },
        "event_trace": runtime.sanitized_event_trace,
        "endpoint_counts": dict(runtime.endpoint_counts),
        "rejected_requests": runtime.rejected_requests,
    }
