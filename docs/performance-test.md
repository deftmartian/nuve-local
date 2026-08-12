# Firmware 1.5.8 equipment performance test

This performance-test path comes from `appStherm` SHA-256
`2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e`.
It was analyzed statically and in an isolated model, never on connected HVAC
equipment.

This is not a passive diagnostic. An
eligible request selects Cooling or Heating, substitutes a 40 °F or 90 °F target,
and runs the thermostat's ordinary HVAC state machine for 15 minutes. Normal
installer settings can therefore energize compressor, fan, conventional heat,
auxiliary heat, reversing-valve, and configured accessory outputs. Nuve Local must
leave both performance-test endpoints unavailable.

## Native ownership and routes

`PerfTestService` owns the complete application-side workflow. The principal exact
addresses are:

| Function | Address | Role |
| --- | ---: | --- |
| `scheduleNextCheck` | `0x2c5710` | choose the next eligibility timer |
| `checkTestEligibility` / callback | `0x2c6824` / `0x2cb2c8` | GET and classify response |
| `prepareStartRunning` | `0x2c9820` | send the `running` result |
| `handleResultUpload` | `0x2c89f8` | enter hardware warmup for `running` |
| `checkWarmupOrRun` | `0x2c8274` | connect controller signals and invoke hardware path |
| `startRunning` / `collectReading` | `0x2c2b8c` / `0x2ca868` | 15-minute sample window |
| `cleanupRunning` / `cancelTest` | `0x2c508c` / `0x2ca278` | disconnect, revert, and report stop |
| `checkAndSendSavedResult` | `0x2ccbc8` | validate and retry a persisted result |

The two authenticated `DevApiExecutor` requests both use a 20-second timeout:

| Method and path | Request / response contract |
| --- | --- |
| `GET api/sync/perftest/schedule?sn=%0` | Response object uses integer `perftest_id` and string `action`; only exact lowercase `cooling` and `heating` are recognized |
| `POST api/sync/perftest/result?sn=%0` | Compact JSON result body; device serial is substituted into the URL from the body's `sn` |

Vendor-side scheduling policy, authorization semantics, and result interpretation
are not present in the firmware and remain unresolved. Application behavior after a
synthetic response is exact.

## Check scheduling

Construction validates any saved result and calls `scheduleNextCheck(currentTime)`.
Date/time-setting changes reschedule the same way. The scheduler first resets the
counters and state to `Idle`, then:

1. if the requested `QTime` is at or before current local time, replace it with
   current time plus 10 seconds;
2. define a same-day 11:45 cutoff, exactly `12:00 - 900 seconds`;
3. after 11:45, schedule tomorrow at 10:00 plus jitter;
4. at or before 10:00, schedule today at 10:00 plus jitter; and
5. between 10:00 and 11:45 inclusive, retain the requested time exactly.

The jitter is Qt 6.4 `QRandomGenerator::bounded(900)`: the high 32 bits of
`random32 * 900`, yielding every integer from 0 through 899 seconds. It is not a
900-second inclusive range. A failed eligibility GET resubmits current time plus
900 seconds through the same scheduler, so cutoff rules can move that retry to the
next 10:00 window.

The UI-busy postpone timer is a separate fixed 43,200,000 ms (12 hours) from the
eligibility response. A log says “12 noon,” but there is no wall-clock-noon
calculation in that branch. If it expires, the request is discarded and the next
check is scheduled from 10:00.

## Eligibility and state machine

The exact enum is `Idle=0`, `Checking=1`, `Eligible=2`, `Warmup=3`, `Running=4`,
`Complete=5`.

| Event | Exact consequence |
| --- | --- |
| Scheduled check with empty serial | No request; schedule the next 10:00 window |
| Network failure | Emit an error and resubmit current time +15 minutes to the scheduler |
| Saved `perftest_id` equals returned ID | Treat as already performed/pending upload; do not rerun |
| `heating` on CoolingOnly or `cooling` on HeatingOnly | Reject as incompatible and schedule next check |
| Recognized action and ID greater than zero | Store ID/mode, enter `Eligible`, and send `running` unless postponed |
| Eligible while postponed | Set `eligibleWhilePostponed`; start the fixed 12-hour timer |
| Resume with that flag | Clear both postpone flags and send `running` |
| Manual check outside `Idle` | Return false without emitting `eligibilityChecked` |

The `running` POST is a notification, not an acknowledgement gate. Its completion
calls `handleResultUpload` even on network error; that function compares only the
request type and invokes `checkWarmupOrRun` for `running`. A failed notification can
therefore still start physical equipment.

`checkWarmupOrRun` sets `isTestRunning`, connects these three exact controller
signals, enters `Warmup`, and calls `DeviceControllerCPP::doPerfTest`:

- `actualModeStarted(SystemMode)` starts `Running`;
- `startSystemDelayCountdown(SystemMode,int)` sets `floor(milliseconds / 1000)`,
  starts the one-second counter, and remains in `Warmup`; and
- `stopSystemDelayCountdown()` starts `Running`.

Reaching zero on the warmup counter stops that counter but does not itself enter
`Running`. `startRunning` is idempotent once already running, sets 900 seconds, and
starts the 15-second reading timer. Its first firing occurs after 15 seconds, so a
normal run appends 60 readings. Each reading is:

```text
{
  timestamp: UTC "yyyy-MM-dd hh:mm:ss",
  temperature: (device_temperature_F - 32) / 1.8
}
```

After the sixtieth reading, cleanup disconnects all three signals, stops warmup and
reading timers, clears `isTestRunning`, and calls `revertPerfTest`. The finished
body is saved and posted, readings are cleared, and `Complete` starts with a
300-second display counter. The one-second callback decrements a positive counter
and calls `finishTest` on a later callback when it is already below one.

Cancel performs cleanup/revert, sends `stopped`, clears readings, and schedules the
next check. Postpone is rejected from `Warmup` onward.

## Result and persistence contract

All result types have exactly these members:

```text
perftest_id: integer
sn: string
action: "cooling" | "heating"
result: "running" | "stopped" | "finished"
time: UTC "yyyy-MM-dd hh:mm:ss"
data: array  # finished only
```

The wire key is `time`. The ARM code forms its four-character pointer inside the
adjacent application literal `set-time`; a containing-literal xref can misleadingly
label it `set-time`, but the constructed JSON key is exactly `time`.

Before a `finished` upload, the compact body and test ID are written to QSettings
keys `perftest_data` and `perftest_id`. Startup retry requires both keys; later timer
retries require `perftest_data`. The saved body is parsed for `sn`, `time`, and
presence of `data`:

- without a `data` member, more than one crossed UTC calendar midnight is
  expired;
- with a `data` member, more than 30 crossed UTC calendar midnights is expired;
- equality at the calendar-day limit and future dates are accepted; and
- invalid JSON/time or expiration removes both keys.

This is a calendar-date comparison, not an elapsed-duration comparison. Exact Qt
6.4 `QDateTime::daysTo` delegates to `date().daysTo(other.date())`, so even a few
seconds across midnight count as one day.

Valid bytes are posted unchanged using the saved serial. A successful result POST
stops the retry timer and removes both saved keys regardless of whether the request
was `running`, `stopped`, or `finished`. A failed `finished` POST starts the
five-minute saved-result timer if it is inactive. This creates a real collision
hazard: a later successful running/stopped notification can delete an older pending
finished result.

## Effective target and ordinary HVAC control

While `isPerfTestRunning` is true, `SchemeDataProvider::effectiveSystemMode`
(`0x1f1768`) returns the selected Cooling or Heating mode and
`effectiveTemperature` (`0x1f1828`) returns the performance target converted to
Fahrenheit:

| Requested action | Celsius constant | Effective Fahrenheit target |
| --- | ---: | ---: |
| cooling | `4.444444...` | 40 °F |
| heating | `32.222222...` | 90 °F |

Vacation is suppressed. The server-facing QML reports this target and rejects a
server setpoint edit while the test is running. Both schedule generations suppress
or clear their active-schedule effect during the test.

`DeviceControllerCPP::doPerfTest` (`0x262ab0`) stores the selected mode, sets its
performance flag, and invokes `restartWork(true)` on both `Scheme` and
`HumidityScheme`. `Scheme::run` then uses the ordinary Cooling or Heating loop.
There is no special fixed-stage relay profile: normal startup delay, minimum-on,
stage escalation, compressor/AUX/dual-fuel lockouts, O/B policy, dissipation, and
installer topology remain authoritative. `revertPerfTest` (`0x25c1ec`) clears the
flag, sets the stored performance mode to Off, and restarts both schemes.

## Relay consequences

`STHERM::RelayConfigs::printStr` (`0x31b0d0`) proves the ten named terminal fields
and their object offsets. `Relay::relays` copies two additional internal slots, but
they are neither named by `printStr` nor included in staged terminal changes.

| `Relay` offset | `RelayConfigs` index | Terminal |
| ---: | ---: | --- |
| `+0x08` | 0 | `G` |
| `+0x0c` | 1 | `Y1` |
| `+0x10` | 2 | `Y2` |
| `+0x18` | 4 | `ACC2` |
| `+0x1c` | 5 | `W1` |
| `+0x20` | 6 | `W2` |
| `+0x24` | 7 | `W3` |
| `+0x28` | 8 | `O/B` |
| `+0x2c` | 9 | `ACC1P` |
| `+0x30` | 10 | `ACC1N` |

The ordinary relay methods reachable from the selected Cooling/Heating loop have
these exact logical effects before final fan and O/B arbitration:

| Method | Logical terminal request |
| --- | --- |
| `coolingStage1` (`0x1b9be4`) | `Y1` on; `Y2`, `W1`-`W3` off |
| `coolingStage2` (`0x1b9f00`) | `Y1` and `Y2` on; `W1`-`W3` off |
| `heatingStage1(true)` (`0x1b9e10`) | heat-pump `Y1` on; `Y2`, `W1`-`W3` off |
| `heatingStage1(false)` | conventional `W1` on; `Y1`, `Y2`, `W2`, `W3` off |
| `heatingStage2(true)` (`0x1b9e88`) | heat-pump `Y1` and `Y2` on; `W1`-`W3` off |
| `heatingStage2(false)` | conventional `W1` and `W2` on; `Y1`, `Y2`, `W3` off |
| `heatingStage3(bool)` (`0x1b9f58`) | `W1`, `W2`, and `W3` on; `Y1` and `Y2` off; a true argument logs a warning but does not prevent it |
| `auxiliaryHeatingStage1(bool)` (`0x1b9d54`) | `W1` on and, when true, `W3` on |
| `auxiliaryHeatingStage2(bool)` (`0x1b9db8`) | true sets `W1`/`W2` on; false sets both off |

Final `Relay::updateFan` (`0x1ba2fc`) turns `G` on for any independent circulation
request, fan dissipation, active `Y1`, thermostat-controlled `W1`/`W3`, or a
fan-coupled active accessory terminal. Conventional heating can leave `G` off when
the furnace owns blower control. `Relay::relays` (`0x1ba3bc`) computes `O/B` on only
when the current non-Off/non-Unknown mode matches configured O/B-on mode.

The performance path itself does not directly write `ACC1P`, `ACC1N`, or `ACC2`.
However, it restarts `HumidityScheme`, which reevaluates humidifier/dehumidifier
configuration and can update those terminals; accessory fan coupling can then also
request `G`. Therefore “performance test means only Y/W outputs” would be unsafe.

When staged output delivery is enabled, `RelayConfigs::changeStepsSorted`
(`0x31e28c`) orders the named terminal transitions and `Scheme::sendRelays` applies
each step 500 ms apart. Without staged delivery, the complete recomputed set is sent
in one TI packet. This proves application commands, not physical airflow or contact
state: the unavailable TI/secondary-controller firmware and absent blower/relay
feedback remain separate unknowns.

## UI routes and lockouts

Exact `PerfTestPopup.qml` compiled functions show:

- `Warmup` displays selected Cooling/Heating and `startTimeLeft`;
- `Running` displays remaining seconds or rounded-up minutes;
- `Complete` says results were sent and allows `finishTest`;
- attempted close during Warmup/Running first opens a stop confirmation; confirmed
  stop calls `cancelTest`;
- the popup is modal and has no ordinary close policy; and
- its `isTestRunning` handler locks Schedule, Vacation, Requested Humidity, Desired
  Temperature, Settings, System Setup, System Mode, Auto Mode, and Messages.

`MainView.qml` function `postponeOrResumePerfTest` (source lines 249-260) postpones
when the screensaver is closed and either the navigation depth is greater than one
or any popup is visible. Otherwise it resumes. This protects an in-progress user
interaction, but it does not make the equipment operation safe.

## Reproduction and support boundary

The independent model is [emulate_firmware_perftest.py](../scripts/emulate_firmware_perftest.py)
with fixtures in
[test_firmware_perftest_emulator.py](../tests/test_firmware_perftest_emulator.py).
It covers scheduling/jitter, eligibility/coercion, result schema, persistence age,
upload callbacks, timer/sample counts, cancellation, relay-stage requests, final
fan/O/B arbitration, and accessory coupling.

Application-side behavior is A+B understood. The remaining unknowns are vendor
service policy and the unavailable TI/secondary-controller implementation and
physical terminal/equipment behavior. Those unknowns are reasons to keep the route
unreachable, not reasons to perform a connected-HVAC experiment.
