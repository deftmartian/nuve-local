"""Tests for push state and liveness behavior."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import custom_components.nuve_local.runtime as runtime_module
from custom_components.nuve_local.models import NuveMode, NuveState, NuveSystemType
from custom_components.nuve_local.runtime import (
    CommandOutcomeUncertainError,
    CommandTimeoutError,
    ControlNotReadyError,
    ControlStateChangedError,
    NuveRuntime,
    PersistenceUnavailableError,
    RuntimeStoppedError,
    UncertainCommand,
)
from tests.helpers import attach_memory_persistence, settings_upload


def _settings() -> dict[str, object]:
    return settings_upload("00-000-000000")


async def _ready_runtime(*, timeout: float = 0.2) -> NuveRuntime:
    runtime = NuveRuntime(
        serial="00-000-000000",
        control_enabled=True,
        paired=True,
        command_timeout_seconds=timeout,
        bootstrap_firmware_version="1.5.7.4",
        bootstrap_technician_url="https://contractor.invalid/preserved",
        bootstrap_metadata_confirmed=True,
        bootstrap_no_update_confirmed=True,
        temp_correction_version=1,
    )
    attach_memory_persistence(runtime)
    now = datetime.now(UTC)
    runtime.async_accept_settings_snapshot(_settings(), received_at=now)
    runtime.async_accept_auto_mode_snapshot(
        {
            "auto_temp_low": 19.0,
            "auto_temp_high": 23.0,
            "is_active": False,
            "mode": "heating",
        },
        received_at=now,
    )
    runtime.async_note_authenticated_contact(now)
    runtime.async_set_outdoor_temperature(10.0, "Test outdoor", observed_at=now)
    await runtime.async_process_monitor_state(
        NuveState(
            available=True,
            last_seen=now,
            sample_time=now,
            monitor_is_sync=True,
            current_temperature=21.2,
            target_temperature=21.5,
            target_humidity=40.0,
            auto_temperature_low=19.0,
            auto_temperature_high=23.0,
            system_type=NuveSystemType.HEAT_PUMP,
            mode=NuveMode.HEAT,
            schedule_type=9,
            records_received=1,
        )
    )
    await runtime.async_get_settings_response(requested_at=now)
    return runtime


def test_authenticated_contact_and_expiry_notify_subscribers() -> None:
    async def scenario() -> None:
        runtime = NuveRuntime(serial="00-000-000000")
        notifications = 0

        def listener() -> None:
            nonlocal notifications
            notifications += 1

        runtime.async_subscribe(listener)
        seen_at = datetime(2026, 8, 9, tzinfo=UTC)
        runtime.async_note_authenticated_contact(seen_at)
        assert runtime.state.available is True
        assert runtime.state.last_seen == seen_at

        runtime._async_mark_unavailable()
        assert runtime.state.available is False
        assert notifications == 2
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_monitor_freshness_allows_firmware_hourly_full_snapshot_cadence() -> None:
    now = datetime.now(UTC)
    runtime = NuveRuntime(
        serial="00-000-000000",
        last_monitor_upload=now - timedelta(minutes=69),
        state=NuveState(
            sample_time=now - timedelta(minutes=69),
            records_received=1,
        ),
    )
    assert runtime.monitor_is_fresh is True

    runtime.last_monitor_upload = now - timedelta(minutes=71)
    runtime.state = replace(
        runtime.state,
        sample_time=now - timedelta(minutes=71),
    )
    assert runtime.monitor_is_fresh is False


def test_monitor_updates_merge_without_erasing_prior_fields() -> None:
    async def scenario() -> None:
        prior = datetime.now(UTC) - timedelta(seconds=1)
        runtime = NuveRuntime(
            serial="00-000-000000",
            state=NuveState(
                sample_time=prior,
                target_temperature=22.0,
                auto_temperature_low=18.0,
                raw_varints={9: 1},
                records_received=2,
            ),
        )
        attach_memory_persistence(runtime)
        now = datetime.now(UTC)

        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                current_temperature=21.5,
                raw_fixed32={2: 21.5},
                records_received=3,
            )
        )

        assert runtime.state.current_temperature == 21.5
        assert runtime.state.target_temperature == 22.0
        assert runtime.state.auto_temperature_low == 18.0
        assert runtime.state.raw_varints == {9: 1}
        assert runtime.state.records_received == 5
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_settings_command_retries_identically_and_waits_for_telemetry(monkeypatch: Any) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime()
        original_target = runtime.state.target_temperature
        command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)

        first = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        second = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        assert first["temp"] == 22.0
        assert first["setting"]["command"] == "push_live_data"
        assert second == first
        assert runtime.state.target_temperature == original_target
        assert not command.done()

        upload = _settings()
        upload["temp"] = 22.0
        runtime.async_accept_settings_snapshot(upload, received_at=datetime.now(UTC))
        assert not command.done()

        await asyncio.sleep(0.002)
        confirmed_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=confirmed_at,
                sample_time=confirmed_at,
                monitor_is_sync=True,
                current_temperature=21.2,
                target_temperature=22.00001,
                target_humidity=40.0,
                auto_temperature_low=19.0,
                auto_temperature_high=23.0,
                system_type=NuveSystemType.HEAT_PUMP,
                mode=NuveMode.HEAT,
                schedule_type=9,
                records_received=1,
            )
        )
        await command
        assert runtime.state.target_temperature == pytest.approx(22.00001)
        assert runtime.command_status == "idle"
        assert runtime.live_data_command_time == first["setting"]["last_update"]
        canonical = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        assert canonical["setting"]["command_time"] == first["setting"]["last_update"]
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_consecutive_settings_commands_keep_full_authority_after_coherent_echo(
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime()
        prior_upload = runtime.last_settings_upload

        for target in (22.0, 21.0):
            command = asyncio.create_task(runtime.async_request_settings_change({"temp": target}))
            await asyncio.sleep(0)
            delivered = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
            assert delivered["temp"] == target
            assert runtime.uncertain_command is not None

            await asyncio.sleep(0.002)
            upload = copy.deepcopy(runtime.settings_snapshot)
            assert upload is not None
            upload["temp"] = target
            runtime.async_accept_settings_snapshot(
                upload,
                received_at=datetime.now(UTC),
            )
            assert runtime.authoritative_control_monitor_seen is True
            assert runtime.last_settings_upload == prior_upload
            assert not command.done()

            await asyncio.sleep(0.002)
            confirmed_at = datetime.now(UTC)
            await runtime.async_process_monitor_state(
                NuveState(
                    available=True,
                    last_seen=confirmed_at,
                    sample_time=confirmed_at,
                    target_temperature=target,
                    records_received=1,
                )
            )
            await command
            assert runtime.state.target_temperature == target
            assert runtime.authoritative_control_monitor_seen is True
            assert runtime.can_enable_control is True
            assert runtime.control_ready is True

        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_consecutive_auto_commands_keep_full_authority_after_coherent_echo(
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime()
        prior_upload = runtime.last_auto_mode_upload

        for changes in ({"auto_temp_low": 20.0}, {"auto_temp_high": 24.0}):
            command = asyncio.create_task(runtime.async_request_auto_mode_change(changes))
            await asyncio.sleep(0)
            delivered = await runtime.async_get_auto_mode_response(requested_at=datetime.now(UTC))
            assert all(delivered[key] == value for key, value in changes.items())
            assert runtime.uncertain_command is not None

            await asyncio.sleep(0.002)
            upload = copy.deepcopy(runtime.auto_mode_snapshot)
            assert upload is not None
            upload.update(changes)
            runtime.async_accept_auto_mode_snapshot(
                {**upload, "is_active": False, "mode": "heating"},
                received_at=datetime.now(UTC),
            )
            assert runtime.authoritative_control_monitor_seen is True
            assert runtime.last_auto_mode_upload == prior_upload
            assert not command.done()

            await asyncio.sleep(0.002)
            confirmed_at = datetime.now(UTC)
            await runtime.async_process_monitor_state(
                NuveState(
                    available=True,
                    last_seen=confirmed_at,
                    sample_time=confirmed_at,
                    auto_temperature_low=changes.get("auto_temp_low"),
                    auto_temperature_high=changes.get("auto_temp_high"),
                    records_received=1,
                )
            )
            await command
            assert runtime.authoritative_control_monitor_seen is True
            assert runtime.can_enable_control is True
            assert runtime.control_ready is True

        trace = runtime.sanitized_event_trace
        block_reasons = [
            item["result"] for item in trace if item["event"] == "control_block_reason"
        ]
        assert "command_queued_awaiting_fetch" in block_reasons
        assert "command_delivered_awaiting_confirmation" in block_reasons
        assert block_reasons[-1] == "ready"
        assert any(
            item["event"] == "upload_echo"
            and item["family"] == "auto"
            and item["result"] == "expected_command"
            for item in trace
        )
        completed = [
            item for item in trace if item["event"] == "command" and item["result"] == "confirmed"
        ]
        assert len(completed) == 2
        assert all(isinstance(item["duration_ms"], int) for item in completed)
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_same_second_monitor_confirms_after_coherent_post_delivery_echo(
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime()
        command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)
        delivered_at = datetime.now(UTC) - timedelta(seconds=1)
        runtime.last_settings_upload = delivered_at - timedelta(seconds=1)
        runtime.state = replace(
            runtime.state,
            sample_time=delivered_at.replace(microsecond=0) - timedelta(seconds=1),
        )
        await runtime.async_get_settings_response(requested_at=delivered_at)

        echo_received_at = delivered_at + timedelta(milliseconds=50)
        upload = copy.deepcopy(runtime.settings_snapshot)
        assert upload is not None
        upload["temp"] = 22.0
        runtime.async_accept_settings_snapshot(upload, received_at=echo_received_at)
        pending = runtime._pending_command
        assert pending is not None
        assert pending.coherent_echo_received_at == echo_received_at

        sample_time = delivered_at.replace(microsecond=0)
        monitor_received_at = echo_received_at + timedelta(milliseconds=50)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=monitor_received_at,
                sample_time=sample_time,
                target_temperature=22.0,
                records_received=1,
            )
        )

        await command
        assert runtime.state.target_temperature == 22.0
        assert runtime.uncertain_command is None
        assert runtime.control_ready is True
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_same_second_monitor_without_post_delivery_echo_remains_unconfirmed(
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime(timeout=0.01)
        command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)
        delivered_at = datetime.now(UTC) - timedelta(seconds=1)
        runtime.state = replace(
            runtime.state,
            sample_time=delivered_at.replace(microsecond=0) - timedelta(seconds=1),
        )
        await runtime.async_get_settings_response(requested_at=delivered_at)

        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=delivered_at + timedelta(milliseconds=100),
                sample_time=delivered_at.replace(microsecond=0),
                target_temperature=22.0,
                records_received=1,
            )
        )

        with pytest.raises(CommandOutcomeUncertainError):
            await command
        assert runtime.uncertain_command is not None
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_uncertainty_error_wins_over_generic_readiness_failure() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        runtime.authoritative_control_monitor_seen = False
        runtime.uncertain_command = UncertainCommand(
            kind="settings",
            desired={"temp": 22.0},
            delivered_at=datetime.now(UTC),
        )

        with pytest.raises(CommandOutcomeUncertainError):
            await runtime.async_request_settings_change({"temp": 22.0})
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_post_delivery_settings_echo_with_unrelated_drift_revokes_authority(
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime()
        command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)
        await runtime.async_get_settings_response(requested_at=datetime.now(UTC))

        await asyncio.sleep(0.002)
        upload = copy.deepcopy(runtime.settings_snapshot)
        assert upload is not None
        upload["temp"] = 22.0
        upload["system"]["heat_min_on_time"] = 6.0
        changed_at = datetime.now(UTC)
        runtime.async_accept_settings_snapshot(upload, received_at=changed_at)

        assert runtime.authoritative_control_monitor_seen is False
        assert runtime.last_settings_upload == changed_at
        assert runtime.can_enable_control is False
        await runtime.async_shutdown()
        with pytest.raises(RuntimeStoppedError):
            await command

    asyncio.run(scenario())


def test_fan_command_confirms_from_durable_post_delivery_full_settings_upload() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        desired_fan = {"mode": 1, "workingPerHour": 40}
        command = asyncio.create_task(runtime.async_request_settings_change({"fan": desired_fan}))
        await asyncio.sleep(0)

        response = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        assert response["fan"] == desired_fan
        assert runtime.uncertain_command is not None
        assert not command.done()

        await asyncio.sleep(0.002)
        received_at = datetime.now(UTC)
        upload = _settings()
        upload["fan"] = desired_fan
        revision, candidate = runtime.prepare_settings_snapshot(upload, received_at=received_at)
        assert "uncertain_command" not in candidate
        runtime.async_accept_settings_snapshot(
            upload,
            received_at=received_at,
            prepared_revision=revision,
        )

        await command
        assert runtime.settings_snapshot is not None
        assert runtime.settings_snapshot["fan"] == desired_fan
        assert runtime.uncertain_command is None
        assert runtime.authoritative_control_monitor_seen is True
        assert runtime.can_enable_control is True
        await runtime.async_shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "changes",
    [
        {"temp": 22.0},
        {"mode_id": 5},
        {"fan": {"mode": 1, "workingPerHour": 40}},
        {"backlight": {"on": False}},
        {"settings": {"brightness": 99}},
    ],
)
def test_settings_commands_fail_closed_while_schedule_active(
    changes: dict[str, Any],
) -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        runtime.state = replace(runtime.state, schedule_type=2)

        with pytest.raises(ControlNotReadyError):
            await runtime.async_request_settings_change(changes)

        assert runtime._pending_command is None
        assert runtime.uncertain_command is None
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_settings_command_is_withdrawn_if_schedule_activates_before_fetch() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)
        runtime.state = replace(runtime.state, schedule_type=2)

        response = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))

        assert not {
            "temp",
            "mode_id",
            "fan",
            "system",
            "schedule",
            "schedule2",
        }.intersection(response)
        with pytest.raises(ControlNotReadyError):
            await command
        assert runtime._pending_command is None
        assert runtime.uncertain_command is None
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_active_schedule_poll_uses_nonapplying_preservation_response() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        runtime.state = replace(runtime.state, schedule_type=1)
        expected_command_time = runtime.live_data_command_time

        response = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))

        assert response["hold"] is False
        assert response["hold_period"] == {}
        assert response["setting"]["command"] == "push_live_data"
        assert response["setting"]["command_time"] == expected_command_time
        assert not {
            "temp",
            "mode_id",
            "fan",
            "system",
            "schedule",
            "schedule2",
        }.intersection(response)
        assert runtime.control_ready is True
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_active_schedule_upload_does_not_replace_effective_monitor_target() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        runtime.state = replace(
            runtime.state,
            schedule_type=1,
            target_temperature=24.0,
        )
        upload = _settings()
        upload["temp"] = 22.0

        runtime.async_accept_settings_snapshot(upload, received_at=datetime.now(UTC))

        assert runtime.settings_snapshot is not None
        assert runtime.settings_snapshot["temp"] == 22.0
        assert runtime.state.target_temperature == 24.0

        response = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        assert not {
            "temp",
            "mode_id",
            "fan",
            "system",
            "schedule",
            "schedule2",
        }.intersection(response)
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_fan_command_fails_closed_without_schedule_authority() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        runtime.state = replace(runtime.state, schedule_type=None)

        with pytest.raises(ControlNotReadyError):
            await runtime.async_request_settings_change({"fan": {"mode": 1, "workingPerHour": 40}})

        assert runtime._pending_command is None
        assert runtime.uncertain_command is None
        await runtime.async_shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fan",
    [
        {"mode": 3, "workingPerHour": 30},
        {"mode": 1, "workingPerHour": 9},
        {"mode": 1, "workingPerHour": 61},
        {"mode": 1, "workingPerHour": 30.5},
        {"mode": True, "workingPerHour": 30},
    ],
)
def test_fan_command_rejects_values_outside_exact_firmware_contract(
    fan: dict[str, object],
) -> None:
    with pytest.raises(ControlNotReadyError):
        NuveRuntime._validated_settings_changes({"fan": fan})


def test_command_boundaries_reject_unproven_fractional_celsius_setpoints() -> None:
    with pytest.raises(ControlNotReadyError):
        NuveRuntime._validated_settings_changes({"temp": 21.5})
    with pytest.raises(ControlNotReadyError):
        NuveRuntime._validated_auto_changes({"auto_temp_low": 19.5})


def test_post_queue_local_settings_change_is_rebased_instead_of_overwritten(
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime()
        command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0.002)
        changed_at = datetime.now(UTC)

        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=changed_at,
                sample_time=changed_at,
                target_temperature=20.5,
                records_received=1,
            )
        )

        with pytest.raises(ControlStateChangedError):
            await command
        assert runtime.settings_snapshot is not None
        assert runtime.settings_snapshot["temp"] == 20.5
        assert runtime.uncertain_outcome is False
        response = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        assert response["temp"] == 20.5
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_post_queue_matching_monitor_completes_without_delivery(monkeypatch: Any) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime()
        command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0.002)
        changed_at = datetime.now(UTC)

        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=changed_at,
                sample_time=changed_at,
                target_temperature=22.0,
                records_received=1,
            )
        )

        await command
        assert runtime.settings_snapshot is not None
        assert runtime.settings_snapshot["temp"] == 22.0
        assert runtime.uncertain_outcome is False
        assert runtime.command_status == "idle"
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_post_queue_matching_auto_monitor_completes_without_delivery(monkeypatch: Any) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime()
        await runtime.async_get_auto_mode_response(requested_at=datetime.now(UTC))
        command = asyncio.create_task(
            runtime.async_request_auto_mode_change({"auto_temp_low": 20.0})
        )
        await asyncio.sleep(0.002)
        changed_at = datetime.now(UTC)

        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=changed_at,
                sample_time=changed_at,
                auto_temperature_low=20.0,
                records_received=1,
            )
        )

        await command
        assert runtime.auto_mode_snapshot == {
            "auto_temp_low": 20.0,
            "auto_temp_high": 23.0,
        }
        assert runtime.uncertain_outcome is False
        assert runtime.command_status == "idle"
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_nonzero_queue_skew_barrier_rejects_early_monitor_evidence(
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 2)
        runtime = await _ready_runtime()
        command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)
        pending = runtime._pending_command
        assert pending is not None

        early_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=early_at,
                sample_time=early_at,
                target_temperature=22.0,
                records_received=1,
            )
        )
        assert not command.done()
        assert runtime.settings_snapshot is not None
        assert runtime.settings_snapshot["temp"] == 21.5

        pending.queued_at -= timedelta(seconds=3)
        accepted_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=accepted_at,
                sample_time=accepted_at,
                target_temperature=22.0,
                records_received=1,
            )
        )
        await command
        assert runtime.settings_snapshot["temp"] == 22.0
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_response_sender_disconnect_retains_write_ahead_uncertainty(
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime(timeout=0.05)
        command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)

        async def disconnected_sender(body: dict[str, Any]) -> None:
            assert body["temp"] == 22.0
            raise ConnectionResetError("synthetic client disconnect")

        with pytest.raises(ConnectionResetError):
            await runtime.async_get_settings_response(
                requested_at=datetime.now(UTC), response_sender=disconnected_sender
            )
        assert runtime.uncertain_command is not None
        assert runtime.uncertain_command.delivered_at is None
        assert runtime.command_status == "delivered"
        with pytest.raises(CommandOutcomeUncertainError):
            await command
        assert runtime.uncertain_command is not None
        assert runtime.uncertain_command.delivered_at is None
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_post_queue_local_auto_change_is_rebased_instead_of_overwritten(
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime()
        await runtime.async_get_auto_mode_response(requested_at=datetime.now(UTC))
        command = asyncio.create_task(
            runtime.async_request_auto_mode_change({"auto_temp_low": 20.0})
        )
        await asyncio.sleep(0.002)
        changed_at = datetime.now(UTC)

        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=changed_at,
                sample_time=changed_at,
                auto_temperature_low=18.5,
                records_received=1,
            )
        )

        with pytest.raises(ControlStateChangedError):
            await command
        assert runtime.auto_mode_snapshot == {
            "auto_temp_low": 18.5,
            "auto_temp_high": 23.0,
        }
        assert runtime.uncertain_outcome is False
        response = await runtime.async_get_auto_mode_response(requested_at=datetime.now(UTC))
        assert response["auto_temp_low"] == 18.5
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_settings_confirmation_preserves_newer_device_state_and_delivery_payload(
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime()
        command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)
        delivered_at = datetime.now(UTC)
        first = await runtime.async_get_settings_response(requested_at=delivered_at)

        assert runtime.settings_snapshot is not None
        system = dict(runtime.settings_snapshot["system"])
        system["heat_min_on_time"] = 6.0
        await asyncio.sleep(0.002)
        runtime.async_accept_partial_settings("system", system, received_at=datetime.now(UTC))
        await asyncio.sleep(0.002)
        changed_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=changed_at,
                sample_time=changed_at,
                target_temperature=21.5,
                mode=NuveMode.COOL,
                records_received=1,
            )
        )

        retry = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        assert retry == first
        assert not command.done()

        await asyncio.sleep(0.002)
        confirmed_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=confirmed_at,
                sample_time=confirmed_at,
                target_temperature=22.0,
                records_received=1,
            )
        )
        await command
        assert runtime.settings_snapshot is not None
        assert runtime.settings_snapshot["temp"] == 22.0
        assert runtime.settings_snapshot["mode_id"] == int(NuveMode.COOL)
        assert runtime.settings_snapshot["system"]["heat_min_on_time"] == 6.0
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_auto_confirmation_preserves_newer_bound_and_immutable_delivery(
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime()
        await runtime.async_get_auto_mode_response(requested_at=datetime.now(UTC))
        command = asyncio.create_task(
            runtime.async_request_auto_mode_change({"auto_temp_low": 20.0})
        )
        await asyncio.sleep(0)
        delivered_at = datetime.now(UTC)
        first = await runtime.async_get_auto_mode_response(requested_at=delivered_at)

        await asyncio.sleep(0.002)
        changed_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=changed_at,
                sample_time=changed_at,
                auto_temperature_high=24.0,
                records_received=1,
            )
        )
        retry = await runtime.async_get_auto_mode_response(requested_at=datetime.now(UTC))
        assert retry == first

        await asyncio.sleep(0.002)
        runtime.async_accept_auto_mode_snapshot(
            {
                "auto_temp_low": 19.0,
                "auto_temp_high": 24.0,
                "is_active": False,
                "mode": "heating",
            },
            received_at=datetime.now(UTC),
        )
        await asyncio.sleep(0.002)
        confirmed_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=confirmed_at,
                sample_time=confirmed_at,
                monitor_is_sync=True,
                current_temperature=21.2,
                target_temperature=21.5,
                auto_temperature_low=20.0,
                auto_temperature_high=24.0,
                mode=NuveMode.HEAT,
                schedule_type=9,
                records_received=1,
            )
        )
        await command
        assert runtime.auto_mode_snapshot == {
            "auto_temp_low": 20.0,
            "auto_temp_high": 24.0,
        }
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_command_timeout_distinguishes_not_delivered_from_uncertain() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime(timeout=0.01)
        persisted = attach_memory_persistence(runtime)
        runtime.last_settings_poll = None
        runtime.last_auto_mode_poll = None

        # A prior poll is not authority and must not create a narrow command
        # window. Fresh canonical monitor state permits queueing; without a new
        # authenticated device fetch, the command remains entirely local and
        # times out without an uncertainty journal.
        assert runtime.can_enable_control is True
        assert runtime.control_ready is True
        with pytest.raises(CommandTimeoutError):
            await runtime.async_request_settings_change({"temp": 22.0})
        assert runtime.uncertain_outcome is False
        assert runtime.settings_snapshot is not None
        assert runtime.settings_snapshot["temp"] == 21.5

        task = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)
        assert runtime._pending_command is not None
        assert runtime._pending_command.delivered is False
        assert runtime.uncertain_command is None
        await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        with pytest.raises(CommandOutcomeUncertainError):
            await task
        assert runtime.uncertain_outcome is True
        assert persisted[-1]["uncertain_command"]["kind"] == "settings"

        runtime.async_accept_settings_snapshot(_settings(), received_at=datetime.now(UTC))
        assert runtime.uncertain_outcome is True
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_full_monitor_sync_resets_missing_monitor_fields() -> None:
    async def scenario() -> None:
        prior = datetime.now(UTC) - timedelta(seconds=1)
        runtime = NuveRuntime(
            serial="00-000-000000",
            state=NuveState(
                sample_time=prior,
                current_temperature=21.0,
                target_humidity=45.0,
                raw_fixed32={3: 45.0, 4: 21.0},
            ),
        )
        attach_memory_persistence(runtime)
        now = datetime.now(UTC)

        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                monitor_is_sync=True,
                current_temperature=22.0,
                raw_fixed32={4: 22.0},
                records_received=1,
            )
        )

        assert runtime.state.current_temperature == 22.0
        assert runtime.state.target_humidity is None
        assert runtime.state.raw_fixed32 == {4: 22.0}
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_explicit_bootstrap_unlocks_fetch_without_inventing_settings() -> None:
    async def scenario() -> None:
        runtime = NuveRuntime(
            serial="00-000-000000",
            paired=True,
            state=NuveState(available=True),
            bootstrap_firmware_version="1.5.7.4",
            bootstrap_technician_url="https://contractor.invalid/preserved",
            bootstrap_metadata_confirmed=True,
            bootstrap_no_update_confirmed=True,
        )
        attach_memory_persistence(runtime)
        now = datetime.now(UTC)
        runtime.last_monitor_upload = now
        runtime.state = NuveState(
            available=True, last_seen=now, sample_time=now, records_received=1
        )

        await runtime.async_arm_baseline_bootstrap(armed_at=now)
        settings = await runtime.async_get_settings_response(requested_at=now)
        auto = await runtime.async_get_auto_mode_response(requested_at=now)

        assert runtime.bootstrap_status == "fetch_unlocked"
        assert settings["hold"] is False
        assert settings["hold_period"] == {}
        assert settings["setting"] == {"last_update": settings["setting"]["last_update"]}
        assert auto["auto_temp_low"] == {}
        assert auto["auto_temp_high"] == {}
        assert not runtime.has_settings_baseline
        assert await runtime.async_get_settings_response(requested_at=now) == {}
        assert await runtime.async_get_auto_mode_response(requested_at=now) == {}

        runtime.async_accept_settings_snapshot(_settings(), received_at=now + timedelta(seconds=1))
        assert runtime.bootstrap_status == "complete"
        assert runtime.has_settings_baseline
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_private_baselines_restore_without_marking_device_available() -> None:
    async def scenario() -> None:
        source = await _ready_runtime()
        now = datetime.now(UTC)
        await source.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                monitor_is_sync=True,
                auto_temperature_low=19.0,
                auto_temperature_high=23.0,
            )
        )
        persisted = source.persistent_baselines()

        restored = NuveRuntime(serial="00-000-000000", paired=True)
        restored.async_restore_persistent_baselines(persisted)

        assert restored.has_settings_baseline
        assert restored.has_auto_mode_baseline
        assert restored.state.target_temperature == 21.5
        assert restored.state.current_temperature is None
        assert restored.state.current_humidity is None
        assert restored.current_temperature_observed_at is None
        assert restored.current_temperature_source is None
        assert restored.state.auto_temperature_low == 19.0
        assert restored.state.auto_temperature_high == 23.0
        assert restored.state.available is False
        assert restored.live_data_command_time == restored.settings_revision
        await source.async_shutdown()
        await restored.async_shutdown()

    asyncio.run(scenario())


def test_room_temperature_uses_newest_observation_across_upload_families() -> None:
    async def scenario() -> None:
        runtime = NuveRuntime(serial="00-000-000000")
        monitor_time = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=monitor_time,
                sample_time=monitor_time,
                current_temperature=24.0,
                records_received=1,
            )
        )
        assert runtime.current_temperature_source == "monitor"

        sensor_time = monitor_time + timedelta(seconds=2)
        runtime.async_accept_current_sensors(
            {"current_temp": "22", "current_humidity": "55", "co2_id": 1},
            received_at=sensor_time,
        )
        assert runtime.state.current_temperature == 22.0
        assert runtime.current_temperature_source == "current_sensors"

        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=sensor_time + timedelta(seconds=1),
                sample_time=monitor_time + timedelta(seconds=1),
                current_temperature=24.0,
                records_received=1,
            )
        )
        assert runtime.state.current_temperature == 22.0
        assert runtime.current_temperature_source == "current_sensors"

        newest_monitor_time = sensor_time + timedelta(seconds=2)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=newest_monitor_time,
                sample_time=newest_monitor_time,
                current_temperature=21.5,
                records_received=1,
            )
        )
        assert runtime.state.current_temperature == 21.5
        assert runtime.current_temperature_observed_at == newest_monitor_time
        assert runtime.current_temperature_source == "monitor"
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_nullable_write_ahead_uncertainty_restores_fail_closed() -> None:
    async def scenario() -> None:
        source = await _ready_runtime()
        persisted = source.persistent_baselines()
        persisted["uncertain_command"] = {
            "kind": "settings",
            "desired": {"temp": 22.0},
            "delivered_at": None,
            "revision": "2026-08-09 03:00:00",
        }

        restored = NuveRuntime(serial="00-000-000000", paired=True)
        restored.async_restore_persistent_baselines(persisted)

        assert restored.uncertain_kind == "settings"
        assert restored.uncertain_command is not None
        assert restored.uncertain_command.delivered_at is None
        assert restored.can_enable_control is False
        await source.async_shutdown()
        await restored.async_shutdown()

    asyncio.run(scenario())


def test_restored_baselines_require_post_start_full_control_telemetry() -> None:
    async def scenario() -> None:
        source = await _ready_runtime()
        persisted = source.persistent_baselines()
        await source.async_shutdown()

        restored = NuveRuntime(
            serial="00-000-000000",
            control_enabled=True,
            paired=True,
            bootstrap_firmware_version="1.5.7.4",
            bootstrap_technician_url="https://contractor.invalid/preserved",
            contractor_url="https://deftmartian.dev",
            bootstrap_metadata_confirmed=True,
            bootstrap_no_update_confirmed=True,
            temp_correction_version=1,
        )
        attach_memory_persistence(restored)
        restored.async_restore_persistent_baselines(persisted)
        now = datetime.now(UTC)
        restored.async_note_authenticated_contact(now)
        restored.async_set_outdoor_temperature(10.0, "Test outdoor", observed_at=now)

        await restored.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                current_temperature=21.2,
                records_received=1,
            )
        )
        reset = await restored.async_get_settings_response(requested_at=now)
        assert set(reset) == {
            "sn",
            "hold",
            "hold_period",
            "setting",
            "qr_url",
            "messages",
        }
        assert reset["hold_period"] == {}
        assert set(reset["setting"]) == {"last_update"}
        assert reset["qr_url"] == "https://deftmartian.dev"

        wake = await restored.async_get_settings_response(requested_at=now)
        assert set(wake) == set(reset)
        assert wake["hold_period"] == {}
        assert wake["setting"]["command"] == "push_live_data"
        assert wake["setting"]["command_time"] > wake["setting"]["last_update"]
        assert wake["qr_url"] == "https://deftmartian.dev"
        auto_companion = await restored.async_get_auto_mode_response(requested_at=now)
        assert auto_companion == {
            "last_update": restored.auto_mode_revision,
            "auto_temp_low": {},
            "auto_temp_high": {},
        }
        assert await restored.async_get_auto_mode_response(requested_at=now) == {}
        assert restored.authoritative_control_monitor_seen is False
        assert restored.can_enable_control is False

        await asyncio.sleep(0.002)
        full_at = datetime.now(UTC)
        await restored.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=full_at,
                sample_time=full_at,
                monitor_is_sync=True,
                current_temperature=21.2,
                target_temperature=21.5,
                target_humidity=40.0,
                auto_temperature_low=19.0,
                auto_temperature_high=23.0,
                system_type=NuveSystemType.HEAT_PUMP,
                mode=NuveMode.HEAT,
                schedule_type=9,
                records_received=1,
            )
        )
        assert restored.authoritative_control_monitor_seen is True
        assert restored.can_enable_control is True
        await restored.async_shutdown()

    asyncio.run(scenario())


def test_monitor_resync_retries_delivery_and_rotates_wake_command_time() -> None:
    async def scenario() -> None:
        source = await _ready_runtime()
        persisted = source.persistent_baselines()
        await source.async_shutdown()

        runtime = NuveRuntime(
            serial="00-000-000000",
            paired=True,
            bootstrap_firmware_version="1.5.7.4",
            bootstrap_technician_url="https://contractor.invalid/preserved",
            bootstrap_metadata_confirmed=True,
            bootstrap_no_update_confirmed=True,
            temp_correction_version=1,
        )
        attach_memory_persistence(runtime)
        runtime.async_restore_persistent_baselines(persisted)
        now = datetime.now(UTC)
        runtime.async_note_authenticated_contact(now)

        async def disconnected_sender(body: dict[str, Any]) -> None:
            assert set(body["setting"]) == {"last_update"}
            raise ConnectionResetError

        with pytest.raises(ConnectionResetError):
            await runtime.async_get_settings_response(
                requested_at=now,
                response_sender=disconnected_sender,
            )
        assert await runtime.async_get_auto_mode_response(requested_at=now) == {}

        reset = await runtime.async_get_settings_response(requested_at=now + timedelta(seconds=1))
        assert set(reset["setting"]) == {"last_update"}
        assert await runtime.async_get_auto_mode_response(
            requested_at=now + timedelta(seconds=1)
        ) == {
            "last_update": runtime.auto_mode_revision,
            "auto_temp_low": {},
            "auto_temp_high": {},
        }
        assert (
            await runtime.async_get_auto_mode_response(requested_at=now + timedelta(seconds=1))
            == {}
        )
        first_wake = await runtime.async_get_settings_response(
            requested_at=now + timedelta(seconds=2)
        )
        second_reset = await runtime.async_get_settings_response(
            requested_at=now + timedelta(seconds=3)
        )
        second_wake = await runtime.async_get_settings_response(
            requested_at=now + timedelta(seconds=4)
        )

        forbidden = {"temp", "mode_id", "fan", "system", "schedule", "schedule2"}
        for response in (reset, first_wake, second_reset, second_wake):
            assert not forbidden.intersection(response)
        assert set(second_reset["setting"]) == {"last_update"}
        assert first_wake["setting"]["command"] == "push_live_data"
        assert second_wake["setting"]["command"] == "push_live_data"
        assert second_wake["setting"]["command_time"] > first_wake["setting"]["command_time"]
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_normal_canonical_echo_requires_exact_firmware_attestations() -> None:
    async def scenario() -> None:
        runtime = NuveRuntime(
            serial="00-000-000000",
            paired=True,
            bootstrap_firmware_version="1.5.7.4",
            bootstrap_technician_url="https://contractor.invalid/preserved",
            bootstrap_metadata_confirmed=True,
            bootstrap_no_update_confirmed=False,
            temp_correction_version=1,
        )
        attach_memory_persistence(runtime)
        now = datetime.now(UTC)
        runtime.async_accept_settings_snapshot(_settings(), received_at=now)
        runtime.async_accept_auto_mode_snapshot(
            {
                "auto_temp_low": 19.0,
                "auto_temp_high": 23.0,
                "is_active": False,
                "mode": "heating",
            },
            received_at=now,
        )

        assert await runtime.async_get_settings_response(requested_at=now) == {}
        assert await runtime.async_get_auto_mode_response(requested_at=now) == {}

        runtime.bootstrap_no_update_confirmed = True
        runtime.bootstrap_firmware_version = "1.6.1.1"
        assert await runtime.async_get_settings_response(requested_at=now) == {}
        assert await runtime.async_get_auto_mode_response(requested_at=now) == {}

        runtime.bootstrap_firmware_version = "unsupported"
        assert runtime.canonical_metadata_ready is False
        assert await runtime.async_get_settings_response(requested_at=now) == {}

        runtime.bootstrap_firmware_version = "1.5.7.4"
        runtime.temp_correction_version = True
        assert runtime.canonical_metadata_ready is False
        assert await runtime.async_get_settings_response(requested_at=now) == {}

        runtime.temp_correction_version = 1
        reset = await runtime.async_get_settings_response(requested_at=now)
        assert set(reset["setting"]) == {"last_update"}
        wake = await runtime.async_get_settings_response(requested_at=now + timedelta(seconds=1))
        assert wake["setting"]["command"] == "push_live_data"
        assert "temp" not in wake
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                monitor_is_sync=True,
                current_temperature=21.2,
                target_temperature=21.5,
                target_humidity=40.0,
                auto_temperature_low=19.0,
                auto_temperature_high=23.0,
                system_type=NuveSystemType.HEAT_PUMP,
                mode=NuveMode.HEAT,
                schedule_type=9,
                records_received=1,
            )
        )
        assert (await runtime.async_get_settings_response(requested_at=now))["temp"] == 21.5
        assert (await runtime.async_get_auto_mode_response(requested_at=now))[
            "auto_temp_low"
        ] == 19.0
        await runtime.async_shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("firmware", "correction_model", "expected"),
    [
        ("1.5.7.4", 2, True),
        ("1.5.7.4", 3, False),
        ("1.5.8", 1, True),
        ("1.5.8", 2, True),
        ("1.5.8", 3, False),
        ("1.5.8", 99, False),
        ("1.5.8", True, False),
        ("1.6.1.1", 3, True),
        ("unsupported", 1, False),
    ],
)
def test_canonical_metadata_uses_exact_firmware_profile(
    firmware: str, correction_model: int, expected: bool
) -> None:
    runtime = NuveRuntime(
        serial="00-000-000000",
        bootstrap_firmware_version=firmware,
        temp_correction_version=correction_model,
    )

    assert runtime.canonical_metadata_ready is expected


def test_recovery_firmware_baseline_requires_exact_version_match() -> None:
    runtime = NuveRuntime(
        serial="00-000-000000",
        paired=True,
        bootstrap_firmware_version="1.5.8",
        bootstrap_technician_url="https://contractor.invalid/preserved",
        bootstrap_metadata_confirmed=True,
        bootstrap_no_update_confirmed=True,
        temp_correction_version=1,
    )
    attach_memory_persistence(runtime)
    runtime.async_accept_settings_snapshot(
        settings_upload("00-000-000000", firmware_version="1.5.8"),
        received_at=datetime.now(UTC),
    )

    assert runtime.baseline_firmware_version == "1.5.8"
    assert runtime.canonical_response_safe is True
    assert runtime.canonical_response_block_reason is None

    runtime.bootstrap_firmware_version = "1.5.7.4"
    assert runtime.canonical_response_safe is False
    assert runtime.canonical_response_block_reason == "firmware_baseline_mismatch"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda runtime: setattr(runtime, "paired", False), "not_paired"),
        (
            lambda runtime: setattr(runtime, "persistence_fault_latched", True),
            "persistence_fault_latched",
        ),
        (
            lambda runtime: setattr(runtime, "persistence_healthy", False),
            "persistence_unhealthy",
        ),
        (
            lambda runtime: setattr(runtime, "_persistence_listener", None),
            "persistence_listener_missing",
        ),
        (
            lambda runtime: setattr(runtime, "settings_snapshot", None),
            "settings_baseline_missing",
        ),
        (
            lambda runtime: setattr(runtime, "bootstrap_metadata_confirmed", False),
            "metadata_not_confirmed",
        ),
        (
            lambda runtime: setattr(runtime, "bootstrap_no_update_confirmed", False),
            "update_state_not_confirmed",
        ),
        (
            lambda runtime: setattr(runtime, "bootstrap_technician_url", None),
            "technician_url_invalid",
        ),
        (
            lambda runtime: setattr(runtime, "bootstrap_firmware_version", "unknown"),
            "firmware_unsupported",
        ),
        (
            lambda runtime: setattr(runtime, "bootstrap_firmware_version", "1.5.8"),
            "firmware_baseline_mismatch",
        ),
        (
            lambda runtime: setattr(runtime, "temp_correction_version", 99),
            "canonical_metadata_invalid",
        ),
    ],
)
def test_canonical_response_block_reason_is_exact(mutation: Any, reason: str) -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        mutation(runtime)
        assert runtime.canonical_response_safe is False
        assert runtime.canonical_response_block_reason == reason
        assert runtime.control_authority_block_reason == reason
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_buffered_monitor_data_cannot_confirm_or_clear_a_delivered_command(
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime(timeout=0.03)
        task = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)
        delivered_at = datetime.now(UTC)
        await runtime.async_get_settings_response(requested_at=delivered_at)

        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=delivered_at,
                sample_time=delivered_at,
                monitor_is_sync=True,
                target_temperature=22.0,
                mode=NuveMode.HEAT,
                records_received=1,
            )
        )
        assert runtime.settings_snapshot is not None
        assert runtime.settings_snapshot["temp"] == 21.5
        assert not task.done()
        with pytest.raises(CommandOutcomeUncertainError):
            await task
        assert runtime.uncertain_kind == "settings"
        assert runtime.uncertain_command is not None
        assert runtime.uncertain_command.desired == {"temp": 22.0}
        assert runtime.uncertain_command.delivered_at == delivered_at

        runtime.async_accept_auto_mode_snapshot(
            {
                "auto_temp_low": 19.0,
                "auto_temp_high": 23.0,
                "is_active": False,
                "mode": "heating",
            },
            received_at=delivered_at + timedelta(seconds=1),
        )
        assert runtime.uncertain_kind == "settings"

        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=delivered_at,
                sample_time=delivered_at,
                monitor_is_sync=True,
                target_temperature=22.0,
                mode=NuveMode.HEAT,
                records_received=1,
            )
        )
        assert runtime.uncertain_kind == "settings"

        await asyncio.sleep(0.002)
        authoritative_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=authoritative_at,
                sample_time=authoritative_at,
                monitor_is_sync=True,
                target_temperature=22.0,
                mode=NuveMode.HEAT,
                records_received=1,
            )
        )
        assert runtime.uncertain_kind is None
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_first_strictly_post_delivery_monitor_can_confirm_command() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        delivered_at = datetime.now(UTC)
        pending = runtime._queue_command_locked(
            "settings",
            {"temp": 20.0},
            runtime._settings_payload(runtime.settings_snapshot, {"temp": 20.0}),
        )
        pending.delivered = True
        pending.delivered_at = delivered_at
        pending.revision = "2026-08-09 22:40:14"
        runtime.uncertain_command = UncertainCommand(
            kind="settings",
            desired={"temp": 20.0},
            delivered_at=delivered_at,
            revision=pending.revision,
        )

        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=delivered_at + timedelta(seconds=10),
                sample_time=delivered_at + timedelta(seconds=10),
                target_temperature=20.0,
                records_received=1,
            )
        )

        assert pending.future.result() == "confirmed"
        assert runtime.uncertain_command is None
        assert runtime.command_status == "idle"
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_full_monitor_cannot_clear_restored_fan_uncertainty() -> None:
    async def scenario() -> None:
        source = await _ready_runtime()
        delivered_at = datetime.now(UTC)
        desired_fan = {"mode": 1, "workingPerHour": 40}
        source.uncertain_command = UncertainCommand(
            kind="settings",
            desired={"fan": desired_fan, "hold_period": "2: UntilChanged"},
            delivered_at=delivered_at,
            revision="2026-08-09 22:40:14",
        )
        persisted = source.persistent_baselines()
        persisted["uncertain_command"]["delivered_at"] = delivered_at
        await source.async_shutdown()

        runtime = NuveRuntime(serial="00-000-000000", paired=True)
        attach_memory_persistence(runtime)
        runtime.async_restore_persistent_baselines(persisted)
        assert runtime.uncertain_command is not None

        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=delivered_at + timedelta(seconds=10),
                sample_time=delivered_at + timedelta(seconds=10),
                monitor_is_sync=True,
                target_temperature=21.0,
                mode=NuveMode.COOL,
                auto_temperature_low=19.0,
                auto_temperature_high=23.0,
                fan_active=True,
                records_received=1,
            )
        )

        assert runtime.uncertain_command is not None
        assert runtime.uncertain_command.desired == {
            "fan": desired_fan,
            "hold_period": "2: UntilChanged",
        }

        upload = _settings()
        upload["fan"] = desired_fan
        upload["hold_period"] = "2: UntilChanged"
        received_at = delivered_at + timedelta(seconds=20)
        revision, candidate = runtime.prepare_settings_snapshot(upload, received_at=received_at)
        assert "uncertain_command" not in candidate
        runtime.async_accept_settings_snapshot(
            upload,
            received_at=received_at,
            prepared_revision=revision,
        )

        assert runtime.uncertain_command is None
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_command_is_revalidated_when_the_thermostat_fetches_it() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        task = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)
        runtime.async_update_state(replace(runtime.state, current_temperature=None))

        response = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        assert response == {}
        with pytest.raises(ControlNotReadyError):
            await task
        assert runtime.command_status == "idle"
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_delivery_is_suppressed_if_readiness_changes_during_persistence() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime(timeout=0.2)
        persist_started = asyncio.Event()
        persist_release = asyncio.Event()

        async def blocking_persist(candidate: dict[str, Any]) -> None:
            assert candidate["uncertain_command"]["kind"] == "settings"
            persist_started.set()
            await persist_release.wait()

        runtime.async_set_persistence_listener(blocking_persist)
        command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)
        poll = asyncio.create_task(
            runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        )
        await persist_started.wait()
        runtime.async_update_state(replace(runtime.state, current_temperature=None))
        persist_release.set()

        response = await poll
        assert response == {}
        with pytest.raises(CommandOutcomeUncertainError):
            await command
        assert runtime.uncertain_kind == "settings"
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_cancelled_persistence_task_latches_fault_without_committing_monitor() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        assert runtime.settings_snapshot is not None
        assert runtime.settings_snapshot["humidity"] == 40

        async def cancelled_persist(candidate: dict[str, Any]) -> None:
            raise asyncio.CancelledError

        runtime.async_set_persistence_listener(cancelled_persist)
        await asyncio.sleep(0.002)
        changed_at = datetime.now(UTC)
        with pytest.raises(PersistenceUnavailableError):
            await runtime.async_process_monitor_state(
                NuveState(
                    available=True,
                    last_seen=changed_at,
                    sample_time=changed_at,
                    target_humidity=45.0,
                    records_received=1,
                )
            )

        assert runtime.settings_snapshot["humidity"] == 40
        assert runtime.persistence_healthy is False
        assert runtime.persistence_fault_latched is True
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_persistence_failure_logs_sanitized_root_cause(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()

        async def failed_persist(candidate: dict[str, Any]) -> None:
            raise RuntimeError("verified readback failed")

        runtime.async_set_persistence_listener(failed_persist)
        caplog.set_level("ERROR", logger="custom_components.nuve_local.runtime")
        with pytest.raises(PersistenceUnavailableError):
            await runtime._async_persist_candidate(runtime.persistent_baselines())

        assert "RuntimeError" in caplog.text
        assert "verified readback failed" in caplog.text
        assert runtime.persistence_fault_latched is True
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_auto_command_requires_telemetry_only_for_fields_that_changed(monkeypatch: Any) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime()
        await runtime.async_get_auto_mode_response(requested_at=datetime.now(UTC))
        await runtime.async_request_auto_mode_change(
            {"auto_temp_low": 19.0, "auto_temp_high": 23.0}
        )
        assert runtime.command_status == "idle"

        task = asyncio.create_task(
            runtime.async_request_auto_mode_change({"auto_temp_low": 20.0, "auto_temp_high": 23.0})
        )
        await asyncio.sleep(0)
        delivered_at = datetime.now(UTC)
        response = await runtime.async_get_auto_mode_response(requested_at=delivered_at)
        assert response["auto_temp_low"] == 20.0
        assert response["auto_temp_high"] == 23.0

        await asyncio.sleep(0.002)
        confirmed_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=confirmed_at,
                sample_time=confirmed_at,
                auto_temperature_low=20.0,
                records_received=1,
            )
        )
        await task
        assert runtime.state.auto_temperature_low == 20.0
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_partial_device_preferences_preserve_zip_and_unknown_fields() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        assert runtime.settings_snapshot is not None
        runtime.settings_snapshot["settings"]["futureFirmwareField"] = {"keep": True}
        partial = dict(runtime.settings_snapshot["settings"])
        partial.pop("futureFirmwareField")

        runtime.async_accept_partial_settings("settings", partial, received_at=datetime.now(UTC))

        assert "zip" not in runtime.settings_snapshot["settings"]
        assert runtime.settings_snapshot["settings"]["futureFirmwareField"] == {"keep": True}
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_outdoor_weather_fails_closed_without_blocking_basic_hvac_control() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        runtime.async_set_outdoor_temperature(float("nan"), "Bad sensor")
        assert runtime.outdoor_is_fresh is False
        assert runtime.can_enable_control is True

        runtime.async_set_outdoor_temperature(
            10.0,
            "Stale sensor",
            observed_at=datetime.now(UTC) - timedelta(days=1),
        )
        assert runtime.outdoor_is_fresh is False
        assert runtime.can_enable_control is True

        runtime.async_set_outdoor_temperature(
            10.0,
            "Recently reported sensor",
            observed_at=datetime.now(UTC) - timedelta(seconds=899),
        )
        assert runtime.outdoor_is_fresh is True
        runtime.async_set_outdoor_temperature(
            10.0,
            "Expired sensor",
            observed_at=datetime.now(UTC) - timedelta(seconds=901),
        )
        assert runtime.outdoor_is_fresh is False
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_control_block_reason_identifies_queue_and_authority_failures() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime(timeout=0.01)
        assert runtime.control_authority_block_reason is None
        assert runtime.control_block_reason == "ready"

        runtime.authoritative_control_monitor_seen = False
        assert runtime.control_authority_block_reason == "monitor_authority_missing"
        assert runtime.control_block_reason == "monitor_authority_missing"

        runtime.authoritative_control_monitor_seen = True
        command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)
        assert runtime.control_block_reason == "command_queued_awaiting_fetch"

        with pytest.raises(CommandTimeoutError):
            await command
        assert runtime.control_block_reason == "ready"
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_expired_bootstrap_cannot_serve_either_compatibility_response() -> None:
    async def scenario() -> None:
        runtime = NuveRuntime(
            serial="00-000-000000",
            paired=True,
            state=NuveState(available=True),
            bootstrap_firmware_version="1.5.7.4",
            bootstrap_technician_url="https://contractor.invalid/preserved",
            bootstrap_metadata_confirmed=True,
            bootstrap_no_update_confirmed=True,
        )
        attach_memory_persistence(runtime)
        now = datetime.now(UTC)
        runtime.last_monitor_upload = now
        runtime.state = NuveState(
            available=True, last_seen=now, sample_time=now, records_received=1
        )
        await runtime.async_arm_baseline_bootstrap(armed_at=now)
        expired_at = now + timedelta(seconds=121)

        assert await runtime.async_get_settings_response(requested_at=expired_at) == {}
        assert await runtime.async_get_auto_mode_response(requested_at=expired_at) == {}
        assert runtime.bootstrap_status == "idle"
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_automatic_baseline_capture_arms_once_when_all_gates_become_ready() -> None:
    async def scenario() -> None:
        now = datetime.now(UTC)
        runtime = NuveRuntime(
            serial="00-000-000000",
            paired=True,
            automatic_baseline_capture=True,
            state=NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                records_received=1,
            ),
            bootstrap_firmware_version="1.5.7.4",
            bootstrap_technician_url="https://contractor.invalid/preserved",
            bootstrap_metadata_confirmed=True,
            bootstrap_no_update_confirmed=True,
        )
        runtime.last_monitor_upload = now
        saved = attach_memory_persistence(runtime)

        for _ in range(10):
            if runtime.bootstrap_status == "armed":
                break
            await asyncio.sleep(0)
        assert runtime.automatic_bootstrap_attempted is True
        assert runtime.bootstrap_status == "armed"
        assert len(saved) == 1

        runtime.bootstrap_armed_until = datetime.now(UTC) - timedelta(seconds=1)
        await runtime._async_expire_bootstrap()
        await asyncio.sleep(0)
        assert runtime.bootstrap_status == "idle"
        assert len(saved) == 2
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_pre_delivery_monitor_cannot_confirm_streamed_command(monkeypatch: Any) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(runtime_module, "MONITOR_FUTURE_SKEW_SECONDS", 0)
        runtime = await _ready_runtime(timeout=0.5)
        persisted = attach_memory_persistence(runtime)
        sender_started = asyncio.Event()
        sender_release = asyncio.Event()
        sent: list[dict[str, Any]] = []

        async def sender(body: dict[str, Any]) -> None:
            sent.append(body)
            sender_started.set()
            await sender_release.wait()

        command = asyncio.create_task(runtime.async_request_settings_change({"temp": 22.0}))
        await asyncio.sleep(0)
        poll = asyncio.create_task(
            runtime.async_get_settings_response(
                requested_at=datetime.now(UTC), response_sender=sender
            )
        )
        await sender_started.wait()
        assert persisted[-1]["uncertain_command"]["delivered_at"] is None

        generated_before_delivery = datetime.now(UTC)
        buffered_monitor = asyncio.create_task(
            runtime.async_process_monitor_state(
                NuveState(
                    available=True,
                    last_seen=generated_before_delivery,
                    sample_time=generated_before_delivery,
                    target_temperature=22.0,
                    records_received=1,
                )
            )
        )
        await asyncio.sleep(0)
        assert not buffered_monitor.done()

        sender_release.set()
        response = await poll
        await buffered_monitor
        assert sent == [response]
        assert persisted[-1]["uncertain_command"]["delivered_at"] is not None
        assert not command.done()

        await asyncio.sleep(0.002)
        confirmed_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=confirmed_at,
                sample_time=confirmed_at,
                target_temperature=22.0,
                records_received=1,
            )
        )
        await command
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_invalid_monitor_auto_pair_never_becomes_canonical() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        persisted = attach_memory_persistence(runtime)
        assert runtime.auto_mode_snapshot == {
            "auto_temp_low": 19.0,
            "auto_temp_high": 23.0,
        }

        await asyncio.sleep(0.002)
        crossed_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=crossed_at,
                sample_time=crossed_at,
                auto_temperature_low=24.0,
                records_received=1,
            )
        )
        assert runtime.auto_mode_snapshot == {
            "auto_temp_low": 19.0,
            "auto_temp_high": 23.0,
        }
        assert persisted == []
        assert runtime.can_enable_control is False

        await asyncio.sleep(0.002)
        reversed_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=reversed_at,
                sample_time=reversed_at,
                monitor_is_sync=True,
                current_temperature=21.2,
                target_temperature=21.5,
                target_humidity=40.0,
                auto_temperature_low=24.0,
                auto_temperature_high=20.0,
                system_type=NuveSystemType.HEAT_PUMP,
                mode=NuveMode.HEAT,
                records_received=1,
            )
        )
        assert runtime.auto_mode_snapshot == {
            "auto_temp_low": 19.0,
            "auto_temp_high": 23.0,
        }
        assert runtime.authoritative_control_monitor_seen is False
        assert runtime.can_enable_control is False
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_full_monitor_rebases_humidity_and_checks_equipment_type() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        await asyncio.sleep(0.002)
        changed_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=changed_at,
                sample_time=changed_at,
                monitor_is_sync=True,
                current_temperature=21.2,
                target_temperature=21.5,
                target_humidity=45.0,
                auto_temperature_low=19.0,
                auto_temperature_high=23.0,
                system_type=NuveSystemType.HEAT_PUMP,
                mode=NuveMode.HEAT,
                records_received=1,
            )
        )
        assert runtime.settings_snapshot is not None
        assert runtime.settings_snapshot["humidity"] == 45.0
        assert runtime.can_enable_control is True

        await asyncio.sleep(0.002)
        mismatch_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=mismatch_at,
                sample_time=mismatch_at,
                monitor_is_sync=True,
                current_temperature=21.2,
                target_temperature=21.5,
                target_humidity=45.0,
                auto_temperature_low=19.0,
                auto_temperature_high=23.0,
                system_type=NuveSystemType.TRADITIONAL,
                mode=NuveMode.HEAT,
                records_received=1,
            )
        )
        assert runtime.authoritative_control_monitor_seen is True
        assert runtime.can_enable_control is False

        await asyncio.sleep(0.002)
        missing_at = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=missing_at,
                sample_time=missing_at,
                monitor_is_sync=True,
                current_temperature=21.2,
                target_temperature=21.5,
                target_humidity=45.0,
                auto_temperature_low=19.0,
                auto_temperature_high=23.0,
                mode=NuveMode.HEAT,
                records_received=1,
            )
        )
        assert runtime.authoritative_control_monitor_seen is False
        assert runtime.can_enable_control is False
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_full_settings_get_echo_preserves_live_monitor_authority() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        assert runtime.settings_snapshot is not None
        assert runtime.authoritative_control_monitor_seen is True
        assert runtime.can_enable_control is True
        prior_upload = runtime.last_settings_upload

        # DeviceController saves a complete settings upload after every
        # successful Settings GET. Ambient/report-only values may drift between
        # those requests, but an exact desired/control echo is not a local
        # thermostat change and must not deadlock the next canonical poll.
        echo = copy.deepcopy(runtime.settings_snapshot)
        echo["current_temp"] = "22.1"
        echo["current_humidity"] = "41.5"
        echo["co2_id"] = 2
        echo["system"]["wifiStrength"] = "73"
        runtime.async_accept_settings_snapshot(echo, received_at=datetime.now(UTC))

        assert runtime.authoritative_control_monitor_seen is True
        assert runtime.last_settings_upload == prior_upload
        assert runtime.can_enable_control is True

        changed = copy.deepcopy(echo)
        changed["system"]["heat_min_on_time"] = 1.0
        changed_at = datetime.now(UTC)
        runtime.async_accept_settings_snapshot(changed, received_at=changed_at)

        assert runtime.authoritative_control_monitor_seen is False
        assert runtime.last_settings_upload == changed_at
        assert runtime.can_enable_control is False
        await runtime.async_shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("path", "changed_value"),
    [
        (("temp",), 22.0),
        (("humidity",), 41),
        (("hold",), True),
        (("hold_period",), "2030-01-01 00:00:00"),
        (("mode_id",), 1),
        (("fan", "mode"), 1),
        (("fan", "workingPerHour"), 40),
        (("backlight", "on"), False),
        (("backlight", "hue"), 0.5),
        (("backlight", "value"), 0.5),
        (("backlight", "shadeIndex"), 1),
        (("settings", "brightness"), 99),
        (("settings", "brightness_mode"), 1),
        (("settings", "speaker"), 49),
        (("settings", "temperatureUnit"), 1),
        (("settings", "timeFormat"), 0),
        (("settings", "currentTimezone"), "America/Halifax"),
        (("settings", "effectDst"), False),
        (("settings", "sleepModeLogo"), False),
        (("settings", "tofEnabled"), False),
        (("settings", "ledBlinkingEnabled"), False),
        (("settings", "setTimeAuto"), False),
        (("settings", "nightModeEnabled"), True),
        (("settings", "nightModeStart"), "23:00"),
        (("settings", "nightModeEnd"), "07:00"),
        (
            ("sensors",),
            [
                {
                    "name": "Synthetic",
                    "location": "Office",
                    "type": "Wireless",
                    "uid": "synthetic",
                }
            ],
        ),
        (("messages",), [{"id": "synthetic"}]),
        (("system", "type"), "traditional"),
        (("system", "coolStage"), 1),
        (("system", "heatStage"), 3),
        (("system", "heatPumpOBState"), 1),
        (("system", "heatPumpEmergency"), False),
        (("system", "systemRunDelay"), 2),
        (("system", "dualFuelThreshold"), -3),
        (("system", "isAUXAuto"), False),
        (("system", "dualFuelManualHeating"), 1),
        (("system", "dualFuelHeatingModeDefault"), 1),
        (("system", "emergencyMinimumTime"), 3),
        (("system", "auxiliaryHeating"), False),
        (("system", "useAuxiliaryParallelHeatPump"), True),
        (("system", "driveAux1AndETogether"), False),
        (("system", "driveAuxAsEmergency"), False),
        (("system", "runFanWithAuxiliary"), False),
        (("system", "turnAuxOnUnreaching"), 45),
        (("system", "thermostatControlFan"), False),
        (("system", "tempCorrection"), 0.5),
        (("system", "heatingControlByFurnace"), True),
        (("system", "compressorLockout"), True),
        (("system", "overcool"), 0.5),
        (("system", "diffToEngageAux"), 4.0),
        (("system", "heat_dissipation_time"), 1.5),
        (("system", "cool_dissipation_time"), 0.5),
        (("system", "fanWithAccessory"), True),
        (("system", "systemAccessories"), {"wire": "T1PWRD", "mode": 1}),
        (("system", "heat_deadband"), 1.5),
        (("system", "cool_deadband"), 1.5),
        (("system", "aux_lockout"), False),
        (("system", "aux_lockout_threshold"), -3.0),
        (("system", "wifiName"), "different-synthetic-network"),
        (("system", "heat_min_on_time"), 4.0),
        (("system", "cool_min_on_time"), 4.0),
        (("vacation", "min_humidity"), 29.0),
        (("vacation", "max_humidity"), 51.0),
        (("vacation", "min_temp"), 15.0),
        (("vacation", "max_temp"), 23.0),
        (("vacation", "is_enable"), "t"),
        (("firmware", "firmware-version"), "1.6.1.1"),
    ],
)
def test_every_settings_control_field_change_revokes_monitor_authority(
    path: tuple[str, ...], changed_value: object
) -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        assert runtime.settings_snapshot is not None
        changed = copy.deepcopy(runtime.settings_snapshot)
        target: dict[str, Any] = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = changed_value

        changed_at = datetime.now(UTC)
        runtime.async_accept_settings_snapshot(changed, received_at=changed_at)

        assert runtime.authoritative_control_monitor_seen is False
        assert runtime.last_settings_upload == changed_at
        assert runtime.can_enable_control is False
        await runtime.async_shutdown()

    asyncio.run(scenario())


def test_auto_get_echo_preserves_live_monitor_authority() -> None:
    async def scenario() -> None:
        runtime = await _ready_runtime()
        assert runtime.authoritative_control_monitor_seen is True
        assert runtime.can_enable_control is True
        prior_upload = runtime.last_auto_mode_upload

        runtime.async_accept_auto_mode_snapshot(
            {
                "auto_temp_low": 19.0,
                "auto_temp_high": 23.0,
                "is_active": False,
                "mode": "heating",
            },
            received_at=datetime.now(UTC),
        )

        assert runtime.authoritative_control_monitor_seen is True
        assert runtime.last_auto_mode_upload == prior_upload
        assert runtime.can_enable_control is True

        changed_at = datetime.now(UTC)
        runtime.async_accept_auto_mode_snapshot(
            {
                "auto_temp_low": 19.0,
                "auto_temp_high": 24.0,
                "is_active": False,
                "mode": "heating",
            },
            received_at=changed_at,
        )

        assert runtime.authoritative_control_monitor_seen is False
        assert runtime.last_auto_mode_upload == changed_at
        assert runtime.can_enable_control is False
        await runtime.async_shutdown()

    asyncio.run(scenario())
