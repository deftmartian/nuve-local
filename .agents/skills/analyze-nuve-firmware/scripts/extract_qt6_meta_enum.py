#!/usr/bin/env python3
"""Extract enum names and values from a Qt 6 static meta-object in an ELF file."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


class ContractError(ValueError):
    """Raised when the binary does not match the supported contract."""


def _integer(text: str) -> int:
    try:
        return int(text, 0)
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"invalid integer: {text}") from err


def _load_segments(blob: bytes) -> tuple[str, list[tuple[int, int, int]]]:
    if blob[:4] != b"\x7fELF" or blob[5] != 1:
        raise ContractError("only little-endian ELF files are supported")
    elf_class = blob[4]
    if elf_class == 1:
        header = struct.unpack_from("<16sHHIIIIIHHHHHH", blob)
        program_offset, entry_size, entry_count = header[5], header[9], header[10]
        program_format = "<IIIIIIII"
    elif elf_class == 2:
        header = struct.unpack_from("<16sHHIQQQIHHHHHH", blob)
        program_offset, entry_size, entry_count = header[5], header[9], header[10]
        program_format = "<IIQQQQQQ"
    else:
        raise ContractError("unsupported ELF class")

    segments: list[tuple[int, int, int]] = []
    for index in range(entry_count):
        values = struct.unpack_from(program_format, blob, program_offset + index * entry_size)
        if values[0] != 1:  # PT_LOAD
            continue
        if elf_class == 1:
            file_offset, virtual_address, file_size = values[1], values[2], values[4]
        else:
            file_offset, virtual_address, file_size = values[2], values[3], values[5]
        segments.append((virtual_address, file_offset, file_size))
    if not segments:
        raise ContractError("ELF has no loadable segments")
    return "<", segments


def _file_offset(address: int, segments: list[tuple[int, int, int]], size: int = 1) -> int:
    for virtual_address, file_offset, file_size in segments:
        relative = address - virtual_address
        if relative >= 0 and relative + size <= file_size:
            return file_offset + relative
    raise ContractError(f"address {address:#x} is not backed by file data")


def extract_enums(
    blob: bytes, *, meta_object_address: int, requested_enum: str | None
) -> dict[str, dict[str, int]]:
    endian, segments = _load_segments(blob)

    def u32(address: int) -> int:
        return struct.unpack_from(f"{endian}I", blob, _file_offset(address, segments, 4))[0]

    meta_object = _file_offset(meta_object_address, segments, 12)
    string_address, metadata_address = struct.unpack_from(f"{endian}II", blob, meta_object + 4)
    if string_address == 0 or metadata_address == 0:
        raise ContractError("static meta-object pointers are unresolved")

    def qstring(index: int) -> str:
        entry = string_address + index * 8
        relative, length = u32(entry), u32(entry + 4)
        offset = _file_offset(string_address + relative, segments, length)
        return blob[offset : offset + length].decode("utf-8")

    revision = u32(metadata_address)
    if revision != 10:
        raise ContractError(f"unsupported Qt meta-object revision: {revision}")
    enum_count = u32(metadata_address + 8 * 4)
    enum_table = u32(metadata_address + 9 * 4)
    result: dict[str, dict[str, int]] = {}
    for enum_index in range(enum_count):
        entry = metadata_address + (enum_table + enum_index * 5) * 4
        name_index = u32(entry)
        item_count = u32(entry + 3 * 4)
        item_table = u32(entry + 4 * 4)
        enum_name = qstring(name_index)
        if requested_enum is not None and enum_name != requested_enum:
            continue
        values: dict[str, int] = {}
        for item_index in range(item_count):
            item = metadata_address + (item_table + item_index * 2) * 4
            key = qstring(u32(item))
            value = struct.unpack("<i", struct.pack("<I", u32(item + 4)))[0]
            values[key] = value
        result[enum_name] = values
    if requested_enum is not None and requested_enum not in result:
        raise ContractError(f"enum not found: {requested_enum}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--meta-object-address", required=True, type=_integer)
    parser.add_argument("--enum")
    args = parser.parse_args()
    try:
        result = extract_enums(
            args.binary.read_bytes(),
            meta_object_address=args.meta_object_address,
            requested_enum=args.enum,
        )
    except (ContractError, OSError, UnicodeDecodeError, struct.error) as err:
        parser.error(str(err))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
