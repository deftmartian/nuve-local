"""Control readiness and canonical-response authority, derived from runtime state."""

from __future__ import annotations

from ..commands import CONTROL_SAFE_MODES
from ..commissioning import valid_technician_url
from ..const import BOOTSTRAP_FIRMWARE_ALLOWLIST, TEMP_CORRECTION_VERSIONS_BY_FIRMWARE
from ..errors import require
from .rules import NO_SCHEDULE_TYPE, SYSTEM_TYPE_NAMES, monitor_is_fresh, values_match
from .state import RuntimeState


class RuntimeReadiness(RuntimeState):
    """Read-only gates deciding whether HA writes and canonical echoes are safe."""

    __slots__ = ()

    @property
    def can_enable_control(self) -> bool:
        """Return whether fresh canonical and monitor evidence permits control."""

        return self.control_authority_block_reason is None

    @property
    def control_authority_block_reason(self) -> str | None:
        """Return the first non-secret reason canonical writes are unsafe."""

        if canonical_reason := self.canonical_response_block_reason:
            return canonical_reason
        if not self.state.available:
            return "device_unavailable"
        if not self.has_auto_mode_baseline:
            return "auto_baseline_missing"
        if not self.authoritative_control_monitor_seen:
            return "monitor_authority_missing"
        if not self.monitor_is_fresh:
            return "monitor_stale"
        if self.state.records_received < 1:
            return "monitor_records_missing"
        if self.state.current_temperature is None:
            return "current_temperature_missing"
        if self.state.target_temperature is None:
            return "target_temperature_missing"
        if self.state.mode not in CONTROL_SAFE_MODES:
            return "unsupported_mode"
        # monitor_is_fresh proved the upload time; the canonical and Auto
        # checks above proved both baselines for _live_state_matches_baselines.
        last_monitor_upload = require(self.last_monitor_upload, "fresh monitor upload time")
        if (
            self.last_settings_upload is not None
            and last_monitor_upload < self.last_settings_upload
        ):
            return "settings_newer_than_monitor"
        if not self._live_state_matches_baselines():
            return "baseline_mismatch"
        return None

    @property
    def control_block_reason(self) -> str:
        """Return why Home Assistant control is closed or ``ready``."""

        if not self.control_enabled:
            return "control_disabled"
        pending = self._pending_command
        if pending is not None:
            return (
                "command_delivered_awaiting_confirmation"
                if pending.delivered
                else "command_queued_awaiting_fetch"
            )
        if self.uncertain_command is not None:
            return "command_outcome_uncertain"
        return (
            self.control_authority_block_reason or self.schedule_authority_block_reason or "ready"
        )

    @property
    def control_ready(self) -> bool:
        """Return whether the integration can accept a new HVAC write now."""

        return self.control_block_reason == "ready"

    @property
    def schedule_authority_block_reason(self) -> str | None:
        """Return why schedule state currently forbids HA-originated writes."""

        schedule_type = self.state.schedule_type
        if schedule_type == NO_SCHEDULE_TYPE:
            return None
        if schedule_type is None:
            return "schedule_unknown"
        return "schedule_active"

    @property
    def canonical_live_consistency_ready(self) -> bool:
        """Return whether a normal whole-snapshot echo is current, not restored."""

        return (
            self.state.available
            and self.has_settings_baseline
            and self.has_auto_mode_baseline
            and self.authoritative_control_monitor_seen
            and self.monitor_is_fresh
            and self._live_state_matches_baselines()
        )

    @property
    def canonical_metadata_ready(self) -> bool:
        """Return whether every non-uploaded canonical setting is exact."""

        firmware_version = self.bootstrap_firmware_version
        if firmware_version is None:
            return False
        allowed = TEMP_CORRECTION_VERSIONS_BY_FIRMWARE.get(firmware_version)
        if allowed is None:
            return False
        value = self.temp_correction_version
        return isinstance(value, int) and not isinstance(value, bool) and value in allowed

    @property
    def canonical_response_safe(self) -> bool:
        """Return whether a whole desired-state echo is firmware-safe."""

        return self.canonical_response_block_reason is None

    @property
    def canonical_response_block_reason(self) -> str | None:
        """Return the exact non-secret prerequisite blocking a canonical echo."""

        if not self.paired:
            return "not_paired"
        if self.persistence_fault_latched:
            return "persistence_fault_latched"
        if not self.persistence_healthy:
            return "persistence_unhealthy"
        if self._persistence.listener is None:
            return "persistence_listener_missing"
        if not self.has_settings_baseline:
            return "settings_baseline_missing"
        if not self.bootstrap_metadata_confirmed:
            return "metadata_not_confirmed"
        if not self.bootstrap_no_update_confirmed:
            return "update_state_not_confirmed"
        if not valid_technician_url(self.bootstrap_technician_url):
            return "technician_url_invalid"
        if self.bootstrap_firmware_version not in BOOTSTRAP_FIRMWARE_ALLOWLIST:
            return "firmware_unsupported"
        if self.baseline_firmware_version != self.bootstrap_firmware_version:
            return "firmware_baseline_mismatch"
        if not self.canonical_metadata_ready:
            return "canonical_metadata_invalid"
        return None

    @property
    def monitor_is_fresh(self) -> bool:
        """Return whether telemetry was received recently enough to expose as live."""

        return monitor_is_fresh(
            self.last_monitor_upload, self.state.sample_time, self.state.records_received
        )

    def _live_state_matches_baselines(self) -> bool:
        """Require whole-snapshot baselines to agree with fresh telemetry."""

        settings = require(self.settings_snapshot, "settings baseline")
        auto_mode = require(self.auto_mode_snapshot, "Auto baseline")
        expected_system_type = self.setting("system", "type")
        state_system_type = self.state.system_type
        actual_system_type = (
            SYSTEM_TYPE_NAMES.get(state_system_type) if state_system_type is not None else None
        )
        return (
            values_match(
                {
                    "temp": self.state.target_temperature,
                    "humidity": self.state.target_humidity,
                    "mode_id": int(self.state.mode) if self.state.mode is not None else None,
                },
                {
                    "temp": settings.get("temp"),
                    "humidity": settings.get("humidity"),
                    "mode_id": settings.get("mode_id"),
                },
            )
            and actual_system_type == expected_system_type
            and values_match(
                {
                    "auto_temp_low": self.state.auto_temperature_low,
                    "auto_temp_high": self.state.auto_temperature_high,
                },
                auto_mode,
            )
        )

    def _effective_technician_url(self) -> str | None:
        """Use a configured QR target only after baseline capture is complete."""

        if self.has_settings_baseline and valid_technician_url(self.contractor_url):
            return self.contractor_url
        return self.bootstrap_technician_url
