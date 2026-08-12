#!/usr/bin/env python3
"""Hash and classify a read-only mounted firmware filesystem tree.

Write the JSON output to private storage. The report includes filesystem paths,
metadata, hashes, and symlink targets, but never file contents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections import Counter
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _kind(relative: Path, path: Path) -> str:
    name = relative.name
    value = relative.as_posix()
    if value.startswith("usr/local/qt6/plugins/"):
        return "qt_plugin"
    if value.startswith(("lib/firmware/", "usr/lib/firmware/")):
        return "kernel_firmware"
    if name.endswith(".service"):
        return "systemd_unit"
    if name.endswith(".dtb"):
        return "device_tree"
    if name.startswith("zImage"):
        return "linux_kernel"
    if ".so" in name:
        return "shared_library"
    if name.endswith((".qml", ".qmltypes")):
        return "qml_source_or_type_metadata"
    if name.endswith((".json", ".ini", ".conf", ".cfg")):
        return "structured_configuration"
    with path.open("rb") as source:
        prefix = source.read(4)
    if prefix == b"\x7fELF":
        return "elf"
    if prefix.startswith(b"#!"):
        return "script"
    return "regular_file"


def _record(root: Path, path: Path) -> dict[str, Any]:
    metadata = path.lstat()
    relative = path.relative_to(root)
    record: dict[str, Any] = {
        "path": "/" + relative.as_posix(),
        "mode": f"0{stat.S_IMODE(metadata.st_mode):03o}",
        "uid": metadata.st_uid,
        "gid": metadata.st_gid,
    }
    if stat.S_ISREG(metadata.st_mode):
        record.update(
            {
                "type": "file",
                "kind": _kind(relative, path),
                "size": metadata.st_size,
                "sha256": _sha256(path),
            }
        )
    elif stat.S_ISLNK(metadata.st_mode):
        record.update({"type": "symlink", "target": os.readlink(path)})
    elif stat.S_ISDIR(metadata.st_mode):
        record["type"] = "directory"
    else:
        record.update({"type": "special", "rdev": metadata.st_rdev})
    return record


def inventory(root: Path, *, source_image_sha256: str) -> dict[str, Any]:
    root = root.resolve(strict=True)
    records = [_record(root, root)]
    records.extend(_record(root, path) for path in sorted(root.rglob("*")))
    regular_files = [record for record in records if record["type"] == "file"]

    digest = hashlib.sha256()
    for record in records:
        digest.update(json.dumps(record, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")

    return {
        "schema_version": 1,
        "source_image_sha256": source_image_sha256,
        "tree_sha256": digest.hexdigest(),
        "record_count": len(records),
        "regular_file_count": len(regular_files),
        "regular_file_bytes": sum(record["size"] for record in regular_files),
        "kind_counts": dict(sorted(Counter(record["kind"] for record in regular_files).items())),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="read-only mounted filesystem root")
    parser.add_argument("--source-image-sha256", required=True)
    args = parser.parse_args()
    try:
        report = inventory(args.root, source_image_sha256=args.source_image_sha256)
    except OSError as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
