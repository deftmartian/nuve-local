# Thermostat operations

## Access

Prefer an existing multiplexed socket only after confirming its target and owner:

```bash
ssh -S <control-socket> <thermostat-host> '<read-only command>'
```

Confirm the exact target and process before any mutation. Record the exact `appStherm` binary hash when firmware behavior matters; version labels alone are insufficient.

## HVAC safety boundary

- Treat the thermostat UI and fresh Home Assistant state as complementary evidence.
- While heating or cooling is active, do not reboot the thermostat, restart or signal `appStherm`, change mode or setpoint, or test fan controls unless the user explicitly permits that exact action after reviewing current state.
- A Home Assistant reload is a separate action and does not stop the local thermostat control loop.
- Send mode and setpoint changes as separate commands when live testing is authorized. Confirm each from strictly newer device evidence before proceeding.
- Never automatically retry a response that may have reached the thermostat.
- Treat display/backlight/LED/night-mode checks as persisted whole-state writes, not
  harmless UI probes. Do not run them during active heating or cooling; preserve the
  complete pre-test preference state and restore it exactly after one confirmed edit.

## Privacy-safe inspection

Do not print raw environment files, settings stores, bearer tokens, contractor values, serials, or journal lines containing request bodies. Prefer:

- service/process active state;
- timestamps and event counts;
- executable and asset hashes;
- HTTP status and endpoint counters;
- field-name matrices without live values;
- redacted or synthetic fixtures.

Use physical screenshots for display-only behavior such as weather-card ordering, title truncation, and cached images. A successful HTTP response proves the transport contract, not that QML rendered or refreshed it.

When sensor history is relevant, parse only the named numeric columns in memory and
emit aggregate counts, ranges, cadence, and sentinel relationships. Do not copy raw
CSV rows, timestamps, paths, identifiers, or correlated household activity into the
repository or diagnostics. A local history can prove observed populations and
sentinels, but not the sensor board's driver version, calibration state, or a missing
network transport.

## Firmware capture

Copy the executable read-only through the SSH socket, hash both ends, and analyze the copy. Do not patch the live executable or modify QML caches during contract recovery. Use `$analyze-nuve-firmware` for the analysis workflow.
