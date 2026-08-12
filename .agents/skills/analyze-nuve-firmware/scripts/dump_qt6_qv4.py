#!/usr/bin/env python3
"""Inspect function names, lookups, and bytecode in a Qt 6 QV4 compiled unit."""

from __future__ import annotations

import argparse
import re
import struct
from pathlib import Path
from typing import Any

QML_OBJECT_FORMAT = "<IIIiHHIIIHHIIHHIIIIIIH2xIH2x"
QML_BUILTIN_TYPES = (
    "var",
    "int",
    "bool",
    "real",
    "string",
    "url",
    "time",
    "date",
    "datetime",
    "rect",
    "point",
    "size",
    "invalid",
)
QML_BINDING_TYPES = (
    "invalid",
    "boolean",
    "number",
    "string",
    "null",
    "translation",
    "translation_by_id",
    "script",
    "object",
    "attached_property",
    "group_property",
)


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


class Qv4Unit:
    """Minimal reader for the Qt 6.4 compiled-data structures used by appStherm."""

    def __init__(self, source: str) -> None:
        path_text, separator, offset_text = source.rpartition("@")
        path = Path(path_text if separator else source)
        offset = int(offset_text, 0) if separator else 0
        self._load(path.read_bytes(), offset)

    @classmethod
    def from_bytes(cls, raw: bytes, offset: int = 0) -> Qv4Unit:
        """Load one unit without rereading a shared containing binary."""

        unit = cls.__new__(cls)
        unit._load(raw, offset)
        return unit

    def _load(self, raw: bytes, offset: int) -> None:
        if offset < 0 or offset + 28 > len(raw):
            raise ValueError("compiled-unit offset is outside the input")
        if raw[offset : offset + 8] != b"qv4cdata":
            raise ValueError("input does not begin with a QV4 compiled-data unit")
        unit_size = _u32(raw, offset + 24)
        if unit_size < 248 or offset + unit_size > len(raw):
            raise ValueError("compiled-unit size is invalid")
        self.data = raw[offset : offset + unit_size]

        values = struct.unpack_from("<" + "I" * 35, self.data, 108)
        names = (
            "flags",
            "string_count",
            "string_offset",
            "function_count",
            "function_offset",
            "class_count",
            "class_offset",
            "template_count",
            "template_offset",
            "block_count",
            "block_offset",
            "lookup_count",
            "lookup_offset",
            "regexp_count",
            "regexp_offset",
            "constant_count",
            "constant_offset",
            "jsclass_count",
            "jsclass_offset",
            "translation_count",
            "translation_offset",
            "local_export_count",
            "local_export_offset",
            "indirect_export_count",
            "indirect_export_offset",
            "star_export_count",
            "star_export_offset",
            "import_count",
            "import_offset",
            "module_request_count",
            "module_request_offset",
            "root_function",
            "source_file",
            "final_url",
            "qml_offset",
        )
        for name, value in zip(names, values, strict=True):
            setattr(self, name, value)

    def string(self, index: int) -> str:
        if not 0 <= index < self.string_count:
            return f"<dynamic:{index}>"
        offset = _u32(self.data, self.string_offset + index * 4)
        size = struct.unpack_from("<i", self.data, offset)[0]
        end = offset + 4 + size * 2
        if size < 0 or end > len(self.data):
            raise ValueError(f"string {index} points outside the compiled unit")
        return self.data[offset + 4 : end].decode("utf-16le")

    def lookup(self, index: int) -> tuple[str, int]:
        word = _u32(self.data, self.lookup_offset + index * 4)
        return self.string(word >> 4), word & 0xF

    def regexp(self, index: int) -> tuple[str, int]:
        """Return the pattern and flags for one compiled RegExp literal."""

        if not 0 <= index < self.regexp_count:
            raise ValueError(f"regular expression {index} is outside the compiled unit")
        word = _u32(self.data, self.regexp_offset + index * 4)
        return self.string(word >> 5), word & 0x1F

    def jsclass(self, index: int) -> list[tuple[str, bool]]:
        offset = _u32(self.data, self.jsclass_offset + index * 4)
        count = _u32(self.data, offset)
        result = []
        for item in range(count):
            word = _u32(self.data, offset + 4 + item * 4)
            result.append((self.string(word & 0x7FFFFFFF), bool(word >> 31)))
        return result

    def constant(self, index: int) -> int | bool | float:
        word = struct.unpack_from("<Q", self.data, self.constant_offset + index * 8)[0]
        tag = word >> 32
        if tag == 0x00038000:
            value = word & 0xFFFFFFFF
            return value - (1 << 32) if value & 0x80000000 else value
        if tag == 0x00030000:
            return bool(word & 1)
        encoded = word ^ 0xFFFC000000000000
        return struct.unpack("<d", struct.pack("<Q", encoded))[0]

    def translation(self, index: int) -> tuple[str, str, int]:
        """Decode one Qt 6.4 CompiledData::TranslationData record."""

        if not 0 <= index < self.translation_count:
            raise ValueError(f"translation index {index} is outside the compiled unit")
        offset = self.translation_offset + index * 16
        if offset + 16 > len(self.data):
            raise ValueError("translation record is outside the compiled unit")
        string_index, comment_index, number, _padding = struct.unpack_from(
            "<IIiI", self.data, offset
        )
        return self.string(string_index), self.string(comment_index), number

    @staticmethod
    def _location(word: int) -> tuple[int, int]:
        return word & ((1 << 20) - 1), word >> 20

    def qml_object(self, index: int) -> dict[str, Any]:
        """Return the fixed fields for one Qt 6.4 QML object record."""

        qml_offset = self.qml_offset
        if qml_offset <= 0 or qml_offset + 16 > len(self.data):
            raise ValueError("compiled unit has no valid QML unit")
        _import_count, _imports_offset, object_count, objects_offset = struct.unpack_from(
            "<IIII", self.data, qml_offset
        )
        if not 0 <= index < object_count:
            raise ValueError(f"QML object index {index} is outside the compiled unit")
        table_entry = qml_offset + objects_offset + index * 4
        if table_entry + 4 > len(self.data):
            raise ValueError("QML object offset table is outside the compiled unit")
        offset = qml_offset + _u32(self.data, table_entry)
        if offset + 84 > len(self.data):
            raise ValueError("QML object record is outside the compiled unit")
        (
            inherited_type,
            id_name,
            flags_and_id,
            default_property,
            function_count,
            property_count,
            functions_offset,
            properties_offset,
            aliases_offset,
            alias_count,
            enum_count,
            enums_offset,
            signals_offset,
            signal_count,
            binding_count,
            bindings_offset,
            named_object_count,
            named_objects_offset,
            location,
            id_location,
            inline_components_offset,
            inline_component_count,
            required_properties_offset,
            required_property_count,
        ) = struct.unpack_from(QML_OBJECT_FORMAT, self.data, offset)
        line, column = self._location(location)
        return {
            "index": index,
            "record_offset": offset,
            "inherited_type": self.string(inherited_type),
            "id_name": self.string(id_name),
            "flags_and_id": flags_and_id,
            "default_property": default_property,
            "function_count": function_count,
            "property_count": property_count,
            "functions_offset": functions_offset,
            "properties_offset": properties_offset,
            "aliases_offset": aliases_offset,
            "alias_count": alias_count,
            "enum_count": enum_count,
            "enums_offset": enums_offset,
            "signals_offset": signals_offset,
            "signal_count": signal_count,
            "binding_count": binding_count,
            "bindings_offset": bindings_offset,
            "named_object_count": named_object_count,
            "named_objects_offset": named_objects_offset,
            "line": line,
            "column": column,
            "id_location": id_location,
            "inline_components_offset": inline_components_offset,
            "inline_component_count": inline_component_count,
            "required_properties_offset": required_properties_offset,
            "required_property_count": required_property_count,
        }

    def qml_objects(self) -> list[dict[str, Any]]:
        if self.qml_offset <= 0 or self.qml_offset + 16 > len(self.data):
            return []
        object_count = _u32(self.data, self.qml_offset + 8)
        return [self.qml_object(index) for index in range(object_count)]

    def qml_object_function_indices(self, qml_object: dict[str, Any]) -> list[int]:
        """Return the compiled function indices owned by one QML object."""

        count = qml_object["function_count"]
        table = qml_object["record_offset"] + qml_object["functions_offset"]
        if table < 0 or table + count * 4 > len(self.data):
            raise ValueError("QML object function table is outside the compiled unit")
        indices = [_u32(self.data, table + index * 4) for index in range(count)]
        if any(index >= self.function_count for index in indices):
            raise ValueError("QML object references an invalid function index")
        return indices

    def qml_enums(self) -> list[dict[str, Any]]:
        """Decode all declarative QML enums using Qt 6.4 on-disk layouts."""

        result = []
        for qml_object in self.qml_objects():
            object_offset = qml_object["record_offset"]
            table = object_offset + qml_object["enums_offset"]
            for enum_index in range(qml_object["enum_count"]):
                table_entry = table + enum_index * 4
                if table_entry + 4 > len(self.data):
                    raise ValueError("QML enum offset table is outside the compiled unit")
                enum_offset = object_offset + _u32(self.data, table_entry)
                if enum_offset + 12 > len(self.data):
                    raise ValueError("QML enum record is outside the compiled unit")
                name_index, value_count, location = struct.unpack_from(
                    "<III", self.data, enum_offset
                )
                values = []
                for value_index in range(value_count):
                    value_offset = enum_offset + 12 + value_index * 12
                    if value_offset + 12 > len(self.data):
                        raise ValueError("QML enum value is outside the compiled unit")
                    value_name, value, value_location = struct.unpack_from(
                        "<IiI", self.data, value_offset
                    )
                    value_line, value_column = self._location(value_location)
                    values.append(
                        {
                            "name": self.string(value_name),
                            "value": value,
                            "line": value_line,
                            "column": value_column,
                        }
                    )
                line, column = self._location(location)
                result.append(
                    {
                        "object_index": qml_object["index"],
                        "object_type": qml_object["inherited_type"],
                        "name": self.string(name_index),
                        "line": line,
                        "column": column,
                        "values": values,
                    }
                )
        return result

    def qml_properties(self) -> list[dict[str, Any]]:
        """Decode QML property declarations from every declarative object."""

        result = []
        for qml_object in self.qml_objects():
            table = qml_object["record_offset"] + qml_object["properties_offset"]
            for property_index in range(qml_object["property_count"]):
                offset = table + property_index * 12
                if offset + 12 > len(self.data):
                    raise ValueError("QML property record is outside the compiled unit")
                name_index, data, location = struct.unpack_from("<III", self.data, offset)
                type_index = data & ((1 << 28) - 1)
                is_builtin = bool(data & (1 << 29))
                type_name = (
                    QML_BUILTIN_TYPES[type_index]
                    if is_builtin and type_index < len(QML_BUILTIN_TYPES)
                    else self.string(type_index)
                )
                line, column = self._location(location)
                result.append(
                    {
                        "object_index": qml_object["index"],
                        "object_type": qml_object["inherited_type"],
                        "index": property_index,
                        "name": self.string(name_index),
                        "type": type_name,
                        "is_builtin": is_builtin,
                        "required": bool(data & (1 << 28)),
                        "list": bool(data & (1 << 30)),
                        "read_only": bool(data & (1 << 31)),
                        "line": line,
                        "column": column,
                    }
                )
        return result

    def _qml_parameter_type(self, raw_type: int) -> tuple[str, bool]:
        is_builtin = bool(raw_type & 1)
        type_index = raw_type >> 1
        type_name = (
            QML_BUILTIN_TYPES[type_index]
            if is_builtin and type_index < len(QML_BUILTIN_TYPES)
            else self.string(type_index)
        )
        return type_name, is_builtin

    def qml_signals(self) -> list[dict[str, Any]]:
        """Decode QML signal declarations and their typed parameters."""

        result = []
        for qml_object in self.qml_objects():
            object_offset = qml_object["record_offset"]
            table = object_offset + qml_object["signals_offset"]
            for signal_index in range(qml_object["signal_count"]):
                table_entry = table + signal_index * 4
                if table_entry + 4 > len(self.data):
                    raise ValueError("QML signal offset table is outside the compiled unit")
                signal_offset = object_offset + _u32(self.data, table_entry)
                if signal_offset + 12 > len(self.data):
                    raise ValueError("QML signal record is outside the compiled unit")
                name_index, parameter_count, location = struct.unpack_from(
                    "<III", self.data, signal_offset
                )
                parameters = []
                for parameter_index in range(parameter_count):
                    parameter_offset = signal_offset + 12 + parameter_index * 8
                    if parameter_offset + 8 > len(self.data):
                        raise ValueError("QML signal parameter is outside the compiled unit")
                    parameter_name, raw_type = struct.unpack_from(
                        "<II", self.data, parameter_offset
                    )
                    type_name, is_builtin = self._qml_parameter_type(raw_type)
                    parameters.append(
                        {
                            "name": self.string(parameter_name),
                            "type": type_name,
                            "is_builtin": is_builtin,
                        }
                    )
                line, column = self._location(location)
                result.append(
                    {
                        "object_index": qml_object["index"],
                        "object_type": qml_object["inherited_type"],
                        "index": signal_index,
                        "name": self.string(name_index),
                        "parameters": parameters,
                        "line": line,
                        "column": column,
                    }
                )
        return result

    def _qml_binding_value(self, binding_type: int, raw_value: int, string_index: int) -> Any:
        if binding_type == 1:
            return bool(raw_value & 0xFF)
        if binding_type == 2:
            return self.constant(raw_value)
        if binding_type == 3:
            return self.string(string_index)
        if binding_type == 4:
            return None
        if binding_type == 5:
            return self.translation(raw_value)
        if binding_type == 6:
            return self.string(string_index)
        if binding_type == 7:
            return {
                "function_index": raw_value,
                "source": self.string(string_index),
            }
        return raw_value

    def qml_bindings(self) -> list[dict[str, Any]]:
        """Decode QML binding records and literal values from all objects."""

        result = []
        for qml_object in self.qml_objects():
            table = qml_object["record_offset"] + qml_object["bindings_offset"]
            for binding_index in range(qml_object["binding_count"]):
                offset = table + binding_index * 24
                if offset + 24 > len(self.data):
                    raise ValueError("QML binding record is outside the compiled unit")
                (
                    property_name,
                    flags_and_type,
                    raw_value,
                    string_index,
                    location,
                    value_location,
                ) = struct.unpack_from("<IIIIII", self.data, offset)
                flags = flags_and_type & 0xFFFF
                binding_type = flags_and_type >> 16
                type_name = (
                    QML_BINDING_TYPES[binding_type]
                    if binding_type < len(QML_BINDING_TYPES)
                    else f"unknown-{binding_type}"
                )
                line, column = self._location(location)
                value_line, value_column = self._location(value_location)
                result.append(
                    {
                        "object_index": qml_object["index"],
                        "object_type": qml_object["inherited_type"],
                        "index": binding_index,
                        "property": self.string(property_name),
                        "type": type_name,
                        "flags": flags,
                        "value": self._qml_binding_value(binding_type, raw_value, string_index),
                        "line": line,
                        "column": column,
                        "value_line": value_line,
                        "value_column": value_column,
                    }
                )
        return result

    def function(self, index: int) -> dict[str, Any]:
        if not 0 <= index < self.function_count:
            raise ValueError(f"function index {index} is outside the compiled unit")
        offset = _u32(self.data, self.function_offset + index * 4)
        fields = struct.unpack_from("<IIIHHIIIHHIIIIHHHBB", self.data, offset)
        (
            code_offset,
            code_size,
            name_index,
            _length,
            formal_count,
            formals_offset,
            _return_type,
            locals_offset,
            local_count,
            line_count,
            _nested,
            _register_count,
            location,
            _label_count,
            _local_tdz,
            _first_register_tdz,
            _register_tdz,
            _flags,
            _padding,
        ) = fields
        formals = []
        for item in range(formal_count):
            name, type_id = struct.unpack_from("<II", self.data, offset + formals_offset + item * 8)
            formals.append((self.string(name), type_id))
        locals_ = [
            self.string(_u32(self.data, offset + locals_offset + item * 4))
            for item in range(local_count)
        ]
        line_table = offset + locals_offset + local_count * 4
        lines = [
            struct.unpack_from("<II", self.data, line_table + item * 8)
            for item in range(line_count)
        ]
        return {
            "index": index,
            "record_offset": offset,
            "code_offset": offset + code_offset,
            "code_size": code_size,
            "name": self.string(name_index),
            "formals": formals,
            "locals": locals_,
            "lines": lines,
            "line": location & ((1 << 20) - 1),
            "column": location >> 20,
        }


def _instruction_spec(header: Path) -> list[tuple[str, list[str]]]:
    source = header.read_text()
    definitions = {}
    for match in re.finditer(
        r"^#define INSTR_(\w+)\(op\) INSTRUCTION\(op,\s*(\w+),\s*(\d+)(?:,\s*([^\)]*))?\)",
        source,
        re.MULTILINE,
    ):
        macro, name, _count, raw_arguments = match.groups()
        definitions[macro] = (
            name,
            [item.strip() for item in (raw_arguments or "").split(",") if item.strip()],
        )
    start = source.index("#define FOR_EACH_MOTH_INSTR(F)")
    end = source.index("#define MOTH_NUM_INSTRUCTIONS", start)
    order = ["Nop", *re.findall(r"F\((\w+)\)", source[start:end])]
    try:
        return [definitions[name] for name in order]
    except KeyError as err:
        raise ValueError(f"unsupported Qt instruction header: missing {err.args[0]}") from err


def _register_name(register: int, formal_count: int) -> str:
    specials = {
        0: "function",
        1: "context",
        2: "accumulator",
        3: "this",
        4: "new.target",
        5: "argc",
    }
    if register in specials:
        return specials[register]
    register -= 6
    if register < formal_count:
        return f"a{register}"
    return f"r{register - formal_count}"


def _decode_function(
    unit: Qv4Unit, specification: list[tuple[str, list[str]]], index: int
) -> list[tuple[int, int, str, list[tuple[str, int]]]]:
    function = unit.function(index)
    code = unit.data[function["code_offset"] : function["code_offset"] + function["code_size"]]
    position = 0
    decoded = []
    while position < len(code):
        start = position
        opcode = code[position]
        position += 1
        if opcode == 1:
            if position >= len(code):
                raise ValueError(f"truncated extended opcode in function {index}")
            opcode = 256 + code[position]
            position += 1
        wide = bool(opcode & 1)
        instruction_index = opcode // 2
        if instruction_index >= len(specification):
            raise ValueError(f"invalid opcode {opcode} in function {index} at {start:#x}")
        name, argument_names = specification[instruction_index]
        arguments = []
        for argument_name in argument_names:
            width = 4 if wide else 1
            if position + width > len(code):
                raise ValueError(f"truncated instruction in function {index} at {start:#x}")
            value = struct.unpack_from("<i" if wide else "<b", code, position)[0]
            position += width
            arguments.append((argument_name, value))
        line = function["line"]
        for code_offset, line_number in function["lines"]:
            if code_offset > start:
                break
            line = line_number
        decoded.append((start, line, name, arguments))
    return decoded


def _referenced_name(unit: Qv4Unit, instruction: str, argument_name: str, value: int) -> str | None:
    if instruction == "LoadRuntimeString" and argument_name == "stringId":
        return unit.string(value)
    if argument_name in {"name", "property", "varName"}:
        return unit.string(value)
    lookup_instructions = {
        "GetLookup",
        "GetOptionalLookup",
        "SetLookup",
        "LoadGlobalLookup",
        "LoadQmlContextPropertyLookup",
        "CallPropertyLookup",
        "CallGlobalLookup",
        "CallQmlContextPropertyLookup",
    }
    if (
        argument_name in {"index", "lookupIndex"}
        and instruction in lookup_instructions
        and 0 <= value < unit.lookup_count
    ):
        return unit.lookup(value)[0]
    return None


def _render_function(unit: Qv4Unit, specification: list[tuple[str, list[str]]], index: int) -> None:
    function = unit.function(index)
    print(
        f"FUNCTION {index} {function['name']!r} "
        f"record={function['record_offset']:#x} code={function['code_offset']:#x} "
        f"size={function['code_size']} source={function['line']}:{function['column']} "
        f"formals={function['formals']} locals={function['locals']}"
    )
    register_arguments = {
        "reg",
        "srcReg",
        "destReg",
        "destTemp",
        "base",
        "args",
        "argv",
        "func",
        "thisObject",
        "heritage",
        "computedNames",
        "lhs",
    }
    for offset, line, instruction, arguments in _decode_function(unit, specification, index):
        rendered = []
        for argument_name, value in arguments:
            suffix = ""
            referenced = _referenced_name(unit, instruction, argument_name, value)
            if referenced is not None:
                suffix = f"={referenced!r}"
            elif (
                argument_name in {"internalClassId", "classIndex"}
                and instruction == "DefineObjectLiteral"
            ):
                suffix = f"={unit.jsclass(value)!r}"
            elif argument_name in {"index", "constIndex"} and instruction in {
                "LoadConst",
                "MoveConst",
            }:
                suffix = f"={unit.constant(value)!r}"
            elif instruction == "MoveRegExp" and argument_name == "regExpId":
                suffix = f"={unit.regexp(value)!r}"
            elif argument_name in register_arguments:
                suffix = f"={_register_name(value, len(function['formals']))}"
            rendered.append(f"{argument_name}={value}{suffix}")
        print(f"{offset:04x} L{line}: {instruction:<34} " + ", ".join(rendered))


def _render_qml_enums(unit: Qv4Unit) -> None:
    for qml_enum in unit.qml_enums():
        values = ", ".join(f"{item['name']}={item['value']}" for item in qml_enum["values"])
        print(
            f"QML ENUM object={qml_enum['object_index']} "
            f"type={qml_enum['object_type']!r} name={qml_enum['name']!r} "
            f"source={qml_enum['line']}:{qml_enum['column']} values=[{values}]"
        )


def _render_qml_properties(unit: Qv4Unit) -> None:
    for prop in unit.qml_properties():
        qualifiers = [
            name
            for name, enabled in (
                ("required", prop["required"]),
                ("list", prop["list"]),
                ("readonly", prop["read_only"]),
            )
            if enabled
        ]
        print(
            f"QML PROPERTY object={prop['object_index']} "
            f"type={prop['object_type']!r} name={prop['name']!r} "
            f"valueType={prop['type']!r} qualifiers={qualifiers!r} "
            f"source={prop['line']}:{prop['column']}"
        )


def _render_qml_signals(unit: Qv4Unit) -> None:
    for signal in unit.qml_signals():
        parameters = ", ".join(
            f"{parameter['name']}:{parameter['type']}" for parameter in signal["parameters"]
        )
        print(
            f"QML SIGNAL object={signal['object_index']} "
            f"type={signal['object_type']!r} name={signal['name']!r} "
            f"parameters=[{parameters}] source={signal['line']}:{signal['column']}"
        )


def _render_qml_bindings(unit: Qv4Unit) -> None:
    for binding in unit.qml_bindings():
        print(
            f"QML BINDING object={binding['object_index']} "
            f"type={binding['object_type']!r} property={binding['property']!r} "
            f"bindingType={binding['type']} flags={binding['flags']:#x} "
            f"value={binding['value']!r} source={binding['line']}:{binding['column']} "
            f"valueSource={binding['value_line']}:{binding['value_column']}"
        )


def _render_lookup_hits(
    unit: Qv4Unit,
    specification: list[tuple[str, list[str]]],
    functions: list[dict[str, Any]],
    targets: list[str],
) -> None:
    for target in targets:
        for function in functions:
            hits = []
            for offset, line, instruction, arguments in _decode_function(
                unit, specification, function["index"]
            ):
                for argument_name, value in arguments:
                    if _referenced_name(unit, instruction, argument_name, value) == target:
                        hits.append(f"{offset:#x}/L{line}/{instruction}")
            if hits:
                print(
                    f"LOOKUP {target!r} FUNCTION {function['index']} "
                    f"{function['name']!r}: {', '.join(hits)}"
                )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect a Qt 6 QV4 compiled unit or an in-place unit at FILE@OFFSET"
    )
    parser.add_argument("unit", help="compiled unit path, optionally FILE@OFFSET")
    parser.add_argument("functions", nargs="*", help="function index or exact function name")
    parser.add_argument(
        "--instruction-header",
        type=Path,
        required=True,
        help="matching Qt qv4instr_moth_p.h",
    )
    parser.add_argument("--list-functions", action="store_true")
    parser.add_argument("--list-qml-enums", action="store_true")
    parser.add_argument("--list-qml-properties", action="store_true")
    parser.add_argument("--list-qml-signals", action="store_true")
    parser.add_argument("--list-qml-bindings", action="store_true")
    parser.add_argument(
        "--find-lookup",
        action="append",
        default=[],
        help="list functions referencing this exact property or method name",
    )
    args = parser.parse_args()

    unit = Qv4Unit(args.unit)
    specification = _instruction_spec(args.instruction_header)
    functions = [unit.function(index) for index in range(unit.function_count)]
    if args.list_functions:
        for function in functions:
            print(
                f"{function['index']:4d} {function['name']!r} "
                f"source={function['line']}:{function['column']} size={function['code_size']}"
            )

    if args.list_qml_enums:
        _render_qml_enums(unit)
    if args.list_qml_properties:
        _render_qml_properties(unit)
    if args.list_qml_signals:
        _render_qml_signals(unit)
    if args.list_qml_bindings:
        _render_qml_bindings(unit)

    _render_lookup_hits(unit, specification, functions, args.find_lookup)

    by_name: dict[str, list[int]] = {}
    for function in functions:
        by_name.setdefault(function["name"], []).append(function["index"])
    for query in args.functions:
        if query.isdecimal():
            selected = [int(query)]
        else:
            selected = by_name.get(query, [])
            if not selected:
                raise ValueError(f"function name not found: {query}")
        for index in selected:
            _render_function(unit, specification, index)

    if not (
        args.list_functions
        or args.list_qml_enums
        or args.list_qml_properties
        or args.list_qml_signals
        or args.list_qml_bindings
        or args.find_lookup
        or args.functions
    ):
        parser.error("select a list mode, --find-lookup, or at least one function")


if __name__ == "__main__":
    main()
