# Messages, alerts, identity, reset, and report workflows

These workflows come from `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
Nuve Local implements only the monitor command-report acknowledgement.

All native requests below require a device serial, use the authenticated executor,
and have a 20-second timeout unless a missing-serial branch is stated explicitly.

## Messages

`Message.qml` at binary file offset `6233616` defines these integer enums:

| Family | Exact values |
| --- | --- |
| type | Unknown 0, Alert 1, Notification 2, SystemNotification 3, SystemAlert 4, Error 5 |
| source | Unknown 0, Device 1, Server 2 |

Each persisted message owns `id`, `type`, `sourceType`, `title`, `message`,
`parsedMessage`, `isRead`, `icon`, and `datetime`. The application retains at most
50, newest first, through the same non-atomic whole-repository save described in
[persistence-schema.md](persistence-schema.md).

The dedicated `NUVE::Sync::fetchMessages` (`0x1f9a44`) issues:

```text
GET api/sync/messages?sn=<serial>
```

Its callback at `0x1f4464` discards the network reply, raw bytes, and parsed JSON
and only emits `messagesLoaded()`. It does not ingest the response. Server messages
actually arrive through the full Settings `messages` member, whose DeviceController
handler delegates to `MessageController.setMessagesServer`.

The exact server-array handler:

- rejects a non-array without changing state;
- requires own members `message_id`, `message`, `created`, and `type`, and ignores
  an empty `message`;
- overwrites the incoming `is_read` member with false before using it;
- converts null `created` to an empty string;
- converts SystemNotification to ordinary Notification and defaults null type to
  Notification, while merely logging other type mismatches;
- deduplicates a Server-origin row by strict `message_id`, or by a negative local
  ID plus strict message, datetime, and type equality;
- on a duplicate, may update the in-memory ID but does not emit `messagesChanged`
  or immediately save;
- parses nonempty `message_rich` for display, otherwise uses `message`;
- marks disabled server Alert/Notification classes read instead of rejecting them,
  and suppresses their popup notification; and
- inserts a new row at the front, trims after 50, emits change, and saves the whole
  settings repository.

Because server content is rendered, persisted, and privacy-sensitive, Nuve Local
continues to preserve already captured Settings state but does not serve a message
inbox or fabricate server messages.

## Device alert upload

Device-origin Alert and SystemAlert messages are queued; Server-origin messages
are never re-uploaded. QML maps the local message text to an alert enum and then to
its string before calling native code. The resulting request is:

```text
POST api/sync/alerts
{"alerts":[{"type":"<mapped type>"}],"sn":"<serial>"}
```

The local QtQuickStream UUID is callback correlation only and is not in the body.
`NUVE::Sync::pushAlertToServer` (`0x206d54`) treats network error zero as success
and emits the parsed object without schema validation. On success QML assigns
`alert.alert_id` to the local message ID even when the member is absent, saves,
and removes the queued item. On failure it retains the item. A nonempty queue
restarts a 6,000 ms timer; no retry cap was recovered.

The route remains unsupported because it transfers device alert state to a private
sink whose authorization, retention, and acknowledgement contract are unavailable.

## Mobile-app identity

`NUVE::Sync::fetchUserData` (`0x1f9de4`) issues:

```text
GET api/sync/client?sn=<serial>
```

An empty parsed object emits no data, but always clears the in-flight flag. A
nonempty object reads exact string members `email` and `con-name`; missing or
wrong-type members become empty strings. DeviceController QV4 function 241 writes
those values to `device.userData.email` and `.name` and calls `saveSettings`.
The Mobile App page fetches on completion and on click, then renders the email in
its login-link explanation.

Those are private account-linkage fields absent from the complete Settings upload.
The endpoint stays unsupported rather than inventing, exposing, or overwriting an
identity.

## Device forget and application reset

`NUVE::Sync::resetFactory` (`0x1ffe1c`) uses:

```text
POST api/sync/forget?sn=<serial>
{"sn":"<serial>"}
```

No serial is treated as immediate success without a request. A normal network
success emits `(true, "")`. Qt network error 5, OperationCanceledError, instead
emits success true together with the nonempty message “The server took too long to
respond. Please try again later.” Other errors emit false.

The development-page consumer starts its destructive countdown only when success
is true **and** the message is empty, so the error-5 branch displays failure despite
its true boolean. The distinction matters for any emulator or replacement UI.

The route is only the server-registration step. Separate application paths then
stop state timers, set the timezone to UTC, delete both primary and recovery
QtQuickStream configuration files, invoke native reset/forget operations, and
reboot. A remote forget request has its own countdown and deletes configuration
before reboot. U-Boot `factory_restore` is yet another mechanism: it can write p1
and p2 from p4 and is documented in [boot-update-recovery.md](boot-update-recovery.md).

None of the server forget, local reset/forget, reboot, or boot restore mechanisms
is exposed by Nuve Local.

## Recovery-image information report

`RecoveryUpdater::reportRecoveryInfomation` (`0x30bb08`) serializes a supplied
nonempty object with compact `QJsonDocument` output. With an empty object it reads
the current `/mnt/recovery/filesInfo.json` cache. It emits nothing when the
resulting bytes are empty. DeviceController forwards nonempty bytes to:

```text
POST api/device/recovery-image?sn=<serial>
Content-Type: application/json
<the exact compact object or cached file bytes>
```

`NUVE::Sync::sendRecoveryInfomationToServer` (`0x1f5280`) ignores the response body
and returns only transport success plus the original bytes. DeviceController owns a
10,000 ms single-shot retry timer:

- success stops the timer and clears its dynamic `fileData` and `isValid` values;
- failure stores the original bytes, sets `isValid=true`, and starts the timer only
  when `isInternetConnected` is currently true;
- timer expiry reads `fileData` and resends it when nonempty; repeated failures can
  continue without a cap; and
- a failure while the connectivity flag is false retains the bytes but starts no
  timer, and no later connectivity-triggered restart was found.

This report can disclose recovery filenames, sizes, and checksums. It is not an
update command, but it remains unsupported alongside the updater.

## Manual Wi-Fi-off acknowledgement

`NUVE::Sync::setWiFiOff` (`0x215818`) issues:

```text
POST api/device/wifi-off?sn=<serial>
{"manual_off":true|false}
```

Its request callback is empty. When the caller's second flag is true and request
creation succeeds, the function runs a nested event loop until the reply finishes;
the completion connection only quits and deletes that loop. This endpoint reports
the manual-off state. It does not disable or enable the Wi-Fi radio and does not
validate a server acknowledgement.

## Command-response report

`NUVE::Sync::reportCommandResponse` (`0x207d50`) sends:

```text
POST api/monitor/report?sn=<serial>
{"data":"<command result>"}
```

The command string is retained for log/retry context but is absent from the body.
Transport success invokes the caller with true and the parsed object; no required
response member was found. Failure waits 60 seconds and recursively retries while
its counter is positive. The System callers pass 2, producing at most three total
attempts before callback false. A missing serial returns false immediately.

Nuve Local acknowledges this route only inside its restricted monitor-command
recovery protocol. This contract does not authorize arbitrary commands or reports.

## Evidence and remaining boundary

The native owners/callbacks and QV4 units provide **A (static)** evidence. The
[miscellaneous API emulator](../scripts/emulate_firmware_misc_api.py) and 12 fixtures
reproduce message ingestion/deduplication, privacy-field
coercion, alert completion, forget timeout handling, Wi-Fi request shape,
recovery-report retry state, and command-report attempts for **B (emulated)**
evidence.

Remaining unknowns are vendor authorization, retention, server-side message and
alert semantics, and crash durability of the non-atomic message/identity save.
They do not block understanding the exact application-side contract, but they do
block support for these private or destructive routes.
