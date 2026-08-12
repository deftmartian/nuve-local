"""Independent checks for exact-1.5.8 legacy schedule recovery claims."""

from __future__ import annotations

import pytest

from scripts.emulate_firmware_schedule_v1 import (
    SystemMode,
    clock_second,
    evaluate_v1_activation,
    expand_v1_ranges,
    find_running_v1_schedule,
    find_v1_overlaps,
    migrate_v1_schedule_page,
    reconcile_v1_identity,
    serialize_v1_schedule,
    time_in_range,
)


def _schedule(mode: SystemMode) -> dict[str, object]:
    return {
        "enable": True,
        "name": "Weekday",
        "type": 2,
        "startTime": "06:00 AM",
        "endTime": "03:00 PM",
        "systemMode": mode,
        "minimumTemperature": 20.0,
        "maximumTemperature": 25.0,
        "humidity": 40,
        "dataSource": "local",
        "repeats": "Mon,Tue",
    }


def test_v1_auto_packet_uses_bounds_and_no_fan_revision_or_client_uuid() -> None:
    packet = serialize_v1_schedule(_schedule(SystemMode.AUTO))
    assert packet == {
        "is_enable": True,
        "name": "Weekday",
        "type_id": 2,
        "start_time": "06:00",
        "end_time": "15:00",
        "mode_id": 3,
        "auto_temp_low": 20.0,
        "auto_temp_high": 25.0,
        "humidity": 40,
        "dataSource": "local",
        "weekdays": ["Mon", "Tue"],
    }
    assert {"fan_on", "fan_hours", "revision", "_qsUuid", "schedule_id"}.isdisjoint(packet)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (SystemMode.COOLING, 25.0),
        (SystemMode.HEATING, 20.0),
    ],
)
def test_v1_single_mode_packet_uses_one_temp(mode: SystemMode, expected: float) -> None:
    packet = serialize_v1_schedule(_schedule(mode))
    assert packet["temp"] == expected
    assert "auto_temp_low" not in packet
    assert "auto_temp_high" not in packet


def test_v1_edit_or_wrong_type_preserves_without_refetch_mutation() -> None:
    local = [{"id": 4, "name": "Home"}]
    assert reconcile_v1_identity(local, [], schedule_editing=True).preserved
    assert reconcile_v1_identity(local, {"wrong": "type"}, schedule_editing=False).preserved


def test_v1_explicit_empty_array_clears_every_local_row() -> None:
    result = reconcile_v1_identity(
        [{"id": 4, "name": "Home"}, {"id": 5, "name": "Away"}],
        [],
        schedule_editing=False,
    )
    assert result.rows == ()
    assert result.removed_ids == (4, 5)


def test_v1_nonempty_server_removes_ids_absent_from_server_and_adds_new_ids() -> None:
    result = reconcile_v1_identity(
        [{"id": 4, "name": "Home"}, {"id": 5, "name": "Away"}],
        [{"schedule_id": 4, "name": "Home"}, {"schedule_id": 8, "name": "Night"}],
        schedule_editing=False,
    )
    assert result.removed_ids == (5,)
    assert [row["id"] for row in result.rows] == [4, 8]


def _range(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 1,
        "enable": True,
        "startTime": "06:00 AM",
        "endTime": "08:00 AM",
        "repeats": "Mo",
    }
    row.update(overrides)
    return row


def test_time_in_range_is_start_inclusive_end_exclusive_and_equal_is_wraparound() -> None:
    assert time_in_range(100, 100, 200)
    assert not time_in_range(200, 100, 200)
    assert time_in_range(0, 100, 100)
    assert time_in_range(100, 100, 100)


def test_equal_ui_minutes_become_a_59_second_range_not_an_all_day_row() -> None:
    segment = expand_v1_ranges((_range(startTime="06:00 AM", endTime="06:00 AM"),))[0]
    assert segment.start_second == clock_second("06:00 AM")
    assert segment.end_second == clock_second("06:00 AM", end_time=True)
    assert segment.end_second - segment.start_second == 59
    assert time_in_range(segment.start_second, segment.start_second, segment.end_second)
    assert not time_in_range(segment.end_second, segment.start_second, segment.end_second)


def test_overnight_row_splits_onto_the_next_repeat_day() -> None:
    segments = expand_v1_ranges((_range(startTime="10:00 PM", endTime="06:00 AM"),))
    actual = [
        (segment.running_days, segment.start_second, segment.end_second) for segment in segments
    ]
    assert actual == [
        (("Mo",), clock_second("10:00 PM"), 86_399),
        (("Tu",), 0, clock_second("06:00 AM", end_time=True)),
    ]


def test_overlap_is_strict_at_end_boundaries_and_crosses_midnight() -> None:
    existing = [_range(id=4, startTime="06:00 AM", endTime="08:00 AM")]
    assert (
        find_v1_overlaps(
            existing,
            _range(id=5, startTime="08:01 AM", endTime="09:00 AM"),
        )
        == ()
    )
    assert find_v1_overlaps(
        existing,
        _range(id=5, startTime="07:59 AM", endTime="09:00 AM"),
    ) == (4,)

    overnight = [_range(id=7, startTime="10:00 PM", endTime="06:00 AM")]
    assert find_v1_overlaps(
        overnight,
        _range(id=8, startTime="05:00 AM", endTime="07:00 AM", repeats="Tu"),
    ) == (7,)


def test_first_matching_expanded_row_wins() -> None:
    rows = [
        _range(id=4, startTime="06:00 AM", endTime="09:00 AM"),
        _range(id=5, startTime="07:00 AM", endTime="10:00 AM"),
    ]
    result = find_running_v1_schedule(
        rows,
        day="Mo",
        now_second=clock_second("08:00 AM"),
    )
    assert result is rows[0]


@pytest.mark.parametrize(
    "gate",
    [
        {"is_hold": True},
        {"system_mode": SystemMode.OFF},
        {"system_mode": SystemMode.EMERGENCY_HEAT},
        {"system_shutoff": True},
        {"performance_test_running": True},
    ],
)
def test_control_gates_suppress_legacy_activation(gate: dict[str, object]) -> None:
    assert (
        find_running_v1_schedule(
            [_range()],
            day="Mo",
            now_second=clock_second("07:00 AM"),
            **gate,  # type: ignore[arg-type]
        )
        is None
    )


def test_accepting_migration_deletes_without_conversion_and_queues_clear_all() -> None:
    result = migrate_v1_schedule_page([_range(id=-4), _range(id=8)], accepted=True, online=True)
    assert result.rows == ()
    assert result.destination == "v2"
    assert result.deleting_queue == (-2,)
    assert result.native_clear_calls == ((-2, 1),)
    assert result.detached_rows == 2
    assert result.saved
    assert not result.converted


def test_offline_or_local_only_migration_has_exact_queue_behavior() -> None:
    offline = migrate_v1_schedule_page([_range(id=8)], accepted=True, online=False)
    assert offline.deleting_queue == (-2,)
    assert offline.native_clear_calls == ()

    local_only = migrate_v1_schedule_page([_range(id=-4)], accepted=True, online=True)
    assert local_only.deleting_queue == ()
    assert local_only.native_clear_calls == ()


def test_rejecting_migration_preserves_rows_and_opens_legacy_page() -> None:
    rows = [_range(id=8)]
    result = migrate_v1_schedule_page(rows, accepted=False, online=True)
    assert result.rows == tuple(rows)
    assert result.destination == "v1"
    assert result.deleting_queue == ()
    assert not result.saved


def test_nonrepeating_row_activates_once_then_disables_after_its_range() -> None:
    row = _range(id=17, repeats="", active=False)
    before = evaluate_v1_activation([row], day="Mo", now_second=clock_second("05:00 AM"))
    assert before.selected_id is None
    assert before.rows[0]["enable"]
    assert not before.rows[0]["active"]

    running = evaluate_v1_activation([row], day="Mo", now_second=clock_second("07:00 AM"))
    assert running.selected_id == 17
    assert running.activated_id == 17
    assert running.rows[0]["active"]

    ended = evaluate_v1_activation([running.rows[0]], day="Mo", now_second=clock_second("09:00 AM"))
    assert ended.selected_id is None
    assert ended.disabled_ids == (17,)
    assert not ended.rows[0]["enable"]
    assert not ended.rows[0]["active"]


def test_active_nonrepeating_overnight_row_is_disabled_after_midnight() -> None:
    row = _range(
        id=18,
        repeats="",
        active=True,
        startTime="10:00 PM",
        endTime="06:00 AM",
    )
    result = evaluate_v1_activation([row], day="Tu", now_second=clock_second("02:00 AM"))
    assert result.selected_id is None
    assert result.activated_id is None
    assert result.disabled_ids == (18,)
    assert not result.rows[0]["enable"]


def test_control_gate_clears_activation_after_row_active_flags_are_updated() -> None:
    row = _range(id=19, active=False)
    result = evaluate_v1_activation(
        [row],
        day="Mo",
        now_second=clock_second("07:00 AM"),
        system_mode=SystemMode.OFF,
    )
    assert result.selected_id == 19
    assert result.activated_id is None
    assert result.rows[0]["active"]
