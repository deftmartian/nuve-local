# Firmware 1.5.8 scheduling protocol

This schedule path comes from `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
It was analyzed statically and in isolation. Nuve Local does not expose schedules.

## Evidence and controller selection

The native schedule transport is owned by `NUVE::Sync::fetchScheduleV2`
(`0x1fa17c`), `addSchedule` (`0x210428`), `editSchedule` (`0x1fef80`), and
`clearSchedule` (`0x1ff694`). Addresses use the exact Ghidra program's `0x10000`
load bias. The principal compiled QML units are:

| Unit | Exact binary file offset | Role |
| --- | ---: | --- |
| `AppSpec.qml` | `6015872` | schedule, fan, version, hold, and hold-period enums |
| `ScheduleControllerV2.qml` | `6276208` | V2 CRUD, reconciliation, current/next activity, holds |
| `SchedulesController.qml` | `6330752` | legacy V1 CRUD and activity selection |

`ScheduleControllerV2.isActive` is true when `device.schedules.length === 0`.
`SchedulesController.isActive` is true when the legacy array contains a schedule or
has a pending deletion. Therefore any legacy V1 row selects the legacy controller;
an empty legacy array selects V2 even when V2 itself is empty. A V2 schedule can
drive control only when at least one V2 row is enabled and the thermostat is not in
Off, Vacation, or the separate vacation flag state.

These are **A (exact static)** findings. The response-coercion, packet, capacity,
activity-selection, hold, retry, legacy-range, overlap, activation, and migration
claims below are also reproduced by the isolated
[`emulate_firmware_schedule_v2.py`](../scripts/emulate_firmware_schedule_v2.py) and
[`emulate_firmware_schedule_v1.py`](../scripts/emulate_firmware_schedule_v1.py)
models and tests, giving those reproduced behaviors **B (emulated)** evidence.
The generic [target-runtime probe](../scripts/qt6_schedule_runtime_probe.cpp) and a
networkless ARM execution of the exact application add B evidence for the Qt 6.4
time and persistence boundaries described below.

## V2 routes and request shape

The firmware uses a 20-second native request timeout for all four operations. URL
concatenation is literal; the inconsistent leading slash is part of the recovered
contract and must not be silently normalized in evidence.

| Operation | Method and literal suffix | Body |
| --- | --- | --- |
| Fetch | `GET /api/sync/schedules2?sn=<serial>` | none |
| Add | `POST api/sync/schedule2?sn=<serial>` | V2 row packet |
| Edit | `PUT api/sync/schedule2/<id>?sn=<serial>` | V2 row packet |
| Delete | `POST api/sync/clearSchedule2?sn=<serial>&id=<id>` | none |

The V2 add/edit packet contains exactly these schedule members:

| JSON member | Local source and conversion |
| --- | --- |
| `is_enable` | `enable` |
| `type` | numeric schedule type |
| `start_time` | `startTime`, converted from `hh:mm AP` to 24-hour time |
| `heat_to` | `minimumTemperature` |
| `cool_to` | `maximumTemperature` |
| `fan_on` | true only when `fanMode === FMOn` |
| `fan_hours` | `fanWorkingPerHour` |
| `weekday` | numeric day corresponding to the first `repeats` token |

It contains no serial in the body, client UUID, revision, ETag, conflict token, or
idempotency key. `_qsUuid` exists only as local callback correlation. If a local row
has multiple comma-separated repeat days, packet construction reduces that row to
the first day and emits/persists the local change. The normal Add UI avoids that
loss by cloning one row per selected day before submission.

## Server row to local row

A V2 server row maps as follows:

| Server member | Local result |
| --- | --- |
| `id` | `id` |
| `is_enable` | `enable` |
| `type` | `type` |
| `weekday` | abbreviated local day token via `Utils.getDayShortFromIndex` |
| `start_time` | 12-hour `startTime` via `convert24HourT12Hour` |
| `fan_on` | `FMOn` when truthy, otherwise `FMAuto` |
| `fan_hours` | `fanWorkingPerHour` |
| `heat_to` | `minimumTemperature`, default `20.0 C`, clamped to `4.0..30.0 C` |
| `cool_to` | `maximumTemperature`, default `23.3333 C`, clamped to at least `2 C` above heat and no more than `32.0 C` |

Temperature members update only when their absolute difference exceeds `0.001`.
The local row is fixed to `CVersion2`. Equality ignores server id and version and
compares enable, type, minimum/maximum temperatures, start time, repeats, fan mode,
and fan minutes per hour.

The default V2 activities are:

| Type | Heat | Cool | Start |
| --- | ---: | ---: | --- |
| Wake | `20.0 C` | `23.88889 C` | `06:00 AM` |
| Away | `15.55556 C` | `29.44444 C` | `08:00 AM` |
| Home | `20.0 C` | `24.44444 C` | `05:00 PM` |
| Sleep | `16.66667 C` | `25.55556 C` | `10:30 PM` |

All four default to fan Auto, 30 fan minutes per hour, V2, and the thermostat's
current abbreviated local weekday.

## Fetch and mutation response coercion

The native completion callbacks are permissive in ways that matter to data safety:

- Fetch rejects an empty outer JSON object. With network success and any non-empty
  object, it emits success and coerces `data` with `toArray()`. Missing, null,
  object, string, or numeric `data` therefore becomes a successful empty schedule
  list. QML then clears the local V2 array.
- Add accepts any non-empty JSON object on network success. Native code does not
  validate the expected `id`; QML consumes `.id`, so a response without it can
  propagate an undefined id.
- Edit accepts any network-success response and ignores its body. On network error,
  it reads the response description. QML treats the exact text
  `Schedule not found.` as terminal and removes the local row.
- Delete accepts network success when `errors` is absent or converts to an empty
  array. A wrong-type `errors` value also converts to empty and is accepted; only a
  non-empty JSON array is rejected.

Consequently, HTTP success is not equivalent to a validated schedule mutation.
Nuve Local must validate response structure more strictly than the firmware before
committing local state.

## Legacy V1 contract

Legacy rows represent time ranges rather than one V2 activity. Their add/edit packet
contains `is_enable`, `name`, `type_id`, `start_time`, `end_time`, `mode_id`,
`humidity`, `dataSource`, and a `weekdays` array. `mode_id` is local system mode plus
one. Cooling sends `temp` from the local maximum temperature; Heating sends `temp`
from the minimum; other modes send `auto_temp_low` and `auto_temp_high`. V1 has no
per-row fan members, revision, or idempotency key.

Native routing differs from V2:

| Operation | Method and suffix | Additional behavior |
| --- | --- | --- |
| Add | `POST api/sync/schedules` | native inserts `sn` into the body |
| Edit | `PUT api/sync/schedules/<id>` | native inserts `sn` into the body |
| Delete | `POST api/sync/clearSchedules?sn=<serial>&scheduleId=<id>` | no body |

There is no separate V1 fetch owner analogous to `fetchScheduleV2`; V1 rows arrive
inside the full Settings `schedule` member. The parser consumes `schedule_id`,
`is_enable`, `name`, `type_id`, `humidity`, `start_time`, `end_time`, `weekdays`,
`dataSource`, optional `mode_id`, optional Auto bounds, and `temp` for Cooling or
Heating. `mode_id` converts back by subtracting one. Humidity and temperature bounds
are clamped; temperature changes use the same `0.001` threshold.

V1 preserves the local array while any mutation queue is non-empty and also on a
non-array server value, but unlike V2 it does not mark either case for explicit
refetch. An explicit empty array clears all V1 rows. For a non-empty array it first
removes local ids absent from the server, then matches each server row by
`schedule_id`, with a secondary same-name match only for a negative local id. It
adds missing rows and updates matches in place. It does not send the V2-style PUT
echo after server normalization.

V1 add success expects `schedule_id` from the generic native add response and saves
that as local `id`. Native still accepts any non-empty response object, so a missing
`schedule_id` has the same validation weakness as missing V2 `id`.

### Legacy range, overlap, and activation semantics

The controller parses start and end text as local `hh:mm AP` times, then explicitly
sets the end object's seconds field to `59`. Its range helper is start-inclusive and
end-exclusive. For a non-wrapping range, it tests `start <= now < end`; for an exact
equal-or-wrapping pair, it tests `now >= start || now < end`.

That helper must not be interpreted in isolation. An equal-minute UI row such as
`06:00 AM` to `06:00 AM` is passed to it as `06:00:00` to `06:00:59`, so it is an
approximately 59-second window, **not** an all-day activity. An ordinary `06:00 AM`
to `08:00 AM` row runs from `06:00:00` through `08:00:58.999...`; the exact
`08:00:59.000` boundary is excluded.

When the adjusted end is earlier than the start, `updateCurrentSchedules` splits the
row into two entries, preserving model order:

1. start to `11:59:59 PM` on the original repeat days; and
2. `12:00 AM` to the adjusted end on each repeat day's exact successor
   `Mo -> Tu -> We -> Th -> Fr -> Sa -> Su -> Mo`.

The first segment's exact `11:59:59.000` end is excluded. Repeated-day overlap uses
strict interval comparisons plus equal-start collision. One range ending exactly
where another starts is not overlap; overnight candidates are recursively split
across original and successor days before comparison.

`findRunningSchedule` calls JavaScript `find` on the expanded array, so the first
enabled matching row wins when ranges overlap. It then marks the corresponding
original row active and the other rows inactive. Control activation is suppressed
while any hold is active, system mode is Off or Emergency Heat, system shutoff is
set, or a performance test is running.

A row with an empty repeat string is a one-shot activity. While inactive, it is
associated with the current local day. Once selected it becomes `active`; after it
falls outside its range, the controller shifts its comparison day and then disables
the no-longer-selected row. There is an exact overnight defect: after midnight,
`timeInRange` says an active wrapping row is still in range, so its base day is not
shifted backward; overnight expansion then places the continuation on tomorrow
rather than today. The row is not found and is immediately disabled. A non-repeating
overnight activity therefore does not survive midnight to its configured end.

### Legacy-to-V2 migration is deletion, not conversion

Opening Schedules while the legacy controller is active displays the migration
popup. Rejecting it preserves every V1 row and opens the legacy page. Accepting it:

1. detaches every legacy row from its repository;
2. immediately clears the local V1 and expanded-current arrays;
3. queues the `-2` clear-all sentinel if any row has a positive server id;
4. issues legacy `clearSchedule(-2)` immediately only when online;
5. schedules the null-state timer and saves settings; and
6. opens the V2 page.

No field or row is translated to V2. Offline acceptance still deletes the local
rows and retains only the clear-all queue for later processing. This is a destructive
migration choice and is not suitable for automatic Home Assistant activation.

The independent [V1 emulator](../scripts/emulate_firmware_schedule_v1.py) reproduces
the packet member selection, identity reconciliation, adjusted range boundaries,
overnight split, overlap, first-match activation gates, one-shot state transitions
and overnight defect, and both migration choices.

## Reconciliation and conflicts

While the schedule edit page is active or a local edit is pending, V2 preserves the
local array and marks it for refetch. A non-array server value takes the same
preserve-and-refetch path. An explicit empty server array instead clears local V2
schedules.

For a non-empty array, the controller:

1. removes local rows whose ids are absent from the server array;
2. matches each incoming row by identical id, or by repeat day plus start time;
3. adds an unmatched row when the day has capacity, otherwise asks the server to
   delete the incoming id;
4. when day/time match but ids differ, asks the server to delete the incoming id;
5. applies server fields to the matched local row; and
6. sends a PUT echo when applying the server row changed local fields.

There is no recovered server revision or compare-and-swap token. This is procedural
last-observation reconciliation, not a transactional merge. A response-lost POST
can be retried by the firmware and create duplicate server rows because neither the
body nor headers expose an idempotency key. Nuve Local's research model permits an
automatic mutation retry only after proven non-delivery; delivered or ambiguous
delivery is terminal pending explicit reconciliation.

## Activity selection and limits

`maximumActivityPerDay` is an exact readonly QML literal of `12`. New-schedule Save
splits `repeats` on commas, clones once per day, and skips only days already at the
limit. Overlap means exact same start-time text plus at least one common repeat day;
the function accepts a type argument but does not use it.

Enabled rows are grouped by trimmed, lowercase two-letter local day token and sorted
by locale parsing of `hh:mm AP`. The running activity is the latest enabled row at
or before now. If today has none, the search walks backward up to seven days. The
next activity search walks today and then up to seven days forward. A repeating
one-second timer recalculates the running row. The isolated model reproduces the
weekday walk and row selection using the exact `Mo` through `Su` token family.

### Exact Qt locale, DST, and timezone behavior

The recovery service declares no locale and the clean root has no locale override,
so its exact default is Qt's `C` locale. Under the exact ARM Qt 6.4.0 libraries,
`hh:mm AP` accepts the application's `AM`/`PM` strings in `C` and `en_US`, rejects
them in `en_CA` and `fr_CA`, and rejects malformed text. No application path calls
`QLocale::setDefault`; a non-C service locale is therefore external environment
drift, and can make otherwise ordinary persisted times invalid.

With `America/Halifax`, the exact QV4 `Date` setters normalize a nonexistent spring
`02:30` backward to `01:30` at the standard offset and choose the standard-offset
occurrence of the repeated fall `01:30`. An in-process UTC-to-Halifax change leaves
an existing `Date` epoch unchanged while its local hour changes from 17 to 14. A
newly reconstructed 17:00 activity remains at wall-clock 17:00 and shifts its epoch
by three hours. That distinction matches the firmware model: schedule rows retain
wall-clock strings and are reconstructed on selection, while an already-created
date retains an absolute instant until the controller recomputes it.

Copying one day's activities deletes all destination-day rows before adding clones.
The overlap override path edits each colliding row with the new type, temperatures,
time, and fan values, then adds the target only for remaining non-overlap days.

## Holds

Native `HoldType` is a bit mask: none `0`, temperature `1`, fan `2`, all `3`.
Declarative `HoldPeriod` is TwoHours `0`, FourHours `1`, UntilNextActivity `2`,
UntilChanged `3`, Unknown `4`. Period and start-time maps are keyed by numeric hold
type. Adding a hold ORs the bit and removing it ANDs the complement.

Two- and four-hour expiry compare JavaScript `Date` elapsed time with exact hour
durations. UntilChanged has no start time and does not expire automatically.
UntilNextActivity expires at the reconstructed next local activity when its hold
start predates that activity; if there is no next activity, it expires immediately.

Temperature hold in Auto temporarily locks the Auto push, then a 3.5-second timer
unlocks and pushes Auto mode. Other temperature holds push hold plus desired
temperature immediately. Fan hold and hold removal push hold state. Clearing all
holds clears both maps and sends native hold type zero.

The controller contains three references to misspelled `AppSpec.HPUnknow`; the
declared member is `HPUnknown = 4`. Exact whole-QV4 call-site search finds only two
callers of `addHoldType`: the Settings handler passes three arguments and the V2 hold
popup passes two. Both explicitly supply a valid hold period. Therefore the typo is
not reached as a default by any recovered caller. If a future caller omitted the
period while the map entry were absent, the hold bit and native hold type would be
set before `updateHoldPeriod` returned early on `undefined === undefined`, without a
period/start update, server push, or settings save. Removal's misspelled assignment
is immediately deleted and has no surviving value effect.

The V2 delete retry defect is now statically resolved rather than a runtime unknown.
The initial call is `clearSchedule(id, CVersion2)`. The timer calls
`clearSchedule(id)`; Qt's exact generated meta-call wrapper makes this callable and
supplies default integer `1`. Exact `AppSpec.qml` declares `CVersion1 = 1` and
`CVersion2 = 2`, and native routing selects V2 only for value `2`. A failed V2 delete
that reaches the timer is therefore retried against the **V1 clear route**, not the
V2 route. This cannot be treated as a safe retry.

## Retry timers

The QML literal intervals are add 2 seconds, delete 3 seconds, edit 4 seconds, and
fetch 5 seconds. These are one-shot queue timers triggered again after a terminal
callback. The current-schedule timer repeats every second; Auto hold push waits 3.5
seconds; unit-change handling waits 100 milliseconds.

The timers describe vendor behavior, not an acceptable retry policy. In particular,
automatic POST retry after ambiguous delivery is unsafe.

## Two Home Assistant ownership designs

Neither design is implemented or authorized by this research pass.

| Property | HA-owned scheduler; thermostat remains `NoSchedule` | Thermostat-native editor/synchronizer managed from HA |
| --- | --- | --- |
| Transition owner | HA automations issue ordinary, complete Settings/Auto changes only after fresh `NoSchedule` authority | Thermostat V2 controller selects activities; HA owns validated CRUD, reconciliation, and an operation journal |
| HA/LAN outage | New scheduled transitions stop; the thermostat keeps its last confirmed setpoint and continues local HVAC control | Confirmed local rows keep selecting on-device, but HA cannot observe edits or reconcile ambiguous vendor/local delivery |
| Manual override | Touchscreen setpoint/fan changes remain ordinary settings until the next explicit HA transition; HA needs an explicit skip/override helper | Touchscreen schedules and holds can interoperate, but every edit must be merged bidirectionally without a revision or idempotency token |
| Recovery | HA schedule configuration belongs in HA backup; restart requires fresh monitor/Settings baselines before the next transition | Device rows persist in the non-atomic QtQuickStream graph; pending CRUD is not journaled, V1 migration deletes rather than converts, and one V2 delete retry uses the wrong route |
| Complexity | Moderate and uses the already proven fail-closed Settings boundary | High: two generations, local/server identity reconciliation, durable delivered/unconfirmed state, conflicts, touchscreen edits, holds, and corruption recovery |
| Residual risk | Missed transitions during HA outage and later automation overriding a manual change | Duplicate/lost rows, stale conflicts, destructive migration, wrong-route retry, persistence loss, and schedule-driven whole-state consequences |

If schedule implementation is considered later, the HA-owned design is the smaller
initial safety boundary because it retains the proven `NoSchedule` gate and never
calls schedule CRUD. It still needs a separate product decision, explicit override
semantics, outage tests, and deployment approval. A native editor should remain
unsupported until it has an atomic local journal, strict response validation,
post-ambiguity reconciliation, touchscreen conflict rules, and disposable-clone
recovery evidence.

## What remains unresolved

- **U:** filesystem/eMMC atomicity for schedules, ids, hold maps, and pending
  mutations across process termination or power loss;
- **U:** authoritative server-side duplicate handling, ordering, and conflict rules;
- **U:** any reversible device test of schedule CRUD and restoration.

The storage item requires fault injection against disposable media matching the
photographed `THGBMTG5D1LBAIL` and still needs exact EXT_CSD, rail, cache, and
interruption behavior; the conflict item requires vendor evidence, and live
activation requires separate approval. The available
corpus has no remaining unreviewed schedule action or locally unmodeled action
family. Schedules remain intentionally unsupported for automatic Home Assistant
control.
