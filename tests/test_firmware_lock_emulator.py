"""Independent checks for exact-1.5.8 screen-lock recovery claims."""

from __future__ import annotations

from scripts.emulate_firmware_lock import (
    build_lock_request,
    decode_lock_response,
    next_retry_interval_ms,
    update_lock_state,
)


def test_lock_requires_exactly_four_characters_but_not_numeric_content() -> None:
    assert not update_lock_state(
        current_locked=False,
        stored_pin="",
        requested_locked=True,
        entered_pin="123",
        has_client=True,
    ).accepted
    result = update_lock_state(
        current_locked=False,
        stored_pin="",
        requested_locked=True,
        entered_pin="ab!z",
        has_client=True,
    )
    assert result.accepted
    assert result.stored_pin == "ab!z"


def test_lock_is_refused_without_an_active_client() -> None:
    result = update_lock_state(
        current_locked=False,
        stored_pin="",
        requested_locked=True,
        entered_pin="1234",
        has_client=False,
    )
    assert not result.accepted
    assert result.reason == "no_client"


def test_unlock_requires_user_pin_or_four_character_master_pin() -> None:
    wrong = update_lock_state(
        current_locked=True,
        stored_pin="1234",
        requested_locked=False,
        entered_pin="9999",
        master_pin="5678",
        has_client=True,
    )
    assert not wrong.accepted
    master = update_lock_state(
        current_locked=True,
        stored_pin="1234",
        requested_locked=False,
        entered_pin="5678",
        master_pin="5678",
        has_client=True,
    )
    assert master.accepted
    assert master.stored_pin == "1234"
    assert master.push_pin == "1234"


def test_server_update_changes_local_state_without_pushback() -> None:
    result = update_lock_state(
        current_locked=False,
        stored_pin="0000",
        requested_locked=True,
        entered_pin="1234",
        has_client=True,
        from_server=True,
    )
    assert result.accepted
    assert not result.should_push
    assert result.push_pin is None


def test_route_selects_action_and_body_contains_only_pin() -> None:
    assert build_lock_request(serial="serial", pin="1234", locked=True) == (
        "api/sync/screen-lock?sn=serial",
        {"pin": "1234"},
    )
    assert build_lock_request(serial="serial", pin="1234", locked=False) == (
        "api/sync/screen-unlock?sn=serial",
        {"pin": "1234"},
    )


def test_response_presence_is_accepted_even_if_state_mismatches_or_type_is_wrong() -> None:
    mismatch = decode_lock_response({"locked": False})
    assert mismatch.accepted
    assert not mismatch.returned_locked
    wrong_type = decode_lock_response({"locked": "true"})
    assert wrong_type.accepted
    assert not wrong_type.returned_locked


def test_missing_locked_response_member_retries_with_capped_exponential_backoff() -> None:
    assert not decode_lock_response({"message": "ok"}).accepted
    assert next_retry_interval_ms(1_000) == 2_000
    assert next_retry_interval_ms(32_000) == 60_000
    assert next_retry_interval_ms(60_000) == 60_000
