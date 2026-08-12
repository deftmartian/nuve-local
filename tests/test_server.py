"""End-to-end request-gate tests for the local Nuve HTTP application."""

from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

import custom_components.nuve_local.runtime as runtime_module
from custom_components.nuve_local.auth import token_sha256
from custom_components.nuve_local.commissioning import new_pairing_deadline
from custom_components.nuve_local.const import (
    CONF_API_HOSTNAME,
    CONF_LISTEN_HOST,
    CONF_LISTEN_PORT,
    CONF_PAIRING_DEADLINE,
    CONF_SERIAL,
    CONF_THERMOSTAT_IP,
    CONF_TOKEN_SHA256,
    CONF_TRUSTED_PROXY_IP,
)
from custom_components.nuve_local.contractor import contractor_logo_signature
from custom_components.nuve_local.models import NuveMode, NuveState, NuveSystemType
from custom_components.nuve_local.runtime import ControlNotReadyError, NuveRuntime
from custom_components.nuve_local.server import NuveApiServer
from custom_components.nuve_local.storage import _build_storage_envelope, validate_stored_baselines
from tests.helpers import settings_upload

SERIAL = "00-000-000000"
TOKEN = "a" * 64
HEADERS = {"Host": "devapi.nuvehvac.com", "Authorization": f"Bearer {TOKEN}"}


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _bytes_field(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _fixed32_field(number: int, value: float) -> bytes:
    return _varint((number << 3) | 5) + struct.pack("<f", value)


def _varint_field(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _monitor_payload(*, timestamp: datetime | None = None, full: bool = False) -> bytes:
    timestamp = timestamp or datetime.now(UTC)
    timestamp = _bytes_field(1, _varint(1 << 3) + _varint(int(timestamp.timestamp())))
    record = timestamp + _fixed32_field(4, 21.0)
    if full:
        record += b"".join(
            (
                _fixed32_field(2, 21.5),
                _fixed32_field(3, 40.0),
                _fixed32_field(5, 42.5),
                _varint_field(13, 1),
                _varint_field(14, 2),
                _varint_field(15, 2),
                _fixed32_field(17, 19.0),
                _fixed32_field(18, 23.0),
                _varint_field(19, 9),
            )
        )
    return _bytes_field(1, record)


def _event_payload(*, target: bytes = b"home") -> bytes:
    timestamp = _bytes_field(1, _varint_field(1, int(datetime.now(UTC).timestamp())))
    event = timestamp + _varint_field(2, 1) + _bytes_field(3, target)
    return _bytes_field(1, event)


def _settings_upload() -> dict[str, object]:
    return settings_upload(SERIAL)


class FakeConfigEntries:
    """Only the config-entry mutation used for token pairing."""

    def async_update_entry(
        self,
        entry: FakeEntry,
        *,
        data: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> None:
        entry.data = data
        if options is not None:
            entry.options = options


@dataclass
class FakeConfig:
    time_zone: str = "America/Halifax"


@dataclass
class FakeHass:
    config_entries: FakeConfigEntries = field(default_factory=FakeConfigEntries)
    config: FakeConfig = field(default_factory=FakeConfig)


@dataclass
class FakeEntry:
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    entry_id: str = "test-entry"


@dataclass
class FakeBaselineStore:
    saved: list[dict[str, Any]] = field(default_factory=list)

    async def async_save(self, data: dict[str, Any]) -> None:
        self.saved.append(data)


@dataclass
class FailingBaselineStore:
    """A persistence boundary that never acknowledges a write."""

    async def async_save(self, data: dict[str, Any]) -> None:
        raise OSError("synthetic persistence failure")


@dataclass
class CancelledBaselineStore:
    """A persistence task that is cancelled internally before durable commit."""

    async def async_save(self, data: dict[str, Any]) -> None:
        raise asyncio.CancelledError


@dataclass
class FinalBoundaryFailingStore:
    """Persist write-ahead state but fail the post-send delivery boundary."""

    saved: list[dict[str, Any]] = field(default_factory=list)

    async def async_save(self, data: dict[str, Any]) -> None:
        uncertainty = data.get("uncertain_command")
        if isinstance(uncertainty, dict) and uncertainty.get("delivered_at") is not None:
            raise OSError("synthetic final-boundary persistence failure")
        self.saved.append(data)


@dataclass
class ValidatingBaselineStore:
    """Exercise the same envelope and validation boundary as the HA Store."""

    saved: list[dict[str, Any]] = field(default_factory=list)
    previous: dict[str, Any] | None = None

    async def async_save(self, data: dict[str, Any]) -> None:
        envelope = _build_storage_envelope(
            data,
            serial=SERIAL,
            previous=self.previous,
            saved_at=datetime.now(UTC),
        )
        validate_stored_baselines(envelope, serial=SERIAL, require_envelope=True)
        self.saved.append(data)
        self.previous = envelope


def _server(
    *,
    thermostat_ip: str = "127.0.0.1",
    trusted_proxy_ip: str | None = None,
    api_hostname: str = "devapi.nuvehvac.com",
    baseline_store: Any = None,
    contractor_logo_bytes: bytes | None = None,
    contractor_url: str | None = None,
) -> tuple[NuveApiServer, NuveRuntime, FakeEntry]:
    entry = FakeEntry()
    runtime = NuveRuntime(
        serial=SERIAL,
        bootstrap_firmware_version="1.5.7.4",
        bootstrap_technician_url="https://contractor.invalid/preserved",
        bootstrap_metadata_confirmed=True,
        bootstrap_no_update_confirmed=True,
        temp_correction_version=1,
        contractor_url=contractor_url,
    )
    if baseline_store is None:
        baseline_store = FakeBaselineStore()
    config = {
        CONF_API_HOSTNAME: api_hostname,
        CONF_THERMOSTAT_IP: thermostat_ip,
        CONF_SERIAL: SERIAL,
        CONF_LISTEN_HOST: "127.0.0.1",
        CONF_LISTEN_PORT: 18443,
        CONF_PAIRING_DEADLINE: new_pairing_deadline(),
    }
    if trusted_proxy_ip is not None:
        config[CONF_TRUSTED_PROXY_IP] = trusted_proxy_ip
    if contractor_logo_bytes is not None:
        config["contractor_brand"] = "Synthetic HVAC"
        config["contractor_phone"] = "555-0100"
        runtime.contractor_info_ready = True
    server = NuveApiServer(
        hass=FakeHass(),
        entry=entry,
        runtime=runtime,
        config=config,  # type: ignore[arg-type]
        baseline_store=baseline_store,  # type: ignore[arg-type]
        contractor_logo_bytes=contractor_logo_bytes,
    )
    return server, runtime, entry


def test_configured_api_hostname_is_exactly_allowlisted() -> None:
    async def scenario() -> None:
        server, runtime, _ = _server(api_hostname="nuve-local.example.net")
        async with TestClient(TestServer(server._create_app())) as client:
            accepted = await client.get("/", headers={"Host": "NUVE-LOCAL.EXAMPLE.NET"})
            assert accepted.status == 200

            unconfigured = await client.get("/", headers={"Host": "other.example.net"})
            assert unconfigured.status == 400

            vendor_host = await client.get("/", headers={"Host": "devapi.nuvehvac.com"})
            assert vendor_host.status == 400

            suffix_attack = await client.get(
                "/", headers={"Host": "nuve-local.example.net.attacker.invalid"}
            )
            assert suffix_attack.status == 400
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_contractor_metadata_uses_stock_download_contract() -> None:
    async def scenario() -> None:
        logo = b"synthetic validated png bytes"
        server, runtime, entry = _server(
            api_hostname="nuve-local.example.net",
            contractor_logo_bytes=logo,
        )
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True
        signature = contractor_logo_signature(
            token_fingerprint=entry.data[CONF_TOKEN_SHA256], serial=SERIAL
        )

        async with TestClient(TestServer(server._create_app())) as client:
            metadata = await client.get(
                f"/api/sync/getContractorInfo?sn={SERIAL}",
                headers={**HEADERS, "Host": "nuve-local.example.net"},
            )
            assert metadata.status == 200
            assert await metadata.json() == {
                "success": True,
                "status": "ok",
                "data": {
                    "brand": "Synthetic HVAC",
                    "phone": "555-0100",
                    "logo": (
                        f"https://nuve-local.example.net:18443/api/contractor-logo?"
                        f"sn={SERIAL}&sig={signature}"
                    ),
                },
            }

            image = await client.get(
                f"/api/contractor-logo?sn={SERIAL}&sig={signature}",
                headers={"Host": "nuve-local.example.net"},
            )
            assert image.status == 200
            assert image.content_type == "image/png"
            assert image.headers["Cache-Control"] == "no-store"
            assert await image.read() == logo

            missing_signature = await client.get(
                f"/api/contractor-logo?sn={SERIAL}",
                headers={"Host": "nuve-local.example.net"},
            )
            assert missing_signature.status == 401

            wrong_signature = await client.get(
                f"/api/contractor-logo?sn={SERIAL}&sig={'0' * 64}",
                headers={"Host": "nuve-local.example.net"},
            )
            assert wrong_signature.status == 401
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_request_gate_and_monitor_upload() -> None:
    async def scenario() -> None:
        server, runtime, entry = _server()
        async with TestClient(TestServer(server._create_app())) as client:
            wrong_host = await client.get("/", headers={"Host": "example.invalid"})
            assert wrong_host.status == 400

            wrong_serial = await client.get("/api/sync/getSettings?sn=wrong", headers=HEADERS)
            assert wrong_serial.status == 404

            invalid_token = await client.get(
                f"/api/sync/getSettings?sn={SERIAL}",
                headers={"Host": "devapi.nuvehvac.com", "Authorization": "Bearer bad"},
            )
            assert invalid_token.status == 401

            unsupported = await client.get(
                f"/api/not-real?sn={SERIAL}",
                headers=HEADERS,
            )
            assert unsupported.status == 404
            assert CONF_TOKEN_SHA256 not in entry.data
            assert runtime.state.available is False

            malformed = await client.post(
                f"/api/monitor/data?sn={SERIAL}",
                headers={**HEADERS, "Content-Type": "application/x-protobuf"},
                data=b"not protobuf",
            )
            assert malformed.status == 400
            assert CONF_TOKEN_SHA256 not in entry.data
            assert runtime.state.available is False

            accepted = await client.post(
                f"/api/monitor/data?sn={SERIAL}",
                headers={**HEADERS, "Content-Type": "application/x-protobuf"},
                data=_monitor_payload(),
            )
            assert accepted.status == 200
            assert runtime.state.current_temperature == 21.0
            assert runtime.state.available is True
            assert CONF_TOKEN_SHA256 in entry.data
            assert TOKEN not in repr(entry.data)

            wrong_paired_token = await client.get(
                f"/api/sync/getSettings?sn={SERIAL}",
                headers={
                    "Host": "devapi.nuvehvac.com",
                    "Authorization": f"Bearer {'b' * 64}",
                },
            )
            assert wrong_paired_token.status == 401
            await runtime.async_shutdown()

        wrong_source_server, _, _ = _server(thermostat_ip="192.0.2.23")
        async with TestClient(TestServer(wrong_source_server._create_app())) as client:
            wrong_source = await client.get("/", headers={"Host": "devapi.nuvehvac.com"})
            assert wrong_source.status == 403

    asyncio.run(scenario())


def test_closed_pairing_window_rejects_unknown_token_without_mutation() -> None:
    async def scenario() -> None:
        server, runtime, entry = _server()
        server._config.pop(CONF_PAIRING_DEADLINE)

        async with TestClient(TestServer(server._create_app())) as client:
            rejected = await client.post(
                f"/api/monitor/data?sn={SERIAL}",
                headers={**HEADERS, "Content-Type": "application/x-protobuf"},
                data=_monitor_payload(),
            )
            rejected_text = await rejected.text()

        assert rejected.status == 401
        assert rejected_text == "pairing window is closed"
        assert CONF_TOKEN_SHA256 not in entry.data
        assert runtime.paired is False
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_authenticated_http_error_paths_fail_without_pairing_or_mutation() -> None:
    async def scenario() -> None:
        server, runtime, entry = _server()
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True
        async with TestClient(TestServer(server._create_app())) as client:
            invalid_json = await client.post(
                f"/api/device/current-sensors?sn={SERIAL}",
                headers={**HEADERS, "Content-Type": "application/json"},
                data=b"{",
            )
            assert invalid_json.status == 400
            assert await invalid_json.text() == "invalid JSON"

            non_object = await client.post(
                f"/api/device/current-sensors?sn={SERIAL}",
                headers=HEADERS,
                json=[],
            )
            assert non_object.status == 400
            assert await non_object.text() == "JSON body must be an object"

            wifi_off = await client.post(
                f"/api/device/wifi-off?sn={SERIAL}",
                headers=HEADERS,
                json={"manual_off": True},
            )
            assert wifi_off.status == 400

            report = await client.post(
                f"/api/monitor/report?sn={SERIAL}",
                headers=HEADERS,
                json={},
            )
            assert report.status == 400

            partial_without_baseline = await client.post(
                f"/api/device/settings?sn={SERIAL}",
                headers=HEADERS,
                json=_settings_upload()["settings"],
            )
            assert partial_without_baseline.status == 409

        assert runtime.has_settings_baseline is False
        assert runtime.state.current_temperature is None
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_private_client_identity_endpoint_remains_quietly_unsupported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        server, runtime, _entry = _server()
        caplog.set_level(logging.DEBUG, logger="custom_components.nuve_local.server")
        async with TestClient(TestServer(server._create_app())) as client:
            response = await client.get(f"/api/sync/client?sn={SERIAL}", headers=HEADERS)
            assert response.status == 404
        await runtime.async_shutdown()

    asyncio.run(scenario())

    matching = [
        record for record in caplog.records if "client-identity endpoint" in record.getMessage()
    ]
    assert len(matching) == 1
    assert matching[0].levelno == logging.DEBUG


def test_monitor_event_upload_is_validated_and_discarded() -> None:
    async def scenario() -> None:
        server, runtime, entry = _server()
        async with TestClient(TestServer(server._create_app())) as client:
            malformed = await client.post(
                f"/api/monitor/event?sn={SERIAL}",
                headers={**HEADERS, "Content-Type": "application/x-protobuf"},
                data=_event_payload(target=b"\xff"),
            )
            assert malformed.status == 400
            assert CONF_TOKEN_SHA256 not in entry.data

            accepted = await client.post(
                f"/api/monitor/event?sn={SERIAL}",
                headers={**HEADERS, "Content-Type": "application/x-protobuf"},
                data=_event_payload(target=b"private-ui-target"),
            )
            assert accepted.status == 200
            assert await accepted.json() == {
                "success": True,
                "status": "ok",
                "data": {},
            }
            assert CONF_TOKEN_SHA256 in entry.data
            assert runtime.state.records_received == 0
            assert runtime.state.current_temperature is None
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_forwarded_source_is_trusted_only_from_one_exact_proxy() -> None:
    async def scenario() -> None:
        server, runtime, _ = _server(thermostat_ip="192.0.2.23", trusted_proxy_ip="127.0.0.1")
        async with TestClient(TestServer(server._create_app())) as client:
            accepted = await client.get(
                "/",
                headers={**HEADERS, "X-Forwarded-For": "192.0.2.23"},
            )
            assert accepted.status == 200

            for forwarded in (None, "192.0.2.24", "192.0.2.23, 198.51.100.1"):
                headers = dict(HEADERS)
                if forwarded is not None:
                    headers["X-Forwarded-For"] = forwarded
                rejected = await client.get("/", headers=headers)
                assert rejected.status == 403
        await runtime.async_shutdown()

        untrusted, untrusted_runtime, _ = _server(
            thermostat_ip="192.0.2.23", trusted_proxy_ip="192.0.2.10"
        )
        async with TestClient(TestServer(untrusted._create_app())) as client:
            spoofed = await client.get(
                "/",
                headers={**HEADERS, "X-Forwarded-For": "192.0.2.23"},
            )
            assert spoofed.status == 403
        await untrusted_runtime.async_shutdown()

    asyncio.run(scenario())


def test_full_settings_upload_pairs_without_query_and_drives_exact_echo() -> None:
    async def scenario() -> None:
        server, runtime, entry = _server(contractor_url="https://contractor.example")
        async with TestClient(TestServer(server._create_app())) as client:
            wrong_body = _settings_upload()
            wrong_body["sn"] = "wrong"
            rejected = await client.post(
                "/api/sync/update",
                headers=HEADERS,
                json=wrong_body,
            )
            assert rejected.status == 400
            assert CONF_TOKEN_SHA256 not in entry.data

            accepted = await client.post(
                "/api/sync/update",
                headers=HEADERS,
                json=_settings_upload(),
            )
            assert accepted.status == 200
            ack = await accepted.json()
            assert ack["success"] is True
            assert ack["status"] == "ok"
            revision = ack["data"]["setting"]["last_update"]
            assert CONF_TOKEN_SHA256 in entry.data
            assert runtime.has_settings_baseline

            monitor = await client.post(
                f"/api/monitor/data?sn={SERIAL}",
                headers={**HEADERS, "Content-Type": "application/x-protobuf"},
                data=_monitor_payload(
                    timestamp=datetime.now(UTC) + timedelta(seconds=1), full=True
                ),
            )
            assert monitor.status == 200

            polled = await client.get(
                f"/api/sync/getSettings?sn={SERIAL}",
                headers=HEADERS,
            )
            body = await polled.json()
            assert body["success"] is True
            body = body["data"]
            assert body["sn"] == SERIAL
            assert body["setting"]["last_update"] == revision
            assert body["temp"] == 21.5
            assert body["qr_url"] == "https://contractor.example"
            assert "zip" not in body["setting"]
            assert body["setting"]["command"] == "push_live_data"
            await runtime.async_shutdown()

    asyncio.run(scenario())


def test_restored_baseline_uses_two_http_polls_to_force_fresh_full_monitor() -> None:
    async def scenario() -> None:
        source = NuveRuntime(serial=SERIAL)
        now = datetime.now(UTC)
        source.async_accept_settings_snapshot(_settings_upload(), received_at=now)
        source.async_accept_auto_mode_snapshot(
            {
                "auto_temp_low": 19.0,
                "auto_temp_high": 23.0,
                "is_active": False,
                "mode": "heating",
            },
            received_at=now,
        )
        persisted = source.persistent_baselines()
        await source.async_shutdown()

        server, runtime, entry = _server()
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True
        runtime.async_restore_persistent_baselines(persisted)

        async with TestClient(TestServer(server._create_app())) as client:
            reset_response = await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            reset = (await reset_response.json())["data"]
            assert reset_response.status == 200
            assert reset["hold_period"] == {}
            assert set(reset["setting"]) == {"last_update"}

            reset_auto_response = await client.get(
                f"/api/sync/autoMode?sn={SERIAL}", headers=HEADERS
            )
            reset_auto = (await reset_auto_response.json())["data"]
            assert reset_auto_response.status == 200
            assert reset_auto == {
                "last_update": runtime.auto_mode_revision,
                "auto_temp_low": {},
                "auto_temp_high": {},
            }

            wake_response = await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            wake = (await wake_response.json())["data"]
            assert wake_response.status == 200
            assert wake["hold_period"] == {}
            assert wake["setting"]["command"] == "push_live_data"
            assert wake["setting"]["command_time"] > wake["setting"]["last_update"]

            wake_auto_response = await client.get(
                f"/api/sync/autoMode?sn={SERIAL}", headers=HEADERS
            )
            wake_auto = (await wake_auto_response.json())["data"]
            assert wake_auto_response.status == 200
            assert wake_auto == reset_auto

            forbidden = {"temp", "mode_id", "fan", "system", "schedule", "schedule2"}
            assert not forbidden.intersection(reset)
            assert not forbidden.intersection(wake)
            assert runtime.authoritative_control_monitor_seen is False

            full = await client.post(
                f"/api/monitor/data?sn={SERIAL}",
                headers={**HEADERS, "Content-Type": "application/x-protobuf"},
                data=_monitor_payload(
                    timestamp=datetime.now(UTC) + timedelta(seconds=1), full=True
                ),
            )
            assert full.status == 200
            assert runtime.authoritative_control_monitor_seen is True
            assert runtime.canonical_live_consistency_ready is True

            canonical = await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            assert (await canonical.json())["data"]["temp"] == 21.5
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_current_sensor_ack_uses_firmware_reply_types() -> None:
    async def scenario() -> None:
        server, runtime, _ = _server()
        async with TestClient(TestServer(server._create_app())) as client:
            response = await client.post(
                f"/api/device/current-sensors?sn={SERIAL}",
                headers=HEADERS,
                json={
                    "current_humidity": "61.9688",
                    "current_temp": 23,
                    "co2_id": 1,
                },
            )
            assert response.status == 200
            assert (await response.json())["data"] == {
                "current_humidity": "61.9688",
                "current_temp": "23",
                "co2_id": 1,
            }
            assert runtime.state.current_temperature == 23.0
            assert runtime.current_temperature_source == "current_sensors"
            assert runtime.current_temperature_observed_at is not None
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_real_http_command_delivery_journals_then_confirms(monkeypatch: Any) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        store = FakeBaselineStore()
        server, runtime, entry = _server(baseline_store=store)
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True
        now = datetime.now(UTC)
        runtime.async_accept_settings_snapshot(_settings_upload(), received_at=now)
        runtime.async_accept_auto_mode_snapshot(
            {
                "auto_temp_low": 19.0,
                "auto_temp_high": 23.0,
                "is_active": False,
                "mode": "heating",
            },
            received_at=now,
        )
        runtime.async_set_outdoor_temperature(10.0, "Test outdoor", observed_at=now)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                monitor_is_sync=True,
                current_temperature=21.0,
                target_temperature=21.5,
                target_humidity=40.0,
                auto_temperature_low=19.0,
                auto_temperature_high=23.0,
                system_type=NuveSystemType.HEAT_PUMP,
                mode=NuveMode.HEAT,
                schedule_type=9,
                records_received=1,
            )
        )
        runtime.control_enabled = True

        async with TestClient(TestServer(server._create_app())) as client:
            baseline = await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            assert baseline.status == 200
            assert (await baseline.json())["data"]["temp"] == 21.5

            command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
            await asyncio.sleep(0)
            delivered = await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            body = await delivered.json()
            assert delivered.status == 200
            assert body["success"] is True
            body = body["data"]
            assert body["temp"] == 22.0
            assert store.saved[-1]["uncertain_command"]["delivered_at"] is not None
            assert runtime.uncertain_command is not None
            assert runtime.uncertain_command.revision == body["setting"]["last_update"]

            await asyncio.sleep(0.002)
            confirmed_at = datetime.now(UTC)
            await runtime.async_process_monitor_state(
                NuveState(
                    available=True,
                    last_seen=confirmed_at,
                    sample_time=confirmed_at,
                    target_temperature=22.0,
                    records_received=1,
                )
            )
            await command
            assert runtime.uncertain_command is None
            assert runtime.live_data_command_time == body["setting"]["last_update"]
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_real_http_fan_command_confirms_only_after_persisted_full_upload() -> None:
    async def scenario() -> None:
        store = ValidatingBaselineStore()
        server, runtime, entry = _server(baseline_store=store)
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True
        now = datetime.now(UTC)
        runtime.async_accept_settings_snapshot(_settings_upload(), received_at=now)
        runtime.async_accept_auto_mode_snapshot(
            {
                "auto_temp_low": 19.0,
                "auto_temp_high": 23.0,
                "is_active": False,
                "mode": "heating",
            },
            received_at=now,
        )
        runtime.async_set_outdoor_temperature(10.0, "Test outdoor", observed_at=now)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                monitor_is_sync=True,
                current_temperature=21.0,
                target_temperature=21.5,
                target_humidity=40.0,
                auto_temperature_low=19.0,
                auto_temperature_high=23.0,
                system_type=NuveSystemType.HEAT_PUMP,
                mode=NuveMode.HEAT,
                schedule_type=9,
                records_received=1,
            )
        )
        runtime.control_enabled = True
        desired_fan = {"mode": 1, "workingPerHour": 40}

        async with TestClient(TestServer(server._create_app())) as client:
            await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            command = asyncio.create_task(
                runtime.async_request_settings_change({"fan": desired_fan})
            )
            await asyncio.sleep(0)
            delivered = await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            body = (await delivered.json())["data"]
            assert body["fan"] == desired_fan
            assert body["hold_period"] == ""
            assert runtime.uncertain_command is not None
            assert not command.done()

            await asyncio.sleep(0.002)
            upload = _settings_upload()
            upload["fan"] = desired_fan
            confirmed = await client.post(
                "/api/sync/update",
                headers=HEADERS,
                json=upload,
            )
            assert confirmed.status == 200
            await command
            assert runtime.uncertain_command is None
            assert runtime.authoritative_control_monitor_seen is True
            assert runtime.can_enable_control is True
            assert "uncertain_command" not in store.saved[-1]
            assert store.saved[-1]["settings"]["fan"] == desired_fan
            assert store.saved[-1]["settings"]["hold_period"] == ""
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_real_http_active_schedule_poll_is_nonapplying_and_blocks_settings() -> None:
    async def scenario() -> None:
        server, runtime, entry = _server()
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True
        now = datetime.now(UTC)
        runtime.async_accept_settings_snapshot(_settings_upload(), received_at=now)
        runtime.async_accept_auto_mode_snapshot(
            {
                "auto_temp_low": 19.0,
                "auto_temp_high": 23.0,
                "is_active": False,
                "mode": "heating",
            },
            received_at=now,
        )
        runtime.async_set_outdoor_temperature(10.0, "Test outdoor", observed_at=now)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                monitor_is_sync=True,
                current_temperature=21.0,
                target_temperature=21.5,
                target_humidity=40.0,
                auto_temperature_low=19.0,
                auto_temperature_high=23.0,
                system_type=NuveSystemType.HEAT_PUMP,
                mode=NuveMode.HEAT,
                schedule_type=2,
                records_received=1,
            )
        )
        runtime.control_enabled = True

        async with TestClient(TestServer(server._create_app())) as client:
            first_poll = await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            second_poll = await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            first_body = (await first_poll.json())["data"]
            second_body = (await second_poll.json())["data"]
            assert first_body == second_body
            assert first_body["hold"] is False
            assert first_body["hold_period"] == {}
            assert first_body["setting"]["command"] == "push_live_data"
            assert not {
                "temp",
                "mode_id",
                "fan",
                "system",
                "schedule",
                "schedule2",
            }.intersection(first_body)

            with pytest.raises(ControlNotReadyError):
                await runtime.async_request_settings_change(
                    {"fan": {"mode": 1, "workingPerHour": 40}}
                )
            assert runtime._pending_command is None
            assert runtime.uncertain_command is None
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_real_http_backlight_command_preserves_hvac_and_confirms_after_persistence() -> None:
    async def scenario() -> None:
        store = ValidatingBaselineStore()
        server, runtime, entry = _server(baseline_store=store)
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True
        now = datetime.now(UTC)
        baseline = _settings_upload()
        runtime.async_accept_settings_snapshot(baseline, received_at=now)
        runtime.async_accept_auto_mode_snapshot(
            {
                "auto_temp_low": 19.0,
                "auto_temp_high": 23.0,
                "is_active": False,
                "mode": "heating",
            },
            received_at=now,
        )
        runtime.async_set_outdoor_temperature(10.0, "Test outdoor", observed_at=now)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                monitor_is_sync=True,
                current_temperature=21.0,
                target_temperature=21.5,
                target_humidity=40.0,
                auto_temperature_low=19.0,
                auto_temperature_high=23.0,
                system_type=NuveSystemType.HEAT_PUMP,
                mode=NuveMode.HEAT,
                schedule_type=9,
                records_received=1,
            )
        )
        runtime.control_enabled = True
        desired = {"on": False, "hue": 0.5, "value": 0.5, "shadeIndex": 5}

        async with TestClient(TestServer(server._create_app())) as client:
            await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            command = asyncio.create_task(
                runtime.async_request_settings_change({"backlight": desired})
            )
            await asyncio.sleep(0)
            delivered = await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            body = (await delivered.json())["data"]
            assert body["setting"]["backlight"] == desired
            assert body["temp"] == baseline["temp"]
            assert body["mode_id"] == baseline["mode_id"]
            assert body["fan"] == baseline["fan"]
            assert body["system"] == baseline["system"]
            assert runtime.uncertain_command is not None
            assert not command.done()

            await asyncio.sleep(0.002)
            upload = _settings_upload()
            upload["backlight"] = desired
            confirmed = await client.post(
                "/api/sync/update",
                headers=HEADERS,
                json=upload,
            )
            assert confirmed.status == 200
            await command
            assert runtime.uncertain_command is None
            assert runtime.authoritative_control_monitor_seen is True
            assert runtime.can_enable_control is True
            assert "uncertain_command" not in store.saved[-1]
            assert store.saved[-1]["settings"]["backlight"] == desired
            assert store.saved[-1]["settings"]["temp"] == baseline["temp"]
            assert store.saved[-1]["settings"]["system"] == baseline["system"]
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_real_http_final_boundary_failure_returns_sent_body_and_latches_control(
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        store = FinalBoundaryFailingStore()
        server, runtime, entry = _server(baseline_store=store)
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True
        runtime.command_timeout_seconds = 0.05
        now = datetime.now(UTC)
        runtime.async_accept_settings_snapshot(_settings_upload(), received_at=now)
        runtime.async_accept_auto_mode_snapshot(
            {
                "auto_temp_low": 19.0,
                "auto_temp_high": 23.0,
                "is_active": False,
                "mode": "heating",
            },
            received_at=now,
        )
        runtime.async_set_outdoor_temperature(10.0, "Test outdoor", observed_at=now)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                monitor_is_sync=True,
                current_temperature=21.0,
                target_temperature=21.5,
                target_humidity=40.0,
                auto_temperature_low=19.0,
                auto_temperature_high=23.0,
                system_type=NuveSystemType.HEAT_PUMP,
                mode=NuveMode.HEAT,
                schedule_type=9,
                records_received=1,
            )
        )
        runtime.control_enabled = True

        async with TestClient(TestServer(server._create_app())) as client:
            await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
            await asyncio.sleep(0)
            delivered = await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            body = await delivered.json()
            assert delivered.status == 200
            assert body["success"] is True
            body = body["data"]
            assert body["temp"] == 22.0
            for _ in range(20):
                if runtime.persistence_fault_latched:
                    break
                await asyncio.sleep(0.005)
            assert runtime.persistence_fault_latched is True
            assert runtime.persistence_healthy is False
            assert runtime.uncertain_command is not None
            assert runtime.uncertain_command.delivered_at is None
            assert store.saved[-1]["uncertain_command"]["delivered_at"] is None
            with pytest.raises(runtime_module.CommandOutcomeUncertainError):
                await command
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_explicit_bootstrap_fetch_is_replaced_by_persisted_device_upload() -> None:
    async def scenario() -> None:
        store = FakeBaselineStore()
        server, runtime, entry = _server(baseline_store=store)
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True
        runtime.bootstrap_firmware_version = "1.5.7.4"
        runtime.bootstrap_technician_url = "https://contractor.invalid/preserved"
        runtime.bootstrap_metadata_confirmed = True
        now = datetime.now(UTC)
        runtime.async_note_authenticated_contact(now)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                records_received=1,
            )
        )

        async with TestClient(TestServer(server._create_app())) as client:
            await runtime.async_arm_baseline_bootstrap(armed_at=datetime.now(UTC))
            settings_response = await client.get(
                f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS
            )
            auto_response = await client.get(f"/api/sync/autoMode?sn={SERIAL}", headers=HEADERS)
            settings_body = await settings_response.json()
            assert settings_body["data"]["hold"] is False
            assert settings_body["data"]["hold_period"] == {}
            assert set(settings_body["data"]["setting"]) == {"last_update"}
            assert (await auto_response.json())["data"]["auto_temp_low"] == {}

            uploaded = await client.post(
                "/api/sync/update",
                headers=HEADERS,
                json=_settings_upload(),
            )
            assert uploaded.status == 200
            assert runtime.bootstrap_status == "complete"
            assert store.saved[-1]["settings"]["temp"] == 21.5

            monitor = await client.post(
                f"/api/monitor/data?sn={SERIAL}",
                headers={**HEADERS, "Content-Type": "application/x-protobuf"},
                data=_monitor_payload(
                    timestamp=datetime.now(UTC) + timedelta(seconds=1), full=True
                ),
            )
            assert monitor.status == 200

            canonical = await client.get(f"/api/sync/getSettings?sn={SERIAL}", headers=HEADERS)
            assert (await canonical.json())["data"]["temp"] == 21.5
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_full_upload_is_not_committed_or_acknowledged_when_persistence_fails() -> None:
    async def scenario() -> None:
        server, runtime, entry = _server(
            baseline_store=FailingBaselineStore()  # type: ignore[arg-type]
        )
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True
        runtime.bootstrap_firmware_version = "1.5.7.4"
        runtime.bootstrap_metadata_confirmed = True
        now = datetime.now(UTC)
        runtime.async_note_authenticated_contact(now)

        async with TestClient(TestServer(server._create_app())) as client:
            response = await client.post(
                "/api/sync/update",
                headers=HEADERS,
                json=_settings_upload(),
            )
            assert response.status == 503
            assert runtime.has_settings_baseline is False
            assert runtime.persistence_fault_latched is True
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_full_upload_internal_persistence_cancellation_fails_closed() -> None:
    async def scenario() -> None:
        server, runtime, entry = _server(
            baseline_store=CancelledBaselineStore()  # type: ignore[arg-type]
        )
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True
        runtime.bootstrap_firmware_version = "1.5.7.4"
        runtime.bootstrap_metadata_confirmed = True

        async with TestClient(TestServer(server._create_app())) as client:
            response = await client.post(
                "/api/sync/update",
                headers=HEADERS,
                json=_settings_upload(),
            )
            assert response.status == 503
            assert runtime.has_settings_baseline is False
            assert runtime.persistence_healthy is False
            assert runtime.persistence_fault_latched is True
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_real_auto_upload_is_projected_and_persists_before_ack() -> None:
    async def scenario() -> None:
        store = ValidatingBaselineStore()
        server, runtime, entry = _server(baseline_store=store)  # type: ignore[arg-type]
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True

        async with TestClient(TestServer(server._create_app())) as client:
            response = await client.post(
                f"/api/sync/autoMode?sn={SERIAL}",
                headers=HEADERS,
                json={
                    "auto_temp_low": 19.0,
                    "auto_temp_high": 23.0,
                    "is_active": True,
                    "mode": "auto",
                },
            )
            assert response.status == 200
            assert runtime.auto_mode_snapshot == {
                "auto_temp_low": 19.0,
                "auto_temp_high": 23.0,
            }
            assert store.saved[-1]["auto_mode"] == runtime.auto_mode_snapshot
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_weather_current_returns_only_observed_state_and_fails_stale() -> None:
    async def scenario() -> None:
        server, runtime, entry = _server()
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True
        observed_at = datetime.now(UTC)
        runtime.async_set_outdoor_temperature(
            7.25,
            "Back garden",
            humidity_percent=82.0,
            weather={"icon": "02d", "description": "partly cloudy"},
            observed_at=observed_at,
        )
        runtime.async_set_forecast(
            {
                "city": {"name": "Amherst", "country": "CA", "timezone": -10800},
                "list": [
                    {
                        "dt": int(observed_at.timestamp()),
                        "temp": {"day": 11.0, "min": 2.0, "max": 11.0},
                        "weather": [{"icon": "02d", "description": "partly cloudy"}],
                    }
                ],
            },
            status="ok",
        )
        server._hass.config.country = "CA"

        async with TestClient(TestServer(server._create_app())) as client:
            response = await client.get(
                f"/api/weather-current?sn={SERIAL}&units=metric",
                headers=HEADERS,
            )
            assert response.status == 200
            body = await response.json()
            assert body == {
                "success": True,
                "status": "ok",
                "data": {
                    "dt": int(observed_at.timestamp()),
                    "name": "Back garden",
                    "main": {
                        "temp": 7.25,
                        "temp_min": 2.0,
                        "temp_max": 11.0,
                        "humidity": 82.0,
                    },
                    "timezone": -10800,
                    "sys": {"country": "CA"},
                    "weather": [{"icon": "02d", "description": "partly cloudy"}],
                },
            }

            runtime.async_set_outdoor_temperature(
                7.25,
                "Back garden",
                observed_at=observed_at - timedelta(hours=3),
            )
            stale = await client.get(
                f"/api/weather-current?sn={SERIAL}&units=metric",
                headers=HEADERS,
            )
            assert stale.status == 503
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_forecast_projection_and_design_temperature_safe_noop() -> None:
    async def scenario() -> None:
        server, runtime, entry = _server()
        entry.data[CONF_TOKEN_SHA256] = token_sha256(TOKEN)
        runtime.paired = True

        async with TestClient(TestServer(server._create_app())) as client:
            forecast = await client.get(
                f"/api/weather-forecast?sn={SERIAL}&units=metric",
                headers=HEADERS,
            )
            assert forecast.status == 200
            assert await forecast.json() == {
                "success": True,
                "status": "ok",
                "data": {"list": []},
            }

            runtime.async_set_forecast(
                {
                    "city": {"name": "Amherst", "country": "CA", "timezone": -10800},
                    "list": [
                        {
                            "dt": 1786291200,
                            "temp": {"day": 24.0, "min": 17.0, "max": 24.0},
                            "humidity": 70.0,
                            "weather": [{"icon": "02d", "description": "partly cloudy"}],
                        }
                    ],
                },
                status="ok",
            )
            populated = await client.get(
                f"/api/weather-forecast?sn={SERIAL}&units=metric",
                headers=HEADERS,
            )
            assert populated.status == 200
            assert await populated.json() == {
                "success": True,
                "status": "ok",
                "data": {
                    "city": {"name": "Amherst", "country": "CA", "timezone": -10800},
                    "list": [
                        {
                            "dt": 1786291200,
                            "temp": {"day": 24.0, "min": 24.0, "max": 17.0},
                            "humidity": 70.0,
                            "weather": [{"icon": "02d", "description": "partly cloudy"}],
                        }
                    ],
                },
            }

            design = await client.get(
                f"/api/designTemperature?sn={SERIAL}",
                headers=HEADERS,
            )
            assert design.status == 200
            assert await design.json() == {
                "success": True,
                "status": "ok",
                "data": {},
            }
        await runtime.async_shutdown()

    asyncio.run(scenario())
