---
name: analyze-nuve-firmware
description: Recover and verify behavior, wire schemas, enum values, sensor scaling, QML display semantics, physical-component identities, and device-side state transitions from exact Nuve Samo firmware and hardware evidence. Use when implementing or auditing Nuve Local endpoints, settings fields, fan or HVAC controls, temperature/IAQ/pressure behavior, backlight or night-mode rendering, weather, contractor branding, or any claim that requires binary, symbol, QML-cache, Ghidra, device-tree, or board-photograph evidence.
---

# Analyze Nuve Firmware

1. Capture the exact live executable read-only and record its SHA-256. Keep version and hash attached to every conclusion.
2. Start with cheap evidence: `file`, `sha256sum`, `strings`, `nm -C`, `readelf`, and `objdump`. Search exact field names, setters, signals, endpoint paths, and QML cache symbols.
3. Use symbol names and cross-references to select bounded functions. Decompile those functions from the exact binary with a persistent Ghidra project; do not infer the current contract from a nearby firmware build. If bad imported types prevent decompilation, repair only a disposable project copy and prove the correction from call-site/disassembly evidence first.
4. Recover both producer and consumer behavior. For JSON, identify container shape, exact keys, types, defaults, setters, and missing-field behavior. For UI behavior, begin at the exact photographed page or route and trace its final QML input back to the producer. Never equate similarly named properties without proving the binding.
5. Separate evidence from inference. Record addresses, symbols, hashes, and observed live requests in `docs/firmware-evidence.md`; keep private values out of the repository.
6. Encode each recovered contract in an independent test with synthetic data. Do not make a test merely restate the implementation.
7. For live validation, use `$operate-nuve-live` and honor its HVAC and privacy boundaries.
8. Preserve raw board photographs outside Git with hashes and owner-only permissions. Publish only sanitized markings; never infer pad ownership from silk, and never probe installed hardware without a separate explicit authorization.

Read [references/workflow.md](references/workflow.md) for exact commands, evidence hierarchy, and common traps. Use `scripts/inventory_symbols.py` to build a repeatable subsystem index before broad decompilation and `scripts/audit_decompile_coverage.py` to reconcile that inventory with the finished logs. Use `scripts/extract_qt6_meta_enum.py` when Qt 6 meta-object enum names and values are present but not printed by ordinary strings output. Use `scripts/inventory_qt6_qv4.py` to prove every embedded Qt 6.4 unit and function decodes with the exact matching instruction header, then use `scripts/dump_qt6_qv4.py` for targeted property and method wiring. Its `--list-qml-enums`, `--list-qml-properties`, `--list-qml-signals`, and `--list-qml-bindings` modes recover declarative metadata and literal initializers that are absent from native `staticMetaObject` data, and its bytecode output resolves runtime strings and regular-expression literals against the exact unit tables.
The QV4 tools also decode Qt 6.4 translation records; generated inventories keep
literal and translation semantics as hashes rather than embedded prose.
Use `scripts/ListApiEndpointXrefs.java` to inventory API literals and their direct
function owners before assigning an implemented, unsupported, or intentionally
unreachable disposition.
