# Changelog

## Unreleased

### Fixed

- Require confirmed `NoSchedule` telemetry for Auto-range writes, matching
  Settings-family commands. Readiness indicators and block reasons now report
  active or unknown schedule authority. Commands are rechecked immediately
  before the response body is sent, including when a schedule activates after
  queuing or during persistence.
- Start the thermostat listener before optional forecast retrieval, bound
  forecast requests, coalesce refresh tasks, and cancel owned tasks on unload.
  Recoverable listener bind failures now raise `ConfigEntryNotReady`, and
  deployment status/diagnostics work when runtime data is missing.
- Separate the thermostat-facing HTTPS port from the Home Assistant listener
  port. Contractor-logo URLs use the external address. Existing reverse-proxy
  entries keep their previous port through migration; proxy setups no longer
  guess an unknown external port. Missing optional logo configuration still
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
