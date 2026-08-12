#!/usr/bin/env python3
"""Independent exact-1.5.8 screen-lock state and response model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LockUpdate:
    accepted: bool
    changed: bool
    is_locked: bool
    stored_pin: str
    push_pin: str | None
    should_push: bool
    reason: str | None


@dataclass(frozen=True)
class LockResponse:
    accepted: bool
    returned_locked: bool


def update_lock_state(
    *,
    current_locked: bool,
    stored_pin: str,
    requested_locked: bool,
    entered_pin: str,
    master_pin: str = "",
    has_client: bool,
    from_server: bool = False,
) -> LockUpdate:
    """Model updateAppLockState plus lockDevice without logging private values."""

    if len(entered_pin) != 4:
        return LockUpdate(False, False, current_locked, stored_pin, None, False, "pin_length")

    effective_pin = entered_pin
    pin_correct = requested_locked or stored_pin == entered_pin
    if not requested_locked and not pin_correct and len(master_pin) == 4:
        pin_correct = master_pin == entered_pin
        if pin_correct:
            effective_pin = stored_pin
    if not pin_correct:
        return LockUpdate(False, False, current_locked, stored_pin, None, False, "pin_mismatch")
    if requested_locked and not has_client:
        return LockUpdate(False, False, current_locked, stored_pin, None, False, "no_client")
    if current_locked == requested_locked and stored_pin == effective_pin:
        return LockUpdate(False, False, current_locked, stored_pin, None, False, "unchanged")

    return LockUpdate(
        accepted=True,
        changed=True,
        is_locked=requested_locked,
        stored_pin=effective_pin,
        push_pin=effective_pin if not from_server else None,
        should_push=not from_server,
        reason=None,
    )


def build_lock_request(*, serial: str, pin: str, locked: bool) -> tuple[str, dict[str, str]]:
    action = "lock" if locked else "unlock"
    return f"api/sync/screen-{action}?sn={serial}", {"pin": pin}


def decode_lock_response(payload: Any) -> LockResponse:
    """Model native contains/toBool behavior without checking desired state."""

    if not isinstance(payload, Mapping) or "locked" not in payload:
        return LockResponse(accepted=False, returned_locked=False)
    value = payload["locked"]
    return LockResponse(accepted=True, returned_locked=value if isinstance(value, bool) else False)


def next_retry_interval_ms(current: int) -> int:
    return min(current * 2, 60_000)
