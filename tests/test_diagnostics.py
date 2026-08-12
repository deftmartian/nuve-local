"""Tests that diagnostics cannot disclose household or protocol secrets."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from custom_components.nuve_local.diagnostics import async_get_config_entry_diagnostics
from custom_components.nuve_local.models import NuveMode, NuveState
from custom_components.nuve_local.runtime import NuveRuntime


@dataclass
class FakeEntry:
    runtime_data: NuveRuntime
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


def test_diagnostics_use_an_allowlist_and_drop_raw_protocol_maps() -> None:
    async def scenario() -> None:
        secrets = {
            "serial": "PRIVATE-SERIAL",
            "thermostat_ip": "192.0.2.23",
            "listen_host": "192.0.2.10",
            "token_sha256": "a" * 64,
            "certificate": "/private/certificate.pem",
            "private_key": "/private/key.pem",
            "outdoor_temperature_entity": "sensor.private_outdoor",
            "weather_entity": "weather.private_forecast",
            "contractor_brand": "Private Contractor",
            "contractor_phone": "555-0199",
            "contractor_logo_path": "/config/private-logo.png",
            "bootstrap_technician_url": "https://private.invalid/technician",
            "trusted_proxy_ip": "192.0.2.1",
        }
        runtime = NuveRuntime(
            serial=secrets["serial"],
            state=NuveState(
                available=True,
                last_seen=datetime.now(UTC),
                current_temperature=21.0,
                mode=NuveMode.HEAT,
                raw_fixed32={4: 21.0},
                raw_varints={15: 2},
            ),
        )
        entry = FakeEntry(
            runtime_data=runtime,
            data={
                **secrets,
                "listen_port": 18443,
                "automatic_baseline_capture": True,
                "control_enabled": False,
            },
        )

        diagnostics = await async_get_config_entry_diagnostics(None, entry)  # type: ignore[arg-type]
        rendered = repr(diagnostics)
        for value in secrets.values():
            assert value not in rendered
        assert "raw_fixed32" not in diagnostics["state"]
        assert "raw_varints" not in diagnostics["state"]
        assert diagnostics["config"] == {
            "listen_port": 18443,
            "control_enabled": False,
            "automatic_baseline_capture": True,
            "bootstrap_firmware_version": None,
            "bootstrap_metadata_confirmed": None,
            "bootstrap_no_update_confirmed": None,
            "temp_correction_version": None,
        }
        assert diagnostics["deployment"] == {
            "profile": "reverse_proxy",
            "listener_running": False,
            "listener_port": 18443,
            "trusted_proxy_configured": True,
            "direct_certificate_configured": True,
            "pairing_window_open": False,
            "paired": False,
            "authenticated_contact_seen": True,
            "settings_baseline_ready": False,
            "auto_baseline_ready": False,
            "monitor_fresh": False,
            "control_activation_ready": False,
        }
        assert diagnostics["protocol"]["persistence_healthy"] is True
        assert diagnostics["protocol"]["persistence_recovered_from_previous"] is False
        assert diagnostics["protocol"]["active_repair_conditions"] == []
        assert diagnostics["protocol"]["trusted_proxy_configured"] is True
        assert diagnostics["protocol"]["canonical_response_safe"] is False
        assert diagnostics["protocol"]["canonical_response_block_reason"] == "not_paired"
        assert diagnostics["protocol"]["canonical_live_consistency_ready"] is False
        assert diagnostics["protocol"]["authoritative_control_monitor_seen"] is False
        assert diagnostics["event_trace"] == [
            {
                "timestamp": runtime.sanitized_event_trace[0]["timestamp"],
                "event": "control_block_reason",
                "family": None,
                "result": "control_disabled",
                "duration_ms": None,
            }
        ]

    asyncio.run(scenario())
