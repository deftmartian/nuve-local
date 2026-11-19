"""Responses to device Settings and Auto polls, including command delivery."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any, Literal

from ..errors import PersistenceUnavailableError, require
from ..protocol import (
    next_revision,
    render_auto_mode_bootstrap_response,
    render_auto_mode_response,
    render_monitor_reset_response,
    render_monitor_wake_response,
    render_settings_response,
)
from ..trace import elapsed_ms
from .monitor import RuntimeMonitor
from .records import PendingCommand, ResponseSender, UncertainCommand, serialize_uncertainty
from .rules import NO_SCHEDULE_TYPE, latest_revision


class RuntimePolling(RuntimeMonitor):
    """Answer device polls with a no-op echo, a resync cycle or a journaled command."""

    __slots__ = ()

    async def async_get_settings_response(
        self,
        *,
        requested_at: datetime,
        response_sender: ResponseSender | None = None,
    ) -> dict[str, Any]:
        """Return a durable no-op echo or whole settings command for a device poll."""

        async with self._persistence.lock:
            if self.persistence_fault_latched:
                raise PersistenceUnavailableError("canonical persistence requires reload")
            self.last_settings_poll = requested_at
            self._tracer.record("poll", family="settings", result="received", at=requested_at)
            await self._async_clear_expired_bootstrap_locked(requested_at)
            if not self.has_settings_baseline:
                return await self._async_serve_settings_bootstrap_locked(requested_at)
            if not self.canonical_response_safe:
                return {}
            if not self.canonical_live_consistency_ready:
                return await self._async_monitor_resync_response(
                    requested_at=requested_at,
                    response_sender=response_sender,
                )

            pending = self._pending_command
            if pending is not None and pending.kind == "settings":
                blocked = self._reject_blocked_pending(pending)
                if blocked is not None:
                    return blocked
                if not pending.delivered:
                    await self._async_journal_delivery(pending, requested_at=requested_at)
                    blocked = self._reject_blocked_pending(pending)
                    if blocked is not None:
                        return blocked
                revision = require(pending.revision, "delivered command revision")
                technician_url = require(self._effective_technician_url(), "technician URL")
                temp_correction_version = require(
                    self.temp_correction_version, "temperature correction version"
                )
                response = render_settings_response(
                    serial=self.serial,
                    revision=revision,
                    settings=self._with_live_data_command(pending.payload, command_time=revision),
                    technician_url=technician_url,
                    temp_correction_version=temp_correction_version,
                )
                return await self._async_deliver_pending_response(
                    pending,
                    response,
                    requested_at=requested_at,
                    response_sender=response_sender,
                )
            if self.state.schedule_type != NO_SCHEDULE_TYPE:
                return self._schedule_preserving_settings_response()
            return self._canonical_settings_response()

    async def async_get_auto_mode_response(
        self,
        *,
        requested_at: datetime,
        response_sender: ResponseSender | None = None,
    ) -> dict[str, Any]:
        """Return a durable no-op echo or whole Auto command for a device poll."""

        async with self._persistence.lock:
            if self.persistence_fault_latched:
                raise PersistenceUnavailableError("canonical persistence requires reload")
            self._tracer.record("poll", family="auto", result="received", at=requested_at)
            await self._async_clear_expired_bootstrap_locked(requested_at)
            # Once the settings trap has been served, its non-applying Auto
            # companion must win over monitor-derived or restored Auto data.
            if self._auto_bootstrap_due(requested_at):
                return await self._async_serve_auto_bootstrap_locked()
            if not self.has_settings_baseline or not self.has_auto_mode_baseline:
                return {}
            if not self.canonical_response_safe:
                return {}
            if not self.canonical_live_consistency_ready:
                companion_revision = self._monitor_resync_auto_companion_revision
                self._monitor_resync_auto_companion_revision = None
                if companion_revision is None:
                    return {}
                return render_auto_mode_bootstrap_response(revision=companion_revision)
            self._monitor_resync_auto_companion_revision = None
            pending = self._pending_command
            if pending is not None and pending.kind == "auto":
                blocked = self._reject_blocked_pending(pending)
                if blocked is not None:
                    return blocked
                if not pending.delivered:
                    await self._async_journal_delivery(pending, requested_at=requested_at)
                    blocked = self._reject_blocked_pending(pending)
                    if blocked is not None:
                        return blocked
                response = render_auto_mode_response(
                    revision=require(pending.revision, "delivered command revision"),
                    settings=pending.payload,
                )
                return await self._async_deliver_pending_response(
                    pending,
                    response,
                    requested_at=requested_at,
                    response_sender=response_sender,
                )
            return self._canonical_auto_mode_response()

    def _canonical_settings_response(self) -> dict[str, Any]:
        """Render the saved device state after the metadata checks pass."""

        return render_settings_response(
            serial=self.serial,
            revision=require(self.settings_revision, "settings revision"),
            settings=self._with_live_data_command(
                require(self.settings_snapshot, "settings baseline")
            ),
            technician_url=require(self._effective_technician_url(), "technician URL"),
            temp_correction_version=require(
                self.temp_correction_version, "temperature correction version"
            ),
        )

    def _schedule_preserving_settings_response(self) -> dict[str, Any]:
        """Keep a local schedule intact without replaying server-owned schedule state."""

        revision = require(self.settings_revision, "settings revision")
        settings = require(self.settings_snapshot, "settings baseline")
        return render_monitor_wake_response(
            serial=self.serial,
            revision=revision,
            technician_url=require(self._effective_technician_url(), "technician URL"),
            messages=settings["messages"],
            command_time=self.live_data_command_time or revision,
        )

    def _canonical_auto_mode_response(self) -> dict[str, Any]:
        """Return the last confirmed Auto snapshot without applying a queued change."""

        revision = require(self.auto_mode_revision, "Auto revision")
        return render_auto_mode_response(
            revision=revision,
            settings=require(self.auto_mode_snapshot, "Auto baseline"),
        )

    def _with_live_data_command(
        self, settings: dict[str, Any], *, command_time: str | None = None
    ) -> dict[str, Any]:
        payload = copy.deepcopy(settings)
        payload["command"] = "push_live_data"
        payload["command_time"] = (
            command_time or self.live_data_command_time or self.settings_revision or "local"
        )
        return payload

    async def _async_monitor_resync_response(
        self,
        *,
        requested_at: datetime,
        response_sender: ResponseSender | None,
    ) -> dict[str, Any]:
        """Cycle monitor offline then online without supplying HVAC state."""

        settings = require(self.settings_snapshot, "settings baseline")
        settings_revision = require(self.settings_revision, "settings revision")
        technician_url = require(self._effective_technician_url(), "technician URL")

        if self._monitor_resync_next == "reset":
            response = render_monitor_reset_response(
                serial=self.serial,
                revision=settings_revision,
                technician_url=technician_url,
                messages=settings["messages"],
            )
            next_phase: Literal["reset", "wake"] = "wake"
        else:
            prior = latest_revision(
                latest_revision(settings_revision, self.settings_revision_floor),
                latest_revision(
                    latest_revision(
                        self.live_data_command_time,
                        (
                            self.uncertain_command.revision
                            if self.uncertain_command is not None
                            else None
                        ),
                    ),
                    self._monitor_wake_command_time,
                ),
            )
            command_time = next_revision(prior, now=requested_at)
            self._monitor_wake_command_time = command_time
            response = render_monitor_wake_response(
                serial=self.serial,
                revision=settings_revision,
                technician_url=technician_url,
                messages=settings["messages"],
                command_time=command_time,
            )
            next_phase = "reset"

        if response_sender is not None:
            await response_sender(copy.deepcopy(response))
        # fetchSettings immediately chains fetchAutoModeSetings. Returning an
        # empty Auto body marks the whole fetch unsuccessful and doubles the
        # firmware retry interval up to 60 seconds. Arm one exact-revision,
        # object-valued companion only after the non-applying Settings body was
        # delivered. The native Auto callback treats the response as a
        # successful fetch, while the QML numeric-difference guards apply no
        # bounds. This keeps the proven 5-second healthy polling cadence without
        # replaying a restored Auto baseline.
        self._monitor_resync_auto_companion_revision = (
            self.auto_mode_revision if self.has_auto_mode_baseline else None
        )
        self._monitor_resync_next = next_phase
        return response

    def _reject_blocked_pending(self, pending: PendingCommand) -> dict[str, Any] | None:
        """Withdraw a queued command that must not reach the response body."""

        if self.schedule_authority_block_reason is not None:
            self._complete_pending("outcome_uncertain" if pending.delivered else "not_ready")
            if pending.kind == "settings":
                return self._schedule_preserving_settings_response()
            return self._canonical_auto_mode_response()
        if not self.can_enable_control:
            self._complete_pending("outcome_uncertain" if pending.delivered else "not_ready")
            return {}
        return None

    async def _async_journal_delivery(
        self, pending: PendingCommand, *, requested_at: datetime
    ) -> None:
        """Persist the write-ahead uncertainty journal before a command body is sent."""

        if pending.kind == "settings":
            current, floor_key = self.settings_revision, "settings_revision_floor"
        else:
            current, floor_key = self.auto_mode_revision, "auto_revision_floor"
        prior = latest_revision(
            latest_revision(current, getattr(self, floor_key)), pending.revision
        )
        revision = next_revision(prior, now=requested_at)
        uncertainty = UncertainCommand(
            kind=pending.kind,
            desired=copy.deepcopy(pending.desired),
            delivered_at=None,
            revision=revision,
        )
        candidate = self.persistent_baselines()
        candidate[floor_key] = revision
        candidate["uncertain_command"] = serialize_uncertainty(uncertainty)

        def commit_delivery() -> None:
            pending.revision = revision
            pending.delivered = True
            pending.delivered_at = None
            setattr(self, floor_key, revision)
            self.uncertain_command = uncertainty
            self._notify_listeners()

        await self.async_persist_and_commit(candidate, commit_delivery)

    async def _async_deliver_pending_response(
        self,
        pending: PendingCommand,
        response: dict[str, Any],
        *,
        requested_at: datetime,
        response_sender: ResponseSender | None,
    ) -> dict[str, Any]:
        """Send a command before establishing its durable confirmation boundary.

        Production passes a sender that writes the HTTP body while the runtime
        transaction lock is held. A nullable write-ahead boundary is already
        durable before that write. Only after the body has been sent do we
        persist the server time from which device-clock skew is measured.
        """

        blocked = self._reject_blocked_pending(pending)
        if blocked is not None:
            return blocked

        if response_sender is not None:
            await response_sender(copy.deepcopy(response))
            delivered_at = datetime.now(UTC)
        else:
            # Direct runtime callers are tests and internal probes; model an
            # immediate response at the supplied request boundary.
            delivered_at = requested_at
        self._tracer.record(
            "command_delivery",
            family=pending.kind,
            result="body_sent",
            duration_ms=elapsed_ms(pending.queued_at, delivered_at),
            at=delivered_at,
        )

        if pending.delivered_at is None:
            uncertainty = UncertainCommand(
                kind=pending.kind,
                desired=copy.deepcopy(pending.desired),
                delivered_at=delivered_at,
                revision=pending.revision,
            )
            candidate = self.persistent_baselines()
            candidate["uncertain_command"] = serialize_uncertainty(uncertainty)

            def commit_delivery_boundary() -> None:
                pending.delivered_at = delivered_at
                self.uncertain_command = uncertainty
                self._notify_listeners()

            await self.async_persist_and_commit(candidate, commit_delivery_boundary)

        # The body may already have reached the thermostat. If any safety gate
        # changed during the send/final journal write, resolve the HA caller as
        # uncertain and retain the durable lockout.
        if not self.can_enable_control or self.schedule_authority_block_reason is not None:
            self._complete_pending("outcome_uncertain")
        return response
