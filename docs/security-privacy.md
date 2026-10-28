# Firmware 1.5.8 security and privacy

This review covers recovery `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`
and the private artifact inventory. Private keys, identifiers, endpoints, logs,
customer data, and password verifiers are omitted.

## Security result

This build has no end-to-end authenticated software chain. Normal API traffic uses
verified TLS and marks 37 of 38 routes as authenticated, but update and recovery
content has no publisher signature. The recovery image also enables root SSH with
password authentication and supplies no persistent packet-filter rules.

Consequences:

- a hostile API response is constrained by TLS only when the endpoint and CA trust
  remain trustworthy, but several response handlers are semantically permissive;
- a hostile update/recovery source can replace executable or boot/root content
  because MD5 supplies corruption detection, not publisher identity;
- a LAN peer that reaches port 22 can attempt root authentication against the
  restored image's credential policy; and
- physical/eMMC access exposes configuration, account data, logs, Wi-Fi state,
  and application data because no storage encryption boundary was found.

Nuve Local protects its own API listener. It does not patch the thermostat OS,
firewall, SSH, bootloader, updater, secondary controllers, or storage.

## Trust boundaries

| Boundary | What the firmware shows | What remains unknown |
| --- | --- | --- |
| Boot, update, and recovery chain | No end-to-end publisher signature on boot, application-update, or recovery content | Details are kept in private research notes |
| Application API | Configured HTTPS base, Qt 6.4/OpenSSL, normal CA/hostname checks, per-call auth boolean, serial-bearing routes | Vendor-side authorization, token issuance/revocation, account isolation, or safe response semantics |
| Local object persistence | JSON/QSettings/INI and filesystem access controls | File authenticity, encryption, transactional replacement, or corruption recovery |
| TI/nRF52832 controllers | UART owners, nRF52832 identity, packet boundaries, and application-side behavior | Secondary firmware integrity, electrical protections, or board-side authorization |
| Nuve Local listener | Local source/Host/serial/route/method/token checks and normal TLS | Protection from a compromised Home Assistant host, thermostat root compromise, or another thermostat OS service |

## Stock API transport and authentication

The application contains 38 direct route literals. Thirty-seven pass the
authenticated flag to the recovered executor. The sole exception is
`api/sync/getSn?uid=%0`, whose response can set the device serial and client state;
it is therefore an unauthenticated identity mutation, not a harmless discovery
call. The complete per-route owner, method, timeout, schema, side effect, privacy
classification, and disposition are in
[api-contract-catalog.md](api-contract-catalog.md).

Several distinct concepts must not be collapsed into “authenticated”:

- the executor's auth boolean controls application request construction;
- `sn` and `uid` query/body values are identifiers and routing/correlation inputs,
  not secrets or authorization proofs;
- TLS authenticates the configured hostname through the system CA bundle, not a
  pinned Nuve key;
- a network-clean response is accepted by several callbacks despite absent,
  wrong-type, mismatched, or semantically dangerous data; and
- the vendor service's account authorization, rate limits, audit, retention,
  tenancy checks, and conflict handling are not present in the firmware corpus.

`NUVE::DeviceConfig` reads the root `endpoint` value from
`/usr/local/bin/device_config.ini`, defaults to the vendor HTTPS base, and writes
the resulting value into `API_SERVER_BASE_URL`. A service-unit environment value
alone is overwritten. The full endpoint, including an explicit port, is retained
and only a missing trailing slash is normalized.

The recovery root contains Qt 6.4's OpenSSL backend and the normal system CA bundle.
No `ignoreSslErrors`, peer-verification disable, or application certificate-pinning
bypass was recovered. This is a useful transport property but not a defense
against a compromised trusted CA, an intentionally changed API base, weak callback
validation, or the separate plaintext update paths.

The application's normal authenticated traffic presents a 64-hex-character device
token observed during local testing. Nuve Local retains only its
SHA-256 verifier. Vendor provisioning, storage, rotation, revocation,
scope, and server-side comparison rules remain unavailable; no broader security
claim is derived from the token's length.

### Response trust hazards

Static analysis and the isolated route emulators establish recurring patterns:

- the unauthenticated serial response mutates two QSettings values and application
  identity;
- installer/customer/job/ZIP responses can persist identity, address, timezone,
  or onboarding state with weak or mismatched correlation;
- warranty writes the old serial before server success and has no failure rollback;
- lock state and plaintext PIN are locally committed before network confirmation;
- schedule fetch/mutation handlers can clear or duplicate effective state through
  missing arrays, permissive success, uncapped retry, or no idempotency token;
- a performance-test schedule/result path can reach ordinary HVAC control even
  when its result POST fails; and
- message, alert, recovery-information, and log-transfer paths disclose private
  state without a recoverable local reason to expose them through Home Assistant.

Knowledge of a route therefore never places it on the local allowlist.

## Thermostat operating-system exposure

The stock recovery image enables remote root administration over SSH with password
authentication and ships no persistent packet-filter rules. Treat TCP 22 as a
high-risk trusted-LAN maintenance surface: after setup, install an SSH key and
restrict the port to explicit administration sources. Nuve Local does not depend on
SSH during normal API operation and does not attempt to change this stock service.

Application Factory Reset is not a root-filesystem restore, and no recovered path
shows it rotating the root credential or SSH host keys. No credential, device-specific
host key, administration key, or transfer secret belongs in Git, diagnostics, command
arguments, or a support report. Credential-level analysis and the exact image state
are kept in private research notes.

## Software authenticity and rollback

Application updates, recovery-file updates, and boot-time factory restore carry no
publisher signature, and the recovered chain has no A/B slot, transactional commit, or
verified rollback. A hostile update or recovery source could therefore replace
executable or boot/root content. Nuve Local does not expose update, recovery, or
reset commands. Step-level ordering and failure states are kept in private research
notes.

## Private data and disclosure paths

The firmware processes more private state than the 39 exposed Home Assistant
entities imply.

| Data class | Examples retained or transmitted by the firmware | Local disposition |
| --- | --- | --- |
| Device/network identity | serial, hardware UID/fuses, API token, Wi-Fi SSID/profile, IP/network details, firmware/version state | Serial is configured privately; token verifier only; raw profiles/captures excluded |
| Household/HVAC state | room/environment values, setpoints, modes, stages, wiring/equipment topology, schedules, holds, vacation, events | Validated fields only; complete device records stay in Home Assistant private storage |
| Location/weather | ZIP, address, city/state/country IDs, timezone, weather/design temperatures | Installer/location routes unsupported; only configured finite/fresh weather projection |
| Account/customer | email, name, phone, membership/enabled flags, job ID, installer/customer records | Unsupported and never exposed as entities or diagnostics |
| Lock/security | four-character screen PIN, locked state, master-unlock path, SSH verifier/keys, transfer authentication material | Lock routes unsupported; no credential values retained in repo or diagnostics |
| Messages/alerts | message body/rich text, timestamps, read state, device-alert types | Inbox/alert sink unsupported; event targets are schema-checked then discarded |
| Recovery/update | filenames, sizes, checksums, selection state, application/updater journals | Reports and update commands unsupported; documentation omits private values |
| Contractor/service | brand, phone, logo URL/image, technician-access URL, serial-bound external contact link | Only constrained configured metadata/logo projection is supported |

Important disclosure paths are:

- authenticated Settings, Auto, monitor, event, sensor, stage, alert, account,
  installer, schedule, lock, performance-test, and recovery-report API traffic;
- current/forecast/design weather responses consumed from the API base;
- contractor metadata followed by a logo fetch that does not forward the bearer
  header in stock firmware;
- HTTP application and recovery downloads containing a stable serial-derived
  identifier or device/version selection data;
- the Send Log workflow, which collects `appStherm` and updater journals and
  transfers them to a vendor endpoint using embedded authentication material; and
- persisted files, NetworkManager profiles, QSettings, protobuf queues, and logs
  exposed by root or raw-storage access.

The Send Log action is an external disclosure, not a read-only diagnostic. It is
never invoked by Nuve Local. Its credentials and raw journal contents remain in the
private corpus only and are never reproduced in documentation or tests.

## Nuve Local compensating controls

Nuve Local implements 15 of the 38 direct firmware routes, with additional
narrowing inside several rows. Its listener:

- makes no outbound network requests and has no cloud fallback;
- validates the configured peer address, Host, serial, route, and method;
- optionally accepts one forwarded client address only from one configured
  proxy peer and rejects direct header spoofing or chains;
- learns the first strictly formed device token only from the expected thermostat
  source during an explicit five-minute pairing window, then closes the window,
  stores only its SHA-256 verifier, and uses a constant-time comparison;
- either terminates normal TLS with an explicit configured certificate or accepts a
  restricted HTTP hop from one exact trusted proxy that terminated the stock
  thermostat's normally verified TLS session;
- limits bodies to one MiB, each request to ten seconds, and concurrent work to
  four requests;
- disables access logging and does not persist raw bodies;
- schema-validates event uploads and discards event targets instead of logging,
  storing, diagnosing, or exposing them;
- stores complete baselines only in Home Assistant private atomic storage and
  excludes them from diagnostics;
- records only a size-limited timeline of event type, family, outcome, and duration;
- signs the stock unauthenticated logo-download URL with an HMAC bound to the
  paired token fingerprint and serial, while still enforcing source/Host/serial;
- fails unknown routes explicitly; and
- durably journals control uncertainty before delivery and requires strictly
  post-delivery, field-owning evidence before success.

The 15-route count does not mean 15 general-purpose capabilities. Design
temperatures are an empty non-applying response, Wi-Fi-off is a report-only
acknowledgement, events are discarded, and command reporting is limited to the
allowlisted monitor-recovery command. Settings/Auto writes remain gated by supported
firmware identity, complete coherent baselines, schedule authority, revisions,
fresh authenticated traffic, and later monitor confirmation.

These controls do not make it safe to expose the listener to the Internet. They
also cannot protect an already root-compromised thermostat or HA host, authenticate
an update, fix SSH, or replace network segmentation.

## Corpus, repository, and diagnostic handling

The private corpus remains outside the worktree. It contains complete device and
recovery images, configuration, deleted-inode recovery, reconstructed diagnostic
overlays, captures, and private indexes. A `.gitignore` rule is not a
confidentiality, backup, scanning, or deletion boundary.

Only these derived artifacts belong in Git:

- public hashes and sizes;
- schemas and field names needed to explain behavior, without private values;
- function addresses and call-path descriptions tied to the application hash;
- tools that emit metadata or credential states without content; and
- synthetic fixtures containing no real identifiers, endpoints, credentials,
  network details, logs, or household state.

Never commit firmware images, extracted binaries, raw decompiles, password
verifiers, SSH material, device tokens, serials, Wi-Fi profiles, raw traffic,
customer data, or journals.

## Residual security unknowns

The following remain unverified: live listening sockets and firewall state on the
running thermostat, vendor API token lifecycle and server-side authorization,
whether other firmware builds reuse the same stock credential, other daemons'
live LAN binding, at-rest protection on the eMMC, and secondary-controller
boot/update authentication. They are not a reason to probe unrelated devices, test
more passwords, intercept updates, contact vendor services, or change a running
thermostat. Detailed evidence requirements are kept in private research notes.
