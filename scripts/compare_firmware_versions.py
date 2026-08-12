#!/usr/bin/env python3
"""Compare public structural reports for two Nuve application ELFs.

The tool reads binaries and previously generated private QV4/symbol reports, then
emits hashes, counts, route presence, and changed symbol/unit names only. It never
emits binary bytes, QV4 instructions, decompiled code, identifiers, or credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _load_api_contracts() -> tuple[Any, ...]:
    catalog_path = Path(__file__).resolve().with_name("firmware_api_catalog.py")
    module_name = "_nuve_firmware_api_catalog"
    specification = importlib.util.spec_from_file_location(module_name, catalog_path)
    if specification is None or specification.loader is None:
        raise RuntimeError("could not load firmware API catalog")
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    return tuple(module.API_CONTRACTS)


API_CONTRACTS = _load_api_contracts()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return value


def _verify_report_hash(report: dict[str, Any], expected: str, keys: tuple[str, ...]) -> None:
    for key in keys:
        value = report.get(key)
        if value is not None:
            if value != expected:
                raise ValueError(f"report {key} does not match the binary")
            return
    raise ValueError(f"report has none of the expected hash keys: {', '.join(keys)}")


def _binary_record(path: Path, data: bytes) -> dict[str, Any]:
    present_routes = sorted(
        contract.literal for contract in API_CONTRACTS if contract.literal.encode() in data
    )
    return {
        "name": path.name,
        "size": len(data),
        "sha256": _sha256(data),
        "catalog_routes_present": present_routes,
        "catalog_routes_missing": sorted(
            {contract.literal for contract in API_CONTRACTS} - set(present_routes)
        ),
    }


def _unit_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    units = report.get("units")
    if not isinstance(units, list):
        raise ValueError("QV4 report has no unit list")
    result: dict[str, dict[str, Any]] = {}
    for unit in units:
        if not isinstance(unit, dict) or not isinstance(unit.get("symbol"), str):
            raise ValueError("QV4 report contains an invalid unit")
        result[unit["symbol"]] = unit
    if len(result) != len(units):
        raise ValueError("QV4 report contains duplicate unit symbols")
    return result


def _function_body_digests(unit: dict[str, Any]) -> list[str]:
    functions = unit.get("functions", [])
    if not isinstance(functions, list):
        raise ValueError("QV4 unit has an invalid function list")
    digests = []
    for function in functions:
        if not isinstance(function, dict):
            raise ValueError("QV4 unit has an invalid function record")
        digest = function.get("instruction_semantic_sha256")
        if isinstance(digest, str):
            digests.append(digest)
    return digests


def _multiset_overlap(left: list[str], right: list[str]) -> int:
    return sum((Counter(left) & Counter(right)).values())


def _optional_equal(left: dict[str, Any], right: dict[str, Any], key: str) -> bool | None:
    left_value = left.get(key)
    right_value = right.get(key)
    if not isinstance(left_value, str) or not isinstance(right_value, str):
        return None
    return left_value == right_value


def _declarative_shape(unit: dict[str, Any]) -> dict[str, Any]:
    functions = unit.get("functions", [])
    body_by_index = {
        function.get("index"): function.get("instruction_semantic_sha256")
        for function in functions
        if isinstance(function, dict)
    }
    objects = [
        {
            "index": item.get("index"),
            "inherited_type": item.get("inherited_type"),
            "id_name": item.get("id_name"),
            "function_bodies": [
                body_by_index.get(index) for index in item.get("function_indices", [])
            ],
        }
        for item in unit.get("qml_objects", [])
    ]
    properties = [
        {
            key: item.get(key)
            for key in (
                "object_index",
                "index",
                "name",
                "type",
                "list",
                "read_only",
                "required",
                "is_builtin",
            )
        }
        for item in unit.get("qml_properties", [])
    ]
    signals = [
        {key: item.get(key) for key in ("object_index", "index", "name", "parameters")}
        for item in unit.get("qml_signals", [])
    ]
    enums = [
        {key: item.get(key) for key in ("object_index", "object_type", "name", "values")}
        for item in unit.get("qml_enums", [])
    ]
    bindings = [
        {
            "object_index": item.get("object_index"),
            "object_type": item.get("object_type"),
            "index": item.get("index"),
            "property": item.get("property"),
            "type": item.get("type"),
            "flags": item.get("flags"),
            "function_body": body_by_index.get(item.get("function_index")),
            "value": item.get("value"),
            "value_length": item.get("value_length"),
            "value_sha256": item.get("value_sha256"),
            "translation_sha256": item.get("translation_sha256"),
        }
        for item in unit.get("qml_bindings", [])
    ]
    return {
        "objects": objects,
        "properties": properties,
        "signals": signals,
        "enums": enums,
        "bindings": bindings,
    }


def _changed_unit_record(
    name: str,
    old_unit: dict[str, Any],
    new_unit: dict[str, Any],
    added_unit_bodies: list[str],
) -> dict[str, Any]:
    old_bodies = _function_body_digests(old_unit)
    new_bodies = _function_body_digests(new_unit)
    shared_bodies = _multiset_overlap(old_bodies, new_bodies)
    old_only_bodies = Counter(old_bodies) - Counter(new_bodies)
    moved_to_added_units = sum((old_only_bodies & Counter(added_unit_bodies)).values())
    old_function_count = old_unit.get("function_count")
    new_function_count = new_unit.get("function_count")
    digest_coverage = (
        isinstance(old_function_count, int)
        and isinstance(new_function_count, int)
        and len(old_bodies) == old_function_count
        and len(new_bodies) == new_function_count
    )
    return {
        "symbol": name,
        "old_size": old_unit.get("size"),
        "new_size": new_unit.get("size"),
        "old_function_count": old_function_count,
        "new_function_count": new_function_count,
        "semantic_body_digest_coverage": digest_coverage,
        "shared_function_body_count": shared_bodies,
        "old_only_function_body_count": len(old_bodies) - shared_bodies,
        "new_only_function_body_count": len(new_bodies) - shared_bodies,
        "old_only_body_moved_to_added_unit_count": moved_to_added_units,
        "remaining_old_only_function_body_count": (
            len(old_bodies) - shared_bodies - moved_to_added_units
        ),
        "declarative_shape_identical": _declarative_shape(old_unit) == _declarative_shape(new_unit),
        "literal_pool_multiset_identical": _optional_equal(
            old_unit, new_unit, "literal_pool_multiset_sha256"
        ),
        "translation_table_identical": _optional_equal(
            old_unit, new_unit, "translation_multiset_sha256"
        ),
    }


def compare_qv4(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_units = _unit_map(old)
    new_units = _unit_map(new)
    old_names = set(old_units)
    new_names = set(new_units)
    common = sorted(old_names & new_names)
    added_unit_bodies = [
        digest
        for name in sorted(new_names - old_names)
        for digest in _function_body_digests(new_units[name])
    ]
    changed = []
    unchanged = 0
    for name in common:
        old_unit = old_units[name]
        new_unit = new_units[name]
        if old_unit.get("sha256") == new_unit.get("sha256"):
            unchanged += 1
            continue
        changed.append(_changed_unit_record(name, old_unit, new_unit, added_unit_bodies))
    return {
        "old_summary": {
            "unit_count": old.get("unit_count"),
            "function_count": old.get("function_count"),
            "instruction_count": old.get("instruction_count"),
            "unit_corpus_sha256": old.get("unit_corpus_sha256"),
        },
        "new_summary": {
            "unit_count": new.get("unit_count"),
            "function_count": new.get("function_count"),
            "instruction_count": new.get("instruction_count"),
            "unit_corpus_sha256": new.get("unit_corpus_sha256"),
        },
        "common_unit_count": len(common),
        "unchanged_unit_count": unchanged,
        "changed_units": changed,
        "removed_units": sorted(old_names - new_names),
        "added_units": sorted(new_names - old_names),
    }


def _first_party_rows(report: dict[str, Any]) -> list[tuple[str, str, str]]:
    subsystems = report.get("subsystems")
    if not isinstance(subsystems, dict):
        raise ValueError("symbol report has no subsystem object")
    rows: set[tuple[str, str, str]] = set()
    for subsystem in subsystems.values():
        if not isinstance(subsystem, dict):
            raise ValueError("symbol report contains an invalid subsystem")
        classes = subsystem.get("classes")
        if not isinstance(classes, dict):
            raise ValueError("symbol subsystem has no class object")
        for items in classes.values():
            if not isinstance(items, list):
                raise ValueError("symbol class contains an invalid row list")
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("symbol report contains an invalid row")
                address = item.get("address")
                symbol_type = item.get("type")
                symbol = item.get("symbol")
                if not all(isinstance(value, str) for value in (address, symbol_type, symbol)):
                    raise ValueError("symbol report row has an invalid field")
                assert isinstance(address, str)
                assert isinstance(symbol_type, str)
                assert isinstance(symbol, str)
                rows.add((symbol, symbol_type, address))
    return sorted(rows)


def compare_symbols(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_rows = _first_party_rows(old)
    new_rows = _first_party_rows(new)
    old_names = {(symbol, symbol_type) for symbol, symbol_type, _address in old_rows}
    new_names = {(symbol, symbol_type) for symbol, symbol_type, _address in new_rows}
    return {
        "old_defined_symbol_count": old.get("defined_symbols"),
        "new_defined_symbol_count": new.get("defined_symbols"),
        "old_qml_cache_symbol_count": old.get("qml_cache_symbol_count"),
        "new_qml_cache_symbol_count": new.get("qml_cache_symbol_count"),
        "old_first_party_row_count": len(old_rows),
        "new_first_party_row_count": len(new_rows),
        "old_first_party_function_address_count": old.get("first_party_function_address_count"),
        "new_first_party_function_address_count": new.get("first_party_function_address_count"),
        "same_address_row_count": len(set(old_rows) & set(new_rows)),
        "removed_name_types": [
            {"symbol": symbol, "type": symbol_type}
            for symbol, symbol_type in sorted(old_names - new_names)
        ],
        "added_name_types": [
            {"symbol": symbol, "type": symbol_type}
            for symbol, symbol_type in sorted(new_names - old_names)
        ],
    }


def compare(
    old_binary: Path,
    new_binary: Path,
    old_qv4_report: Path,
    new_qv4_report: Path,
    old_symbol_report: Path,
    new_symbol_report: Path,
) -> dict[str, Any]:
    old_data = old_binary.read_bytes()
    new_data = new_binary.read_bytes()
    old_record = _binary_record(old_binary, old_data)
    new_record = _binary_record(new_binary, new_data)
    old_qv4 = _read_json(old_qv4_report)
    new_qv4 = _read_json(new_qv4_report)
    old_symbols = _read_json(old_symbol_report)
    new_symbols = _read_json(new_symbol_report)
    _verify_report_hash(old_qv4, old_record["sha256"], ("binary_sha256",))
    _verify_report_hash(new_qv4, new_record["sha256"], ("binary_sha256",))
    _verify_report_hash(old_symbols, old_record["sha256"], ("sha256",))
    _verify_report_hash(new_symbols, new_record["sha256"], ("sha256",))
    return {
        "schema_version": 3,
        "old_binary": old_record,
        "new_binary": new_record,
        "route_set_identical": (
            old_record["catalog_routes_present"] == new_record["catalog_routes_present"]
        ),
        "qv4": compare_qv4(old_qv4, new_qv4),
        "selected_first_party_symbols": compare_symbols(old_symbols, new_symbols),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_binary", type=Path)
    parser.add_argument("new_binary", type=Path)
    parser.add_argument("--old-qv4-report", type=Path, required=True)
    parser.add_argument("--new-qv4-report", type=Path, required=True)
    parser.add_argument("--old-symbol-report", type=Path, required=True)
    parser.add_argument("--new-symbol-report", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = compare(
            args.old_binary,
            args.new_binary,
            args.old_qv4_report,
            args.new_qv4_report,
            args.old_symbol_report,
            args.new_symbol_report,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
