# Maintenance

Run `scripts/check` before every commit and release. It checks the lock file, Ruff,
formatting, repository metadata, Pyright, and the full test suite.

## Current quality baseline

As of 2026-08-12, the gate has 540 tests. The last measured coverage result is from
v0.6.0: 86% overall and 92% for the control runtime across 300 tests. Later tests add
deployment, scheduling, persistence, Repairs, display, installer-diagnostic, and
command-confirmation cases, but no newer coverage percentage has been measured.

A dependency audit against the locked environment found no known vulnerabilities.
Repeat it when updating Home Assistant or another pinned dependency.

Pyright `1.1.411` reports no findings. The only suppressions are local to six Home
Assistant entity adapters whose supported overrides conflict with Home Assistant's
type stubs.

Ruff enforces a maximum McCabe complexity of 15.

Hassfest reports one valid integration and no invalid integrations. HACS validation
requires a public GitHub projection and must run before publication.

On 2026-08-10, Gitleaks `8.30.1` found only two false positives: the public
`devapi11.nuvehvac.com` hostname. Separate checks found no private keys, tokens,
private IPs, sensitive archives, or files over one MiB. Repeat the audit before
publication.

## Release discipline

1. Keep `pyproject.toml`, the integration manifest, and the changelog version in
   sync; tests enforce this.
2. Run `scripts/check` from a clean worktree.
3. Build the deterministic component archive with `scripts/build_release.py` and
   retain its SHA-256 checksum with the manual release.
4. Compare the complete staged and deployed component inventories before activation;
   never copy selected Python files from different revisions.
5. Run Home Assistant's configuration check, preserve a private rollback copy, and
   restart only Home Assistant Core when activation requires new Python modules.
6. Verify Core health, component hash parity, fresh thermostat telemetry, and control
   readiness without issuing an HVAC command.

Keep firmware, decompiler projects, captures, tokens, certificates, device IDs,
contractor data, and Home Assistant storage outside the repository. Repeat the
privacy and HACS checks before publication. Home Assistant is pinned to `2026.8.1`;
update it only with a matching live compatibility pass.
