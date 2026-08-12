# Installer, customer, identity, and warranty contracts

These private workflows come from `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
Nuve Local does not implement them.

## Transport inventory

All listed calls use `application/json`. The authentication column is the boolean
passed by the firmware to `RestApiExecutor`. The vendor server's authorization policy
is not present in the recovered code.

| Method and exact path shape | Firmware owner | Auth | Timeout | Response use |
| --- | --- | --- | --- | --- |
| `GET api/sync/getWirings?uid=%0` | `Sync::fetchWirings`, Ghidra `0x1f8b70` | yes | 20 s | Ignores the JSON and network status and emits parameterless `wiringReady` when the callback runs |
| `GET api/sync/getSn?uid=%0` | `Sync::fetchSerialNumber`, `0x21535c` | no | 20 s | Consumes `serial_number` string and `has_client` boolean and mutates identity state |
| `GET api/sync/client?sn=%0` | `Sync::fetchUserData`, `0x1f9de4` | yes | 20 s | A nonempty object yields wire fields `email` and `con-name`; QML stores them as persisted `userData.email` and `.name` |
| `GET /api/technicians/service-titan/customer/%0?sn=%1` | `Sync::getJobIdInformation`, `0x1fba04` | yes | 20 s | Object shape below; empty JSON is failure |
| `GET /api/customer?email=...` | `Sync::getCustomerInformationManual`, `0x1fc178` | yes | 20 s | Email is percent-encoded by `prepareUrlWithEmail`; HTTP success and object emptiness are distinct outcomes |
| `GET /api/zipCode?code=%0` | `Sync::getAddressInformationManual`, `0x1fd72c` | yes | 20 s | Object shape below; may change timezone during initial setup |
| `POST /api/sync/updateAddress` | `Sync::updateAddressInformationManual`, `0x1f9344` | yes | 20 s | Emits success, reply error text, and retry disposition |
| `POST /api/technicians/device/install` | `Sync::installDevice`, `0x204638` | yes | 40 s | Any network-error-free reply is success; `is_enabled` is read only for logging |
| `POST /api/technicians/warranty` | `Sync::warrantyReplacement`, `0x2148a8` | yes | 20 s | Reads optional `message`; error 299 is treated as nonretryable |

The paths retain the firmware's inconsistent leading slash. URL-base
joining happens in `RestApiExecutor`, so normalizing the literals would no longer
be an exact inventory.

## Persisted installer model and enums

`ServiceTitan.qml` file offset `6379024` is a `QSObject` in the persisted device
graph. It holds manual/active/fetched flags plus email, ZIP, job number, full name,
phone, two address lines, country, city, state, and numeric city/state IDs. Text
defaults to empty, IDs to `-1`, and the private `_fetched` member is excluded by the
underscore serializer rule. `I_Device.qml` offset `6217120` defaults to installation
type `ITUnknown=2`, residence `Unknown=2`, `whereInstalled=-1`, `systemAge=0`, and
an empty thermostat name.

The exact declarative enums and lists are:

- installation: new `0`, existing `1`, unknown `2`;
- residence: misspelled `Residental=0`, commercial `1`, unknown `2`;
- countries: `US`, `Canada`, `Australia`, projected to API IDs `1`, `2`, `3`;
- an unlisted country projects to `0` because QML sends `indexOf(country) + 1`;
- `where_installed_id` is the zero-based index into a residence-specific UI list,
  not a global enum. Residential has 12 labels and commercial has four; unknown
  has none.

The residential order is Basement, Bedroom, Dining Room, Downstairs, Guesthouse,
Kids Room, Living Room, Main Floor, Master Bedroom, Office, Upstairs, Custom. The
commercial order is Lunchroom, Office, Warehouse, Custom.

## Install and address request schemas

`DeviceController._prepareAddressPacket` returns:

```json
{"zip_code": "UPPERCASED", "country": 1}
```

When external-service mode is active, nonempty `address1` and `address2` are added.
Manual mode suppresses both street fields. `updateAddressInformation` adds `sn` to
that object and posts it directly to `/api/sync/updateAddress`.

`_pushInitialSetupInformation` first creates a `client` object containing `email`.
External-service mode also adds nonempty `full_name` and `phone`. It then extends
the address packet into the one device row:

```text
zip_code, country, [address1], [address2], sn, installation_type,
system_age, resident_type_id, where_installed_id, [name]
```

`installation_type` is `new` only for enum zero and `existing` for every other
value, including `ITUnknown`. New installation forces `system_age` to zero; other
values use the stored age. Thermostat `name` is omitted when empty. The final body
is `{client, devices: [device]}` and external-service mode adds top-level `job_id`
when the stored job number is nonempty. The device/address placement is important:
address fields are not nested beneath `client`.

The install callback treats `QNetworkReply::NoError` as success regardless of JSON
shape or the value of `is_enabled`. Failure supplies executor error text and retry
classification. While retryable, a repeating QML timer resends the complete body
every five seconds with no recovered attempt cap. The UI shows every second
retryable failure and every nonretryable failure. Success ends the first-run flow,
starts timezone/log housekeeping, changes edit flags, and requests a full monitor
packet. A fake success would therefore advance persisted onboarding state.

## Lookup response schemas

Job lookup considers any nonempty JSON object successful, even if the network
status was erroneous. An empty object is retryable unless the reply error is the
custom value 299. On success QML accepts these fields:

```text
full_name, phone, email,
zip.code or scalar zip,
country.name or scalar country,
city.name/id or scalar city,
state.short/id or scalar state,
address1, address2, system_age
```

Missing text becomes empty, missing numeric IDs become `-1`, missing system age
becomes zero, and `United States` is normalized to `US`. The values are assigned to
the persisted installer/device model. There is no response identifier correlation
beyond the active UI state.

ZIP success accepts `code`, nested `city.name/id`, nested `state.short/id`, and
optional `time_zone_id`. If returned `code` differs from the request, firmware logs
a warning but still applies the city/state data and records the returned code.
During initial setup, when the timezone polling timer is not already running, a
different `time_zone_id` is assigned directly to `DateTimeManager.currentTimeZone`,
copied to `setting.installationTimezone` (with `UTC` only for null/undefined), and
followed by `updateTimezoneAutomatically`. This is a material local side effect of
a lookup response.

Customer lookup success is based on network error zero. A successful empty object
is treated as a new email and continues without an error. For nonempty data, QML
logs but otherwise ignores `membership` and `is_enabled`, copies `full_name` and
`phone`, and records returned `email` only as an internal comparison token. An
email mismatch is merely warned; the originally entered email is not overwritten
and the returned row is still accepted.

The job, ZIP, address, and warranty pages use single-shot five-second retry timers.
Retry counters are not capped. Nonretryable failures are shown immediately and
retryable failures are surfaced on every even counter while retrying continues.

## Identity and warranty hazards

`getSn` is the only recovered unauthenticated call in this family. A response with
`serial_number` and `has_client` updates in-memory Sync state, two `QSettings`
values, and the `DeviceInfo` singleton. It compares against any previous serial,
raises UI alerts on missing/mismatched identity, and emits either `serialNumberReady`
or test-mode/initial-setup signals. A response lacking `serial_number` follows
special error/test-mode paths rather than a normal empty result. This route cannot
be safely emulated as a harmless discovery endpoint.

Both warranty UIs require serials matching `^\\d{2}-\\d{3}-\\d{6}$`; they auto-insert
hyphens after two and five digits. The current device serial is the read-only new
serial and the technician enters the damaged thermostat as old serial. Native code:

1. rejects equal values locally;
2. writes the submitted **old** serial to the serial-number `QSettings` key before
   making the request;
3. posts `{"old_sn": old, "new_sn": current}`;
4. on network success, ignores all response fields except optional `message` and
   starts a refetch/re-onboarding sequence.

There is no rollback of the prewritten serial in the failure callback. This
pre-response persistence and the identity/refetch consequences make warranty
emulation unsafe even when the server reply would be synthetic.

## Disposition and reproduced checks

The isolated model in `scripts/emulate_firmware_installer.py` reproduces install
packet construction, manual-mode omission, country projection, job/ZIP/customer
coercion, mismatch acceptance, timezone mutation, warranty prewrite, and retry UI
cadence. `tests/test_firmware_installer_emulator.py` supplies independent fixtures.

The application-side request and response shapes above are grade A+B. The vendor
server's authorization, email/job lookup rules, warranty transaction semantics,
and audit/retention behavior remain unavailable. Every route in this document stays
unavailable in Nuve Local; no catch-all endpoint should acknowledge
it.
