#!/usr/bin/env python3
"""Inventory every embedded Qt 6 QV4 unit and function in one exact ELF."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from dump_qt6_qv4 import Qv4Unit, _decode_function, _instruction_spec, _referenced_name
from extract_qt6_meta_enum import _file_offset, _load_segments

_QML_DATA = re.compile(r"^([0-9a-fA-F]+)\s+[A-Za-z]\s+QmlCacheGeneratedCode::(.+)::qmlData$")
_EFFECT_FREE_STUB_INSTRUCTIONS = {
    "CreateCallContext",
    "LoadReg",
    "LoadUndefined",
    "PopContext",
    "Ret",
}
_NAMED_READ_INSTRUCTIONS = {
    "GetLookup",
    "GetOptionalLookup",
    "LoadGlobalLookup",
    "LoadName",
    "LoadOptionalProperty",
    "LoadProperty",
    "LoadQmlContextPropertyLookup",
    "LoadSuperProperty",
    "TypeofName",
}
_NAMED_WRITE_INSTRUCTIONS = {
    "SetLookup",
    "StoreNameSloppy",
    "StoreNameStrict",
    "StoreProperty",
    "StoreSuperProperty",
}
_NAMED_CALL_INSTRUCTIONS = {
    "CallGlobalLookup",
    "CallName",
    "CallProperty",
    "CallPropertyLookup",
    "CallQmlContextPropertyLookup",
}
_NAMED_DELETE_INSTRUCTIONS = {"DeleteName", "DeleteProperty"}
_DYNAMIC_CALL_INSTRUCTIONS = {
    "CallElement",
    "CallPossiblyDirectEval",
    "CallValue",
    "CallWithReceiver",
    "CallWithSpread",
    "TailCall",
}
_CONTROL_FLOW_INSTRUCTIONS = {
    "Jump",
    "JumpFalse",
    "JumpNoException",
    "JumpNotUndefined",
    "JumpTrue",
    "Resume",
    "UnwindDispatch",
    "UnwindToLabel",
    "Yield",
    "YieldStar",
}
_THROW_INSTRUCTIONS = {
    "DeadTemporalZoneCheck",
    "ThrowException",
    "ThrowOnNullOrUndefined",
}
_OBJECT_CREATION_INSTRUCTIONS = {
    "Construct",
    "ConstructWithSpread",
    "CreateClass",
    "CreateMappedArgumentsObject",
    "CreateRestParameter",
    "CreateUnmappedArgumentsObject",
    "DefineArray",
    "DefineObjectLiteral",
    "LoadClosure",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _private_value_digest(value: Any) -> str:
    return _sha256_bytes(repr(value).encode("utf-8"))


def _private_multiset_digest(values: list[Any]) -> str:
    """Fingerprint a private value multiset without retaining its members."""

    members = sorted(_private_value_digest(value) for value in values)
    return _sha256_bytes(json.dumps(members, separators=(",", ":")).encode("utf-8"))


def _semantic_argument(
    unit: Qv4Unit, instruction: str, argument_name: str, value: int
) -> tuple[str, str, int | str]:
    referenced = _referenced_name(unit, instruction, argument_name, value)
    if referenced is not None:
        return argument_name, "reference-sha256", _private_value_digest(referenced)
    if argument_name in {"internalClassId", "classIndex"} and instruction == (
        "DefineObjectLiteral"
    ):
        return argument_name, "class-sha256", _private_value_digest(unit.jsclass(value))
    if argument_name in {"index", "constIndex"} and instruction in {
        "LoadConst",
        "MoveConst",
    }:
        return argument_name, "constant-sha256", _private_value_digest(unit.constant(value))
    if instruction == "MoveRegExp" and argument_name == "regExpId":
        return argument_name, "regexp-sha256", _private_value_digest(unit.regexp(value))
    return argument_name, "integer", value


def _instruction_semantic_digest(
    unit: Qv4Unit,
    decoded: list[tuple[int, int, str, list[tuple[str, int]]]],
) -> str:
    normalized = [
        (
            instruction,
            [
                _semantic_argument(unit, instruction, argument_name, value)
                for argument_name, value in arguments
            ],
        )
        for _offset, _line, instruction, arguments in decoded
    ]
    return _sha256_bytes(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode())


def _argument_value(arguments: list[tuple[str, int]], target: str) -> int | None:
    return next((value for name, value in arguments if name == target), None)


def _row_names(unit: Qv4Unit, instruction: str, arguments: list[tuple[str, int]]) -> set[str]:
    return {
        referenced
        for argument_name, value in arguments
        if (referenced := _referenced_name(unit, instruction, argument_name, value)) is not None
    }


def _update_register_origins(
    unit: Qv4Unit,
    instruction: str,
    arguments: list[tuple[str, int]],
    previous: tuple[int, int, str, list[tuple[str, int]]] | None,
    register_origins: dict[int, set[str]],
) -> None:
    if instruction == "MoveReg":
        source = _argument_value(arguments, "srcReg")
        destination = _argument_value(arguments, "destReg")
        origins = register_origins.get(source, set())
    elif instruction == "StoreReg":
        destination = _argument_value(arguments, "reg")
        origins = set()
        if previous is not None:
            _offset, _line, previous_instruction, previous_args = previous
            origins = _row_names(unit, previous_instruction, previous_args)
            if previous_instruction == "LoadReg":
                origins = register_origins.get(_argument_value(previous_args, "reg"), set())
    else:
        return
    if not isinstance(destination, int):
        return
    if origins:
        register_origins[destination] = set(origins)
    else:
        register_origins.pop(destination, None)


def _operation_summary(
    unit: Qv4Unit,
    decoded: list[tuple[int, int, str, list[tuple[str, int]]]],
) -> dict[str, Any]:
    named_reads: set[str] = set()
    named_writes: set[str] = set()
    named_calls: set[str] = set()
    named_constructs: set[str] = set()
    named_deletes: set[str] = set()
    counts = Counter()
    register_origins: dict[int, set[str]] = {}
    previous: tuple[int, int, str, list[tuple[str, int]]] | None = None
    for row in decoded:
        _offset, _line, instruction, arguments = row
        names = _row_names(unit, instruction, arguments)
        for target, instruction_set in (
            (named_reads, _NAMED_READ_INSTRUCTIONS),
            (named_writes, _NAMED_WRITE_INSTRUCTIONS),
            (named_calls, _NAMED_CALL_INSTRUCTIONS),
            (named_deletes, _NAMED_DELETE_INSTRUCTIONS),
        ):
            if instruction in instruction_set:
                target.update(names)
        counts["named_call_count"] += instruction in _NAMED_CALL_INSTRUCTIONS
        counts["dynamic_call_count"] += instruction in _DYNAMIC_CALL_INSTRUCTIONS
        if instruction in {"Construct", "ConstructWithSpread"}:
            function_register = _argument_value(arguments, "func")
            origins = register_origins.get(function_register, set())
            if origins:
                named_constructs.update(origins)
                counts["named_construct_count"] += 1
            else:
                counts["unresolved_construct_count"] += 1
        counts["element_read_count"] += instruction == "LoadElement"
        counts["element_write_count"] += instruction == "StoreElement"
        counts["delete_count"] += instruction in _NAMED_DELETE_INSTRUCTIONS
        counts["control_flow_count"] += instruction in _CONTROL_FLOW_INSTRUCTIONS
        counts["throw_count"] += instruction in _THROW_INSTRUCTIONS
        counts["object_creation_count"] += instruction in _OBJECT_CREATION_INSTRUCTIONS
        _update_register_origins(unit, instruction, arguments, previous, register_origins)
        previous = row
    return {
        "named_reads": sorted(named_reads),
        "named_writes": sorted(named_writes),
        "named_calls": sorted(named_calls),
        "named_constructs": sorted(named_constructs),
        "named_deletes": sorted(named_deletes),
        **{
            name: counts[name]
            for name in (
                "named_call_count",
                "dynamic_call_count",
                "named_construct_count",
                "unresolved_construct_count",
                "element_read_count",
                "element_write_count",
                "delete_count",
                "control_flow_count",
                "throw_count",
                "object_creation_count",
            )
        },
    }


def _qml_data_symbols(path: Path) -> list[tuple[int, str]]:
    completed = subprocess.run(
        ["nm", "-C", "--defined-only", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    result = []
    for line in completed.stdout.splitlines():
        match = _QML_DATA.match(line)
        if match:
            result.append((int(match.group(1), 16), match.group(2)))
    if not result:
        raise ValueError("no QmlCacheGeneratedCode qmlData symbols found")
    return sorted(result)


def _function_record(
    unit: Qv4Unit, specification: list[tuple[str, list[str]]], index: int
) -> dict[str, Any]:
    function = unit.function(index)
    referenced_names: set[str] = set()
    closure_indices: set[int] = set()
    decoded = _decode_function(unit, specification, index)
    for _offset, _line, instruction, arguments in decoded:
        for argument_name, value in arguments:
            referenced = _referenced_name(unit, instruction, argument_name, value)
            if referenced is not None:
                referenced_names.add(referenced)
            if instruction == "LoadClosure" and argument_name == "value":
                if not isinstance(value, int) or not 0 <= value < unit.function_count:
                    raise ValueError("LoadClosure target is outside its QV4 unit")
                closure_indices.add(value)
    return {
        "index": index,
        "name": function["name"],
        "source_line": function["line"],
        "source_column": function["column"],
        "code_size": function["code_size"],
        "instruction_count": len(decoded),
        "instruction_semantic_sha256": _instruction_semantic_digest(unit, decoded),
        "operation_summary": _operation_summary(unit, decoded),
        "formals": [name for name, _type_id in function["formals"]],
        "local_count": len(function["locals"]),
        "referenced_names": sorted(referenced_names),
        "closure_indices": sorted(closure_indices),
        "is_effect_free_stub": bool(decoded)
        and all(
            instruction in _EFFECT_FREE_STUB_INSTRUCTIONS
            for _offset, _line, instruction, _arguments in decoded
        ),
    }


def _qml_object_record(unit: Qv4Unit, qml_object: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": qml_object["index"],
        "inherited_type": qml_object["inherited_type"],
        "id_name": qml_object["id_name"],
        "line": qml_object["line"],
        "column": qml_object["column"],
        "function_indices": unit.qml_object_function_indices(qml_object),
    }


def _qml_binding_record(binding: dict[str, Any]) -> dict[str, Any]:
    value = binding["value"]
    record = {
        "object_index": binding["object_index"],
        "object_type": binding["object_type"],
        "index": binding["index"],
        "property": binding["property"],
        "type": binding["type"],
        "flags": binding["flags"],
        "line": binding["line"],
        "column": binding["column"],
        "value_line": binding["value_line"],
        "value_column": binding["value_column"],
    }
    if binding["type"] == "script":
        record["function_index"] = value["function_index"]
    elif binding["type"] == "translation":
        record["translation_sha256"] = _private_value_digest(value)
    elif isinstance(value, str):
        encoded = value.encode("utf-8")
        record["value_length"] = len(value)
        record["value_sha256"] = _sha256_bytes(encoded)
    elif value is None or isinstance(value, (bool, int, float)):
        record["value"] = value
    return record


def inventory(binary: Path, instruction_header: Path) -> dict[str, Any]:
    blob = binary.read_bytes()
    header = instruction_header.read_bytes()
    _endian, segments = _load_segments(blob)
    specification = _instruction_spec(instruction_header)
    units = []
    for address, symbol in _qml_data_symbols(binary):
        offset = _file_offset(address, segments, 28)
        unit = Qv4Unit.from_bytes(blob, offset)
        functions = [
            _function_record(unit, specification, index) for index in range(unit.function_count)
        ]
        qml_objects = [_qml_object_record(unit, item) for item in unit.qml_objects()]
        qml_enums = unit.qml_enums()
        qml_properties = unit.qml_properties()
        qml_signals = unit.qml_signals()
        qml_bindings = [_qml_binding_record(item) for item in unit.qml_bindings()]
        literal_pool_values = [
            *(("string", unit.string(index)) for index in range(unit.string_count)),
            *(("constant", unit.constant(index)) for index in range(unit.constant_count)),
            *(("regexp", unit.regexp(index)) for index in range(unit.regexp_count)),
            *(("jsclass", unit.jsclass(index)) for index in range(unit.jsclass_count)),
            *(("translation", unit.translation(index)) for index in range(unit.translation_count)),
        ]
        units.append(
            {
                "symbol": symbol,
                "virtual_address": f"0x{address:08x}",
                "file_offset": offset,
                "size": len(unit.data),
                "sha256": _sha256_bytes(unit.data),
                "source_file": unit.string(unit.source_file),
                "final_url": unit.string(unit.final_url),
                "function_count": unit.function_count,
                "lookup_count": unit.lookup_count,
                "string_count": unit.string_count,
                "constant_count": unit.constant_count,
                "regexp_count": unit.regexp_count,
                "jsclass_count": unit.jsclass_count,
                "translation_count": unit.translation_count,
                "translation_multiset_sha256": _private_multiset_digest(
                    [unit.translation(index) for index in range(unit.translation_count)]
                ),
                "literal_pool_multiset_sha256": _private_multiset_digest(literal_pool_values),
                "functions": functions,
                "qml_object_count": len(qml_objects),
                "qml_enum_count": len(qml_enums),
                "qml_property_count": len(qml_properties),
                "qml_signal_count": len(qml_signals),
                "qml_binding_count": len(qml_bindings),
                "qml_objects": qml_objects,
                "qml_enums": qml_enums,
                "qml_properties": qml_properties,
                "qml_signals": qml_signals,
                "qml_bindings": qml_bindings,
            }
        )

    all_functions = [function for unit in units for function in unit["functions"]]
    return {
        "schema_version": 4,
        "binary": binary.name,
        "binary_sha256": _sha256_bytes(blob),
        "instruction_header": instruction_header.name,
        "instruction_header_sha256": _sha256_bytes(header),
        "unit_count": len(units),
        "function_count": len(all_functions),
        "instruction_count": sum(function["instruction_count"] for function in all_functions),
        "qml_object_count": sum(unit["qml_object_count"] for unit in units),
        "qml_enum_count": sum(unit["qml_enum_count"] for unit in units),
        "qml_property_count": sum(unit["qml_property_count"] for unit in units),
        "qml_signal_count": sum(unit["qml_signal_count"] for unit in units),
        "qml_binding_count": sum(unit["qml_binding_count"] for unit in units),
        "unit_corpus_sha256": _sha256_bytes(
            b"".join(bytes.fromhex(unit["sha256"]) for unit in units)
        ),
        "units": units,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--instruction-header", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = inventory(args.binary, args.instruction_header)
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
