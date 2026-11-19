"""Change notification and durable baseline transactions."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from ..models import NuveState
from .persistence import PersistenceListener
from .readiness import RuntimeReadiness
from .records import serialize_uncertainty


class RuntimeTransactions(RuntimeReadiness):
    """Notify listeners and persist-then-commit the private durable baselines."""

    __slots__ = ()

    if TYPE_CHECKING:
        # Every notification re-checks the automatic bootstrap gates; the
        # bootstrap layer above this one provides the implementation.
        def _schedule_automatic_bootstrap_if_ready(self) -> None: ...

    def _notify_listeners(self) -> None:
        self._trace_control_block_transition()
        for listener in tuple(self._listeners):
            listener()
        self._schedule_automatic_bootstrap_if_ready()

    def _trace_control_block_transition(self) -> None:
        if self._tracer.enabled:
            self._tracer.note_control_block_reason(self.control_block_reason)

    def async_update_state(self, state: NuveState) -> None:
        """Replace state and notify entities from the Home Assistant event loop."""

        self.state = state
        self._notify_listeners()

    def async_set_paired(self) -> None:
        """Mark token pairing complete without retaining the bearer token."""

        self.paired = True
        self._notify_listeners()

    def async_set_persistence_listener(self, listener: PersistenceListener) -> None:
        """Register a callback used when uncertainty changes outside a request."""

        self._persistence.listener = listener
        self._schedule_automatic_bootstrap_if_ready()

    async def async_persist_and_commit(
        self,
        candidate: dict[str, Any],
        commit: Callable[[], object],
        *,
        family: Literal["settings", "auto"] | None = None,
    ) -> None:
        """Persist a prepared candidate, then expose its exact runtime transition."""

        if family is None and self._pending_command is not None:
            family = self._pending_command.kind
        await self._persistence.persist_and_commit(candidate, commit, family=family)

    def persistent_baselines(self) -> dict[str, Any]:
        """Return the private, versioned device baselines that survive HA restarts."""

        data: dict[str, Any] = {}
        if self.has_settings_baseline:
            data["settings"] = copy.deepcopy(self.settings_snapshot)
            data["settings_revision"] = self.settings_revision
        if self.has_auto_mode_baseline:
            data["auto_mode"] = copy.deepcopy(self.auto_mode_snapshot)
            data["auto_mode_revision"] = self.auto_mode_revision
        if self.settings_revision_floor is not None:
            data["settings_revision_floor"] = self.settings_revision_floor
        if self.auto_revision_floor is not None:
            data["auto_revision_floor"] = self.auto_revision_floor
        if self.live_data_command_time is not None:
            data["live_data_command_time"] = self.live_data_command_time
        if (
            not self.has_settings_baseline
            and self.bootstrap_revision is not None
            and self.bootstrap_armed_at is not None
            and self.bootstrap_armed_until is not None
        ):
            data["bootstrap"] = {
                "revision": self.bootstrap_revision,
                "armed_at": self.bootstrap_armed_at.isoformat(),
                "expires_at": self.bootstrap_armed_until.isoformat(),
                "settings_served": self.bootstrap_settings_served,
                "auto_served": self.bootstrap_auto_served,
            }
        if self.uncertain_command is not None:
            data["uncertain_command"] = serialize_uncertainty(self.uncertain_command)
        return data
