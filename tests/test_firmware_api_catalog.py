"""Integrity checks for the exact-1.5.8 direct API route catalog."""

from __future__ import annotations

import re
from pathlib import Path

from scripts.firmware_api_catalog import (
    API_CONTRACTS,
    APP_SHA256,
    SUPPORTED_ROUTE_LITERALS,
    contract_by_literal,
)

EXPECTED_ROUTE_LITERALS = (
    "%0api/device/recovery-image?sn=%1",
    "/api/customer",
    "/api/device/settings",
    "/api/device/system",
    "/api/sync/schedules2?sn=%0",
    "/api/sync/updateAddress",
    "/api/technicians/device/install",
    "/api/technicians/service-titan/customer/%0?sn=%1",
    "/api/technicians/warranty",
    "/api/zipCode?code=%0",
    "api/designTemperature?sn=%0",
    "api/device/current-sensors?sn=%0",
    "api/device/current-stages?sn=%0",
    "api/device/wifi-off?sn=%0",
    "api/monitor/data?sn=%0",
    "api/monitor/event?sn=%0",
    "api/monitor/report?sn=%0",
    "api/sync/alerts",
    "api/sync/autoMode?sn=%0",
    "api/sync/clearSchedule2",
    "api/sync/clearSchedules",
    "api/sync/client?sn=%0",
    "api/sync/forget?sn=%1",
    "api/sync/getContractorInfo?sn=%0",
    "api/sync/getSettings?sn=%0",
    "api/sync/getSn?uid=%0",
    "api/sync/getWirings?uid=%0",
    "api/sync/messages?sn=%0",
    "api/sync/perftest/result?sn=%0",
    "api/sync/perftest/schedule?sn=%0",
    "api/sync/schedule2/%0?sn=%1",
    "api/sync/schedule2?sn=%0",
    "api/sync/schedules",
    "api/sync/schedules/%0",
    "api/sync/screen-%1?sn=%2",
    "api/sync/update",
    "api/weather-current?sn=%0&units=%1",
    "api/weather-forecast?sn=%0&units=%1",
)

EXPECTED_SUPPORTED = frozenset(
    {
        "/api/device/settings",
        "/api/device/system",
        "api/designTemperature?sn=%0",
        "api/device/current-sensors?sn=%0",
        "api/device/current-stages?sn=%0",
        "api/device/wifi-off?sn=%0",
        "api/monitor/data?sn=%0",
        "api/monitor/event?sn=%0",
        "api/monitor/report?sn=%0",
        "api/sync/autoMode?sn=%0",
        "api/sync/getContractorInfo?sn=%0",
        "api/sync/getSettings?sn=%0",
        "api/sync/update",
        "api/weather-current?sn=%0&units=%1",
        "api/weather-forecast?sn=%0&units=%1",
    }
)


def test_catalog_is_exact_unique_38_literal_inventory() -> None:
    literals = tuple(contract.literal for contract in API_CONTRACTS)
    assert literals == EXPECTED_ROUTE_LITERALS
    assert len(literals) == len(set(literals)) == 38
    assert APP_SHA256 == "2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e"


def test_every_contract_has_owner_transport_schemas_effects_and_disposition() -> None:
    owner_pattern = re.compile(r" @ 0x[0-9a-f]+$")
    for contract in API_CONTRACTS:
        assert contract.methods and set(contract.methods) <= {"GET", "POST", "PUT"}
        assert contract.owners and all(owner_pattern.search(owner) for owner in contract.owners)
        assert contract.timeout_ms in {20_000, 40_000}
        assert contract.request_schema
        assert contract.response_and_retry
        assert contract.persistence_hardware_privacy
        assert contract.local_disposition.startswith(("supported:", "unsupported:"))
        assert contract.detail_doc.endswith(".md")
        assert contract_by_literal(contract.literal) is contract


def test_authentication_timeout_and_multi_method_exceptions_are_explicit() -> None:
    unauthenticated = {contract.literal for contract in API_CONTRACTS if not contract.authenticated}
    long_timeout = {contract.literal for contract in API_CONTRACTS if contract.timeout_ms != 20_000}
    multi_method = {contract.literal for contract in API_CONTRACTS if len(contract.methods) > 1}
    assert unauthenticated == {"api/sync/getSn?uid=%0"}
    assert long_timeout == {"/api/technicians/device/install"}
    assert multi_method == {"api/sync/autoMode?sn=%0"}


def test_supported_routes_are_an_explicit_allowlist_not_unknown_path_success() -> None:
    assert SUPPORTED_ROUTE_LITERALS == EXPECTED_SUPPORTED
    assert len(SUPPORTED_ROUTE_LITERALS) == 15


def test_human_catalog_names_every_exact_literal_and_detail_document() -> None:
    document = Path("docs/api-contract-catalog.md").read_text()
    for contract in API_CONTRACTS:
        assert f"`{contract.literal}`" in document
        assert f"[{contract.detail_doc}]({contract.detail_doc})" in document
