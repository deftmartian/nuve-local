"""Tests for explicit direct TLS, certificate renewal, and reverse-proxy TLS termination."""

from __future__ import annotations

import asyncio
import itertools
import os
import ssl
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

import custom_components.nuve_local.server as server_module
from custom_components.nuve_local.certificate import ReloadableCertificate, async_load_certificate
from custom_components.nuve_local.commissioning import new_pairing_deadline
from custom_components.nuve_local.const import (
    CONF_API_HOSTNAME,
    CONF_CERTIFICATE,
    CONF_DEPLOYMENT_PROFILE,
    CONF_LISTEN_HOST,
    CONF_LISTEN_PORT,
    CONF_PAIRING_DEADLINE,
    CONF_PRIVATE_KEY,
    CONF_SERIAL,
    CONF_THERMOSTAT_IP,
    DEPLOYMENT_PROFILE_DIRECT_TLS,
    DEPLOYMENT_PROFILE_REVERSE_PROXY,
)
from custom_components.nuve_local.runtime import NuveRuntime
from custom_components.nuve_local.server import NuveApiServer, _async_listener_certificate

SERIAL = "00-000-000000"
_REWRITES = itertools.count(1)


class FakeHass:
    async def async_add_executor_job(self, target: Any, *args: Any) -> Any:
        return target(*args)


def _write_test_certificate(
    directory: Path,
    *,
    private_key: rsa.RSAPrivateKey | None = None,
    write_key: bool = True,
) -> tuple[str, str, bytes]:
    """Write a fresh self-signed pair; return the paths and the certificate's DER."""

    private_key = private_key or rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "nuve.test")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(private_key, hashes.SHA256())
    )
    certificate_path = directory / "certificate.pem"
    private_key_path = directory / "private-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    if write_key:
        private_key_path.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    # Renewal detection compares modification times; step each rewrite forward so
    # it is visible even on filesystems with coarse timestamps.
    stamp = time.time_ns() + next(_REWRITES) * 1_000_000_000
    os.utime(certificate_path, ns=(stamp, stamp))
    return (
        str(certificate_path),
        str(private_key_path),
        certificate.public_bytes(serialization.Encoding.DER),
    )


def test_configured_certificate_files_are_loaded_through_the_executor(tmp_path: Path) -> None:
    async def scenario() -> None:
        certificate, private_key, _ = _write_test_certificate(tmp_path)
        loaded = await async_load_certificate(
            FakeHass(),  # type: ignore[arg-type]
            certificate,
            private_key,
        )
        assert isinstance(loaded.context, ssl.SSLContext)
        assert loaded.context.minimum_version == ssl.TLSVersion.TLSv1_2

    asyncio.run(scenario())


def test_direct_tls_requires_a_complete_explicit_certificate_pair() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="direct TLS requires"):
            await async_load_certificate(
                FakeHass(),  # type: ignore[arg-type]
                "/config/certificate.pem",
                "",
            )

    asyncio.run(scenario())


def test_reverse_proxy_terminates_tls_and_direct_profile_owns_tls(tmp_path: Path) -> None:
    async def scenario() -> None:
        reverse = await _async_listener_certificate(
            FakeHass(),  # type: ignore[arg-type]
            {CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_REVERSE_PROXY},
        )
        assert reverse is None

        certificate, private_key, _ = _write_test_certificate(tmp_path)
        direct = await _async_listener_certificate(
            FakeHass(),  # type: ignore[arg-type]
            {
                CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_DIRECT_TLS,
                CONF_CERTIFICATE: certificate,
                CONF_PRIVATE_KEY: private_key,
            },
        )
        assert isinstance(direct, ReloadableCertificate)

    asyncio.run(scenario())


def test_unchanged_files_are_not_reloaded(tmp_path: Path) -> None:
    certificate, private_key, _ = _write_test_certificate(tmp_path)
    loaded = ReloadableCertificate(certificate, private_key)

    assert loaded.load_if_changed() is None
    assert loaded.current is loaded.context


def test_a_mismatched_renewal_keeps_the_previous_pair(tmp_path: Path) -> None:
    certificate, private_key, _ = _write_test_certificate(tmp_path)
    loaded = ReloadableCertificate(certificate, private_key)

    # A renewal caught half-written: a new certificate next to the old key.
    _write_test_certificate(tmp_path, write_key=False)
    with pytest.raises(ssl.SSLError):
        loaded.load_if_changed()
    assert loaded.current is loaded.context
    # The failure was not recorded as loaded, so the next check retries.
    with pytest.raises(ssl.SSLError):
        loaded.load_if_changed()


def _direct_tls_server(certificate: str, private_key: str) -> NuveApiServer:
    runtime = NuveRuntime(
        serial=SERIAL,
        bootstrap_firmware_version="1.5.7.4",
        bootstrap_technician_url="https://contractor.invalid/preserved",
        bootstrap_metadata_confirmed=True,
        bootstrap_no_update_confirmed=True,
        temp_correction_version=1,
    )
    config = {
        CONF_API_HOSTNAME: "nuve.test",
        CONF_THERMOSTAT_IP: "127.0.0.1",
        CONF_SERIAL: SERIAL,
        CONF_LISTEN_HOST: "127.0.0.1",
        CONF_LISTEN_PORT: 0,
        CONF_PAIRING_DEADLINE: new_pairing_deadline(),
        CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_DIRECT_TLS,
        CONF_CERTIFICATE: certificate,
        CONF_PRIVATE_KEY: private_key,
    }
    return NuveApiServer(
        hass=FakeHass(),  # type: ignore[arg-type]
        entry=None,  # type: ignore[arg-type]
        runtime=runtime,
        config=config,
        baseline_store=None,  # type: ignore[arg-type]
    )


async def _served_certificate(server: NuveApiServer, *, sni: bool = True) -> bytes:
    """Complete a real TLS handshake with the listener and return its certificate."""

    assert server._runner is not None
    host, port = server._runner.addresses[0][:2]
    client = ssl.create_default_context()
    client.check_hostname = False
    client.verify_mode = ssl.CERT_NONE
    # An empty server_hostname sends no SNI, as some thermostat builds might.
    _, writer = await asyncio.open_connection(
        host, port, ssl=client, server_hostname="nuve.test" if sni else ""
    )
    try:
        served = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
    finally:
        writer.close()
        await writer.wait_closed()
    assert served is not None
    return served


def test_direct_tls_listener_serves_a_renewed_certificate_without_restart(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        certificate, private_key, original = _write_test_certificate(tmp_path)
        server = _direct_tls_server(certificate, private_key)
        await server.async_start()
        try:
            assert server._certificate_watch is not None
            assert await _served_certificate(server) == original
            assert await server.async_reload_certificate_if_changed() is False

            _, _, renewed = _write_test_certificate(tmp_path)
            assert await server.async_reload_certificate_if_changed() is True
            assert await _served_certificate(server) == renewed
            assert await _served_certificate(server, sni=False) == renewed

            # A broken renewal is logged and the renewed pair keeps serving.
            _write_test_certificate(tmp_path, write_key=False)
            assert await server.async_reload_certificate_if_changed() is False
            assert server._certificate_reload_failed is True
            assert await _served_certificate(server) == renewed
        finally:
            watch = server._certificate_watch
            await server.async_stop()
        assert watch is not None and watch.cancelled()
        assert server._certificate_watch is None

    asyncio.run(scenario())


def test_the_watcher_picks_up_a_renewal_and_survives_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_module, "CERTIFICATE_RELOAD_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(server_module, "CERTIFICATE_RELOAD_RETRY_SECONDS", 0.01)

    async def served_becomes(server: NuveApiServer, expected: bytes) -> None:
        async with asyncio.timeout(5):
            # Polls an external effect (the served certificate); there is no event to await.
            while await _served_certificate(server) != expected:  # noqa: ASYNC110
                await asyncio.sleep(0.02)

    async def scenario() -> None:
        certificate, private_key, _ = _write_test_certificate(tmp_path)
        server = _direct_tls_server(certificate, private_key)
        await server.async_start()
        try:
            _, _, renewed = _write_test_certificate(tmp_path)
            await served_becomes(server, renewed)

            # An unexpected error is logged, and the watcher keeps running.
            original = server.async_reload_certificate_if_changed
            calls = 0

            async def failing_once() -> bool:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("synthetic watcher failure")
                return await original()

            monkeypatch.setattr(server, "async_reload_certificate_if_changed", failing_once)
            _, _, again = _write_test_certificate(tmp_path)
            await served_becomes(server, again)
            assert calls >= 2
            assert server._certificate_watch is not None
            assert not server._certificate_watch.done()
        finally:
            await server.async_stop()

    asyncio.run(scenario())
