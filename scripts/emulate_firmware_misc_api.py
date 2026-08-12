#!/usr/bin/env python3
"""Offline firmware 1.5.8 model for miscellaneous private API workflows.

The model omits protocol values. It reproduces recovered request,
completion, persistence, and retry behavior without contacting a thermostat or
vendor service and without retaining private identifiers or message content.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

REQUEST_TIMEOUT_MS = 20_000
ALERT_RETRY_MS = 6_000
RECOVERY_REPORT_RETRY_MS = 10_000
COMMAND_REPORT_RETRY_MS = 60_000
MESSAGE_LIMIT = 50
RESET_TIMEOUT_MESSAGE = "The server took too long to respond. Please try again later."


class MessageType(IntEnum):
    UNKNOWN = 0
    ALERT = 1
    NOTIFICATION = 2
    SYSTEM_NOTIFICATION = 3
    SYSTEM_ALERT = 4
    ERROR = 5


class MessageSource(IntEnum):
    UNKNOWN = 0
    DEVICE = 1
    SERVER = 2


@dataclass(frozen=True)
class ApiRequest:
    method: str
    path: str
    body: Mapping[str, Any] | bytes | None
    timeout_ms: int = REQUEST_TIMEOUT_MS
    authenticated: bool = True
    wait_for_reply: bool = False


@dataclass(frozen=True)
class MessageMerge:
    messages: tuple[dict[str, Any], ...]
    changed: bool
    save_settings: bool
    accepted_rows: int
    ignored_rows: int


@dataclass(frozen=True)
class UserDataCompletion:
    emitted: bool
    email: str = ""
    name: str = ""
    fetching: bool = False


@dataclass(frozen=True)
class FactoryResetCompletion:
    success: bool
    message: str
    starts_countdown: bool


@dataclass(frozen=True)
class AlertCompletion:
    success: bool
    assigned_id: Any
    save_settings: bool
    remove_from_queue: bool
    retry_after_ms: int | None


@dataclass(frozen=True)
class RecoveryReportState:
    payload: bytes = b""
    valid: bool = False
    timer_running: bool = False


@dataclass(frozen=True)
class CommandReportCompletion:
    callback_success: bool | None
    retries_remaining: int
    retry_after_ms: int | None


def _js_strict_equal(left: Any, right: Any) -> bool:
    """Enough JavaScript strict equality for recovered JSON/model fields."""

    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    return type(left) is type(right) and left == right


def _json_string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _is_negative_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and value < 0


def complete_messages_fetch(*, network_ok: bool, payload: Any) -> bool:
    """The dedicated messages callback ignores transport status and payload."""

    del network_ok, payload
    return True


def merge_server_messages(
    existing: Sequence[Mapping[str, Any]],
    payload: Any,
    *,
    enabled_alerts: bool = True,
    enabled_notifications: bool = True,
    control_alert_feature_enabled: bool = True,
) -> MessageMerge:
    """Model Settings ``messages`` ingestion and whole-repository save behavior.

    Rich-message image parsing and QtQuickStream object identity are outside this
    value-free model; the selected rich/plain source is retained in
    ``parsedMessage`` so the branch can be tested on its own.
    """

    messages = [dict(item) for item in existing]
    if not isinstance(payload, list):
        return MessageMerge(tuple(messages), False, False, 0, 0)

    changed = False
    accepted = 0
    ignored = 0
    for row_value in payload:
        if not isinstance(row_value, Mapping):
            ignored += 1
            continue
        row = dict(row_value)
        required = ("message_id", "message", "created", "type")
        if any(key not in row for key in required) or row["message"] == "":
            ignored += 1
            continue

        # Exact QML mutates the input row before reading its optional value.
        row["is_read"] = False
        message_datetime = "" if row["created"] is None else row["created"]
        row_type = (
            MessageType.NOTIFICATION
            if _js_strict_equal(row["type"], MessageType.SYSTEM_NOTIFICATION)
            else (MessageType.NOTIFICATION if row["type"] is None else row["type"])
        )

        found: dict[str, Any] | None = None
        for candidate in messages:
            if not _js_strict_equal(candidate.get("sourceType"), MessageSource.SERVER):
                continue
            same_id = _js_strict_equal(row["message_id"], candidate.get("id"))
            same_unassigned = (
                _is_negative_number(candidate.get("id"))
                and _js_strict_equal(candidate.get("message"), row["message"])
                and _js_strict_equal(candidate.get("datetime"), message_datetime)
                and _js_strict_equal(candidate.get("type"), row_type)
            )
            if same_id or same_unassigned:
                found = candidate
                break

        if found is not None:
            if row["message_id"] is not None:
                found["id"] = row["message_id"]
            ignored += 1
            continue

        is_read = False
        if (
            not enabled_alerts
            and control_alert_feature_enabled
            and _js_strict_equal(row_type, MessageType.ALERT)
        ):
            is_read = True
        if not enabled_notifications and _js_strict_equal(row_type, MessageType.NOTIFICATION):
            is_read = True

        rich = row.get("message_rich")
        parsed = rich if rich and len(rich) > 0 else row["message"]
        messages.insert(
            0,
            {
                "id": row["message_id"],
                "type": row_type,
                "sourceType": MessageSource.SERVER,
                "title": "" if row.get("title") is None else row.get("title", ""),
                "message": row["message"],
                "parsedMessage": parsed,
                "isRead": is_read,
                "icon": "" if row.get("icon") is None else row.get("icon", ""),
                "datetime": message_datetime,
            },
        )
        if len(messages) > MESSAGE_LIMIT:
            del messages[MESSAGE_LIMIT:]
        changed = True
        accepted += 1

    return MessageMerge(tuple(messages), changed, changed, accepted, ignored)


def build_alert_request(*, serial: str, alert_type: str) -> ApiRequest | None:
    if not serial:
        return None
    return ApiRequest(
        "POST",
        "api/sync/alerts",
        {"alerts": [{"type": alert_type}], "sn": serial},
    )


def complete_alert_push(
    *, network_ok: bool, response: Mapping[str, Any], matching_message_found: bool
) -> AlertCompletion:
    """Model transport-only success and unvalidated ``alert_id`` assignment."""

    assigned_id = response.get("alert_id") if matching_message_found and network_ok else None
    return AlertCompletion(
        success=network_ok,
        assigned_id=assigned_id,
        save_settings=network_ok and matching_message_found,
        remove_from_queue=network_ok,
        retry_after_ms=None if network_ok else ALERT_RETRY_MS,
    )


def build_user_data_request(*, serial: str) -> ApiRequest | None:
    if not serial:
        return None
    return ApiRequest("GET", f"api/sync/client?sn={serial}", None)


def complete_user_data(payload: Any) -> UserDataCompletion:
    if not isinstance(payload, Mapping) or not payload:
        return UserDataCompletion(emitted=False)
    return UserDataCompletion(
        emitted=True,
        email=_json_string(payload.get("email")),
        name=_json_string(payload.get("con-name")),
    )


def build_factory_reset_request(*, serial: str) -> ApiRequest | None:
    if not serial:
        return None
    return ApiRequest("POST", f"api/sync/forget?sn={serial}", {"sn": serial})


def complete_factory_reset(*, serial_present: bool, network_error: int) -> FactoryResetCompletion:
    if not serial_present or network_error == 0:
        return FactoryResetCompletion(True, "", True)
    if network_error == 5:
        return FactoryResetCompletion(True, RESET_TIMEOUT_MESSAGE, False)
    return FactoryResetCompletion(False, "", False)


def build_wifi_off_request(
    *, serial: str, manual_off: bool, wait_for_reply: bool
) -> ApiRequest | None:
    if not serial:
        return None
    return ApiRequest(
        "POST",
        f"api/device/wifi-off?sn={serial}",
        {"manual_off": manual_off},
        wait_for_reply=wait_for_reply,
    )


def build_recovery_report_request(*, serial: str, payload: bytes) -> ApiRequest | None:
    if not serial:
        return None
    return ApiRequest("POST", f"api/device/recovery-image?sn={serial}", payload)


def complete_recovery_report(
    *, payload: bytes, network_ok: bool, has_internet: bool
) -> RecoveryReportState:
    if network_ok:
        return RecoveryReportState()
    return RecoveryReportState(
        payload=payload,
        valid=True,
        timer_running=has_internet,
    )


def fire_recovery_report_timer(state: RecoveryReportState) -> tuple[RecoveryReportState, bool]:
    """A one-shot firing resends nonempty ``fileData`` and leaves it pending."""

    should_send = bool(state.payload)
    return RecoveryReportState(state.payload, state.valid, False), should_send


def build_command_report_request(*, serial: str, data: str) -> ApiRequest | None:
    if not serial:
        return None
    return ApiRequest("POST", f"api/monitor/report?sn={serial}", {"data": data})


def complete_command_report(*, network_ok: bool, retries_remaining: int) -> CommandReportCompletion:
    if network_ok:
        return CommandReportCompletion(True, retries_remaining, None)
    if retries_remaining > 0:
        return CommandReportCompletion(None, retries_remaining - 1, COMMAND_REPORT_RETRY_MS)
    return CommandReportCompletion(False, 0, None)
