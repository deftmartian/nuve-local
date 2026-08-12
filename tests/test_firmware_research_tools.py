"""Regression tests for the private firmware-analysis helpers."""

from __future__ import annotations

import importlib.util
import json
import re
import struct
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
AUDIT_PATH = (
    ROOT
    / ".agents"
    / "skills"
    / "analyze-nuve-firmware"
    / "scripts"
    / "audit_decompile_coverage.py"
)
INVENTORY_PATH = ROOT / "scripts" / "inventory_firmware_artifacts.py"
FILESYSTEM_INVENTORY_PATH = ROOT / "scripts" / "inventory_filesystem_tree.py"
DEVICE_TREE_INVENTORY_PATH = ROOT / "scripts" / "inventory_device_tree.py"
QV4_DUMP_PATH = (
    ROOT / ".agents" / "skills" / "analyze-nuve-firmware" / "scripts" / "dump_qt6_qv4.py"
)


def _fdt_fixture() -> bytes:
    strings = b"compatible\0reg\0enabled\0"
    structure = bytearray()
    structure.extend(struct.pack(">I", 1))
    structure.extend(b"\0\0\0\0")
    compatible = b"vendor,board\0"
    structure.extend(struct.pack(">III", 3, len(compatible), 0))
    structure.extend(compatible)
    structure.extend(b"\0" * ((-len(compatible)) % 4))
    structure.extend(struct.pack(">I", 1))
    child_name = b"i2c@1000\0"
    structure.extend(child_name)
    structure.extend(b"\0" * ((-len(child_name)) % 4))
    structure.extend(struct.pack(">III2I", 3, 8, 11, 0x1000, 0x100))
    structure.extend(struct.pack(">III", 3, 0, 15))
    structure.extend(struct.pack(">III", 2, 2, 9))
    reserved = b"\0" * 16
    structure_offset = 40 + len(reserved)
    strings_offset = structure_offset + len(structure)
    total_size = strings_offset + len(strings)
    header = struct.pack(
        ">10I",
        0xD00DFEED,
        total_size,
        structure_offset,
        strings_offset,
        40,
        17,
        16,
        0,
        len(strings),
        len(structure),
    )
    return header + reserved + structure + strings


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_decompile_coverage_requires_a_successful_attempt(tmp_path: Path) -> None:
    audit = _load_module("audit_decompile_coverage", AUDIT_PATH)
    failed = tmp_path / "failed.txt"
    recovered = tmp_path / "recovered.txt"
    failed.write_text(
        "INFO script> ===== DeviceIOController::processNRFResponse @ 0033c794 =====\n"
        "INFO script> DECOMPILE FAILED:\n"
        "Low-level Error: Cannot properly adjust input varnodes\n"
    )
    recovered.write_text(
        "INFO script> ===== DeviceIOController::processNRFResponse @ 0033c794 =====\n"
        "void DeviceIOController::processNRFResponse(void) {}\n"
    )

    assert audit._covered_addresses([failed], address_bias=0x10000) == set()
    assert audit._covered_addresses([failed, recovered], address_bias=0x10000) == {0x32C794}


def test_private_artifact_inventory_is_deterministic_and_metadata_only(
    tmp_path: Path,
) -> None:
    inventory_tool = _load_module("inventory_firmware_artifacts", INVENTORY_PATH)
    (tmp_path / "recovery-files").mkdir()
    (tmp_path / "recovery-files" / "root.gz").write_bytes(b"firmware")
    (tmp_path / "live-config").mkdir()
    (tmp_path / "live-config" / "private.ini").write_text("secret=value\n")
    (tmp_path / inventory_tool.PRIVATE_REPORT_NAME).write_text("excluded\n")

    first = inventory_tool.inventory(tmp_path)
    second = inventory_tool.inventory(tmp_path)

    assert first == second
    assert first["artifact_count"] == 2
    assert first["total_size"] == 21
    assert {item["relative_path"] for item in first["artifacts"]} == {
        "live-config/private.ini",
        "recovery-files/root.gz",
    }
    assert "secret=value" not in json.dumps(first)
    groups = {item["relative_path"]: item["firmware_association"] for item in first["artifacts"]}
    assert groups["recovery-files/root.gz"] == "exact recovery 1.5.8"


def test_filesystem_inventory_records_hashes_metadata_and_symlinks(tmp_path: Path) -> None:
    inventory_tool = _load_module("inventory_filesystem_tree", FILESYSTEM_INVENTORY_PATH)
    (tmp_path / "usr" / "local" / "bin").mkdir(parents=True)
    application = tmp_path / "usr" / "local" / "bin" / "appStherm"
    application.write_bytes(b"\x7fELFsynthetic")
    application.chmod(0o755)
    (tmp_path / "app").symlink_to("usr/local/bin/appStherm")

    report = inventory_tool.inventory(tmp_path, source_image_sha256="a" * 64)
    records = {record["path"]: record for record in report["records"]}

    assert report["source_image_sha256"] == "a" * 64
    assert report["regular_file_count"] == 1
    assert report["kind_counts"] == {"elf": 1}
    assert records["/usr/local/bin/appStherm"]["mode"] == "0755"
    assert records["/app"] == {
        "path": "/app",
        "mode": "0777",
        "uid": records["/app"]["uid"],
        "gid": records["/app"]["gid"],
        "type": "symlink",
        "target": "usr/local/bin/appStherm",
    }


def test_device_tree_inventory_parses_exact_nodes_properties_and_cells() -> None:
    inventory_tool = _load_module("inventory_device_tree", DEVICE_TREE_INVENTORY_PATH)

    nodes = inventory_tool.parse_device_tree(_fdt_fixture())
    records = inventory_tool.inventory_device_tree(nodes)

    assert [node.path for node in nodes] == ["/", "/i2c@1000"]
    assert records == [
        {"path": "/", "properties": {"compatible": "vendor,board"}},
        {
            "path": "/i2c@1000",
            "properties": {
                "reg": ["0x00001000", "0x00000100"],
                "enabled": True,
            },
        },
    ]
    assert inventory_tool.decode_property(b"\0\0\0\0") == ["0x00000000"]


def test_device_tree_inventory_rejects_invalid_magic_and_supports_filters() -> None:
    inventory_tool = _load_module("inventory_device_tree_filtered", DEVICE_TREE_INVENTORY_PATH)
    data = _fdt_fixture()
    nodes = inventory_tool.parse_device_tree(data)

    records = inventory_tool.inventory_device_tree(
        nodes,
        node_pattern=re.compile("i2c"),
        property_pattern=re.compile("reg"),
    )
    assert records == [
        {
            "path": "/i2c@1000",
            "properties": {"reg": ["0x00001000", "0x00000100"]},
        }
    ]
    with pytest.raises(inventory_tool.DeviceTreeError, match="magic"):
        inventory_tool.parse_device_tree(b"bad!" + data[4:])


def test_qv4_unit_can_reuse_a_shared_binary_blob() -> None:
    qv4 = _load_module("dump_qt6_qv4", QV4_DUMP_PATH)
    unit_data = bytearray(248)
    unit_data[:8] = b"qv4cdata"
    struct.pack_into("<I", unit_data, 24, len(unit_data))

    unit = qv4.Qv4Unit.from_bytes(b"prefix" + unit_data + b"suffix", 6)

    assert len(unit.data) == 248
    assert unit.function_count == 0


def test_qv4_runtime_string_instruction_resolves_exact_text() -> None:
    qv4 = _load_module("dump_qt6_qv4_runtime_string", QV4_DUMP_PATH)

    class UnitStub:
        @staticmethod
        def string(index: int) -> str:
            assert index == 17
            return "until_next_activity"

    assert (
        qv4._referenced_name(UnitStub(), "LoadRuntimeString", "stringId", 17)
        == "until_next_activity"
    )


def test_qv4_regexp_layout_decodes_pattern_and_flags() -> None:
    qv4 = _load_module("dump_qt6_qv4_regexp", QV4_DUMP_PATH)
    data = bytearray(16)
    struct.pack_into("<I", data, 8, (7 << 5) | 0x12)

    unit = qv4.Qv4Unit.__new__(qv4.Qv4Unit)
    unit.data = bytes(data)
    unit.regexp_count = 1
    unit.regexp_offset = 8
    unit.string = lambda index: {7: r"^\d{2}$"}[index]

    assert unit.regexp(0) == (r"^\d{2}$", 0x12)


def test_qv4_translation_layout_decodes_source_comment_and_plural() -> None:
    qv4 = _load_module("dump_qt6_qv4_translation", QV4_DUMP_PATH)
    data = bytearray(32)
    struct.pack_into("<IIiI", data, 8, 3, 4, -1, 0)

    unit = qv4.Qv4Unit.__new__(qv4.Qv4Unit)
    unit.data = bytes(data)
    unit.translation_count = 1
    unit.translation_offset = 8
    unit.string = lambda index: {3: "Source text", 4: "Translator comment"}[index]

    expected = ("Source text", "Translator comment", -1)
    assert unit.translation(0) == expected
    assert unit._qml_binding_value(5, 0, 3) == expected
    assert unit._qml_binding_value(6, 0, 3) == "Source text"
    with pytest.raises(ValueError, match="outside"):
        unit.translation(1)


def test_qv4_qml_enum_layout_decodes_names_and_signed_values() -> None:
    qv4 = _load_module("dump_qt6_qv4_qml_enum", QV4_DUMP_PATH)
    data = bytearray(168)
    qml_offset = 16
    object_offset = qml_offset + 24
    struct.pack_into("<IIII", data, qml_offset, 0, 0, 1, 16)
    struct.pack_into("<I", data, qml_offset + 16, 24)
    location = 5 | (2 << 20)
    struct.pack_into(
        qv4.QML_OBJECT_FORMAT,
        data,
        object_offset,
        0,
        4,
        0,
        -1,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        84,
        0,
        0,
        0,
        0,
        0,
        0,
        location,
        0,
        0,
        0,
        0,
        0,
    )
    struct.pack_into("<I", data, object_offset + 84, 88)
    struct.pack_into("<III", data, object_offset + 88, 1, 2, location)
    struct.pack_into("<IiI", data, object_offset + 100, 2, 0, location)
    struct.pack_into("<IiI", data, object_offset + 112, 3, -1, location)

    unit = qv4.Qv4Unit.__new__(qv4.Qv4Unit)
    unit.data = bytes(data)
    unit.qml_offset = qml_offset
    names = ["AppSpecCPP", "HoldPeriod", "TwoHours", "UntilChanged", ""]
    unit.string = lambda index: names[index]

    assert unit.qml_enums() == [
        {
            "object_index": 0,
            "object_type": "AppSpecCPP",
            "name": "HoldPeriod",
            "line": 5,
            "column": 2,
            "values": [
                {"name": "TwoHours", "value": 0, "line": 5, "column": 2},
                {"name": "UntilChanged", "value": -1, "line": 5, "column": 2},
            ],
        }
    ]


def test_qv4_qml_property_and_number_binding_layouts_decode() -> None:
    qv4 = _load_module("dump_qt6_qv4_qml_property_binding", QV4_DUMP_PATH)
    data = bytearray(184)
    qml_offset = 16
    object_offset = qml_offset + 24
    constant_offset = 176
    struct.pack_into("<IIII", data, qml_offset, 0, 0, 1, 16)
    struct.pack_into("<I", data, qml_offset + 16, 24)
    location = 12 | (3 << 20)
    struct.pack_into(
        qv4.QML_OBJECT_FORMAT,
        data,
        object_offset,
        0,
        2,
        0,
        -1,
        0,
        1,
        0,
        84,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        96,
        0,
        0,
        location,
        0,
        0,
        0,
        0,
        0,
    )
    property_data = 1 | (1 << 29) | (1 << 31)
    struct.pack_into("<III", data, object_offset + 84, 1, property_data, location)
    struct.pack_into(
        "<IIIIII",
        data,
        object_offset + 96,
        1,
        (2 << 16) | 0x8,
        0,
        0,
        location,
        location,
    )
    struct.pack_into("<Q", data, constant_offset, (0x00038000 << 32) | 12)

    unit = qv4.Qv4Unit.__new__(qv4.Qv4Unit)
    unit.data = bytes(data)
    unit.qml_offset = qml_offset
    unit.constant_offset = constant_offset
    names = ["ScheduleControllerV2", "maximumActivityPerDay", ""]
    unit.string = lambda index: names[index]

    assert unit.qml_properties() == [
        {
            "object_index": 0,
            "object_type": "ScheduleControllerV2",
            "index": 0,
            "name": "maximumActivityPerDay",
            "type": "int",
            "is_builtin": True,
            "required": False,
            "list": False,
            "read_only": True,
            "line": 12,
            "column": 3,
        }
    ]
    assert unit.qml_bindings() == [
        {
            "object_index": 0,
            "object_type": "ScheduleControllerV2",
            "index": 0,
            "property": "maximumActivityPerDay",
            "type": "number",
            "flags": 0x8,
            "value": 12,
            "line": 12,
            "column": 3,
            "value_line": 12,
            "value_column": 3,
        }
    ]


def test_qv4_qml_signal_layout_decodes_typed_parameters() -> None:
    qv4 = _load_module("dump_qt6_qv4_qml_signal", QV4_DUMP_PATH)
    data = bytearray(184)
    qml_offset = 16
    object_offset = qml_offset + 24
    location = 19 | (4 << 20)
    struct.pack_into("<IIII", data, qml_offset, 0, 0, 1, 16)
    struct.pack_into("<I", data, qml_offset + 16, 24)
    struct.pack_into(
        qv4.QML_OBJECT_FORMAT,
        data,
        object_offset,
        0,
        5,
        0,
        -1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        84,
        1,
        0,
        88,
        0,
        0,
        location,
        0,
        0,
        0,
        0,
        0,
    )
    struct.pack_into("<I", data, object_offset + 84, 92)
    struct.pack_into("<III", data, object_offset + 92, 1, 2, location)
    struct.pack_into("<II", data, object_offset + 104, 2, 3 << 1)
    struct.pack_into("<II", data, object_offset + 112, 4, (4 << 1) | 1)

    unit = qv4.Qv4Unit.__new__(qv4.Qv4Unit)
    unit.data = bytes(data)
    unit.qml_offset = qml_offset
    names = ["SensorPairPage", "sensorPaired", "sensor", "Sensor", "", "root"]
    unit.string = lambda index: names[index]

    assert unit.qml_signals() == [
        {
            "object_index": 0,
            "object_type": "SensorPairPage",
            "index": 0,
            "name": "sensorPaired",
            "parameters": [
                {"name": "sensor", "type": "Sensor", "is_builtin": False},
                {"name": "", "type": "string", "is_builtin": True},
            ],
            "line": 19,
            "column": 4,
        }
    ]


def test_qv4_qml_object_function_table_maps_exact_indices() -> None:
    qv4 = _load_module("dump_qt6_qv4_qml_functions", QV4_DUMP_PATH)
    data = bytearray(144)
    qml_offset = 16
    object_offset = qml_offset + 24
    struct.pack_into("<IIII", data, qml_offset, 0, 0, 1, 16)
    struct.pack_into("<I", data, qml_offset + 16, 24)
    struct.pack_into(
        qv4.QML_OBJECT_FORMAT,
        data,
        object_offset,
        0,
        1,
        0,
        -1,
        2,
        0,
        84,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )
    struct.pack_into("<II", data, object_offset + 84, 3, 7)

    unit = qv4.Qv4Unit.__new__(qv4.Qv4Unit)
    unit.data = bytes(data)
    unit.qml_offset = qml_offset
    unit.function_count = 8
    unit.string = lambda index: ["Connections", "callbacks"][index]

    qml_object = unit.qml_object(0)
    assert unit.qml_object_function_indices(qml_object) == [3, 7]

    unit.function_count = 7
    with pytest.raises(ValueError, match="invalid function index"):
        unit.qml_object_function_indices(qml_object)
