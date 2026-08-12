"""Deployment-profile and five-minute pairing-window helpers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from .const import (
    CONF_DEPLOYMENT_PROFILE,
    CONF_PAIRING_DEADLINE,
    DEFAULT_DEPLOYMENT_PROFILE,
    DEPLOYMENT_PROFILES,
    PAIRING_WINDOW_SECONDS,
)


def deployment_profile(config: Mapping[str, Any]) -> str:
    """Return the explicit profile or the recommended clean-setup default."""

    configured = config.get(CONF_DEPLOYMENT_PROFILE)
    if configured in DEPLOYMENT_PROFILES:
        return str(configured)
    return DEFAULT_DEPLOYMENT_PROFILE


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
