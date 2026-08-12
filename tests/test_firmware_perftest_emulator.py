"""Independent checks for exact-1.5.8 performance-test behavior."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest

from scripts.emulate_firmware_perftest import (
    COMPLETE_SECONDS,
    COOLING_TARGET_C,
    HEATING_TARGET_C,
    POSTPONE_SECONDS,
    RUN_SECONDS,
    PerformanceTestRun,
    RelaySnapshot,
    RelayValue,
    ResultType,
    SystemMode,
    SystemType,
    TestState,
    auxiliary_heating_stage,
    build_result,
    cooling_stage,
    decode_eligibility,
    finalize_relays,
    heating_stage,
    inspect_saved_result,
    result_upload_disposition,
    schedule_next_check,
    target_temperature_c,
)


def test_next_check_uses_exact_qt_bounded_jitter_before_ten() -> None:
    now = datetime(2026, 8, 11, 8, 0, tzinfo=UTC)
    assert schedule_next_check(now, time(9), random32=0) == datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
    assert schedule_next_check(now, time(9), random32=0xFFFF_FFFF) == datetime(
        2026, 8, 11, 10, 14, 59, tzinfo=UTC
    )


def test_next_check_keeps_midmorning_exact_and_rolls_after_cutoff() -> None:
    now = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    assert schedule_next_check(now, time(10, 37), random32=0xFFFF_FFFF) == datetime(
        2026, 8, 11, 10, 37, tzinfo=UTC
    )
    assert schedule_next_check(now, time(11, 46), random32=0) == datetime(
        2026, 8, 12, 10, 0, tzinfo=UTC
    )


def test_eligibility_gates_id_action_system_type_and_saved_result() -> None:
    payload = {"perftest_id": 7, "action": "heating"}
    assert decode_eligibility(
        network_ok=True, payload=payload, system_type=SystemType.CONVENTIONAL
    ).send_running
    assert (
        decode_eligibility(
            network_ok=True, payload=payload, system_type=SystemType.COOLING_ONLY
        ).outcome
        == "incompatible"
    )
    assert (
        decode_eligibility(
            network_ok=True,
            payload=payload,
            system_type=SystemType.CONVENTIONAL,
            saved_test_id=7,
        ).outcome
        == "saved_result_pending"
    )
    assert (
        decode_eligibility(
            network_ok=True,
            payload=payload,
            system_type=SystemType.CONVENTIONAL,
            postponed=True,
        ).postpone_seconds
        == POSTPONE_SECONDS
    )
    assert (
        decode_eligibility(
            network_ok=True,
            payload={"perftest_id": 7, "action": "unknown"},
            system_type=SystemType.CONVENTIONAL,
        ).outcome
        == "none"
    )


def test_result_packet_uses_time_not_containing_set_time_literal() -> None:
    when = datetime(2026, 8, 11, 13, 14, 15, tzinfo=UTC)
    packet = build_result(
        test_id=7,
        serial="redacted",
        mode=SystemMode.COOLING,
        result=ResultType.FINISHED,
        when=when,
        readings=[],
    )
    assert packet == {
        "perftest_id": 7,
        "sn": "redacted",
        "action": "cooling",
        "result": "finished",
        "time": "2026-08-11 13:14:15",
        "data": [],
    }
    assert "set-time" not in packet


def test_nonfinished_results_omit_data_and_targets_are_exact() -> None:
    packet = build_result(
        test_id=8,
        serial="redacted",
        mode=SystemMode.HEATING,
        result=ResultType.RUNNING,
        when=datetime(2026, 8, 11, tzinfo=UTC),
        readings=[{"ignored": True}],
    )
    assert packet["action"] == "heating"
    assert "data" not in packet
    assert target_temperature_c(SystemMode.COOLING) == pytest.approx(COOLING_TARGET_C)
    assert target_temperature_c(SystemMode.HEATING) == pytest.approx(HEATING_TARGET_C)


def test_saved_result_retention_counts_calendar_midnights_and_accepts_future() -> None:
    now = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    base = {"sn": "redacted", "time": "2026-08-10 23:59:59"}
    assert inspect_saved_result(base, now=now, startup=True, saved_test_id_present=True).valid
    assert inspect_saved_result(
        {**base, "time": "2026-08-09 23:59:59"},
        now=now,
        startup=True,
        saved_test_id_present=True,
    ).remove_saved_keys
    assert inspect_saved_result(
        {**base, "time": "2026-07-12 12:00:00", "data": []},
        now=now,
        startup=True,
        saved_test_id_present=True,
    ).valid
    assert inspect_saved_result(
        {**base, "time": "2026-07-11 23:59:59", "data": []},
        now=now,
        startup=True,
        saved_test_id_present=True,
    ).remove_saved_keys
    assert inspect_saved_result(
        {**base, "time": "2026-08-12 12:00:00", "data": []},
        now=now,
        startup=True,
        saved_test_id_present=True,
    ).valid


def test_saved_result_startup_requires_id_and_invalid_time_removes_both_keys() -> None:
    now = datetime(2026, 8, 11, tzinfo=UTC)
    payload = {"sn": "redacted", "time": "not-a-time", "data": []}
    assert not inspect_saved_result(
        payload, now=now, startup=True, saved_test_id_present=False
    ).remove_saved_keys
    assert inspect_saved_result(
        payload, now=now, startup=True, saved_test_id_present=True
    ).remove_saved_keys


def test_result_callback_starts_running_even_when_running_upload_fails() -> None:
    failed_running = result_upload_disposition(result=ResultType.RUNNING, network_ok=False)
    assert failed_running.start_hardware_test
    assert failed_running.retry_saved_after_seconds is None
    failed_finished = result_upload_disposition(result=ResultType.FINISHED, network_ok=False)
    assert not failed_finished.start_hardware_test
    assert failed_finished.retry_saved_after_seconds == 300
    assert result_upload_disposition(result=ResultType.STOPPED, network_ok=True).clear_saved_result


def test_run_collects_sixty_fifteen_second_samples_then_completes() -> None:
    run = PerformanceTestRun(7, "redacted", SystemMode.COOLING)
    run.start_warmup()
    run.countdown_start(30_999)
    assert run.start_time_left == 30
    for _ in range(30):
        run.countdown_tick()
    assert run.state is TestState.WARMUP  # zero does not itself start Running
    run.start_running()
    assert run.test_time_left == RUN_SECONDS

    start = datetime(2026, 8, 11, tzinfo=UTC)
    for sample in range(60):
        completed = run.collect(
            temperature_f=40.0,
            when=start + timedelta(seconds=15 * (sample + 1)),
        )
    assert completed
    assert run.state is TestState.COMPLETE
    assert not run.is_test_running
    assert len(run.readings) == 60
    assert run.readings[-1]["temperature"] == pytest.approx(4.444444444444445)
    assert run.finish_time_left == COMPLETE_SECONDS
    assert len(run.finished_packet(when=start + timedelta(seconds=900))["data"]) == 60


def test_complete_counter_and_cancel_cleanup() -> None:
    run = PerformanceTestRun(7, "redacted", SystemMode.HEATING, state=TestState.COMPLETE)
    run.finish_time_left = 1
    assert not run.completion_tick()
    assert run.finish_time_left == 0
    assert run.completion_tick()
    assert run.state is TestState.IDLE

    run = PerformanceTestRun(7, "redacted", SystemMode.HEATING)
    run.start_warmup()
    run.readings.append({"private": "discard"})
    packet = run.cancel()
    assert packet["result"] == "stopped"
    assert run.state is TestState.IDLE
    assert run.readings == []


def test_relay_stage_methods_and_final_fan_arbitration() -> None:
    cooling = finalize_relays(
        cooling_stage(2),
        effective_mode=SystemMode.COOLING,
        ob_on_mode=SystemMode.COOLING,
    )
    assert (cooling.g, cooling.y1, cooling.y2, cooling.ob) == (
        RelayValue.ON,
        RelayValue.ON,
        RelayValue.ON,
        RelayValue.ON,
    )

    heat_pump = finalize_relays(
        heating_stage(2, heat_pump=True),
        effective_mode=SystemMode.HEATING,
        ob_on_mode=SystemMode.COOLING,
    )
    assert (heat_pump.g, heat_pump.y1, heat_pump.y2, heat_pump.ob) == (
        RelayValue.ON,
        RelayValue.ON,
        RelayValue.ON,
        RelayValue.OFF,
    )

    conventional = finalize_relays(
        heating_stage(3, heat_pump=False),
        effective_mode=SystemMode.HEATING,
        ob_on_mode=SystemMode.COOLING,
        thermostat_controls_heating_fan=False,
    )
    assert conventional.g is RelayValue.OFF
    assert (conventional.w1, conventional.w2, conventional.w3) == (
        RelayValue.ON,
        RelayValue.ON,
        RelayValue.ON,
    )


def test_aux_and_accessory_paths_are_not_a_fixed_safe_off_profile() -> None:
    assert auxiliary_heating_stage(1, argument=True).w3 is RelayValue.ON
    assert auxiliary_heating_stage(2, argument=False).w1 is RelayValue.OFF
    accessories = RelaySnapshot(acc1p=RelayValue.ON)
    finalized = finalize_relays(
        accessories,
        effective_mode=SystemMode.HEATING,
        ob_on_mode=SystemMode.COOLING,
    )
    assert finalized.acc1p is RelayValue.ON
    assert finalized.g is RelayValue.ON
