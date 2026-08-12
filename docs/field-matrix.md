# Nuve Samo 1.5.8 field matrix

This matrix maps firmware fields to Home Assistant for `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
Other builds are not assumed compatible.

Codes: **N** normal entity, **C** configuration, **D** diagnostic, **RO** read-only,
**U** unsupported, and **H** hidden protocol state. **Off** means the entity is
disabled by default. Cadence: **M** monitor, **S** Settings, **P** partial upload,
**W** Home Assistant weather, and **Static** setup or firmware data. Settings, Auto,
revision floors, and uncertain commands are saved privately; monitor and weather
caches are runtime-only.

Only one command may be active. Temperature, mode, and Auto changes need newer
monitor data. Fan and display changes need a later complete Settings upload. HTTP
success or a partial upload does not confirm a change.

## Monitor and partial live state

| Firmware source / field | Contract | Cadence / persistence | HA disposition / default | Write / confirmation | Remaining risk |
| --- | --- | --- | --- | --- | --- |
| Protobuf timestamp | UTC seconds; absent allowed | M / runtime | Used for freshness, H | None | Device clock skew bounded at command confirmation |
| f2 `set_temperature` | float °C, accepted -50..100; HA writes whole values 18..30 | M; merged to Settings | climate target + sensor, N | Settings `temp`; newer monitor | Home QV4 changes its selected slider by exactly one display unit; Fahrenheit-derived device values retain precision |
| f3 `set_humidity` | float %RH, 0..100 | M; merged to Settings | target humidity sensor, N/RO | U | No proven HA write UX |
| f4 `current_temperature_embedded` | float °C, -50..100 | M / runtime | climate current + sensor, N | None | Same rounded `displayCurrentTemp` source as Settings and current-sensors; source time prevents buffered rollback |
| f5 `current_humidity_embedded` | float %RH, 0..100 | M / runtime | current humidity sensor, N | None | None known |
| f6 `current_temperature_MCU` | float °C, -50..150 | M / runtime | controller temperature, D/Off | None | Board location, not room temperature |
| f7 `airPressureHPa` | float hPa, 300..1200; producer integer hPa; zero unavailable | M / runtime | air pressure sensor, N | None | Sea-level correction not proven; the reference unit currently supplies zero |
| f8 IAQ enum | 0 none; 1 when score <2.9; 2 for 2.9..4; 3 when >4 | M / runtime | neutral IAQ enum, N | None | Numeric score/eCO2/TVOC are not transported and remain unexposed |
| f9 cooling stage | integer 0..2: 0 idle, 1 first output, 2 first plus second output | M / runtime | stage sensor, D | None | Never interpret a missing sparse field as zero |
| f10 aggregate heating stage | integer 0..3 | M / runtime | stage sensor, D | None | No separate AUX-active bit |
| f11 fan output | integer 0/1 on wire, boolean state | M / runtime | fan-active binary sensor, N | None | Output is not configured fan mode |
| f12 status LED output | integer 0/1 | M / runtime | status LED binary sensor, D/Off | None | Not screen backlight or blink preference |
| f13 full-sync flag | integer 0/1 | M / runtime authority | monitor/canonical readiness, D/Off | None | Repeated `push_live_data` does not force another full packet |
| f14 system type | enum 0 none, 1 traditional, 2 heat pump, 3 cool-only, 4 heat-only, 5 dual fuel | M; compared with Settings | equipment type sensor, D | U | Installer write dependencies not proven |
| f15 system mode | enum 0 none, 1 cool, 2 heat, 3 auto, 4 vacation, 5 off, 6 emergency heat | M; merged to Settings | climate mode/action, N | Settings `mode_id` for 1/2/3/5; newer monitor | Vacation/emergency heat RO |
| f16 reported online | integer 0/1 | M / runtime | connectivity binary sensor, D | None | Authenticated contact is separate reachability evidence |
| f17/f18 Auto low/high | float °C; device 4..33, HA whole values 4..32; low < high | M + Auto / Store | Auto sensors Off + climate range, N | Auto GET; newer monitor; reversible consecutive writes live-confirmed | Mode string/is_active are upload-only corroboration |
| f19 schedule type | 0 sleep, 1 wake, 2 home, 3 away, 8 hold, 9 none | M / runtime | schedule enum + hold binary, N | U | Schedule CRUD contract not implemented |
| `/device/current-sensors.current_temp` | numeric/string upload; response must be string | P / runtime | same current temperature, H duplicate | None | Request/response type asymmetry is exact; server receipt time is retained as provenance |
| `/device/current-sensors.current_humidity` | numeric/string upload; response must be string | P / runtime | same humidity, H duplicate | None | Request/response type asymmetry is exact |
| `/device/current-sensors.co2_id` | integer 1..3 category | P / runtime | same neutral IAQ category, H duplicate | None | Not CO, CO2 ppm, or eCO2 ppm |
| `/device/current-stages.*` | numeric fan 0/1, heat 0..3, cool 0..2 | P / runtime | same output/stage entities, H duplicate | None | Numeric JSON, not booleans |
| last authenticated contact | server timestamp | each accepted request / runtime | last-seen + connectivity, N/D | None | Does not establish complete monitor authority |

## Desired state, preferences, and server-owned fields

| Settings upload / response field | Contract | Cadence / persistence | HA disposition / default | Write / confirmation | Remaining risk |
| --- | --- | --- | --- | --- | --- |
| `sn` | string identifier, exact match | S / Store | H | Never | Private identifier |
| `temp` | finite °C, device 4..33; during an active schedule the upload may alternate between `requestedTemp` and the schedule projection | S / Store | climate target, N | Implemented; newer monitor remains effective-target authority during schedules | Normal HA command range intentionally narrower |
| `humidity` | finite %RH 0..100 | S / Store | target humidity, N/RO | U | No proven control UX |
| `current_temp`, `current_humidity`, `co2_id` | observational duplicates | S / Store | H | Never echoed as control evidence | Excluded from canonical-echo comparison; persisted room values are not restored as live telemetry |
| `hold` | bool | S / Store | hold binary, N/RO | U | Server schedule semantics incomplete |
| `hold_period` | `<HoldType>: <HoldPeriod>` pairs joined by `; `; `HTFan=2` | S / Store | H | Never synthesized for new writes | General hold UX, schedule preservation, and expiry control remain unsupported |
| `mode_id` | enum 1..6 as above | S / Store | climate, N | 1/2/3/5 implemented; newer monitor | 4/6 RO |
| `fan.mode` | Qt `FMAuto=0`, `FMOn=1`, `FMOff=2` | S / Store | climate fan mode, C only with proven NoSchedule | Post-GET full upload | No-schedule Auto-to-On is live-confirmed; active or unknown schedule authority fails closed before delivery |
| `fan.workingPerHour` | integer 10..60 min/hour; mode 1 cycles, 60 is continuous | S / Store | number 10..60, C only with proven NoSchedule | Same complete-upload confirmation | A changed no-schedule duty is live-confirmed; active or unknown schedule authority fails closed before delivery |
| `backlight.on` | bool | S / Store | backlight light, N | Complete post-GET upload of all four backlight fields | Must not be confused with status LED |
| `backlight.hue` | real 0..1 | S / Store | backlight HS color, N | Same full-backlight path | Used only by free-color shade index 5 |
| `backlight.value` | real 0..1 | S / Store | backlight brightness, N | Same full-backlight path | Saved value is preserved; renderer caps physical value above 0.3 and floors nonzero output at 0.05 |
| `backlight.shadeIndex` | integer 0..5 | S / Store | six-way shade select, C | Same full-backlight path; reversible fixed/free shade pair live-confirmed | Indices 0..4 use fixed hue with saturation 0/25/50/75/100%; 5 uses free hue at full saturation |
| `settings.brightness` | integer 0..100 | S/P / Store | display-brightness number, C | Complete post-GET upload of all 14 settings fields; reversible 52→53→52 write live-confirmed | Saved screen brightness; distinct from backlight value |
| `settings.brightness_mode` | integer 0/1, response projected to bool | S/P / Store | manual/adaptive select, C | Same full-settings path | Native setter receives the adaptive flag directly |
| `settings.speaker` | integer 0..100 | S/P / Store | RO | U; a 50→49 request was not applied | The same test window produced unrelated target/unit drift, so no entity is exposed |
| `settings.temperatureUnit` | integer 0/1; QV4 labels and the live physical display confirm 0 Celsius, 1 Fahrenheit on firmware 1.5.8 | S/P / Store | RO | D-negative | A 0→1 test later moved the target from 22 to 20 °C and activated cooling; Celsius/raw 0 and 22 °C were restored |
| `settings.timeFormat` | integer 0/1; QV4 enum 12-hour/24-hour | S/P / Store | 12/24-hour select, D | Complete Settings owner; reversible 0→1→0 live-confirmed with unrelated state unchanged | Timezone and clock source are not exposed |
| `settings.currentTimezone` | string | S/P / Store | RO | Static negative | Exact `setSettingsServer` does not consume this field; ZIP lookup owns automatic timezone mutation |
| `settings.effectDst` | bool | S/P / Store | RO | Static negative | Exact server-reply handler does not apply this field |
| `settings.sleepModeLogo` | bool | S/P / Store | RO | D-negative | The request was rejected by the first complete owner and the value remained unchanged |
| `settings.tofEnabled` | bool | S/P / Store | proximity switch, D | Complete Settings owner; reversible false→true→false live-confirmed with unrelated state unchanged | Range/distance data remain unexposed |
| `settings.ledBlinkingEnabled` | bool | S/P / Store | HVAC LED blinking switch, C | Same full-settings path | Preference, not physical output field f12 |
| `settings.setTimeAuto` | bool | S/P / Store | RO | D-negative | First owner rejected Off, then a later upload showed delayed application; original On state was restored |
| `settings.nightModeEnabled` | bool | S/P / Store | night-mode switch, C | Same full-settings path | Temporarily forces adaptive off and backlight off during the interval |
| `settings.nightModeStart`, `nightModeEnd` | minute values serialized as `HH:MM` or live `HH:MM:00`, unequal by minute; overnight allowed | S/P / Store | start/end time entities, C | Same full-settings path; HA emits the live `HH:MM:00` shape | Effective brightness is `min(50, saved adaptive value or saved manual brightness)`; saved state is restored on exit |
| `setting.tempCorrectionVersion` | exact metadata integer; 1.5.8 permits 1 or 2 | Settings GET / config | H safety gate | Never guessed or changed | Absent from upload; operator must verify |
| `setting.last_update` | UTC `yyyy-MM-dd HH:mm:ss`, strictly monotonic | each response / Store floor | H | Protocol revision | Second resolution requires monotonic increment |
| `setting.command`, `command_time` | empty reset or paired `push_live_data` plus fresh time | Settings GET / Store | H | Internal monitor resync only | Exact false-to-true publisher transition forces a full snapshot; neither response contains HVAC desired state |
| Auto `is_active`, `mode` | bool + named mode string | Auto upload / not canonical | RO corroboration | U | Auto response consumes only low/high |
| `sensors[]` name/location/type/uid | upload maps location 0 to Office and every other enum to Bedroom; type 0 to OnBoard and every other value to Wireless; literal uid `213137` | S / Store | H/unsupported | Never | Exact 1.5.8 pairing is disconnected, server rows are ignored, runtime rows are not persisted, and remove can target the wrong array index; see `remote-sensors.md` |
| `messages[]` | rows require `message_id`, `message`, `created`, `type`; server `is_read` is overwritten false before local preference gates; newest-first limit 50 | S / Store | H/unsupported | Never; see [messages-reset-api.md](messages-reset-api.md) | Rendered private content and whole-repository persistence; dedicated messages GET discards its body |
| `schedule`, `schedule2` | server-owned arrays, absent from upload | Settings GET | U; omitted from active-schedule preservation responses | U | Empty arrays erase local schedules; non-array `schedule2` preserves arrays but marks activities for refetch and is not a pure no-op |
| `locked`, `pin` | server-owned, absent from upload | Settings GET | U/H | U | PIN is private; lock contract incomplete |
| `vacation.min_humidity` | real 20..50 %RH | S / Store | RO | U | Must remain at least 20 below max |
| `vacation.max_humidity` | real 40..70 %RH | S / Store | RO | U | Paired validation required |
| `vacation.min_temp`, `max_temp` | real °C; device-originated lower bound includes exact 39 °F conversion 3.888… °C, upper ingestion bound 33 °C; min < max | S / Store | RO | U | Vacation mode/write contract deferred; HA exposes no Vacation write |
| `vacation.is_enable` | upload string `t`/`f`; response bool | S / Store | RO | U | Exact representation conversion required |
| `firmware.firmware-version` | string installed version | S / Store | firmware sensor, D/Off | Never | Not an update instruction |
| firmware/update instruction | distinct updater/server path; app and recovery metadata/payloads use plaintext HTTP plus MD5 | H/unsupported | Never | No publisher signature, transaction, rollback, or safe HA control; client and p4 recovery orchestration are modeled, but real interruption remains unresolved |

## Installer/system fields

All fields below come from the complete `system` object shared by full Settings and
`/api/device/system`. Nuve Local saves the object as received and requires fresh
monitor data after it changes. Understood, non-private fields appear as read-only
diagnostics that are disabled by default. Integer enums remain numeric when their
labels are unclear, and installer settings cannot be changed.

| Field | Type / unit / range or enum | HA disposition | Write / confirmation | Remaining dependency or risk |
| --- | --- | --- | --- | --- |
| `sn` | exact string identifier | H | Never | Private identifier |
| `type` | traditional, heat_pump, cooling, heating, dual_fuel_heating | D/Off, RO | Never | Equipment topology and rollback |
| `coolStage` | integer 1..2; installed-stage capability gate | D/Off, RO | Never | Stage 2 is reachable only when this is 2; wiring/equipment dependency |
| `heatStage` | integer 1..3 | D/Off, RO | Never | Wiring/equipment dependency |
| `heatPumpOBState` | integer 0/1 | D raw/Off, RO | Never | No guessed O/B label; polarity can cause unsafe operation |
| `heatPumpEmergency` | bool | D/Off, RO | Never | Emergency behavior dependency |
| `systemRunDelay` | integer 1, 2, or 5 minutes | D/Off, RO | Never | Compressor timing |
| `dualFuelThreshold` | real °C -32..19 | D/Off, RO | Never | Outdoor/design dependency |
| `isAUXAuto` | bool | D/Off, RO | Never | AUX policy |
| `dualFuelManualHeating` | enum 0..2 | D raw/Off, RO | Never | Labels/control path incomplete |
| `dualFuelHeatingModeDefault` | enum 0..2 | D raw/Off, RO | Never | Labels/control path incomplete |
| `emergencyMinimumTime` | integer 2..5 minutes | D/Off, RO | Never | Emergency heat behavior |
| `auxiliaryHeating` | bool | D/Off, RO | Never | AUX equipment dependency |
| `useAuxiliaryParallelHeatPump` | bool | D/Off, RO | Never | Simultaneous equipment risk |
| `driveAux1AndETogether` | bool | D/Off, RO | Never | Terminal dependency |
| `driveAuxAsEmergency` | bool | D/Off, RO | Never | Terminal dependency |
| `runFanWithAuxiliary` | bool | D/Off, RO | Never | Airflow/equipment dependency |
| `turnAuxOnUnreaching` | integer 15/30/45/60 minutes | D/Off, RO | Never | AUX escalation behavior |
| `thermostatControlFan` | bool | D/Off, RO | Never | Furnace versus thermostat fan control |
| `tempCorrection` | real °C -4..4 | D/Off, RO | Never | Distinct from correction-model version |
| `heatingControlByFurnace` | bool | D/Off, RO | Never | Furnace dependency |
| `compressorLockout` | bool | D/Off, RO | Never | Outdoor/design dependency |
| `overcool` | real °C 0..3 | D/Off, RO | Never | Humidity/control interaction |
| `diffToEngageAux` | real °C 1..5 | D/Off, RO | Never | Current verified installation remains unchanged |
| `heat_dissipation_time` | real minutes 0..15 | D/Off, RO | Never | Fan timing |
| `cool_dissipation_time` | real minutes 0..15 | D/Off, RO | Never | Fan timing |
| `fanWithAccessory` | bool | D/Off, RO | Never | Accessory dependency |
| `systemAccessories.wire` | T1PWRD, T1Short, T2PWRD, None | D raw/Off, RO | Never | Wiring dependency |
| `systemAccessories.mode` | integer 0..2 | D raw/Off, RO | Never | Enum labels/accessory behavior incomplete |
| `heat_deadband` | real °C 0.5..2.3 | D/Off, RO | Never | Cycling behavior |
| `cool_deadband` | real °C 0.5..2.3 | D/Off, RO | Never | Ordinary stage 1 begins at this gap; stage 2 threshold is another 1 °F (5/9 °C) above it |
| `aux_lockout` | bool | D/Off, RO | Never | Outdoor/AUX policy |
| `aux_lockout_threshold` | real °C -18..27 | D/Off, RO | Never | Outdoor/AUX policy |
| `wifiName` | string SSID | H | Never | Private; excluded from entities/diagnostics |
| `wifiStrength` | dynamic string | D raw sensor/Off | Never | Unit/scale not normalized; only drift is proven |
| `heat_min_on_time` | real minutes 0..20 | D/Off, RO | Never | Cycling behavior; do not impose generic defaults |
| `cool_min_on_time` | real minutes 0..20 | D/Off, RO | Never | Cycling behavior; do not impose generic defaults |

## Weather, contractor, runtime, and unresolved internal fields

| Source / field | Contract and cadence | HA disposition | Write / confirmation | Remaining risk |
| --- | --- | --- | --- | --- |
| current outdoor temperature | override sensor, else weather entity; finite °C; max age 15 min | input only + freshness D/Off | HA source event | Never emit missing as 0 |
| current outdoor humidity | weather humidity fallback, 0..100 %RH | input only | HA source event | Override temperature sensor may not carry humidity |
| weather location/country/timezone | concise weather entity name; ISO country; seconds east UTC | input only | HA source event | Firmware truncates long titles |
| current `main.temp_min/max` | validated today's low/high; missing elapsed bound uses current observation | input only | W cache | Bound fallback is observed, not a historical extreme |
| current/forecast `weather[0]` | allowlisted OpenWeather icon + description | input only | W cache | Unsupported HA conditions fail closed |
| forecast `dt` | local-noon Unix seconds, today/future, unique/sorted, max seven | input only | W cache | Physical weekday verified on exact device |
| forecast `temp.day` | duplicate of validated daily high for native parser | input only | W cache | Added only because exact parser consumes it |
| forecast `temp.min/max` canonical | finite °C, low <= high | input only | W cache | Runtime retains semantic low/high |
| forecast card wire slots | high sent in parser `min`, low in `max` | input only | W cache | Exact 1.5.8 QML renders first slot bold; display-only quirk |
| forecast humidity | optional 0..100 %RH | input only | W cache | Provider may omit daily humidity |
| design temperature | proven empty-data no-op | U | Never | Required values are Fahrenheit; no trustworthy source |
| contractor brand/phone | validated private options, never diagnostics | H config | stock metadata route | Private values must not enter logs/releases |
| Settings `qr_url` / Technician Access QR | absolute HTTPS URL, separate from captured bootstrap URL | H config | canonical Settings response after baseline capture | Updates `contactContractor.technicianURL` for the separate Technician Access popup, not the Contact Contractor page |
| `DeviceController.contactContractorURL` / Contact Contractor QR | exact `https://thestat.link/api/schedulelink?sn=` plus device serial | U | Never | Contact Contractor page reads this bound property directly; no safe API override was recovered |
| contractor metadata `url` / `contactContractor.qrURL` | optional server field stored by `onContractorInfoReady` | U | Never | Exact all-unit QV4 lookup scan finds the assignment but no reader; it does not drive the photographed QR |
| contractor logo | exact 750x375 RGBA PNG, <=1 MiB | C option/path | signed stock download; file hash/render proof | Firmware may cache/overwrite; manual atomic fallback has rollback |
| UI event timestamp/name/target | exact `EventList`; target optional UTF-8 | U | validated 2xx acknowledgement only | Target discarded; no logs, storage, diagnostics, or entity |
| `/sync/client` `email`, `con-name` | private strings persisted as user-data email/name and rendered by Mobile App page | H/unsupported | Never; see [messages-reset-api.md](messages-reset-api.md) | Full Settings does not carry them; fabricated response would be persisted |
| installer/customer/address/job model | exact schemas, residence-dependent location indices, private identity/location/contact data | H/unsupported | Never; see `installer-private-api.md` | Lookup mismatches are accepted, ZIP may alter timezone, and install success advances onboarding |
| warranty old/new serials | exact `NN-NNN-NNNNNN`; submitted old serial is prewritten before the request | H/unsupported | Never | Failure has no recovered rollback; success starts identity refetch/onboarding |
| performance-test `perftest_id`, action, result, time, readings | exact vendor workflow; 15-minute Cooling/Heating target override with persisted retry result | H/unsupported | Never; see [performance-test.md](performance-test.md) | Can run ordinary compressor, fan, heat/AUX, O/B, and configured accessory paths; vendor policy and physical controller remain unavailable |
| control/canonical/persistence/forecast health | runtime booleans | D binary sensors, mostly Off | None | Diagnostic state, not device telemetry |
| `temperatureRaw` | internal QVariant key only | U | None | Source/unit/cadence not fully traced |
| `temperature` | internal QVariant key only | U | None | Ambiguous raw/effective placement |
| `temperatureCompensationCorrection` | internal thermal correction component | U | None | Stateful model; not safely reproducible from protocol |
| `temperatureAmbientEstimator` | internal estimator output | U | None | Stateful relay/brightness/thermal inputs |
| `processedTemperature`, `roundTemperature` | internal display/control pipeline keys | U | None | Exact chain reaches `displayCurrentTemp`, Home, Settings, current-sensors, and monitor; algorithm is not reimplemented |
| `humidity`, `humidityRaw` internal | internal diagnostic keys | U | None | Scale/sentinel/cadence incomplete |
| `co2`, `etoh`, `Tvoc`, `iaq` internal | NRF producer: uint16 ppm eCO2, uint16/100 ppm ethanol-equivalent, uint16/1000 mg/m3 TVOC, byte/10 standardized IAQ score | U | None | Proven producer and long-run populations, but no numeric JSON/protobuf transport or board algorithm/calibration metadata; never label as CO |
| `pressure` internal | NRF uint16 integer hPa; `LiveDataManager` publishes on >=1 hPa change | N duplicate of f7 | None | Zero is a synchronized unavailable sentinel; current reference unit does not produce a positive value |
| `RangeMilliMeter` | ToF range candidate | U | None | Source/sentinel/privacy behavior unproven |
| `brightness` internal | display/ambient input | U | None | Distinct from saved brightness preference |
| `fanSpeed` | low-level SIO/NRF hardware command | U | Never from HA | Not the configured fan mode/duty field; hardware-test risk |

## Release boundary

Core v0.8 includes the exact local sync/control model, monitor telemetry, categorical
IAQ, positive pressure, current weather/forecast, contractor route, value-free
runtime event trace, fan mode/minutes-per-hour controls, and field-owning display
controls. A no-schedule fan On plus changed circulation duration is positively
confirmed by a later complete Settings upload. An active-schedule test
applied the requested fan duty but then cleared the schedule because the whole
Settings handler supplied empty defaults to the schedule controllers. Nuve Local
therefore permits no Settings-family write unless fresh monitor telemetry proves
NoSchedule; active or unknown authority is a local fail-closed result, not an open
hardware-validation item.
Time format and proximity are the only advanced preferences promoted in v0.8.1 after
independent reversible live tests. Speaker, temperature unit, sleep-logo, automatic
clock, timezone, and DST remain unavailable because handler analysis or live
tests produced rejected owners, delayed application, or unrelated target/cooling
drift. Installer writes, schedule/lock, remote-sensor CRUD, firmware-update, and
numeric IAQ writes likewise remain deferred rather than guessed.

The durable uncertainty journal accepts the same validated legacy
fan-plus-optional-hold recovery shape, complete backlight object, and complete
device-settings object as runtime. Invalid modes,
duty values, hold syntax, display ranges, equal night boundaries, and mixed control
families remain rejected.
