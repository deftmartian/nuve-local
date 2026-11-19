"""The one-shot initial-baseline bootstrap window."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from ..commissioning import valid_technician_url
from ..const import BOOTSTRAP_FIRMWARE_ALLOWLIST, BOOTSTRAP_WINDOW_SECONDS
from ..errors import ControlNotReadyError, PersistenceUnavailableError
from ..protocol import (
    next_revision,
)
from .rules import latest_revision
from .transactions import RuntimeTransactions

# Keep the historical logger name so existing Home Assistant logger filters
# for ``custom_components.nuve_local.runtime`` still apply.
_LOGGER = logging.getLogger(__package__)


class RuntimeBootstrap(RuntimeTransactions):
    """Arm, serve, expire and clear the durable compatibility-bridge journal."""

    __slots__ = ()

    @property
    def bootstrap_status(self) -> str:
        """Return the non-secret initial-baseline bootstrap state."""

        if self.has_settings_baseline:
            return "complete"
        if self.bootstrap_armed_until is None:
            return "idle"
        if self.bootstrap_auto_served:
            return "fetch_unlocked"
        if self.bootstrap_settings_served:
            return "settings_served"
        return "armed"

    @property
    def can_arm_bootstrap(self) -> bool:
        """Return whether every explicit compatibility-bridge precondition is met."""

        return (
            not self._stopped
            and self.paired
            and self.persistence_healthy
            and self._persistence.listener is not None
            and self.state.available
            and self.monitor_is_fresh
            and not self.has_settings_baseline
            and not self.control_enabled
            and self.bootstrap_armed_until is None
            and self._pending_command is None
            and self.bootstrap_metadata_confirmed
            and self.bootstrap_no_update_confirmed
            and valid_technician_url(self.bootstrap_technician_url)
            and self.bootstrap_firmware_version in BOOTSTRAP_FIRMWARE_ALLOWLIST
        )

    def _schedule_automatic_bootstrap_if_ready(self) -> None:
        """Start at most one proven bootstrap window when every gate is ready."""

        if (
            not self.automatic_baseline_capture
            or self._automatic_bootstrap_attempted
            or self._automatic_bootstrap_task is not None
            or not self.can_arm_bootstrap
        ):
            return
        self._automatic_bootstrap_attempted = True
        self._automatic_bootstrap_task = asyncio.create_task(
            self._async_automatic_bootstrap(),
            name="Arm automatic Nuve baseline capture",
        )

    async def _async_automatic_bootstrap(self) -> None:
        """Run one non-retrying automatic baseline-capture attempt."""

        try:
            await self.async_arm_baseline_bootstrap(armed_at=datetime.now(UTC))
        except ControlNotReadyError:
            _LOGGER.debug("Nuve automatic baseline capture lost readiness before arming")
        except PersistenceUnavailableError:
            _LOGGER.warning("Nuve automatic baseline capture could not be persisted")
        finally:
            self._automatic_bootstrap_task = None

    async def async_arm_baseline_bootstrap(self, *, armed_at: datetime) -> None:
        """Durably arm the explicitly requested one-shot compatibility bridge."""

        async with self._persistence.lock:
            if self.has_settings_baseline:
                return
            if not self.can_arm_bootstrap:
                raise ControlNotReadyError
            prior = latest_revision(
                latest_revision(self.settings_revision, self.settings_revision_floor),
                latest_revision(self.auto_mode_revision, self.auto_revision_floor),
            )
            revision = next_revision(prior, now=armed_at)
            expires_at = armed_at + timedelta(seconds=BOOTSTRAP_WINDOW_SECONDS)
            candidate = self.persistent_baselines()
            candidate["settings_revision_floor"] = revision
            candidate["auto_revision_floor"] = revision
            candidate["bootstrap"] = {
                "revision": revision,
                "armed_at": armed_at.astimezone(UTC).isoformat(),
                "expires_at": expires_at.astimezone(UTC).isoformat(),
                "settings_served": False,
                "auto_served": False,
            }

            def commit() -> None:
                self._clear_bootstrap()
                self.bootstrap_armed_at = armed_at
                self.bootstrap_armed_until = expires_at
                self.bootstrap_revision = revision
                self.settings_revision_floor = revision
                self.auto_revision_floor = revision
                self._schedule_bootstrap_expiry(expires_at)
                self._notify_listeners()

            await self.async_persist_and_commit(candidate, commit)

    def _bootstrap_active(self, now: datetime) -> bool:
        return (
            not self.has_settings_baseline
            and self.bootstrap_armed_until is not None
            and now <= self.bootstrap_armed_until
        )

    def _schedule_bootstrap_expiry(self, expires_at: datetime) -> None:
        delay = max(0.0, (expires_at - datetime.now(UTC)).total_seconds())
        self._bootstrap_timer.start(
            delay,
            lambda: asyncio.create_task(
                self._async_expire_bootstrap(), name="Expire Nuve bootstrap journal"
            ),
        )

    async def _async_expire_bootstrap(self) -> None:
        async with self._persistence.lock:
            self._bootstrap_timer.forget()
            if self._stopped or self.has_settings_baseline or self.bootstrap_armed_until is None:
                return
            if datetime.now(UTC) < self.bootstrap_armed_until:
                self._schedule_bootstrap_expiry(self.bootstrap_armed_until)
                return
            candidate = self.persistent_baselines()
            candidate.pop("bootstrap", None)

            def commit() -> None:
                self._clear_bootstrap(cancel_timer=False)
                self._notify_listeners()

            await self.async_persist_and_commit(candidate, commit)

    async def _async_clear_expired_bootstrap_locked(self, now: datetime) -> None:
        """Remove an expired durable journal while the transaction lock is held."""

        if (
            self.has_settings_baseline
            or self.bootstrap_armed_until is None
            or now <= self.bootstrap_armed_until
        ):
            return
        candidate = self.persistent_baselines()
        candidate.pop("bootstrap", None)

        def commit() -> None:
            self._clear_bootstrap()
            self._notify_listeners()

        await self.async_persist_and_commit(candidate, commit)

    def _clear_bootstrap(self, *, cancel_timer: bool = True) -> None:
        if cancel_timer:
            self._bootstrap_timer.cancel()
        else:
            self._bootstrap_timer.forget()
        self.bootstrap_armed_until = None
        self.bootstrap_armed_at = None
        self.bootstrap_revision = None
        self.bootstrap_settings_served = False
        self.bootstrap_auto_served = False
