"""Independent checks for exact-1.5.8 QtQuickStream persistence claims."""

from __future__ import annotations

import json

import pytest

from scripts.emulate_firmware_persistence import (
    ConfigSource,
    build_schedule_hold_repository,
    choose_startup_repository,
    decode_repository,
    decode_schedule_hold_state,
    firmware_reports_write_success,
    interrupted_direct_write,
    storage_property_allowed,
)


def _repo(label: str) -> bytes:
    return json.dumps({"root": f"qqs:/{label}", label: {"qsType": "Device"}}).encode()


def test_startup_prefers_primary_then_legacy_then_recovery() -> None:
    assert (
        choose_startup_repository(
            primary=_repo("primary"), legacy_relative=_repo("legacy"), recovery=_repo("recovery")
        ).source
        is ConfigSource.PRIMARY
    )
    assert (
        choose_startup_repository(
            primary=b"corrupt", legacy_relative=_repo("legacy"), recovery=_repo("recovery")
        ).source
        is ConfigSource.LEGACY_RELATIVE
    )
    assert (
        choose_startup_repository(
            primary=b"corrupt", legacy_relative=b"", recovery=_repo("recovery")
        ).source
        is ConfigSource.RECOVERY
    )


def test_startup_uses_default_device_when_every_candidate_is_invalid() -> None:
    result = choose_startup_repository(primary=b"", legacy_relative=b"[]", recovery=b'{"x":1}')
    assert result.source is ConfigSource.DEFAULT_DEVICE
    assert result.repository is None


@pytest.mark.parametrize("blob", [b"", b"[]", b"{}", b'{"root":""}', b'{"root":null}'])
def test_repository_requires_a_truthy_root_member(blob: bytes) -> None:
    assert decode_repository(blob) is None


def test_partial_truncating_write_destroys_the_previous_valid_file() -> None:
    replacement = _repo("new")
    on_disk = interrupted_direct_write(replacement, bytes_written=len(replacement) // 2)
    assert decode_repository(on_disk) is None


@pytest.mark.parametrize("result", [-1, 1, 12])
def test_firmware_reports_any_nonzero_write_result_as_success(result: int) -> None:
    assert firmware_reports_write_success(result)


def test_firmware_reports_only_zero_write_result_as_failure() -> None:
    assert not firmware_reports_write_success(0)


@pytest.mark.parametrize("name", ["_qsUuid", "_qsRepo", "temporary_", "objectName"])
def test_internal_or_blacklisted_properties_are_not_stored(name: str) -> None:
    assert not storage_property_allowed(name)


@pytest.mark.parametrize("name", ["schedulesV2", "holdPeriod", "holdStartTime", "id"])
def test_public_schedule_and_hold_properties_are_stored(name: str) -> None:
    assert storage_property_allowed(name)


def test_populated_v1_v2_and_hold_state_round_trip_through_qs_references() -> None:
    blob = build_schedule_hold_repository(
        schedules=[
            {
                "id": 41,
                "name": "Synthetic legacy",
                "startTime": "06:00 AM",
                "endTime": "08:00 AM",
                "repeats": "Mo",
                "version": 1,
            }
        ],
        schedules_v2=[
            {
                "id": 84,
                "type": 2,
                "startTime": "05:00 PM",
                "repeats": "Tu",
                "version": 2,
            }
        ],
        hold_type=3,
        hold_period={"1": 2, "2": 3},
        hold_start_time={"1": "2026-08-11T12:00:00.000Z"},
    )
    state = decode_schedule_hold_state(blob)
    assert state is not None
    graph = json.loads(blob)
    root = graph[graph["root"][len("qqs:/") :]]
    assert graph["root"].startswith("qqs:/{")
    assert all(reference.startswith("qqs:/{") for reference in root["schedules"])
    assert all(reference.startswith("qqs:/{") for reference in root["schedulesV2"])
    assert [(row["id"], row["version"]) for row in state.schedules] == [(41, 1)]
    assert [(row["id"], row["version"]) for row in state.schedules_v2] == [(84, 2)]
    assert state.hold_type == 3
    assert state.hold_period == {"1": 2, "2": 3}
    assert state.hold_start_time == {"1": "2026-08-11T12:00:00.000Z"}
    assert state.dropped_references == ()


def test_synthetic_dump_applies_the_exact_property_blacklist() -> None:
    blob = build_schedule_hold_repository(
        schedules=[
            {
                "id": 41,
                "_qsUuid": "not-stored",
                "temporary_": "not-stored",
                "objectName": "not-stored",
            }
        ],
        schedules_v2=[],
        hold_type=0,
        hold_period={},
        hold_start_time={},
    )
    state = decode_schedule_hold_state(blob)
    assert state is not None
    assert state.schedules == ({"qsType": "ScheduleCPP", "id": 41},)


def test_dangling_schedule_reference_is_silently_filtered_from_array() -> None:
    graph = json.loads(
        build_schedule_hold_repository(
            schedules=[],
            schedules_v2=[],
            hold_type=0,
            hold_period={},
            hold_start_time={},
        )
    )
    graph[graph["root"][len("qqs:/") :]]["schedulesV2"] = ["qqs:/missing-row"]
    state = decode_schedule_hold_state(json.dumps(graph).encode())
    assert state is not None
    assert state.schedules_v2 == ()
    assert state.dropped_references == ("qqs:/missing-row",)


def test_dangling_root_reference_cannot_produce_a_device_state() -> None:
    assert (
        decode_schedule_hold_state(
            json.dumps({"root": "qqs:/missing-device", "other": {}}).encode()
        )
        is None
    )


def test_wrong_typed_fields_pass_the_repository_gate_but_decode_to_bounded_views() -> None:
    graph = json.loads(
        build_schedule_hold_repository(
            schedules=[],
            schedules_v2=[],
            hold_type=0,
            hold_period={},
            hold_start_time={},
        )
    )
    root = graph[graph["root"][len("qqs:/") :]]
    root.update(
        schedules={},
        schedulesV2="wrong-type",
        holdType="wrong-type",
        holdPeriod=[],
        holdStartTime="wrong-type",
    )
    state = decode_schedule_hold_state(json.dumps(graph).encode())
    assert state is not None
    assert (state.schedules, state.schedules_v2) == ((), ())
    assert state.hold_type == "wrong-type"
    assert (state.hold_period, state.hold_start_time) == ({}, {})


def test_duplicate_json_member_uses_the_last_value() -> None:
    state = decode_schedule_hold_state(
        b'{"root":"qqs:/root","root":{"qsType":"Device","holdType":1,"holdType":3}}'
    )
    assert state is not None
    assert state.hold_type == 3
