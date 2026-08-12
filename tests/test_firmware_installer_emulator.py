"""Independent checks for exact-1.5.8 installer/private API behavior."""

from __future__ import annotations

from scripts.emulate_firmware_installer import (
    ServiceTitan,
    apply_customer_information,
    apply_job_information,
    apply_zip_information,
    build_address_packet,
    build_install_packet,
    show_retry_error,
    warranty_request,
)


def test_manual_install_omits_job_identity_and_street_fields() -> None:
    service = ServiceTitan(
        is_manual_mode=True,
        email="user@example.invalid",
        zip_code="b3k 0a1",
        job_number="private-job",
        full_name="Private Name",
        phone="555",
        address1="Private Street",
        address2="Unit 1",
        country="Canada",
    )
    assert build_install_packet(
        service,
        serial="redacted",
        installation_type=0,
        residence_type=0,
        where_installed=2,
        system_age=19,
    ) == {
        "client": {
            "email": "user@example.invalid",
        },
        "devices": [
            {
                "zip_code": "B3K 0A1",
                "country": 2,
                "sn": "redacted",
                "installation_type": "new",
                "system_age": 0,
                "resident_type_id": 0,
                "where_installed_id": 2,
            }
        ],
    }


def test_external_service_install_includes_only_nonempty_optional_fields() -> None:
    service = ServiceTitan(
        email="user@example.invalid",
        zip_code="90210",
        job_number="job-redacted",
        full_name="Private Name",
        address1="Private Street",
        country="US",
    )
    packet = build_install_packet(
        service,
        serial="redacted",
        installation_type=1,
        residence_type=1,
        where_installed=3,
        system_age=8,
        thermostat_name="Main",
    )
    assert packet["client"] == {
        "email": "user@example.invalid",
        "full_name": "Private Name",
    }
    assert packet["devices"][0]["zip_code"] == "90210"
    assert packet["devices"][0]["country"] == 1
    assert packet["devices"][0]["address1"] == "Private Street"
    assert packet["devices"][0]["installation_type"] == "existing"
    assert packet["devices"][0]["system_age"] == 8
    assert packet["devices"][0]["name"] == "Main"
    assert packet["job_id"] == "job-redacted"


def test_unknown_country_projects_to_zero() -> None:
    assert build_address_packet(ServiceTitan(country="Unknown"))["country"] == 0


def test_job_response_accepts_nested_and_scalar_location_shapes() -> None:
    service = ServiceTitan()
    apply_job_information(
        service,
        success=True,
        data={
            "full_name": "Private Name",
            "email": "user@example.invalid",
            "zip": {"code": "90210"},
            "country": {"name": "United States"},
            "city": {"name": "City", "id": 7},
            "state": {"short": "ST", "id": 8},
        },
    )
    assert service.zip_code == "90210"
    assert service.country == "US"
    assert (service.city_id, service.state_id) == (7, 8)


def test_zip_mismatch_is_warned_but_applied_and_can_change_timezone() -> None:
    service = ServiceTitan(zip_code="REQUESTED")
    result, timezone = apply_zip_information(
        service,
        success=True,
        data={
            "code": "DIFFERENT",
            "city": {"name": "City", "id": 1},
            "state": {"short": "ST", "id": 2},
            "time_zone_id": "America/Test",
        },
        need_retry=True,
        initial_setup=True,
        current_timezone="UTC",
    )
    assert result.mismatch_accepted
    assert result.timezone_changed
    assert timezone == "America/Test"
    assert (service.city, service.state) == ("City", "ST")


def test_customer_email_mismatch_is_accepted_without_overwriting_requested_email() -> None:
    service = ServiceTitan(email="requested@example.invalid")
    result, returned_email = apply_customer_information(
        service,
        success=True,
        data={
            "email": "different@example.invalid",
            "full_name": "Returned Name",
            "phone": None,
            "membership": "ignored",
            "is_enabled": False,
        },
        error="",
        need_retry=False,
    )
    assert result.mismatch_accepted
    assert returned_email == "different@example.invalid"
    assert service.email == "requested@example.invalid"
    assert service.full_name == "Returned Name"
    assert service.phone == ""


def test_warranty_prewrite_uses_submitted_old_serial_before_response() -> None:
    body, prewritten = warranty_request("01-111-111111", "01-222-222222")
    assert body == {"old_sn": "01-111-111111", "new_sn": "01-222-222222"}
    assert prewritten == "01-111-111111"
    assert warranty_request("same", "same") == (None, "")


def test_retry_ui_surfaces_nonretryable_and_every_second_retryable_failure() -> None:
    assert show_retry_error(need_retry=False, retry_counter=1)
    assert not show_retry_error(need_retry=True, retry_counter=1)
    assert show_retry_error(need_retry=True, retry_counter=2)
