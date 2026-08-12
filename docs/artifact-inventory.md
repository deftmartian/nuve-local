# Firmware 1.5.8 artifact inventory

This is an index of the private research archive. Firmware, device configuration,
credentials, captures, and private paths stay outside Git; checked-in tools emit only
metadata and hashes.

## Primary application

The primary application is recovery `1.5.8` `appStherm`, 32,219,628 bytes, SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
Addresses and behavior claims apply only to that hash.

The private 2026-08-09 corpus inventory covers 147 files and 21,731,177,276 bytes.
Its deterministic corpus digest is
`e2d4c7af1dc3db7d980e7611483f3bf86267ae689fea7ab7bbc2361849c54db1`;
the JSON report itself has SHA-256
`1ef2e3c5bdc3bb93640f3dc0b8a58d7c90650197d29899b4ca3c888c570a7037`.
It records, per file, exact private path, size, SHA-256, provenance group, build
association, complete/reconstructed status, reproduction tooling, privacy class,
and authenticity uncertainty.

| Private evidence group | Files | Bytes | Role |
| --- | ---: | ---: | --- |
| Complete live eMMC, partitions, and exact derivatives | 42 | 21,292,172,687 | Crash-consistent 1.5.7.4-era device snapshot and full recovery source |
| Targeted live configuration and deleted-inode recovery | 23 | 12,494,808 | Device-specific configuration and forensic evidence |
| Reconstructed transient overlay candidates | 25 | 166,874,671 | Diagnostic-only 1.5.7.4 view; never a persistent restore source |
| Exact vendor recovery 1.5.8 pair and manifest | 3 | 258,372,457 | Clean canonical boot/root source |
| Private validation captures | 52 | 1,249,040 | Test-scoped HA/device evidence; build association remains ledger-specific |
| Corpus metadata | 2 | 13,613 | Backup notes and prior checksum manifest |

## Complete recovery-root index

The clean decompressed recovery root is ext4, 1,019,253,760 bytes, SHA-256
`7c5a22b98369a73eb8389b773c6fd84886e1e08172ed6bb6f7489f0a6b245dbf`,
and passes non-writing `e2fsck`. A private filesystem report inventories 30,764
paths, including 27,274 regular files totaling 641,372,391 bytes. Its tree digest is
`c441332b50acc0c89ffcca3466727da969b5ba7eb5cc9857363b70fa7cc60494`.

The report individually hashes 743 ELF files, 855 shared libraries, 55 Qt plugins,
784 QML source/type-metadata files, 127 systemd units, 182 scripts, 17 kernel
firmware files, the kernel, and the device tree. It also records modes, ownership,
symlinks, and structured-configuration paths. Embedded QV4 units and protobuf
descriptors inside `appStherm` are indexed separately by the application-analysis
workflow rather than represented as standalone filesystem files. The private QV4
report structurally decodes all 308 units, 8,988 function records, and 102,236
instructions against the matching Qt 6.4.0 instruction header; its unit-corpus digest is
`b0f2bbb2bad5c537ce4addf739c9bebed67ae974b3a09fdbbe864ed7b66be788`.

A separate private target-runtime report records networkless ARM execution of the
application and Qt libraries with the source image read-only and all
writable identity/state synthetic. It covers locale/DST/timezone changes, duplicate
JSON members, wrong-typed root fields, registered schedule identifiers, populated
V1/V2/hold restoration, and the no-enabled-activity hold clear. Raw logs and
synthetic writable images are scratch rather than corpus artifacts.

Six user-supplied non-contact photographs of the installed mainboard are preserved
separately from the 2026-08-09 147-file corpus, so that earlier corpus count and
digest remain stable. The mode-600 originals total 10,403,630 bytes. A private
2,705-byte manifest with SHA-256
`ec188849759e9319116b30131dba24e15fe154c82e4c27f81ccf4f7f937e9f95`
records each image's size/hash, installed-unit provenance, visible component
markings, test-point labels, and non-contact boundary. The images may contain
device-identifying labels and must not enter Git or diagnostics.

## Core exact artifacts

| Artifact | Size | SHA-256 | Provenance and status |
| --- | ---: | --- | --- |
| Recovery `root.gz` | 247,571,818 | `393f72558858b0ebf12988139b06db74d49440bea2acc34794e5c698d016d621` | Complete vendor recovery 1.5.8 root; matches live p4 |
| Decompressed root | 1,019,253,760 | `7c5a22b98369a73eb8389b773c6fd84886e1e08172ed6bb6f7489f0a6b245dbf` | Exact derived ext4 image |
| Recovery `boot.gz` | 10,800,310 | `33baf13d32e7220d5bf6e0934bd895f1bff1c4d7ea613e7a367ba7a7bad76797` | Complete vendor recovery 1.5.8 boot; matches live p4 |
| Decompressed boot | 27,262,976 | `5db90a7713e88d0cc22eb6993606a5e05ce682f4cd385615ab9845d8670d98e9` | Exact FAT16 image |
| `appStherm` | 32,219,628 | `2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e` | Complete canonical non-stripped ARM ELF from recovery root |
| `zImage` | 5,840,336 | `d75c4b75d298332e713aae288352fca10f6543b066b26fc5709227e542744799` | Identical in recovery boot, recovery root, and captured live boot |
| `imx6sl-evk.dtb` | 31,566 | `0524701e0feac4e7f3913555134b80277ffd802d3be60aaa15e6a3c2828496e7` | Identical in recovery boot, recovery root, and captured live boot |
| U-Boot ROM-loaded region | 528,384 | `af98c7a3241d7b0cf6222f8730bef9b3f38c702e769774bfc79d072269324af1` | Exact IVT-declared region from live eMMC; includes MBR |
| Default U-Boot environment | 4,138 | `f1c032c6a96c77812011c4c8823cf8611bedccaf1fb1a1f0f1799d81668116ec` | Byte-identical in live copy and recovery root |
| `appStherm.service` | 271 | `93eeaa2f25b54f6fbcf3189d2790688aa287b914477a8f54f3455992bb1515c5` | Exact recovery-root service unit |
| Installed-board photograph manifest | 2,705 | `ec188849759e9319116b30131dba24e15fe154c82e4c27f81ccf4f7f937e9f95` | Private additive manifest for six exact installed-mainboard photographs; originals remain outside Git |

The complete eMMC user-area image, boot regions, partitions, repair simulation, live
configuration, and derived files remain in private storage. The authoritative backup
notes distinguish direct reads from reconstructions and forbid using the repair
simulation or overlays as restore sources.

## Nearby-version and mobile evidence

Earlier work recorded hashes for update `1.5.7.4`, update `1.6.1.1`, the corresponding
application binaries, and three Android APK splits. Their files are not present in
the currently audited corpus or current scratch storage. They are therefore
**hash-only historical evidence**, not presently reproducible artifacts. No
compatibility or current contract may depend on them until exact files are
reacquired, rehashed, and entered in the private inventory.

The live snapshot does preserve exact `appStherm` 1.5.7.4 with SHA-256
`d07abe078039843c7627f80bbc634808aa7679e35a13f06974c7ec6fe8007cc4`.
It is a separate build and may be used only for explicitly labeled difference work.

## Reproduction

Run `scripts/inventory_firmware_artifacts.py` against the external corpus to rebuild
the 147-file ledger. Decompress the verified root, mount it read-only through
`fuse2fs` with `ro,norecovery,fakeroot`, and run
`scripts/inventory_filesystem_tree.py` to rebuild the filesystem ledger. Neither
script emits file contents.

Do not place the private corpus inside the Git worktree. A Git ignore rule is not a
confidentiality, backup, or deletion boundary.
