---
name: operate-nuve-live
description: Safely inspect, authenticate to, deploy, reload, and validate the live Nuve Local Home Assistant integration and Nuve Samo thermostat. Use for Home Assistant API access through the SSH add-on, config-entry diagnostics or reloads, custom-component deployment and rollback, thermostat SSH or log inspection, reversible display checks, physical-device validation, and any live HVAC-affecting operation.
---

# Operate Nuve Live

Treat Home Assistant, the thermostat, and the HVAC equipment as separate failure domains.

1. Read the repository instructions and the scoped implementation or runbook before acting.
2. Map access, active HVAC state, requested mutations, and rollback artifacts.
3. Distinguish a Home Assistant Core/config-entry reload from a thermostat or `appStherm` restart. Never imply that authorization for one permits the other.
4. Preserve an active heating or cooling call. Do not restart the thermostat, restart `appStherm`, change mode/setpoint/fan, or force an equipment transition unless the user explicitly authorizes that exact action at the current state.
5. Use read-only checks first. For an authorized change, make a recoverable backup, validate before activation, and verify live state without broadening the mutation.
6. Never print bearer tokens, refresh tokens, private contractor metadata, serials, or raw logs likely to contain them. Emit sanitized status, counts, hashes, and selected fields.
7. Treat a delivered-but-unconfirmed control response as outcome-uncertain. Do not retry automatically.
8. Treat backlight, brightness, night mode, and HVAC LED preferences as live device
   writes. Capture their complete owning object, change one bounded property, require
   a later complete Settings upload, and restore the exact baseline once. Defer even
   display-only tests while heating or cooling is active because a rejected whole-state
   response can revoke control authority.
9. During active or unknown local schedule authority, verify that ordinary Settings
   polls contain no desired HVAC, `schedule`, or `schedule2` fields and that the
   effective target stays monitor-owned. Withhold every Settings-family write
   (setpoint, mode, fan, backlight, and general display settings); exact firmware
   turns missing schedule fields into empty arrays, while non-array preservation
   values request an unsupported activity refetch. Permit those writes only after a
   fresh monitor proves `NoSchedule`.

Entity IDs, unique IDs, config-entry titles, and config-entry IDs may embed the
thermostat serial. Do not output them during registry or config-entry inspection.
Perform comparisons inside the projection and emit only fixed labels, booleans,
counts, categories, and disabled state that cannot reproduce the identifier.

Read [references/home-assistant.md](references/home-assistant.md) for Home Assistant authentication, diagnostics, reload, and deployment. Read [references/thermostat.md](references/thermostat.md) for thermostat access, process safety, and privacy-safe validation.
