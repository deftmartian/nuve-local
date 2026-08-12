# Application update process

This update path comes from application `1.5.8`, SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`, using
static analysis and an isolated model. Nuve Local exposes none of it.

## Artifact and transport boundary

Application updates are ZIP archives installed under `/usr/local/bin`. They are
independent of the U-Boot p1/p2 image-update and p4 factory-restore paths. The exact
client constructs update metadata names in the `update_<model>_V1.json` family and
recovery metadata names in the `recovery_<model>_V1` family. The two source model
labels normalized to `00` have not yet been named with enough evidence.

The updater uses `http://update.nuvehvac.com`, a 10-second download timeout, and a
query of the form `?id=<MD5(serial bytes)>`. Metadata uses
`<base>/<metadata-name>?id=...`; normal payloads use the base plus the normalized
metadata `Address`, and the manual path prefixes `/manual_update/`. This is
plaintext transport carrying a stable serial-derived identifier. It is neither a
secret nor an authentication proof, but it is persistent device-identifying data.

## Metadata contracts

The application metadata validator selects one version, requires its name to split
into exactly three dot-separated pieces, and requires these seven members:

| Required member | Later use |
| --- | --- |
| `ReleaseDate` | parsed as `d/M/yyyy`, displayed as `dd MMM yyyy` |
| `ChangeLog` | update presentation |
| `Address` | payload URL |
| `RequiredMemory` | download/install free-space gate |
| `CurrentFileSize` | download progress/size state |
| `CheckSum` | hex-decoded expected MD5 |
| `Staging` | version-selection gate described below |

The validator rejects an absent/null member, an empty JSON string, and numeric
zero. It does not reject booleans, arrays, or objects. This is syntactic presence
checking with weak type validation, not a complete schema. `ForceUpdate`,
`ExcludedForContractors`, `AvailableForContractors`, and
`ForcedForContractors` are optional at this gate.

The backplate metadata check requires only the presence of `CurrentFileSize`,
`CheckSum`, `Address`, and `Version` in the root object. Each recovery metadata
entry must instead be a nonempty object containing `CurrentFileSize`, `CheckSum`,
`Address`, and `fileName`; value types are not validated by this check.

For client-specific app versions, exclusion wins: a current contractor ID in
`ExcludedForContractors` makes the version inapplicable. Otherwise either
`AvailableForContractors` or `ForcedForContractors` must contain zero or the
current contractor ID. Missing and wrong-type arrays coerce to empty and do not
match.

Version keys other than `LatestVersion` are sorted newest-first by a numeric
dot-component comparator. It compares as many components as either side supplies,
pads a missing component with zero, and treats a failed signed-integer conversion
as zero. The latest-version scan chooses the first applicable candidate. A candidate
whose `Staging` value is JSON `true` is skipped in normal mode and factory-test mode;
it is visible only when test mode is true and factory-test mode is false.

The force scan considers only candidates newer than the installed application. It
requires applicability and then requires `ForcedForContractors` to contain the
exact current contractor ID; wildcard zero alone makes an ordinary contractor's
version applicable but not forced. The same staging gate applies. The scan is
newest-first but does not break after a force match, so each older qualifying row
overwrites the result and the returned forced version is the oldest qualifying
version still newer than installed. The client-specific code does not read the
scalar `ForceUpdate` member after its static initialization; that member does not
control this exact strategy.

## Client orchestration and timers

The client-specific strategy has four recovered scheduling intervals plus one
download-state gate:

| State | Exact behavior |
| --- | --- |
| base update timer | 21,600,000 ms (six hours); Wi-Fi connect starts it and disconnect stops it |
| metadata retry timer | 5,000 ms, one-shot; initial setup and eligible metadata errors arm it |
| client queue timer | 10,000 ms, one-shot; advances the sequential metadata-fetch queue |
| recovery retry timer | 20,000 ms, one-shot; retries a failed recovery-file operation |
| active download timer | a separate timer at strategy offset `+0x108`; while active, a server-requested app update is rejected |

Outside night mode and initial setup, Wi-Fi connection immediately copies the
application, backplate, and recovery `UpdateInformation` keys into a DNS queue.
The six-hour timer repeats that operation. Each key is processed sequentially with
a DNS TXT lookup. The client uses only the first TXT record's first value, parsed
with `yyyy-MM-ddTHH:mm:ss`. An invalid cached timestamp, or a parsed timestamp newer
than the cached one, updates the cached value and queues that metadata family for a
fetch. Otherwise the application key alone re-enters the server-request path. A DNS
error or missing record/value removes the key for that cycle without an immediate
DNS retry.

When the DNS queue empties, the 10-second timer begins sequential metadata fetches:
type zero dispatches application metadata, type one backplate metadata, and type two
recovery metadata. Application completion removes type zero, restarts the queue
timer, and checks the stored server request. Recovery network/validation callback
failures retain type two and restart the same queue timer; successful validation
writes the local metadata, removes the key, and starts `RecoveryUpdater`.

The five-second metadata timer fires only with internet present. It restarts the
six-hour countdown if that timer is active, then calls the virtual metadata fetch
with both native booleans true. This is distinct from the application-archive retry
counter below.

Recovery completion copies its first boolean into the client in-process latch. A
retry-requested completion with that latch false arms the 20-second timer while its
integer property is below three. Each timeout invokes the recovery updater and then
increments that property. The property is initialized to zero and no reset was
found, so the client permits at most three timer-driven recovery attempts per
process lifetime, not three per manifest or failure.

## Selection, notification, and manual/server modes

`checkPartialUpdate(notify, directLatest)` always refreshes the metadata object
first. With `directLatest=false`, the client-specific virtual selects only a
contractor-forced version and sets the force latch. With `directLatest=true`, it
uses the newest applicable version instead. An empty selection returns before
clearing initial-setup state.

A selected version newer than the installed user version latches
`updateAvailable=true`; this method does not clear an already-true value when a
later selection is not newer. If availability remains false, it clears
initial-setup state and emits `updateNoChecked`. A direct-latest check starts its
selected version even if it is equal to or older than the installed version. A
forced selection starts automatically only when neither current manual-update nor
firmware-server-update state is set.

The generic notification branch requires a newer, non-forced selection, a true
`notify` argument, and neither origin flag. No recovered client-specific caller
combines those conditions: normal network completion uses the forced scan, while
the direct-latest manual-exit call uses `notify=false`. The branch exists but is not
claimed as a reachable client notification path in this exact build.

At construction, `Stherm/IsManualUpdate` is copied into both current manual state
and an immutable process-start snapshot. `exitManualMode()` acts only when that
snapshot is true: it clears current manual state and performs a direct-latest
check. `ignoreManualUpdateMode(runCheck)` also clears only current state and, when
requested, performs a notifying forced check. Neither function clears the persisted
setting or the process-start snapshot. Consequently a specific server request
remains blocked for that process if it started in manual mode.

The server-request path is gated by test mode, the active download timer, and the
restarting latch, then by a successful metadata refresh. An empty request with
persisted firmware-server state clears `Stherm/IsFWServerUpdate` and runs a
non-notifying forced check. A nonempty request different from the installed user
version reaches the same archive path with only the firmware-server origin flag,
unless the process-start manual snapshot is true. An equal version is ignored.

`systemUpdating` persists `updateSequenceOnStart=true` before the delayed helper
start. On a later launch, `updateSequenceOnStart()` returns the stored value and
unconditionally writes it back as false. The in-process restarting latch remains
true once `updateAndRestart` reaches this phase; no same-process clear was found.

## Download and retry state

For a normal version, the client reads `Address`, `RequiredMemory`,
`CurrentFileSize`, and hex-decodes `CheckSum`. A cached
`/mnt/update/latestVersion/update.zip` can be accepted without another download if
its MD5 matches. A new payload is MD5-checked in memory, written to that path,
reopened, read back, and MD5-checked again before `partialUpdateReady` is emitted.
The second check detects a failed/corrupt file write, but neither check establishes
publisher authenticity. No detached signature, signed manifest, certificate-bound
payload, or ZIP-member allowlist was found in this path.

Initial-setup non-manual download failures share a process-static counter. Failures
one through five arm the retry timer; failure six clears initial-update state and
emits `updateNoChecked`. No reset of that counter was found, so it is a cumulative
process-lifetime budget rather than six attempts per update. Other download failures
emit the updater error directly.

The three explicit archive-entry routes retain their origin: ordinary
`partialUpdate(backdoor)` stores either the selected forced/latest version or the
backdoor version; `partialUpdateByVersion` marks reset-to-version; and a specific
server request marks firmware-server origin. Retry dispatches by the stored
reset-to-version bit first, otherwise by the stored backdoor bit.

## Install preflight and persisted flags

Both filesystem gates use strict inequality: available bytes must be greater than
`RequiredMemory`, not equal to it. If the update filesystem is short, the app
deletes `/mnt/log/log/` and `/mnt/log/networkLogs/` and rechecks. If the application
filesystem is short, it counts the current app executable as replaceable space,
then deletes `/test_results.csv`, `/usr/local/bin/updateInfo.json`, and
`/usr/local/bin/files_info.json` before rechecking.

Before starting the helper service, the application persists the update date and:

- `Stherm/IsManualUpdate = isBackdoor || isResetToVersion`;
- `Stherm/IsFWServerUpdate = isFWServerVersion`.

It synchronizes settings, emits the updating state, installs the helper script/unit,
and starts `appStherm-update` after 200 ms.

## Helper-service failure model

The generated unit runs `/usr/local/bin/update.sh` and has
`Restart=on-failure`. The embedded script mounts/uses the p3 update area, unpacks
the archive, stops `appStherm`, waits for it to leave, recursively copies extracted
content into `/usr/local/bin`, unconditionally removes the update source, attempts
to start the application, and exits zero.

The script has no fail-fast mode, command-result checks, staging directory,
atomic rename, backup, A/B slot, or rollback. An unzip, decompression, stop, copy,
or start failure can therefore be masked by the final zero exit. The source may be
destroyed after an incomplete copy, and `Restart=on-failure` will not retry a helper
that reported success. Application service `Restart=on-failure` can restart a valid
binary but cannot restore overwritten bytes.

## Reproduced boundary

The isolated emulator and fixtures reproduce:

- the three metadata presence contracts and weak app-value predicate;
- numeric version ordering, staging visibility, contractor applicability, and the
  oldest-qualifying forced-version overwrite;
- synthetic plaintext URLs and stable serial-derived IDs without private data;
- in-memory and post-write MD5 decisions;
- the cumulative five-retry/sixth-abort behavior;
- the six-hour/5-second/10-second/20-second timers, DNS freshness routing,
  notification/force decisions, manual snapshot, server race gates, recovery retry
  exhaustion, and consumed restart-sequence flag;
- strict free-space comparisons, cleanup order, and update-origin flags; and
- masked shell-command failures, unconditional cleanup, zero exit, and lack of a
  systemd retry.

The emulator rejects malformed MD5 text. It does not attempt to reproduce every
`QByteArray::fromHex` edge or execute Qt DNS/network
objects or model real ZIP semantics, systemd/process interruption, filesystem
durability, or power loss. The separate p4 recovery-file state machine is described in
[recovery-updater.md](recovery-updater.md). Real fault outcomes still require
isolated cloned filesystems, never the connected thermostat.
