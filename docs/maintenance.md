# Maintenance

Run `scripts/check` before every commit and release. It checks the lock file, Ruff,
formatting, repository metadata, Pyright, and the full test suite.

## Current quality baseline

As of 2026-09-15, `scripts/check` plus the Home Assistant lifecycle tests pass.
Measured coverage of `custom_components/nuve_local` is 87% overall and 93% for
`runtime.py`. The earlier v0.6.0 figures (86% overall and 92% runtime across 300
tests) remain historical evidence from the private series.

A fresh OSV and PyPI audit on 2026-09-15 found three distinct advisories in
`cryptography==48.0.1`: CVE-2026-69247 (PKCS#7 decryption oracle), CVE-2026-69248
(DNS name-constraint verification), and CVE-2026-69249 (certificate-verification
resource exhaustion). Home Assistant 2026.9.2 requires that exact version; the
complete set is fixed in cryptography 50.0.0. The dependency remains upstream-pinned
rather than overriding Home Assistant's tested requirements.

Nuve's shipped runtime does not import cryptography or invoke those affected APIs.
Its certificate tests use generated local keys/certificates, and the release ZIP
contains no development dependencies. This is an outstanding development-environment
audit finding, not a claim that the wider HA installation is unaffected. Re-audit
and update with an upstream-compatible HA pin when available.

Sources: [PKCS#7 advisory](https://github.com/advisories/GHSA-g6cj-pr64-35w5),
[DNS constraints](https://github.com/advisories/GHSA-m2h6-j472-rp4c), and
[verification exhaustion](https://github.com/advisories/GHSA-jwv3-5hgf-82ww).

Pyright `1.1.414` reports no findings. The only suppressions are local to six Home
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
