"""Tests for deduplicated actionable Nuve Repairs issues."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from custom_components.nuve_local.models import NuveMode, NuveState, NuveSystemType
from custom_components.nuve_local.repairs import (
    BASELINE_ISSUE,
    FIRMWARE_ISSUE,
    MONITOR_ISSUE,
    PERSISTENCE_ISSUE,
    SCHEDULE_ISSUE,
    UNCERTAIN_ISSUE,
    NuveRepairManager,
    delete_entry_issues,
    issue_id,
    repair_conditions,
)
from custom_components.nuve_local.runtime import NuveRuntime, UncertainCommand
from tests.helpers import attach_memory_persistence, settings_upload


def _ready_runtime() -> NuveRuntime:
    now = datetime.now(UTC)
    runtime = NuveRuntime(
        serial="00-000-000000",
        control_enabled=True,
        paired=True,
        bootstrap_firmware_version="1.5.8",
        bootstrap_technician_url="https://contractor.invalid/preserved",
        bootstrap_metadata_confirmed=True,
        bootstrap_no_update_confirmed=True,
        temp_correction_version=2,
    )
    attach_memory_persistence(runtime)
    runtime.settings_snapshot = settings_upload(runtime.serial, firmware_version="1.5.8")
    runtime.settings_revision = "2026-08-11 12:00:00"
    runtime.auto_mode_snapshot = {"auto_temp_low": 19.0, "auto_temp_high": 23.0}
    runtime.auto_mode_revision = "2026-08-11 12:00:00"
    runtime.last_monitor_upload = now
    runtime.authoritative_control_monitor_seen = True
    runtime.state = NuveState(
        available=True,
        sample_time=now,
        current_temperature=21.0,
        target_temperature=21.5,
        target_humidity=40.0,
        auto_temperature_low=19.0,
        auto_temperature_high=23.0,
        system_type=NuveSystemType.HEAT_PUMP,
        mode=NuveMode.HEAT,
        schedule_type=9,
        records_received=1,
    )
    return runtime


def test_repair_conditions_are_actionable_and_nonoverlapping() -> None:
    runtime = _ready_runtime()
    assert repair_conditions(runtime) == frozenset()

    runtime.state = replace(runtime.state, schedule_type=8)
    assert repair_conditions(runtime) == {SCHEDULE_ISSUE}
    runtime.state = replace(runtime.state, schedule_type=9)

    runtime.authoritative_control_monitor_seen = False
    assert repair_conditions(runtime) == {MONITOR_ISSUE}
    runtime.authoritative_control_monitor_seen = True

    runtime.state = replace(runtime.state, target_temperature=20.0)
    assert repair_conditions(runtime) == {BASELINE_ISSUE}
    runtime.state = replace(runtime.state, target_temperature=21.5)

    runtime.state = replace(runtime.state, available=False)
    assert repair_conditions(runtime) == frozenset()
    runtime.state = replace(runtime.state, available=True)

    assert runtime.settings_snapshot is not None
    runtime.settings_snapshot["firmware"]["firmware-version"] = "9.9.9"
    assert repair_conditions(runtime) == {FIRMWARE_ISSUE}

    unpaired = NuveRuntime(serial="00-000-000000", control_enabled=True)
    assert repair_conditions(unpaired) == {BASELINE_ISSUE}


def test_persistence_and_uncertainty_report_even_with_control_disabled() -> None:
    runtime = NuveRuntime(serial="00-000-000000", control_enabled=False)
    runtime.persistence_recovered_from_previous = True
    runtime.uncertain_command = UncertainCommand(
        kind="settings",
        desired={"settings": {"brightness": 49}},
        delivered_at=datetime.now(UTC),
    )
    assert repair_conditions(runtime) == {PERSISTENCE_ISSUE, UNCERTAIN_ISSUE}

    unsupported = NuveRuntime(
        serial="00-000-000000",
        control_enabled=False,
        bootstrap_firmware_version="9.9.9",
    )
    assert repair_conditions(unsupported) == {FIRMWARE_ISSUE}


def test_manager_deduplicates_clears_and_applies_schedule_grace(monkeypatch: Any) -> None:
    async def scenario() -> None:
        created: list[str] = []
        deleted: list[str] = []
        monkeypatch.setattr(
            "custom_components.nuve_local.repairs.ir.async_create_issue",
            lambda hass, domain, issue_id, **kwargs: created.append(issue_id),
        )
        monkeypatch.setattr(
            "custom_components.nuve_local.repairs.ir.async_delete_issue",
            lambda hass, domain, issue_id: deleted.append(issue_id),
        )

        clean = NuveRepairManager(object(), "entry-clean", _ready_runtime())  # type: ignore[arg-type]
        clean.start()
        assert len(deleted) == 6
        clean.shutdown()
        deleted.clear()

        runtime = NuveRuntime(serial="00-000-000000")
        runtime.uncertain_command = UncertainCommand(
            kind="settings",
            desired={"settings": {"brightness": 49}},
            delivered_at=datetime.now(UTC),
        )
        manager = NuveRepairManager(object(), "entry-private", runtime, grace_seconds=0.01)  # type: ignore[arg-type]
        manager.start()
        manager.refresh()
        assert len(created) == 1
        runtime.uncertain_command = None
        manager.refresh()
        assert sum("uncertain_command_outcome" in item for item in deleted) == 1
        manager.shutdown()

        created.clear()
        deleted.clear()
        scheduled = _ready_runtime()
        scheduled.state = replace(scheduled.state, schedule_type=8)
        manager = NuveRepairManager(object(), "entry-schedule", scheduled, grace_seconds=0.01)  # type: ignore[arg-type]
        manager.start()
        assert len(created) == 0
        await asyncio.sleep(0.02)
        assert len(created) == 1
        scheduled.state = replace(scheduled.state, schedule_type=9)
        manager.refresh()
        assert sum("schedule_authority_block" in item for item in deleted) == 1
        manager.shutdown()

        stale = _ready_runtime()
        stale.last_monitor_upload = datetime.now(UTC) - timedelta(hours=2)
        assert repair_conditions(stale) == {MONITOR_ISSUE}

    asyncio.run(scenario())


def test_entry_removal_deletes_only_stable_private_issue_ids(monkeypatch: Any) -> None:
    deleted: list[str] = []
    monkeypatch.setattr(
        "custom_components.nuve_local.repairs.ir.async_delete_issue",
        lambda hass, domain, repair_id: deleted.append(repair_id),
    )

    entry_id = "private-config-entry"
    delete_entry_issues(object(), entry_id)  # type: ignore[arg-type]

    assert len(deleted) == 6
    assert len(set(deleted)) == 6
    assert all(entry_id not in repair_id for repair_id in deleted)
    assert issue_id(entry_id, FIRMWARE_ISSUE) in deleted
