# Maintenance

Run `scripts/check` before every commit and release. It checks the lock file, Ruff,
formatting, repository metadata, Pyright, and the full test suite.

## Quality gates

- `scripts/check` and the Home Assistant lifecycle tests must pass.
- Pyright runs with no findings. The only suppressions are local to the Home
  Assistant entity adapters whose supported overrides conflict with Home Assistant's
  type stubs.
- Ruff enforces a maximum McCabe complexity of 15.
- Hassfest must report a valid integration. HACS validation requires a public GitHub
  projection and must run before publication.
- Before publication, run a secret scan (for example Gitleaks) and check for private
  keys, tokens, private IPs, sensitive archives, and large files. The public
  `devapi11.nuvehvac.com` hostname is an expected false positive.

## Known dependency advisory

Home Assistant 2026.9.2 pins `cryptography==48.0.1`, which has three published
advisories fixed in 50.0.0
([PKCS#7](https://github.com/advisories/GHSA-g6cj-pr64-35w5),
[DNS constraints](https://github.com/advisories/GHSA-m2h6-j472-rp4c),
[verification exhaustion](https://github.com/advisories/GHSA-jwv3-5hgf-82ww)).
Nuve's shipped runtime does not import cryptography, its certificate tests use only
generated local keys, and the release ZIP has no development dependencies. This is a
development-environment finding, not a claim about the wider Home Assistant
installation. Re-audit when an upstream-compatible Home Assistant pin is available.

## Release discipline

1. Keep `pyproject.toml`, the integration manifest, and the changelog version in
   sync; tests enforce this.
2. Run `scripts/check` from a clean worktree.
3. Run `scripts/check_ha_compat.sh` when claiming a Home Assistant version range.
4. Build the deterministic component archive with `scripts/build_release.py` and
   retain its SHA-256 checksum with the manual release.
5. Compare the complete staged and deployed component inventories before activation;
   never copy selected Python files from different revisions.
6. Run Home Assistant's configuration check, preserve a private rollback copy, and
   restart only Home Assistant Core when activation requires new Python modules.
7. Verify Core health, component hash parity, fresh thermostat telemetry, and control
   readiness without issuing an HVAC command.

Keep firmware, decompiler projects, captures, tokens, certificates, device IDs,
contractor data, and Home Assistant storage outside the repository. Repeat the
privacy and HACS checks before publication. Home Assistant is pinned to `2026.9.2`;
update it only with a matching live compatibility pass.

Repeatable version checks use `scripts/check_ha_compat.sh`. It creates disposable
environments for the advertised minimum (`2026.7.4`), the previous development
pin (`2026.8.1`), and the current development pin (`2026.9.2`). Do not raise `hacs.json`'s Home Assistant minimum unless that
gate finds a concrete requirement.
