"""Independent fixtures for exact-1.5.8 miscellaneous API workflows."""

from __future__ import annotations

from scripts.emulate_firmware_misc_api import (
    ALERT_RETRY_MS,
    COMMAND_REPORT_RETRY_MS,
    MESSAGE_LIMIT,
    RECOVERY_REPORT_RETRY_MS,
    MessageSource,
    MessageType,
    RecoveryReportState,
    build_alert_request,
    build_command_report_request,
    build_factory_reset_request,
    build_recovery_report_request,
    build_user_data_request,
    build_wifi_off_request,
    complete_alert_push,
    complete_command_report,
    complete_factory_reset,
    complete_messages_fetch,
    complete_recovery_report,
    complete_user_data,
    fire_recovery_report_timer,
    merge_server_messages,
)


def test_dedicated_message_fetch_discards_body_and_transport_result() -> None:
    assert complete_messages_fetch(network_ok=False, payload={"private": "discarded"})


def test_server_message_requires_exact_members_and_overwrites_read_state() -> None:
    result = merge_server_messages(
        [],
        [
            {"message_id": 1, "message": "", "created": "time", "type": 2},
            {"message_id": 2, "message": "safe", "created": None, "type": 2, "is_read": True},
        ],
    )
    assert result.changed and result.save_settings
    assert result.accepted_rows == 1 and result.ignored_rows == 1
    assert result.messages[0]["id"] == 2
    assert result.messages[0]["datetime"] == ""
    assert result.messages[0]["isRead"] is False


def test_server_system_notification_is_coerced_and_disabled_types_are_marked_read() -> None:
    result = merge_server_messages(
        [],
        [
            {"message_id": 1, "message": "notice", "created": "t", "type": 3},
            {"message_id": 2, "message": "alert", "created": "t", "type": 1},
        ],
        enabled_notifications=False,
        enabled_alerts=False,
    )
    by_id = {message["id"]: message for message in result.messages}
    assert by_id[1]["type"] is MessageType.NOTIFICATION
    assert by_id[1]["isRead"] is True
    assert by_id[2]["isRead"] is True


def test_server_message_dedupes_id_and_unassigned_shape_without_saving() -> None:
    existing = [
        {
            "id": -1,
            "type": MessageType.NOTIFICATION,
            "sourceType": MessageSource.SERVER,
            "message": "safe",
            "datetime": "time",
        }
    ]
    result = merge_server_messages(
        existing,
        [{"message_id": 9, "message": "safe", "created": "time", "type": 2}],
    )
    assert not result.changed and not result.save_settings
    assert result.messages[0]["id"] == 9


def test_message_storage_is_newest_first_and_capped_at_fifty() -> None:
    existing = [
        {
            "id": index,
            "type": MessageType.ERROR,
            "sourceType": MessageSource.DEVICE,
            "message": f"old-{index}",
            "datetime": "time",
        }
        for index in range(MESSAGE_LIMIT)
    ]
    result = merge_server_messages(
        existing,
        [{"message_id": 100, "message": "new", "created": "time", "type": 2}],
    )
    assert len(result.messages) == MESSAGE_LIMIT
    assert result.messages[0]["id"] == 100
    assert result.messages[-1]["id"] == MESSAGE_LIMIT - 2


def test_alert_packet_has_exact_shape_and_completion_trusts_transport_only() -> None:
    request = build_alert_request(serial="redacted", alert_type="safe-type")
    assert request is not None
    assert request.path == "api/sync/alerts"
    assert request.body == {
        "alerts": [{"type": "safe-type"}],
        "sn": "redacted",
    }
    completed = complete_alert_push(network_ok=True, response={}, matching_message_found=True)
    assert completed.success and completed.save_settings and completed.remove_from_queue
    assert completed.assigned_id is None
    failed = complete_alert_push(
        network_ok=False, response={"alert_id": 7}, matching_message_found=True
    )
    assert failed.retry_after_ms == ALERT_RETRY_MS
    assert not failed.remove_from_queue


def test_user_data_requires_nonempty_object_and_qt_string_members() -> None:
    assert build_user_data_request(serial="redacted").path == "api/sync/client?sn=redacted"
    assert not complete_user_data({}).emitted
    completion = complete_user_data({"email": 1, "con-name": "safe-name"})
    assert completion.emitted and completion.email == "" and completion.name == "safe-name"
    assert completion.fetching is False


def test_factory_reset_timeout_is_success_with_message_but_does_not_start_countdown() -> None:
    request = build_factory_reset_request(serial="redacted")
    assert request is not None
    assert request.body == {"sn": "redacted"}
    assert complete_factory_reset(serial_present=False, network_error=99).starts_countdown
    timed_out = complete_factory_reset(serial_present=True, network_error=5)
    assert timed_out.success and timed_out.message
    assert not timed_out.starts_countdown
    assert not complete_factory_reset(serial_present=True, network_error=6).success


def test_wifi_off_is_reporting_only_and_wait_flag_controls_nested_wait() -> None:
    request = build_wifi_off_request(serial="redacted", manual_off=True, wait_for_reply=True)
    assert request is not None
    assert request.body == {"manual_off": True}
    assert request.wait_for_reply
    assert build_wifi_off_request(serial="", manual_off=True, wait_for_reply=True) is None


def test_recovery_report_retries_value_identical_payload_every_ten_seconds() -> None:
    payload = b'{"files":[]}'
    request = build_recovery_report_request(serial="redacted", payload=payload)
    assert request is not None and request.body == payload
    failed = complete_recovery_report(payload=payload, network_ok=False, has_internet=True)
    assert failed == RecoveryReportState(payload, True, True)
    assert RECOVERY_REPORT_RETRY_MS == 10_000
    after_fire, should_send = fire_recovery_report_timer(failed)
    assert should_send and not after_fire.timer_running and after_fire.payload == payload
    assert (
        complete_recovery_report(payload=payload, network_ok=True, has_internet=True)
        == RecoveryReportState()
    )


def test_recovery_report_failure_while_offline_stalls_with_payload_retained() -> None:
    failed = complete_recovery_report(payload=b"safe", network_ok=False, has_internet=False)
    assert failed.valid and failed.payload == b"safe"
    assert not failed.timer_running


def test_command_report_body_omits_command_and_retries_twice_for_three_attempts() -> None:
    request = build_command_report_request(serial="redacted", data="safe-data")
    assert request is not None
    assert request.body == {"data": "safe-data"}
    assert "command" not in request.body

    first = complete_command_report(network_ok=False, retries_remaining=2)
    second = complete_command_report(network_ok=False, retries_remaining=first.retries_remaining)
    third = complete_command_report(network_ok=False, retries_remaining=second.retries_remaining)
    assert first.retry_after_ms == second.retry_after_ms == COMMAND_REPORT_RETRY_MS
    assert third.callback_success is False and third.retry_after_ms is None
    assert complete_command_report(network_ok=True, retries_remaining=2).callback_success is True
