#!/usr/bin/env python3
"""Build a deterministic private inventory of the Nuve evidence corpus.

The output contains private absolute paths and belongs outside Git. It records
metadata and hashes only; it never reads structured device configuration values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any

PRIVATE_REPORT_NAME = "ARTIFACT-INVENTORY.private.json"

GROUPS: dict[str, dict[str, str]] = {
    "authoritative_live_image": {
        "provenance": "direct 2026-08-09 eMMC read or exact lossless derivative",
        "firmware_association": "live snapshot containing appStherm 1.5.7.4",
        "completeness": "complete or exact partition extraction as named",
        "reproduction": "zstd, fdisk, dd, sha256sum, filesystem checkers",
        "authenticity_uncertainty": "device-origin is direct; snapshot is crash-consistent",
        "privacy": "device-specific private recovery material",
    },
    "live_configuration": {
        "provenance": "read-only copies from the live 2026-08-09 filesystem",
        "firmware_association": "live appStherm 1.5.7.4 state",
        "completeness": "targeted copy, not a complete filesystem",
        "reproduction": "read-only filesystem copy and sha256sum",
        "authenticity_uncertainty": "direct copy; individual scope is path-specific",
        "privacy": "contains credentials or device and network identifiers",
    },
    "offline_live_derivative": {
        "provenance": "read-only extraction or analysis of the authoritative live image",
        "firmware_association": "live snapshot containing appStherm 1.5.7.4",
        "completeness": "derived artifact; authoritative source image retained",
        "reproduction": "fdisk, dd, debugfs, fsck tools, gzip, sha256sum",
        "authenticity_uncertainty": "derivation is reproducible from the source image",
        "privacy": "may contain device-specific data",
    },
    "reconstructed_overlay": {
        "provenance": "reconstructed from a repair-simulation view plus exact saved config",
        "firmware_association": "appStherm 1.5.7.4 transient diagnostic candidate",
        "completeness": "reconstructed and explicitly not a persistent restore source",
        "reproduction": "debugfs, tar, sha256sum, byte comparison",
        "authenticity_uncertainty": "non-INI files match; endpoint variant is intentional",
        "privacy": "contains device configuration",
    },
    "recovered_deleted_data": {
        "provenance": "forensic recovery from deleted inodes in the live p2 image",
        "firmware_association": "live appStherm 1.5.7.4 state",
        "completeness": "recovered or reconstructed; not a filesystem restore source",
        "reproduction": "debugfs and independent byte/hash comparison",
        "authenticity_uncertainty": "inode recovery is tied to the retained source image",
        "privacy": "contains device configuration",
    },
    "vendor_recovery_1_5_8": {
        "provenance": "retained vendor recovery payload",
        "firmware_association": "exact recovery 1.5.8",
        "completeness": "complete boot/root recovery pair plus vendor manifest metadata",
        "reproduction": "gzip, md5sum, sha256sum, debugfs, FAT tools",
        "authenticity_uncertainty": "matches live p4 and published size/MD5; no signature proven",
        "privacy": "proprietary firmware; no device-specific live state expected",
    },
    "private_validation_evidence": {
        "provenance": "bounded local integration or endpoint validation capture",
        "firmware_association": "validation evidence; use its ledger for the firmware build",
        "completeness": "test-scoped capture, not a firmware or recovery artifact",
        "reproduction": "test-specific redacted capture workflow and sha256sum",
        "authenticity_uncertainty": "scope and timing are test-specific",
        "privacy": "may contain household, device, or Home Assistant state",
    },
    "corpus_metadata": {
        "provenance": "operator-authored corpus note or prior checksum manifest",
        "firmware_association": "cross-version corpus metadata",
        "completeness": "metadata only",
        "reproduction": "text inspection and sha256sum",
        "authenticity_uncertainty": "claims require the referenced artifact checks",
        "privacy": "private paths and recovery context",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _group_for(relative: Path) -> str:
    top = relative.parts[0]
    if len(relative.parts) == 1:
        if top in {"BACKUP-NOTES.md", "SHA256SUMS"}:
            return "corpus_metadata"
        return "authoritative_live_image"
    return {
        "live-config": "live_configuration",
        "offline-analysis": "offline_live_derivative",
        "overlay-source": "reconstructed_overlay",
        "recovered-deleted-inodes": "recovered_deleted_data",
        "recovery-files": "vendor_recovery_1_5_8",
    }.get(top, "private_validation_evidence")


def _artifact(root: Path, path: Path) -> dict[str, Any]:
    relative = path.relative_to(root)
    details = GROUPS[_group_for(relative)]
    return {
        "absolute_path": str(path),
        "relative_path": relative.as_posix(),
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        **details,
    }


def inventory(root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    paths = []
    for candidate in root.rglob("*"):
        if candidate.name == PRIVATE_REPORT_NAME:
            continue
        if stat.S_ISREG(candidate.lstat().st_mode):
            paths.append(candidate)
    artifacts = [_artifact(root, path) for path in sorted(paths)]

    corpus_digest = hashlib.sha256()
    for artifact in artifacts:
        corpus_digest.update(artifact["relative_path"].encode())
        corpus_digest.update(b"\0")
        corpus_digest.update(str(artifact["size"]).encode())
        corpus_digest.update(b"\0")
        corpus_digest.update(artifact["sha256"].encode())
        corpus_digest.update(b"\n")

    return {
        "schema_version": 1,
        "source_root": str(root),
        "artifact_count": len(artifacts),
        "total_size": sum(artifact["size"] for artifact in artifacts),
        "corpus_sha256": corpus_digest.hexdigest(),
        "excluded_report_name": PRIVATE_REPORT_NAME,
        "artifacts": artifacts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    try:
        report = inventory(args.root)
    except OSError as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
