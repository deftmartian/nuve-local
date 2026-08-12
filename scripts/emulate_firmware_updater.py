#!/usr/bin/env python3
"""Offline firmware 1.5.8 application-updater contract model.

This is offline research tooling. It models recovered metadata, URL, checksum,
retry, preflight, settings, and shell-install behavior without importing Nuve
Local, contacting the vendor, writing an update archive, or controlling a device.

RecoveryUpdater and systemd/process interruption are not modeled here. The
notification/manual/server and client queue state below follows the native decisions
recovered from 1.5.8.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from functools import cmp_to_key
from hashlib import md5
from numbers import Real
from typing import Any

APP_REQUIRED_KEYS = (
    "ReleaseDate",
    "ChangeLog",
    "Address",
    "RequiredMemory",
    "CurrentFileSize",
    "CheckSum",
    "Staging",
)
BACKPLATE_REQUIRED_KEYS = (
    "CurrentFileSize",
    "CheckSum",
    "Address",
    "Version",
)
RECOVERY_REQUIRED_KEYS = (
    "CurrentFileSize",
    "CheckSum",
    "Address",
    "fileName",
)

UPDATE_ARCHIVE = "/mnt/update/latestVersion/update.zip"
UPDATE_CLEANUP_TARGETS = ("/mnt/log/log/", "/mnt/log/networkLogs/")
ROOT_CLEANUP_TARGETS = (
    "/test_results.csv",
    "/usr/local/bin/updateInfo.json",
    "/usr/local/bin/files_info.json",
)
UPDATE_SERVICE_RESTART = "on-failure"
DOWNLOAD_TIMEOUT_MS = 10_000
MAX_INITIAL_RETRIES = 5
UPDATE_POLL_INTERVAL_MS = 21_600_000
METADATA_RETRY_INTERVAL_MS = 5_000
CLIENT_QUEUE_INTERVAL_MS = 10_000
RECOVERY_RETRY_INTERVAL_MS = 20_000
MAX_RECOVERY_RETRIES = 3
DNS_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"
UPDATE_SEQUENCE_SETTING = "updateSequenceOnStart"


@dataclass(frozen=True)
class ValidationDisposition:
    valid: bool
    reason: str = ""


@dataclass(frozen=True)
class ArchiveDisposition:
    ready: bool
    initial_checksum_match: bool
    reread_checksum_match: bool
    archive_written: bool
    reason: str = ""


@dataclass(frozen=True)
class RetryDisposition:
    cumulative_failures: int
    retry: bool
    clear_initial_update: bool
    emit_update_not_checked: bool
    emit_error: bool


@dataclass(frozen=True)
class InstallPreflight:
    ready: bool
    update_space_ready: bool
    root_space_ready: bool
    cleanup_attempts: tuple[str, ...]
    reason: str = ""


@dataclass(frozen=True)
class UpdateSettings:
    manual_update: bool
    firmware_server_update: bool


@dataclass(frozen=True)
class ShellInstallDisposition:
    service_exit_code: int
    source_cleaned: bool
    application_start_attempted: bool
    application_running: bool
    replacement_complete: bool
    masked_failures: tuple[str, ...]
    systemd_will_retry: bool


@dataclass(frozen=True)
class VersionSelection:
    version: str
    has_force_update: bool = False


@dataclass(frozen=True)
class PartialCheckDisposition:
    selected_version: str
    force_selected: bool
    update_available: bool
    clear_initial_setup: bool
    emit_update_not_checked: bool
    notify_new_update: bool
    start_download: bool


@dataclass(frozen=True)
class ServerTriggerDisposition:
    action: str
    clear_firmware_server_update: bool
    run_forced_check: bool
    start_specific_version: bool
    reason: str = ""


@dataclass(frozen=True)
class DnsRecordDisposition:
    remove_dns_key: bool
    queue_metadata_fetch: bool
    update_cached_timestamp: bool
    start_server_trigger: bool
    parsed_timestamp: datetime | None


@dataclass(frozen=True)
class RecoveryCompletionDisposition:
    in_process: bool
    start_retry_timer: bool
    retry_exhausted: bool


@dataclass(frozen=True)
class RecoveryTimeoutDisposition:
    invoke_updater: bool
    retries_started_after: int


@dataclass(frozen=True)
class UpdateSequenceDisposition:
    reported_on_start: bool
    persisted_after_read: bool


def _qt_value_is_rejected(value: Any) -> bool:
    """Model the narrow type-dependent predicate in ``checkUpdateFile``."""

    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, bool):
        return False
    if isinstance(value, Real):
        return value == 0
    return False


def validate_app_metadata(document: Any, *, selected_version: str) -> ValidationDisposition:
    """Validate the selected app-version object with the exact seven-key gate."""

    if not isinstance(document, dict):
        return ValidationDisposition(False, "root is not an object")
    if not selected_version or len(selected_version.split(".")) != 3:
        return ValidationDisposition(False, "selected version is not three-part")
    version_object = document.get(selected_version)
    if not isinstance(version_object, dict):
        return ValidationDisposition(False, "selected version is not an object")
    for key in APP_REQUIRED_KEYS:
        if key not in version_object:
            return ValidationDisposition(False, f"missing {key}")
        if _qt_value_is_rejected(version_object[key]):
            return ValidationDisposition(False, f"empty {key}")
    return ValidationDisposition(True)


def validate_backplate_metadata(document: Any) -> ValidationDisposition:
    """Model the backplate root-object and four-key presence check."""

    if not isinstance(document, dict):
        return ValidationDisposition(False, "root is not an object")
    for key in BACKPLATE_REQUIRED_KEYS:
        if key not in document:
            return ValidationDisposition(False, f"missing {key}")
    return ValidationDisposition(True)


def validate_recovery_metadata(document: Any) -> ValidationDisposition:
    """Model the per-entry recovery-object and four-key presence check."""

    if not isinstance(document, dict):
        return ValidationDisposition(False, "root is not an object")
    for name, value in document.items():
        if not isinstance(value, dict) or not value:
            return ValidationDisposition(False, f"{name} is not a nonempty object")
        for key in RECOVERY_REQUIRED_KEYS:
            if key not in value:
                return ValidationDisposition(False, f"{name} missing {key}")
    return ValidationDisposition(True)


def _qt_array_contains(values: Any, target: int) -> bool:
    if not isinstance(values, list):
        return False
    return any(
        isinstance(value, Real) and not isinstance(value, bool) and value == target
        for value in values
    )


def version_is_applicable(version_object: Any, *, contractor_id: int) -> bool:
    """Apply exact exclusion then Available/Forced contractor membership gates."""

    if not isinstance(version_object, dict):
        return False
    if _qt_array_contains(version_object.get("ExcludedForContractors"), contractor_id):
        return False
    return any(
        _qt_array_contains(version_object.get(key), candidate)
        for key in ("AvailableForContractors", "ForcedForContractors")
        for candidate in (0, contractor_id)
    )


def _qt_decimal_component(component: str) -> int:
    """Model the updater comparator's successful signed-32-bit decimal subset."""

    stripped = component.strip()
    if not re.fullmatch(r"[+-]?\d+", stripped):
        return 0
    value = int(stripped)
    return value if -(2**31) <= value < 2**31 else 0


def version_is_newer(candidate: str, reference: str) -> bool:
    """Compare dot-separated numeric components, padding missing/invalid parts with zero."""

    candidate_parts = candidate.split(".")
    reference_parts = reference.split(".")
    for index in range(max(len(candidate_parts), len(reference_parts))):
        candidate_value = (
            _qt_decimal_component(candidate_parts[index]) if index < len(candidate_parts) else 0
        )
        reference_value = (
            _qt_decimal_component(reference_parts[index]) if index < len(reference_parts) else 0
        )
        if candidate_value != reference_value:
            return candidate_value > reference_value
    return False


def _newest_first(versions: list[str]) -> list[str]:
    def compare(left: str, right: str) -> int:
        if version_is_newer(left, right):
            return -1
        if version_is_newer(right, left):
            return 1
        return 0

    return sorted(versions, key=cmp_to_key(compare))


def _staging_is_hidden(
    version_object: dict[str, Any], *, test_mode: bool, factory_test_mode: bool
) -> bool:
    staging = version_object.get("Staging") is True
    return staging and (not test_mode or factory_test_mode)


def select_latest_version(
    document: Any,
    *,
    contractor_id: int,
    test_mode: bool = False,
    factory_test_mode: bool = False,
) -> VersionSelection:
    """Model client-specific newest applicable, visible version selection."""

    if not isinstance(document, dict):
        return VersionSelection("")
    candidates = _newest_first(
        [key for key in document if isinstance(key, str) and key != "LatestVersion"]
    )
    for version in candidates:
        version_object = document.get(version)
        if not version_is_applicable(version_object, contractor_id=contractor_id):
            continue
        if not isinstance(version_object, dict):
            continue
        if _staging_is_hidden(
            version_object,
            test_mode=test_mode,
            factory_test_mode=factory_test_mode,
        ):
            continue
        return VersionSelection(version)
    return VersionSelection("")


def select_forced_version(
    document: Any,
    *,
    installed_version: str,
    contractor_id: int,
    test_mode: bool = False,
    factory_test_mode: bool = False,
) -> VersionSelection:
    """Model the client-specific force scan, including its oldest-match overwrite."""

    if not isinstance(document, dict):
        return VersionSelection("")
    selected = ""
    candidates = _newest_first(
        [key for key in document if isinstance(key, str) and key != "LatestVersion"]
    )
    for version in candidates:
        if not version_is_newer(version, installed_version):
            break
        version_object = document.get(version)
        if not isinstance(version_object, dict):
            continue
        if not version_is_applicable(version_object, contractor_id=contractor_id):
            continue
        # Exact client-specific code checks the current ID, not wildcard zero, here.
        if not _qt_array_contains(version_object.get("ForcedForContractors"), contractor_id):
            continue
        if _staging_is_hidden(
            version_object,
            test_mode=test_mode,
            factory_test_mode=factory_test_mode,
        ):
            continue
        # The native loop does not break, so later/older qualifying rows overwrite.
        selected = version
    return VersionSelection(selected, has_force_update=bool(selected))


def check_partial_update_disposition(
    document: Any,
    *,
    installed_version: str,
    contractor_id: int,
    notify_requested: bool,
    select_latest_directly: bool,
    manual_update: bool,
    firmware_server_update: bool,
    already_available: bool = False,
    test_mode: bool = False,
    factory_test_mode: bool = False,
) -> PartialCheckDisposition:
    """Model ``checkPartialUpdate`` after its metadata-object refresh succeeds.

    ``select_latest_directly`` is the second native boolean. It selects the latest
    applicable version instead of the force scan and starts that version even when
    it is not newer. The first boolean controls the optional user notification.
    """

    if select_latest_directly:
        selection = select_latest_version(
            document,
            contractor_id=contractor_id,
            test_mode=test_mode,
            factory_test_mode=factory_test_mode,
        )
    else:
        selection = select_forced_version(
            document,
            installed_version=installed_version,
            contractor_id=contractor_id,
            test_mode=test_mode,
            factory_test_mode=factory_test_mode,
        )

    if not selection.version:
        return PartialCheckDisposition(
            selected_version="",
            force_selected=False,
            update_available=already_available,
            clear_initial_setup=False,
            emit_update_not_checked=False,
            notify_new_update=False,
            start_download=False,
        )

    newer = version_is_newer(selection.version, installed_version)
    update_available = already_available or newer
    origin_blocks_force = manual_update or firmware_server_update
    notify = (
        newer and notify_requested and not origin_blocks_force and not selection.has_force_update
    )
    start_download = select_latest_directly or (
        selection.has_force_update and not origin_blocks_force
    )
    no_update = not update_available
    return PartialCheckDisposition(
        selected_version=selection.version,
        force_selected=selection.has_force_update,
        update_available=update_available,
        clear_initial_setup=no_update,
        emit_update_not_checked=no_update,
        notify_new_update=notify,
        start_download=start_download,
    )


def server_trigger_disposition(
    *,
    requested_version: str,
    installed_version: str,
    firmware_server_update: bool,
    manual_at_process_start: bool,
    test_mode: bool = False,
    download_timer_active: bool = False,
    restarting: bool = False,
    metadata_refresh_valid: bool = True,
) -> ServerTriggerDisposition:
    """Model the base server-trigger gates after client DNS/metadata routing."""

    if test_mode:
        return ServerTriggerDisposition("blocked", False, False, False, "test mode")
    if download_timer_active:
        return ServerTriggerDisposition("blocked", False, False, False, "download timer active")
    if restarting:
        return ServerTriggerDisposition("blocked", False, False, False, "restarting")
    if not metadata_refresh_valid:
        return ServerTriggerDisposition("blocked", False, False, False, "metadata refresh failed")
    if not requested_version:
        if not firmware_server_update:
            return ServerTriggerDisposition("none", False, False, False, "no stored server request")
        return ServerTriggerDisposition(
            "forced-check",
            clear_firmware_server_update=True,
            run_forced_check=True,
            start_specific_version=False,
        )
    if requested_version == installed_version:
        return ServerTriggerDisposition(
            "none", False, False, False, "requested version is installed"
        )
    if manual_at_process_start:
        return ServerTriggerDisposition(
            "blocked", False, False, False, "manual mode was set at process start"
        )
    return ServerTriggerDisposition(
        "specific-version",
        clear_firmware_server_update=False,
        run_forced_check=False,
        start_specific_version=True,
    )


def dns_record_disposition(
    *,
    update_type: int,
    dns_error: bool,
    first_txt_value: str | None,
    cached_timestamp: datetime | None,
) -> DnsRecordDisposition:
    """Model one client DNS TXT freshness decision.

    The native client uses only the first TXT record's first value and the exact
    ``yyyy-MM-ddTHH:mm:ss`` format. Every completion removes the DNS queue key.
    """

    if dns_error or first_txt_value is None:
        return DnsRecordDisposition(True, False, False, False, None)
    try:
        # The exact Qt format carries no offset; preserving that naive local value
        # is part of the recovered contract rather than an application timestamp.
        parsed = datetime.strptime(  # noqa: DTZ007
            first_txt_value, DNS_TIMESTAMP_FORMAT
        )
    except ValueError:
        parsed = None

    queue_fetch = cached_timestamp is None or (parsed is not None and cached_timestamp < parsed)
    return DnsRecordDisposition(
        remove_dns_key=True,
        queue_metadata_fetch=queue_fetch,
        update_cached_timestamp=queue_fetch,
        start_server_trigger=not queue_fetch and update_type == 0,
        parsed_timestamp=parsed,
    )


def recovery_completion_disposition(
    *, in_process: bool, retry_requested: bool, retries_started: int
) -> RecoveryCompletionDisposition:
    """Model the recovery completion signal and 20-second retry arming."""

    if retries_started < 0:
        raise ValueError("retries_started must be nonnegative")
    retry_candidate = retry_requested and not in_process
    return RecoveryCompletionDisposition(
        in_process=in_process,
        start_retry_timer=retry_candidate and retries_started < MAX_RECOVERY_RETRIES,
        retry_exhausted=retry_candidate and retries_started >= MAX_RECOVERY_RETRIES,
    )


def recovery_retry_timeout(*, retries_started: int) -> RecoveryTimeoutDisposition:
    """Model the timer callback's process-lifetime recovery retry property."""

    if retries_started < 0:
        raise ValueError("retries_started must be nonnegative")
    if retries_started >= MAX_RECOVERY_RETRIES:
        return RecoveryTimeoutDisposition(False, retries_started)
    return RecoveryTimeoutDisposition(True, retries_started + 1)


def consume_update_sequence_flag(stored: bool) -> UpdateSequenceDisposition:
    """Return the launch marker and its unconditional post-read stored value."""

    return UpdateSequenceDisposition(stored, persisted_after_read=False)


def serial_query_id(serial: bytes) -> str:
    """Return the stable lowercase MD5 hex identifier sent in updater queries."""

    return md5(serial, usedforsecurity=False).hexdigest()


def metadata_url(*, base_url: str, file_name: str, serial: bytes) -> str:
    return f"{base_url.rstrip('/')}/{file_name.lstrip('/')}?id={serial_query_id(serial)}"


def payload_url(*, base_url: str, address: str, serial: bytes) -> str:
    normalized_address = address if address.startswith("/") else f"/{address}"
    return f"{base_url.rstrip('/')}{normalized_address}?id={serial_query_id(serial)}"


def _decode_expected_md5(checksum_hex: str) -> bytes | None:
    """Decode the accepted 16-byte subset without over-modeling Qt malformed input."""

    if len(checksum_hex) != 32:
        return None
    try:
        return bytes.fromhex(checksum_hex)
    except ValueError:
        return None


def verify_and_stage_archive(
    payload: bytes,
    *,
    checksum_hex: str,
    reread_payload: bytes | None = None,
) -> ArchiveDisposition:
    """Model MD5 validation, file write, re-read, and readiness signaling.

    The firmware uses ``QByteArray::fromHex``. This emulator accepts only a
    32-hex-character MD5 string; odd and non-hex Qt edge
    coercions remain outside the proven model.
    """

    expected = _decode_expected_md5(checksum_hex)
    if expected is None:
        return ArchiveDisposition(False, False, False, False, "noncanonical checksum")
    initial_match = md5(payload, usedforsecurity=False).digest() == expected
    if not initial_match:
        return ArchiveDisposition(False, False, False, False, "download checksum mismatch")
    reread = payload if reread_payload is None else reread_payload
    reread_match = md5(reread, usedforsecurity=False).digest() == expected
    return ArchiveDisposition(
        ready=reread_match,
        initial_checksum_match=True,
        reread_checksum_match=reread_match,
        archive_written=True,
        reason="" if reread_match else "stored archive checksum mismatch",
    )


def download_failure_disposition(
    *, initial_setup: bool, backdoor: bool, cumulative_failures: int
) -> RetryDisposition:
    """Model the process-static initial-setup failure counter and sixth abort."""

    if cumulative_failures < 0:
        raise ValueError("cumulative_failures must be nonnegative")
    if not initial_setup or backdoor:
        return RetryDisposition(
            cumulative_failures,
            retry=False,
            clear_initial_update=False,
            emit_update_not_checked=False,
            emit_error=True,
        )
    failures = cumulative_failures + 1
    retry = failures <= MAX_INITIAL_RETRIES
    return RetryDisposition(
        failures,
        retry=retry,
        clear_initial_update=not retry,
        emit_update_not_checked=not retry,
        emit_error=False,
    )


def install_preflight(
    *,
    required_bytes: int,
    update_free_before: int,
    update_free_after_cleanup: int,
    root_free_before: int,
    root_free_after_cleanup: int,
    current_app_size: int,
) -> InstallPreflight:
    """Model strict free-space gates and their ordered cleanup attempts."""

    cleanup: list[str] = []
    update_ready = required_bytes < update_free_before
    if not update_ready:
        cleanup.extend(UPDATE_CLEANUP_TARGETS)
        update_ready = required_bytes < update_free_after_cleanup
    if not update_ready:
        return InstallPreflight(
            False,
            update_space_ready=False,
            root_space_ready=False,
            cleanup_attempts=tuple(cleanup),
            reason="insufficient update filesystem space",
        )

    root_ready = required_bytes < root_free_before + current_app_size
    if not root_ready:
        cleanup.extend(ROOT_CLEANUP_TARGETS)
        root_ready = required_bytes < root_free_after_cleanup + current_app_size
    return InstallPreflight(
        root_ready,
        update_space_ready=True,
        root_space_ready=root_ready,
        cleanup_attempts=tuple(cleanup),
        reason="" if root_ready else "insufficient application filesystem space",
    )


def update_settings(
    *, backdoor: bool, reset_to_version: bool, firmware_server_version: bool
) -> UpdateSettings:
    """Model the two persisted update-origin flags written before service start."""

    return UpdateSettings(
        manual_update=backdoor or reset_to_version,
        firmware_server_update=firmware_server_version,
    )


def simulate_update_script(
    *,
    unzip_ok: bool = True,
    gunzip_ok: bool = True,
    stop_ok: bool = True,
    copy_ok: bool = True,
    start_ok: bool = True,
) -> ShellInstallDisposition:
    """Model the archive-present branch of the embedded update shell script.

    The script has no fail-fast mode or command-result checks. It attempts cleanup
    and application start, then exits zero even when one or more commands fail.
    """

    outcomes = {
        "unzip": unzip_ok,
        "gunzip": gunzip_ok,
        "stop": stop_ok,
        "copy": copy_ok,
        "start": start_ok,
    }
    failures = tuple(name for name, succeeded in outcomes.items() if not succeeded)
    exit_code = 0
    return ShellInstallDisposition(
        service_exit_code=exit_code,
        source_cleaned=True,
        application_start_attempted=True,
        application_running=start_ok,
        replacement_complete=unzip_ok and gunzip_ok and copy_ok,
        masked_failures=failures,
        systemd_will_retry=exit_code != 0 and UPDATE_SERVICE_RESTART == "on-failure",
    )
