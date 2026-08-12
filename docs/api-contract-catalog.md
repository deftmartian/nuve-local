# Firmware 1.5.8 API catalog

This catalog lists all 38 direct API routes in `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
It records each route's owner, transport, data shape, effects, and Nuve Local status.
The 39th `api/` string is a fragment, not a route.

[`scripts/firmware_api_catalog.py`](../scripts/firmware_api_catalog.py) is the
machine-readable source. Tests lock the route inventory and the 15-route allowlist.

Paths preserve the firmware's slashes and Qt `%0`/`%1` placeholders. `Auth` is the
boolean passed to the client executor; vendor authorization policy is unknown.

## Complete direct-route matrix

| ID | Firmware route | Method; auth; timeout | Owner | Behavior and consequence | Nuve Local support / details |
| --- | --- | --- | --- | --- | --- |
| R01 | `%0api/device/recovery-image?sn=%1` | POST; yes; 20 s | recovery report / `0x1f5280` | Raw compact/cached recovery JSON; response is transport-only; online failures retry every 10 s uncapped, while offline failure stalls retained filenames/hash data | Unsupported private recovery report; [messages-reset-api.md](messages-reset-api.md) |
| R02 | `/api/customer` | GET; yes; 20 s | customer lookup / `0x1fc178` | Percent-encoded email query; empty success means new customer; returned contact data can persist despite mismatch warnings; retryable failures repeat at 5 s uncapped | Unsupported private onboarding lookup; [installer-private-api.md](installer-private-api.md) |
| R03 | `/api/device/settings` | POST; yes; 20 s | device preference push / `0x206044` | Complete preference/backlight projection; revision acknowledgement is delivery evidence, not later application proof; captured baseline is private persistent state | Supported strict observational ingestion; [firmware-evidence.md](firmware-evidence.md) |
| R04 | `/api/device/system` | POST; yes; 20 s | system push / `0x2066cc` | Complete 36-field HVAC/installer topology including serial and private SSID; partial/mismatched objects fail; no relay action | Supported complete read-only baseline ingestion; [field-matrix.md](field-matrix.md) |
| R05 | `/api/sync/schedules2?sn=%0` | GET; yes; 20 s | V2 fetch / `0x1fa17c` | Wrong-type/missing `data` coerces to an empty array and can clear persisted schedules; 5 s retry is uncapped; reconciled rows alter effective targets | Unsupported destructive schedule fetch; [scheduling-protocol.md](scheduling-protocol.md) |
| R06 | `/api/sync/updateAddress` | POST; yes; 20 s | address update / `0x1f9344` | Address/ZIP/country/serial body; retryable failure repeats at 5 s uncapped; changes private onboarding/location state | Unsupported private address mutation; [installer-private-api.md](installer-private-api.md) |
| R07 | `/api/technicians/device/install` | POST; yes; 40 s | install / `0x204638` | Client plus device/address/equipment body; any network-clean reply succeeds; uncapped 5 s retry; advances onboarding and requests monitor state | Unsupported onboarding transition; [installer-private-api.md](installer-private-api.md) |
| R08 | `/api/technicians/service-titan/customer/%0?sn=%1` | GET; yes; 20 s | job lookup / `0x1fba04` | Any nonempty object can succeed despite network error; private identity/address/equipment values persist; uncapped 5 s retry | Unsupported permissive private lookup; [installer-private-api.md](installer-private-api.md) |
| R09 | `/api/technicians/warranty` | POST; yes; 20 s | warranty / `0x2148a8` | Old/new serial body; old serial is prewritten with no failure rollback; retry can be uncapped and success restarts identity/onboarding | Unsupported vendor transaction and identity mutation; [installer-private-api.md](installer-private-api.md) |
| R10 | `/api/zipCode?code=%0` | GET; yes; 20 s | ZIP lookup / `0x1fd72c` | Applies returned city/state even on code mismatch and may immediately change timezone; retryable failures repeat at 5 s | Unsupported private lookup with timezone side effect; [installer-private-api.md](installer-private-api.md) |
| R11 | `api/designTemperature?sn=%0` | GET; yes; 20 s | design temperatures / `0x1fe940` | Optional Fahrenheit heating/cooling design values can affect lockouts; exact empty `data` is non-applying | Supported only as validated empty-data no-op; [firmware-evidence.md](firmware-evidence.md) |
| R12 | `api/device/current-sensors?sn=%0` | POST; yes; 20 s | sensor values / `0x202db4` | Room temperature/humidity plus one-based IAQ category; acknowledgement cannot confirm control; no hardware write | Supported strict observational ingestion; [field-matrix.md](field-matrix.md) |
| R13 | `api/device/current-stages?sn=%0` | POST; yes; 20 s | current stages / `0x202430` | Numeric fan/heat/cool stage observation; cannot prove contacts or airflow and cannot drive them | Supported strict observational ingestion; [field-matrix.md](field-matrix.md) |
| R14 | `api/device/wifi-off?sn=%0` | POST; yes; 20 s | Wi-Fi-off report / `0x215818` | `{manual_off}` report; callback ignores reply and optional caller wait is a nested loop; never controls the radio | Supported only as a report acknowledgement; [messages-reset-api.md](messages-reset-api.md) |
| R15 | `api/monitor/data?sn=%0` | POST; yes; 20 s | live-data manager / `0x2aa0ac` | Raw `LiveDataPointList` protobuf; validated delivery drains file queue; sparse fields never mean zero and full-sync records establish authority | Supported with strict schema and range checks; [firmware-evidence.md](firmware-evidence.md) |
| R16 | `api/monitor/event?sn=%0` | POST; yes; 20 s | event-data manager / `0x2a472c` | Raw `EventList` protobuf; validated delivery drains queue; activity payload is discarded rather than logged or persisted | Supported privacy-preserving acknowledgement; [firmware-evidence.md](firmware-evidence.md) |
| R17 | `api/monitor/report?sn=%0` | POST; yes; 20 s | command report / `0x207d50` | Body contains result only; any parsed object succeeds; System uses at most three attempts separated by 60 s | Supported only for allowlisted command recovery; [messages-reset-api.md](messages-reset-api.md) |
| R18 | `api/sync/alerts` | POST; yes; 20 s | alert push / `0x206d54` | Device alert types plus serial; transport-only success consumes optional ID; failures retry at 6 s uncapped and disclose private alert state | Unsupported private alert sink; [messages-reset-api.md](messages-reset-api.md) |
| R19 | `api/sync/autoMode?sn=%0` | GET/POST; yes; 20 s | Auto fetch/push / `0x1fa92c`, `0x2057b4` | Reads/writes complete Auto bounds; revision ack alone is insufficient and newer authoritative monitor evidence confirms control | Supported canonical read and guarded reversible control; [firmware-evidence.md](firmware-evidence.md) |
| R20 | `api/sync/clearSchedule2` | POST; yes; 20 s | schedule clear / `0x1ff694` | Serial/id query; permissive `errors` coercion; 3 s retry loses the original V2 argument; deletes effective schedule state | Unsupported destructive V2 mutation; [scheduling-protocol.md](scheduling-protocol.md) |
| R21 | `api/sync/clearSchedules` | POST; yes; 20 s | schedule clear / `0x1ff694` | Serial/scheduleId query; permissive completion and no delivery-safe transaction; deletes legacy schedule state | Unsupported destructive legacy mutation; [scheduling-protocol.md](scheduling-protocol.md) |
| R22 | `api/sync/client?sn=%0` | GET; yes; 20 s | user-data fetch / `0x1f9de4` | Exact response strings are `email` and `con-name`; values persist as user-data email/name and email is rendered in UI | Unsupported private account-linkage state; [messages-reset-api.md](messages-reset-api.md) |
| R23 | `api/sync/forget?sn=%1` | POST; yes; 20 s | factory reset / `0x1ffe1c` | Registration forget precedes separate config deletion/timezone reset/reboot; Qt error 5 has a true boolean but blocks countdown via message | Unsupported destructive reset workflow; [messages-reset-api.md](messages-reset-api.md) |
| R24 | `api/sync/getContractorInfo?sn=%0` | GET; yes; 20 s | contractor fetch / `0x1f96a4` | Brand/phone/logo metadata; stock logo download lacks bearer forwarding, so local projection uses a serial/token-bound signed PNG URL | Supported constrained configured metadata; [firmware-evidence.md](firmware-evidence.md) |
| R25 | `api/sync/getSettings?sn=%0` | GET; yes; 20 s | settings fetch / `0x1fa54c` | Flat desired state plus nested singular `setting`; complete captured baselines and strictly newer revision are required; can alter desired HVAC state | Supported canonical fail-closed read/control response; [firmware-evidence.md](firmware-evidence.md) |
| R26 | `api/sync/getSn?uid=%0` | GET; **no**; 20 s | serial fetch / `0x21535c` | UID query; `serial_number`/`has_client` mutate two QSettings values, Sync, DeviceInfo, alerts, and onboarding | Unsupported unauthenticated identity mutation; [installer-private-api.md](installer-private-api.md) |
| R27 | `api/sync/getWirings?uid=%0` | GET; yes; 20 s | wiring fetch / `0x1f8b70` | Callback ignores response and network status, then emits `wiringReady`; can advance onboarding without valid wiring data | Unsupported response-ignoring transition; [installer-private-api.md](installer-private-api.md) |
| R28 | `api/sync/messages?sn=%0` | GET; yes; 20 s | message fetch / `0x1f9a44` | Callback discards all response data; real private message ingestion is through full Settings and whole-repository persistence | Unsupported inert/private inbox route; [messages-reset-api.md](messages-reset-api.md) |
| R29 | `api/sync/perftest/result?sn=%0` | POST; yes; 20 s | result upload / `0x2c3d48` | Running completion launches hardware even on network error; finished results persist/retry at 300 s and can collide with later success | Unsupported direct equipment-test activation; [performance-test.md](performance-test.md) |
| R30 | `api/sync/perftest/schedule?sn=%0` | GET; yes; 20 s | eligibility / `0x2c6824` | Valid id plus cooling/heating action can select 40 F/90 F target and start ordinary 15-minute HVAC operation | Unsupported server-triggered physical test; [performance-test.md](performance-test.md) |
| R31 | `api/sync/schedule2/%0?sn=%1` | PUT; yes; 20 s | schedule edit / `0x1fef80` | Complete V2 row; body ignored on success; no revision/idempotency and 4 s retry can be delivery-ambiguous | Unsupported V2 mutation; [scheduling-protocol.md](scheduling-protocol.md) |
| R32 | `api/sync/schedule2?sn=%0` | POST; yes; 20 s | schedule add / `0x210428` | Complete V2 row; any nonempty object succeeds and missing ID propagates; 2 s retry can duplicate activities | Unsupported V2 mutation; [scheduling-protocol.md](scheduling-protocol.md) |
| R33 | `api/sync/schedules` | POST; yes; 20 s | legacy add / `0x210428` | Legacy range/body plus native-inserted serial; permissive response consumes possibly absent schedule ID; no idempotency | Unsupported legacy mutation; [scheduling-protocol.md](scheduling-protocol.md) |
| R34 | `api/sync/schedules/%0` | PUT; yes; 20 s | legacy edit / `0x1fef80` | Legacy packet plus inserted serial; response ignored on success and queued retries have no conflict token | Unsupported legacy mutation; [scheduling-protocol.md](scheduling-protocol.md) |
| R35 | `api/sync/screen-%1?sn=%2` | POST; yes; 20 s | lock push / `0x1fdd80` | Four-character PIN; local plaintext save/lock precedes delivery; wrong-type `locked` can succeed; retry doubles 1 s to 60 s without durable journal | Unsupported precommitted private lock mutation; [lock-protocol.md](lock-protocol.md) |
| R36 | `api/sync/update` | POST; yes; 20 s | full settings push / `0x2008a8` | Exact 18-member complete upload with nested system/settings; persisted as private canonical baseline, never as command confirmation | Supported strict complete baseline ingestion; [firmware-evidence.md](firmware-evidence.md) |
| R37 | `api/weather-current?sn=%0&units=%1` | GET; yes; 20 s | current weather / `0x2d0130` | OpenWeather-shaped current data; finite/fresh source required and missing temperature yields 503; outdoor input can affect HVAC lockouts | Supported validated fail-closed HA projection; [firmware-evidence.md](firmware-evidence.md) |
| R38 | `api/weather-forecast?sn=%0&units=%1` | GET; yes; 20 s | forecast / `0x2cfc2c` | Up to seven validated dated rows; empty list is safe no-forecast; display slots compensate exact QML high/low quirk | Supported validated fail-closed HA projection; [firmware-evidence.md](firmware-evidence.md) |

## Safety boundary

The allowlist is exactly the 15 rows marked supported. It is not inferred from a
known path, HTTP method, or harmless-looking name. Several unsupported calls mutate
local identity or persistent state before acknowledgement; others can clear
schedules, change timezone, lock the screen, reboot after reset, or exercise HVAC
equipment. Unknown paths fail explicitly.

“Supported” is also narrow. The Wi-Fi route acknowledges a report but never controls
the radio; design temperatures return only the proven empty no-op; events are
discarded; and command reports exist only as the terminal step of the allowlisted
monitor-command recovery protocol. Settings and Auto control remain gated by exact
firmware identity, complete private baselines, revision ordering, and independent
post-delivery confirmation described in [firmware-evidence.md](firmware-evidence.md).

Vendor-side authorization, retention, conflict handling, and business semantics are
not embedded in the application and cannot be recovered from this corpus. Those
server unknowns do not leave application-side behavior uncataloged; they determine
why private, transactional, destructive, or equipment-test rows remain unsupported.
