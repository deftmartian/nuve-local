# Home Assistant operations

## Access and authentication

Use the operator's already-authorized Home Assistant access path. If an SSH
control socket exists, confirm that it belongs to the intended host before reuse:

```bash
ssh -S <control-socket> <home-assistant-host> '<read-only command>'
```

Do not assume that `localhost` in an add-on is Home Assistant Core. Resolve the
Core API URL from the authorized deployment or add-on documentation and keep it
outside the repository.

For REST or WebSocket access, use a dedicated credential explicitly provisioned
for this operation. Supply it through a protected environment variable, file
descriptor, or header file; never place it in argv, output, shell history, or the
repository. Do not scrape Home Assistant's internal auth store or repurpose an
owner refresh token.

```bash
printf 'Authorization: Bearer %s\n' "$NUVE_HA_ACCESS_TOKEN" \
  | curl -fsS -H @- "$NUVE_HA_API_URL/api/config" \
  | jq '{version, state}'
```

Pipe responses immediately through a narrow projection; do not display raw config
entries, auth files, token responses, or entity attributes that may contain private
data.

## Nuve config entry

Resolve the entry ID through the supported config-entry API or a narrow local
projection when direct storage access is explicitly authorized. Never print the
complete entry.

Download diagnostics through:

```text
GET /api/diagnostics/config_entry/<entry_id>
```

Reload only this entry through:

```text
POST /api/config/config_entries/entry/<entry_id>/reload
```

Do not assume that a similarly named service call is equivalent to the supported
config-entry reload endpoint. A reload briefly makes entities unavailable and
intentionally clears in-memory stage authority until fresh reports arrive.

## Component deployment

1. Capture the current component and config-entry state in a private, recoverable
   backup outside the public repository.
2. Build or extract the stage from a tracked, cache-free component artifact. Never
   recursively copy a working checkout because ignored bytecode and scratch files
   are still copied.
3. Stage the complete replacement on the same filesystem as the live component so
   activation can be atomic.
4. Before the first rename, compare the complete relative file/hash inventory and
   prove that no `__pycache__` or bytecode exists. Match the live component's owner,
   group, directory modes, and file modes exactly.
5. Activate with an explicit rollback branch for every partial rename or copy.
6. Run the Home Assistant Core configuration check.
7. Restart Core only after the check passes and only when authorized.
8. Verify Core health, the Nuve config entry, selected non-secret state, endpoint
   rejection counts, and deployed hashes. Reload only the entry if its runtime
   caches need a fresh subscription.

A Home Assistant restart does not authorize or require a thermostat or `appStherm` restart. After activation, verify diagnostics, endpoint counts, rejection count, and selected climate state. Never infer an equipment transition from a temporarily unknown `hvac_action` after reload.

## Prove command delivery and durable state separately

Classify every failed control attempt from the narrowest authoritative evidence:

- a queued timeout with no durable delivery timestamp proves that the integration
  did not deliver a response body; it does not prove that the thermostat rejected
  a command;
- a pre-delivery persistence or response-sender failure proves a local fail-closed
  outcome; check the exact block reason and durable journal instead of inferring a
  device result;
- a delivered response is still not proof of application; require the later
  field-owning upload or monitor record defined by the firmware contract; and
- configured fan mode, circulation minutes, and holds belong to the complete
  Settings upload. Physical fan-output monitor telemetry cannot confirm or clear
  uncertainty for those configured fields.
- backlight and general display preferences likewise belong to their complete
  four-field or 14-field Settings subsection. Partial device-preference uploads and
  an entity service return cannot confirm or clear uncertainty for them.

Use the bounded diagnostics `event_trace` to distinguish queue wait, body delivery,
persistence, echo, monitor confirmation, and a control-block transition. Project only
the allowlisted event, family, result, duration, and timestamp fields. Never print or
join the trace with raw Settings, Auto, monitor, entity identifiers, or request logs.

Whenever runtime adds a cross-field command, exercise the real response path through
production-equivalent persistence validation and durable readback. A permissive fake
store can conceal a mismatch between the runtime command shape and the restart
journal. Never generate a scheduled-fan hold without also owning and validating the
exact schedule arrays processed later by the same whole-Settings handler.
