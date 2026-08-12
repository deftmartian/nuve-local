"""Tests for strict device-request authentication primitives."""

from __future__ import annotations

import hashlib

import pytest

from custom_components.nuve_local.auth import (
    extract_bearer_token,
    is_allowed_source,
    is_expected_host,
    token_sha256,
)


def test_accepts_exact_bearer_token() -> None:
    token = "a" * 64
    assert extract_bearer_token(f"Bearer {token}") == token
    assert extract_bearer_token(f"bearer {token.upper()}") == token.upper()
    assert token_sha256(token) == hashlib.sha256(token.encode()).hexdigest()


@pytest.mark.parametrize(
    "authorization",
    [
        "",
        "Bearer",
        "Basic " + "a" * 64,
        "Bearer " + "a" * 63,
        "Bearer " + "g" * 64,
        "Bearer  " + "a" * 64,
        "Bearer " + "a" * 64 + " trailing",
    ],
)
def test_rejects_non_exact_authorization(authorization: str) -> None:
    assert extract_bearer_token(authorization) is None


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("devapi.nuvehvac.com", True),
        ("DEVAPI.NUVEHVAC.COM:443", True),
        ("devapi.nuvehvac.com:18443", True),
        ("devapi11.nuvehvac.com", True),
        ("devapi.nuvehvac.com:", False),
        ("devapi.nuvehvac.com:garbage", False),
        ("devapi.nuvehvac.com:0", False),
        ("devapi.nuvehvac.com:65536", False),
        ("devapi.nuvehvac.com.example", False),
        ("198.51.100.2", False),
        ("", False),
    ],
)
def test_expected_host_allowlist(host: str, expected: bool) -> None:
    assert is_expected_host(host) is expected


def test_custom_host_is_exactly_scoped() -> None:
    expected = {"nuve-local.example.net"}
    assert is_expected_host("NUVE-LOCAL.EXAMPLE.NET:18443", expected) is True
    assert is_expected_host("devapi.nuvehvac.com", expected) is False
    assert is_expected_host("nuve-local.example.net.attacker.invalid", expected) is False


def test_proxy_source_requires_one_exact_forwarded_address() -> None:
    common = {
        "peer_ip": "192.0.2.10",
        "thermostat_ip": "192.0.2.23",
        "trusted_proxy_ip": "192.0.2.10",
    }
    assert is_allowed_source(**common, forwarded_for=["192.0.2.23"]) is True
    assert is_allowed_source(**common, forwarded_for=[]) is False
    assert is_allowed_source(**common, forwarded_for=["192.0.2.23", "192.0.2.24"]) is False
    assert is_allowed_source(**common, forwarded_for=["192.0.2.23, 192.0.2.24"]) is False
    assert is_allowed_source(**common, forwarded_for=["not-an-ip"]) is False


def test_untrusted_peer_cannot_spoof_forwarded_address() -> None:
    assert (
        is_allowed_source(
            peer_ip="198.51.100.1",
            thermostat_ip="192.0.2.23",
            trusted_proxy_ip="192.0.2.10",
            forwarded_for=["192.0.2.23"],
        )
        is False
    )
