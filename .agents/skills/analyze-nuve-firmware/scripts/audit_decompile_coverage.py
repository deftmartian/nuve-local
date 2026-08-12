#!/usr/bin/env python3
"""Compare a Nuve symbol inventory with Ghidra decompile logs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_HEADER = re.compile(r"===== .*? @ (?:0x)?([0-9a-fA-F]+) =====")
_FAILED = "DECOMPILE FAILED:"
_FUNCTION_TYPES = frozenset("TtWw")


def _parse_int(value: str) -> int:
    return int(value, 0)


def _covered_addresses(paths: list[Path], *, address_bias: int) -> set[int]:
    """Return addresses with at least one completed decompile block.

    DecompileMatching prints its function header before attempting the decompile.
    Counting headers alone therefore treats a failed attempt as coverage. A later
    successful attempt for the same address is sufficient, which supports the
    documented disposable-project type-repair workflow.
    """

    covered: set[int] = set()
    for path in paths:
        current: int | None = None
        failed = False
        for line in path.read_text(errors="replace").splitlines():
            header = _HEADER.search(line)
            if header:
                if current is not None and not failed:
                    covered.add(current - address_bias)
                current = int(header.group(1), 16)
                failed = False
            elif current is not None and _FAILED in line:
                failed = True
        if current is not None and not failed:
            covered.add(current - address_bias)
    return covered


def _expected(details: dict[str, Any]) -> dict[int, set[str]]:
    expected: dict[int, set[str]] = {}
    for items in details["classes"].values():
        for item in items:
            if item["type"] not in _FUNCTION_TYPES:
                continue
            expected.setdefault(int(item["address"], 16), set()).add(item["symbol"])
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("logs", type=Path, nargs="+")
    parser.add_argument(
        "--address-bias",
        type=_parse_int,
        required=True,
        help="Ghidra address minus ELF symbol address, for example 0x10000",
    )
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()

    report = json.loads(args.inventory.read_text())
    covered = _covered_addresses(args.logs, address_bias=args.address_bias)
    all_expected: dict[int, set[str]] = {}
    for subsystem, details in report["subsystems"].items():
        expected = _expected(details)
        all_expected.update(expected)
        hits = expected.keys() & covered
        print(f"{subsystem}: {len(hits)}/{len(expected)}")

    missing = all_expected.keys() - covered
    print(f"total: {len(all_expected) - len(missing)}/{len(all_expected)}")
    for address in sorted(missing):
        names = " | ".join(sorted(all_expected[address]))
        print(f"missing 0x{address:08x} {names}")
    return 1 if args.require_complete and missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
