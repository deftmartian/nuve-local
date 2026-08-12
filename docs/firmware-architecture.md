# Nuve Samo firmware architecture

This map covers recovery application `1.5.8`, SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
Addresses apply only to that hash.

The thermostat itself runs the HVAC state machine. The synchronization API supplies
settings and receives observations; it does not directly control equipment. Linux
owns the UI, policy, persistence, and networking, while separate TI and Nordic
controllers handle HVAC and sensor-side hardware over UART.

The structural review covers all 1,955 first-party executable functions and 1,128
recognized QV4 event handlers. That establishes coverage, not full semantic
understanding of every helper. Counts and reproduction details are in
[Function inventory](function-inventory.md) and
[UI action register](ui-action-register.md).

## System model

```text
 Local files and API responses
            |
            v
   QML state and DeviceControllerCPP <---- schedules, hold, vacation
            |
            v
      SchemeDataProvider             requested -> effective state
            |
            v
           Scheme                    HVAC modes, thresholds, timers
            |
            v
           Relay                     logical outputs and fan arbitration
            |
            v
    DeviceIOController <-----------> TI / NRF / GPIO hardware
            |
            +---- sensor data ----> correction and smoothing ----> QML display
            |                                      |
            |                                      +-----------> monitor protobuf
            |
            +---- relay state ----------------------------------> monitor protobuf

 NUVE::Sync / DevApiExecutor <----> local synchronization API
 ProtoDataManager             ----> sparse/full monitor and event uploads
 WeatherService              <---- current and forecast responses
```

The Linux application runs on an i.MX6 SoloLite and does not directly own the
HVAC terminals or raw room-sensor buses. It exchanges 9600-baud packet streams
with a TI-side HVAC controller over `/dev/ttymxc3` and an NRF-side sensor
controller over `/dev/ttymxc1`; GPIO21 and GPIO22 are receive-ready indications.
Display, touch, backlight, eMMC, Wi-Fi, watchdog, enabled/disabled interfaces, and
the GPIO direction defect are mapped in
[hardware-bus-map.md](hardware-bus-map.md). Hash-bound photographs of the installed
`HVAC021-C2-MAIN` additionally establish an nRF52832-QFAA, 4 GB
`THGBMTG5D1LBAIL` eMMC, AP6256 radio module, PF0100 PMIC, NAU88C22 codec, and
i.MX6/RAM markings. TI and nRF52832 firmware, pad ownership, and board electrical
behavior remain unknown.

Normal API traffic uses verified TLS, but update and recovery paths lack publisher
authentication and the recovery image enables root SSH. See
[Security and privacy](security-privacy.md).

## State is layered

The same concept can have several representations. Treating them as interchangeable
causes stale displays and unsafe confirmations.

| Layer | Owner | Examples | Meaning |
| --- | --- | --- | --- |
| Hardware input | `DeviceIOController`, TI/NRF | temperature, humidity, numeric IAQ family, pressure, relay feedback | Latest board and sensor observations |
| Processed room data | `DeviceControllerCPP` | corrected/smoothed temperature and humidity | Values used by the UI and control provider |
| Requested state | QML settings and full Settings sync | setpoint, mode, fan pair, complete backlight, display settings | Persisted operator/server intent |
| Effective state | `SchemeDataProvider` and `Scheme` | schedule-selected setpoint/fan, vacation mode, active thresholds | Intent after schedule, hold, vacation, and test-mode rules |
| Published telemetry | `LiveDataManager` and protobuf | current temperature, stages, fan output, full-sync marker | Change-filtered sparse deltas plus periodic full records |

Settings answers “what is configured.” Monitor telemetry answers “what the
controller is currently observing or driving.” A command must be confirmed from
the layer that actually contains that field.

## Startup and persistence

`main` (`0x4483c`) initializes the Qt application, hardware and display metadata,
QML engine, and root context. The native back end is registered with QML, then the
QML application owns most state assembly and orchestration.

`NUVE::DeviceConfig::load` (`0x34c3d0`) loads the device INI and
`NUVE::DeviceConfig::setEnv` (`0x34c2e4`) publishes the configured API base to the
process environment. This is why a service-unit environment override alone is not
authoritative. `DeviceInfo` owns runtime identity; Qt Quick Stream repository
classes persist the larger QML object graph.

A networkless ARM sandbox executes the application and Qt 6.4.0 libraries
from the verified read-only recovery image against synthetic identity and disposable
state. It reproduces default repository generation, populated V1/V2/hold restoration,
C-locale and Halifax time behavior, duplicate/wrong-type JSON handling, and the
no-enabled-V2-activity hold-clear rule. This strengthens the application-side model;
it does not emulate `THGBMTG5D1LBAIL` power-loss physics, TI/nRF52832 firmware,
or real HVAC outputs.

There are several independent persistence domains:

- device identity and API-base configuration;
- QML settings, schedules, hold, vacation, and UI preferences;
- Wi-Fi profiles and their recovery copies;
- queued monitor/event protobuf files; and
- updater and recovery state.

A whole-state sync response must preserve fields outside the requested mutation
because QML applies it across more than one persistence domain.

## Sensor and indoor-temperature path

`DeviceIOController` receives the board payload and emits `mainDataReady`.
`DeviceControllerCPP::setMainData` (`0x2659f4`) validates and normalizes it before
passing a main-data map to the rest of the application.

The temperature path is intentionally processed:

1. optional compensation is applied by
   `temperatureCompensationCorrection` (`0x265128`);
2. the ambient estimator accounts for display brightness and active relay load;
3. `mainDataSmoother` (`0x26e560`) averages successive samples; and
4. `calculateProcessedTemperature` (`0x264a20`) limits each processed transition
   to one degree Fahrenheit before converting back to Celsius.

Monitor publication is also change-filtered. `LiveDataManager::setCurrentTemperature`
(`0x2a9c94`) emits a sparse change at an absolute difference of at least `0.001`, while
`ProtoDataManager::setSendDataOnline` (`0x2baecc`) creates a full record on the
offline-to-online transition and the repeating full-record timer refreshes it
hourly.

The observed case where the thermostat displayed 22 C while Home Assistant still
showed 24 C was a consistency issue, not evidence for a fixed calibration offset.
Exact QV4 bytecode establishes that Home's temperature binding, Settings,
current-sensors, and monitor f4 all use the rounded `displayCurrentTemp` value
rather than separate calibration paths. The integration had restored an older
observational Settings value after Home Assistant restarted, allowing unrelated
authenticated traffic to make that stale value visible before newer temperature
telemetry arrived. Nuve Local now records temperature source time, rejects buffered
rollback across those upload families, and never promotes a persisted Settings
observation to live telemetry after restart. A synchronized physical capture can
still characterize normal transport latency, but it is not required to invent or
apply a temperature correction.

The same NRF response producer supplies `co2` as integer eCO2 ppm, `etoh` as a
hundredth-ppm ethanol-equivalent value, `Tvoc` as a thousandth-mg/m3 value, `iaq` as
a tenth-point standardized score, and `pressure` as integer hPa. These are already
processed board results, not raw ADC or resistance values. DeviceController converts
the IAQ score to only three published categories: below 2.9, 2.9 through 4, and
above 4. The numeric IAQ family has no recovered JSON/protobuf transport. Pressure
does reach monitor f7 through a one-hPa change filter, with zero representing no
usable reading on the reference unit. This boundary supports categorical IAQ and
positive hPa pressure, not invented numeric sensor entities.

## HVAC control path

`SchemeDataProvider` is the boundary between persisted/requested state and the
effective values used for control. It resolves schedules, hold state, vacation,
test mode, Auto bounds, outdoor conditions, and installer configuration.

`Scheme::run` (`0x1e74c8`) dispatches the effective mode into separate Off, Cool,
Heat, Auto, Vacation, and Emergency paths. Representative state-machine anchors
are:

| Behavior | Exact `1.5.8` anchor |
| --- | --- |
| Cooling state machine | `Scheme::CoolingLoop`, `0x1d9220` |
| Heating state machine | `Scheme::HeatingLoop`, `0x1e4400` |
| Auto mode selection | `Scheme::AutoModeLoop`, `0x1e515c` |
| Minimum-on enforcement | `coolingNotReachedMinOnTimeLoop`, `0x1cd634`; `heatingNotReachedMinOnTimeLoop`, `0x1cce84` |
| Compressor/AUX lockout decisions | `isCompressorHeatConditionMetWithLockout`, `0x1c242c`; `isAuxHeatLockedOut`, `0x1c24f0` |
| Relay delivery | `Scheme::sendRelays`, `0x1d53c8` |

### Cooling-stage selection

Cooling stages are equipment outputs, not alternate temperature setpoints.
`Relay::coolingStage1` (`0x1b9be4`) requests the first cooling output;
`Relay::coolingStage2` (`0x1b9f00`) retains that output and requests the second.
`Relay::currentCoolingStage` (`0x1ba498`) consequently reports 0 while no cooling
stage is active, 1 for the first output, and 2 for both outputs.

The ordinary-cooling selection policy is exact in the `1.5.8` state machine:

1. `Scheme::updateCoolingThresholdParameters` (`0x1c2294`) converts the installer
   `cool_deadband` from Celsius to Fahrenheit. That is the stage-1 threshold. The
   stage-2 threshold is exactly one Fahrenheit degree higher.
2. `Scheme::CoolingLoop` starts stage 1 when current temperature minus effective
   cooling target reaches the stage-1 threshold, subject to the normal system-run
   delay and state-machine guards.
3. `Scheme::internalCoolingLoopStage1` (`0x1d837c`) can enter stage 2 only when
   `system.coolStage == 2`. It escalates when the temperature gap reaches the
   stage-2 threshold or when stage 1 has run continuously for the hard-coded
   1,800,000 ms (30 minutes).
4. `Scheme::internalCoolingLoopStage2` (`0x1d7200`) drops ordinary cooling back to
   stage 1 once the gap returns to the stage-1 threshold or below. A hard-coded
   120-second guard prevents immediate stage-2 re-entry after that downshift.

The humidity-overcool branch has separate exit comparisons. Minimum-on time governs
when an active cooling call may end; it is not the ordinary stage-2 escalation
timer. Likewise, `systemRunDelay` delays initial equipment startup rather than
selecting stage 1 versus stage 2.

`Relay` turns those decisions into a complete logical relay set. Its fan output is
an arbitration result: a circulation request, heating/cooling stage, dissipation,
or an accessory may require the fan. “Fan Off” therefore does not mean the blower
may be suppressed while equipment requires it.

`DeviceIOController::sendRelays` (`0x336014`) serializes the logical set for the TI
controller. Responses update actual stage and fan status, which are the values
published to monitor telemetry.

### Equipment performance test

The equipment performance test is an alternate input to these ordinary control
loops, not a separate harmless diagnostic. While it is active,
`SchemeDataProvider::effectiveSystemMode` (`0x1f1768`) returns server-selected
Cooling or Heating and `effectiveTemperature` (`0x1f1828`) returns 40 °F or 90 °F.
`DeviceControllerCPP::doPerfTest` (`0x262ab0`) restarts both `Scheme` and
`HumidityScheme`; ordinary delays, stage escalation, compressor/AUX/dual-fuel
policy, O/B, fan arbitration, dissipation, and configured accessory behavior still
apply. A failed `running` result POST does not prevent this hardware path from
starting.

The complete application state machine, packet/persistence contract, UI gates,
timer/sample behavior, terminal layout, and stage-specific logical relay effects
are documented in [performance-test.md](performance-test.md). Nuve Local keeps both
performance-test endpoints unreachable.

## Fan behavior

The exact Qt meta-object maps `FMAuto=0`, `FMOn=1`, and `FMOff=2`. The configured
object always contains both `mode` and `workingPerHour`.

`SchemeDataProvider::setFan` (`0x1f20f0`) stores the requested pair and then derives
the effective pair. An active schedule can supply its own fan pair unless hold
state prevents that override. Home Assistant therefore exposes the configured fan
object, not an assertion that the physical blower must currently match it.

The server-facing QML adds an earlier schedule gate. `updateFanServer` (compiled
`DeviceController.qml` function 30, source lines 1906-1920) returns without calling
`updateFan` while a version-2 schedule is active and no fan hold exists. The full
Settings handler processes `hold_period` before `fan` (function 226, source lines
928-929). Exact Qt metadata identifies `HTFan=2`, and `AppSpec.qml` serializes the
hold map as `<HoldType>: <HoldPeriod>` pairs separated by `; `. That order alone is
not sufficient for a safe scheduled fan response: the same whole-Settings handler
later passes `schedule` and `schedule2` to both schedule controllers and then saves
the result.

Ordinary whole-Settings echoes are unsafe while that local schedule remains active.
`getTemperatureForServer` (compiled `DeviceController.qml` function 48) normally
starts from `requestedTemp`, but projects the active schedule's maximum in Cool or
minimum in Heat once version-2 activities are synchronized and no temperature hold
is active. Conversely, `setDesiredTemperatureFromServer` (function 57) refuses a
server temperature while a schedule owns it. `ScheduleControllerV2.qml`
`setSchedulesFromServer` (function 58) preserves its local arrays for a non-array
`schedule2` value but still sets `_isNeedFetchActivities`; it is therefore not a
side-effect-free sentinel. Nuve Local omits both schedule fields and all desired
HVAC state from normal active-schedule polls. It reuses a stable `push_live_data`
pair whose exact native dispatcher returns before monitor mutation when the pair is
unchanged. Empty schedule arrays erase local schedules; non-array values retain the
arrays but force a fetch from unsupported schedule endpoints. Because Nuve Local
does not own the exact schedule arrays, it withholds every Settings-family write
unless fresh monitor telemetry proves `NoSchedule`.

`Scheme::setFan` (`0x1d6940`) implements circulation:

- Auto does not request independent circulation;
- On with native values 1 through 59 uses the hourly circulation timers;
- On with 60 minutes requests continuous circulation; and
- Off removes the independent circulation request but cannot defeat equipment or
  accessory fan requirements.

The Home Assistant control intentionally exposes only the firmware/UI-supported
range of 10 through 60 whole minutes per hour.

## Display preference path

The backlight and general display settings are two separate field-owning objects in
the complete Settings state. `Backlight.qml` retains power, normalized hue/value,
and a six-way shade index. Indices 0 through 4 select fixed-hue saturation steps;
index 5 selects the stored hue at full saturation. Physical rendering caps effective
value above 0.3 and floors a nonzero output at 0.05 without changing the saved value.

The general settings object owns saved screen brightness, its manual/adaptive mode,
the HVAC LED blinking preference, and night-mode enabled/start/end alongside eight
unexposed sibling preferences. Night mode temporarily forces adaptive behavior and
backlight output off inside the configured interval, then restores the saved state.
It is not monitor f12 and does not change the HVAC relay model.

Nuve Local expands each exposed display edit into its complete owning object while
preserving every sibling and all HVAC/fan/installer state. The HTTP response is only
delivery. A strictly later complete Settings save must match the whole object before
the entity changes; a partial upload cannot confirm it. This same boundary drives the
durable uncertainty journal across restart.

The release reference-unit pass exercised the complete backlight owner by changing
the free-color shade to the fixed 75-percent-saturation shade and restoring it. Both
directions were confirmed by later complete Settings uploads; mode, target, fan,
schedule, and installer-owned state were preserved. The same pass exercised two
consecutive Auto-family writes, 20–23 to 20–24 and back, in 8.49 and 11.10 seconds
without revoking monitor authority or starting an equipment stage.

`Relay::updateFan` (`0x1ba2fc`) performs the final arbitration. The monitor protocol
contains only that physical output; it has no configured fan-mode or duty field.
Nuve Local consequently confirms a fan configuration only from a later complete
Settings upload containing the requested whole object. The first reference-unit
Auto-to-On attempt was transport-confirmed but
the later full upload remained Auto with no fan hold, matching the recovered QML
rejection path. A later corrected attempt exposed a local persistence-schema
mismatch: runtime added the required fan hold while the uncertainty journal still
rejected fan and hold fields. The response failed closed before its body was sent,
so no thermostat state changed. The journal now validates the same narrow
legacy recovery shape as runtime, with storage-backed end-to-end coverage. A later
no-schedule reference-unit run confirmed fan On and a changed circulation duration
in the complete Settings upload with an empty uncertainty journal. A bounded
active-schedule run then applied a requested duty change before the same handler
cleared the schedule; restoring the original duty under `NoSchedule` confirmed in a
later complete upload. This live result establishes the fail-closed schedule-state
gate for every Settings-family write.

### Cooling/fan safety invariant

The fan-duty timer changes only `Relay`'s independent circulation-request flag. It
does not write the `G` relay directly. Every normal relay snapshot passes through
`Relay::relays` (`0x1ba3bc`), which calls `Relay::updateFan` immediately before it
copies the complete relay set. `updateFan` permits `G` to be off only when every fan
reason is absent, including a check that the primary cooling output `Y1` is not on.
Both `Relay::coolingStage1` (`0x1b9be4`) and `Relay::coolingStage2` (`0x1b9f00`)
set `Y1` on. Consequently, expiry of an On/30 circulation window while cooling is
active clears the independent request but recomputes `G` as on.

The optional staged-output path preserves the invariant during transitions as well.
`STHERM::RelayConfigs::changeStepsSorted` (`0x31e28c`) assigns ascending on
priorities `G=2`, `Y1=3` and off priorities `Y1=-3`, `G=-2`; `Scheme::sendRelays`
applies each non-zero step in ascending order with 500 ms between updates. Thus `G`
is commanded before `Y1` on startup and `Y1` is removed before `G` on shutdown.
When staging is not used, the complete recomputed relay set is sent in one TI
controller packet. A whole-text call-site scan found no normal direct caller of
`Relay::fanOFF` or `Relay::fanOn`; `Relay::relays` is the only caller of
`Relay::updateFan`.

This is a firmware-level command invariant, not proof of airflow. TI-reported fan
status can corroborate the controller output, but it is not a blower tachometer or
airflow switch and cannot rule out a failed blower, control board, relay, or wiring.

## Synchronization and telemetry

`NUVE::Sync` constructs the thermostat's request set. `DevApiExecutor` and the HTTP
executors provide the common transport and unwrap the outer `data` envelope.
`DevApiExecutor::prepareJsonResponse` (`0x1a73c0`) is the key response boundary.

The main synchronization families are:

- complete desired-state fetch and complete device-state upload;
- separate device-preference and installer/system uploads;
- Auto bounds, schedules, lock state, weather, and contractor metadata; and
- monitor/event protobuf uploads.

The complete settings fetch is split after envelope removal: desired HVAC fields
are flat, while revision and command metadata live inside singular `setting`.
Complete device uploads use plural `settings`. The names are similar but the shapes
are not interchangeable.

`LiveDataManager` uses proto3 presence bits and change masks to build sparse
records. A full record marks all known monitor fields present. `ProtoDataManager`
queues live and event data, sends online changes, and retains file-backed data when
delivery is unavailable. This supports intermittent connectivity but means absence
in a sparse record is never zero.

The separate `EventList` descriptor carries a timestamp, one of three UI action
names, and an optional target string. Nuve Local validates the exact protobuf shape,
acknowledges it so the firmware can drain its retry queue, and discards targets
without logging, persistence, diagnostics, or entities.

## Weather and UI consumers

`WeatherService::fetchCurrentWeather` (`0x2d0130`) and
`fetchForecastWeather` (`0x2cfc2c`) use separate parsers and data models. The current
response supplies location, country, current/min/max temperature, humidity,
description, and icon. Forecast rows supply date, daily/min/max temperature,
humidity, description, and icon.

The generated Weather page QML renders the parser's first forecast-temperature
slot first and in bold. Nuve Local swaps only the two display slots on the wire so
the daily high is emphasized while its canonical Home Assistant forecast remains
ordered low <= high.

Weather is an input to display and outdoor-temperature-dependent control decisions,
but its temporary absence does not invalidate an otherwise authoritative HVAC
baseline. Missing current or design-temperature values are failed closed rather
than replaced with zero.

## Networking, update, and recovery

The network stack separates low-level `nmcli` process control from the QML-facing
`NetworkInterface`. The normal Qt/OpenSSL path performs peer and hostname
verification; no application-level certificate-error bypass was recovered.

Update selection is strategy-based (`UpdateManager`, `IUpdateStrategy`, legacy and
client-specific strategies) and is independent of the HVAC state machine. The
exact app path fetches metadata and payloads over HTTP with a stable MD5-of-serial
query identifier. Its seven-key version validator is weakly typed; contractor
exclusion/applicability gates selection. A downloaded archive is checked with MD5
in memory and after a write/read cycle. This detects ordinary corruption but is not
publisher authentication.

Version keys sort newest-first numerically. Normal/factory modes hide staged rows;
non-factory test mode admits them. Force selection uses exact contractor membership,
ignores the scalar `ForceUpdate` member in this client-specific strategy, and returns
the oldest qualifying forced row still newer than the installed version.

Install preflight uses strict free-space comparisons and can delete log/test/update
metadata files to make room. The helper then replaces `/usr/local/bin` content in
place, ignores individual command failures, cleans the source unconditionally, and
exits zero. There is no staging rename, backup, A/B slot, or rollback, and the
helper's `Restart=on-failure` cannot retry a masked zero exit.

The separate `RecoveryUpdater` stages manifest-named files under
`/mnt/log/download/recovery` and uses in-place, source-removing rsync to p4
`/mnt/recovery/`. Its p4 cache records `boot.gz` and `root.gz`, connecting this path
boundary to U-Boot's later factory restore. Download-space shortage first removes
the application-directory contents, then logs; failed downloads can immediately
retry without a recovered budget, while a nonzero copy exit leaves the in-process
latch set. It still does not directly write p1/p2. The high-level DNS/fetch queues,
notification/manual/server selection, timer/retry gates, and restart latch are
covered by an emulator; fault-injected filesystem and service outcomes remain open. Nuve
Local exposes neither update nor recovery commands. See
[application-update.md](application-update.md) and [recovery-updater.md](recovery-updater.md).

The endpoint inventory follows the same boundary. Ordinary sync, live telemetry,
weather, and contractor display paths are implemented narrowly. Server-owned
schedules and screen lock remain unsupported without complete baselines.
Installation, address/customer, performance-test, private identity/message/alert,
forget, recovery, external-service, and warranty paths are not exposed. Recognizing
an endpoint string is not enough to support its workflow. Their application-side
persistence and retry contracts are documented in
[messages-reset-api.md](messages-reset-api.md); being understood does not make them
safe to expose.

Monitor recovery is narrower than an HVAC command. Firmware always maps an
absent Settings command to monitor-off and maps `push_live_data` to monitor-on; only
the false-to-true transition queues a full monitor snapshot. After a server restart,
Nuve Local uses that two-poll transition with a QML-non-applying response envelope.
It never supplies thermostat desired state during the transition, so fresh control
authority can be rebuilt without replaying mode, temperature, fan, or installer
configuration.

Each resync Settings response arms one non-applying Auto companion for the chained
Auto fetch. The QML otherwise treats an empty Auto body as failure, doubles the
Settings retry interval up to 60 seconds, and delays the second half of the reset/wake
pair. The companion keeps the proven healthy five-second interval while leaving the
fresh full-monitor snapshot as the authority that re-enables writes.

Ordinary successful Settings polls run every five seconds; only failed combined
Settings/Auto cycles back off to 60 seconds. Duplicate in-flight GETs are
suppressed per operation and URL, not globally. The independent 66-minute
`/sync/client` fetch therefore does not explain control latency. A prior runtime bug
instead treated an expected changed Auto echo as canonical drift, revoked full
monitor authority, and imposed the two-poll resync before a following command.
Auto now receives the same field-by-field echo treatment as Settings. A size-limited
event trace without protocol values distinguishes queue, delivery, persistence,
confirmation, and block-reason timing.

Factory recovery is a separate bootloader/root-filesystem mechanism. It is not a
Home Assistant control path and is documented only as recovery evidence.

## Proven boundaries and open work

The architecture supports the current Nuve Local boundary:

- read and display monitor, settings, Auto, weather, and contractor state;
- mutate only whole, validated setpoint/mode/Auto/fan and display-preference state;
- confirm each command from a strictly newer authoritative source that actually
  carries that field; and
- leave schedules, lock, vacation writes, emergency heat, update, recovery, and
  low-level hardware/test commands unexposed.

Open evidence gaps are intentionally narrow:

- obtain physical schedule-durability/server-conflict and lock server-side
  authorization evidence before implementing them;
- model application/recovery in-place interruption only on a disposable cloned
  filesystem;
- do not infer design temperatures or transportable numeric IAQ values from
  application-internal fields; and
- re-run the complete exact-hash review for every newly supported firmware build.

See [firmware evidence](firmware-evidence.md) for the protocol-level proof and
[field matrix](field-matrix.md) for individual field ownership and confirmation
rules.
