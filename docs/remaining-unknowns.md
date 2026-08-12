# Open questions for firmware 1.5.8

This register lists the remaining questions for `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`
and the [artifact inventory](artifact-inventory.md).

## Overall result

The Linux application, its 38 API routes, persistence, update and recovery paths,
bootloader, and Linux-side hardware buses are well mapped. Full-device understanding
still needs TI and nRF52832 firmware, schematics, vendor-server behavior, missing
version files, and destructive tests that should use disposable hardware or storage.

Nuve Local contains these gaps by leaving affected features read-only or unavailable.
The current gaps do not weaken supported 1.5.8 controls.

## Resolution states

| State | Meaning |
|---|---|
| `open-local` | Existing private artifacts and isolated tooling can make progress without touching a device or service. |
| `needs-clone` | Requires a disposable copy of the filesystem, storage, or target system instead of the connected thermostat. |
| `needs-approval` | A read-only check or a small reversible device test may answer the question, but it has not been approved. |
| `blocked-artifact` | The required firmware, schematic, build, or hardware identity is unavailable. |
| `blocked-vendor` | Only vendor service/design/source evidence can establish the claim. |

## Register

`Safety / current boundary` shows how each unknown affects Nuve Local. Contained
features are read-only, unavailable, or blocked by a specific check.

| ID | Subsystem and unresolved claim | Safety / current boundary | State | Evidence required |
|---|---|---|---|---|
| SCH-U01 | Filesystem/eMMC schedule and hold behavior during power loss, vendor conflict rules, and live restoration behavior | High; contained by the active-or-unknown schedule safety gate and unsupported schedule routes | `needs-clone` plus `blocked-artifact` plus `blocked-vendor` plus `needs-approval` | Fault-injected disposable storage matching the photographed `THGBMTG5D1LBAIL`, its EXT_CSD and power-rail behavior, vendor conflict information, and an approved reversible device test only if still necessary |
| PERSIST-U01 | Arbitrary combined nested-graph corruption, partial valid writes, physical eMMC power-loss guarantees, external recovery intervention, and cross-version schema migration | High for restart recovery; representative exact-target corrupt graphs and populated V1/V2/hold round trips are A+B, and Nuve Local does not copy this design | `needs-clone` plus `blocked-artifact` | Fault-injected disposable ext4 storage matching the photographed `THGBMTG5D1LBAIL` plus exact EXT_CSD/rail behavior; another complete exact-version artifact for migration |
| LOCK-U01 | Vendor authorization, storage, audit, rate limits, network-error parsing, brute-force resistance, and recovery from crashes or corrupt data | Medium/privacy; contained because lock routes and controls are unsupported | `open-local` plus `blocked-vendor` | Executor/error harness and crash model; vendor design or an approved isolated backend test |
| SENSOR-U01 | Secondary-radio pairing, identity, calibration, battery/signal ingestion, and vendor interpretation of the literal UID/lossy location projection | High if exposed; remote-sensor CRUD is disconnected and unsupported, but onboard processed values still cross the secondary boundary | `blocked-artifact` plus `blocked-vendor` | Exact secondary firmware and protocol plus vendor interpretation; application-side disconnected CRUD is already A+B |
| INST-U01 | Vendor authorization, lookup correlation and rate limits, warranty transaction and rollback, and private-data retention and audit behavior | High/privacy; contained because installer and warranty routes are not exposed | `blocked-vendor` | Vendor service information or an approved isolated service account; never change a production identity for research |
| PERF-U01 | Vendor eligibility/result policy and physical TI/controller/contact/equipment behavior during the recovered performance test | Critical; contained because both routes are not exposed and no connected-HVAC test is approved | `blocked-vendor` plus `blocked-artifact` | Vendor policy/service implementation, secondary-controller firmware and schematic, and an electrically isolated bench if ever approved |
| BOOT-U01 | Physical identity and polarity of recovery GPIO102 and likely S7 control | Critical for reboot/recovery; contained because recovery is not exposed | `blocked-artifact` | Schematic/BOM or separately approved read-only physical correlation with HVAC isolated |
| BOOT-U02 | Power-loss behavior during U-Boot `gzwrite`, second GPIO-read failure behavior, and end-to-end restore result | Critical; contained because no boot/recovery write is exposed | `needs-clone` | Cloned removable/eMMC media or faithful emulation with fault injection; never live eMMC |
| UPD-U03 | Target-system unzip/rsync/process interruption, the unusual single `-n 19` argument, filesystem durability, and partial in-place replacement outcomes | Critical; contained because application and recovery updates are not exposed | `needs-clone` | Disposable target filesystem with the original binaries, service/process model, and interruption/power-loss injection |
| HW-U01 | Exact TI MCU/firmware, nRF52832 firmware, transceivers, schematic/BOM, terminal drivers, and TI heartbeat/reset implementation | Critical for full physical-control claims; photographs establish the installed nRF52832 but the application UART boundary cannot prove either secondary implementation or contact behavior | `blocked-artifact` | Exact secondary firmware and schematic/BOM; isolated donor-board instrumentation only under separate approval |
| GPIO-U01 | GPIO21/22 exact pads/nets/pulls and fresh-boot versus retained sysfs behavior after the invalid direction write | Medium/availability; neither pin is used by Nuve Local | `blocked-artifact` plus `needs-clone` | Schematic/kernel source and cloned-kernel sysfs harness; optional isolated logic trace |
| NRF-U01 | Exact sensor/ToF variants, driver/library versions, optical geometry, algorithms, calibration, sentinel/warm-up behavior, and radio pairing implementation | High because processed sensor values can influence UI/control; U18 establishes an nRF52832-QFAA while application scaling and the transported subset are known | `blocked-artifact` | nRF52832 firmware, vendor protocol, schematic/BOM, and isolated sensor fixtures |
| WDG-U01 | TI-side heartbeat/reset effect and whether the enabled i.MX6 watchdog is armed in the deployed system | High/availability; application watchdog call paths are mapped, physical reset consequence is not | `blocked-artifact` plus `needs-approval` | TI firmware plus a redacted read-only boot/watchdog report or a cloned target harness |
| SEC-U01 | Current sockets, firewall, SSH/account/key state, and differences from the clean recovery root | Critical/security; static recovery posture is known, current exposure is not | `needs-approval` | Read-only local-console checks of sockets, firewall, units, and credential classes; never reveal or test a password verifier |
| SEC-U02 | Vendor token issuance, storage, rotation, revocation, scope, authorization, audit, rate limits, retention, and tenancy | High/privacy; vendor services are not a safety boundary and private routes stay unavailable | `blocked-vendor` | Vendor design information or an approved isolated service account |
| SEC-U03 | Reuse of the recovered 1.5.8 root credential across other recovery builds and devices | Critical/security; the 1.5.8 recovery-image match and owned reference-unit login say nothing about fleet-wide reuse | `blocked-vendor` plus `blocked-artifact` | Redacted per-image comparison or vendor provisioning information; never publish verifier material |
| SEC-U04 | Live binding/response behavior of `ntpd`, resolver LLMNR/mDNS, rpcbind activation, and daemons not represented by network socket units | Medium/security; static unit inventory alone cannot prove runtime exposure | `needs-clone` or `needs-approval` | Cloned target boot with socket/packet observation, or separately approved read-only live capture |
| SEC-U05 | Exact `THGBMTG5D1LBAIL` eMMC at-rest protection, discard behavior, and secure deletion | High/privacy; the photographed model is known, but configuration, logs, profiles, and deleted data may remain recoverable | `blocked-artifact` plus `needs-clone` | Exact EXT_CSD/configuration state, power-rail behavior, and cloned-media forensic tests |
| SEC-U06 | Secondary-controller boot/update authentication and debug interfaces | Critical/security; compromise could bypass Linux policy and directly affect HVAC | `blocked-artifact` | Exact TI and nRF52832 firmware, schematic/BOM, and isolated donor-board analysis |
| VER-U02 | Native body parity outside previously targeted integration paths | High only for cross-version support; addresses are already treated as hash-specific | `open-local` | Hash-bound dual-project normalized body/call/state comparison by symbol, never reused address |
| VER-U03 | Complete clean 1.5.7.4 root, kernel, DT, services, and update-container comparison | High only for 1.5.7.4 platform claims | `blocked-artifact` | Reacquire the update or a complete clean root and inventory it separately from the damaged live snapshot |
| VER-U04 | Reproducible 1.6.1.1 application and update behavior | High because v0.6 historically allowlisted it without the files now available | `blocked-artifact` | Reacquire files matching the recorded hashes and repeat the artifact, static, and protocol analysis before renewing support |
| VER-U05 | Android/mobile protocol differences | Low for thermostat-local operation; mobile endpoints are outside the thermostat sync contract | `blocked-artifact` | Reacquire and hash the historical APK splits and analyze them as a separate target |
| LIVE-U01 | Current deployed revision, entity set, service health, schedule state, storage, and telemetry after later Home Assistant or network changes | High for a present-tense deployment claim; the live ledger records the 2026-08-11 check and rollback, while static firmware findings do not change with deployment drift | `needs-approval` | Repeat the read-only checks for any claim made after 2026-08-11; describe and approve any live change separately |

## What is already established

- All 38 direct exact-1.5.8 API route literals have an application owner, client
  contract, material-consequence summary, privacy class, and Nuve Local disposition.
- The QV4 event boundary is exhaustively enumerated: 1,128 recognized handlers in
  198 units. Exact closure traversal and schema-4 operation summaries produce 1,115
  named-effect maps, nine effect-free stubs, one read/computation-only handler, and
  three exact-reviewed diagnostic indexed-state writes. All 12 constructor actions
  resolve to `Date`; zero dynamic/indexed effect targets or effect domains remain.
- Every changed 1.5.7.4-to-1.5.8 QV4 unit has a binding/translation-aware semantic
  disposition; `VER-U01` is closed with the null fallback retained as a known
  difference rather than an unknown.
- The absence of publisher authentication in application update, recovery-file,
  and U-Boot restore paths is proven. Nuve Local therefore does not expose those
  operations; publisher authenticity itself is not an open question.
- The i.MX6-to-TI/NRF UART ownership and Linux-side device tree are exact, and the
  installed mainboard's U18 marking establishes an nRF52832-QFAA. Missing TI and
  nRF52832 implementations remain `HW-U01`/`NRF-U01`, not filled by analogy.
- Existing supported Settings, Auto, monitor, weather, display, fan, and HVAC paths
  retain their A+B+C/D evidence and fail-closed confirmation rules.

## Next safe closure order

1. Continue `SCH-U01` only with fault-injected disposable storage, missing physical
   media evidence, or vendor evidence. Do not enable schedules.
2. Continue `PERSIST-U01` only with combined-fault tests on disposable target storage;
   the existing runtime tests already cover representative corruption cases.
3. Optionally continue non-current-support `VER-U02` with normalized native body/call/state comparison without
   changing firmware 1.5.8 support.
4. Continue pad ownership, firmware extraction, and physical-media work only on an
   electrically isolated donor board; the photographed installed unit is not a
   continuity, debugger, readback, or fault-injection target.
5. Treat all `needs-clone`, `needs-approval`, `blocked-artifact`, and
   `blocked-vendor` rows as separate future decisions. None is authority to touch a
   thermostat, Home Assistant, network, Forgejo, or vendor service.
