#!/usr/bin/env python3
"""Independent exact-1.5.8 installer/customer/warranty contract model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUPPORTED_COUNTRIES = ("US", "Canada", "Australia")
IT_NEW_INSTALLATION = 0


@dataclass
class ServiceTitan:
    is_manual_mode: bool = False
    email: str = ""
    zip_code: str = ""
    job_number: str = ""
    full_name: str = ""
    phone: str = ""
    address1: str = ""
    address2: str = ""
    country: str = ""
    city: str = ""
    state: str = ""
    city_id: int = -1
    state_id: int = -1


@dataclass(frozen=True)
class LookupResult:
    error: str
    need_retry: bool
    mismatch_accepted: bool = False
    timezone_changed: bool = False


def _present(value: Any, fallback: Any) -> Any:
    return fallback if value is None else value


def _nested_or_scalar(data: dict[str, Any], name: str, field: str, fallback: Any) -> Any:
    value = data.get(name)
    if isinstance(value, dict):
        return _present(value.get(field), fallback)
    return _present(value, fallback)


def build_address_packet(service: ServiceTitan) -> dict[str, Any]:
    """Model DeviceController._prepareAddressPacket."""

    try:
        country = SUPPORTED_COUNTRIES.index(service.country) + 1
    except ValueError:
        country = 0
    packet: dict[str, Any] = {
        "zip_code": service.zip_code.upper(),
        "country": country,
    }
    if not service.is_manual_mode:
        if service.address1:
            packet["address1"] = service.address1
        if service.address2:
            packet["address2"] = service.address2
    return packet


def build_install_packet(
    service: ServiceTitan,
    *,
    serial: str,
    installation_type: int,
    residence_type: int,
    where_installed: int,
    system_age: int,
    thermostat_name: str = "",
) -> dict[str, Any]:
    """Model DeviceController._pushInitialSetupInformation."""

    client: dict[str, Any] = {"email": service.email}
    if not service.is_manual_mode:
        if service.full_name:
            client["full_name"] = service.full_name
        if service.phone:
            client["phone"] = service.phone

    is_new = installation_type == IT_NEW_INSTALLATION
    device: dict[str, Any] = build_address_packet(service)
    device.update(
        {
            "sn": serial,
            "installation_type": "new" if is_new else "existing",
            "system_age": 0 if is_new else system_age,
            "resident_type_id": residence_type,
            "where_installed_id": where_installed,
        }
    )
    if thermostat_name:
        device["name"] = thermostat_name

    packet: dict[str, Any] = {"client": client, "devices": [device]}
    if not service.is_manual_mode and service.job_number:
        packet["job_id"] = service.job_number
    return packet


def apply_job_information(
    service: ServiceTitan, *, success: bool, data: dict[str, Any] | None
) -> None:
    """Apply the successful job callback; failure leaves the model untouched."""

    if not success or data is None:
        return
    service.full_name = _present(data.get("full_name"), "")
    service.phone = _present(data.get("phone"), "")
    service.email = _present(data.get("email"), "")
    service.zip_code = _nested_or_scalar(data, "zip", "code", "")
    service.country = _nested_or_scalar(data, "country", "name", "US")
    if service.country == "United States":
        service.country = "US"
    service.city = _nested_or_scalar(data, "city", "name", "")
    service.state = _nested_or_scalar(data, "state", "short", "")
    city = data.get("city")
    state = data.get("state")
    service.city_id = _present(city.get("id"), -1) if isinstance(city, dict) else -1
    service.state_id = _present(state.get("id"), -1) if isinstance(state, dict) else -1
    service.address1 = _present(data.get("address1"), "")
    service.address2 = _present(data.get("address2"), "")


def apply_zip_information(
    service: ServiceTitan,
    *,
    success: bool,
    data: dict[str, Any] | None,
    need_retry: bool,
    initial_setup: bool = False,
    timezone_timer_running: bool = False,
    current_timezone: str = "UTC",
) -> tuple[LookupResult, str]:
    """Model the ZIP callback, including accepted code mismatches."""

    if not success or not data:
        return LookupResult("Getting zip code information failed.", need_retry), current_timezone

    returned_code = data.get("code")
    mismatch = returned_code != service.zip_code
    city = data.get("city")
    state = data.get("state")
    service.city = _present(city.get("name"), "") if isinstance(city, dict) else ""
    service.state = _present(state.get("short"), "") if isinstance(state, dict) else ""
    service.city_id = _present(city.get("id"), -1) if isinstance(city, dict) else -1
    service.state_id = _present(state.get("id"), -1) if isinstance(state, dict) else -1

    timezone_changed = False
    if initial_setup and not timezone_timer_running and "time_zone_id" in data:
        returned_timezone = data.get("time_zone_id")
        if returned_timezone != current_timezone:
            current_timezone = returned_timezone
            timezone_changed = True
    return (
        LookupResult("", False, mismatch_accepted=mismatch, timezone_changed=timezone_changed),
        current_timezone,
    )


def apply_customer_information(
    service: ServiceTitan,
    *,
    success: bool,
    data: dict[str, Any] | None,
    error: str,
    need_retry: bool,
) -> tuple[LookupResult, str]:
    """Model customer lookup; returned email is a comparison token, not a model write."""

    if not success:
        return LookupResult(f"Getting customer information failed. {error}", need_retry), ""
    if not data:
        return LookupResult("", False), ""

    returned_email = _present(data.get("email"), "")
    mismatch = returned_email != service.email
    service.full_name = _present(data.get("full_name"), "")
    service.phone = _present(data.get("phone"), "")
    return LookupResult("", False, mismatch_accepted=mismatch), returned_email


def warranty_request(old_serial: str, new_serial: str) -> tuple[dict[str, str] | None, str]:
    """Return request body and the value prewritten to the serial QSettings key."""

    if old_serial == new_serial:
        return None, ""
    return {"old_sn": old_serial, "new_sn": new_serial}, old_serial


def show_retry_error(*, need_retry: bool, retry_counter: int) -> bool:
    """All recovered installer pages surface nonretryable and every second retryable error."""

    return not need_retry or retry_counter % 2 == 0
