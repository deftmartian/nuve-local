"""The single-flight HA command lifecycle: queue, wait, confirm and uncertainty."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Literal

from ..commands import expand_settings_changes, validated_auto_changes, validated_settings_changes
from ..errors import (
    CommandOutcomeUncertainError,
    CommandTimeoutError,
    ControlBusyError,
    ControlDisabledError,
    ControlNotReadyError,
    ControlStateChangedError,
    RuntimeStoppedError,
    require,
)
from ..models import NuveState
from ..protocol import next_revision
from ..trace import elapsed_ms
from .bootstrap import RuntimeBootstrap
from .records import PendingCommand
from .rules import changed_fields, command_payload, latest_revision, values_match


class RuntimeCommands(RuntimeBootstrap):
    """Queue one HA write, wait for evidence, and resolve or retain its outcome."""

    __slots__ = ()

    async def async_request_settings_change(self, changes: dict[str, Any]) -> None:
        """Queue settings changes and wait for matching monitor telemetry."""

        async with self._persistence.lock:
            self._assert_ready("settings")
            baseline = require(self.settings_snapshot, "settings baseline")
            desired = validated_settings_changes(changes)
            desired = expand_settings_changes(baseline, desired)
            desired = changed_fields(desired, baseline)
            if not desired:
                return
            payload = command_payload(baseline, desired)
            pending = self._queue_command_locked("settings", desired, payload)
        await self._wait_for_command(pending)

    async def async_request_auto_mode_change(self, changes: dict[str, Any]) -> None:
        """Queue auto-range changes and wait for matching device state."""

        async with self._persistence.lock:
            self._assert_ready("auto")
            baseline = require(self.auto_mode_snapshot, "Auto baseline")
            desired = validated_auto_changes(changes)
            desired = changed_fields(desired, baseline)
            if not desired:
                return
            payload = command_payload(baseline, desired)
            if float(payload["auto_temp_low"]) >= float(payload["auto_temp_high"]):
                raise ControlNotReadyError
            pending = self._queue_command_locked("auto", desired, payload)
        await self._wait_for_command(pending)

    def _queue_command_locked(
        self,
        kind: Literal["settings", "auto"],
        desired: dict[str, Any],
        payload: dict[str, Any],
    ) -> PendingCommand:
        if self._pending_command is not None:
            raise ControlBusyError
        future = asyncio.get_running_loop().create_future()
        baseline = require(
            self.settings_snapshot if kind == "settings" else self.auto_mode_snapshot,
            f"{kind} baseline",
        )
        pending = PendingCommand(
            kind=kind,
            desired=copy.deepcopy(desired),
            payload=copy.deepcopy(payload),
            future=future,
            queued_at=datetime.now(UTC),
            queued_baseline={key: copy.deepcopy(baseline[key]) for key in desired},
        )
        self._pending_command = pending
        self._tracer.record("command", family=kind, result="queued", at=pending.queued_at)
        self._notify_listeners()
        return pending

    async def _wait_for_command(self, pending: PendingCommand) -> None:
        """Wait outside the coordinator lock, then clean up under it."""

        future = pending.future
        try:
            result = await asyncio.wait_for(
                asyncio.shield(future), timeout=self.command_timeout_seconds
            )
        except TimeoutError:
            async with self._persistence.lock:
                if future.done():
                    result = future.result()
                else:
                    if self._pending_command is pending:
                        self._pending_command = None
                        self._notify_listeners()
                    result = "outcome_uncertain" if pending.delivered else "timeout"
        except asyncio.CancelledError:
            async with self._persistence.lock:
                if self._pending_command is pending:
                    self._pending_command = None
                    self._notify_listeners()
            raise

        if result == "confirmed":
            return
        if result == "timeout":
            raise CommandTimeoutError
        if result == "state_changed":
            raise ControlStateChangedError
        if result == "stopped":
            raise RuntimeStoppedError
        if result == "not_ready":
            raise ControlNotReadyError
        raise CommandOutcomeUncertainError

    def _assert_ready(self, kind: Literal["settings", "auto"]) -> None:
        if not self.control_enabled:
            raise ControlDisabledError
        if self.uncertain_command is not None:
            raise CommandOutcomeUncertainError
        if self._pending_command is not None:
            raise ControlBusyError
        if not self.can_enable_control:
            raise ControlNotReadyError
        if self.schedule_authority_block_reason is not None:
            raise ControlNotReadyError
        if kind == "auto" and not self.has_auto_mode_baseline:
            raise ControlNotReadyError

    def _complete_pending(self, result: str) -> None:
        pending = self._pending_command
        if pending is None:
            return
        self._pending_command = None
        self._tracer.record(
            "command",
            family=pending.kind,
            result=result,
            duration_ms=elapsed_ms(pending.queued_at, datetime.now(UTC)),
        )
        self._notify_listeners()
        if not pending.future.done():
            pending.future.set_result(result)

    def _settings_owned_upload_result(
        self, incoming: dict[str, Any], received_at: datetime
    ) -> str | None:
        """Resolve Settings-owned fields from the post-GET complete upload."""

        desired: dict[str, Any] | None = None
        delivered_at: datetime | None = None
        pending = self._pending_command
        if (
            pending is not None
            and pending.kind == "settings"
            and pending.delivered
            and self._settings_upload_owns(pending.desired)
        ):
            desired = pending.desired
            delivered_at = pending.delivered_at
        elif (
            self.uncertain_command is not None
            and self.uncertain_command.kind == "settings"
            and self._settings_upload_owns(self.uncertain_command.desired)
        ):
            desired = self.uncertain_command.desired
            delivered_at = self.uncertain_command.delivered_at
        if delivered_at is None or desired is None or received_at <= delivered_at:
            return None
        return "confirmed" if values_match(desired, incoming) else "state_changed"

    @staticmethod
    def _settings_upload_owns(desired: dict[str, Any]) -> bool:
        keys = set(desired)
        return keys in ({"fan"}, {"backlight"}, {"settings"})

    def _delivered_echo_changes(
        self,
        kind: Literal["settings", "auto"],
        incoming: dict[str, Any],
        *,
        received_at: datetime,
    ) -> frozenset[str]:
        """Return exact queued fields in a coherent post-delivery echo."""

        pending = self._pending_command
        if (
            pending is None
            or pending.kind != kind
            or not pending.delivered
            or pending.delivered_at is None
            or received_at <= pending.delivered_at
            or not values_match(pending.desired, incoming)
        ):
            return frozenset()
        return frozenset(pending.desired)

    def _confirm_from_monitor(self, state: NuveState) -> bool:
        pending = self._pending_command
        if (
            pending is None
            or not pending.delivered
            or pending.delivered_at is None
            or state.sample_time is None
            or not self._monitor_evidence_is_post_delivery(
                state,
                pending,
                delivered_at=pending.delivered_at,
                sample_time=state.sample_time,
            )
        ):
            return False
        if pending.kind == "settings":
            actual: dict[str, Any] = {}
            if state.target_temperature is not None:
                actual["temp"] = state.target_temperature
            if state.mode is not None:
                actual["mode_id"] = int(state.mode)
            if not values_match(pending.desired, actual):
                return False
            confirmed_revision = next_revision(
                latest_revision(
                    self.settings_revision_floor,
                    latest_revision(self.settings_revision, pending.revision),
                ),
                now=state.sample_time,
            )
            confirmed_settings = copy.deepcopy(require(self.settings_snapshot, "settings baseline"))
            confirmed_settings.update(copy.deepcopy(pending.desired))
            self.settings_snapshot = confirmed_settings
            self.settings_revision = confirmed_revision
            self.settings_revision_floor = confirmed_revision
            self.live_data_command_time = pending.revision
            self.state = replace(self.state, settings_revision=confirmed_revision)
        else:
            actual = {}
            if state.auto_temperature_low is not None:
                actual["auto_temp_low"] = state.auto_temperature_low
            if state.auto_temperature_high is not None:
                actual["auto_temp_high"] = state.auto_temperature_high
            if not values_match(pending.desired, actual):
                return False
            confirmed_revision = next_revision(
                latest_revision(
                    self.auto_revision_floor,
                    latest_revision(self.auto_mode_revision, pending.revision),
                ),
                now=state.sample_time,
            )
            confirmed_auto = copy.deepcopy(require(self.auto_mode_snapshot, "Auto baseline"))
            confirmed_auto.update(copy.deepcopy(pending.desired))
            self.auto_mode_snapshot = confirmed_auto
            self.auto_mode_revision = confirmed_revision
            self.auto_revision_floor = confirmed_revision
        self.uncertain_command = None
        self._complete_pending("confirmed")
        return True

    @staticmethod
    def _monitor_evidence_is_post_delivery(
        state: NuveState,
        pending: PendingCommand,
        *,
        delivered_at: datetime,
        sample_time: datetime,
    ) -> bool:
        """Order monitor evidence across device-second and server-subsecond clocks."""

        if sample_time > delivered_at:
            return True

        echo_received_at = pending.coherent_echo_received_at
        if (
            echo_received_at is None
            or state.last_seen is None
            or echo_received_at <= delivered_at
            or state.last_seen <= echo_received_at
        ):
            return False

        # Firmware emits protobuf Timestamp seconds without a useful
        # subsecond component. A matching monitor record from the delivery
        # second can therefore sort before the server's microsecond boundary.
        # Accept it only after a coherent post-delivery full Settings echo and
        # a later monitor HTTP receipt establish the missing causal order.
        delivery_second = delivered_at.replace(microsecond=0)
        return sample_time >= delivery_second

    def _resolve_uncertainty_from_monitor(self, state: NuveState) -> bool:
        """Clear uncertainty only from a complete field-owning monitor snapshot."""

        uncertain = self.uncertain_command
        pending = self._pending_command
        if (
            uncertain is None
            or uncertain.delivered_at is None
            or (pending is not None and pending.delivered and pending.kind == uncertain.kind)
            or not state.monitor_is_sync
            or state.sample_time is None
            or state.sample_time <= uncertain.delivered_at
        ):
            return False
        # A full monitor owns the active temperature/mode and Auto bounds, but
        # not the configured fan mode or circulation minutes. Those
        # fan fields can be resolved only by a later complete Settings upload.
        # Keep unknown future Settings fields fail-closed for the same reason.
        if uncertain.kind == "settings":
            if not set(uncertain.desired).issubset({"temp", "mode_id"}):
                return False
            complete_family = state.target_temperature is not None and state.mode is not None
        else:
            complete_family = (
                state.auto_temperature_low is not None and state.auto_temperature_high is not None
            )
        if complete_family:
            self.uncertain_command = None
            self._notify_listeners()
            return True
        return False

    def _trace_monitor_result(
        self,
        pending: PendingCommand | None,
        pending_kind: Literal["settings", "auto"] | None,
    ) -> None:
        """Record whether one monitor transaction resolved the active command."""

        if pending is None:
            return
        result = (
            pending.future.result()
            if pending.future.done() and not pending.future.cancelled()
            else "not_confirmed"
        )
        self._tracer.record("monitor_confirmation", family=pending_kind, result=result)
        if result != "not_confirmed":
            self._tracer.record(
                "command",
                family=pending_kind,
                result=result,
                duration_ms=elapsed_ms(pending.queued_at, datetime.now(UTC)),
            )
