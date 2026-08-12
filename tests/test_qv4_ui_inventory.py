"""Tests for public QV4 declarative-structure inventory records."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[1]
QV4_SCRIPT_DIRECTORY = ROOT / ".agents" / "skills" / "analyze-nuve-firmware" / "scripts"
INVENTORY_PATH = QV4_SCRIPT_DIRECTORY / "inventory_qt6_qv4.py"


def _load_module(name: str, path: Path) -> ModuleType:
    sys.path.insert(0, str(QV4_SCRIPT_DIRECTORY))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(QV4_SCRIPT_DIRECTORY))


def _binding(binding_type: str, value: object) -> dict[str, object]:
    return {
        "object_index": 3,
        "object_type": "Button",
        "index": 7,
        "property": "onClicked",
        "type": binding_type,
        "flags": 0,
        "value": value,
        "line": 41,
        "column": 9,
        "value_line": 42,
        "value_column": 13,
    }


def test_script_binding_retains_linkage_but_not_source() -> None:
    inventory = _load_module("inventory_qt6_qv4_script", INVENTORY_PATH)
    secret = "deviceController.factoryReset(privateIdentifier)"

    record = inventory._qml_binding_record(
        _binding("script", {"function_index": 19, "source": secret})
    )

    assert record["function_index"] == 19
    assert "source" not in record
    assert secret not in json.dumps(record)


def test_string_binding_is_represented_only_by_length_and_hash() -> None:
    inventory = _load_module("inventory_qt6_qv4_string", INVENTORY_PATH)
    proprietary_text = "Embedded interface prose must not be copied into the report."

    record = inventory._qml_binding_record(_binding("string", proprietary_text))

    assert record["value_length"] == len(proprietary_text)
    assert len(record["value_sha256"]) == 64
    assert "value" not in record
    assert proprietary_text not in json.dumps(record)


def test_literal_binding_retains_nontext_value() -> None:
    inventory = _load_module("inventory_qt6_qv4_literal", INVENTORY_PATH)

    record = inventory._qml_binding_record(_binding("boolean", True))

    assert record["value"] is True


def test_translation_binding_retains_only_a_digest() -> None:
    inventory = _load_module("inventory_qt6_qv4_translation", INVENTORY_PATH)
    private_text = "Proprietary translated interface text."

    record = inventory._qml_binding_record(
        _binding("translation", (private_text, "private comment", -1))
    )

    assert len(record["translation_sha256"]) == 64
    assert "value" not in record
    assert private_text not in json.dumps(record)


def test_instruction_semantic_digest_retains_no_private_string() -> None:
    inventory = _load_module("inventory_qt6_qv4_digest", INVENTORY_PATH)
    private_text = "Proprietary interface text must remain outside the report."

    class FakeUnit:
        def string(self, _index: int) -> str:
            return private_text

    digest = inventory._instruction_semantic_digest(
        FakeUnit(),
        [(0, 10, "LoadRuntimeString", [("stringId", 4)])],
    )

    assert len(digest) == 64
    assert private_text not in digest


def test_private_multiset_digest_retains_no_private_members() -> None:
    inventory = _load_module("inventory_qt6_qv4_pool", INVENTORY_PATH)
    private_text = "Proprietary literal-pool member must not be retained."

    digest = inventory._private_multiset_digest(
        [
            ("string", private_text),
            ("constant", 1.8),
            ("translation", (private_text, "", -1)),
        ]
    )

    assert len(digest) == 64
    assert private_text not in digest


def test_operation_summary_separates_named_and_dynamic_effects() -> None:
    inventory = _load_module("inventory_qt6_qv4_operations", INVENTORY_PATH)

    class FakeUnit:
        lookup_count = 2

        @staticmethod
        def lookup(index: int) -> tuple[str, int]:
            return {0: ("deviceController", 0), 1: ("Date", 0)}[index]

        @staticmethod
        def string(index: int) -> str:
            return {
                3: "saveSettings",
                4: "currentIndex",
                5: "temporaryValue",
            }[index]

    summary = inventory._operation_summary(
        FakeUnit(),
        [
            (0, 1, "LoadQmlContextPropertyLookup", [("index", 0)]),
            (2, 1, "CallProperty", [("property", 3)]),
            (4, 1, "StoreProperty", [("property", 4)]),
            (5, 1, "LoadQmlContextPropertyLookup", [("index", 1)]),
            (6, 1, "StoreReg", [("reg", 8)]),
            (7, 1, "Construct", [("func", 8), ("argc", 0), ("argv", 0)]),
            (6, 1, "CallValue", [("func", 7)]),
            (8, 1, "StoreElement", []),
            (9, 1, "DeleteName", [("name", 5)]),
            (10, 1, "JumpFalse", [("offset", 1)]),
            (12, 1, "ThrowException", []),
        ],
    )

    assert summary["named_reads"] == ["Date", "deviceController"]
    assert summary["named_calls"] == ["saveSettings"]
    assert summary["named_constructs"] == ["Date"]
    assert summary["named_writes"] == ["currentIndex"]
    assert summary["named_deletes"] == ["temporaryValue"]
    assert summary["named_call_count"] == 1
    assert summary["dynamic_call_count"] == 1
    assert summary["named_construct_count"] == 1
    assert summary["unresolved_construct_count"] == 0
    assert summary["element_write_count"] == 1
    assert summary["delete_count"] == 1
    assert summary["control_flow_count"] == 1
    assert summary["throw_count"] == 1
