# Firmware 1.5.8 application persistence

This persistence model comes from `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
It excludes the device INI, NetworkManager, protobuf queues, updater files, and
bootloader storage.

## Owner and files

The root `Device` is a `QSObject` graph managed by the bundled QtQuickStream
`QSRepository`. `I_Device.qml` at file offset `6217120` declares schedules,
V2 schedules, hold type, hold-period and hold-start maps, fan, backlight, wiring,
settings, vacation, night mode, lock, user data, and other nested persistent
objects.

The primary path is a read-only QML string:

```text
/usr/local/bin/sthermConfig.QQS.json
```

The recovery path is `StorageController.recoveryDirectory()` plus
`/sthermConfig.QQS.json`. A legacy relative `sthermConfig.QQS.json` is also tried at
startup. The startup order is primary, legacy relative, recovery, then a new
default `Device` object.

## Stored representation

`QSRepository.dumpRepo(STORAGE)` emits one JSON object keyed by each QS object's
internal UUID plus a `root` member containing a `qqs:/<uuid>` reference. Registered
object references and schedule arrays use the same URL form. Dates serialize with
`toISOString()`.

`QSSerializer` walks enumerable object properties. It excludes `objectName` and any
name beginning or ending with `_`; consequently `_qsUuid` and `_qsRepo` are not
ordinary fields, while public `schedules`, `schedulesV2`, `holdType`, `holdPeriod`,
`holdStartTime`, and schedule `id` are persisted. `saveToFile` uses pretty JSON with
four-space indentation.

The `ScheduleCPP` public row includes name, type, system mode, start/end time, data
source, repeats, temperature, humidity, minimum/maximum temperatures, enable,
active, id, version, fan mode, and fan minutes per hour. V2 packet construction uses
the narrower subset in [scheduling-protocol.md](scheduling-protocol.md), but the
local object serializer is broader.

The retained private 2026-08-09 live snapshot corroborates the container shape
without contributing private values: 15 top-level members, one root reference, and
14 object records. The root had array-typed V1/V2 schedule members and object-typed
hold maps. All retained copies had zero schedule rows and empty hold maps, so that
snapshot cannot prove populated-row round trips. It is a nearby live 1.5.7.4
artifact and is not used as firmware 1.5.8 evidence.

The isolated emulator builds a fully synthetic populated graph using the same root
URL, registered `ScheduleCPP` records, V1/V2 URL arrays, public ids/versions, hold
bit, period map, and ISO start map. A networkless ARM execution then loaded and
re-serialized that shape under the application and Qt 6.4.0 target libraries.
Properly braced QtQuickStream identifiers preserved one V1 row, one V2 row, both
ids/versions, hold type `3`, and two UntilChanged period entries with no dangling
reference. The source image was read-only; identity, client, schedules, and writable
state were synthetic and disposable.

The same run establishes a controller rule outside the serializer itself:
`findCurrentSchedules` calls `clearHoldType` whenever no V2 row is enabled. A
nonzero persisted hold is therefore normalized to no hold when the enabled-activity
map is empty. With one enabled synthetic V2 row, the exact runtime preserved the
hold state across restart. This is **B (emulated target-runtime)** evidence, not a
live thermostat activation.

## Save timing and restart behavior

`DeviceController.saveSettings` does nothing during factory-reset state. Otherwise
it restarts a one-shot 1,000 ms `saveTimer`. The timer requires only that
`uiSession.currentFile` be non-empty, then writes the complete current repository
to the primary path. Repeated changes inside the interval are coalesced.

Pending schedule add/edit/delete queues belong to the controller, not the persisted
root object graph. No recovered path journals those in-flight operations across an
application restart. Confirmed local schedule rows, ids, and hold maps are part of
the repository; delivery ambiguity is not.

On startup, `loadFromFile`:

1. rejects a zero-length file;
2. parses JSON;
3. rejects a missing or falsey `root` member;
4. reconstructs QS objects and resolves `qqs:/` references; and
5. returns false on an exception.

After startup chooses or creates a repository, it removes the legacy relative file
and saves the selected state to the recovery path. The recovery copy is therefore a
startup snapshot, not a continuously updated mirror of later primary-file changes.

## Atomicity and corruption boundary

The bundled `FileIO::write` (`0x1664ec`) opens `QFile` with numeric mode `10`, which
is `WriteOnly | Truncate`, and writes directly to the target. There is no `QSaveFile`,
temporary sibling, flush/fsync, checksum, generation number, backup rotation, or
atomic rename in this path.

It reports success whenever `QIODevice::write` returns a nonzero value. That means a
partial positive write is accepted, and even the conventional error result `-1` is
treated as success; only exactly zero is reported as failure. The caller does not
check an expected byte count.

The isolated [persistence emulator](../scripts/emulate_firmware_persistence.py)
reproduces the load gates, fallback order, property blacklist, truncated-write
result, nonzero-return bug, registered schedule URL graph, public property filter,
populated V1/V2/hold-map round trip, and dangling-array-reference filter. Its tests
and the target-runtime run establish **B (emulated)** evidence for those behaviors.
QV4 and native code provide **A (static)** evidence.

## Safety consequences

- Power loss or process termination during a primary save can leave invalid or
  partially valid JSON. The next startup may fall through to a stale recovery copy
  or defaults.
- Recovery is not current after every setting change. It reflects the state selected
  at the preceding startup.
- Valid JSON with a truthy `root` can pass the initial gate without any file-level
  authenticity or integrity proof. Per-object reconstruction errors may still make
  load fail, but there is no transactional rollback.
- A dangling `qqs:/` entry in a schedule array resolves to `undefined` and is then
  silently filtered out by the serializer callback. A dangling root reference
  cannot produce the root Device. Thus some internal corruption can look like an
  empty/missing row rather than an all-or-nothing load failure.
- Qt 6.4 duplicate JSON members use the last value and serialize back to one
  member. A duplicate property can therefore overwrite earlier state without making
  the document invalid.
- Wrong-typed root schedule and hold fields pass the truthy-root admission gate. In
  the target runtime they remained wrong-typed, the application stayed alive,
  and schedule handlers raised repeatable QML assignment/iteration errors. The
  loader is not a schema validator and does not reliably normalize admitted state.
- A response-lost schedule mutation is not durably journaled. Restart can discard
  the pending retry context while retaining a locally saved row or deletion.

Nuve Local must not copy this persistence design for schedule writes. A supported
implementation needs atomic replacement, schema validation, a generation or
revision record, and an explicit delivered/unconfirmed operation journal.

## Remaining unknowns

- **U:** arbitrary combinations of deeper nested-object corruption and dangling
  references outside the root/schedule cases reproduced above;
- **U:** filesystem and eMMC guarantees during sudden power loss, including whether
  the recovery volume write is durable on the physical eMMC;
- **U:** whether any external target service restores a corrupted primary before QML
  startup; and
- **U:** cross-version schema migration beyond the one legacy filename fallback.

The structural graph, load gates, fallback order, public schedule/hold fields,
property blacklist, duplicate-member rule, wrong-type persistence, dangling
schedule-array/root behavior, direct-truncation hazard, populated target-runtime
schedule/hold round trip, and no-enabled-activity hold clearing are closed with A+B
evidence. Arbitrary combined corruption cannot be turned into a schema-safety claim
because the firmware has no schema gate. The installed storage is photographically
identified as a `THGBMTG5D1LBAIL`, but durability still requires matching
fault-injected disposable media plus EXT_CSD, rail, cache, and interruption behavior.
Cross-version migration requires another complete version-specific artifact.
