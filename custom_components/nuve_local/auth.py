"""Small authentication primitives with no Home Assistant dependency."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Collection

from .const import EXPECTED_HOSTS, TOKEN_PATTERN


def extract_bearer_token(authorization: str) -> str | None:
    """Return a strictly formed device token without retaining the header."""

    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not re.fullmatch(TOKEN_PATTERN, token):
        return None
    return token


def token_sha256(token: str) -> str:
    """Return the persisted verifier for a device token."""

    return hashlib.sha256(token.encode()).hexdigest()


def is_expected_host(host: str, expected_hosts: Collection[str] = EXPECTED_HOSTS) -> bool:
    """Validate the host used by the thermostat, allowing a numeric port."""

    if not host or host != host.strip():
        return False
    hostname, separator, port = host.rpartition(":")
    if separator:
        if not hostname or not port.isdecimal():
            return False
        port_number = int(port)
        if not 1 <= port_number <= 65535:
            return False
    else:
        hostname = host
    if ":" in hostname:
        return False
    hostname = hostname.lower()
    return hostname in expected_hosts


def is_allowed_source(
    *,
    peer_ip: str | None,
    thermostat_ip: str,
    trusted_proxy_ip: str | None,
    forwarded_for: Collection[str],
) -> bool:
    """Validate a direct peer or one strict proxy-supplied client address."""

    try:
        peer = ipaddress.ip_address(peer_ip) if peer_ip is not None else None
        thermostat = ipaddress.ip_address(thermostat_ip)
    except ValueError:
        return False

    if peer == thermostat:
        return True
    if not trusted_proxy_ip:
        return False
    try:
        trusted_proxy = ipaddress.ip_address(trusted_proxy_ip)
    except ValueError:
        return False
    if peer != trusted_proxy:
        return False

    values = tuple(forwarded_for)
    if len(values) != 1 or "," in values[0]:
        return False
    try:
        forwarded = ipaddress.ip_address(values[0].strip())
    except ValueError:
        return False
    return forwarded == thermostat
