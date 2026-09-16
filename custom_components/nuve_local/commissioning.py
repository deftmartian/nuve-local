"""Deployment-profile and five-minute pairing-window helpers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from .const import (
    CONF_API_HOSTNAME,
    CONF_DEPLOYMENT_PROFILE,
    CONF_LISTEN_PORT,
    CONF_PAIRING_DEADLINE,
    CONF_THERMOSTAT_HTTPS_PORT,
    DEFAULT_DEPLOYMENT_PROFILE,
    DEFAULT_LISTEN_PORT,
    DEPLOYMENT_PROFILE_DIRECT_TLS,
    DEPLOYMENT_PROFILES,
    PAIRING_WINDOW_SECONDS,
)


def deployment_profile(config: Mapping[str, Any]) -> str:
    """Return the explicit profile or the recommended clean-setup default."""

    configured = config.get(CONF_DEPLOYMENT_PROFILE)
    if configured in DEPLOYMENT_PROFILES:
        return str(configured)
    return DEFAULT_DEPLOYMENT_PROFILE


def thermostat_https_port(config: Mapping[str, Any]) -> int | None:
    """Return the thermostat-facing HTTPS port, or None when it cannot be known.

    Direct TLS may derive the port from the listener. Reverse-proxy deployments
    require an explicit thermostat-facing port and must not guess one.
    """

    port = (
        config.get(CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT)
        if deployment_profile(config) == DEPLOYMENT_PROFILE_DIRECT_TLS
        else config.get(CONF_THERMOSTAT_HTTPS_PORT)
    )
    if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535:
        return port
    return None


def thermostat_https_authority(config: Mapping[str, Any]) -> str | None:
    """Return ``host`` or ``host:port`` for thermostat-facing HTTPS URLs."""

    hostname = config.get(CONF_API_HOSTNAME)
    port = thermostat_https_port(config)
    if not isinstance(hostname, str) or not hostname or port is None:
        return None
    return hostname if port == 443 else f"{hostname}:{port}"


def new_pairing_deadline(*, now: datetime | None = None) -> str:
    """Return the UTC deadline for one explicit five-minute pairing window."""

    opened_at = (now or datetime.now(UTC)).astimezone(UTC)
    return (opened_at + timedelta(seconds=PAIRING_WINDOW_SECONDS)).isoformat()


def pairing_window_is_open(config: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """Return whether token learning is currently and explicitly authorized."""

    raw_deadline = config.get(CONF_PAIRING_DEADLINE)
    if not isinstance(raw_deadline, str) or not raw_deadline:
        return False
    try:
        deadline = datetime.fromisoformat(raw_deadline)
    except ValueError:
        return False
    if deadline.tzinfo is None:
        return False
    return (now or datetime.now(UTC)).astimezone(UTC) <= deadline.astimezone(UTC)
