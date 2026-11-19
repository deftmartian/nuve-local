"""Monitor telemetry ingest and its merge into runtime state and baselines."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Literal, Self

from ..models import NuveState
from ..protocol import next_revision
from .records import PendingCommand
from .rules import (
    SYSTEM_TYPE_NAMES,
    current_monitor_sample_time,
    latest_revision,
    monitor_gap_expired,
    monitor_sample_is_post_queue,
    valid_auto_pair,
    valid_humidity,
    values_match,
)
from .snapshots import RuntimeSnapshots
from .timers import OneShotTimer
from .tracing import RuntimeTracer


class RuntimeMonitor(RuntimeSnapshots):
    """Prepare each monitor merge on an isolated shadow, persist, then commit it."""

    __slots__ = ()

    async def async_process_monitor_state(self, state: NuveState) -> None:
        """Persist any canonical monitor merge before exposing telemetry or success."""

        async with self._persistence.lock:
            pending = self._pending_command
            pending_kind = pending.kind if pending is not None else None
            self._tracer.record(
                "monitor_upload",
                family="monitor",
                result="full" if state.monitor_is_sync else "sparse",
                at=state.last_seen,
            )
            shadow, shadow_future = self._monitor_shadow()
            shadow._merge_monitor_state_in_place(state)
            if self.persistence_fault_latched:
                # Keep read-only live telemetry available, but do not trust or
                # expose any canonical mutation after an ambiguous disk result.
                self.state = replace(
                    copy.deepcopy(shadow.state),
                    settings_revision=self.state.settings_revision,
                )
                self.last_monitor_upload = shadow.last_monitor_upload
                self.current_temperature_observed_at = shadow.current_temperature_observed_at
                self.current_temperature_source = shadow.current_temperature_source
                self._notify_listeners()
                self._tracer.record(
                    "monitor_confirmation", family=pending_kind, result="persistence_latched"
                )
                return

            before = self.persistent_baselines()
            candidate = shadow.persistent_baselines()
            if candidate == before:
                self._commit_monitor_shadow(shadow, shadow_future=shadow_future)
                self._trace_monitor_result(pending, pending_kind)
                return
            await self.async_persist_and_commit(
                candidate,
                lambda: self._commit_monitor_shadow(shadow, shadow_future=shadow_future),
            )
            self._trace_monitor_result(pending, pending_kind)

    def _monitor_shadow(self) -> tuple[Self, asyncio.Future[str] | None]:
        """Build an isolated copy for preparing a monitor transaction."""

        shadow = copy.copy(self)
        shadow.state = copy.deepcopy(self.state)
        shadow.settings_snapshot = copy.deepcopy(self.settings_snapshot)
        shadow.auto_mode_snapshot = copy.deepcopy(self.auto_mode_snapshot)
        shadow.uncertain_command = copy.deepcopy(self.uncertain_command)
        shadow._listeners = set()
        shadow._liveness_timer = OneShotTimer()
        shadow._bootstrap_timer = OneShotTimer()
        shadow._tracer = RuntimeTracer(enabled=False)
        shadow._persistence = self._persistence.detached(
            tracer=shadow._tracer, on_fault=shadow._notify_listeners
        )
        dummy_future: asyncio.Future[str] | None = None
        pending = self._pending_command
        if pending is None:
            shadow._pending_command = None
        else:
            dummy_future = asyncio.get_running_loop().create_future()
            shadow._pending_command = PendingCommand(
                kind=pending.kind,
                desired=copy.deepcopy(pending.desired),
                payload=copy.deepcopy(pending.payload),
                future=dummy_future,
                queued_at=pending.queued_at,
                queued_baseline=copy.deepcopy(pending.queued_baseline),
                revision=pending.revision,
                delivered=pending.delivered,
                delivered_at=pending.delivered_at,
                coherent_echo_received_at=pending.coherent_echo_received_at,
            )
        return shadow, dummy_future

    def _commit_monitor_shadow(
        self,
        shadow: Self,
        *,
        shadow_future: asyncio.Future[str] | None,
    ) -> None:
        """Expose a verified monitor plan and resolve its waiter last."""

        real_pending = self._pending_command
        shadow_pending = shadow._pending_command
        pending_result = (
            shadow_future.result() if shadow_future is not None and shadow_future.done() else None
        )

        self.state = copy.deepcopy(shadow.state)
        self.last_monitor_upload = shadow.last_monitor_upload
        self.settings_snapshot = copy.deepcopy(shadow.settings_snapshot)
        self.settings_revision = shadow.settings_revision
        self.settings_revision_floor = shadow.settings_revision_floor
        self.auto_mode_snapshot = copy.deepcopy(shadow.auto_mode_snapshot)
        self.auto_mode_revision = shadow.auto_mode_revision
        self.auto_revision_floor = shadow.auto_revision_floor
        self.live_data_command_time = shadow.live_data_command_time
        self.uncertain_command = copy.deepcopy(shadow.uncertain_command)
        self.authoritative_control_monitor_seen = shadow.authoritative_control_monitor_seen
        self.current_temperature_observed_at = shadow.current_temperature_observed_at
        self.current_temperature_source = shadow.current_temperature_source

        if real_pending is not None:
            if shadow_pending is None:
                self._pending_command = None
            else:
                real_pending.payload = copy.deepcopy(shadow_pending.payload)
                real_pending.revision = shadow_pending.revision
                real_pending.delivered = shadow_pending.delivered
                real_pending.delivered_at = shadow_pending.delivered_at

        self._notify_listeners()
        if (
            pending_result is not None
            and real_pending is not None
            and not real_pending.future.done()
        ):
            real_pending.future.set_result(pending_result)

    def _merge_monitor_state_in_place(self, state: NuveState) -> bool:
        """Merge one monitor payload into this runtime or an isolated shadow."""

        current = self.state
        received_at = state.last_seen or datetime.now(UTC)
        self._note_monitor_upload(received_at)
        sample_time = current_monitor_sample_time(
            state.sample_time, received_at, self.state.sample_time
        )
        if sample_time is None:
            # Authentication/liveness is independent from telemetry authority.
            self.async_update_state(
                replace(
                    current,
                    available=state.available or current.available,
                    last_seen=received_at,
                )
            )
            return False

        monitor_fields, preserve_newer_temperature = self._monitor_fields(
            state, sample_time=sample_time
        )
        self.async_update_state(
            replace(
                current,
                available=state.available,
                last_seen=state.last_seen or current.last_seen,
                **monitor_fields,
                monitor_is_sync=state.monitor_is_sync,
                records_received=current.records_received + state.records_received,
            )
        )
        if not preserve_newer_temperature and state.current_temperature is not None:
            self.current_temperature_observed_at = sample_time
            self.current_temperature_source = "monitor"
        self._update_full_monitor_authority(state)
        confirmed = self._confirm_from_monitor(state)
        persistent_changed = self._merge_monitor_into_baselines(state, sample_time=sample_time)
        uncertainty_cleared = self._resolve_uncertainty_from_monitor(state)
        return confirmed or persistent_changed or uncertainty_cleared

    def _note_monitor_upload(self, received_at: datetime) -> None:
        """Advance monitor liveness and expire authority after a telemetry gap."""

        previous_monitor_upload = self.last_monitor_upload
        self.last_monitor_upload = received_at
        if monitor_gap_expired(previous_monitor_upload, received_at):
            self.authoritative_control_monitor_seen = False

    def _monitor_fields(
        self, state: NuveState, *, sample_time: datetime
    ) -> tuple[dict[str, Any], bool]:
        """Build a full or incremental monitor merge without mutating state."""

        current = self.state
        monitor_fields = {
            "sample_time": sample_time,
            "current_temperature": state.current_temperature,
            "current_humidity": state.current_humidity,
            "target_temperature": state.target_temperature,
            "target_humidity": state.target_humidity,
            "auto_temperature_low": state.auto_temperature_low,
            "auto_temperature_high": state.auto_temperature_high,
            "mcu_temperature": state.mcu_temperature,
            "air_pressure": state.air_pressure,
            "air_quality_level": state.air_quality_level,
            "cooling_stage": state.cooling_stage,
            "heating_stage": state.heating_stage,
            "fan_active": state.fan_active,
            "led_active": state.led_active,
            "system_type": state.system_type,
            "mode": state.mode,
            "online": state.online,
            "schedule_type": state.schedule_type,
        }
        preserve_newer_temperature = (
            self.current_temperature_observed_at is not None
            and sample_time <= self.current_temperature_observed_at
        )
        if preserve_newer_temperature:
            # Settings and current-sensor uploads carry the same rounded room
            # value as monitor f4, but have no embedded device timestamp. A
            # buffered monitor packet must not roll either newer observation
            # back merely because it arrived later over HTTP.
            monitor_fields["current_temperature"] = current.current_temperature
        if not state.monitor_is_sync:
            for key, value in tuple(monitor_fields.items()):
                if value is None:
                    monitor_fields[key] = getattr(current, key)
        return monitor_fields, preserve_newer_temperature

    def _update_full_monitor_authority(self, state: NuveState) -> None:
        """Recompute whole-snapshot control authority only for a full monitor."""

        if not state.monitor_is_sync:
            return
        self.authoritative_control_monitor_seen = bool(
            state.available
            and state.target_temperature is not None
            and valid_humidity(state.target_humidity)
            and state.mode is not None
            and valid_auto_pair(state.auto_temperature_low, state.auto_temperature_high)
            and state.system_type in SYSTEM_TYPE_NAMES
        )

    def _merge_monitor_into_baselines(self, state: NuveState, *, sample_time: datetime) -> bool:
        """Keep future whole-snapshot writes aligned with device-local changes."""

        seen_at = sample_time
        pending = self._pending_command
        evidence_is_post_queue = bool(
            pending is not None
            and not pending.delivered
            and monitor_sample_is_post_queue(sample_time, pending.queued_at)
        )
        changed = self._merge_monitor_settings_baseline(
            state,
            seen_at=seen_at,
            pending=pending,
            evidence_is_post_queue=evidence_is_post_queue,
        )
        if self._merge_monitor_auto_baseline(
            state,
            seen_at=seen_at,
            pending=pending,
            evidence_is_post_queue=evidence_is_post_queue,
        ):
            changed = True

        if self._reconcile_undelivered_pending_from_monitor(state):
            changed = True

        if changed:
            self._notify_listeners()
        return changed

    @staticmethod
    def _pending_blocks_monitor_field(
        pending: PendingCommand | None,
        *,
        kind: Literal["settings", "auto"],
        field: str,
        evidence_is_post_queue: bool,
    ) -> bool:
        """Keep pre-command monitor evidence from replacing a queued field."""

        return bool(
            pending is not None
            and pending.kind == kind
            and field in pending.desired
            and not evidence_is_post_queue
        )

    def _merge_monitor_settings_baseline(
        self,
        state: NuveState,
        *,
        seen_at: datetime,
        pending: PendingCommand | None,
        evidence_is_post_queue: bool,
    ) -> bool:
        """Merge Settings-owned monitor fields into the durable baseline."""

        snapshot = self.settings_snapshot
        if snapshot is None:
            return False
        candidates = {
            "temp": state.target_temperature,
            "mode_id": int(state.mode) if state.mode is not None else None,
        }
        updates = {
            key: value
            for key, value in candidates.items()
            if value is not None
            and not self._pending_blocks_monitor_field(
                pending,
                kind="settings",
                field=key,
                evidence_is_post_queue=evidence_is_post_queue,
            )
        }
        if valid_humidity(state.target_humidity):
            updates["humidity"] = state.target_humidity

        changed = False
        for key, value in updates.items():
            if snapshot.get(key) == value:
                continue
            snapshot[key] = value
            if pending is not None and pending.kind == "settings" and not pending.delivered:
                pending.payload[key] = value
            changed = True
        if not changed:
            return False

        self.settings_revision = next_revision(
            latest_revision(self.settings_revision, self.settings_revision_floor),
            now=seen_at,
        )
        self.settings_revision_floor = self.settings_revision
        self.state = replace(self.state, settings_revision=self.settings_revision)
        return True

    def _merge_monitor_auto_baseline(
        self,
        state: NuveState,
        *,
        seen_at: datetime,
        pending: PendingCommand | None,
        evidence_is_post_queue: bool,
    ) -> bool:
        """Merge Auto-owned monitor fields into the durable baseline."""

        snapshot = self.auto_mode_snapshot
        if snapshot is None and (
            state.monitor_is_sync
            and state.auto_temperature_low is not None
            and state.auto_temperature_high is not None
            and valid_auto_pair(state.auto_temperature_low, state.auto_temperature_high)
        ):
            self.auto_mode_snapshot = {
                "auto_temp_low": state.auto_temperature_low,
                "auto_temp_high": state.auto_temperature_high,
            }
            snapshot = self.auto_mode_snapshot
            changed = True
        elif snapshot is None:
            return False
        else:
            candidates = {
                "auto_temp_low": state.auto_temperature_low,
                "auto_temp_high": state.auto_temperature_high,
            }
            updates = {
                key: value
                for key, value in candidates.items()
                if value is not None
                and not self._pending_blocks_monitor_field(
                    pending,
                    kind="auto",
                    field=key,
                    evidence_is_post_queue=evidence_is_post_queue,
                )
            }
            prospective = copy.deepcopy(snapshot)
            prospective.update(updates)
            if not valid_auto_pair(
                prospective.get("auto_temp_low"), prospective.get("auto_temp_high")
            ):
                return False
            changed = False
            for key, value in updates.items():
                if snapshot.get(key) == value:
                    continue
                snapshot[key] = value
                if pending is not None and pending.kind == "auto" and not pending.delivered:
                    pending.payload[key] = value
                changed = True
        if not changed:
            return False

        self.auto_mode_revision = next_revision(
            latest_revision(
                latest_revision(self.settings_revision, self.settings_revision_floor),
                latest_revision(self.auto_mode_revision, self.auto_revision_floor),
            ),
            now=seen_at,
        )
        self.auto_revision_floor = self.auto_mode_revision
        return True

    def _reconcile_undelivered_pending_from_monitor(self, state: NuveState) -> bool:
        """Resolve a queued write when later device evidence changes its baseline."""

        pending = self._pending_command
        if (
            pending is None
            or pending.delivered
            or state.sample_time is None
            or not monitor_sample_is_post_queue(state.sample_time, pending.queued_at)
        ):
            return False

        actual: dict[str, Any] = {}
        if pending.kind == "settings":
            if "temp" in pending.desired and state.target_temperature is not None:
                actual["temp"] = state.target_temperature
            if "mode_id" in pending.desired and state.mode is not None:
                actual["mode_id"] = int(state.mode)
        else:
            if "auto_temp_low" in pending.desired and state.auto_temperature_low is not None:
                actual["auto_temp_low"] = state.auto_temperature_low
            if "auto_temp_high" in pending.desired and state.auto_temperature_high is not None:
                actual["auto_temp_high"] = state.auto_temperature_high

        if not actual:
            return False
        if set(actual) == set(pending.desired) and values_match(pending.desired, actual):
            self._complete_pending("confirmed")
            return True
        if any(
            not values_match({key: pending.queued_baseline[key]}, {key: value})
            for key, value in actual.items()
        ):
            self._complete_pending("state_changed")
            return True
        return False
