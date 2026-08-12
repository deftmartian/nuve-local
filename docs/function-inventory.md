# Firmware 1.5.8 native and QV4 function inventory

This inventory covers `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
It measures structural coverage; decompiling a function does not fully explain it.

## Native inventory

`nm -C --defined-only` returns 48,220 symbol rows. The selected first-party class
selection contains 2,172 rows, representing 2,046 unique address/name identities
after constructor, destructor, and other linker aliases are deduplicated. Of these,
1,955 unique addresses are executable function symbols.

| Subsystem | Selected symbol rows | Unique function addresses |
| --- | ---: | ---: |
| Startup and state | 567 | 511 |
| Control and HVAC | 412 | 384 |
| Hardware and sensors | 181 | 161 |
| API and synchronization | 324 | 291 |
| Network | 270 | 235 |
| Weather and UI services | 135 | 114 |
| Update and recovery | 243 | 223 |
| Firmware contract | 40 | 36 |
| **Total** | **2,172** | **1,955** |

Class ownership is disjoint across the subsystem rows. The function-address total
deduplicates constructor, destructor, and other linker aliases across the complete
selection. Third-party Qt, C++ runtime, protobuf runtime, Abseil, and generic
library symbols are excluded from this first-party review set.

The retained Ghidra project decompiles all 1,955 addresses. The original
`DeviceIOController::processNRFResponse` failure was caused by a one-byte imported
`STHERM::SIOPacket` placeholder. Copy sizes and ARM argument placement show that the
structure is `0x108` bytes. Correcting the type in a disposable copy allowed the
function to decompile without changing the retained project.

This proves address coverage, not that every branch has a final disposition.
Externally reachable, state-changing, persistent, hardware-facing, timer, callback,
and UI-entry functions still require an owner, contract, consequence, evidence
grade, and decision about whether Nuve Local should expose it.

## QV4 inventory

The binary contains:

- 308 embedded `qmlData` compiled units;
- 8,988 QV4 function records;
- 102,236 decoded QV4 instructions;
- 4,920 declarative objects, 25 enums, 2,349 properties, 108 signals, and 16,875
  binding records with private values replaced by hashes;
- 1,701 direct native AOT function symbols; and
- 4,095 QML-cache-related symbol rows when guards and generated support symbols are
  included.

Every unit, function record, lookup, string reference, and instruction stream
structurally decodes with the matching Qt Declarative 6.4.0 instruction header.
Declarative QML enums are decoded separately from the Qt 6.4 `QmlUnit` object
records. Runtime string operands are resolved from the unit string table, and
16-byte Qt 6.4 translation records resolve source/comment/plural semantics.
Schema 4 retains private literal/translation values only as deterministic hashes,
avoiding ambiguous numeric IDs without copying proprietary prose into the report.

The 8,988 QV4 records and 1,701 AOT symbols are different views and must not be
added together or treated as equivalent coverage. The former is the complete
compiled JavaScript/QML function table; the latter is the subset for which the
build retained direct native AOT symbols.

## Reproduction

Generate the native index:

```bash
uv run --frozen python \
  .agents/skills/analyze-nuve-firmware/scripts/inventory_symbols.py \
  /private/path/appStherm-1.5.8 --format json
```

Generate the private full QV4 index:

```bash
uv run --frozen python \
  .agents/skills/analyze-nuve-firmware/scripts/inventory_qt6_qv4.py \
  /private/path/appStherm-1.5.8 \
  --instruction-header /private/path/qt-6.4.0-qv4instr_moth_p.h
```

List declarative enums, properties, signals, or literal bindings, or decode selected
functions:

```bash
uv run --frozen python \
  .agents/skills/analyze-nuve-firmware/scripts/dump_qt6_qv4.py \
  /private/path/appStherm-1.5.8@<qml-data-file-offset> \
  --instruction-header /private/path/qt-6.4.0-qv4instr_moth_p.h \
  --list-qml-enums --list-qml-properties --list-qml-signals --list-qml-bindings
```

Generated symbol, decompile, and full QV4 reports remain private. Repository
documentation records only counts, hashes, call anchors, and contracts that do not
contain private values. The separately generated
[UI action register](ui-action-register.md)
maps 947 bound `onX` expressions and 181 declared callbacks to 198 action-bearing
units, follows nested-closure edges, identifies nine effect-free stubs, and excludes
script bodies and embedded prose.

## Current semantic boundary

Together, the native and QV4 inventories account for the application code selected
for review. The operation summaries and UI register cover all 1,128 recognized
handlers. High-risk behavior is assessed from its protocol and state machine, not
from the name shown in the UI. [Open questions](remaining-unknowns.md) tracks the
remaining gaps, especially physical
schedule durability/vendor edges, lock/PIN server behavior, unavailable
remote-sensor and relay-board firmware, installer/vendor service behavior,
performance-test vendor policy and physical-controller behavior, update
interruption, broad cross-version native parity, and unavailable secondary firmware.
The application-side performance-test workflow is covered separately in
[performance-test.md](performance-test.md).
