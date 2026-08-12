"""Tests for explicit direct TLS and reverse-proxy TLS termination."""

from __future__ import annotations

import asyncio
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from custom_components.nuve_local.certificate import async_create_ssl_context
from custom_components.nuve_local.const import (
    CONF_CERTIFICATE,
    CONF_DEPLOYMENT_PROFILE,
    CONF_PRIVATE_KEY,
    DEPLOYMENT_PROFILE_DIRECT_TLS,
    DEPLOYMENT_PROFILE_REVERSE_PROXY,
)
from custom_components.nuve_local.server import _async_listener_ssl_context


class FakeHass:
    async def async_add_executor_job(self, target: Any, *args: Any) -> Any:
        return target(*args)


def _write_test_certificate(directory: Path) -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
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
    private_key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return str(certificate_path), str(private_key_path)


def test_configured_certificate_files_are_loaded_through_the_executor(tmp_path: Path) -> None:
    async def scenario() -> None:
        certificate, private_key = _write_test_certificate(tmp_path)
        context = await async_create_ssl_context(
            FakeHass(),  # type: ignore[arg-type]
            certificate,
            private_key,
        )
        assert isinstance(context, ssl.SSLContext)
        assert context.minimum_version == ssl.TLSVersion.TLSv1_2

    asyncio.run(scenario())


def test_direct_tls_requires_a_complete_explicit_certificate_pair() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="direct TLS requires"):
            await async_create_ssl_context(
                FakeHass(),  # type: ignore[arg-type]
                "/config/certificate.pem",
                "",
            )

    asyncio.run(scenario())


def test_reverse_proxy_terminates_tls_and_direct_profile_owns_tls(tmp_path: Path) -> None:
    async def scenario() -> None:
        reverse = await _async_listener_ssl_context(
            FakeHass(),  # type: ignore[arg-type]
            {CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_REVERSE_PROXY},
        )
        assert reverse is None

        certificate, private_key = _write_test_certificate(tmp_path)
        direct = await _async_listener_ssl_context(
            FakeHass(),  # type: ignore[arg-type]
            {
                CONF_DEPLOYMENT_PROFILE: DEPLOYMENT_PROFILE_DIRECT_TLS,
                CONF_CERTIFICATE: certificate,
                CONF_PRIVATE_KEY: private_key,
            },
        )
        assert isinstance(direct, ssl.SSLContext)

    asyncio.run(scenario())
