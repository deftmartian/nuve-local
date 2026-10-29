# Changelog

## 0.0.5 - 2026-10-28

### Fixed

- Render the thermostat-facing HTTPS port in Network options. In 0.0.4 Home
  Assistant serialized the field as a constant, so the form showed its label with
  no input and an existing reverse-proxy entry could not set the port. The field is
  now an optional integer that suggests the saved value.
- Accept only ASCII digits in night-mode start and end times. Non-ASCII Unicode
  digits previously passed the parser and could break that entity's state updates.

### Compatibility

- Development is pinned to Home Assistant 2026.10.4. The compatibility gate covers
  2026.7.4, 2026.8.1, 2026.9.2, and 2026.10.4; the advertised minimum remains
  2026.7.4.
- The development environment now resolves `cryptography` 50.0.1, which clears the
  advisories noted for 0.0.4.

### Maintenance

- Drive sensors, binary sensors, switches, selects, numbers, and times from entity
  descriptions. A registry snapshot test proves every entity keeps its unique ID.
- Type the config entry's runtime data, extract weather sources, trace helpers, and
  command validators from the runtime, share protocol envelopes and range checks,
  and remove dead code and unreachable branches.
- Remove test-only fallback paths from production code; tests now run through the
  prepared runtime path.

### Documentation

- Move firmware research tools, emulators, and their tests to a separate private
  repository. Integration, deployment, protocol, field-matrix, and security pages
  remain here.
- Consolidate overlapping firmware and API pages and remove stale version labels,
  test counts, and coverage figures.

### Upgrade, verification, and rollback

- Config-entry and storage versions are unchanged from 0.0.4, so reinstalling the
  complete 0.0.4 component is a valid rollback.
- After upgrading a reverse-proxy entry, set the thermostat-facing HTTPS port in
  Network options to restore optional contractor-logo downloads.
- After install, verify load, telemetry, control-ready, and the unchanged entity
  list before issuing commands.

### Remaining limitations

- Schedules, Vacation, and Emergency Heat remain unexposed.
- Live activation and reversible thermostat command testing remain separate from
  repository and release validation.

### Validation

- Pass the complete locked repository gate: Ruff, formatting, Pyright, and the test suite.
- Pass the Home Assistant compatibility gate for 2026.7.4, 2026.8.1, 2026.9.2, and
  2026.10.4.

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
- Distinguish requested versus confirmed setpoints.

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

- Pass the complete locked repository gate: Ruff, formatting, Pyright, and the test suite.
