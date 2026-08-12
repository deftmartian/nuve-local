# Firmware 1.5.8 screen-lock protocol

This lock path comes from `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
PIN values are omitted from repository fixtures and research notes.

## Local model and UI

Exact `Lock.qml` at binary file offset `6232864` is a persisted `QSObject` with:

| Property | Type | Default | Persistence |
| --- | --- | --- | --- |
| `pin` | string | empty | persisted in the application JSON |
| `_masterPIN` | string | empty | excluded by the leading-underscore serializer rule |
| `isLock` | bool | false | persisted in the application JSON |

`updateAppLockState(isLock, pin, fromServer=false)` requires a string length of
exactly four. It does not itself require four decimal digits; the normal keyboard
supplies digits, but another caller can supply any four characters.

Locking treats the supplied PIN as valid but refuses to lock when
`system.hasClient()` is false. Unlocking requires the stored PIN or a generated
four-character master PIN. When the master PIN succeeds, the function substitutes
the stored user PIN before changing state and before any server push. An unchanged
lock boolean plus unchanged PIN is ignored.

`lockDevice` writes `pin` and `isLock`, calls the non-atomic whole-repository
`saveSettings`, and immediately changes `ScreenSaverManager` lock state. Local UI
state therefore changes before server acknowledgement. A Settings response calls
the same function with `fromServer=true`, which suppresses pushback.

The unlock emergency UI generates an encoded value for support and can derive a
master PIN through `AppUtilities::decodeLockPassword`. The exact QML also logs the
entered PIN and, in the master path, the master PIN. That is a plaintext log-disclosure
risk in addition to plaintext persistence of the user PIN.

## Server push

`NUVE::Sync::pushLockState` (`0x1fdd80`) uses a 20-second POST:

```text
api/sync/screen-lock?sn=<serial>
api/sync/screen-unlock?sn=<serial>
```

The body contains only:

```json
{"pin":"<four-character PIN>"}
```

The native callback reports success if the parsed response object merely contains
the exact member `locked`. It coerces that member with `toBool()` and emits both
`success` and the resulting boolean. The QML completion handler stops retrying on
`success` but ignores the returned boolean. It therefore does not verify that the
server's state equals the locally requested state. A wrong-type `locked` member is
accepted and coerces to false.

Missing `locked` keeps the pusher active. It begins at 1,000 ms, sends immediately,
and doubles the one-shot retry interval after each failed callback up to 60,000 ms.
The retry state is in the controller, not the persisted object graph, so application
restart loses it while retaining the locally changed PIN/lock state.

The full Settings fetch owns the server-to-device `locked` and `pin` fields. Full
Settings uploads do not own them; local-to-server synchronization uses only the
separate screen-lock route.

## Evidence and disposition

Exact QV4 units, native transport, and callback provide **A (exact static)**
evidence. The isolated [lock emulator](../scripts/emulate_firmware_lock.py) and
independent fixtures reproduce PIN acceptance, master substitution, no-client
refusal, request shape, permissive response handling, and retry backoff for **B
(emulated)** evidence.

The route remains unsupported in Nuve Local because:

- local state is committed before server confirmation;
- the vendor acknowledgement does not confirm requested-state equality;
- retries have no durable delivered/unconfirmed journal;
- the PIN is plaintext at rest and in vendor debug logs; and
- no separately approved reversible live lock/unlock validation exists.

## Remaining unknowns

- **U:** server authorization, PIN storage, rate limiting, and audit behavior;
- **U:** whether a network-error response containing `locked` can reach the callback
  as a parsed non-empty object in every executor branch;
- **U:** brute-force resistance of the local PIN UI and master-PIN derivation;
- **U:** behavior after a crash between local save, screen lock, and server push; and
- **U:** recovery behavior when the persisted lock JSON is corrupted.
