"""Independent checks for exact-1.5.8 schedule V2 recovery claims."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scripts.emulate_firmware_schedule_v2 import (
    C_VERSION_1,
    C_VERSION_2,
    DeliveryState,
    HoldPeriod,
    HoldType,
    add_hold,
    decode_add_reply,
    decode_clear_reply,
    decode_fetch_reply,
    emulate_add_hold_call,
    expand_new_schedule,
    find_next_activity,
    find_running_activity,
    hold_expired,
    initial_v2_clear_call,
    may_automatically_retry,
    normalize_restored_holds,
    remove_hold,
    retry_v2_clear_call,
    serialize_v2_schedule,
)


def _schedule(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "enable": True,
        "type": 2,
        "startTime": "05:00 PM",
        "minimumTemperature": 20.0,
        "maximumTemperature": 24.44444,
        "fanMode": 0,
        "fanWorkingPerHour": 30,
        "repeats": "Mon, Tue",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize("data", [None, {}, "wrong", 4])
def test_nonempty_fetch_envelope_coerces_wrong_data_to_accepted_empty(data: object) -> None:
    assert decode_fetch_reply(network_ok=True, payload={"data": data}).accepted
    assert decode_fetch_reply(network_ok=True, payload={"data": data}).schedules == ()


def test_empty_fetch_object_is_failure_but_explicit_empty_array_is_success() -> None:
    assert not decode_fetch_reply(network_ok=True, payload={}).accepted
    assert decode_fetch_reply(network_ok=True, payload={"data": []}).accepted


def test_fetch_network_failure_rejects_even_a_well_formed_payload() -> None:
    result = decode_fetch_reply(network_ok=False, payload={"data": [{"id": 1}]})
    assert not result.accepted
    assert result.schedules == ()


def test_add_accepts_any_nonempty_object_without_validating_id() -> None:
    result = decode_add_reply(network_ok=True, payload={"message": "accepted"})
    assert result.accepted
    assert not result.has_server_id
    assert result.server_id is None


def test_add_rejects_empty_object_and_network_failure() -> None:
    assert not decode_add_reply(network_ok=True, payload={}).accepted
    assert not decode_add_reply(network_ok=False, payload={"id": 8}).accepted


def test_clear_treats_wrong_type_errors_as_an_empty_array() -> None:
    result = decode_clear_reply(network_ok=True, payload={"errors": "failure"})
    assert result.accepted
    assert result.malformed_errors_accepted
    assert not decode_clear_reply(network_ok=True, payload={"errors": ["failure"]}).accepted


def test_v2_packet_has_no_serial_uuid_revision_or_idempotency_key() -> None:
    serialized = serialize_v2_schedule(_schedule(), weekday_index=1)
    assert serialized.packet == {
        "is_enable": True,
        "type": 2,
        "start_time": "17:00",
        "heat_to": 20.0,
        "cool_to": 24.44444,
        "fan_on": False,
        "fan_hours": 30,
        "weekday": 1,
    }
    assert serialized.normalized_local["repeats"] == "Mon"
    assert {"sn", "_qsUuid", "revision", "idempotency_key"}.isdisjoint(serialized.packet)


def test_schedule_serializer_rejects_an_empty_day_selection() -> None:
    with pytest.raises(ValueError, match="repeat day"):
        serialize_v2_schedule(_schedule(repeats=""), weekday_index=1)


def test_new_schedule_expands_per_day_and_skips_only_full_days() -> None:
    existing = [_schedule(repeats="Mon", startTime=f"{hour:02}:00 AM") for hour in range(1, 13)]
    result = expand_new_schedule(_schedule(repeats="Mon, Tue"), existing)
    assert result.capacity_rejected_days == ("Mon",)
    assert [row["repeats"] for row in result.accepted] == ["Tue"]


def test_hold_type_is_a_two_bit_mask() -> None:
    value = add_hold(HoldType.NONE, HoldType.TEMPERATURE)
    value = add_hold(value, HoldType.FAN)
    assert value == HoldType.ALL
    assert remove_hold(value, HoldType.TEMPERATURE) == HoldType.FAN


def test_restored_holds_are_cleared_when_no_v2_activity_is_enabled() -> None:
    restored = normalize_restored_holds(
        schedules_v2=[_schedule(enable=False)],
        hold_type=HoldType.ALL,
        hold_period={"1": HoldPeriod.UNTIL_CHANGED, "2": HoldPeriod.UNTIL_CHANGED},
        hold_start_time={},
    )
    assert restored.cleared_for_no_enabled_activity
    assert (restored.hold_type, restored.hold_period, restored.hold_start_time) == (0, {}, {})


def test_restored_holds_survive_when_one_v2_activity_is_enabled() -> None:
    restored = normalize_restored_holds(
        schedules_v2=[_schedule(enable=True, repeats="Tu")],
        hold_type=HoldType.ALL,
        hold_period={"1": HoldPeriod.UNTIL_CHANGED, "2": HoldPeriod.UNTIL_CHANGED},
        hold_start_time={},
    )
    assert not restored.cleared_for_no_enabled_activity
    assert restored.hold_type == HoldType.ALL
    assert restored.hold_period == {
        "1": HoldPeriod.UNTIL_CHANGED,
        "2": HoldPeriod.UNTIL_CHANGED,
    }


def test_fixed_and_next_activity_hold_expiry() -> None:
    started = datetime(2026, 8, 10, 12, tzinfo=UTC)
    assert not hold_expired(
        HoldPeriod.TWO_HOURS, now=started + timedelta(minutes=119), started=started
    )
    assert hold_expired(HoldPeriod.TWO_HOURS, now=started + timedelta(hours=2), started=started)
    assert hold_expired(
        HoldPeriod.UNTIL_NEXT_ACTIVITY,
        now=started + timedelta(minutes=1),
        started=started,
        next_activity=None,
    )
    assert not hold_expired(
        HoldPeriod.UNTIL_CHANGED,
        now=started + timedelta(days=100),
        started=started,
    )


@pytest.mark.parametrize("delivery", [DeliveryState.DELIVERED, DeliveryState.UNKNOWN])
def test_delivered_or_ambiguous_mutation_is_never_automatically_retried(
    delivery: DeliveryState,
) -> None:
    assert not may_automatically_retry(delivery)


def test_proven_non_delivery_can_be_retried() -> None:
    assert may_automatically_retry(DeliveryState.NOT_DELIVERED)


def test_running_activity_is_latest_today_or_nearest_past_day() -> None:
    monday_morning = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
    wake = _schedule(id=1, repeats="Mo", startTime="06:00 AM")
    away = _schedule(id=2, repeats="Mo", startTime="08:00 AM")
    sunday = _schedule(id=3, repeats="Su", startTime="10:00 PM")
    result = find_running_activity([wake, sunday, away], now=monday_morning)
    assert result is not None
    assert result.schedule is away
    assert result.day_offset == 0

    before_wake = find_running_activity([wake, sunday, away], now=monday_morning.replace(hour=5))
    assert before_wake is not None
    assert before_wake.schedule is sunday
    assert before_wake.day_offset == -1


def test_running_activity_ignores_disabled_rows() -> None:
    now = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
    disabled = _schedule(enable=False, repeats="Mo", startTime="08:00 AM")
    assert find_running_activity([disabled], now=now) is None


def test_next_activity_walks_today_then_seven_future_days() -> None:
    monday = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
    current = _schedule(id=1, repeats="Mo", startTime="09:00 AM")
    later = _schedule(id=2, repeats="Mo", startTime="05:00 PM")
    tuesday = _schedule(id=3, repeats="Tu", startTime="06:00 AM")
    result = find_next_activity([tuesday, later, current], now=monday, current_schedule=current)
    assert result is not None
    assert result.schedule is later
    assert result.day_offset == 0

    after_later = find_next_activity(
        [tuesday, later, current],
        now=monday.replace(hour=23),
        current_schedule=later,
    )
    assert after_later is not None
    assert after_later.schedule is tuesday
    assert after_later.day_offset == 1


def test_v2_delete_retry_is_callable_but_uses_the_v1_default_route() -> None:
    initial = initial_v2_clear_call(42)
    retry = retry_v2_clear_call(42)
    assert (initial.version, initial.route_generation, initial.wrong_route) == (
        C_VERSION_2,
        "v2",
        False,
    )
    assert (retry.version, retry.route_generation, retry.wrong_route) == (
        C_VERSION_1,
        "v1",
        True,
    )


def test_known_explicit_hold_period_path_completes() -> None:
    result = emulate_add_hold_call(
        HoldType.NONE,
        HoldType.TEMPERATURE,
        period=HoldPeriod.TWO_HOURS,
    )
    assert result.hold_bits == HoldType.TEMPERATURE
    assert result.native_hold_written
    assert result.period_changed
    assert result.start_time_written
    assert result.server_push_attempted
    assert result.settings_saved


def test_omitted_hold_period_can_stop_after_setting_the_hold_bit() -> None:
    result = emulate_add_hold_call(
        HoldType.NONE,
        HoldType.TEMPERATURE,
        period=None,
    )
    assert result.hold_bits == HoldType.TEMPERATURE
    assert result.native_hold_written
    assert result.period_value is None
    assert not result.period_changed
    assert not result.start_time_written
    assert not result.server_push_attempted
    assert not result.settings_saved


def test_omitted_period_overwrites_an_existing_period_with_undefined() -> None:
    result = emulate_add_hold_call(
        HoldType.TEMPERATURE,
        HoldType.TEMPERATURE,
        period=None,
        existing_period=HoldPeriod.FOUR_HOURS,
    )
    assert result.hold_bits == HoldType.TEMPERATURE
    assert not result.native_hold_written
    assert result.period_changed
    assert result.period_value is None
    assert result.start_time_written
    assert result.server_push_attempted
    assert result.settings_saved
