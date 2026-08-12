"""Deduplicated Home Assistant Repairs for Nuve Local safety conditions."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.helpers import issue_registry as ir

from .const import BOOTSTRAP_FIRMWARE_ALLOWLIST, DOMAIN
from .runtime import NO_SCHEDULE_TYPE, NuveRuntime

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

FIRMWARE_ISSUE = "unsupported_firmware"
BASELINE_ISSUE = "canonical_baseline_problem"
MONITOR_ISSUE = "monitor_authority_stale"
PERSISTENCE_ISSUE = "persistence_problem"
UNCERTAIN_ISSUE = "uncertain_command_outcome"
SCHEDULE_ISSUE = "schedule_authority_block"

ISSUE_KINDS = frozenset(
    {
        FIRMWARE_ISSUE,
        BASELINE_ISSUE,
        MONITOR_ISSUE,
        PERSISTENCE_ISSUE,
        UNCERTAIN_ISSUE,
        SCHEDULE_ISSUE,
    }
)
GRACED_ISSUES = frozenset({BASELINE_ISSUE, MONITOR_ISSUE, SCHEDULE_ISSUE})


@dataclass(frozen=True, slots=True)
class IssueDefinition:
    """Stable presentation metadata for one repair family."""

    severity: ir.IssueSeverity


ISSUE_DEFINITIONS = {
    FIRMWARE_ISSUE: IssueDefinition(ir.IssueSeverity.ERROR),
    BASELINE_ISSUE: IssueDefinition(ir.IssueSeverity.WARNING),
    MONITOR_ISSUE: IssueDefinition(ir.IssueSeverity.WARNING),
    PERSISTENCE_ISSUE: IssueDefinition(ir.IssueSeverity.ERROR),
    UNCERTAIN_ISSUE: IssueDefinition(ir.IssueSeverity.ERROR),
    SCHEDULE_ISSUE: IssueDefinition(ir.IssueSeverity.WARNING),
}


def repair_conditions(runtime: NuveRuntime) -> frozenset[str]:
    """Classify only actionable, non-transient safety conditions."""

    issues: set[str] = set()
    if (
        not runtime.persistence_healthy
        or runtime.persistence_fault_latched
        or runtime.persistence_recovered_from_previous
    ):
        issues.add(PERSISTENCE_ISSUE)
    if runtime.uncertain_outcome:
        issues.add(UNCERTAIN_ISSUE)

    firmware = runtime.baseline_firmware_version
    configured_firmware = runtime.bootstrap_firmware_version
    canonical_reason = runtime.canonical_response_block_reason
    if (
        configured_firmware is not None and configured_firmware not in BOOTSTRAP_FIRMWARE_ALLOWLIST
    ) or (
        firmware is not None
        and (
            firmware not in BOOTSTRAP_FIRMWARE_ALLOWLIST
            or canonical_reason in {"firmware_unsupported", "firmware_baseline_mismatch"}
        )
    ):
        issues.add(FIRMWARE_ISSUE)

    if not runtime.control_enabled:
        return frozenset(issues)

    if canonical_reason in {
        "not_paired",
        "settings_baseline_missing",
        "metadata_not_confirmed",
        "update_state_not_confirmed",
        "technician_url_invalid",
        "canonical_metadata_invalid",
    } or runtime.control_authority_block_reason in {
        "auto_baseline_missing",
        "baseline_mismatch",
    }:
        issues.add(BASELINE_ISSUE)

    if (
        canonical_reason is None
        and runtime.has_auto_mode_baseline
        and runtime.control_authority_block_reason
        in {
            "monitor_authority_missing",
            "monitor_stale",
            "monitor_records_missing",
            "current_temperature_missing",
            "target_temperature_missing",
            "settings_newer_than_monitor",
        }
    ):
        issues.add(MONITOR_ISSUE)

    if (
        canonical_reason is None
        and runtime.has_auto_mode_baseline
        and runtime.state.available
        and runtime.monitor_is_fresh
        and runtime.state.records_received > 0
        and runtime.state.schedule_type != NO_SCHEDULE_TYPE
    ):
        issues.add(SCHEDULE_ISSUE)
    return frozenset(issues)


def issue_id(entry_id: str, kind: str) -> str:
    """Return a stable per-entry identifier without exposing the raw entry ID."""

    digest = hashlib.sha256(entry_id.encode()).hexdigest()[:12]
    return f"{kind}_{digest}"


class NuveRepairManager:
    """Mirror runtime safety state into deduplicated persistent HA issues."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        runtime: NuveRuntime,
        *,
        grace_seconds: float = 300,
    ) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._runtime = runtime
        self._grace_seconds = grace_seconds
        self._unsubscribe: object | None = None
        self._handles: dict[str, asyncio.TimerHandle] = {}
        self._status: dict[str, bool] = {}

    def start(self) -> None:
        """Subscribe after the listener and platforms have started successfully."""

        self._unsubscribe = self._runtime.async_subscribe(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """Reconcile current conditions and start any grace periods."""

        desired = repair_conditions(self._runtime)
        for kind in ISSUE_KINDS:
            if kind in desired:
                if self._status.get(kind) is True:
                    continue
                if kind in GRACED_ISSUES:
                    if kind not in self._handles:
                        self._handles[kind] = asyncio.get_running_loop().call_later(
                            self._grace_seconds,
                            self._activate_after_grace,
                            kind,
                        )
                    continue
                self._create(kind)
                continue

            handle = self._handles.pop(kind, None)
            if handle is not None:
                handle.cancel()
            if self._status.get(kind) is not False:
                ir.async_delete_issue(self._hass, DOMAIN, issue_id(self._entry_id, kind))
            self._status[kind] = False

    def _activate_after_grace(self, kind: str) -> None:
        self._handles.pop(kind, None)
        if kind in repair_conditions(self._runtime):
            self._create(kind)

    def _create(self, kind: str) -> None:
        definition = ISSUE_DEFINITIONS[kind]
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id(self._entry_id, kind),
            is_fixable=False,
            is_persistent=True,
            severity=definition.severity,
            translation_key=kind,
        )
        self._status[kind] = True

    def shutdown(self) -> None:
        """Cancel local callbacks without hiding unresolved persistent issues."""

        if callable(self._unsubscribe):
            self._unsubscribe()
        self._unsubscribe = None
        for handle in self._handles.values():
            handle.cancel()
        self._handles.clear()


def delete_entry_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Remove every issue when its owning config entry is deleted."""

    for kind in ISSUE_KINDS:
        ir.async_delete_issue(hass, DOMAIN, issue_id(entry_id, kind))
