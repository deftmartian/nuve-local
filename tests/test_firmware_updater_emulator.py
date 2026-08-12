"""Independent checks for exact-1.5.8 application-updater behavior."""

from __future__ import annotations

from datetime import datetime
from hashlib import md5

import pytest

from scripts.emulate_firmware_updater import (
    APP_REQUIRED_KEYS,
    BACKPLATE_REQUIRED_KEYS,
    CLIENT_QUEUE_INTERVAL_MS,
    DNS_TIMESTAMP_FORMAT,
    DOWNLOAD_TIMEOUT_MS,
    MAX_INITIAL_RETRIES,
    MAX_RECOVERY_RETRIES,
    METADATA_RETRY_INTERVAL_MS,
    RECOVERY_REQUIRED_KEYS,
    RECOVERY_RETRY_INTERVAL_MS,
    ROOT_CLEANUP_TARGETS,
    UPDATE_CLEANUP_TARGETS,
    UPDATE_POLL_INTERVAL_MS,
    UPDATE_SEQUENCE_SETTING,
    check_partial_update_disposition,
    consume_update_sequence_flag,
    dns_record_disposition,
    download_failure_disposition,
    install_preflight,
    metadata_url,
    payload_url,
    recovery_completion_disposition,
    recovery_retry_timeout,
    select_forced_version,
    select_latest_version,
    serial_query_id,
    server_trigger_disposition,
    simulate_update_script,
    update_settings,
    validate_app_metadata,
    validate_backplate_metadata,
    validate_recovery_metadata,
    verify_and_stage_archive,
    version_is_applicable,
    version_is_newer,
)


def _app_document(**overrides: object) -> dict[str, object]:
    version: dict[str, object] = {
        "ReleaseDate": "11/8/2026",
        "ChangeLog": "Synthetic fixture",
        "Address": "/synthetic/update.zip",
        "RequiredMemory": 1,
        "CurrentFileSize": 1,
        "CheckSum": "00" * 16,
        "Staging": False,
    }
    version.update(overrides)
    return {"1.2.3": version}


def test_app_metadata_requires_exact_seven_keys_and_three_part_version() -> None:
    assert APP_REQUIRED_KEYS == (
        "ReleaseDate",
        "ChangeLog",
        "Address",
        "RequiredMemory",
        "CurrentFileSize",
        "CheckSum",
        "Staging",
    )
    assert validate_app_metadata(_app_document(), selected_version="1.2.3").valid
    assert not validate_app_metadata(_app_document(), selected_version="1.2").valid
    for key in APP_REQUIRED_KEYS:
        document = _app_document()
        del document["1.2.3"][key]  # type: ignore[index]
        assert not validate_app_metadata(document, selected_version="1.2.3").valid


@pytest.mark.parametrize("value", [None, "", 0, 0.0])
def test_app_metadata_rejects_null_empty_string_and_numeric_zero(value: object) -> None:
    assert not validate_app_metadata(_app_document(Address=value), selected_version="1.2.3").valid


@pytest.mark.parametrize("value", [False, True, [], {}, ["unexpected"]])
def test_app_metadata_weak_type_gate_accepts_bool_array_and_object(value: object) -> None:
    assert validate_app_metadata(_app_document(Address=value), selected_version="1.2.3").valid


def test_force_and_contractor_keys_are_optional_to_app_syntax_gate() -> None:
    document = _app_document()
    assert not any(
        key in document["1.2.3"]
        for key in (
            "ForceUpdate",
            "ExcludedForContractors",
            "AvailableForContractors",
            "ForcedForContractors",
        )
    )
    assert validate_app_metadata(document, selected_version="1.2.3").valid


def test_backplate_and_recovery_validators_check_presence_not_value_types() -> None:
    assert BACKPLATE_REQUIRED_KEYS == (
        "CurrentFileSize",
        "CheckSum",
        "Address",
        "Version",
    )
    assert validate_backplate_metadata({key: None for key in BACKPLATE_REQUIRED_KEYS}).valid
    assert not validate_backplate_metadata({"Address": "present"}).valid

    assert RECOVERY_REQUIRED_KEYS == (
        "CurrentFileSize",
        "CheckSum",
        "Address",
        "fileName",
    )
    valid = {"synthetic": {key: None for key in RECOVERY_REQUIRED_KEYS}}
    assert validate_recovery_metadata(valid).valid
    assert not validate_recovery_metadata({"synthetic": {}}).valid
    assert validate_recovery_metadata({}).valid  # exact per-entry loop is vacuous


def test_contractor_exclusion_wins_and_zero_is_a_wildcard() -> None:
    assert version_is_applicable({"AvailableForContractors": [0]}, contractor_id=42)
    assert version_is_applicable({"ForcedForContractors": [42]}, contractor_id=42)
    assert not version_is_applicable(
        {
            "ExcludedForContractors": [42],
            "AvailableForContractors": [0, 42],
            "ForcedForContractors": [42],
        },
        contractor_id=42,
    )
    assert not version_is_applicable({}, contractor_id=42)
    assert not version_is_applicable({"AvailableForContractors": [False]}, contractor_id=0)


def test_version_comparator_is_numeric_variable_length_and_invalid_is_zero() -> None:
    assert version_is_newer("1.10.0", "1.9.99")
    assert version_is_newer("2", "1.999.999")
    assert not version_is_newer("1.2", "1.2.0")
    assert not version_is_newer("1.invalid.0", "1.0.0")
    assert version_is_newer("1.invalid.1", "1.0.0")
    assert not version_is_newer(str(2**31), "1")  # overflow becomes zero


def test_latest_selects_newest_applicable_and_removes_latestversion_marker() -> None:
    document = {
        "LatestVersion": "9.9.9",
        "1.2.0": {"AvailableForContractors": [42], "Staging": False},
        "1.10.0": {"AvailableForContractors": [42], "Staging": False},
        "2.0.0": {"AvailableForContractors": [7], "Staging": False},
    }
    assert select_latest_version(document, contractor_id=42).version == "1.10.0"


def test_staging_is_visible_only_in_nonfactory_test_mode() -> None:
    document = {
        "2.0.0": {"AvailableForContractors": [42], "Staging": True},
        "1.0.0": {"AvailableForContractors": [42], "Staging": False},
    }
    assert select_latest_version(document, contractor_id=42).version == "1.0.0"
    assert select_latest_version(document, contractor_id=42, test_mode=True).version == "2.0.0"
    assert (
        select_latest_version(
            document,
            contractor_id=42,
            test_mode=True,
            factory_test_mode=True,
        ).version
        == "1.0.0"
    )


def test_force_scan_uses_exact_contractor_not_wildcard_or_forceupdate_scalar() -> None:
    document = {
        "3.0.0": {
            "AvailableForContractors": [42],
            "ForcedForContractors": [0],
            "ForceUpdate": True,
            "Staging": False,
        },
        "2.0.0": {
            "AvailableForContractors": [42],
            "ForcedForContractors": [42],
            "ForceUpdate": False,
            "Staging": False,
        },
    }
    selected = select_forced_version(document, installed_version="1.0.0", contractor_id=42)
    assert selected.version == "2.0.0"
    assert selected.has_force_update


def test_force_scan_returns_oldest_qualifying_newer_version() -> None:
    document = {
        version: {
            "AvailableForContractors": [42],
            "ForcedForContractors": [42],
            "Staging": False,
        }
        for version in ("4.0.0", "3.0.0", "2.0.0", "1.0.0")
    }
    selected = select_forced_version(document, installed_version="1.5.0", contractor_id=42)
    assert selected.version == "2.0.0"


def test_force_scan_obeys_staging_visibility_and_stops_at_installed_version() -> None:
    document = {
        "3.0.0": {
            "AvailableForContractors": [42],
            "ForcedForContractors": [42],
            "Staging": True,
        },
        "2.0.0": {
            "AvailableForContractors": [42],
            "ForcedForContractors": [42],
            "Staging": False,
        },
        "1.0.0": {
            "AvailableForContractors": [42],
            "ForcedForContractors": [42],
            "Staging": False,
        },
    }
    assert (
        select_forced_version(document, installed_version="1.5.0", contractor_id=42).version
        == "2.0.0"
    )
    assert (
        select_forced_version(
            document,
            installed_version="1.5.0",
            contractor_id=42,
            test_mode=True,
        ).version
        == "2.0.0"
    )  # 3.0.0 is overwritten by the older qualifying 2.0.0
    assert (
        select_forced_version(
            {"3.0.0": document["3.0.0"]},
            installed_version="1.5.0",
            contractor_id=42,
            test_mode=True,
        ).version
        == "3.0.0"
    )


def test_orchestration_timer_and_setting_constants_are_exact() -> None:
    assert UPDATE_POLL_INTERVAL_MS == 6 * 60 * 60 * 1000
    assert METADATA_RETRY_INTERVAL_MS == 5_000
    assert CLIENT_QUEUE_INTERVAL_MS == 10_000
    assert RECOVERY_RETRY_INTERVAL_MS == 20_000
    assert MAX_RECOVERY_RETRIES == 3
    assert DNS_TIMESTAMP_FORMAT == "%Y-%m-%dT%H:%M:%S"
    assert UPDATE_SEQUENCE_SETTING == "updateSequenceOnStart"


def test_forced_partial_check_starts_only_without_manual_or_server_origin() -> None:
    document = {
        "2.0.0": {
            "AvailableForContractors": [42],
            "ForcedForContractors": [42],
            "Staging": False,
        }
    }
    normal = check_partial_update_disposition(
        document,
        installed_version="1.0.0",
        contractor_id=42,
        notify_requested=True,
        select_latest_directly=False,
        manual_update=False,
        firmware_server_update=False,
    )
    assert normal.selected_version == "2.0.0"
    assert normal.force_selected
    assert normal.update_available
    assert normal.start_download
    assert not normal.notify_new_update

    for manual, server in ((True, False), (False, True)):
        blocked = check_partial_update_disposition(
            document,
            installed_version="1.0.0",
            contractor_id=42,
            notify_requested=True,
            select_latest_directly=False,
            manual_update=manual,
            firmware_server_update=server,
        )
        assert blocked.update_available
        assert not blocked.start_download


def test_direct_latest_path_starts_even_when_version_is_not_newer() -> None:
    document = {
        "1.0.0": {
            "AvailableForContractors": [42],
            "Staging": False,
        }
    }
    disposition = check_partial_update_disposition(
        document,
        installed_version="1.0.0",
        contractor_id=42,
        notify_requested=False,
        select_latest_directly=True,
        manual_update=False,
        firmware_server_update=False,
    )
    assert disposition.selected_version == "1.0.0"
    assert not disposition.force_selected
    assert not disposition.update_available
    assert disposition.clear_initial_setup
    assert disposition.emit_update_not_checked
    assert disposition.start_download


def test_update_available_latch_stays_true_for_a_later_nonnewer_selection() -> None:
    disposition = check_partial_update_disposition(
        {
            "1.0.0": {
                "AvailableForContractors": [42],
                "Staging": False,
            }
        },
        installed_version="1.0.0",
        contractor_id=42,
        notify_requested=False,
        select_latest_directly=True,
        manual_update=False,
        firmware_server_update=False,
        already_available=True,
    )
    assert disposition.update_available
    assert not disposition.clear_initial_setup
    assert not disposition.emit_update_not_checked
    assert disposition.start_download


def test_empty_force_selection_returns_before_clearing_initial_setup() -> None:
    disposition = check_partial_update_disposition(
        {
            "2.0.0": {
                "AvailableForContractors": [42],
                "Staging": False,
            }
        },
        installed_version="1.0.0",
        contractor_id=42,
        notify_requested=True,
        select_latest_directly=False,
        manual_update=False,
        firmware_server_update=False,
    )
    assert not disposition.selected_version
    assert not disposition.clear_initial_setup
    assert not disposition.emit_update_not_checked


@pytest.mark.parametrize(
    ("gate", "reason"),
    (
        ({"test_mode": True}, "test mode"),
        ({"download_timer_active": True}, "download timer active"),
        ({"restarting": True}, "restarting"),
        ({"metadata_refresh_valid": False}, "metadata refresh failed"),
    ),
)
def test_specific_server_request_obeys_all_race_gates(gate: dict[str, bool], reason: str) -> None:
    disposition = server_trigger_disposition(
        requested_version="2.0.0",
        installed_version="1.0.0",
        firmware_server_update=False,
        manual_at_process_start=False,
        **gate,
    )
    assert disposition.action == "blocked"
    assert disposition.reason == reason
    assert not disposition.start_specific_version


def test_server_request_empty_and_specific_routes_are_distinct() -> None:
    forced = server_trigger_disposition(
        requested_version="",
        installed_version="1.0.0",
        firmware_server_update=True,
        manual_at_process_start=False,
    )
    assert forced.action == "forced-check"
    assert forced.clear_firmware_server_update
    assert forced.run_forced_check

    specific = server_trigger_disposition(
        requested_version="2.0.0",
        installed_version="1.0.0",
        firmware_server_update=False,
        manual_at_process_start=False,
    )
    assert specific.action == "specific-version"
    assert specific.start_specific_version
    assert not specific.clear_firmware_server_update

    manual = server_trigger_disposition(
        requested_version="2.0.0",
        installed_version="1.0.0",
        firmware_server_update=False,
        manual_at_process_start=True,
    )
    assert manual.reason == "manual mode was set at process start"


def test_dns_freshness_uses_first_txt_timestamp_and_app_no_change_trigger() -> None:
    cached = datetime(2026, 8, 11, 12, 0, 0)  # noqa: DTZ001 - exact Qt local value
    newer = dns_record_disposition(
        update_type=0,
        dns_error=False,
        first_txt_value="2026-08-11T12:00:01",
        cached_timestamp=cached,
    )
    assert newer.remove_dns_key
    assert newer.queue_metadata_fetch
    assert newer.update_cached_timestamp
    assert not newer.start_server_trigger

    unchanged_app = dns_record_disposition(
        update_type=0,
        dns_error=False,
        first_txt_value="2026-08-11T12:00:00",
        cached_timestamp=cached,
    )
    assert not unchanged_app.queue_metadata_fetch
    assert unchanged_app.start_server_trigger

    unchanged_recovery = dns_record_disposition(
        update_type=2,
        dns_error=False,
        first_txt_value="2026-08-11T12:00:00",
        cached_timestamp=cached,
    )
    assert not unchanged_recovery.queue_metadata_fetch
    assert not unchanged_recovery.start_server_trigger


def test_dns_error_and_missing_value_drop_item_until_a_later_cycle() -> None:
    for dns_error, value in ((True, "2026-08-11T12:00:01"), (False, None)):
        disposition = dns_record_disposition(
            update_type=0,
            dns_error=dns_error,
            first_txt_value=value,
            cached_timestamp=None,
        )
        assert disposition.remove_dns_key
        assert not disposition.queue_metadata_fetch
        assert not disposition.start_server_trigger


def test_invalid_first_dns_timestamp_still_fetches_when_cache_is_invalid() -> None:
    first = dns_record_disposition(
        update_type=0,
        dns_error=False,
        first_txt_value="invalid",
        cached_timestamp=None,
    )
    assert first.queue_metadata_fetch
    assert first.update_cached_timestamp
    assert first.parsed_timestamp is None

    later = dns_record_disposition(
        update_type=0,
        dns_error=False,
        first_txt_value="invalid",
        cached_timestamp=datetime(  # noqa: DTZ001 - exact Qt local value
            2026, 8, 11, 12, 0, 0
        ),
    )
    assert not later.queue_metadata_fetch
    assert later.start_server_trigger


def test_recovery_retry_counter_allows_three_process_lifetime_timer_attempts() -> None:
    retries = 0
    for expected in range(1, MAX_RECOVERY_RETRIES + 1):
        completion = recovery_completion_disposition(
            in_process=False, retry_requested=True, retries_started=retries
        )
        assert completion.start_retry_timer
        timeout = recovery_retry_timeout(retries_started=retries)
        assert timeout.invoke_updater
        retries = timeout.retries_started_after
        assert retries == expected

    exhausted = recovery_completion_disposition(
        in_process=False, retry_requested=True, retries_started=retries
    )
    assert exhausted.retry_exhausted
    assert not exhausted.start_retry_timer
    assert not recovery_retry_timeout(retries_started=retries).invoke_updater


def test_update_sequence_flag_is_consumed_unconditionally() -> None:
    assert consume_update_sequence_flag(True).reported_on_start
    assert not consume_update_sequence_flag(True).persisted_after_read
    assert not consume_update_sequence_flag(False).reported_on_start
    assert not consume_update_sequence_flag(False).persisted_after_read


def test_urls_disclose_stable_serial_derived_id_over_plain_http() -> None:
    serial = b"synthetic-serial"
    identifier = serial_query_id(serial)
    assert identifier == md5(serial, usedforsecurity=False).hexdigest()
    assert (
        metadata_url(
            base_url="http://update.example.invalid",
            file_name="update_00_V1.json",
            serial=serial,
        )
        == f"http://update.example.invalid/update_00_V1.json?id={identifier}"
    )
    assert (
        payload_url(
            base_url="http://update.example.invalid/",
            address="manual_update/synthetic.zip",
            serial=serial,
        )
        == f"http://update.example.invalid/manual_update/synthetic.zip?id={identifier}"
    )
    assert DOWNLOAD_TIMEOUT_MS == 10_000


def test_archive_requires_md5_match_before_and_after_storage() -> None:
    payload = b"synthetic archive"
    checksum = md5(payload, usedforsecurity=False).hexdigest()
    ready = verify_and_stage_archive(payload, checksum_hex=checksum)
    assert ready.ready
    assert ready.archive_written
    assert ready.initial_checksum_match
    assert ready.reread_checksum_match

    corrupt_download = verify_and_stage_archive(payload + b"!", checksum_hex=checksum)
    assert not corrupt_download.ready
    assert not corrupt_download.archive_written

    corrupt_storage = verify_and_stage_archive(
        payload, checksum_hex=checksum, reread_payload=payload + b"!"
    )
    assert corrupt_storage.archive_written
    assert not corrupt_storage.ready
    assert not corrupt_storage.reread_checksum_match


@pytest.mark.parametrize("checksum", ["", "0" * 31, "gg" * 16])
def test_emulator_rejects_noncanonical_checksum_without_claiming_qt_edge_parity(
    checksum: str,
) -> None:
    result = verify_and_stage_archive(b"synthetic", checksum_hex=checksum)
    assert not result.ready
    assert result.reason == "noncanonical checksum"


def test_initial_setup_has_five_retries_and_sixth_failure_aborts() -> None:
    failures = 0
    for expected in range(1, MAX_INITIAL_RETRIES + 1):
        result = download_failure_disposition(
            initial_setup=True, backdoor=False, cumulative_failures=failures
        )
        failures = result.cumulative_failures
        assert failures == expected
        assert result.retry
        assert not result.clear_initial_update

    sixth = download_failure_disposition(
        initial_setup=True, backdoor=False, cumulative_failures=failures
    )
    assert sixth.cumulative_failures == 6
    assert not sixth.retry
    assert sixth.clear_initial_update
    assert sixth.emit_update_not_checked

    later = download_failure_disposition(
        initial_setup=True,
        backdoor=False,
        cumulative_failures=sixth.cumulative_failures,
    )
    assert later.cumulative_failures == 7  # no success-path reset exists
    assert not later.retry


def test_noninitial_and_manual_failures_emit_error_without_consuming_retry_budget() -> None:
    for initial_setup, backdoor in ((False, False), (True, True)):
        result = download_failure_disposition(
            initial_setup=initial_setup, backdoor=backdoor, cumulative_failures=3
        )
        assert result.cumulative_failures == 3
        assert result.emit_error
        assert not result.retry


def test_preflight_uses_strict_space_comparison_and_ordered_cleanup() -> None:
    update_equal = install_preflight(
        required_bytes=100,
        update_free_before=100,
        update_free_after_cleanup=101,
        root_free_before=60,
        root_free_after_cleanup=60,
        current_app_size=41,
    )
    assert update_equal.ready
    assert update_equal.cleanup_attempts == UPDATE_CLEANUP_TARGETS

    root_equal = install_preflight(
        required_bytes=100,
        update_free_before=101,
        update_free_after_cleanup=101,
        root_free_before=60,
        root_free_after_cleanup=60,
        current_app_size=40,
    )
    assert not root_equal.ready
    assert root_equal.cleanup_attempts == ROOT_CLEANUP_TARGETS

    recovered_root = install_preflight(
        required_bytes=100,
        update_free_before=101,
        update_free_after_cleanup=101,
        root_free_before=59,
        root_free_after_cleanup=61,
        current_app_size=40,
    )
    assert recovered_root.ready
    assert recovered_root.cleanup_attempts == ROOT_CLEANUP_TARGETS


def test_update_origin_flags_match_persisted_settings_contract() -> None:
    assert update_settings(
        backdoor=False, reset_to_version=False, firmware_server_version=False
    ) == update_settings(backdoor=False, reset_to_version=False, firmware_server_version=False)
    assert not update_settings(
        backdoor=False, reset_to_version=False, firmware_server_version=False
    ).manual_update
    assert update_settings(
        backdoor=True, reset_to_version=False, firmware_server_version=False
    ).manual_update
    assert update_settings(
        backdoor=False, reset_to_version=True, firmware_server_version=False
    ).manual_update
    assert update_settings(
        backdoor=False, reset_to_version=False, firmware_server_version=True
    ).firmware_server_update


def test_shell_masks_command_failures_cleans_source_and_prevents_systemd_retry() -> None:
    failed = simulate_update_script(
        unzip_ok=False,
        gunzip_ok=False,
        stop_ok=False,
        copy_ok=False,
        start_ok=False,
    )
    assert failed.masked_failures == ("unzip", "gunzip", "stop", "copy", "start")
    assert failed.service_exit_code == 0
    assert failed.source_cleaned
    assert failed.application_start_attempted
    assert not failed.application_running
    assert not failed.replacement_complete
    assert not failed.systemd_will_retry


def test_shell_success_is_still_in_place_and_nontransactional() -> None:
    successful = simulate_update_script()
    assert successful.service_exit_code == 0
    assert successful.source_cleaned
    assert successful.application_running
    assert successful.replacement_complete
    assert not successful.systemd_will_retry
