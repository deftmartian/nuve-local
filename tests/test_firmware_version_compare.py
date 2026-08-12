from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "compare_firmware_versions.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("compare_firmware_versions", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def compare_module():
    return _load_module()


def _qv4_report(binary: bytes, units: list[dict[str, object]]) -> dict[str, object]:
    import hashlib

    return {
        "binary_sha256": hashlib.sha256(binary).hexdigest(),
        "unit_count": len(units),
        "function_count": sum(int(unit["function_count"]) for unit in units),
        "instruction_count": 12,
        "unit_corpus_sha256": "synthetic-corpus",
        "units": units,
    }


def _symbol_report(binary: bytes, rows: list[dict[str, str]]) -> dict[str, object]:
    import hashlib

    return {
        "sha256": hashlib.sha256(binary).hexdigest(),
        "defined_symbols": len(rows),
        "qml_cache_symbol_count": 0,
        "first_party_function_address_count": len(rows),
        "subsystems": {
            "synthetic": {
                "classes": {"Synthetic": rows},
            }
        },
    }


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value))
    return path


def test_compare_reports_changed_units_and_address_drift(tmp_path: Path, compare_module) -> None:
    old_binary = b"old:" + b"api/sync/getSettings?sn=%0"
    new_binary = b"new:" + b"api/sync/getSettings?sn=%0"
    old_path = tmp_path / "old-app"
    new_path = tmp_path / "new-app"
    old_path.write_bytes(old_binary)
    new_path.write_bytes(new_binary)
    old_qv4 = _qv4_report(
        old_binary,
        [
            {"symbol": "same", "sha256": "a", "size": 10, "function_count": 1},
            {"symbol": "changed", "sha256": "b", "size": 20, "function_count": 2},
            {"symbol": "removed", "sha256": "c", "size": 30, "function_count": 3},
        ],
    )
    new_qv4 = _qv4_report(
        new_binary,
        [
            {"symbol": "same", "sha256": "a", "size": 10, "function_count": 1},
            {"symbol": "changed", "sha256": "d", "size": 21, "function_count": 4},
            {"symbol": "added", "sha256": "e", "size": 40, "function_count": 5},
        ],
    )
    old_symbols = _symbol_report(
        old_binary,
        [
            {"symbol": "Controller::same()", "type": "T", "address": "0x00000010"},
            {"symbol": "Controller::old()", "type": "T", "address": "0x00000020"},
        ],
    )
    new_symbols = _symbol_report(
        new_binary,
        [
            {"symbol": "Controller::same()", "type": "T", "address": "0x00000018"},
            {"symbol": "Controller::new()", "type": "T", "address": "0x00000028"},
        ],
    )

    report = compare_module.compare(
        old_path,
        new_path,
        _write_json(tmp_path / "old-qv4.json", old_qv4),
        _write_json(tmp_path / "new-qv4.json", new_qv4),
        _write_json(tmp_path / "old-symbols.json", old_symbols),
        _write_json(tmp_path / "new-symbols.json", new_symbols),
    )

    assert report["route_set_identical"] is True
    assert report["qv4"]["unchanged_unit_count"] == 1
    assert report["qv4"]["changed_units"] == [
        {
            "symbol": "changed",
            "old_size": 20,
            "new_size": 21,
            "old_function_count": 2,
            "new_function_count": 4,
            "semantic_body_digest_coverage": False,
            "shared_function_body_count": 0,
            "old_only_function_body_count": 0,
            "new_only_function_body_count": 0,
            "old_only_body_moved_to_added_unit_count": 0,
            "remaining_old_only_function_body_count": 0,
            "declarative_shape_identical": True,
            "literal_pool_multiset_identical": None,
            "translation_table_identical": None,
        }
    ]
    assert report["qv4"]["removed_units"] == ["removed"]
    assert report["qv4"]["added_units"] == ["added"]
    symbol_diff = report["selected_first_party_symbols"]
    assert symbol_diff["same_address_row_count"] == 0
    assert symbol_diff["removed_name_types"] == [{"symbol": "Controller::old()", "type": "T"}]
    assert symbol_diff["added_name_types"] == [{"symbol": "Controller::new()", "type": "T"}]


def test_compare_rejects_report_for_another_binary(tmp_path: Path, compare_module) -> None:
    binary = tmp_path / "app"
    binary.write_bytes(b"exact")
    qv4 = _write_json(
        tmp_path / "qv4.json",
        {"binary_sha256": "wrong", "units": []},
    )
    symbols = _write_json(
        tmp_path / "symbols.json",
        {"sha256": "wrong", "subsystems": {}},
    )

    with pytest.raises(ValueError, match="does not match"):
        compare_module.compare(binary, binary, qv4, qv4, symbols, symbols)


def test_duplicate_qv4_symbols_fail_closed(compare_module) -> None:
    report = {
        "units": [
            {"symbol": "duplicate", "sha256": "a"},
            {"symbol": "duplicate", "sha256": "b"},
        ]
    }

    with pytest.raises(ValueError, match="duplicate"):
        compare_module.compare_qv4(report, {"units": []})


def test_changed_unit_reports_semantic_body_overlap(compare_module) -> None:
    old = {
        "units": [
            {
                "symbol": "changed",
                "sha256": "old",
                "size": 10,
                "function_count": 2,
                "functions": [
                    {"index": 0, "instruction_semantic_sha256": "same"},
                    {"index": 1, "instruction_semantic_sha256": "old-only"},
                ],
            }
        ]
    }
    new = {
        "units": [
            {
                "symbol": "changed",
                "sha256": "new",
                "size": 11,
                "function_count": 2,
                "functions": [
                    {"index": 0, "instruction_semantic_sha256": "same"},
                    {"index": 1, "instruction_semantic_sha256": "new-only"},
                ],
            }
        ]
    }

    changed = compare_module.compare_qv4(old, new)["changed_units"][0]

    assert changed["semantic_body_digest_coverage"]
    assert changed["shared_function_body_count"] == 1
    assert changed["old_only_function_body_count"] == 1
    assert changed["new_only_function_body_count"] == 1
    assert changed["old_only_body_moved_to_added_unit_count"] == 0
    assert changed["remaining_old_only_function_body_count"] == 1
    assert changed["declarative_shape_identical"]


def test_changed_unit_reports_body_moved_to_added_unit(compare_module) -> None:
    old = {
        "units": [
            {
                "symbol": "changed",
                "sha256": "old",
                "size": 10,
                "function_count": 2,
                "literal_pool_multiset_sha256": "same-pool",
                "translation_multiset_sha256": "same-translations",
                "translation_count": 0,
                "functions": [
                    {"index": 0, "instruction_semantic_sha256": "retained"},
                    {"index": 1, "instruction_semantic_sha256": "moved"},
                ],
            }
        ]
    }
    new = {
        "units": [
            {
                "symbol": "changed",
                "sha256": "new",
                "size": 11,
                "function_count": 1,
                "literal_pool_multiset_sha256": "same-pool",
                "translation_multiset_sha256": "same-translations",
                "translation_count": 0,
                "functions": [
                    {"index": 0, "instruction_semantic_sha256": "retained"},
                ],
            },
            {
                "symbol": "added",
                "sha256": "added",
                "size": 4,
                "function_count": 1,
                "functions": [
                    {"index": 0, "instruction_semantic_sha256": "moved"},
                ],
            },
        ]
    }

    changed = compare_module.compare_qv4(old, new)["changed_units"][0]

    assert changed["semantic_body_digest_coverage"]
    assert changed["old_only_body_moved_to_added_unit_count"] == 1
    assert changed["remaining_old_only_function_body_count"] == 0
    assert changed["literal_pool_multiset_identical"] is True
    assert changed["translation_table_identical"] is True
