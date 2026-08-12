"""Independent checks for exact-1.5.8 RecoveryUpdater behavior."""

from __future__ import annotations

from scripts.emulate_firmware_recovery_updater import (
    RECOVERY_CLEANUP_TARGETS,
    RECOVERY_COPY_PREFIX,
    RECOVERY_DIRECTORY,
    RECOVERY_DOWNLOAD_DIRECTORY,
    RECOVERY_FILE_INFO_MAX_AGE_SECONDS,
    RECOVERY_RESERVE_BYTES,
    FileObservation,
    build_recovery_files_info,
    chmod_result_is_accepted,
    plan_recovery_update,
    recovery_copy_command,
    recovery_copy_disposition,
    recovery_download_disposition,
    recovery_path_has_traversal,
    recovery_preflight,
    recovery_wget_command,
)

BOOT_MD5 = "c9f3352f9b45b67ec9c2af3632ab1ad1"
ROOT_MD5 = "691ae1541f4d612ab8c4e0650527e66d"


def _entry(name: str, checksum: str, size: int, address: str) -> dict[str, object]:
    return {
        "fileName": name,
        "CheckSum": checksum,
        "CurrentFileSize": size,
        "Address": address,
    }


def test_cached_name_and_checksum_suppress_destination_and_stage_checks() -> None:
    manifest = {"boot": _entry("boot.gz", BOOT_MD5, 100, "/boot.gz")}
    files_info = {"files": [{"Name": "boot.gz", "CheckSum": BOOT_MD5, "CurrentFileSize": 100}]}
    plan = plan_recovery_update(
        manifest,
        files_info=files_info,
        staged_files={"boot.gz": FileObservation(True, 100, "00" * 16)},
        recovery_files={},
    )
    assert plan.cached_current == ("boot.gz",)
    assert plan.next_action == "finish_without_copy"
    assert plan.required_recovery_bytes == 0


def test_verified_stage_is_copied_without_download_preflight() -> None:
    manifest = {"root": _entry("root.gz", ROOT_MD5, 200, "/root.gz")}
    plan = plan_recovery_update(
        manifest,
        files_info={},
        staged_files={"root.gz": FileObservation(True, 200, ROOT_MD5)},
        recovery_files={},
    )
    assert plan.staged_for_copy == ("root.gz",)
    assert plan.downloads == ()
    assert plan.required_recovery_bytes == 200
    assert plan.next_action == "copy_without_preflight"


def test_download_plan_uses_manifest_key_address_and_partial_stage_size() -> None:
    manifest = {"root-slot": _entry("root.gz", ROOT_MD5, 200, "/root.gz")}
    plan = plan_recovery_update(
        manifest,
        files_info={"files": []},
        staged_files={"root.gz": FileObservation(True, 75, "00" * 16)},
        recovery_files={"root.gz": FileObservation(True, 50, "11" * 16)},
    )
    assert plan.downloads == (("root-slot", "/root.gz"),)
    assert plan.required_download_bytes == 125
    assert plan.required_recovery_bytes == 150
    assert plan.next_action == "preflight_then_download"


def test_recovery_space_counter_is_cumulative_then_clamped_per_destination() -> None:
    manifest = {
        "a": _entry("a.bin", "11" * 16, 100, "/a"),
        "b": _entry("b.bin", "22" * 16, 100, "/b"),
    }
    plan = plan_recovery_update(
        manifest,
        files_info={},
        staged_files={},
        recovery_files={
            "a.bin": FileObservation(True, 150, ""),
            "b.bin": FileObservation(True, 25, ""),
        },
    )
    assert plan.required_recovery_bytes == 75  # max(0, 100-150), then +100-25


def test_preflight_requires_one_mib_reserve_and_accepts_exact_equality() -> None:
    threshold = 7 + RECOVERY_RESERVE_BYTES
    result = recovery_preflight(
        required_recovery_bytes=7,
        required_download_bytes=7,
        recovery_storage_valid=True,
        download_storage_valid=True,
        recovery_available=threshold,
        download_available_initial=threshold,
    )
    assert result.ready
    assert result.cleanup_attempts == ()


def test_download_shortage_wipes_app_directory_before_logs() -> None:
    result = recovery_preflight(
        required_recovery_bytes=0,
        required_download_bytes=100,
        recovery_storage_valid=True,
        download_storage_valid=True,
        recovery_available=RECOVERY_RESERVE_BYTES,
        download_available_initial=0,
        download_available_after_app_cleanup=50,
        download_available_after_log_cleanup=RECOVERY_RESERVE_BYTES + 100,
    )
    assert result.ready
    assert result.cleanup_attempts == RECOVERY_CLEANUP_TARGETS
    assert RECOVERY_CLEANUP_TARGETS[0] == "/usr/local/bin"


def test_recovery_shortage_does_not_attempt_download_cleanup() -> None:
    result = recovery_preflight(
        required_recovery_bytes=1,
        required_download_bytes=0,
        recovery_storage_valid=True,
        download_storage_valid=True,
        recovery_available=RECOVERY_RESERVE_BYTES,
        download_available_initial=RECOVERY_RESERVE_BYTES,
    )
    assert not result.ready
    assert result.cleanup_attempts == ()


def test_wget_argv_is_low_priority_resumable_plain_url_to_stage_path() -> None:
    program, args = recovery_wget_command(
        base_url="http://update.example.invalid",
        address="/recovery/root.gz",
        file_name="root.gz",
    )
    assert program == "ionice"
    assert args == (
        "-c3",
        "nice",
        "-n",
        "19",
        "wget",
        "-c",
        "http://update.example.invalid/recovery/root.gz",
        "-O",
        f"{RECOVERY_DOWNLOAD_DIRECTORY}/root.gz",
    )


def test_rsync_argv_contains_combined_nice_argument_and_inplace_removal() -> None:
    program, args = recovery_copy_command(
        ["missing.gz", "boot.gz", "root.gz"],
        existing_staged_names={"boot.gz", "root.gz"},
    )
    assert program == "ionice"
    assert RECOVERY_COPY_PREFIX[2] == "-n 19"
    assert args == (
        *RECOVERY_COPY_PREFIX,
        f"{RECOVERY_DOWNLOAD_DIRECTORY}/boot.gz",
        f"{RECOVERY_DOWNLOAD_DIRECTORY}/root.gz",
        RECOVERY_DIRECTORY,
    )
    assert "--inplace" in args
    assert "--remove-source-files" in args


def test_ordinary_nonzero_chmod_exit_is_accepted() -> None:
    assert chmod_result_is_accepted(0)
    assert chmod_result_is_accepted(1)
    assert chmod_result_is_accepted(127)
    assert not chmod_result_is_accepted(-2)
    assert not chmod_result_is_accepted(-1)


def test_failed_download_and_checksum_mismatch_retain_entry_for_immediate_retry() -> None:
    failed = recovery_download_disposition(
        exit_code=4, checksum_matches=False, pending_entries_before=1
    )
    assert failed.immediately_retry
    assert not failed.remove_pending_entry
    assert not failed.remove_staged_file

    mismatch = recovery_download_disposition(
        exit_code=0, checksum_matches=False, pending_entries_before=1
    )
    assert mismatch.immediately_retry
    assert mismatch.remove_staged_file
    assert not mismatch.remove_pending_entry


def test_verified_download_removes_pending_entry_and_advances_to_copy() -> None:
    result = recovery_download_disposition(
        exit_code=0, checksum_matches=True, pending_entries_before=1
    )
    assert result.remove_pending_entry
    assert result.append_to_copy_list
    assert not result.immediately_retry


def test_copy_process_failure_leaves_in_process_latched() -> None:
    result = recovery_copy_disposition(
        {"boot": _entry("boot.gz", BOOT_MD5, 100, "/boot.gz")},
        process_present=True,
        normal_exit=True,
        exit_code=1,
        destination_checksums={},
    )
    assert not result.success and result.error
    assert result.in_process_after
    assert not result.file_info_rebuilt


def test_copy_checksum_failure_clears_latch_but_keeps_download_directory() -> None:
    result = recovery_copy_disposition(
        {"boot": _entry("boot.gz", BOOT_MD5, 100, "/boot.gz")},
        process_present=True,
        normal_exit=True,
        exit_code=0,
        destination_checksums={"boot.gz": "00" * 16},
    )
    assert not result.success and result.error
    assert not result.in_process_after
    assert result.file_info_rebuilt
    assert not result.download_directory_cleaned


def test_copy_success_rechecks_every_manifest_destination_then_cleans() -> None:
    manifest = {
        "boot": _entry("boot.gz", BOOT_MD5, 100, "/boot.gz"),
        "root": _entry("root.gz", ROOT_MD5, 200, "/root.gz"),
    }
    result = recovery_copy_disposition(
        manifest,
        process_present=True,
        normal_exit=True,
        exit_code=0,
        destination_checksums={"boot.gz": BOOT_MD5, "root.gz": ROOT_MD5},
    )
    assert result.success and not result.error
    assert not result.in_process_after
    assert result.download_directory_cleaned
    assert result.file_info_rebuilt


def test_file_info_schema_excludes_json_and_records_name_md5_and_size() -> None:
    result = build_recovery_files_info(
        [
            ("boot.gz", FileObservation(True, 100, BOOT_MD5)),
            ("cpuLoad.json", FileObservation(True, 50, "33" * 16)),
            ("nested.data.json", FileObservation(True, 50, "44" * 16)),
            ("empty.bin", FileObservation(True, 0, "55" * 16)),
        ]
    )
    assert result == {"files": [{"Name": "boot.gz", "CheckSum": BOOT_MD5, "CurrentFileSize": 100}]}
    assert RECOVERY_FILE_INFO_MAX_AGE_SECONDS == 30 * 24 * 60 * 60


def test_manifest_file_name_is_concatenated_without_traversal_rejection() -> None:
    name = "../../usr/local/bin/replacement"
    _, wget_args = recovery_wget_command(
        base_url="http://update.example.invalid", address="/payload", file_name=name
    )
    _, copy_args = recovery_copy_command([name], existing_staged_names={name})
    assert f"{RECOVERY_DOWNLOAD_DIRECTORY}/{name}" in wget_args
    assert f"{RECOVERY_DOWNLOAD_DIRECTORY}/{name}" in copy_args
    assert recovery_path_has_traversal(name)
    assert not recovery_path_has_traversal("/absolute")
    assert not recovery_path_has_traversal("boot.gz")
