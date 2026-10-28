# Firmware evidence and safety boundaries

This page explains the firmware behavior used by Nuve Local and the limits of that
analysis. Firmware, captures, credentials, certificates, and device data stay outside
the repository.

## Evidence set

The primary target is recovery application `1.5.8`, SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
The 1.5.8 recovery set and 1.5.7.4 application are retained privately. Other builds
and the Android app have only historical hashes and must be reacquired before their
analysis can be repeated. [Artifact inventory](artifact-inventory.md) owns the full
hash and provenance list.

Analysis combined ARM code, Qt/QV4 data, protobuf descriptors, recovered QML,
private packet captures, isolated models, and non-contact board photographs. The
photographs identify visible parts and labels, not electrical ownership. Mobile-app
endpoints are separate from the thermostat sync protocol.

The 1.5.8 work was repeated against the hash above after an earlier project was found
to contain 1.5.7.4 under the wrong name. Relevant compiled QML is byte-identical
between those builds, and native request/parsing paths were checked separately.
Compatibility is still tied to each named build, never inferred as a version range.

The [claim ledger](#claim-ledger) below records whether each claim comes from static
analysis, reproduction, observation, a reversible test, or remains unresolved.

## Evidence grades

- **A — Static analysis:** confirmed in hash-matched code, metadata, filesystems,
  images, or the bootloader.
- **B — Reproduced:** confirmed with an isolated parser, server, emulator, fixture,
  or hardware model.
- **C — Live observation:** seen on the reference thermostat without changing it.
- **D — Reversible live test:** changed and restored on the reference thermostat.
- **U — Unresolved:** the available information is missing, contradictory, or not
  strong enough for the claim.

Grades can be combined. A state-changing feature normally needs static analysis and
an isolated reproduction before live testing, followed by live observation or a
reversible test before it is supported. `U` remains until the missing artifact or
test is identified.

## Reproducibility method

The proprietary images and private captures cannot be redistributed. The steps below
can be repeated against lawfully obtained copies:

1. Hash the update/recovery container and extracted `appStherm` before importing it.
2. Import the ARM ELF with its load addresses intact; preserve symbols where present.
3. Locate embedded QML through the Qt resource/QV4 metadata, extract the relevant
   compiled units, and compare their bytes between builds before assuming parity.
   The schema-4 inventory and schema-3 [UI action register](ui-action-register.md) enumerate
   declarative objects, bindings, object-owned functions, and every recognized
   `onX` handler without retaining embedded source or prose.
4. Recover `DevApiExecutor`, `Sync`, `WeatherService`, `ProtoDataManager`,
   `LiveDataManager`, and `DeviceConfig` call sites from strings and cross-references;
   trace QJson/QVariant conversions through the callback, not only endpoint literals.
5. Extract the serialized protobuf descriptor and generate independent known-field
   decoding tests. Preserve proto3 field presence when merging sparse records.
6. Use an isolated local endpoint to record request method, path, headers, exact body
   length, timing, and response outcome. Redact bearer tokens, serials, addresses,
   Wi-Fi names, and contractor metadata before retaining examples.
7. Reconcile every captured value with its producing QML/native constructor. A live
   rejection is evidence to revisit the decompile, not a reason to loosen parsing
   until arbitrary input happens to pass.
8. Preserve raw board photographs outside Git with owner-only permissions and a
   hash manifest. Publish only redacted markings, and require a schematic or
   donor-board continuity evidence before assigning silk labels to nets or owners.

Key exact `1.5.8` landmarks used in the final reconciliation include Ghidra
`0x1a73c0` for the DevApi `data` unwrapping path; `0x20b43c` for nested Settings
revision lookup; `0x23b53c` and `0x23b694` for nested command metadata; QV4
DeviceController functions 51/53 for the full upload and system constructors; and
native `ProtoDataManager` around Ghidra `0x2baecc` for online-mode/timer behavior. Addresses
are version-specific and are supplied only as reproducibility anchors; hashes, code
shape, and call graph must all match before reusing them.

The indoor-temperature producer/consumer chain is exact. DeviceController QV4
function 89 calls native `getMainData`, assigns `roundTemperature` to
`displayCurrentTemp`, and passes that same property to
`ProtoDataManager.setCurrentTemperature`. Function 51 serializes
`displayCurrentTemp` as full-Settings `current_temp`; function 269 supplies it to
`pushSensorValues`; and Home QV4 function 120 binds its displayed `temperature`
property to `deviceController.displayCurrentTemp`. Native
`LiveDataManager::setCurrentTemperature` (`0x2a9c94`) records a sparse change at an
absolute difference of at least `0.001`. These paths disprove separate UI-versus-HA
calibration sources. Historical Settings observations and buffered cross-family
delivery remain transport concerns, so Nuve Local retains observation provenance
and never restores persisted room values as live telemetry.

## Synchronization API

The following behavior is exact for firmware `1.5.7.4`; corresponding paths were
checked in recovery `1.5.8` and `1.6.1.1`. These three exact strings form the current
allowlist. Compatibility is not inferred for intermediate, earlier, or later
versions; each new firmware requires renewed native/QML review before canonical
responses or control are enabled.

For exact `1.5.8`, a raw-string pass found 39 distinct `api/`-bearing strings. The
Ghidra defined-data/xref pass resolved direct function owners for all 38 route
literals; the remaining literal is the generic `/api/` fragment rather than a
standalone operation. The implemented and non-implemented tables below assign every
route family a disposition, so an unobserved onboarding or test URL is not silently
treated as supported.

| Request | Confirmed role |
| --- | --- |
| `GET /api/sync/getSettings?sn=...` | Whole desired-state poll |
| `POST /api/sync/update` | Complete device-originated state upload |
| `GET/POST /api/sync/autoMode?sn=...` | Auto low/high bounds |
| `POST /api/device/settings?sn=...` | Complete device-preference subsection |
| `POST /api/device/system?sn=...` | Complete HVAC/installer subsection |
| `POST /api/device/current-sensors?sn=...` | Current room-sensor values |
| `POST /api/device/current-stages?sn=...` | Current relay-stage values |
| `POST /api/device/wifi-off?sn=...` | Manual Wi-Fi-off state acknowledgement |
| `POST /api/monitor/data?sn=...` | Protobuf live telemetry |
| `POST /api/monitor/event?sn=...` | Protobuf UI-event queue |
| `POST /api/monitor/report?sn=...` | Command-response report acknowledgement |
| `GET /api/sync/getContractorInfo?sn=...` | Contractor metadata and logo URL |
| `GET /api/contractor-logo?sn=...&sig=...` | Exact PNG for stock image downloader |
| `GET /api/weather-current?sn=...&units=metric` | Current outdoor conditions |
| `GET /api/weather-forecast?sn=...&units=metric` | Up to seven forecast days |
| `GET /api/designTemperature?sn=...` | Fahrenheit heating/cooling design values |

The exact `1.5.8` binary contains additional API paths whose owning functions
were reconciled even though Nuve Local does not implement them:

| Path family | Firmware owner / role | Local disposition |
| --- | --- | --- |
| `/api/sync/client` | `fetchUserData`; private `email` and `con-name`, persisted as user-data email/name | Unsupported; see [messages-reset-api.md](messages-reset-api.md) |
| `/api/sync/messages` | `fetchMessages`; callback discards the body, while server messages arrive through full Settings | Unsupported; see [messages-reset-api.md](messages-reset-api.md) |
| `/api/sync/schedule*`, `/api/sync/schedules*`, `/api/sync/clearSchedule*` | fetch/add/edit/clear schedule generations | Unsupported; Settings returns non-array preservation sentinels |
| `/api/sync/screen-*` | push screen-lock state | Unsupported; no captured server lock baseline |
| `/api/sync/alerts` | push device Alert/SystemAlert with 6-second uncapped retry and transport-only acknowledgement | Unsupported; no private alert sink or retention policy; see [messages-reset-api.md](messages-reset-api.md) |
| `/api/sync/getSn`, `/api/sync/getWirings` | installation identity mutation and response-ignoring wiring notification | Not exposed; see [installer-private-api.md](installer-private-api.md) |
| `/api/sync/updateAddress`, `/api/zipCode`, `/api/customer` | address/customer lookups with persisted and timezone side effects | Not exposed; see [installer-private-api.md](installer-private-api.md) |
| `/api/technicians/device/install`, `/api/technicians/service-titan/customer/*`, `/api/technicians/warranty` | installer/external-service operations, including a pre-response warranty serial write | Not exposed; see [installer-private-api.md](installer-private-api.md) |
| `/api/sync/forget`, `/api/device/recovery-image` | registration reset and recovery file-information report | Not exposed; see [messages-reset-api.md](messages-reset-api.md) |
| `/api/sync/perftest/*` | equipment performance-test schedule/results | Not exposed because the application path can exercise normal HVAC and accessory outputs; see [performance-test.md](performance-test.md) |

Unknown paths receive an explicit failure rather than a catch-all success. This
keeps dormant onboarding, customer, destructive, and equipment-test flows from
becoming accidentally active merely because their URL strings are known.

The complete `/api/sync/update` upload has these required top-level fields:

```text
sn, temp, humidity, current_humidity, current_temp, co2_id, hold,
hold_period, mode_id, fan, backlight, settings, sensors, messages,
system, vacation, firmware
```

Its nested `system` object is built by the same recovered QML function as
`/api/device/system` and contains all 36 installer/HVAC fields, including its own
`sn`. Nuve Local rejects a full baseline if that object is incomplete or its nested
serial differs; it never fills missing installer settings with defaults.

Every DevApi JSON response has an outer `data` member. The settings response is not
a direct echo. After that outer wrapper is removed by native code, the desired HVAC
state is flat while device preferences and native synchronization metadata are in a
single nested `setting` object:

```text
{
  data: {
    sn, temp, humidity, hold, hold_period, mode_id, fan, sensors, system,
    vacation, schedule, schedule2,
    setting: {
      <device preferences>, backlight, tempCorrectionVersion, last_update,
      command?, command_time?
    },
    qr_url, messages, locked?, pin?, firmware?
  }
}
```

Native `DevApiExecutor::prepareJsonResponse` in exact `1.5.8` unwraps the outer
`data` object. Native settings code then reads the revision specifically from
`data.setting.last_update`, but passes the whole flat `data` map to QML. Recovered
QML reads `temp`, `fan`, `system`, `vacation`, and the other desired fields directly,
then reads UI preferences from singular `setting`. Native command dispatch likewise
reads `command` and `command_time` from that same nested object. This split was
confirmed at the exact `1.5.8` native paths corresponding to Ghidra `0x1a73c0`
(DevApi unwrap), `0x20b43c` (nested revision), and `0x23b53c`/`0x23b694`
(nested command metadata), plus DeviceController QV4 functions 51 and 53.

The upload's plural `settings` therefore becomes singular `setting`, and the sibling
upload `backlight` must be merged into that inner preferences object. The upload's
`firmware` object reports the installed version; it must not be turned into the
distinct top-level firmware-update instruction.

Schedules and screen-lock state are server-owned and absent from a full settings
upload. Returning an empty schedule array clears local schedules. Until their exact
endpoint state has been captured and implemented, Nuve Local returns a non-array
sentinel which both schedule controllers reject without replacing local state. It
omits unknown lock fields rather than fabricating an unlocked state or PIN.

Remote-sensor metadata is present in a full upload but has no dedicated CRUD route.
Exact 1.5.8 builds the upload from private `_sensors`, collapses all nonzero location
enums to `Bedroom`, and assigns every entry literal UID `213137`. The pairing page
never calls the inert native pairing hooks, while Settings `sensors` rows are only
logged and never copied into the visible private array. See
[remote-sensors.md](remote-sensors.md); this path is intentionally unsupported.

`qr_url` is not a harmless optional field, but it also does not own the photographed
Contact Contractor page. Recovered QML compares it with the persisted
`contactContractor.technicianURL`; any unequal string replaces that metadata and
schedules a save to `/usr/local/bin/sthermConfig.QQS.json`. Baseline capture therefore
requires the exact current string. After a complete baseline exists, the explicit
Home Assistant option may replace it. Missing, null, fabricated empty, and object
values remain unsafe.

Exact `1.5.8` separates three similarly named URL paths:

- DeviceController QV4 function 228 reads Settings `data.qr_url` during
  `onAppDataReady` and calls function 55, `updateTechQRurl`. Function 55 strictly
  compares and updates `device.contactContractor.technicianURL`, then calls
  `saveSettings()` only when it differs. The Technician Access popup compiled unit
  at `0x6a0120` reads that property to generate its QR.
- The photographed Contact Contractor page compiled unit at `0x6d8db0`, function 2,
  instead reads `root.deviceController.contactContractorURL`. DeviceController
  function 19 builds that property from the literal
  `https://thestat.link/api/schedulelink?sn=` plus `system.serialNumber`. It does not
  read Settings `qr_url`.
- `onContractorInfoReady` function 249 stores contractor metadata `info.url` in
  `contactContractor.qrURL`. An exhaustive lookup scan of every exact-`1.5.8` QV4
  unit found that assignment but no reader of `qrURL`.

The reference screen's unchanged Contact Contractor QR therefore corroborates the
bytecode rather than showing a failed Settings delivery. Nuve Local labels the
existing option as the Technician Access QR website and leaves the Contact Contractor
QR unsupported; changing it would require a different, presently unproven device
modification path.

`GET /api/sync/client` is separate from contractor metadata. Exact
`NUVE::Sync::fetchUserData` (`0x1f9de4`) reads string fields `email` and
`con-name`; DeviceController QV4 function 241 stores them in private device user
data and calls `saveSettings`. The Mobile App page fetches the endpoint on page
completion and renders the email. Those private values are absent from the full
Settings upload, so Nuve Local leaves the endpoint unsupported rather than
inventing, disclosing, or overwriting an identity.

The inner preferences response also requires the exact numeric
`tempCorrectionVersion`. That value is absent from the full settings upload, and
there is no proven neutral sentinel. Firmware `1.5.7.4` and `1.5.8` contain correction
models 1 and 2; `1.6.1.1` contains models 1, 2, and 3. Those sets can validate a value
read from the thermostat; they cannot tell us which value to choose. Full Settings
responses also require confirmation that no firmware
update is active, because an update instruction and an installed-version report are
different protocol concepts and must not be conflated.

No automatic local API that safely acquires all three response-only facts has been
proven. The installed version can be cross-checked against the device version screen
and its later full upload. The Technician Access URL must come from the current
Technician Access display/QR or a read-only copy of the live configuration. The
correction model requires current read-only configuration or log evidence; recovered
logs may identify the selected model, but supported-model tables alone do not. The
no-update assertion requires independent current device/update-service evidence. A
failed update fetch does not prove that no update is active. If any value is unknown,
Nuve Local must not render the canonical whole-state response.

`last_update` is UTC in `yyyy-MM-dd HH:mm:ss` form and must increase strictly for
the firmware to apply a new desired state. On the wire, a settings-upload
acknowledgement is `{"data":{"setting":{"last_update":"..."}}}`; partial and
Auto acknowledgements place `last_update` directly inside `data`.

## Capturing the initial device state

This state machine was recovered from both firmware versions:

1. An installed thermostat starts with `_initialSetupPushCompleted=true`.
2. Its settings push timer is gated by `System::areSettingsFetched` and by the
   settings loader not fetching.
3. Empty settings JSON is a failed fetch. The chained Auto fetch must also return a
   nonempty object before `areSettingsFetched` becomes true.
4. A local setpoint nudge can update monitor telemetry without bypassing this gate.
5. The Backlight page's Save action always queues `EMBacklight`, even when no value
   changed. That queued edit survives until the fetch gate opens, then routes to the
   complete `/api/sync/update` path.

Nuve Local can open a short capture window. During that window only,
one settings poll receives a serial-matched, nonempty envelope whose first QML
handler rejects an intentionally non-string `hold_period` before later desired-state
handlers run. Its companion Auto response uses object operands; the native layer sees
a nonempty response while the QML numeric-difference tests evaluate false. No HVAC,
fan, schedule, lock, or setpoint value is supplied. It does update firmware sync/cache
and forgotten-device state, and the Auto handler requests persistence; it is therefore
non-applying for HVAC, but it still changes firmware sync/cache state. Capture stops
as soon as the complete upload is saved and accepted. A new installation normally
arms one attempt after pairing and fresh monitor data arrive; an optional diagnostic
button allows a manual retry.

The response is outside the vendor schema and exists only to break this startup
deadlock. It is limited to the short capture window, covered by regression tests, and
disabled once the starting device state has been saved.

## Monitor protobuf and confirmation

The embedded descriptor was extracted from all three applications;
the `1.5.7.4` and `1.5.8` descriptor blobs are byte-identical with SHA-256
`f3339980764bc8f15e96d961bcbeff2863569ed9d3b795ff40df9a8d1ea39d7d`.
Private captures confirmed that `/api/monitor/data` is a raw serialized
`LiveDataPointList` with `Content-Type: application/x-protobuf`, not JSON or a
compressed envelope. The recovered message contains repeated `LiveDataPoint`
records. Fields
2 through 19 represent, in order where present: set temperature, set humidity,
embedded temperature, embedded humidity, MCU temperature, pressure, IAQ category,
cooling stage, heating stage, fan output, LED output, full-sync flag, system type,
running mode, reported connectivity, Auto low, Auto high, and schedule type.

### Indoor-air-quality and pressure provenance

Exact `1.5.8` `DeviceIOController::processNRFResponse` case `0x4a` proves the
application-side producer rather than relying on labels or a nearby sensor example.
It decodes `co2` as an unscaled `uint16`, `etoh` as `uint16 / 100`, `Tvoc` as
`uint16 / 1000`, `iaq` as `uint8 / 10`, and `pressure` as an unscaled `uint16`,
alongside temperature, humidity, range, brightness, and fan-speed values. The sensor
identity is the Renesas ZMOD4410. Its official firmware documentation defines eCO2
in ppm, ethanol-equivalent in ppm, TVOC in mg/m3, and the standardized IAQ score;
it is not a carbon-monoxide measurement. See the
[ZMOD4410 data sheet](https://www.renesas.com/en/document/dst/zmod4410-datasheet),
[official product page](https://www.renesas.com/en/products/general-parts/zmod4410-firmware-configurable-indoor-air-quality-iaq-sensor-embedded-artificial-intelligence-ai),
and Renesas explanations of
[eCO2](https://community.renesas.com/sensor-products/f/support/32019/eco2-to-detect-human-presence---zmod4410) and
[TVOC/ethanol-equivalent output](https://community.renesas.com/analog-products/f/support/52136/problem-using-zmod4410/185557).

The downstream contract is narrower. Exact `DeviceController` QV4 function 89
copies `pressure` to the device model and `ProtoDataManager`, but converts `iaq`
through `I_Device::airQuality`: scores below 2.9 become internal category 0,
2.9 through 4 become category 1, and scores above 4 become category 2. The JSON and
protobuf transports publish only the resulting one-based category. Numeric eCO2,
ethanol-equivalent, TVOC, and IAQ score never enter those recovered transports.
`LiveDataManager::setAirPressure` publishes integer hPa when the value changes by at
least 1 hPa, confirming the unit of monitor f7.

A privacy-preserving read-only characterization of the reference unit's local
sensor history found 107,555 valid rows over 1,800.8 hours at a 60-second median and
95th-percentile cadence. Positive populations spanned 400..2413 eCO2, 0.08..35.2
ethanol-equivalent, 0.157..65.043 TVOC, 1..4.6 IAQ score, and 993..1020 hPa. IAQ
category populations matched the exact thresholds. Synchronized all-zero sensor rows
prove zero is a missing/unready sentinel; pressure also remained zero throughout the
most recent 120 rows on this unit. No raw row, timestamp, identifier, path content,
or private device value is retained in the repository.

This closes the unit, scale, range, sentinel, cadence, and category-direction
questions but not the transport gap. The application receives already processed
values from the NRF board; the exact board driver/library version, algorithm mode,
calibration state, and numeric network transport remain unproven. Nuve Local therefore
keeps the neutral categorical entity, enables positive hPa pressure normally, treats
zero as unavailable, and does not expose numeric IAQ-family entities.

Except for the full-sync flag, scalar fields are proto3 optional. Later records are
sparse deltas. Nuve Local replaces monitor state at a full-sync record and otherwise
merges only fields present on the wire. Absence is never interpreted as numeric zero.

Exact `1.5.8` also embeds `event.proto` at
`descriptor_table_protodef_event_2eproto` (`0x1bcb09c`). `EventList` contains
repeated `Event` records with a `google.protobuf.Timestamp`, an `EventNameType`, and
an optional UTF-8 target. The enum is limited to none, contact-contractor clicked,
get-mobile-app clicked, and contractor-message closed. `EventDataManager` sends the
raw list as `application/x-protobuf`; its completion callback checks transport error
state rather than parsing a response body, and removes a queued file after success.

Nuve Local accepts only that exact structure and enum range. It returns the normal
DevApi success envelope, counts the endpoint request, and discards the target. The
target never enters logs, persistence, diagnostics, or Home Assistant state. A
A device check using redacted output confirmed that a queued multi-event file drained
after the endpoint returned success.

Exact `1.5.8` timer disassembly shows that the first transition to online monitor
mode creates a full packet, the sender then checks for queued sparse changes every
10 seconds, and a separate repeating timer creates an unchanged full packet every
3,600,000 ms. Repeating `push_live_data` while online re-enters dispatch but
`setSendDataOnline(true)` returns without creating another full packet. The
integration therefore retains authoritative full-monitor state for 70 minutes, a
10-minute scheduling/network margin over the exact one-hour cadence. This is an
availability horizon, not a command-confirmation timeout: a write still requires a
new post-delivery sparse/full record within 75 seconds.

The command path also supports post-restart resynchronization. At
`System::onAppDataReady` (`0x23b4e4`), firmware passes the Settings `command` and
`command_time` to `System::attemptToRunCommand` (`0x239ec8`) even when both strings
are absent. That function always finishes by calling
`ProtoDataManager::setSendDataOnline(command == "push_live_data")`. The latter
function (`0x2baecc`) creates a full monitor packet only on its false-to-true
transition. Nuve Local therefore alternates two delivery-aware, non-applying
Settings responses while fresh post-start monitor authority is absent: an empty
command turns only the monitor publisher off, then a newer `push_live_data` turns it
back on and queues a full snapshot. Both responses use the already proven
`hold_period` object trap and contain no desired temperature, mode, fan, system,
schedule, vacation, or lock state. A failed HTTP delivery does not advance the
phase, and an unreceived full snapshot causes the safe pair to repeat.

The exact QML polling path explains why the chained Auto response must remain
nonempty during that transition. In the `DeviceController.qml` compiled unit
(`qmlData` `0x5c3390`), `onAreSettingsFetchedChanged` (function 227, source lines
964-980) sets the next Settings interval to 5,000 ms after success, but doubles a
failed interval up to 60,000 ms. Its Settings timer handler (function 271, source
lines 1593-1595) calls `System::fetchSettings`. Native `Sync::fetchSettings`
completion (`0x20afdc`) immediately chains `fetchAutoModeSetings`; the latter's
completion (`0x20d080`) reports the combined fetch successful whenever the Auto
HTTP body is nonempty. During monitor resync, Nuve Local therefore arms one Auto
companion only after a reset or wake Settings body is delivered. It uses the exact
stored Auto revision plus object-valued bounds: the native fetch succeeds, while
the already-proven QML numeric-difference guards apply no Auto values. Failed
Settings delivery does not arm the companion, and a second Auto request receives
an empty response. This preserves the healthy five-second poll cadence without
replaying restored HVAC state or weakening the fresh-full-monitor control gate.

An active local schedule needs a distinct steady-state Settings response. In exact
`1.5.8` compiled `DeviceController.qml`, `getTemperatureForServer` (function 48,
source line 2355) starts with `device.requestedTemp`, then returns the synchronized
schedule maximum in Cool or minimum in Heat when no temperature hold is active.
`setDesiredTemperatureFromServer` (function 57, source line 2571) refuses a server
temperature under a version-1 schedule or a version-2 schedule without a temperature
hold. The whole response handler `onSettingsReady` (function 226) applies hold, fan,
and temperature fields before passing `schedule` and `schedule2` to their controllers.

Exact compiled `ScheduleControllerV2.qml` function 58,
`setSchedulesFromServer`, does preserve the local activity arrays when `schedule2`
is not an array, but it also sets `_isNeedFetchActivities` before returning. The
previous object-valued schedule sentinel was therefore not a pure no-op. Repeating
it could make subsequent Settings uploads alternate between `requestedTemp` and the
schedule projection while activities resynchronized. Exact native
`System::attemptToRunCommand` returns early for a repeated identical
`(command, command_time)` pair. Nuve Local consequently answers ordinary
active-schedule polls with one stable `push_live_data` pair plus the early
`hold_period` object trap and no temperature, mode, fan, system, `schedule`, or
`schedule2` fields. Whole-Settings commands are different: missing schedule fields
default to empty arrays in `onSettingsReady`, which erases local schedule state;
non-array sentinels preserve arrays but force an unsupported schedule-endpoint
refetch. Nuve Local therefore withdraws a queued Settings command if schedule state
activates before fetch and refuses every new Settings-family write unless a fresh
monitor proves `NoSchedule`. Monitor telemetry remains the authority for the
effective scheduled target.

`RestApiExecutor::callGetApi` stores callbacks by operation plus URL and suppresses
only an exact duplicate while that request is in flight; it is not a global network
lock. Its retry classifier returns false for no error, Qt errors 201 through 207,
and 299, and true for other errors, but does not schedule a retry itself. The owning
QML timer sets the actual five-second Settings success cadence and exponential
failure backoff. Each Settings GET has a 20-second transfer timeout and immediately
chains Auto. Separately, `/sync/client` is requested by the Mobile App/contractor
path on a 3,960,000 ms (66-minute) success interval and a 30-second failure interval;
it does not serialize or delay Settings traffic.

Observed pre-fix reference-unit timing matched that model: ordinary Settings-owned
commands completed in roughly 0.6 to 5 seconds, but a valid changed Auto upload was
compared to the previous baseline and unnecessarily revoked full-monitor authority.
The resulting two-poll resync kept the next command blocked for about 51 to 53
seconds. Nuve Local now treats only the exact queued Auto fields as a coherent
post-delivery echo, preserves monitor authority, and records a bounded value-free
timeline of polls, persistence, delivery, upload echoes, monitor confirmation,
completion latency, and control-block reason transitions. Unexpected sibling drift
still revokes authority. The release hardware pass confirmed consecutive Auto writes
from 20–23 to 20–24 and back in 8.49 and 11.10 seconds with both equipment stages at
zero, rather than the prior 51–53-second recovery path. A Home Assistant restart
remains separate: observed runs reached readiness in roughly 29 seconds and, during
the release pass, 37.7 seconds from loader discovery. Exact firmware still needs two
successful Settings polls to create the monitor publisher's false-to-true full-packet
transition; no safe single-poll equivalent was found, so this latency was measured
rather than hidden by weakening the fresh-monitor gate.

Temperatures and Auto bounds are Celsius, humidity is percent RH, and pressure is
hPa. Cooling stage is `0..2`; aggregate heating stage is `0..3`; fan is the actual
relay/output state rather than configured fan mode. The protocol has no independent
auxiliary-heat-active bit, so it cannot reliably distinguish compressor heat from
auxiliary heat.

A Home Assistant command is successful only after monitor telemetry received strictly
after actual delivery contains and matches the requested temperature, mode, or Auto
bounds. Before delivery, Nuve Local durably writes the command family, desired values,
revision floor, and an uncertainty journal with a null delivery boundary. The HTTP
body is then streamed while the transaction lock remains held. Only after the body is
sent is the actual server timestamp durably committed as the confirmation boundary.
Telemetry buffered before that boundary cannot confirm the command. Failure or
uncertainty after the body may have reached the thermostat keeps the journal and
latches control off. For monitor-visible temperature, mode, and Auto fields, a
matching JSON upload is not treated as a command acknowledgement; only newer
same-family monitor evidence can clear uncertainty. The firmware command
`push_live_data` is correlated by the exact `(command, command_time)` pair. Nuve Local
requires fresh monitor data after Home Assistant restarts before it will deliver
control.

Configured fan state has a different exact evidence path. Settings contains
`fan.mode` and `fan.workingPerHour`, but the monitor protocol exposes only the
physical fan output. Exact `1.5.8` Qt metadata maps `FMAuto=0`, `FMOn=1`, and
`FMOff=2`. Native `Scheme::setFan` at `0x1d6940` stores both fields; On with native
values 1 through 59 uses the circulation timer and 60 minutes is continuous. Nuve
Local exposes only the firmware/UI-supported range 10 through 60. The higher-level
paths include `SchemeDataProvider::setFan` at `0x1f20f0` and
`DeviceControllerCPP::setFan` at `0x26f1b4`.

The exact compiled `DeviceController.qml` unit (`qmlData` `0x5c3390`) adds a
cross-field precondition that the native setters alone do not reveal:

- `onSettingsReady` (function 226, source lines 928-929) calls
  `updateHoldServer(settings.hold, settings.hold_period)` before
  `updateFanServer(settings.fan)`;
- `updateFanServer` (function 30, source lines 1906-1920) returns early when a
  version-2 schedule and current activity exist but `isActiveHoldFan()` is false;
- `isActiveHoldFan` (compiled `ScheduleControllerV2.qml` function 74, source lines
  1263-1264) tests the `HTFan` bit, whose exact Qt value is `2`; and
- `AppSpec.qml` functions 2-5 (source lines 197-242) serialize hold entries as
  `<HoldType>: <HoldPeriod>`, join them with `; `, and recognize `TwoHours`,
  `FourHours`, `UntilNextActivity`, and `UntilChanged`.

The thermostat's Fan popup follows the same distinction: its Save handler updates
the fan directly only when no scheduled fan is authoritative; otherwise it opens
the version-2 hold flow, whose schedule controller owns the complete activity arrays.
Nuve Local cannot mirror that flow safely without implementing and validating those
schedule endpoints. It therefore emits a fan response only when a fresh monitor
proves `NoSchedule`. Confirmation requires a strictly post-delivery, complete
`/api/sync/update` upload to contain the requested whole `fan` object. Partial uploads
and the HTTP response cannot confirm it.

The reference unit's first Auto-to-On attempt fetched the command but its later
complete Settings upload remained `FMAuto` with an empty hold map. That is direct
live evidence of the recovered rejection gate, not evidence that the corrected
sequence has been physically validated. A later queued request timed out before an
authenticated Settings fetch, so no body was delivered and no device outcome was
created. A subsequent attempt was stopped even earlier by a local durable-journal
schema error before response delivery. These transport and persistence failures are
not device rejections and must not be combined with the first result. The corrected
no-schedule path was subsequently validated: the complete Settings upload confirmed
`FMOn` with a changed circulation duration and an empty uncertainty journal, and a
following setpoint command was confirmed before physical cooling began.

A later reversible active-schedule duty test disproved the proposed fan-hold response as
a safe integration boundary. The thermostat fetched the command, applied the duty
change, uploaded a complete fan object with an empty hold map, and changed its
schedule state to `NoSchedule`; the integration correctly classified the result as
different rather than confirmed. Both HVAC stages remained zero. After authority
recovered, one no-schedule command restored the original duty and was confirmed in
3.38 seconds. No retry was sent. The release consequently blocks all Settings-family
writes while schedule state is active or unknown.

The independent circulation timer cannot suppress the fan during cooling in the
exact `1.5.8` relay model. `Scheme::fanWork` (`0x1d68f0`) changes only the
circulation-request flag and asks for a normal relay send. `Relay::relays`
(`0x1ba3bc`) always calls `Relay::updateFan` (`0x1ba2fc`) before copying the output
set. That arbitration can select `G=off` only when the circulation and dissipation
requests are false, `Y1` is not on, and no applicable heat or accessory output
requires the fan. Both cooling stages set `Y1=on`. The optional sequential-output
path is also ordered safely: `changeStepsSorted` (`0x31e28c`) sorts `G=on` at
priority 2 before `Y1=on` at priority 3, and sorts `Y1=off` at -3 before `G=off`
at -2; the caller waits 500 ms between non-zero steps. The non-sequential path sends
the complete recomputed set in one TI packet. A full ARM text call-site scan found
only `Relay::relays` calling `Relay::updateFan` and no direct caller of the separate
`fanOFF`/`fanOn` helpers. This proves the commanded-relay invariant, not physical
airflow or blower health; TI fan status is not a tachometer or airflow switch.

## Display backlight, brightness, night mode, and LED preference

Exact `1.5.8` `Backlight.qml` compiled data (`qmlData` `0x5c2520`) defines the
persisted model: `on` defaults false, `hue` and `value` are normalized 0..1,
`shadeIndex` is 0..5 with 5 as free color, `_saturation` defaults 1.0, and the fixed
shade hue is `#FF8200`. For indices 0 through 4, rendering uses that fixed hue with
saturation `shadeIndex / 4`; index 5 uses the stored hue at full saturation. The
renderer preserves the saved `value`, caps the physical value at 0.3, and floors a
nonzero effective output at 0.05.

`BacklightPage` compiled data (`qmlData` `0x6d0a80`) defines the edit
contract. Save calls `updateBacklight(on, colorSlider.value,
brightnessSlider.value, selected index or 5)`, queues `EMBacklight`, and saves the
complete Settings state. Its five fixed buttons use `backgroundOrange10`, `30`,
`50`, `70`, and `100`; the free-color selection is index 5. Nuve Local maps the
exact persisted model to an HS light and exposes a separate six-way select so an
automation can retain every discrete firmware state rather than collapse it into
an approximate RGB value.

The general display settings are a separate complete object. `setSettingsServer`
maps `brightness_mode` directly to the adaptive flag; `pushToServer` serializes it
as integer 1/0. Native `setSettings` applies saved brightness/adaptive behavior and
`setLEDBlinkingEnabled` applies the HVAC activity-blink preference. That preference
is not monitor f12, which reports physical LED output.

Exact `1.5.8` compiled data and popup labels establish the two temperature-unit and
12/24-hour choices. The physical display confirmed raw `0` as Celsius
and raw `1` as Fahrenheit. Static meaning still does not make the whole-object write
path safe. Temperatures in the local protocol and Home Assistant remain Celsius.
The exact server-reply handler applies `timeFormat` and `setTimeAuto`, but does not
consume `currentTimezone` or `effectDst`; timezone instead has a ZIP-lookup side
effect. Those last two fields therefore have no direct control path in this protocol.

Speaker volume, sleep-mode logo, and `tofEnabled` are likewise members of the exact
14-field general Settings owner. Static shape alone does not prove safe independent
writes, especially because a whole Settings response replays HVAC and every sibling
preference. Nuve Local exposes only time format and `tofEnabled`, after the
independent live tests below.

The reference unit's disabled Vacation baseline can serialize its minimum as
`3.888888888888889` °C, the exact conversion of 39 °F. This value appeared in a
complete device-originated Settings upload during a pre-release device test and
is accepted at ingestion. It does not widen any Home Assistant command range or add
Vacation control; values below that exact firmware-emitted floor still fail closed.

The advanced-preference test then requested speaker 50→49 under fresh
NoSchedule authority with both stages zero. The request was delivered, but the later
complete Settings owner retained speaker 50. During the same test window the
target stepped from 21 to 20 and the raw temperature-unit value changed from `0`
(Celsius) to `1` (Fahrenheit). Speaker itself required no restoration. The operator
then restored Celsius/raw `0` and a 22 °C setpoint physically; two device-originated
canonical snapshots confirmed both values. Uncertainty reconciled from fresh
canonical state, persistence stayed healthy, and mode, fan, schedule, and stages
remained unchanged. Because the unrelated drift violated the stop condition,
temperature unit, time format, sleep-logo, and proximity writes were not attempted
in that pass.

A later pass separated the candidates. Time format `0→1→0` and proximity
`false→true→false` each changed only their intended complete Settings field while
Cool mode, a 22 °C target, fan On, NoSchedule, and idle stages stayed fixed. Both
original values were restored. Sleep-logo was rejected by the first complete owner.
Automatic clock was initially rejected but appeared Off in a later upload, proving
that it can apply after Home Assistant has already reported failure; it was restored
On. A temperature-unit `0→1` request initially preserved the 22 °C target, but a
later canonical sample moved the target to 20 °C and activated cooling, reproducing
the earlier unrelated-drift hazard. Celsius/raw `0` and the 22 °C target were
restored, with both stages idle. Speaker was not repeated after its earlier failed
owner and the reproduced drift. These outcomes qualify only time format and
proximity.

Night-mode QML rejects equal start/end times and represents overnight intervals by
adding 24 hours to the earlier end. Native `setNightModeSettings` stores enabled,
start, and end. The reference unit's complete Settings upload serializes those
minute-resolution values as `HH:MM:00`; the journal accepts that live form and the
short `HH:MM` form while comparing equality by minute. While active, `runNightMode`
selects an effective brightness of
`min(50, adaptive brightness when adaptive is enabled, otherwise saved brightness)`,
forces adaptive mode off and the backlight off during screen timeout, and restores
the saved brightness, adaptive flag, and backlight state on exit. The integration
therefore exposes only the proven enable and minute-resolution start/end controls;
it does not reimplement the device's scheduling or renderer.

All display writes remain single-family and non-optimistic. Runtime expands one
changed property against the complete canonical `backlight` or 14-field `settings`
object, preserves HVAC, fan, installer, and sibling preference state, and requires a
strictly post-delivery complete Settings upload to match the whole field-owning
object. Partial Settings uploads cannot confirm. A clamped/rejected full upload
resolves as state-changed, revokes monitor authority, and keeps the durable command
boundary fail-closed across restart.

The release hardware pass changed only `shadeIndex`, from the free-color state to a
fixed 75-percent-saturation shade and back. Both service calls completed after the
thermostat returned complete Settings uploads, the original shade was restored, and
the HVAC mode, target, fan configuration, schedule state, and installer-owned fields
did not change. The only non-backlight difference between adjacent complete uploads
was naturally sampled current humidity.

The same pass tested the general-Settings owner by changing saved
screen brightness from 52 to 53 and back. The complete 14-field uploads confirmed
the writes in 1.20 and 4.77 seconds, with durable commits under 10 ms and both HVAC
stages at zero. Persisted comparison found only `settings.brightness` plus naturally
sampled room observations on the outward write, and only `settings.brightness` on
restore.

`DeviceControllerCPP::setFanSpeed` at
`0x2586b0` is a separate low-level SIO hardware/test command. Nuve Local does not
expose it.

## Air-quality semantics

Board inspection identifies a Renesas ZMOD4410 indoor-air-quality/TVOC sensor and a
Sensirion SHT25 temperature/humidity sensor. The ZMOD4410 is not a carbon-monoxide
sensor. Full JSON, partial current-sensor JSON, and protobuf reports all expose the
same one-based categories `1..3`; protobuf `0` is `NONE`/missing. The recovered
protobuf exposes only `NONE` plus three category values; no
numeric ppm eCO2 field has been proven. The integration therefore exposes the exact
raw category as `No reading` or `Level 0..2` and does not invent direction labels,
carbon-monoxide readings, or eCO2 units.

## Control boundary

The firmware exactly maps desired `mode_id` values as Cool `1`, Heat `2`, Auto `3`,
Vacation `4`, Off `5`, and Emergency Heat `6`. Nuve Local currently writes only Cool,
Heat, Auto, and Off. Vacation, Emergency Heat, and unknown mode remain read-only.

Control also requires a complete device-originated settings baseline from the exact
allowlisted firmware; the exact preserved Technician Access URL and correction-model
version; an explicit no-update-active attestation; fresh authenticated polling; and a
fresh authoritative full-sync monitor record. The monitor record must contain target
temperature, target humidity, valid ordered Auto low/high bounds, mode, and system
type. Those values must agree with the stored settings, Auto, and equipment baselines.
HA-originated normal setpoints must lie from 18 to 30 degrees Celsius and
HA-originated Auto bounds from 4 to 32 degrees, both on whole-degree increments.
The exact Home QV4 plus/minus handlers add or subtract one from the active slider,
and the live reference thermostat uploads `temperatureUnit=0` while displaying
Celsius. The command boundary therefore uses the proven Celsius UI grid rather
than advertising unsupported half-degree values.
Device-originated starting values are less quantized: firmware configured in
Fahrenheit serializes its canonical-Celsius conversions as repeating decimals (for
example 74 F as about 23.333 C and 90 F as about 32.222 C). Those exact finite values
are preserved for mutation-free echo rather than rounded or rejected. Missing,
reversed, mismatched, stale, or partial authority fails closed.

The selected Home Assistant weather source must provide finite Celsius values. An
optional temperature sensor may override its current temperature; the weather entity
still supplies humidity, location, country, and daily forecast. Current temperature
must have been observed no more than 15 minutes earlier. Stale or unavailable input
makes the current-weather endpoint return HTTP 503, but does not block basic setpoint
or mode control. This separation prevents an unavailable display feed from disabling
HVAC control while still refusing to tell compressor/AUX lockout logic that invented
weather is current.

Exact `1.5.8` current-weather parsing consumes the standard nested OpenWeather shape:
`main.temp`, `main.temp_min`, `main.temp_max`, optional `main.humidity`,
`weather[0]`, `sys.country`, `name`, and `timezone`. The forecast parser consumes a
DevApi-wrapped `list` of up to seven dated rows with `dt`, `temp.day`, `temp.min`,
`temp.max`, optional humidity, and `weather[0]`. Nuve Local derives only validated
today/future daily data from Home Assistant, maps known conditions to allowlisted
OpenWeather icons, and fails missing values closed rather than emitting zero. Exact
QML renders the parser's first forecast-temperature slot in bold even though its
labels are visually high/low; the wire projection swaps only those two display slots
so the high is bold while canonical runtime data retains low <= high. A weather state
change schedules an immediate forecast refresh, while the normal refresh interval is
45 minutes. An empty list remains the only safe no-forecast response because an empty
row is marked valid before its optional fields are read.

The separate design-temperature response is a DevApi envelope containing Fahrenheit
`heating_temp` and `cooling_temp` values. Because no trustworthy local source has been
established, Nuve Local returns the firmware-proven non-applying `{"data":{}}`
response. It never derives those values from current weather.

## API-base and TLS behavior

The Home Assistant component itself does not modify thermostat firmware, bootloader,
fuses, or filesystem. A live local deployment does require the separate, operator-managed
API-base change described below. All three allowlisted application binaries consume
`API_SERVER_BASE_URL`, defaulting to `https://devapi.nuvehvac.com/`, and normalize a
missing trailing slash. This is an intentional configuration seam, not a binary-patch
proposal.

The full configured endpoint string is retained, including an explicit port.
`DevApiExecutor` only appends a missing trailing slash, and the route builders append
their `api/...` paths before passing the result to `QUrl`/`QNetworkRequest`. An
endpoint such as `https://nuve-local.example:18443/` is therefore supported by the
inspected `1.5.7.4` construction path; this does not waive ordinary certificate and
hostname verification.

A firewall test—not split DNS—accepted a self-signed certificate once; normal boot rejected it.

An operator may terminate that verified client TLS session at a local reverse
proxy. This is a network deployment choice, not thermostat protocol behavior. Nuve
Local's trusted-proxy profile accepts a plain HTTP upstream only from one configured
proxy peer, requires exactly one forwarded real thermostat IP, and still validates
serial, Host, route, method, and bearer token. The proxy-to-Home-Assistant path must
therefore be locally restricted by source and destination; it is not suitable across
an untrusted segment. An existing operator-controlled hostname may be reused on a
dedicated port because the recovered endpoint preserves that port and TLS
authenticates the proxy hostname separately from its backend. This avoids path-based
multiplexing on Home Assistant's normal `/api` namespace. Direct deployment remains
peer-IP-only and owns its TLS certificate in Home Assistant.

All three inspected startup implementations add an important precedence rule:
`NUVE::DeviceConfig` loads `/usr/local/bin/device_config.ini`, reads its root
`endpoint` value with the vendor URL as the default, then calls `qputenv` for
`API_SERVER_BASE_URL`. A systemd `Environment=API_SERVER_BASE_URL=...` line alone
would therefore be overwritten. The `1.6.1.1` initializer also sets
`READY_CONF=1`; future work must inspect the exact live unit and preserve the
initializer and complete existing INI state rather than replacing them wholesale.

The recovered applications use Qt 6.4's OpenSSL network backend. No
`ignoreSslErrors`, disabled-peer-verification, or application pinning bypass was
found. The recovered root filesystem contains the normal system CA bundle at
`/etc/ssl/certs/ca-certificates.crt`. The safest intended route is therefore a custom
hostname controlled by the operator, a matching publicly trusted certificate, and
local DNS to either the trusted reverse proxy or direct listener. Nuve Local does not
generate a self-signed fallback because an unmodified thermostat would not trust it.

## Recovery and persistent-device boundary

The public recovery manifest's compressed images were downloaded and verified against
both its sizes and MD5 values: `root.gz` is 247,571,818 bytes with MD5
`691ae1541f4d612ab8c4e0650527e66d`; `boot.gz` is 10,800,310 bytes with MD5
`c9f3352f9b45b67ec9c2af3632ab1ad1`. Their stronger local SHA-256 values appear in
the artifact table above. The decompressed root image is a clean ext4 filesystem, and
the boot image is FAT16 with `zImage` and `imx6sl-evk.dtb`.

The recovered OS identifies itself as `Stherm XWayland 1.0.0 (zeus)` and contains
application version `1.5.8`, Qt 6.4.0, OpenSSL 1.1.1g, and the
`4.14.98-imx+g4b55fef88af8` kernel image. Its exact `appStherm.service` starts
`/usr/local/bin/appStherm -platform linuxfb`, restarts on failure, and contains only
Qt framebuffer and library-path environment entries; it does not itself define the
API base.

The recovered U-Boot environment identifies boot, root, update, and recovery
partitions. Its `factory_restore` command loads `boot.gz` and `root.gz` from the
recovery partition and uses `gzwrite` to replace boot and root when a GPIO condition
is asserted. The physical trigger mapping was not tested. Recovery
therefore remains an operator-owned last resort, not a Home Assistant feature.

The FAT16 boot BPB declares more sectors than its MBR partition contains and extends
into the beginning of root. Even though the overlapping clusters are unused in the
factory image and the vendor sequence writes boot before root, a boot-only restore
could overwrite root. Preserve complete device configuration separately and never
treat a partial boot restore as safe.

Application update ZIPs contain only compressed application executables and are not
boot/root recovery media. The recovered update path downloads from an HTTP base URL
with a stable MD5-of-serial query identifier. It validates seven required metadata
members with weak type checking, applies contractor membership gates, and checks the
payload MD5 both before and after writing `/mnt/update/latestVersion/update.zip`.
The check detects corruption but supplies no publisher authenticity.

The application preflight uses strict greater-than free-space tests and may delete
logs, performance-test results, and prior update metadata. Its helper stops the app,
copies extracted files into `/usr/local/bin` in place, unconditionally deletes the
update source, attempts to restart the app, and exits zero without checking command
results. It has no staging rename, backup, A/B slot, or rollback; a masked failure
also defeats the helper unit's `Restart=on-failure`. The isolated model reproduces
the client DNS/fetch queues, notification/manual/server selection,
timer/retry gates, restart marker, and remaining interruption boundary. See
[application-update.md](application-update.md). Update authenticity and safe
application rollback is therefore absent from this update path.

The exact `RecoveryUpdater` is a second application-managed path. It downloads
manifest-selected payloads over HTTP into `/mnt/log/download/recovery`, validates
attacker-selected MD5, and copies verified filenames into p4 `/mnt/recovery/` with
`rsync --whole-file --inplace --remove-source-files`. The retained p4
`filesInfo.json` records exactly the matching `boot.gz` and `root.gz` pair described
above. Low staging space can erase `/usr/local/bin` contents before deleting logs,
download failure has no recovered retry budget, and a nonzero copy exit leaves the
in-process latch set. It does not directly write p1/p2; U-Boot consumes those p4
sources only on its later factory-restore branch. The exact planner, argv, cache,
cleanup, and completion model is in
[recovery-updater.md](recovery-updater.md). Real target-process and power-loss
outcomes remain unresolved.
Before applying a persistent API-base change, the operator still needs:

1. an exact, minimally scoped `device_config.ini` edit confirmed on that installed
   build, preserving all unrelated INI state and retaining a verified original;
2. a hostname and trusted certificate path proven from the thermostat before the
   endpoint is switched; and
3. a rollback path that remains available if the application,
   network, or root filesystem fails.

The contractor image is loaded as a PNG through Qt/QImage and aspect-fitted. Firmware
`1.5.7.4` and `1.5.8` write `/home/root/customIcon.png`; firmware `1.6.1.1` writes
`/usr/local/bin/customIcon.png`. The UI adds cache-busting behavior, and a later
contractor refresh can overwrite the file. Exact `1.5.8` accepts contractor metadata
from `/api/sync/getContractorInfo`, then downloads the returned image without
forwarding its bearer header. Nuve Local therefore validates a 750 by 375 RGBA PNG no
larger than one MiB and returns a purpose-specific HMAC URL bound to the paired token
fingerprint and serial. The normal Host, exact source, and serial checks still apply
to that otherwise unauthenticated stock download path.

Contractor brand and phone come from the metadata response. Settings `qr_url` controls
only the separate Technician Access popup. Nuve Local exposes that URL as a distinct
Home Assistant option, requires absolute HTTPS, and retains the captured value until a
canonical baseline exists. The Contact Contractor page uses the hard-coded,
serial-bound `contactContractorURL` described above and is not exposed as writable.

The recovered Send Log action collects the `appStherm` and `appStherm-update`
journals and transfers them to a vendor endpoint using authentication material
embedded in the firmware. Logs may contain thermostat state, device/network
identifiers, and other private data. Neither the credentials nor raw log output belong
in this repository or public diagnostics, and triggering the workflow is an external
disclosure rather than a read-only local action.

Reference-hardware validation proved the exact API-base seam, authenticated local
Settings/Auto/monitor/weather traffic, durable baseline capture, signed contractor
logo download, replacement wordmark rendering, and privacy-preserving event-queue
draining. The unchanged Contact Contractor QR exposed and corrected an earlier model:
that page is independent of the configurable Technician Access QR path.
This does not make a blind edit safe on a different firmware or storage state. The
deployment guide therefore keeps device backup, route activation, and rollback as
explicit operator boundaries.

## Claim ledger

| ID | Claim | Grade | Evidence | Current disposition |
| --- | --- | --- | --- | --- |
| ART-001 | Application and recovery archive identity | A+B | File hashes, 147-file archive ledger, 30,764-entry filesystem ledger, and a second extraction/hash run | Confirmed for firmware 1.5.8 |
| NAT-001 | First-party native inventory includes every selected function address | A+B | 48,220 defined symbols; 1,955 unique selected first-party function addresses; all 1,955 decompile after correcting the disposable `SIOPacket` type | Address coverage is complete; behavior is assessed per subsystem |
| QV4-001 | Embedded QV4 data is structurally decodable | A+B | Schema-4 inventory: 308 `qmlData` units, 8,988 QV4 functions, 102,236 instructions, 4,920 declarative objects, 25 enums, 2,349 properties, 108 signals, and 16,875 bindings decode with the matching Qt 6.4.0 header; private values are represented only by hashes; 1,701 direct AOT function symbols | Structural and per-function operation coverage is complete; subsystem behavior is graded separately |
| UI-001 | Every recognized QML event handler has an owner, trigger, operation map, effect domain, consequence, and Nuve Local decision | A+B | Hash-bound QV4 inventory, public register, and fixtures: 1,128 handlers in 198 units, comprising 947 bound expressions and 181 declared callbacks | 1,115 named-effect maps, nine effect-free stubs, one read/computation-only handler, and three reviewed diagnostic indexed-state writers; all 12 constructor actions resolve to `Date`; no dynamic or indexed target remains unknown |
| API-001 | The binary contains 38 API route strings and every route has a direct owner | A+B | Fresh raw-string count and read-only Ghidra `ListApiEndpointXrefs` run: 38/38 | Every route has an owner; contracts are assessed per route |
| API-002 | Message ingestion, device-alert upload, mobile identity, server forget, recovery-information report, manual Wi-Fi-off acknowledgement, and command-report callback/retry paths | A+B | Native owners/callbacks and QV4 consumers plus a private-value-free API emulator and 12 fixtures | Application contracts are understood; private and destructive routes remain unsupported except the restricted command acknowledgement |
| SET-001 | Settings envelope, field ownership, revision, command metadata, and initial-state capture | A+B+C+D | Native/QV4 paths, synthetic HTTP/runtime tests, authenticated uploads, and reversible device tests | Supported only through the existing fail-closed control path |
| MON-001 | Protobuf monitor framing, sparse/full merge, state transition, and confirmation ordering | A+B+C+D | Embedded descriptor, parser tests, authenticated monitor records, and reversible commands | Supported only for allowlisted fields |
| HVAC-001 | Cooling-stage thresholds and commanded fan-before-cooling relay order | A+B+C+D | `Scheme`/`Relay` paths, transition-order tests, read-only stage telemetry, and a cooling observation | Command order is confirmed; airflow is not sensed |
| DSP-001 | Backlight model and ownership of exposed display preferences | A+B+C+D | Backlight QV4/native consumers, tests, and reversible shade and brightness changes | Only tested fields are supported |
| WEA-001 | Current/forecast parser, card ordering, and empty design-temperature response | A+B+C | Parser/QV4 paths, deterministic fixtures, and physical page observation | Supported within validated input limits |
| SEN-001 | Published room temperature/humidity, categorical IAQ, pressure, and relay-stage producer chains | A+B+C | TI/nRF parsing and publishers, fixtures, and redacted read-only history | Published values are understood; board algorithms remain unavailable |
| SCH-001 | Missing/empty/non-array schedule values and Settings interaction | A+B+D | QV4 handler order, synthetic preservation tests, and the recorded active-schedule incident | Schedule writes remain disabled and Settings writes fail closed while a schedule may be active |
| SCH-002 | V2 routes, packet schema, response coercion, controller selection, activity limit/selection, retry timers, hold bit/period semantics, unreachable-with-current-callers `HPUnknow` default, and wrong-route V2 delete retry | A+B | Exact native/meta-call owners, AppSpec enums, exhaustive QV4 caller search, isolated schedule emulator, and independent fixtures | Statically understood bounded subset; wrong-route retry is a confirmed defect and schedules remain disabled for HA control |
| SCH-003 | V1 packet schema, Settings delivery, response id, preserve/clear behavior, id reconciliation, adjusted end boundary, overnight split, strict overlap, first-match activation gates, one-shot disable behavior including the midnight defect, destructive no-conversion migration, exact C-locale parsing, Halifax DST construction, and timezone change | A+B | Exact generic native transport, legacy/migration QV4 controllers, isolated V1 emulator, exact Qt 6.4 target-runtime probe, and independent fixtures | Core legacy application path understood; physical storage durability, vendor, and live boundaries remain U |
| PER-001 | QtQuickStream root graph, registered schedule references, primary/recovery paths, save debounce, load fallback order, serializer blacklist, duplicate/wrong-type/dangling behavior, populated target-runtime V1/V2/hold round trip, empty-activity hold clearing, and direct truncating writer | A+B | QV4/native paths, isolated persistence emulator, networkless ARM target-runtime harness, and a private result report without device values | Structural format and representative corruption behavior understood; physical power-loss durability remains unknown |
| LOCK-001 | Four-character local PIN gate, client prerequisite, user/master unlock, persisted state, screen-lock routes, response coercion, and retry backoff | A+B | Exact Lock/DeviceController/LockPage/UnlockPage QV4 plus native callback and isolated emulator | Core path understood but intentionally unsupported |
| SENSOR-002 | Remote-sensor QML model, disconnected pairing UI, public/private array split, inert native hooks, edit/remove behavior, and lossy Settings projection | A+B | Exact Sensor/SensorController/Add/Pair/Info QV4, native stub and route inventories, plus isolated sensor emulator | Exact application path understood and intentionally unsupported; board radio implementation remains unavailable |
| INST-001 | Installer model, install/address/customer/job/identity/wiring/warranty request and callback contracts, coercion, retry cadence, and persistence hazards | A+B | DeviceController/AppSpec/installer/warranty QV4, native Sync/RestApiExecutor owners and callbacks, plus an isolated installer emulator | Application path understood; Nuve Local does not expose it |
| PERF-001 | Performance-test scheduling/jitter, eligibility, UI postpone/lock behavior, result/persistence/retry contract, timers/samples, effective targets, and relay consequences | A+B | PerfTestService/DeviceController/Scheme/Relay paths, PerfTestPopup/MainView/schedule QV4, Qt 6.4 random implementation, plus isolated performance-test and logical-relay emulators | Application path understood; Nuve Local does not expose it because it can energize normal HVAC and accessory outputs |
| HW-001 | i.MX6 processor, memory, console, display/touch/backlight, eMMC/removable-media/Wi-Fi, PMIC, enabled/disabled buses, and application-to-secondary-controller topology | A+B | Exact-hash DTB and recovery filesystem plus complete read-only FDT parser, malformed-input/decoding tests, exact application device paths, constructor ownership, connection factories, and hash-bound installed-board photographs | Linux-side hardware topology understood; secondary board firmware and electrical design remain unavailable |
| HW-002 | Installed `HVAC021-C2-MAIN` component identities and visible debug/bus silk | A | Six exact private photographs with a mode-600 hash manifest plus manufacturer documentation: `MCIMX6L3DVN10AC`, `NT6TL256T32BQ-60`, `MMPF0100F1AEP`, `THGBMTG5D1LBAIL`, `N52832 QFAAE1`, `AP6256 SISO`, and `NAU88C22` | Exact visible identities and labels proven; no pad ownership, voltage, continuity, debug accessibility, firmware readout, or electrical behavior is inferred |
| BUS-001 | TI is `/dev/ttymxc3`/UART4, NRF is `/dev/ttymxc1`/UART2, both run 9600 8N1 without flow control, and HVAC/sensors cross those controller boundaries rather than direct i.MX6 GPIO/I2C | A | Exact `DeviceIOController` constructor, `createTIConnection`, `createNRF`, `UARTConnection::startConnection`, packet layout, DT aliases, and sysfs/device literals | Exact application-side bus ownership understood; physical transceivers and controller implementations remain U |
| GPIO-001 | GPIO21 is NRF data-ready, GPIO22 is ToF/luminosity-ready, both request falling edges, and the input-direction helper incorrectly writes `/usr/local/bin` instead of `in` | A | Exact constructor/callback xrefs and literal-pool resolution in `configurePins` and `exportGPIOPin` | Firmware defect established; restart/retained-direction behavior remains unresolved and is not relied on by Nuve Local |
| WDG-001 | TI UART heartbeat, 120-second NRF-data watchdog/heartbeat-disable chain, and i.MX6 watchdog hardware are three distinct paths | A | Exact `wtdExec`/`NRFWatchdog` native paths, DT watchdog nodes, exact systemd defaults and service unit, and recovery-root unit inventory | Linux-side behavior understood; TI-side reset effect and active SoC-watchdog policy remain U |
| SEC-001 | Recovery-root SSH activation/directives, credential classes, host-key generation, socket-unit exposure, and empty persistent iptables rules | A+B | Recovery filesystem plus an offline security inventory that omits secrets and tests that enforce that rule | Static root posture understood; live network/config drift remains unknown and Nuve Local does not require SSH |
| VER-001 | 1.5.7.4-to-1.5.8 binary identity, selected symbol/address changes, 38-route parity, complete QV4 unit diff, review of all four changed units, and six integration-critical byte-identical units | A+B | Both application binaries, QV4/symbol reports, Qt 6.4 translation decoder, hash-bound comparison tool that omits private values, and mismatch/diff/privacy fixtures | The changed QV4 behavior is understood: one metadata-only unit, one shared fan-control refactor with valid-boolean parity, and one documented null/default/presentation difference; native and missing-file gaps remain unknown |
| UPD-001 | Application metadata schemas, version ordering, staging visibility, contractor/forced selection, DNS/fetch queues, notification/manual/server selection, timers and retries, plaintext serial-derived URLs, MD5 checks, preflight, origin flags, helper unit, and in-place shell-install failures | A+B | `IUpdateStrategy`/`ClientSpecificUpdateStrategy`/`UpdateManager` paths, embedded resource/unit strings, updater emulator, and 45 fixtures | Application update behavior is understood and not exposed; it has no publisher authentication or transactional rollback |
| UPD-002 | Application-managed p4 recovery planner, cache trust, download routing, space accounting, destructive cleanup order, wget/rsync arguments, unlimited download retry, copy completion, and later p1/p2 restore boundary | A+B | `RecoveryUpdater`/`UpdateDescriptor` paths, p4 `filesInfo.json`, retained boot/root pair, recovery emulator, and 17 fixtures | Recovery-file behavior is understood and not exposed; it has no publisher authentication, transaction, or rollback |
| BOOT-001 | Boot/update/recovery branch and write order | A+B | Exact IVT/U-Boot region, byte-identical default environment, upstream command return semantics, offline branch model | Statically understood; no boot write is exposed |
| AUTH-001 | Application, recovery-file, and boot-partition update paths lack a cryptographic publisher-signature check | A+B | HTTP metadata/payload plus sender-selected MD5; IVT CSF pointer zero; raw zImage/ext4 payloads; U-Boot checks only file existence before `gzwrite` | Nuve Local does not expose update or recovery commands |
| LIVE-001 | Recorded pre-release reference deployment state | C+D | [Reference-thermostat validation history](live-validation-ledger.md), authenticated observations, and restored controls | Point-in-time evidence from 2026-08-10; see LIVE-U01 for current state |

## Unresolved claims that block broader support

The detailed register, including overlap and resolution state, is
[remaining-unknowns.md](remaining-unknowns.md).

| ID | Missing proof | Safety relevance | Required evidence |
| --- | --- | --- | --- |
| SCH-U01 | Filesystem/eMMC schedule and hold behavior during power loss, vendor conflict rules, and live restoration behavior | High for Settings writes; contained by the schedule safety gate and unsupported schedule routes | Fault-injected storage matching the photographed `THGBMTG5D1LBAIL`, its EXT_CSD and power-rail behavior, vendor conflict information, and an approved reversible device test only if still needed |
| LOCK-U01 | Server authorization, rate limits, audit, network-error parsing, brute-force resistance, and crash recovery | Medium/privacy | Isolated executor harness plus server information or an approved isolated backend test |
| SENSOR-U01 | Secondary-firmware radio pairing, identity, calibration, battery/signal ingestion, and vendor interpretation of the literal UID/lossy location projection | High if exposed | Board firmware/vendor protocol artifact; exact application-side CRUD path is closed as SENSOR-002 |
| INST-U01 | Vendor-server authorization, lookup correlation and rate limits, warranty transaction and rollback, and private-data audit and retention | High/privacy | Vendor information or an approved isolated service account; application-side schemas stay unsupported |
| PERF-U01 | Vendor-side eligibility policy/result interpretation and physical TI/controller/contact/equipment behavior | Critical | Vendor documentation or service implementation plus secondary-controller firmware/schematic; no connected-HVAC test is needed or authorized |
| BOOT-U01 | Physical identity/electrical polarity of GPIO102 and likely S7 control | Critical for reboot/recovery | Schematic or separately approved read-only physical correlation with HVAC isolated |
| BOOT-U02 | Power-loss behavior during `gzwrite`, second-read GPIO failure behavior on hardware, and end-to-end restore result | Critical | Cloned-media/emulated boot test; never use live eMMC for proof |
| UPD-U03 | Real unzip/rsync/systemd/process interruption, exact target-userland handling of the recovery copy's single `-n 19` argv element, filesystem durability, and power-loss outcomes after partial in-place replacement | Critical | Disposable cloned filesystem/service harness with target binaries and fault injection; never the connected thermostat |
| HW-U01 | Exact TI-side MCU/firmware, nRF52832 firmware, physical transceivers, schematic/BOM, terminal-driver electrical design, and TI heartbeat/reset behavior | Critical for hardware claims | Exact secondary firmware and schematic/BOM; isolated donor-board instrumentation only if separately approved |
| GPIO-U01 | GPIO21/22 exact pads/nets/pulls and fresh-boot versus already-exported behavior after the invalid direction write | Medium/availability | Schematic/kernel source plus cloned-kernel sysfs harness; no connected-HVAC fault injection |
| NRF-U01 | Exact secondary sensor/radio implementation: sensor variants, VL53L0X-family driver/library, optical geometry, algorithms, calibration, and pairing protocol | High | nRF52832 firmware, vendor protocol, and schematic/BOM; the photographed MCU identity plus application-side packets and feature strings cannot supply it |
| SEC-U01 | Current sockets/firewall/SSH drift, root-credential reuse beyond recovery 1.5.8 and the owned reference unit, vendor token lifecycle/authorization, and secondary-controller trust | Critical/security | Redacted per-image comparison, vendor information, cloned target boot, or approved read-only device checks; never publish verifier material or probe unrelated devices |
| VER-U02 | Broad native-body parity, complete clean 1.5.7.4 root/update, and currently absent 1.6.1.1 application/update | High for cross-version support | Hash-bound dual-project native comparison and reacquired exact artifacts; changed QV4 units are closed in VER-001 |
| PERSIST-U01 | Arbitrary combined nested-graph corruption, physical power-loss durability, external recovery intervention, and cross-version schema migration | High for restart recovery; representative graph/runtime behavior is already A+B and unsupported by Nuve Local | Fault-injected storage matching the photographed `THGBMTG5D1LBAIL` plus exact EXT_CSD/rail behavior; another complete exact-version artifact for migration; never the connected thermostat |
| WDG-U01 | TI-side heartbeat/reset effect and deployed i.MX6 watchdog arming policy | High/availability | TI firmware plus a cloned target harness or an approved read-only watchdog report without private values |
| LIVE-U01 | Present deployed state after later Home Assistant and network changes | High for present-tense live claims | Separate current-state read-only inspection; mutation manifest and explicit approval before any change |

No row above is converted to supported behavior merely because its endpoint or symbol
is known.

## Requirement traceability

These tables link safety requirements to firmware analysis, implementation, and tests.

### Evidence status

| Area | Firmware analysis | Reference-unit test | Limit |
| --- | --- | --- | --- |
| Settings, Auto, monitor, and restart resync | Exact endpoint owners, response handlers, monitor publisher transition, and complete symbol coverage | Repeated authenticated full uploads and fresh full monitor recovery after HA-only restarts; the release restart reached control-ready 37.7 seconds after loader discovery | Proven for the allowlisted reference firmware; restart still requires the safe two-poll transition, and a new hash requires revalidation |
| Setpoint and HVAC mode | Native/QML setters, whole-degree Home controls, and field-owning monitor confirmation | Reversible setpoint/mode changes and physical Cool-stage observation | Proven within the exposed modes/range; vacation and emergency heat remain read-only |
| Auto bounds | Exact Auto fetch/apply and monitor fields plus synthetic server tests | Reversible 20–23 to 20–24 to 20–23 reference-unit writes confirmed in 8.49 and 11.10 seconds while both stages stayed zero | The field-owning write path and consecutive-command fix are live-proven; bounds remain whole-degree Celsius only |
| Fan mode and circulation | Exact enums, QML scheduled-hold gate, hold-before-fan order, later schedule application, native circulation state machine, cooling/fan arbitration, transition priorities, and full Settings save | No-schedule fan On and changed duty confirmed by a complete Settings upload; an active-schedule duty attempt applied the fan then cleared the schedule, and the original duty was restored once under NoSchedule | Basic path and the commanded-relay cooling invariant are proven; active or unknown schedule authority blocks Settings-family writes, and relay status is not airflow proof |
| Display preferences | Backlight/BacklightPage/AppSpec/time-format QV4, native settings/night-mode/proximity consumers, complete Settings save, and field ownership | Existing display writes work; time format and proximity passed reversible tests, while sleep-logo, unit, automatic clock, and speaker did not | Time format and proximity are exposed; the other settings are not |
| Installer/HVAC configuration | Exact complete 36-field `system` constructor, validation, and serial binding | Current complete reference-unit system baseline populated every exposed field without a device write | Semantically proven non-private values are read-only disabled diagnostics; raw enums stay raw and no installer write exists |
| Repairs and health | Runtime safety-state ownership, persistence ordering, and schedule/monitor authority rules | Release validation checks deduplication, grace, clear, and persistent-condition behavior without creating live transient noise | Repairs describe conditions only; they never retry, restore, or broaden control authority |
| IAQ and pressure | NRF producer scales, category thresholds, pressure publisher, and official ZMOD4410 units | Redacted 1,800.8-hour history showing populated values, cadence, and sentinels | Categorical IAQ and positive hPa pressure are proven; numeric IAQ-family transport and board calibration metadata are not |
| Weather and forecast | Exact current/daily parsers and QML card ordering | Current and forecast page populated and corrected high-first cards visibly confirmed | Missing provider fields still fail closed rather than becoming fabricated values |
| Contractor metadata | Exact fetch, stock logo download, Settings `qr_url`, and both QR-page bytecode paths | Replacement wordmark rendered; the photographed Contact Contractor QR correctly remained unchanged | Branding is live-proven; Settings `qr_url` belongs to a separate Technician Access popup and cannot change the Contact Contractor page |

### Requirements

| Requirement | Evidence | Implementation | Regression proof |
| --- | --- | --- | --- |
| Never invent a starting device state | Native/QML whole Settings shape and limited bootstrap bridge | `protocol.py`, `runtime.py`, `storage.py` | `test_bootstrap_responses_are_minimal_and_do_not_contain_hvac_values`, `test_explicit_bootstrap_fetch_is_replaced_by_persisted_device_upload` |
| Preserve every installer field and serial binding | Complete 36-field system constructor | `protocol.py`, `storage.py` | `test_settings_upload_rejects_wrong_serial_missing_state_and_bad_types`, `test_storage_envelope_binds_serial_hashes_and_immutable_initial_capture` |
| Expose installer configuration without allowing installer changes | Complete system constructor plus validated field types and enum ranges | `sensor.py`, `binary_sensor.py`; every entity is diagnostic, read-only, and disabled by default | `test_installer_sensors_are_complete_read_only_diagnostics`, `test_installer_booleans_are_disabled_read_only_diagnostics` |
| Accept exact device-originated Fahrenheit conversion without adding command authority | Reference firmware emitted disabled-Vacation 39 °F as `3.888888888888889` °C | `const.py`, `protocol.py`; ingestion only, with Vacation still read-only | `test_settings_upload_rejects_wrong_serial_missing_state_and_bad_types` plus the Fahrenheit-derived Vacation bounds case in `test_settings_upload_validates_all_full_state_fields` |
| Persist before acknowledging state | Full/Auto upload call graph plus revision contract | `server.py`, `storage.py` | `test_full_upload_is_not_committed_or_acknowledged_when_persistence_fails`, `test_real_auto_upload_is_projected_and_persists_before_ack` |
| Reject pre-delivery command evidence | Exact monitor cadence and asynchronous fetch model | `runtime.py`, `server.py` | `test_pre_delivery_monitor_cannot_confirm_streamed_command`, `test_buffered_monitor_data_cannot_confirm_or_clear_a_delivered_command` |
| Recover post-restart control authority without replaying HVAC state | Empty-command monitor-off path, non-applying chained Auto fetch, healthy five-second retry cadence, and false-to-true `push_live_data` full-packet creation | `protocol.py`, `runtime.py`, `server.py` | `test_monitor_resync_responses_never_supply_desired_hvac_state`, `test_monitor_resync_retries_delivery_and_rotates_wake_command_time`, `test_restored_baseline_uses_two_http_polls_to_force_fresh_full_monitor` |
| Preserve a thermostat-owned schedule without target flapping, replaying schedule state, or accepting Settings or Auto writes | Exact schedule temperature projection/refusal paths; missing arrays erase; non-array `schedule2` requests activity refetch; repeated-command early return | `runtime.py`, `server.py` | `test_active_schedule_poll_uses_nonapplying_preservation_response`, `test_active_schedule_upload_does_not_replace_effective_monitor_target`, `test_settings_commands_fail_closed_while_schedule_active`, `test_auto_commands_fail_closed_without_confirmed_noschedule`, `test_settings_command_is_withdrawn_if_schedule_activates_before_fetch`, `test_auto_command_is_withdrawn_if_schedule_activates_before_fetch`, `test_settings_command_does_not_send_body_if_schedule_activates_during_persist`, `test_auto_command_does_not_send_body_if_schedule_activates_during_persist`, `test_real_http_active_schedule_poll_is_nonapplying_and_blocks_settings`, `test_real_http_auto_command_is_withdrawn_if_schedule_activates_before_fetch` |
| Keep the HA setpoint control stable without claiming premature confirmation | HA service lifecycle plus distinct requested, confirmed, and uncertainty states | `climate.py`, `runtime.py` | `test_climate_projects_requested_temperature_until_confirmation`, `test_climate_requested_temperature_reverts_after_undelivered_timeout` |
| Expose only the target model active in the current HVAC mode | Exact Home Assistant climate renderer prioritizes any non-null low/high range over the single setpoint | `climate.py` | `test_climate_exposes_only_the_active_mode_target_model` |
| Permit consecutive Settings and Auto commands without accepting an echo as confirmation | Exact queued-field post-delivery echo plus newer monitor confirmation | `runtime.py` | `test_consecutive_settings_commands_keep_full_authority_after_coherent_echo`, `test_consecutive_auto_commands_keep_full_authority_after_coherent_echo`, `test_post_delivery_settings_echo_with_unrelated_drift_revokes_authority` |
| Queue safely between thermostat Settings polls | A prior poll is not state authority; only the later authenticated fetch creates a delivery boundary | `runtime.py` | `test_command_timeout_distinguishes_not_delivered_from_uncertain` |
| Reconcile device-second monitor time with server-subsecond delivery | Protobuf Timestamp precision plus ordered post-delivery Settings echo and monitor receipt | `runtime.py` | `test_same_second_monitor_confirms_after_coherent_post_delivery_echo`, `test_same_second_monitor_without_post_delivery_echo_remains_unconfirmed`, `test_pre_delivery_monitor_cannot_confirm_streamed_command` |
| Report an existing uncertainty latch before generic readiness | Delivered-command safety state is more actionable than its downstream authority loss | `runtime.py`, `entity.py` | `test_uncertainty_error_wins_over_generic_readiness_failure` |
| Report actionable safety conditions without transient repair noise | Runtime owns unsupported firmware, canonical readiness, monitor freshness, persistence, uncertainty, and schedule authority | `repairs.py`, `diagnostics.py`, `__init__.py` | `test_repair_conditions_are_actionable_and_nonoverlapping`, `test_manager_deduplicates_clears_and_applies_schedule_grace`, `test_persistence_and_uncertainty_report_even_with_control_disabled` |
| Latch ambiguous delivery across restart | Network delivery can outlive response/journal failure | `runtime.py`, `storage.py` | `test_response_sender_disconnect_retains_write_ahead_uncertainty`, `test_uncertain_command_delivery_boundary_survives_validation` |
| Preserve newer device changes while confirming | Sparse monitor plus whole-family command model | `runtime.py` | `test_settings_confirmation_preserves_newer_device_state_and_delivery_payload`, `test_auto_confirmation_preserves_newer_bound_and_immutable_delivery` |
| Do not infer missing sparse monitor fields as zero | Proto3 optional descriptor and full/sparse packets | `protobuf.py`, `runtime.py` | `test_decode_monitor_payload_merges_incremental_records`, `test_full_monitor_sync_resets_missing_monitor_fields` |
| Do not expose or roll back stale room temperature | Home/Settings/current-sensors/monitor all consume QV4 `displayCurrentTemp`; cross-family delivery can be buffered | `runtime.py`, `server.py` | `test_private_baselines_restore_without_marking_device_available`, `test_room_temperature_uses_newest_observation_across_upload_families` |
| Do not infer idle equipment from HVAC mode alone | Output stages and fan are independent optional monitor fields | `climate.py` | `test_climate_does_not_infer_idle_from_mode_without_output_authority` |
| Report only proven IAQ/pressure semantics | NRF producer scaling, QV4 category thresholds, ZMOD4410 official units, one-hPa publisher, and zero sentinel | `sensor.py`, `protobuf.py` | `test_air_quality_sensor_preserves_unlabelled_firmware_categories`, `test_proven_diagnostic_telemetry_has_dedicated_sensors`, `test_out_of_range_promoted_value_remains_in_diagnostics` |
| Weather absence cannot disable basic HVAC control | Weather is a separate display/lockout fetch | `runtime.py`, `server.py` | `test_outdoor_weather_fails_closed_without_blocking_basic_hvac_control`, `test_weather_current_returns_only_observed_state_and_fails_stale` |
| Forecast uses exact parser shape and high-first card display | Current parser, daily parser, and WeatherPage QML | `weather.py`, `server.py`, `__init__.py` | `test_daily_forecast_is_converted_sorted_deduplicated_and_bounded`, `test_firmware_forecast_cards_project_high_before_low_without_mutating_cache`, `test_setup_uses_current_override_and_caches_daily_weather` |
| Contractor download cannot become a general unauthenticated file route | Stock downloader omits bearer header | `contractor.py`, `server.py`, `config_flow.py` | `test_contractor_metadata_uses_stock_download_contract`, `test_wrong_dimensions_or_color_mode_fail_closed` |
| Technician Access QR override cannot corrupt bootstrap capture | QML persists Settings `qr_url`; bootstrap requires the captured current value | `config_flow.py`, `runtime.py`, `server.py` | `test_technician_access_qr_url_requires_a_safe_absolute_https_url`, `test_full_settings_upload_pairs_without_query_and_drives_exact_echo`, `test_restored_baselines_require_post_start_full_control_telemetry` |
| Do not claim the Contact Contractor QR is configurable | Exact page bytecode reads the hard-coded serial-bound `contactContractorURL`, not Settings `qr_url` or contractor metadata `url` | UI label and documentation keep the two QR paths distinct; no unsupported write is exposed | Exhaustive exact-`1.5.8` QV4 lookup scan finds the Technician Access readers and Contact Contractor reader as separate paths |
| UI event targets never enter Home Assistant state | Exact `event.proto`; sender deletes queued files after transport success | `protobuf.py`, `server.py` | `test_decode_event_payload_validates_records_and_returns_only_count`, `test_monitor_event_upload_is_validated_and_discarded` |
| Fan controls preserve canonical mode, minutes, schedule authority, the pre-delivery journal, and field-owning confirmation | `FanMode`/`HoldType` Qt enums; QML hold-before-fan and later schedule-processing order; `Scheme::setFan` `0x1d6940`; monitor carries only physical fan output; full Settings save carries configured fan state | `climate.py`, `number.py`, `runtime.py`, `storage.py` | `test_real_http_fan_command_confirms_only_after_persisted_full_upload`, `test_uncertain_scheduled_fan_command_survives_validation`, `test_uncertain_fan_command_rejects_unproven_state`, `test_active_schedule_poll_uses_nonapplying_preservation_response`, `test_full_monitor_cannot_clear_restored_fan_uncertainty`, `test_fan_command_fails_closed_without_schedule_authority`, `test_settings_commands_fail_closed_while_schedule_active`, `test_climate_fan_mode_waits_for_post_delivery_settings_upload` |
| Display controls preserve complete field ownership and remain non-optimistic | Exact backlight renderer/save QV4; native adaptive, LED, and night-mode consumers; complete Settings upload owns both preference objects | `light.py`, `number.py`, `select.py`, `switch.py`, `time.py`, `runtime.py`, `storage.py` | `test_display_controls_are_confirmed_nonoptimistic_and_hvac_preserving`, `test_display_command_rejection_revokes_authority_and_does_not_use_partial_upload`, `test_uncertain_display_command_survives_validation`, `test_real_http_backlight_command_preserves_hvac_and_confirms_after_persistence` |
| Expose only advanced preferences that passed device tests | Handler analysis and reversible tests: time format and proximity round-tripped; speaker and sleep-logo did not apply cleanly, automatic clock applied late after rejection, and a unit change later moved the target and activated cooling | `select.py` and `switch.py` expose only time format and proximity; runtime rejects speaker, unit, sleep-logo, automatic clock, timezone, and DST | `test_display_controls_are_confirmed_nonoptimistic_and_hvac_preserving` plus `test_disqualified_advanced_preferences_remain_unexposed` |
| A circulation-duty expiry cannot command the fan off while cooling is commanded | `Scheme::fanWork` changes only the independent request; `Relay::updateFan` forces `G` for `Y1`; both cooling stages set `Y1`; staged priorities start `G` before `Y1` and stop `Y1` before `G`; the alternative path sends one complete set | Firmware-owned; HA can change only the complete fan pair and preserves the installer `system` object | Fan entity tests assert temperature, mode, and `system` remain at baseline; exact-binary decompile and whole-text call-site scan provide the relay proof |
| Do not expose the low-level fan-speed hardware command | `DeviceControllerCPP::setFanSpeed` `0x2586b0` is separate from Settings fan | No platform or server mapping | Field-matrix unsupported disposition plus fan command allowlist tests |
| Diagnostics cannot disclose raw household state | Settings includes Wi-Fi, identifiers, and contractor metadata | `diagnostics.py`; allowlisted diagnostic entities | `test_diagnostics_use_an_allowlist_and_drop_raw_protocol_maps`, `test_private_settings_diagnostics_expose_firmware_and_raw_strength_only` |
| Timing diagnostics cannot disclose protocol values | Root-cause analysis needs queue, delivery, persistence, echo, monitor, completion, block transitions, and private root-cause logging but not payloads | Size-limited `runtime.py` event trace without protocol values exposed through `diagnostics.py`; private persistence error log omits state values | `test_consecutive_auto_commands_keep_full_authority_after_coherent_echo`, `test_persistence_failure_logs_sanitized_root_cause`, `test_diagnostics_use_an_allowlist_and_drop_raw_protocol_maps` |
| Proxy headers are trusted only across the exact configured hop | Source and Host gate contract | `auth.py`, `server.py`, `config_flow.py` | `test_forwarded_source_is_trusted_only_from_one_exact_proxy`, `test_untrusted_peer_cannot_spoof_forwarded_address` |

The full field-by-field disposition is in [field-matrix.md](field-matrix.md).
The no-schedule fan mode and duty path is live-proven. Active-schedule hardware
evidence instead proves that whole Settings writes can clear the schedule, so the integration
withholds that entire command family until fresh monitor state reports NoSchedule.
The Contact Contractor QR has no proven writable API and remains unsupported.

## Function and QV4 inventory

This inventory measures structural coverage of the `appStherm` build above;
decompiling a function does not fully explain it.

### Native inventory

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

Class-prefix batches covered 1,949 of the 1,955 addresses; a final explicit address
pass covered the six nested lambdas whose demangled names escaped their owning class
prefix. The retained Ghidra project decompiles all 1,955 addresses. The original
`DeviceIOController::processNRFResponse` failure was caused by a one-byte imported
`STHERM::SIOPacket` placeholder. Copy sizes and ARM argument placement show that the
structure is `0x108` bytes. Correcting the type in a disposable copy allowed the
function to decompile without changing the retained project.

This proves address coverage, not that every branch has a final disposition.
Externally reachable, state-changing, persistent, hardware-facing, timer, callback,
and UI-entry functions still require an owner, contract, consequence, evidence
grade, and decision about whether Nuve Local should expose it.

### QV4 inventory

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

### Reproduction

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

### Current semantic boundary

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
