# Firmware analysis workflow

## Establish identity

```bash
file appStherm
sha256sum appStherm
readelf -Wl appStherm
nm -C appStherm | rg 'TargetClass::targetFunction|staticMetaObject'
strings -a appStherm | rg 'exactField|endpoint|Changed$'
```

Do not mix symbols, addresses, or decompilation from different hashes.

For a broad review, create a repeatable first-party subsystem index before
selecting decompilation targets:

```bash
python .agents/skills/analyze-nuve-firmware/scripts/inventory_symbols.py \
  appStherm --format markdown
```

The inventory is a navigation aid. Symbol presence alone does not establish a
wire contract, state transition, or safety property.

Inventory API literals and their direct owning functions before class-by-class
review. This catches dormant or hazardous families that a traffic capture will
not exercise:

```bash
analyzeHeadless <project-dir> <project-name> \
  -process <program-name> -readOnly -noanalysis \
  -scriptPath .agents/skills/analyze-nuve-firmware/scripts \
  -postScript ListApiEndpointXrefs.java
```

The script examines references to the string base and exact API-pattern starts,
groups the output by literal, and reports strings with no direct Ghidra reference. Treat
the result as an inventory, not proof that an endpoint is reachable or safe. Trace
the owner and completion callback before assigning a contract or disposition.
Cross-check it against `strings -a appStherm | rg 'api/'`: Ghidra may leave a
generic fragment or pooled literal undefined, so neither source alone proves the
inventory is complete.

To decompile every method owned by one or more first-party classes without
pulling in unrelated Qt template instantiations, add the skill's script directory
to Ghidra's script path and run:

```bash
analyzeHeadless <project-dir> <project-name> \
  -process <program-name> -readOnly -noanalysis \
  -scriptPath .agents/skills/analyze-nuve-firmware/scripts \
  -postScript DecompileMatching.java 'Scheme::' 'SchemeDataProvider::'
```

Keep the full output in private scratch space. Promote only concise behavioral
claims, function anchors, and unresolved gaps into the repository.

Reconcile the finished logs against the exact inventory. Establish the address bias
from a known symbol rather than assuming one; this ELF loads 0x10000 above `nm`
addresses in Ghidra:

```bash
python .agents/skills/analyze-nuve-firmware/scripts/audit_decompile_coverage.py \
  inventory.json decompile-*.txt --address-bias 0x10000 --require-complete
```

Nested lambdas may lose their owning class prefix in Ghidra. Decompile any reported
tail addresses explicitly, then rerun the audit. Complete address coverage still
does not mean every branch has been semantically interpreted.

## Preserve photographic hardware evidence

Treat board photographs as exact physical-artifact evidence with a narrower scope
than a schematic or continuity map:

1. Preserve originals outside Git with owner-only permissions and record each
   size/hash in a private manifest. Raw photographs can expose serial, QR, MAC,
   manufacturing, or household identifiers even when the intended subject is a
   chip marking.
2. Promote only sanitized PCB references, component markings, connector labels,
   and bounded conclusions. Cross-check a marking against primary manufacturer
   documentation before assigning capacity, interface, silicon family, or package.
3. Record whether the photographed board is installed or disposable. A photograph
   of installed hardware authorizes no continuity test, debugger attachment,
   storage probe, reset, or power experiment.
4. Treat silk labels as hypotheses. They do not establish voltage, direction,
   continuity, processor ownership, safe pinout, or runtime enablement.
5. Reconcile the photographic identity with the exact DT, filesystem, native
   consumers, and bus aliases. Preserve contradictions rather than selecting the
   source that makes the map look complete.
6. Keep secondary firmware extraction and physical-media fault injection on an
   electrically isolated donor board under separate authorization. Never issue an
   erase/recover command merely to bypass debug readback protection.

## Recover a wire contract

1. Find the request/fetch function and its completion lambda.
2. Trace the JSON object passed after any outer API envelope is unwrapped.
3. For each member, recover the exact nesting, key, conversion (`toString`, `toDouble`, `toInteger`, `toArray`, `toObject`), default, and destination setter.
4. Trace how QML reads the destination. Parser field names may not match display semantics; firmware 1.5.8 forecast cards, for example, render the parser's `min` member first and bold.
5. Compare against a sanitized live request/response or physical screenshot. Treat the binary contract as necessary but not sufficient proof of cache refresh or rendering.

Beware of nearby strings that belong to other endpoints. Key length and surrounding `QJsonObject::contains/value` calls are stronger evidence than string proximity alone.

Treat a screenshot as a page-identity constraint, not just a value check. Locate the
exact page's compiled unit and trace the final display expression before selecting a
producer. Similar names can represent unrelated UI paths: exact `1.5.8` has
`qrURL`, `technicianURL`, and `contactContractorURL`, but the Contact Contractor page
reads only the last of those. When aliases remain ambiguous, enumerate exact-property
lookups across every valid `qv4cdata` unit in the binary and distinguish assignments
from readers. A parser or setter match does not prove that the photographed page
consumes the value.

### Recover cross-field command preconditions

A target setter is not the whole command contract. For a server-applied control:

1. Dump the complete response handler and preserve the order in which sibling
   fields are applied.
2. Trace every early return between the response field and the native setter,
   especially edit locks, schedule state, holds, and local authority checks.
3. Trace the device's own UI action for the same edit. A popup or confirmation
   flow often supplies a companion field that is absent from the obvious setter.
4. Recover the companion enum values and wire serialization independently from
   the exact Qt meta-object and QML compiled unit.
5. Exercise the atomic response with a synthetic consumer test and require the
   device's later full-state projection to confirm every generated field.
6. Identify which later transport actually owns each configured field. Do not use a
   physical-output monitor bit to confirm a saved mode, duty, hold, or preference
   that appears only in a complete state upload.
7. Pass the exact generated command shape through the production persistence and
   restart journal boundary. A runtime-only test can miss a schema mismatch in a
   companion field added after initial validation.
8. Do not label a rejected-type or non-array branch a no-op after checking only the
   target setter. Trace every flag assignment, refresh request, signal, and later
   projection before and after its return; exact `1.5.8` schedule preservation keeps
   local arrays but still marks activities for refetch.

For sensor fields, trace both sides of the application boundary: exact board-packet
integer width and scaling into the device map, then every category conversion,
change filter, JSON/protobuf publisher, and zero/missing rule. Official sensor-vendor
documentation can establish algorithm output units, but it cannot prove which mode,
library version, or calibration the separate board runs. A sanitized local-history
population can corroborate range/cadence/sentinels; it cannot create a transport that
the exact application does not have.

For display preferences, recover the saved model, renderer, edit-page Save handler,
native consumer, night/sleep overrides, and restoration path separately. A displayed
value may be capped or floored without changing the saved value. Identify the later
full-state owner before choosing confirmation; a partial preference upload is not
automatically authoritative.

This method distinguishes a transported-but-ignored command from a timing or
confirmation bug. Do not brute-force alternate values around a proven state gate.

## Ghidra headless analysis

Maintain one project per exact binary hash. Import/analyze once, then run targeted decompiler scripts against demangled function names or addresses. Keep output in scratch space and promote only concise evidence into the repository.

Useful targets include:

- native fetch completion lambdas for endpoint schemas;
- every owner reported by `ListApiEndpointXrefs.java`, including unsupported
  installation, recovery, performance-test, and external-service paths;
- device-controller setters for state transitions;
- QML-cache generated functions for display ordering;
- `AppSpecCPP::staticMetaObject` for enum names and values;
- data-provider and scheme functions for effective versus raw values.

Cross-check decompiler types against call sites; recovered ARM types and class offsets are often approximate.

### Repair a broken imported prototype

An imported zero-length structure or wrong calling convention can make one function
fail with `Cannot properly adjust input varnodes` even when its disassembly is valid.
Do not mutate the canonical evidence project to make the decompiler happy. Copy the
project, establish the exact ABI from the function and its callers, and repair only
that disposable copy:

```bash
analyzeHeadless <scratch-project-dir> <scratch-project-name> \
  -process <program-name> -noanalysis \
  -scriptPath .agents/skills/analyze-nuve-firmware/scripts \
  -postScript SetFunctionCallingConvention.java \
    'DeviceIOController::processNRFResponse' __thiscall \
  -postScript RepairStructureLength.java \
    /Demangler/STHERM/SIOPacket 0x108
```

The size in this example is not a guess: exact `1.5.8` code copies and advances
`SIOPacket` objects by `0x108`, and the repaired ARM parameter placement agrees with
the caller. Require at least two such anchors before changing a type. Re-run the
decompiler read-only after the repair, retain the original disassembly, and record
the repair as analysis metadata rather than firmware truth.

## Qt 6 meta-object enums

Locate the static meta-object address:

```bash
nm -C appStherm | rg 'AppSpecCPP::staticMetaObject'
objdump -s --start-address=<address> --stop-address=<address+32> appStherm
```

Then extract an enum deterministically:

```bash
python .agents/skills/analyze-nuve-firmware/scripts/extract_qt6_meta_enum.py \
  appStherm --meta-object-address <address> --enum FanMode
```

The helper supports little-endian ELF32/ELF64 files whose Qt 6 static meta-object retains direct in-file string-table and metadata pointers. Fail closed if relocations leave those pointers unresolved.

## Qt 6 QML compiled-data units

Ghidra can decompile the AOT lambdas but generally exposes numeric lookup indices
instead of the QML property and method names. The embedded unit retains both its
QV4 bytecode and lookup table. Locate the `qmlData` symbol, map its virtual address
to a file offset, and inspect the unit in place with the matching Qt instruction
header:

```bash
python .agents/skills/analyze-nuve-firmware/scripts/dump_qt6_qv4.py \
  appStherm@<qml-data-file-offset> \
  --instruction-header <qt-source>/src/qml/compiler/qv4instr_moth_p.h \
  --find-lookup displayCurrentTemp \
  --find-lookup setCurrentTemperature
```

Then dump the bounded function indices reported by the lookup search:

```bash
python .agents/skills/analyze-nuve-firmware/scripts/dump_qt6_qv4.py \
  appStherm@<qml-data-file-offset> \
  --instruction-header <qt-source>/src/qml/compiler/qv4instr_moth_p.h \
  <function-index> [<function-index> ...]
```

`LoadRuntimeString` and `MoveRegExp` operands are resolved through the exact unit
string and regular-expression tables. Qt 6.4 `TranslationData` records are decoded
as source string, comment, and plural number; keep their values private and promote
only hashes, equality results, or concise behavioral conclusions.
Declarative QML enums, property and signal declarations, and literal initializers live in the
`QmlUnit` object records rather than the native Qt meta-object; list them separately
when QML-owned constants, defaults, or timer intervals affect a contract:

```bash
python .agents/skills/analyze-nuve-firmware/scripts/dump_qt6_qv4.py \
  appStherm@<qml-data-file-offset> \
  --instruction-header <qt-source>/src/qml/compiler/qv4instr_moth_p.h \
  --list-qml-enums --list-qml-properties --list-qml-signals --list-qml-bindings
```

Require the unit's `qv4cdata` magic and declared size to fit inside the file.
Match the Qt source version recorded in the unit/firmware; opcode order is not a
cross-version contract. Use the bytecode to prove wiring and ordering, then
cross-check native callees and a physical or sanitized live observation.

Before targeted interpretation, inventory and decode every unit/function against
the exact matching Qt instruction header. Keep the generated JSON private:

```bash
python .agents/skills/analyze-nuve-firmware/scripts/inventory_qt6_qv4.py \
  appStherm \
  --instruction-header <qt-6.4.0-source>/src/qml/compiler/qv4instr_moth_p.h \
  > qv4-inventory.private.json
```

The command fails on an invalid unit, string, translation, function record, or
opcode. Its schema-4 output hashes literal and translation pools and binding values,
and records sanitized named-operation summaries, without retaining prose or
instruction bodies. Success establishes structural decode coverage, not semantic
interpretation; disposition each UI action and externally relevant function
separately.

## Evidence strength

Prefer, in order:

1. Exact-hash binary plus successful live/physical confirmation.
2. Exact-hash binary contract plus independent synthetic test.
3. Exact-hash strings/symbols with bounded decompilation.
4. Nearby-version behavior, clearly labeled as provisional.

Never represent an untested HVAC command, fan setting, app restart, or firmware write as live-verified.
