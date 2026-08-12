# Firmware 1.5.8 security and privacy

This review covers recovery `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`
and the files in [Artifact inventory](artifact-inventory.md). Private keys,
identifiers, endpoints, logs, customer data, and password verifiers are omitted. The
stock maintenance login appears only in [Deployment and rollback](deployment.md).

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
- physical/eMMC access exposes configuration, account verifier, logs, Wi-Fi state,
  and application data because no storage encryption boundary was found.

Nuve Local protects its own API listener. It does not patch the thermostat OS,
firewall, SSH, bootloader, updater, secondary controllers, or storage.

## Trust boundaries

| Boundary | What the firmware shows | What remains unknown |
| --- | --- | --- |
| Boot ROM to U-Boot | IVT layout and ROM-loaded U-Boot region; CSF pointer is zero | No authenticated-boot signature or secure chain into kernel/root |
| U-Boot to Linux | Raw FAT `zImage`/DTB load and `gzwrite` restore of p1/p2 from p4 | No signature, signed manifest, A/B slot, transaction, or rollback |
| Application API | Configured HTTPS base, Qt 6.4/OpenSSL, normal CA/hostname checks, per-call auth boolean, serial-bearing routes | Vendor-side authorization, token issuance/revocation, account isolation, or safe response semantics |
| Application update | HTTP metadata/payload, serial-derived identifier, MD5 before and after write | Publisher authenticity, archive-member policy, atomic installation, or rollback |
| Recovery-file update | HTTP download, manifest-selected files, attacker-selected MD5, in-place p4 copy | Publisher authenticity, pairwise atomicity, or safe later p1/p2 restore |
| Local object persistence | JSON/QSettings/INI and filesystem access controls | File authenticity, encryption, transactional replacement, or corruption recovery |
| TI/nRF52832 controllers | UART owners, photographed nRF52832 identity, packet boundaries, and application-side behavior | Secondary firmware integrity, electrical protections, or board-side authorization |
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

## Recovery-root network surface

The offline security inventory found the following state in the clean recovery root:

| Item | Exact recovery-image state | Security meaning |
| --- | --- | --- |
| SSH activation | `sshd.socket` is enabled, `ListenStream=22`, `Accept=yes`, and the per-connection service runs `sshd -i` | Port 22 is not scoped to a particular address by the unit |
| Root login | `PermitRootLogin yes` | Root login is explicitly permitted |
| Password auth | No explicit `PasswordAuthentication no`; the shipped configuration identifies enabled password auth as its default | Password authentication is not fail-closed in this image |
| Empty passwords | `PermitEmptyPasswords yes`, but 0 of 27 preserved accounts has an empty verifier field | No preserved empty-password account was found; the permissive setting is still unsafe if one appears |
| Account state | 26 accounts locked; root is the only account with a nonempty, nonlocked verifier | The stock root password is documented for device owners; the verifier itself is not reproduced |
| Authorized keys | No root `authorized_keys` file in the pristine image | Factory image does not provide a key-only root boundary |
| Host keys | No static host private/public keys in the pristine image | `sshdgenkeys` generates RSA, ECDSA, and ED25519 host keys on demand using temporary files, syncs, and renames |
| Packet filter | Enabled `iptables.service` loads a zero-byte rules file with SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | The supplied root contributes no persistent IPv4 allow/deny rules; live boot/runtime state could still differ |

The systemd socket inventory also found `rpcbind.socket` listening only on
`/var/run/rpcbind.sock` and `systemd-networkd.socket` listening on local route
netlink. Neither unit declares a network TCP/UDP port. `ntpd.service` is separately
enabled and launches `ntpd` without an interface restriction; its configuration
has a local-clock source and bare `restrict default`. Whether it binds/responds on
Wi-Fi in the live target remains unknown because it was not checked on the running
thermostat.

The recovery image contains the root verifier but no system-script path that
regenerates it on first boot. `run-postinsts` has no retained password-changing
script to execute. SSH host-key regeneration is handled separately. A U-Boot factory
restore therefore reinstates the verifier found in this root image, while missing
host keys are generated later. Other recovery versions and devices may differ and
must be checked separately.

The touchscreen application Factory Reset is not a root-filesystem restore. It
clears application/registration/Wi-Fi/log state and reboots, so no recovered path
shows it rotating the root verifier or replacing the SSH host keys. The application
also contains a separate log-transfer SSH helper and embedded transfer
authentication material. That is external disclosure machinery, not evidence of a
local root-password rotation path.

### Stock-OS disposition

Port 22 should be treated as a high-risk trusted-LAN maintenance surface unless a
read-only check of the running system shows otherwise. External
segmentation should restrict it to an explicit administration source. Nuve Local
does not depend on SSH during normal API operation and does not attempt to change
this stock service.

No password verifier, device-specific host key, private/public administration key,
or transfer credential belongs in Git, diagnostics, command arguments, or a support
report. The known stock password appears only as deployment/security documentation;
it must never be interpreted as a device-unique secret or proof of cross-version
reuse. No further password testing is required for Nuve Local operation.

## Software authenticity and rollback

Three independent paths fail the publisher-authenticity requirement:

1. **Application ZIP.** Metadata and archive are fetched over HTTP. The expected
   checksum is supplied by the same untrusted metadata path. MD5 is checked in
   memory and after write, then a shell helper overwrites `/usr/local/bin` in place.
2. **Recovery files.** Manifest-selected files are fetched over HTTP and validated
   with manifest-supplied MD5 before in-place, source-removing copy into p4.
3. **Boot restore.** U-Boot checks only that `boot.gz` and `root.gz` can be loaded,
   then writes boot before root. The IVT CSF pointer is zero and no signed kernel,
   DTB, root, or recovery manifest gate was found.

The hardware RNG/DCP nodes and enabled `rngd.service` do not change this result;
availability of cryptographic hardware is not evidence that these flows use a
publisher signature. There is no A/B slot, transactional commit, verified rollback,
or safe power-loss guarantee in the recovered chain. Nuve Local does not expose
update, recovery, or reset commands.

See [application-update.md](application-update.md),
[recovery-updater.md](recovery-updater.md), and
[boot-update-recovery.md](boot-update-recovery.md) for ordering and failure
states.

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

## Reproduction

After verifying and mounting a private decompressed root read-only, run:

```bash
.venv/bin/python scripts/inventory_recovery_security.py \
  <read-only-recovery-root-mount>
```

The tool reads only fixed SSH/systemd/iptables/account files. It emits explicit
SSHD directives, enabled socket/unit metadata, rule-file metadata, aggregate
credential-state counts, and the conventional root account's state class. It never
emits a verifier, arbitrary account name, key, authorized-key content, or embedded
credential. Unit fixtures assert that representative secret values cannot appear
in its JSON output.

## Residual security unknowns

| ID | Unresolved fact | Consequence | Evidence required |
| --- | --- | --- | --- |
| SEC-U01 | Live listening sockets, iptables/ip6tables state, SSH directives, root/key state, and drift from the clean recovery image | LAN exposure can differ from the static root | Approved local-console, read-only checks of `ss`, firewall, units, and credential classes |
| SEC-U02 | Vendor API token issuance, storage, rotation, revocation, scope, server authorization, audit, rate limits, retention, and tenancy checks | Authenticated flag and token length cannot prove backend security | Vendor design/source or isolated service account under separate approval |
| SEC-U03 | Whether other recovery builds and devices reuse the recovered 1.5.8 root credential | One recovery image and one owned reference unit say nothing about fleet-wide reuse | Redacted per-image comparison or vendor provisioning information; never publish verifier material |
| SEC-U04 | `ntpd`, resolver LLMNR/mDNS, rpcbind activation, and other daemon live binding/response behavior | Additional LAN surfaces may exist outside socket-unit declarations | Cloned target boot with packet/socket observation, or separate approved read-only live check |
| SEC-U05 | At-rest protection and secure deletion on the photographed `THGBMTG5D1LBAIL` eMMC | Raw storage may retain configuration, logs, profiles, and deleted data | EXT_CSD/configuration and power-rail evidence plus cloned-media forensic tests |
| SEC-U06 | Secondary-controller boot/update/authentication and debug interfaces | TI/nRF52832 compromise could bypass Linux-side policy | Exact secondary firmware, schematic/BOM, and isolated donor-board analysis |

These questions are not a reason to probe unrelated devices, test more passwords,
intercept updates, contact vendor services, or change a running thermostat. Each row
states what would be needed to answer it.
