"""Tests for the public QML action register."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
REGISTER_PATH = ROOT / "scripts" / "build_ui_action_register.py"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _fixture() -> dict[str, object]:
    def operations(*, calls: list[str] | None = None) -> dict[str, object]:
        named_calls = calls or []
        return {
            "named_reads": [],
            "named_writes": [],
            "named_calls": named_calls,
            "named_constructs": [],
            "named_deletes": [],
            "named_call_count": len(named_calls),
            "dynamic_call_count": 0,
            "named_construct_count": 0,
            "unresolved_construct_count": 0,
            "element_read_count": 0,
            "element_write_count": 0,
            "delete_count": 0,
            "control_flow_count": 0,
            "throw_count": 0,
            "object_creation_count": 0,
        }

    functions = [
        {
            "index": 0,
            "name": "expression for onClicked",
            "source_line": 10,
            "source_column": 4,
            "referenced_names": ["saveSettings", "Private UI prose is excluded"],
            "operation_summary": operations(calls=["saveSettings"]),
        },
        {
            "index": 1,
            "name": "expression for onCompleted",
            "source_line": 3,
            "source_column": 1,
            "referenced_names": [],
            "operation_summary": operations(),
        },
        {
            "index": 2,
            "name": "onSchedulesChanged",
            "source_line": 20,
            "source_column": 2,
            "referenced_names": ["sync", "schedule"],
            "operation_summary": operations(calls=["sync"]),
        },
        {
            "index": 3,
            "name": "ordinaryFunction",
            "source_line": 30,
            "source_column": 2,
            "referenced_names": ["factoryReset"],
            "operation_summary": operations(calls=["factoryReset"]),
        },
    ]
    qml_objects = [
        {
            "index": 0,
            "inherited_type": "SchedulePage",
            "id_name": "root",
            "line": 1,
            "column": 1,
            "function_indices": [0, 1, 3],
        },
        {
            "index": 1,
            "inherited_type": "Connections",
            "id_name": "",
            "line": 18,
            "column": 1,
            "function_indices": [2],
        },
    ]
    bindings = [
        {
            "object_index": 0,
            "object_type": "SchedulePage",
            "index": 0,
            "property": "onClicked",
            "type": "script",
            "function_index": 0,
        },
        {
            "object_index": 0,
            "object_type": "SchedulePage",
            "index": 1,
            "property": "onCompleted",
            "type": "script",
            "function_index": 1,
        },
        {
            "object_index": 0,
            "object_type": "SchedulePage",
            "index": 2,
            "property": "visible",
            "type": "script",
            "function_index": 3,
        },
    ]
    return {
        "schema_version": 4,
        "binary_sha256": "a" * 64,
        "unit_corpus_sha256": "b" * 64,
        "unit_count": 1,
        "function_count": len(functions),
        "qml_object_count": len(qml_objects),
        "qml_binding_count": len(bindings),
        "units": [
            {
                "symbol": "_0x5f_Stherm_qml_View_Schedule_SchedulePage_qml",
                "functions": functions,
                "qml_objects": qml_objects,
                "qml_bindings": bindings,
            }
        ],
    }


def test_register_exhausts_bound_and_declared_handlers_without_source_leakage() -> None:
    register = _load_module("build_ui_action_register", REGISTER_PATH)

    report = register.build_register(_fixture())

    assert report["action_count"] == 3
    assert report["source_counts"] == {"declared-handler": 1, "script-binding": 2}
    assert report["action_unit_count"] == 1
    assert len({action["id"] for action in report["actions"]}) == 3
    assert {action["handler"] for action in report["actions"]} == {
        "onClicked",
        "onCompleted",
        "onSchedulesChanged",
    }
    assert "Private UI prose is excluded" not in json.dumps(report)
    clicked = next(action for action in report["actions"] if action["handler"] == "onClicked")
    assert clicked["referenced_identifiers"] == ["saveSettings"]
    assert clicked["semantic_disposition"] == "identifier-level-map"
    assert clicked["consequence_disposition"] == "named-effect-boundary"
    assert clicked["operation_map"]["named_calls"] == ["saveSettings"]
    assert "persistence" in clicked["effect_domains"]
    assert clicked["integration_disposition"] == ["unsupported-schedule"]
    completed = next(action for action in report["actions"] if action["handler"] == "onCompleted")
    assert completed["semantic_disposition"] == "unresolved-no-identifier"
    assert completed["consequence_disposition"] == "local-computation-or-read"
    declared = next(
        action for action in report["actions"] if action["handler"] == "onSchedulesChanged"
    )
    assert declared["object_type"] == "Connections"
    assert declared["trigger_class"] == "signal-callback"

    markdown = register.render_markdown(report)
    assert "1 action-bearing unit" in markdown
    assert "onCompleted" in markdown
    assert "Private UI prose is excluded" not in markdown


def test_register_rejects_invalid_counts_and_handler_indices() -> None:
    register = _load_module("build_ui_action_register_invalid", REGISTER_PATH)
    fixture = _fixture()
    fixture["unit_count"] = 2
    with pytest.raises(register.RegisterError, match="unit count"):
        register.build_register(fixture)

    fixture = _fixture()
    fixture["units"][0]["qml_bindings"][0]["function_index"] = 99
    with pytest.raises(register.RegisterError, match="invalid function index"):
        register.build_register(fixture)


def test_register_follows_nested_closure_identifier_edges() -> None:
    register = _load_module("build_ui_action_register_closure", REGISTER_PATH)
    fixture = _fixture()
    fixture["units"][0]["functions"][1]["closure_indices"] = [3]

    report = register.build_register(fixture)

    completed = next(action for action in report["actions"] if action["handler"] == "onCompleted")
    assert completed["referenced_identifiers"] == ["factoryReset"]
    assert completed["transitive_closure_count"] == 1
    assert completed["semantic_disposition"] == "identifier-level-map"
    assert completed["operation_map"]["named_calls"] == ["factoryReset"]
    assert completed["effect_domains"] == ["factory-reset", "schedule"]
    assert completed["integration_disposition"] == [
        "unsupported-reset",
        "unsupported-schedule",
    ]


def test_register_rejects_out_of_range_closure_target() -> None:
    register = _load_module("build_ui_action_register_bad_closure", REGISTER_PATH)
    fixture = _fixture()
    fixture["units"][0]["functions"][1]["closure_indices"] = [99]

    with pytest.raises(register.RegisterError, match="closure function index"):
        register.build_register(fixture)


def test_register_classifies_no_identifier_effect_free_stub() -> None:
    register = _load_module("build_ui_action_register_stub", REGISTER_PATH)
    fixture = _fixture()
    fixture["units"][0]["functions"][1]["is_effect_free_stub"] = True

    report = register.build_register(fixture)

    completed = next(action for action in report["actions"] if action["handler"] == "onCompleted")
    assert completed["referenced_identifiers"] == []
    assert completed["is_effect_free_stub"]
    assert completed["semantic_disposition"] == "effect-free-stub"
    assert completed["effect_domains"] == ["none"]
    assert completed["integration_disposition"] == ["firmware-ui-evidence-only"]


def test_exact_review_catalog_closes_three_touch_test_index_writes() -> None:
    register = _load_module("build_ui_action_register_reviewed", REGISTER_PATH)
    actions = [
        {
            "id": action_id,
            "unit": "_0x5f_Stherm_qml_View_Test_TouchTestPage_qml",
            "consequence_disposition": "indexed-state-write",
        }
        for action_id in (
            "ui-aab701d46b404c6d",
            "ui-3484face58e03f3e",
            "ui-eea19fd0068068a6",
        )
    ]

    register._apply_reviewed_consequences(
        actions,
        "2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e",
    )

    assert {action["consequence_disposition"] for action in actions} == {
        "diagnostic-local-indexed-state"
    }
    assert {action["review_evidence"] for action in actions} == {"exact-instruction-review"}
