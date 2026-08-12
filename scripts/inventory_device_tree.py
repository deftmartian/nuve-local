#!/usr/bin/env python3
"""Read-only flattened-device-tree inventory for private Nuve artifacts.

The script emits decoded metadata to stdout only.  It does not extract or copy the
input DTB into the repository.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9
HEADER = struct.Struct(">10I")
UINT32 = struct.Struct(">I")


class DeviceTreeError(ValueError):
    """Malformed or unsupported flattened device tree."""


@dataclass(frozen=True, slots=True)
class DeviceTreeProperty:
    """One exact property payload."""

    name: str
    value: bytes


@dataclass(slots=True)
class DeviceTreeNode:
    """One node in structure-block order."""

    path: str
    properties: list[DeviceTreeProperty] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _FdtLayout:
    structure_offset: int
    structure_end: int
    strings_offset: int
    strings_end: int


def _align4(offset: int) -> int:
    return (offset + 3) & ~3


def _read_c_string(data: bytes, offset: int, *, limit: int) -> tuple[str, int]:
    if not 0 <= offset < limit:
        raise DeviceTreeError(f"string offset {offset} is outside its block")
    end = data.find(b"\0", offset, limit)
    if end < 0:
        raise DeviceTreeError("unterminated device-tree string")
    try:
        value = data[offset:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DeviceTreeError("device-tree string is not UTF-8") from exc
    return value, end + 1


def _parse_layout(data: bytes) -> _FdtLayout:
    if len(data) < HEADER.size:
        raise DeviceTreeError("input is shorter than the FDT header")
    (
        magic,
        total_size,
        structure_offset,
        strings_offset,
        _reserved_offset,
        version,
        last_compatible_version,
        _boot_cpu,
        strings_size,
        structure_size,
    ) = HEADER.unpack_from(data)
    if magic != FDT_MAGIC:
        raise DeviceTreeError("input does not have the FDT magic")
    if total_size > len(data) or total_size < HEADER.size:
        raise DeviceTreeError("declared FDT size is outside the input")
    if version < 17 or last_compatible_version > 17:
        raise DeviceTreeError(f"unsupported FDT version {version}/{last_compatible_version}")

    structure_end = structure_offset + structure_size
    strings_end = strings_offset + strings_size
    if not HEADER.size <= structure_offset <= structure_end <= total_size:
        raise DeviceTreeError("structure block is outside the FDT")
    if not HEADER.size <= strings_offset <= strings_end <= total_size:
        raise DeviceTreeError("strings block is outside the FDT")

    return _FdtLayout(structure_offset, structure_end, strings_offset, strings_end)


def _begin_node(
    data: bytes,
    cursor: int,
    layout: _FdtLayout,
    stack: list[DeviceTreeNode],
    nodes: list[DeviceTreeNode],
) -> int:
    name, cursor = _read_c_string(data, cursor, limit=layout.structure_end)
    cursor = _align4(cursor)
    if not stack:
        if name:
            raise DeviceTreeError("root node name is not empty")
        path = "/"
    else:
        path = f"{stack[-1].path.rstrip('/')}/{name}"
    node = DeviceTreeNode(path)
    nodes.append(node)
    stack.append(node)
    return cursor


def _end_node(stack: list[DeviceTreeNode]) -> None:
    if not stack:
        raise DeviceTreeError("unbalanced FDT_END_NODE")
    stack.pop()


def _add_property(
    data: bytes,
    cursor: int,
    layout: _FdtLayout,
    stack: list[DeviceTreeNode],
) -> int:
    if not stack or cursor + 8 > layout.structure_end:
        raise DeviceTreeError("property appears outside a complete node")
    value_length, name_offset = struct.unpack_from(">2I", data, cursor)
    cursor += 8
    value_end = cursor + value_length
    if value_end > layout.structure_end:
        raise DeviceTreeError("property value extends past structure block")
    name, _ = _read_c_string(
        data,
        layout.strings_offset + name_offset,
        limit=layout.strings_end,
    )
    stack[-1].properties.append(DeviceTreeProperty(name=name, value=data[cursor:value_end]))
    return _align4(value_end)


def _parse_structure(data: bytes, layout: _FdtLayout) -> tuple[DeviceTreeNode, ...]:
    cursor = layout.structure_offset
    stack: list[DeviceTreeNode] = []
    nodes: list[DeviceTreeNode] = []
    saw_end = False
    while cursor + UINT32.size <= layout.structure_end:
        token = UINT32.unpack_from(data, cursor)[0]
        cursor += UINT32.size
        if token == FDT_BEGIN_NODE:
            cursor = _begin_node(data, cursor, layout, stack, nodes)
        elif token == FDT_END_NODE:
            _end_node(stack)
        elif token == FDT_PROP:
            cursor = _add_property(data, cursor, layout, stack)
        elif token == FDT_NOP:
            continue
        elif token == FDT_END:
            if stack:
                raise DeviceTreeError("FDT_END appears before all nodes close")
            saw_end = True
            break
        else:
            raise DeviceTreeError(f"unknown structure token {token:#x}")
    if not saw_end:
        raise DeviceTreeError("structure block has no FDT_END")
    return tuple(nodes)


def parse_device_tree(data: bytes) -> tuple[DeviceTreeNode, ...]:
    """Parse the complete FDT structure block without mutating the input."""

    return _parse_structure(data, _parse_layout(data))


def _is_printable_string_list(value: bytes) -> bool:
    if not value or value[-1] != 0:
        return False
    if any(not part for part in value[:-1].split(b"\0")):
        return False
    try:
        decoded = value.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return all(character == "\0" or character.isprintable() for character in decoded)


def decode_property(value: bytes) -> bool | str | list[str] | list[str | int]:
    """Produce a lossless-enough human inventory value for an FDT property."""

    if not value:
        return True
    if _is_printable_string_list(value):
        strings = value[:-1].decode("utf-8").split("\0")
        return strings[0] if len(strings) == 1 else strings
    if len(value) % UINT32.size == 0:
        return [
            f"0x{UINT32.unpack_from(value, offset)[0]:08x}" for offset in range(0, len(value), 4)
        ]
    return f"hex:{value.hex()}"


def inventory_device_tree(
    nodes: tuple[DeviceTreeNode, ...],
    *,
    node_pattern: re.Pattern[str] | None = None,
    property_pattern: re.Pattern[str] | None = None,
) -> list[dict[str, Any]]:
    """Convert selected nodes/properties to stable JSON records."""

    records: list[dict[str, Any]] = []
    for node in nodes:
        node_matches = node_pattern is None or node_pattern.search(node.path)
        properties = {
            prop.name: decode_property(prop.value)
            for prop in node.properties
            if property_pattern is None or property_pattern.search(prop.name)
        }
        property_matches = property_pattern is None or bool(properties)
        if node_matches and property_matches:
            records.append({"path": node.path, "properties": properties})
    return records


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    parser.add_argument("--node-pattern", help="regular expression matched against full node path")
    parser.add_argument(
        "--property-pattern",
        help="regular expression matched against property name",
    )
    return parser.parse_args()


def main() -> int:
    """Run the read-only inventory CLI."""

    args = _parse_args()
    nodes = parse_device_tree(args.dtb.read_bytes())
    node_pattern = re.compile(args.node_pattern, re.IGNORECASE) if args.node_pattern else None
    property_pattern = (
        re.compile(args.property_pattern, re.IGNORECASE) if args.property_pattern else None
    )
    print(
        json.dumps(
            inventory_device_tree(
                nodes,
                node_pattern=node_pattern,
                property_pattern=property_pattern,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
