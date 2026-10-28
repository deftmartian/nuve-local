# Firmware version differences

A version number alone does not establish compatibility. The comparisons below are
tied to SHA-256-identified files. Addresses, routes, QV4 results, and behavior should
not be carried from one build to another without comparing the files.

## Current artifact status

| Version/artifact | Size | Identity | Current evidence status |
| --- | ---: | --- | --- |
| Live-snapshot `appStherm` 1.5.7.4 | 32,219,360 | Hash kept in private research notes | Exact application bytes are present in reconstructed overlay candidates tied to a retained live snapshot; not a clean update container or preferred restore source |
| Recovery `appStherm` 1.5.8 | 32,219,628 | SHA-256 `2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e` | Complete canonical exact application from the clean verified recovery root |
| Historical update 1.5.7.4 | Unknown | Hash-only record in private research notes | Container absent |
| Historical update 1.6.1.1 | Unknown | Hash-only record in private research notes | Container absent |
| Historical `appStherm` 1.6.1.1 | Unknown | Hash-only record in private research notes | Application absent and current behavior is not reproducible |

The three 1.5.7.4 candidate files have the same size and hash. Their reconstruction
status limits filesystem/restore provenance, but it does not make their application
bytes approximate. They are suitable for explicitly labeled binary-difference
analysis. The clean 1.5.8 recovery application remains the only canonical target
for the comprehensive behavior model.

The missing 1.6.1.1 file is a hard boundary. Earlier work recorded targeted findings
and a pre-release build still contained an exact-version allowlist entry, but this
research pass cannot rerun its symbol, native, QV4, route, persistence, hardware, or
security audit. It must not be used to infer compatibility with 1.5.8 or with a
future build.

## ELF identity and address drift

| Property | 1.5.7.4 | 1.5.8 |
| --- | --- | --- |
| GNU build ID | Recorded privately | Recorded privately |
| ELF type/architecture | ELF32 little-endian ARM PIE, EABI5 hard-float | Same format |
| Entry point | `0x443ed` | `0x44409` |
| Defined symbol rows | 48,207 | 48,220 |
| Generated QML-cache symbols | 4,094 | 4,095 |
| Selected first-party address/name rows | 2,046 | 2,046 |
| Selected first-party name/type identities | 1,990 | 1,990 |
| Selected first-party executable function addresses | 1,955 | 1,955 |

The selected first-party name/type sets are identical: no selected name/type was
added or removed. That is structural parity, not function-body parity. Only 59 of
the 2,046 selected address/name rows occur at the same address in both binaries.
Every Ghidra address in the 1.5.8 documentation is therefore hash-specific; even a
same-named 1.5.7.4 function must be resolved in its own project.

The raw size delta is only 268 bytes, but that number is not a semantic measure.
Changed QV4 unit sizes, layout, link addresses, notes, and section placement can
offset one another.

## Direct API route literals

All 38 exact literals in the 1.5.8 machine catalog occur in both application
binaries, and neither binary is missing a catalog literal. The route set is
therefore byte-proven identical for this catalog.

This does **not** prove that method selection, auth flag, timeout, callback,
coercion, retry, persistence, or hardware consequence is identical. A literal can
survive while its owner changes. The 1.5.8 contracts in
[api-contract-catalog.md](api-contract-catalog.md) remain 1.5.8-only unless the
corresponding old owner/callback was separately compared.

Earlier targeted native comparison covered the Settings/Auto/monitor/weather
surface supported by a pre-release build and embedded monitor descriptor. The new structural comparison does not
silently extend that result to schedules, installer, lock, reset, updater,
performance test, or other private paths.

## Complete QV4 comparison

Both applications decode against the exact retained Qt 6.4.0 instruction header.

| Metric | 1.5.7.4 | 1.5.8 |
| --- | ---: | ---: |
| QV4 units | 307 | 308 |
| QV4 function records | 8,995 | 8,988 |
| Decoded instructions | 102,253 | 102,236 |
| Unit-corpus SHA-256 | Recorded privately | Recorded privately |

All 307 old unit symbols exist in 1.5.8. Of those, 303 unit byte ranges are
byte-identical. Four changed, and one unit was added:

| Exact QV4 unit suffix | 1.5.7.4 size/functions | 1.5.8 size/functions | Proven structural difference |
| --- | ---: | ---: | --- |
| `UiCore_Components_CautionRectangle_qml` | 5,804 / 15 | 5,828 / 15 | All 15 normalized instruction bodies, the declarative shape, literal-pool multiset, and empty translation table are identical; only source-location/string-table layout metadata differs |
| `View_SystemSetup_DualFuelHeatingPage_qml` | 45,244 / 122 | 42,860 / 117 | 115 bodies remain in place, five move exactly into the shared component, and two selector/save bodies change |
| `View_SystemSetup_SystemTypeHeatOnlyPage_qml` | 14,596 / 35 | 11,956 / 30 | Inline fan-control/caution objects are replaced by the new shared component |
| `View_SystemSetup_SystemTypeTraditionPage_qml` | 16,892 / 40 | 14,268 / 35 | Inline fan-control/caution objects are replaced by the new shared component |
| `UiCore_Components_SytemTypeFanControlOption_qml` | absent | 5,012 / 8 | New shared two-choice fan-control component; exact symbol retains the firmware's `Sytem` spelling |

The exact Qt 6.4 `TranslationData` layout is now decoded, and private translation
values are retained only as semantic hashes. The decoder follows the tagged
[Qt 6.4.0 compiled-data definition](https://github.com/qt/qtdeclarative/blob/v6.4.0/src/qml/common/qv4compileddata_p.h#L453-L460): source string, comment,
plural number, and padding occupy one 16-byte record.

`CautionRectangle` is semantically unchanged at the compiled-QML boundary. Every
function's opcode/reference/operand digest matches, the normalized objects,
properties, signals, enums, and bindings match, the literal values match as a
multiset, and both translation tables are empty. The 24-byte raw difference is
accounted for by source-location and reordered/aligned string-table metadata; it
does not add, remove, or change a QML value or body.

The other three pages are one coherent fan-control refactor:

| Page | Bodies unchanged in page | Bodies moved exactly to new component | Old-only / new-only bodies |
| --- | ---: | ---: | ---: |
| Dual Fuel | 115 | 5 | 2 / 2 |
| Heat Only | 28 | 5 | 2 / 2 |
| Traditional | 33 | 5 | 2 / 2 |

The five moved bodies implement common spacing, wrapping, font, width, and caution
type. The new eight-body component adds three component-owned expressions for its
selected-index proxy, rich-text formatting, and revised explanatory text. Its two
existing labels are reversed from thermostat/furnace to furnace/thermostat. The
pages reverse both model-to-index and index-to-boolean conversion with that order:

| Model value | 1.5.7.4 selected index | 1.5.8 selected index | Value saved after no edit |
| --- | ---: | ---: | --- |
| `true` | 0 | 1 | `true` in both |
| `false` | 1 | 0 | `false` in both |
| null/missing | 0 | 0 | `true` in 1.5.7.4; `false` in 1.5.8 |

The page-layer equipment argument is therefore preserved for valid boolean model
state. The genuine behavior changes are the null fallback, revised caution prose,
and, on Traditional only, replacement of an optional `systemSetup` lookup with a
direct lookup. The exact 1.5.8 model normally supplies a boolean, but no isolated
QML runtime proves null impossible; cross-version migration or corrupt-state claims
must retain that narrow caveat. Native body parity remains a separate `VER-U02`
question.

### Byte-identical integration-critical QV4 units

These exact QV4 byte ranges are identical between the two present builds:

| Unit | Size/functions |
| --- | ---: |
| `Core_Backlight_qml` | 1,760 / 3 |
| `Core_DeviceController_qml` | 173,704 / 286 |
| `Core_I_DeviceController_qml` | 7,624 / 25 |
| `Core_Setting_qml` | 3,184 / 5 |
| `View_BacklightPage_qml` | 20,600 / 56 |
| `View_WeatherPage_qml` | 35,960 / 132 |

Byte identity establishes exact parity for those compiled units only. Native
objects they call, filesystem state, recovery image, API service, and secondary
controllers remain independent comparison domains.

## 1.6.1.1 historical findings and current disposition

Prior work associated the absent 1.6.1.1 hash with these targeted differences:

- startup also sets `READY_CONF=1` after loading the device configuration;
- the contractor image path changes from `/home/root/customIcon.png` to
  `/usr/local/bin/customIcon.png`; and
- temperature-correction model 3 was included in the exact-version profile of a pre-release build.

Those findings are historical context, not currently reproducible evidence. The
application and update files must be reacquired, checked against
the recorded values, entered into the private artifact inventory, and rerun through
the complete native/QV4/route/persistence/security workflow before this research
can reaffirm them.

The current runtime allowlist therefore carries a legacy risk: it still recognizes
1.6.1.1 based on earlier review, but the current archive cannot reproduce that work.
Changing runtime support requires a separate implementation decision. No new build
may be added by version range.

## Reproduction

The comparison method and tooling are kept in private research notes. It compares only
reports bound to the exact binary hashes and never emits binary bytes, instructions,
decompiled code, device identifiers, or credentials.

## Remaining version gaps

| ID | Gap | Required evidence |
| --- | --- | --- |
| VER-U02 | Native body parity outside the previously targeted integration paths | Hash-bound dual-project decompilation and normalized call/state comparison by symbol, never by reused address |
| VER-U03 | Complete 1.5.7.4 filesystem/kernel/DT/service/update-container comparison | Reacquire the update or a complete clean root and inventory it separately from the corrupted live snapshot |
| VER-U04 | Reproducible 1.6.1.1 behavior | Reacquire exact update/app files matching the recorded hashes and rerun every phase |
| VER-U05 | Android/mobile protocol differences | Reacquire and hash the three historical APK splits; keep mobile behavior separate from thermostat firmware |

`VER-U01` is closed by the binding/translation-aware disposition above. Until the
remaining rows close, “compatible” means only the exact byte-identical or separately
compared path stated here. It never means “between 1.5.7.4 and 1.6.1.1.”
