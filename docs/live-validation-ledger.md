# Reference-thermostat validation history

These are dated tests on the reference thermostat, not its current state.

The canonical firmware for the rows below is recovery `appStherm` 1.5.8 SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
The rollback release was Nuve Local v0.6.0 commit `572b8f6`, deterministic package
SHA-256 `8ec6954388f140724aba4b6581318215779c730a83b6b939b8d237a48d449778`,
deployed as an exact 28-file component on Home Assistant 2026.8.1. The historical
v0.8.0 candidate described below was temporary; v0.8.0 was later released and
installed before the v0.8.1 pass.

## Latest recorded state

The current point-in-time record is dated 2026-08-11. The final v0.8.1 29-file
component is installed byte-for-byte with local/deployed content digest
`dcb5f59befb468d6263a0104fdb5b3f709bc7c5e86379d50024d1d0c479ec082`.
All 75 Nuve registry entries are present: the 34 v0.8.0 installer/HVAC diagnostics
remain disabled, while the new time-format and proximity controls are enabled. The
four rejected candidate entity records were removed after final activation, with the
pre-test registry retained in the private rollback. Persistence is healthy, monitor
authority is fresh, the command queue is idle, no uncertainty or Nuve Repair is
present, and both HVAC stages are inactive. The thermostat reports Cool mode, fan On,
no schedule, Celsius/raw `0`, automatic clock On, proximity Off, 12-hour format, and
a 22 °C target.

This was the state at the end of that test window. Home Assistant, integration,
thermostat, or network changes may have changed it since then; current-state claims
must be checked again.

## 2026-08-11 v0.8 candidate pass

The temporary pre-release v0.8.0 candidate package had SHA-256
`c9814424de931bd83c285e5fd9853140e1ca5112713a3a560a6b1608f020bca5`.
It registered 39 new entities disabled by default: the 34 read-only installer/HVAC
diagnostics retained for v0.8.0 and five proposed advanced preference controls. The
candidate loaded with zero Nuve Repairs. Only the five advanced candidates were
enabled for the test; the installer/HVAC diagnostics remained disabled and
read-only.

The first speaker request, 50→49, was delivered, but the later complete Settings
owner retained speaker 50. During that window the target changed from 21 to 20 and
the raw temperature-unit value changed from Celsius/`0` to Fahrenheit/`1`, violating
the unrelated-state stop condition. No unit, time-format, sleep-logo, or proximity
request was attempted. The operator physically restored Celsius/`0` and selected a
22 °C target; Home Assistant observed both values with fresh NoSchedule authority,
both stages idle, and no uncertainty or persistence fault.

The same pass identified the disabled-Vacation minimum emitted as exactly 39 °F
(`3.888888888888889` °C). The candidate accepted that device-originated value without
widening any command range. Two later complete canonical snapshots normalized both
the current and previous-good saved minima to 4 °C, allowing the exact v0.6.0
rollback to validate its private store. After rollback, the source tree matched its
preserved copy byte-for-byte, Home Assistant passed its configuration check and
restart, the registry returned to 39 Nuve entities, and zero Nuve Repairs remained.
All temporary candidate archives, staging directories, and private rollback copies
were then removed.

The failed speaker owner and unrelated target/unit drift are negative D evidence for
the advanced group. Speaker, unit, time format, sleep-logo, and proximity therefore
remain unexposed in v0.8.0.

## 2026-08-11 v0.8.1 candidate pass

The final v0.8.1 component archive has SHA-256
`c28a64d3b4df0ac4f58096240c1c5931b0075f4c54221323ea8a0efc1b913909`.
A private rollback captured the exact installed v0.8.0 component, Nuve baseline
store, and Home Assistant entity registry before activation. The candidate loaded
on Home Assistant 2026.8.1 with all six proposed entities enabled for qualification,
fresh NoSchedule authority, Cool mode, fan On, a 22 °C target, both stages idle, and
no uncertainty, persistence fault, or Nuve Repair.

Time format changed `0→1→0` and proximity changed `false→true→false`. Each operation
was confirmed by a strictly later complete Settings owner in both directions; only
the requested setting changed, while target, mode, fan, system, Vacation, backlight,
Auto bounds, schedule, and stages remained stable. Both controls were restored and
qualify for v0.8.1.

Sleep-logo remained at its old value in the first complete owner and failed.
Automatic clock initially failed the same way, but a later upload showed the Off
value had applied after Home Assistant reported failure; the original On value was
restored. Temperature unit changed from Celsius/raw `0` to Fahrenheit/raw `1` and
the expected disabled-Vacation floor changed from 4 °C to exact 39 °F
(`3.888888888888889` °C). A later sample then moved the target from 22 to 20 °C and
activated two-stage cooling despite NoSchedule. Celsius/raw `0` and 22 °C were
restored, followed by idle stages and fresh authority. Speaker was not repeated after
its v0.8.0 failure and this reproduction of delayed unrelated drift. Firmware
analysis separately proves that the Settings server-reply handler ignores
`currentTimezone` and `effectDst`, so neither has a direct command path.

The final candidate therefore retains only enabled-by-default time-format and
proximity entities. Speaker, temperature unit, sleep-logo, automatic clock, timezone,
and DST remain explicitly outside the runtime allowlist.

## Historical reference-unit evidence

Dates below identify the 2026-08-09 through 2026-08-10 validation window.
“Restoration” is used only when the records show that the original value was
restored, not simply that the service later appeared healthy.

| ID | Area | Grade | Observation or operation | Confirmation | Restoration | Result |
|---|---|---|---|---|---|---|
| LV-001 | API base, TLS, authentication, and Settings/Auto/monitor/weather transport | C+D | Reference firmware reached the local listener through the configured route and completed authenticated protocol flows | Configured source, Host, serial/token verifier, route/method, parsed envelope, and saved starting state | Original configuration and recovery files were preserved before activation; no vendor fallback exists | Proven for the recorded deployment only |
| LV-002 | Release/deployment parity | C | v0.6.0 was installed as the deterministic 28-file package on Home Assistant 2026.8.1 | Complete source/deployed inventory and hashes, integration load, 39 registered entities | No mixed-file deployment was observed; the 2026-08-11 rollback matched its preserved tree byte-for-byte | Point-in-time PASS; later parity is `LIVE-U01` |
| LV-003 | Pairing, persistence, and fresh control authority | C | Complete device-originated Settings and Auto baselines plus fresh full monitor state established readiness | Private atomic HA Store, source-time ordering, full/sparse authority, idle queue and no uncertainty | HA-only restart recovery re-established authority without replaying stored HVAC state | Historical PASS; current freshness is `LIVE-U01` |
| LV-004 | HA-only restart resynchronization | C | Two non-applying delivery-aware polls forced a fresh full monitor transition; one recorded release restart became control-ready 37.7 seconds after loader discovery | Fresh post-restart full monitor plus compatible stored Settings/Auto/equipment baselines | No HVAC desired state was replayed from storage and no device restart was required | Proven algorithm and historical observation; not rerun here |
| LV-005 | Setpoint and ordinary HVAC modes | D | Reversible target/mode changes exercised the exposed Cool/Heat/Auto/Off model; a Cool-stage transition was physically observed | Post-delivery monitor and Settings data confirmed the requested field, rather than HTTP success alone | Original target/mode were restored and confirmed; unrelated fields stayed unchanged | Proven within exposed ranges/modes; no command run here |
| LV-006 | Consecutive Auto bounds | D | The whole-degree Auto range was changed, restored, and then changed a second time | Auto data plus a newer monitor update confirmed both deliveries; stages remained inactive | The changed range was confirmed in 8.49 seconds and the original range restored in 11.10 seconds | Proven for firmware 1.5.8; no command run here |
| LV-007 | Fan mode and circulation without a schedule | D | Fan On and one circulation-duty change were delivered while fresh monitor data reported `NoSchedule` | A complete post-delivery Settings upload contained the full fan pair; physical fan telemetry was not used as configured-state confirmation | Original fan configuration was restored and confirmed | Proven only with fresh `NoSchedule` state |
| LV-008 | Active-schedule Settings hazard | D | One fan-duty change under an active schedule showed that a whole Settings response could apply fan state and clear the schedule | A later device Settings upload exposed the change | The original duty was restored under `NoSchedule`; this incident led to the schedule write block | Hazard confirmed; schedule writes remain unsupported |
| LV-009 | Backlight shade/color | D | One reversible complete-backlight round trip moved from color to a fixed shade and back | A complete post-delivery Settings upload contained the backlight object | Original color/value/shade object was restored; mode, target, fan, schedule, and installer fields remained unchanged | Proven path; no display command run here |
| LV-010 | Saved screen brightness | D | One whole-step brightness change and return exercised the general Settings path | Complete post-delivery general-Settings upload, with inactive HVAC stages during the test | Original brightness was restored; unrelated HVAC/fan state remained unchanged | Proven path; no display command run here |
| LV-011 | Weather and forecast display | C | Current conditions and the daily forecast populated the thermostat UI; high-first card ordering was visibly confirmed | Current/daily request parsers plus on-device page rendering | No thermostat persistence or HVAC value was changed | Historical display check; provider freshness changes over time |
| LV-012 | Contractor branding and QR separation | C+D | Replacement wordmark rendered while the photographed Contact Contractor QR remained unchanged | Contractor metadata/logo route and separate QV4 consumers for branding, Technician Access QR, and hard-coded Contact Contractor URL | Branding result was confirmed; no unsupported Contact Contractor rewrite occurred | Branding works; the two QR paths are separate |
| LV-013 | Event-queue privacy and draining | C | Valid event protobuf batches were accepted and drained | Schema validation and sender-side successful-delivery queue removal | Targets were discarded rather than logged, stored, or exposed as HA state | Historical PASS; no raw events retained in this repo |
| LV-014 | IAQ category and pressure observations | C | Redacted long-term history showed populated values, reporting cadence, and sentinels | NRF-to-QML/monitor producer chains plus observed Home Assistant entities | Read-only observation; no calibration or sensor setting was changed | Transported category and positive-pressure values are understood; board algorithm remains `NRF-U01` |

## Explicitly absent live proof

No row in this ledger supplies C or D evidence for:

- schedule fetch/add/edit/delete, holds, migration, overlap, or reboot persistence;
- screen lock/PIN or master-PIN behavior;
- remote-sensor pairing, add/edit/remove, radio identity, or battery/signal state;
- installer, address/customer/job/warranty, registration, or device-forget workflows;
- performance-test scheduling/results or any low-level relay/equipment test;
- application update, recovery-file copy, factory reset, factory restore, or
  bootloader/partition writes;
- SSH/password strength, live firewall/socket exposure, vendor token policy, or
  secondary-controller debug/update trust; or
- 1.5.7.4 or 1.6.1.1 operational parity beyond the exact historical evidence stated
  in [version-differences.md](version-differences.md).

Those omissions are intentional. Static or emulated A+B evidence does not become
live proof, and a dangerous path does not need a connected-device test to justify
leaving it unavailable in Nuve Local.

## Requirements for a future current-state refresh

A separately authorized read-only refresh should establish, without issuing a
thermostat command:

1. exact deployed component revision and complete source/deployed hash parity;
2. Home Assistant version, integration load, expected entity registry count, and
   absence of setup/restart errors;
3. fresh authenticated contact and full monitor authority, with source timestamps;
4. current schedule/hold authority and the active-or-unknown fail-closed gate;
5. idle pending/delivered command state and absence of uncertainty;
6. persistence health and valid private storage envelope without copying its values;
7. current HVAC stage/fan output telemetry, clearly labeled as telemetry rather than
   physical airflow/contact proof;
8. rejected-request/error counters and size-limited logs without state values; and
9. no unexpected network, TLS, DNS, proxy, source, Host, or allowlist drift.

Any proposed state change after that refresh requires a new mutation manifest with
the exact start value, request path, persistence/HVAC consequences, field-owning
confirmation, rollback, stop conditions, and reason static/emulated evidence is
insufficient. Delivered-but-unconfirmed work must never be retried automatically.

## Owners

- [traceability.md](traceability.md) owns requirement-to-code/test links.
- [firmware-evidence.md](firmware-evidence.md) owns protocol and confirmation
  semantics.
- [remaining-unknowns.md](remaining-unknowns.md) owns `LIVE-U01` and all unavailable
  evidence.
- This ledger records only the redacted point-in-time device observations and their
  boundary.
