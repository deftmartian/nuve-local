"""Device-originated Settings and Auto snapshots: prepare, accept and restore."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any, Literal

from ..errors import ControlNotReadyError
from ..models import NuveMode
from ..protocol import next_revision, parse_auto_mode_baseline
from .command_lifecycle import RuntimeCommands
from .records import UncertainCommand
from .rules import ACTIVE_SCHEDULE_TYPES, command_payload, latest_revision


class RuntimeSnapshots(RuntimeCommands):
    """Prepare, accept and restore whole and partial device uploads."""

    __slots__ = ()

    def prepare_settings_snapshot(
        self, snapshot: dict[str, Any], *, received_at: datetime
    ) -> tuple[str, dict[str, Any]]:
        """Build the exact persistent candidate before acknowledging an upload."""

        incoming = copy.deepcopy(snapshot)
        revision = self._settings_snapshot_revision(incoming, received_at)
        candidate = self.persistent_baselines()
        candidate.pop("bootstrap", None)
        candidate["settings"] = incoming
        candidate["settings_revision"] = revision
        candidate["settings_revision_floor"] = latest_revision(
            self.settings_revision_floor, revision
        )
        if self._settings_owned_upload_result(incoming, received_at) is not None:
            candidate.pop("uncertain_command", None)
        if candidate.get("live_data_command_time") is None:
            candidate["live_data_command_time"] = revision
        return revision, candidate

    def async_accept_settings_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        received_at: datetime,
        prepared_revision: str,
    ) -> str:
        """Store a complete device-originated settings snapshot and return its ack revision."""

        incoming = copy.deepcopy(snapshot)
        pending = self._pending_command
        settings_result = self._settings_owned_upload_result(incoming, received_at)
        revision = prepared_revision
        permitted_changes = self._delivered_echo_changes(
            "settings",
            incoming,
            received_at=received_at,
        )
        canonical_echo = self._settings_snapshot_is_canonical_echo(
            incoming,
            permitted_changes=permitted_changes,
        )
        if settings_result == "state_changed":
            canonical_echo = False
        if canonical_echo and permitted_changes and pending is not None:
            pending.coherent_echo_received_at = received_at
        complete_pending = (
            pending is not None and pending.kind == "settings" and not pending.delivered
        )

        self.settings_snapshot = incoming
        self.settings_revision = revision
        self.settings_revision_floor = latest_revision(self.settings_revision_floor, revision)
        self._clear_bootstrap()
        if self.live_data_command_time is None:
            self.live_data_command_time = revision
        # DeviceController's Settings GET handler calls saveSettings()
        # unconditionally, even after an exact no-op echo. That creates a full
        # /sync/update upload. Preserve post-start monitor authority only when
        # every desired/control field is byte-for-JSON equivalent to the
        # baseline we just served. A post-delivery upload may differ only by
        # the exact queued fields; it proves a coherent echo but does not
        # confirm a temperature or mode command, which still requires newer
        # monitor telemetry. Observational room values are intentionally
        # excluded. Any local/clamped/configuration change still fails closed
        # until newer monitor evidence arrives.
        if not canonical_echo:
            self.last_settings_upload = received_at
            self.authoritative_control_monitor_seen = False
        self._tracer.record(
            "upload_echo",
            family="settings",
            result=(
                "expected_command"
                if canonical_echo and permitted_changes
                else "canonical"
                if canonical_echo
                else "changed"
            ),
            at=received_at,
        )
        self._merge_settings_into_state(incoming, revision, observed_at=received_at)
        if settings_result is not None:
            self.uncertain_command = None
            if pending is not None and pending.kind == "settings":
                self._complete_pending(settings_result)
            else:
                self._notify_listeners()
        elif complete_pending:
            self._complete_pending("state_changed")
        else:
            self._notify_listeners()
        return revision

    def prepare_auto_mode_snapshot(
        self, snapshot: dict[str, Any], *, received_at: datetime
    ) -> tuple[str, dict[str, Any]]:
        """Build the exact persistent Auto candidate before acknowledging an upload."""

        incoming = parse_auto_mode_baseline(snapshot)
        revision = self._auto_snapshot_revision(incoming, received_at)
        candidate = self.persistent_baselines()
        candidate["auto_mode"] = incoming
        candidate["auto_mode_revision"] = revision
        candidate["auto_revision_floor"] = latest_revision(self.auto_revision_floor, revision)
        return revision, candidate

    def async_accept_auto_mode_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        received_at: datetime,
        prepared_revision: str,
    ) -> str:
        """Store a complete device-originated auto-mode snapshot and return its ack revision."""

        # The device uploads four fields, all of which are validated at the
        # request boundary.  Only the two temperature bounds are consumed by
        # the firmware's Auto GET response, so keep one canonical projection
        # for runtime state, monitor-derived baselines, hashing, and restore.
        incoming = parse_auto_mode_baseline(snapshot)
        pending = self._pending_command
        revision = prepared_revision
        permitted_changes = self._delivered_echo_changes(
            "auto",
            incoming,
            received_at=received_at,
        )
        canonical_echo = self._auto_snapshot_is_canonical_echo(
            incoming,
            permitted_changes=permitted_changes,
        )
        if canonical_echo and permitted_changes and pending is not None:
            pending.coherent_echo_received_at = received_at
        complete_pending = pending is not None and pending.kind == "auto" and not pending.delivered

        self.auto_mode_snapshot = incoming
        self.auto_mode_revision = revision
        self.auto_revision_floor = latest_revision(self.auto_revision_floor, revision)
        if not canonical_echo:
            self.last_auto_mode_upload = received_at
            self.authoritative_control_monitor_seen = False
        self._tracer.record(
            "upload_echo",
            family="auto",
            result=(
                "expected_command"
                if canonical_echo and permitted_changes
                else "canonical"
                if canonical_echo
                else "changed"
            ),
            at=received_at,
        )
        self._merge_auto_into_state(incoming, revision)
        if complete_pending:
            self._complete_pending("state_changed")
        else:
            self._notify_listeners()
        return revision

    def _settings_snapshot_revision(self, incoming: dict[str, Any], received_at: datetime) -> str:
        prior = latest_revision(
            latest_revision(
                latest_revision(self.settings_revision, self.settings_revision_floor),
                self.bootstrap_revision,
            ),
            self._pending_command.revision if self._pending_command is not None else None,
        )
        return next_revision(prior, now=received_at)

    def _auto_snapshot_revision(self, incoming: dict[str, Any], received_at: datetime) -> str:
        # The one-shot Auto bootstrap shares the settings bootstrap timestamp.
        # The first canonical Auto response must therefore also advance beyond
        # the accepted settings revision, even when both uploads occur in one second.
        prior = latest_revision(
            latest_revision(self.settings_revision, self.settings_revision_floor),
            latest_revision(
                latest_revision(self.auto_mode_revision, self.auto_revision_floor),
                self._pending_command.revision if self._pending_command is not None else None,
            ),
        )
        return next_revision(prior, now=received_at)

    def _settings_snapshot_is_canonical_echo(
        self,
        incoming: dict[str, Any],
        *,
        permitted_changes: frozenset[str] = frozenset(),
    ) -> bool:
        """Return whether a full upload is the firmware's no-op GET echo."""

        if self.settings_snapshot is None:
            return False

        def control_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
            projected = copy.deepcopy(snapshot)
            # These fields report room observations rather than state supplied
            # by Settings GET. They can legitimately drift between the GET and
            # the firmware's unconditional follow-up saveSettings() upload.
            for key in ("current_temp", "current_humidity", "co2_id"):
                projected.pop(key, None)
            for key in permitted_changes:
                projected.pop(key, None)
            system = projected.get("system")
            if isinstance(system, dict):
                # Exact 1.5.8 live traffic proved RSSI can drift across an
                # otherwise identical echo. No other system field is exempt.
                system.pop("wifiStrength", None)
            return projected

        return control_projection(incoming) == control_projection(self.settings_snapshot)

    def _auto_snapshot_is_canonical_echo(
        self,
        incoming: dict[str, Any],
        *,
        permitted_changes: frozenset[str],
    ) -> bool:
        """Allow only the exact delivered Auto fields to differ from baseline."""

        if self.auto_mode_snapshot is None:
            return False
        expected = copy.deepcopy(self.auto_mode_snapshot)
        for key in permitted_changes:
            expected[key] = copy.deepcopy(incoming[key])
        return incoming == expected

    def prepare_partial_settings(
        self,
        section: Literal["settings", "system"],
        snapshot: dict[str, Any],
        *,
        received_at: datetime,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        """Prepare a complete subsection merge without exposing it in runtime."""

        if self.settings_snapshot is None:
            raise ControlNotReadyError
        full = copy.deepcopy(self.settings_snapshot)
        value = copy.deepcopy(snapshot)
        value.pop("sn", None)
        existing = full.get(section)
        if isinstance(existing, dict):
            merged = copy.deepcopy(existing)
            merged.update(value)
            value = merged
        full[section] = value
        revision = next_revision(
            latest_revision(self.settings_revision, self.settings_revision_floor),
            now=received_at,
        )
        candidate = self.persistent_baselines()
        candidate["settings"] = full
        candidate["settings_revision"] = revision
        candidate["settings_revision_floor"] = revision
        return revision, candidate, full

    def async_accept_partial_settings(
        self, prepared_snapshot: dict[str, Any], *, prepared_revision: str
    ) -> str:
        """Commit a prepared device-preferences or HVAC-system merge."""

        revision = prepared_revision
        self.settings_snapshot = copy.deepcopy(prepared_snapshot)
        self.settings_revision = revision
        self.settings_revision_floor = latest_revision(self.settings_revision_floor, revision)
        pending = self._pending_command
        if pending is not None and pending.kind == "settings" and not pending.delivered:
            pending.payload = command_payload(self.settings_snapshot, pending.desired)
        self.async_update_state(replace(self.state, settings_revision=revision))
        return revision

    def async_accept_current_sensors(
        self, snapshot: dict[str, Any], *, received_at: datetime
    ) -> None:
        """Merge a current room-sensor partial report."""

        if (
            self.current_temperature_observed_at is None
            or received_at >= self.current_temperature_observed_at
        ):
            self.current_temperature_observed_at = received_at
            self.current_temperature_source = "current_sensors"
            current_temperature = float(snapshot["current_temp"])
        else:
            current_temperature = self.state.current_temperature
        self.async_update_state(
            replace(
                self.state,
                current_temperature=current_temperature,
                current_humidity=float(snapshot["current_humidity"]),
                air_quality_level=int(snapshot["co2_id"]),
            )
        )

    def async_accept_current_stages(self, snapshot: dict[str, Any]) -> None:
        """Merge a current HVAC relay-stage partial report."""

        self.async_update_state(
            replace(
                self.state,
                fan_active=bool(snapshot["current_fan_status"]),
                heating_stage=int(snapshot["current_heating_stage"]),
                cooling_stage=int(snapshot["current_cooling_stage"]),
            )
        )

    def async_restore_persistent_baselines(self, data: Mapping[str, Any]) -> None:
        """Restore previously validated private baselines without marking the device online."""

        self.persistence_recovered_from_previous = data.get("recovered_from_previous") is True
        if data.get("persistence_fault") is True or self.persistence_recovered_from_previous:
            # A later durable transaction may have contained a delivered-write
            # journal. Recovery is useful for read-only telemetry, but it is not
            # proof that no command was delivered, so writes remain latched off.
            self.persistence_healthy = False
            self.persistence_fault_latched = True

        settings = data.get("settings")
        settings_revision = data.get("settings_revision")
        if settings is not None and settings_revision is not None:
            self.settings_snapshot = copy.deepcopy(settings)
            self.settings_revision = settings_revision
            self.live_data_command_time = data.get("live_data_command_time", settings_revision)
            # Room observations in a persisted settings baseline are a
            # historical upload, not live state after a Home Assistant restart.
            self._merge_settings_into_state(settings, settings_revision)

        self.settings_revision_floor = data.get("settings_revision_floor")

        auto_mode = data.get("auto_mode")
        auto_mode_revision = data.get("auto_mode_revision")
        if auto_mode is not None and auto_mode_revision is not None:
            self.auto_mode_snapshot = copy.deepcopy(auto_mode)
            self.auto_mode_revision = auto_mode_revision
            self._merge_auto_into_state(auto_mode, auto_mode_revision)

        self.auto_revision_floor = data.get("auto_revision_floor")

        bootstrap = data.get("bootstrap")
        if isinstance(bootstrap, dict):
            expires_at = bootstrap.get("expires_at")
            if isinstance(expires_at, datetime):
                self.bootstrap_revision = bootstrap["revision"]
                self.bootstrap_armed_at = bootstrap["armed_at"]
                self.bootstrap_armed_until = expires_at
                self.bootstrap_settings_served = bootstrap["settings_served"]
                self.bootstrap_auto_served = bootstrap["auto_served"]
                self._schedule_bootstrap_expiry(expires_at)

        uncertain = data.get("uncertain_command")
        if isinstance(uncertain, dict):
            kind = uncertain.get("kind")
            desired = uncertain.get("desired")
            delivered_at = uncertain.get("delivered_at")
            if (
                kind in ("settings", "auto")
                and isinstance(desired, dict)
                and (delivered_at is None or isinstance(delivered_at, datetime))
            ):
                self.uncertain_command = UncertainCommand(
                    kind=kind,
                    desired=copy.deepcopy(desired),
                    delivered_at=delivered_at,
                    revision=uncertain.get("revision"),
                )

    def _merge_settings_into_state(
        self,
        settings: dict[str, Any],
        revision: str,
        *,
        observed_at: datetime | None = None,
    ) -> None:
        current = self.state
        accept_temperature = observed_at is not None and (
            self.current_temperature_observed_at is None
            or observed_at >= self.current_temperature_observed_at
        )
        if accept_temperature:
            self.current_temperature_observed_at = observed_at
            self.current_temperature_source = "settings"
        target_temperature = float(settings["temp"])
        if (
            current.schedule_type in ACTIVE_SCHEDULE_TYPES
            and current.target_temperature is not None
        ):
            # With a synced local schedule and no temperature hold, exact QML
            # uploads the active schedule's temperature. An invalid
            # server schedule sentinel marks activity refresh as needed; during
            # that interval the same upload falls back to requestedTemp. Monitor
            # telemetry remains the authority for the effective scheduled target.
            target_temperature = current.target_temperature
        self.async_update_state(
            replace(
                current,
                target_temperature=target_temperature,
                current_temperature=(
                    float(settings["current_temp"])
                    if accept_temperature
                    else current.current_temperature
                ),
                current_humidity=(
                    float(settings["current_humidity"])
                    if observed_at is not None
                    else current.current_humidity
                ),
                mode=NuveMode(settings["mode_id"]),
                settings_revision=revision,
            )
        )

    def _merge_auto_into_state(self, settings: dict[str, Any], revision: str) -> None:
        self.async_update_state(
            replace(
                self.state,
                auto_temperature_low=float(settings["auto_temp_low"]),
                auto_temperature_high=float(settings["auto_temp_high"]),
                settings_revision=revision,
            )
        )
