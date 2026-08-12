"""Private persistence for device-originated Nuve synchronization baselines."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypedDict

from homeassistant.helpers.storage import Store

from .const import (
    BACKLIGHT_KEYS,
    DOMAIN,
    FAN_MODE_IDS,
    HOLD_PERIOD_NAMES,
    HOLD_TYPE_IDS,
    MAX_FAN_WORKING_PER_HOUR,
    MIN_FAN_WORKING_PER_HOUR,
)
from .protocol import (
    DEVICE_SETTINGS_KEYS,
    NuveProtocolError,
    normalize_night_mode_time,
    parse_auto_mode_baseline,
    parse_revision,
    parse_settings_upload,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1
PAYLOAD_SCHEMA_VERSION = 3


class StoredBaselines(TypedDict, total=False):
    """Versioned state retained in Home Assistant's private storage."""

    settings: dict[str, Any]
    settings_revision: str
    settings_revision_floor: str
    auto_mode: dict[str, float]
    auto_mode_revision: str
    auto_revision_floor: str
    live_data_command_time: str
    bootstrap: dict[str, Any]
    uncertain_command: dict[str, Any]
    recovered_from_previous: bool
    persistence_fault: bool


class NuveBaselineStore:
    """Load and save validated snapshots without exposing them in diagnostics."""

    def __init__(self, hass: HomeAssistant, entry_id: str, *, serial: str) -> None:
        self._hass = hass
        self._serial = serial
        self._last_good_envelope: dict[str, Any] | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.baselines",
            private=True,
            atomic_writes=True,
        )

    async def async_load(self, *, serial: str) -> StoredBaselines:
        """Load only complete, protocol-valid baseline pairs."""

        if serial != self._serial:
            _LOGGER.error("Refusing to load Nuve baselines for a different serial binding")
            return {"persistence_fault": True}
        existed_before_load = await self._hass.async_add_executor_job(
            os.path.exists, self._store.path
        )
        raw = await self._store.async_load()
        if raw is None:
            if existed_before_load:
                _LOGGER.error("Nuve baseline storage existed but Home Assistant could not load it")
                return {"persistence_fault": True}
            return {}
        if not isinstance(raw, dict):
            _LOGGER.error("Nuve baseline storage has a non-object payload")
            return {"persistence_fault": True}

        try:
            restored = validate_stored_baselines(raw, serial=serial, require_envelope=True)
        except NuveProtocolError as err:
            previous = raw.get("previous_good")
            try:
                if not isinstance(previous, dict):
                    raise NuveProtocolError("no previous-good baseline is available")
                restored = validate_stored_baselines(previous, serial=serial, require_envelope=True)
            except NuveProtocolError as previous_err:
                _LOGGER.error(
                    "Nuve baseline storage and its recovery copy are invalid (%s; %s)",
                    err,
                    previous_err,
                )
                return {"persistence_fault": True}
            restored["recovered_from_previous"] = True
            self._last_good_envelope = copy.deepcopy(previous)
            _LOGGER.warning("Recovered Nuve baselines from the previous-good copy after: %s", err)
            return restored

        # Preserve even a valid empty envelope as the next recovery predecessor.
        self._last_good_envelope = copy.deepcopy(raw)
        return restored

    async def async_save(self, data: dict[str, Any]) -> None:
        """Atomically save an already validated runtime projection."""

        envelope = _build_storage_envelope(
            data,
            serial=self._serial,
            previous=self._last_good_envelope,
            saved_at=datetime.now(UTC),
        )
        # Validate the exact bytes-to-be-persisted before replacing the previous
        # recoverable copy. Store itself performs the atomic filesystem replace.
        validated = validate_stored_baselines(envelope, serial=self._serial, require_envelope=True)
        for key in ("settings", "auto_mode", "uncertain_command"):
            if key in data and key not in validated:
                raise NuveProtocolError(f"prepared {key} did not survive storage validation")
        await self._store.async_save(copy.deepcopy(envelope))
        # Home Assistant's Store logs and swallows filesystem write failures,
        # and it defers writes while Core is stopping.  A returned await is not
        # therefore a durability acknowledgement.  Reload and compare the
        # exact versioned envelope before the API is allowed to ACK or expose
        # this state.
        if getattr(self._store, "_data", None) is not None:
            raise NuveProtocolError(
                "Nuve baseline storage commit was deferred and is not yet durable"
            )
        committed = await self._hass.async_add_executor_job(
            _read_committed_payload,
            self._store.path,
            self._store.version,
            self._store.minor_version,
            self._store.key,
        )
        if not isinstance(committed, dict) or _canonical_hash(committed) != _canonical_hash(
            envelope
        ):
            raise NuveProtocolError("Nuve baseline storage commit could not be verified")
        validate_stored_baselines(committed, serial=self._serial, require_envelope=True)
        self._last_good_envelope = envelope


def validate_stored_baselines(
    raw: Any, *, serial: str, require_envelope: bool = False
) -> StoredBaselines:
    """Return only complete baseline/revision pairs that still match the device."""

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        if require_envelope:
            raise NuveProtocolError("Nuve baseline storage is not an object")
        return {"persistence_fault": True}

    try:
        return _validate_current_envelope(raw, serial=serial)
    except (NuveProtocolError, ValueError) as err:
        if require_envelope:
            raise NuveProtocolError(f"Nuve baseline storage validation failed: {err}") from err
        previous = raw.get("previous_good")
        try:
            if not isinstance(previous, dict):
                raise NuveProtocolError("no previous-good baseline is available")
            restored = _validate_current_envelope(previous, serial=serial)
            restored["recovered_from_previous"] = True
        except (NuveProtocolError, ValueError) as previous_err:
            _LOGGER.warning(
                "Ignoring invalid persisted Nuve baselines (%s); recovery copy also failed (%s)",
                err,
                previous_err,
            )
            return {"persistence_fault": True}
        _LOGGER.warning("Recovered Nuve baselines from the previous-good copy after: %s", err)
        return restored


def _validate_current_envelope(raw: dict[str, Any], *, serial: str) -> StoredBaselines:
    """Validate one nonrecursive current envelope and return its runtime projection."""

    _validate_envelope_metadata(raw, serial=serial)
    if raw.get("payload_sha256") != _canonical_hash(_durable_payload(raw)):
        raise NuveProtocolError("stored durable-payload integrity hash does not match")
    restored = _validate_baseline_sections(raw, serial=serial)
    restored.update(_validate_runtime_metadata(raw))
    _validate_initial_capture(raw, serial=serial)
    uncertain = _validate_uncertain_command(raw.get("uncertain_command"))
    if uncertain is not None:
        restored["uncertain_command"] = uncertain
    return restored


def _validate_runtime_metadata(raw: dict[str, Any]) -> StoredBaselines:
    restored: StoredBaselines = {}
    for key in (
        "settings_revision_floor",
        "auto_revision_floor",
        "live_data_command_time",
    ):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise NuveProtocolError(f"stored {key} is invalid")
        parse_revision(value)
        restored[key] = value  # type: ignore[literal-required]

    settings_revision = raw.get("settings_revision")
    settings_floor = raw.get("settings_revision_floor")
    if (
        isinstance(settings_revision, str)
        and isinstance(settings_floor, str)
        and parse_revision(settings_floor) < parse_revision(settings_revision)
    ):
        raise NuveProtocolError("stored settings revision floor regressed")
    auto_revision = raw.get("auto_mode_revision")
    auto_floor = raw.get("auto_revision_floor")
    if (
        isinstance(auto_revision, str)
        and isinstance(auto_floor, str)
        and parse_revision(auto_floor) < parse_revision(auto_revision)
    ):
        raise NuveProtocolError("stored Auto revision floor regressed")

    bootstrap = raw.get("bootstrap")
    if bootstrap is None:
        return restored
    if "settings" in raw or not isinstance(bootstrap, dict):
        raise NuveProtocolError("stored bootstrap journal is incompatible with settings")
    if set(bootstrap) != {
        "revision",
        "armed_at",
        "expires_at",
        "settings_served",
        "auto_served",
    }:
        raise NuveProtocolError("stored bootstrap journal has an unexpected shape")
    revision = bootstrap.get("revision")
    if not isinstance(revision, str):
        raise NuveProtocolError("stored bootstrap revision is invalid")
    parse_revision(revision)
    armed_at = _parse_aware_datetime(bootstrap.get("armed_at"), name="bootstrap armed_at")
    expires_at = _parse_aware_datetime(bootstrap.get("expires_at"), name="bootstrap expires_at")
    settings_served = bootstrap.get("settings_served")
    auto_served = bootstrap.get("auto_served")
    if (
        expires_at <= armed_at
        or not isinstance(settings_served, bool)
        or not isinstance(auto_served, bool)
        or (auto_served and not settings_served)
    ):
        raise NuveProtocolError("stored bootstrap journal is invalid")
    for floor_key in ("settings_revision_floor", "auto_revision_floor"):
        floor = raw.get(floor_key)
        if not isinstance(floor, str) or parse_revision(floor) < parse_revision(revision):
            raise NuveProtocolError("stored bootstrap revision floor is missing")
    restored["bootstrap"] = {
        "revision": revision,
        "armed_at": armed_at,
        "expires_at": expires_at,
        "settings_served": settings_served,
        "auto_served": auto_served,
    }
    return restored


def _validate_envelope_metadata(raw: dict[str, Any], *, serial: str) -> None:
    if raw.get("storage_schema") != PAYLOAD_SCHEMA_VERSION:
        raise NuveProtocolError("legacy or unknown storage schema")
    if raw.get("serial_binding") != serial:
        raise NuveProtocolError("stored baselines belong to a different thermostat")
    commit_id = raw.get("commit_id")
    if not isinstance(commit_id, str) or re.fullmatch(r"[0-9a-f]{32}", commit_id) is None:
        raise NuveProtocolError("stored commit identity is invalid")
    complete = raw.get("complete")
    if not isinstance(complete, bool):
        raise NuveProtocolError("stored completeness marker is invalid")
    actual_complete = "settings" in raw and "auto_mode" in raw
    if complete != actual_complete:
        raise NuveProtocolError("stored completeness marker does not match its contents")
    _parse_aware_datetime(raw.get("saved_at"), name="saved_at")


def _validate_baseline_sections(raw: dict[str, Any], *, serial: str) -> StoredBaselines:
    restored: StoredBaselines = {}
    settings = raw.get("settings")
    settings_revision = raw.get("settings_revision")
    if settings is not None or settings_revision is not None:
        if not isinstance(settings_revision, str):
            raise NuveProtocolError("stored settings revision is missing")
        parse_revision(settings_revision)
        parsed_settings = parse_settings_upload(settings, serial=serial)
        if raw.get("settings_sha256") != _canonical_hash(parsed_settings):
            raise NuveProtocolError("stored settings integrity hash does not match")
        restored["settings"] = parsed_settings
        restored["settings_revision"] = settings_revision

    auto_mode = raw.get("auto_mode")
    auto_mode_revision = raw.get("auto_mode_revision")
    if auto_mode is not None or auto_mode_revision is not None:
        if not isinstance(auto_mode_revision, str):
            raise NuveProtocolError("stored Auto revision is missing")
        parse_revision(auto_mode_revision)
        parsed_auto = parse_auto_mode_baseline(auto_mode)
        if raw.get("auto_mode_sha256") != _canonical_hash(parsed_auto):
            raise NuveProtocolError("stored Auto integrity hash does not match")
        restored["auto_mode"] = parsed_auto
        restored["auto_mode_revision"] = auto_mode_revision
    return restored


def _validate_initial_capture(raw: dict[str, Any], *, serial: str) -> None:
    if "settings" not in raw:
        return
    initial = raw.get("initial_capture")
    if not isinstance(initial, dict):
        raise NuveProtocolError("immutable initial settings capture is missing")
    _parse_aware_datetime(initial.get("captured_at"), name="initial captured_at")
    revision = initial.get("settings_revision")
    if not isinstance(revision, str):
        raise NuveProtocolError("initial settings revision is missing")
    parse_revision(revision)
    settings = parse_settings_upload(initial.get("settings"), serial=serial)
    if initial.get("settings_sha256") != _canonical_hash(settings):
        raise NuveProtocolError("initial settings integrity hash does not match")
    firmware_version = initial.get("firmware_version")
    if firmware_version is not None and not isinstance(firmware_version, str):
        raise NuveProtocolError("initial firmware version is invalid")


def _validate_uncertain_command(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise NuveProtocolError("uncertain command must be an object")
    kind = value.get("kind")
    desired = value.get("desired")
    if kind not in ("settings", "auto") or not isinstance(desired, dict):
        raise NuveProtocolError("uncertain command kind or desired state is invalid")
    raw_delivered_at = value.get("delivered_at")
    delivered_at = (
        None
        if raw_delivered_at is None
        else _parse_aware_datetime(raw_delivered_at, name="uncertain command delivery time")
    )
    revision = value.get("revision")
    if revision is not None:
        if not isinstance(revision, str):
            raise NuveProtocolError("uncertain command revision is invalid")
        parse_revision(revision)
    _validate_uncertain_desired(kind, desired)
    return {
        "kind": kind,
        "desired": copy.deepcopy(desired),
        "delivered_at": delivered_at,
        "revision": revision,
    }


def _parse_aware_datetime(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise NuveProtocolError(f"{name} is missing")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise NuveProtocolError(f"{name} has no timezone")
    return parsed


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _read_committed_payload(
    path: str, version: int, minor_version: int, key: str
) -> dict[str, Any] | None:
    """Read the Store file itself, bypassing pending data and manager caches."""

    try:
        with open(path, encoding="utf-8") as handle:
            outer = json.load(handle)
    except OSError, json.JSONDecodeError:
        return None
    if not isinstance(outer, dict) or (
        outer.get("version") != version
        or outer.get("minor_version", 1) != minor_version
        or outer.get("key") != key
        or not isinstance(outer.get("data"), dict)
    ):
        return None
    return outer["data"]


def _durable_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    """Return every current durable field covered by the envelope-wide hash."""

    return {
        key: copy.deepcopy(value)
        for key, value in envelope.items()
        if key not in {"payload_sha256", "previous_good"}
    }


def _baseline_copy(envelope: dict[str, Any] | None) -> dict[str, Any] | None:
    """Copy the full previous durable state without recursive history."""

    if envelope is None:
        return None
    previous = {
        key: copy.deepcopy(value) for key, value in envelope.items() if key != "previous_good"
    }
    return previous or None


def _build_storage_envelope(
    data: dict[str, Any],
    *,
    serial: str,
    previous: dict[str, Any] | None,
    saved_at: datetime,
) -> dict[str, Any]:
    """Wrap runtime state with immutable capture and recovery metadata."""

    envelope = copy.deepcopy(data)
    envelope["storage_schema"] = PAYLOAD_SCHEMA_VERSION
    envelope["commit_id"] = uuid.uuid4().hex
    envelope["serial_binding"] = serial
    envelope["saved_at"] = saved_at.astimezone(UTC).isoformat()
    envelope["complete"] = "settings" in data and "auto_mode" in data

    if "settings" in data:
        envelope["settings_sha256"] = _canonical_hash(data["settings"])
    if "auto_mode" in data:
        envelope["auto_mode_sha256"] = _canonical_hash(data["auto_mode"])

    prior_initial = previous.get("initial_capture") if previous is not None else None
    if isinstance(prior_initial, dict):
        envelope["initial_capture"] = copy.deepcopy(prior_initial)
    elif "settings" in data and "settings_revision" in data:
        firmware = data["settings"].get("firmware")
        firmware_version = firmware.get("firmware-version") if isinstance(firmware, dict) else None
        envelope["initial_capture"] = {
            "captured_at": saved_at.astimezone(UTC).isoformat(),
            "firmware_version": firmware_version,
            "settings": copy.deepcopy(data["settings"]),
            "settings_revision": data["settings_revision"],
            "settings_sha256": _canonical_hash(data["settings"]),
        }

    envelope["previous_good"] = _baseline_copy(previous)
    envelope["payload_sha256"] = _canonical_hash(_durable_payload(envelope))
    return envelope


def _validate_uncertain_desired(kind: str, desired: dict[str, Any]) -> None:
    """Validate the narrow command surface before restoring a lockout record."""

    if not desired:
        raise NuveProtocolError("uncertain command desired state is empty")
    if kind == "settings" and "fan" in desired:
        _validate_uncertain_fan_desired(desired)
        return
    if kind == "settings" and set(desired) == {"backlight"}:
        _validate_uncertain_backlight_desired(desired["backlight"])
        return
    if kind == "settings" and set(desired) == {"settings"}:
        _validate_uncertain_device_settings_desired(desired["settings"])
        return
    allowed = {"temp", "mode_id"} if kind == "settings" else {"auto_temp_low", "auto_temp_high"}
    if not set(desired).issubset(allowed):
        raise NuveProtocolError("uncertain command contains unsupported fields")
    for key, value in desired.items():
        if key == "mode_id":
            if isinstance(value, bool) or not isinstance(value, int) or value not in (1, 2, 3, 5):
                raise NuveProtocolError("uncertain mode is invalid")
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not -50 <= float(value) <= 100
        ):
            raise NuveProtocolError(f"uncertain {key} is invalid")


def _validate_uncertain_backlight_desired(value: Any) -> None:
    """Validate a complete backlight object retained in the write journal."""

    if not isinstance(value, dict) or set(value) != BACKLIGHT_KEYS:
        raise NuveProtocolError("uncertain backlight command is invalid")
    if not isinstance(value.get("on"), bool):
        raise NuveProtocolError("uncertain backlight command is invalid")
    for key in ("hue", "value"):
        candidate = value.get(key)
        if (
            isinstance(candidate, bool)
            or not isinstance(candidate, (int, float))
            or not math.isfinite(float(candidate))
            or not 0 <= float(candidate) <= 1
        ):
            raise NuveProtocolError("uncertain backlight command is invalid")
    shade_index = value.get("shadeIndex")
    if (
        isinstance(shade_index, bool)
        or not isinstance(shade_index, int)
        or not 0 <= shade_index <= 5
    ):
        raise NuveProtocolError("uncertain backlight command is invalid")


def _validate_uncertain_device_settings_desired(value: Any) -> None:
    """Validate the complete settings subsection retained in the journal."""

    if not isinstance(value, dict) or set(value) != DEVICE_SETTINGS_KEYS:
        raise NuveProtocolError("uncertain device-settings command is invalid")
    for key in ("brightness", "speaker"):
        candidate = value.get(key)
        if (
            isinstance(candidate, bool)
            or not isinstance(candidate, int)
            or not 0 <= candidate <= 100
        ):
            raise NuveProtocolError("uncertain device-settings command is invalid")
    for key in ("brightness_mode", "temperatureUnit", "timeFormat"):
        candidate = value.get(key)
        if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate not in (0, 1):
            raise NuveProtocolError("uncertain device-settings command is invalid")
    for key in ("currentTimezone", "nightModeStart", "nightModeEnd"):
        if not isinstance(value.get(key), str):
            raise NuveProtocolError("uncertain device-settings command is invalid")
    for key in (
        "effectDst",
        "sleepModeLogo",
        "tofEnabled",
        "ledBlinkingEnabled",
        "setTimeAuto",
        "nightModeEnabled",
    ):
        if not isinstance(value.get(key), bool):
            raise NuveProtocolError("uncertain device-settings command is invalid")
    try:
        start = normalize_night_mode_time(value["nightModeStart"], name="nightModeStart")
        end = normalize_night_mode_time(value["nightModeEnd"], name="nightModeEnd")
    except NuveProtocolError as err:
        raise NuveProtocolError("uncertain device-settings command is invalid") from err
    if start == end:
        raise NuveProtocolError("uncertain device-settings command is invalid")


def _validate_uncertain_fan_desired(desired: dict[str, Any]) -> None:
    """Validate the exact fan command and optional schedule-hold companion."""

    if not set(desired).issubset({"fan", "hold_period"}):
        raise NuveProtocolError("uncertain fan command contains unsupported fields")
    fan = desired.get("fan")
    if not isinstance(fan, dict) or set(fan) != {"mode", "workingPerHour"}:
        raise NuveProtocolError("uncertain fan command is invalid")
    mode = fan.get("mode")
    working_per_hour = fan.get("workingPerHour")
    if (
        isinstance(mode, bool)
        or not isinstance(mode, int)
        or mode not in FAN_MODE_IDS
        or isinstance(working_per_hour, bool)
        or not isinstance(working_per_hour, int)
        or not MIN_FAN_WORKING_PER_HOUR <= working_per_hour <= MAX_FAN_WORKING_PER_HOUR
    ):
        raise NuveProtocolError("uncertain fan command is invalid")

    hold_period = desired.get("hold_period")
    if hold_period is None:
        return
    if not isinstance(hold_period, str) or not hold_period.strip():
        raise NuveProtocolError("uncertain fan hold is invalid")
    seen: set[int] = set()
    for raw_pair in hold_period.split(";"):
        parts = [part.strip() for part in raw_pair.split(":")]
        if len(parts) != 2:
            raise NuveProtocolError("uncertain fan hold is invalid")
        try:
            hold_type = int(parts[0])
        except ValueError as err:
            raise NuveProtocolError("uncertain fan hold is invalid") from err
        if hold_type not in HOLD_TYPE_IDS or hold_type in seen or parts[1] not in HOLD_PERIOD_NAMES:
            raise NuveProtocolError("uncertain fan hold is invalid")
        seen.add(hold_type)
