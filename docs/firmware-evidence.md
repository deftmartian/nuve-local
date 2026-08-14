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

The [evidence ledger](evidence-ledger.md) records whether each claim comes from static
analysis, reproduction, observation, a reversible test, or remains unresolved.

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

The broad class inventory contains 1,955 unique first-party function addresses after
deduplicating symbol aliases. Class-prefix batches covered 1,949; a final explicit
address pass covered the six nested lambdas whose demangled names escaped their
owning class prefix. All 1,955 decompiled without a remaining failure after the
disposable `SIOPacket` prototype repair described in the firmware-analysis skill.
This measures function coverage, not proof that every path or generated QML helper
has been semantically interpreted.

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
complete device-originated Settings upload during the v0.8 device test and
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
for v0.8.0.

The later v0.8.1 pass separated the candidates. Time format `0→1→0` and proximity
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
proximity for v0.8.1.

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
