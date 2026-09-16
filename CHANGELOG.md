# Changelog

## 0.0.4 - 2026-09-15

### Fixed

- Require confirmed `NoSchedule` telemetry for Auto-range writes, matching
  Settings-family commands. Readiness indicators and block reasons now report
  active or unknown schedule authority. Commands are rechecked immediately
  before the response body is sent, including when a schedule activates after
  queuing or during persistence.
- Start the thermostat listener before optional forecast retrieval, bound
  forecast requests, coalesce refresh tasks, and cancel owned tasks on unload.
  Recoverable listener bind failures now raise `ConfigEntryNotReady`, and
  deployment status/diagnostics work when runtime data is missing. Failed-setup
  cleanup is idempotent when Home Assistant subsequently runs unload callbacks.
- Separate the thermostat-facing HTTPS port from the Home Assistant listener
  port. Contractor-logo URLs use the external address. Existing reverse-proxy
  entries leave an unknown external port unset until configured; direct TLS
  always derives its port from the listener. Missing optional logo configuration still
  does not block setup.

### Compatibility

- Add real Home Assistant ConfigEntry lifecycle tests and a disposable
  compatibility gate covering 2026.7.4 and current stable 2026.9.2.
  Config-flow HTTP schema checks use Home Assistant 2026.9's `probatio`
  serializer with a fallback for 2026.7.4. The advertised minimum remains
  2026.7.4. The development pin is 2026.9.2.

### Maintenance

- Share one Celsius command validator between the climate entity and runtime.
- Give the HTTP listener a public persistence/transaction interface instead of
  private runtime internals.
- Label pre-public v0.6–v0.8 version numbers as historical evidence, refresh
  coverage figures, and distinguish requested versus confirmed setpoints.

### Upgrade, verification, and rollback

- Home Assistant 2026.7.4 or newer remains the advertised minimum. Development is
  pinned to 2026.9.2. Repeat `scripts/check_ha_compat.sh` after future pins.
- After upgrading a reverse-proxy entry, set the thermostat-facing HTTPS port
  in Network options to restore optional contractor-logo downloads. Migration
  preserves existing settings without guessing that port; telemetry and control
  do not depend on it. Direct TLS derives the port from the listener.
- After install, verify load, telemetry, control-ready, and recovery first. Do
  not treat this release as live-proven for the changed Auto-range schedule gate
  until a separately defined reversible thermostat test is run.
- Rollback requires a Home Assistant backup taken before 0.0.4. Config entries
  migrate to version 3; replacing only the Python files with 0.0.3 is not enough.

### Remaining limitations

- Schedules, Vacation, and Emergency Heat remain unexposed.
- Live activation and reversible thermostat command testing remain separate
  from repository and release validation.
- A stalled weather provider no longer blocks the listener, but forecast cards
  stay empty until a bounded refresh succeeds.
- The HA development dependency pins `cryptography==48.0.1`, which has three
  known advisories. Nuve runtime code does not import it; tests use it only to
  generate local certificates. See [Maintenance](docs/maintenance.md) for the
  audit scope and upstream constraint.

## 0.0.3 - 2026-08-14

### Documentation

- Make an operator-controlled hostname and persistent API endpoint change the only
  supported deployment path.
- Align installation, network preparation, rollback, platform, and firmware evidence
  around repeatable trusted TLS behavior.

## 0.0.2 - 2026-08-14

### Documentation

- Add HACS custom-repository installation instructions and clarify that HACS does
  not configure the thermostat network path.

## 0.0.1 - 2026-08-12

Initial public release of Nuve Local.

### Included

- Local Home Assistant climate control, sensor data, display settings, diagnostics,
  and Repairs for supported Nuve Samo thermostats.
- Fail-closed command handling that waits for current thermostat data and confirmed
  state changes.
- Deployment, rollback, hardware, firmware, protocol, and safety documentation.

### Validation

- Pass the complete locked repository gate: Ruff, formatting, Pyright, and 540 tests.
