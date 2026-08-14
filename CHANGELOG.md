# Changelog

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
