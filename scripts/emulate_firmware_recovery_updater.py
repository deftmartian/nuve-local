#!/usr/bin/env python3
"""Offline firmware 1.5.8 RecoveryUpdater contract model.

This is offline research tooling. It models the recovered p4 file planner,
free-space cleanup order, argv construction, retry disposition, file-info shape,
and copy completion gate. It does not contact the vendor, mount an image, write a
recovery partition, execute an updater process, or control a device.

Malformed QJson numeric conversions, permissive ``QByteArray::fromHex`` edge
cases, asynchronous cancellation, and real filesystem/process durability are not
modeled.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from pathlib import PurePosixPath
from typing import Any

RECOVERY_DIRECTORY = "/mnt/recovery/"
RECOVERY_DOWNLOAD_DIRECTORY = "/mnt/log/download/recovery"
RECOVERY_FILE_INFO = "/mnt/recovery/filesInfo.json"
RECOVERY_RESERVE_BYTES = 1_048_576
RECOVERY_CLEANUP_TARGETS = (
    "/usr/local/bin",
    "/mnt/log/log/",
    "/mnt/log/networkLogs/",
)
RECOVERY_FILE_INFO_MAX_AGE_SECONDS = 2_592_000

RECOVERY_WGET_PROGRAM = "ionice"
RECOVERY_WGET_PREFIX = ("-c3", "nice", "-n", "19", "wget", "-c")
RECOVERY_COPY_PROGRAM = "ionice"
RECOVERY_COPY_PREFIX = (
    "-c3",
    "nice",
    "-n 19",
    "rsync",
    "-a",
    "-c",
    "--whole-file",
    "--inplace",
    "--remove-source-files",
)


@dataclass(frozen=True)
class FileObservation:
    """A synthetic regular-file observation used by the offline planner."""

    exists: bool = False
    size: int = 0
    checksum: str = ""


@dataclass(frozen=True)
class RecoveryPlan:
    cached_current: tuple[str, ...]
    staged_for_copy: tuple[str, ...]
    downloads: tuple[tuple[str, str], ...]
    required_recovery_bytes: int
    required_download_bytes: int

    @property
    def next_action(self) -> str:
        if self.downloads:
            return "preflight_then_download"
        if self.staged_for_copy:
            return "copy_without_preflight"
        return "finish_without_copy"


@dataclass(frozen=True)
class RecoveryPreflight:
    ready: bool
    cleanup_attempts: tuple[str, ...]
    reason: str = ""


@dataclass(frozen=True)
class RecoveryDownloadDisposition:
    remove_pending_entry: bool
    append_to_copy_list: bool
    remove_staged_file: bool
    immediately_retry: bool


@dataclass(frozen=True)
class RecoveryCopyDisposition:
    success: bool
    error: bool
    in_process_after: bool
    download_directory_cleaned: bool
    file_info_rebuilt: bool
    reason: str


def _qt_json_int(value: Any) -> int:
    """Model the ordinary integral, signed-32-bit QJsonValue::toInt subset."""

    if isinstance(value, bool) or not isinstance(value, Real):
        return 0
    converted = int(value)
    if converted != value or not -(2**31) <= converted < 2**31:
        return 0
    return converted


def _md5_bytes(value: Any) -> bytes | None:
    """Decode the MD5 text accepted by the public fixtures."""

    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", value):
        return None
    return bytes.fromhex(value)


def _file_info_records(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict) or not isinstance(document.get("files"), list):
        return []
    return [item for item in document["files"] if isinstance(item, dict)]


def _cached_checksum_for(records: Sequence[dict[str, Any]], name: str) -> Any:
    for record in records:
        if record.get("Name") == name:
            return record.get("CheckSum")
    return None


def _observation(observations: Mapping[str, FileObservation], name: str) -> FileObservation:
    return observations.get(name, FileObservation())


def plan_recovery_update(
    manifest: Any,
    *,
    files_info: Any,
    staged_files: Mapping[str, FileObservation],
    recovery_files: Mapping[str, FileObservation],
) -> RecoveryPlan:
    """Model exact planning for the normal, well-typed recovery metadata subset.

    ``QJsonObject::keys()`` supplies the native loop in sorted key order. A cache
    Name/CheckSum match suppresses all destination and staged-file checks. For a
    needed item, the recovered implementation updates its recovery-space counter
    cumulatively, then subtracts the current destination size from that cumulative
    value and clamps at zero.
    """

    if not isinstance(manifest, dict):
        return RecoveryPlan((), (), (), 0, 0)

    records = _file_info_records(files_info)
    cached_current: list[str] = []
    staged_for_copy: list[str] = []
    downloads: list[tuple[str, str]] = []
    required_recovery = 0
    required_download = 0

    for key in sorted(manifest):
        value = manifest[key]
        if not isinstance(value, dict) or not value:
            continue

        name_value = value.get("fileName")
        name = name_value if isinstance(name_value, str) else ""
        expected_checksum = _md5_bytes(value.get("CheckSum"))
        cached_checksum = _md5_bytes(_cached_checksum_for(records, name))
        if cached_checksum == expected_checksum and expected_checksum is not None:
            cached_current.append(name)
            continue

        expected_size = _qt_json_int(value.get("CurrentFileSize"))
        staged = _observation(staged_files, name)
        if staged.exists and _md5_bytes(staged.checksum) == expected_checksum:
            staged_for_copy.append(name)
        else:
            address_value = value.get("Address")
            address = address_value if isinstance(address_value, str) else ""
            downloads.append((str(key), address))
            staged_size = staged.size if staged.exists else 0
            required_download += max(0, expected_size - staged_size)

        required_recovery += expected_size
        destination = _observation(recovery_files, name)
        if destination.exists:
            required_recovery = max(0, required_recovery - destination.size)

    return RecoveryPlan(
        tuple(cached_current),
        tuple(staged_for_copy),
        tuple(downloads),
        required_recovery,
        required_download,
    )


def recovery_preflight(
    *,
    required_recovery_bytes: int,
    required_download_bytes: int,
    recovery_storage_valid: bool,
    download_storage_valid: bool,
    recovery_available: int,
    download_available_initial: int,
    download_available_after_app_cleanup: int | None = None,
    download_available_after_log_cleanup: int | None = None,
) -> RecoveryPreflight:
    """Model the exact 1 MiB reserve and destructive cleanup sequence."""

    if not recovery_storage_valid or not download_storage_valid:
        return RecoveryPreflight(False, (), "storage path remains invalid")

    recovery_threshold = required_recovery_bytes + RECOVERY_RESERVE_BYTES
    if recovery_available < recovery_threshold:
        return RecoveryPreflight(False, (), "insufficient recovery storage")

    download_threshold = required_download_bytes + RECOVERY_RESERVE_BYTES
    if download_available_initial >= download_threshold:
        return RecoveryPreflight(True, ())

    cleanup_attempts = [RECOVERY_CLEANUP_TARGETS[0]]
    after_app = (
        download_available_initial
        if download_available_after_app_cleanup is None
        else download_available_after_app_cleanup
    )
    if after_app >= download_threshold:
        return RecoveryPreflight(True, tuple(cleanup_attempts))

    cleanup_attempts.extend(RECOVERY_CLEANUP_TARGETS[1:])
    after_logs = (
        after_app
        if download_available_after_log_cleanup is None
        else download_available_after_log_cleanup
    )
    if after_logs >= download_threshold:
        return RecoveryPreflight(True, tuple(cleanup_attempts))
    return RecoveryPreflight(False, tuple(cleanup_attempts), "insufficient download storage")


def recovery_wget_command(
    *, base_url: str, address: str, file_name: str
) -> tuple[str, tuple[str, ...]]:
    """Return the exact ProcessExecutor program and ordinary recovered argv."""

    destination = f"{RECOVERY_DOWNLOAD_DIRECTORY}/{file_name}"
    return (
        RECOVERY_WGET_PROGRAM,
        (*RECOVERY_WGET_PREFIX, f"{base_url}{address}", "-O", destination),
    )


def recovery_copy_command(
    file_names: Sequence[str], *, existing_staged_names: set[str]
) -> tuple[str, tuple[str, ...]]:
    """Return the exact rsync wrapper argv, filtering absent staged paths."""

    sources = tuple(
        f"{RECOVERY_DOWNLOAD_DIRECTORY}/{name}"
        for name in file_names
        if name in existing_staged_names
    )
    return (
        RECOVERY_COPY_PROGRAM,
        RECOVERY_COPY_PREFIX + sources + (RECOVERY_DIRECTORY,),
    )


def chmod_result_is_accepted(exit_code: int) -> bool:
    """The native unsigned comparison rejects QProcess -2/-1, not ordinary exits."""

    return exit_code not in (-2, -1)


def recovery_download_disposition(
    *, exit_code: int, checksum_matches: bool, pending_entries_before: int
) -> RecoveryDownloadDisposition:
    """Model one download callback and its immediate recursion decision."""

    verified = exit_code == 0 and checksum_matches
    mismatch = exit_code == 0 and not checksum_matches
    remaining = pending_entries_before - (1 if verified else 0)
    return RecoveryDownloadDisposition(
        remove_pending_entry=verified,
        append_to_copy_list=verified,
        remove_staged_file=mismatch,
        immediately_retry=remaining > 0,
    )


def recovery_copy_disposition(
    manifest: Any,
    *,
    process_present: bool,
    normal_exit: bool,
    exit_code: int,
    destination_checksums: Mapping[str, str],
) -> RecoveryCopyDisposition:
    """Model the exact copy callback and its in-process latch behavior."""

    if not process_present or not normal_exit or exit_code != 0:
        return RecoveryCopyDisposition(
            False,
            True,
            True,
            False,
            False,
            "copy process absent, crashed, or returned nonzero",
        )

    verified = isinstance(manifest, dict)
    if verified:
        for key in sorted(manifest):
            value = manifest[key]
            if not isinstance(value, dict):
                verified = False
                break
            name_value = value.get("fileName")
            name = name_value if isinstance(name_value, str) else ""
            if _md5_bytes(destination_checksums.get(name)) != _md5_bytes(value.get("CheckSum")):
                verified = False
                break

    return RecoveryCopyDisposition(
        success=verified,
        error=not verified,
        in_process_after=False,
        download_directory_cleaned=verified,
        file_info_rebuilt=True,
        reason="all destination checksums match" if verified else "checksum mismatch",
    )


def _complete_suffix(name: str) -> str:
    trimmed = name.rsplit("/", maxsplit=1)[-1]
    if "." not in trimmed or (trimmed.startswith(".") and trimmed.count(".") == 1):
        return ""
    return trimmed.split(".", maxsplit=1)[1]


def build_recovery_files_info(
    observations: Sequence[tuple[str, FileObservation]],
) -> dict[str, list[dict[str, Any]]]:
    """Build the recovered ``files`` array for normal regular-file fixtures."""

    files: list[dict[str, Any]] = []
    for name, observation in observations:
        if "json" in _complete_suffix(name):
            continue
        if not observation.exists or observation.size <= 0:
            continue
        if _md5_bytes(observation.checksum) is None:
            continue
        files.append(
            {
                "Name": name,
                "CheckSum": observation.checksum,
                "CurrentFileSize": observation.size,
            }
        )
    return {"files": files}


def recovery_path_has_traversal(file_name: str) -> bool:
    """Flag parent traversal the native string concatenation does not reject."""

    path = PurePosixPath(file_name)
    return ".." in path.parts
