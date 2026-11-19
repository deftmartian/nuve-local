# Maintenance

Run `scripts/check` before every commit and release. It checks the lock file, Ruff,
formatting, Pyright, and the full test suite with a branch-coverage floor. The test
suite includes repository invariants: version sync, translation parity, doc links,
and Home Assistant version consistency.

## Continuous integration

Forgejo CI (`.forgejo/workflows/check.yml`) runs on every push to `main` and every
pull request. Treat every job as a merge gate; to enforce it, list each job's status
check (`Check / <job> (pull_request)`) as required in the branch protection for `main`:

| Job | Runs | Locally |
| --- | --- | --- |
| `check` | `scripts/check` on the locked development environment | `scripts/check` |
| `compat` | The full test suite on the advertised Home Assistant minimum from `hacs.json` | `scripts/check_ha_compat.sh` |
| `hassfest` | Home Assistant's integration validator, from Core at the pinned version | `scripts/hassfest` |
| `secrets` | A Gitleaks scan of the full history | `gitleaks git --redact .` |

Reviewed Gitleaks false positives are listed by fingerprint in `.gitleaksignore`.
Add one only after confirming the match is not a credential.

HACS validation checks the public GitHub repository, not the code, so it runs on the
GitHub mirror (`.github/workflows/validate.yml`) on each push to `main` and weekly.
GitHub Actions must be enabled on the mirror for it to run.

## Dependency updates

Renovate (`renovate.json`, extending the shared `deftmartian/renovate` preset) opens
pull requests for Python dependencies, workflow actions, and the uv and Gitleaks
versions in CI. Its Dependency Dashboard is a repository issue.

- `cryptography` is never bumped alone: Home Assistant pins it exactly, so it moves
  only together with `homeassistant`.
- A Renovate pull request updates pins only. Changes that alter behaviour or
  compatibility, such as adopting a new Home Assistant API or raising the supported
  minimum, go in their own pull request with a changelog entry, not as an extra
  commit on a Renovate branch.
- Docs refer to the development pin as "the version in `pyproject.toml`" rather than
  quoting it, so Renovate bumps do not leave stale numbers behind.

## Quality gates

- All four CI jobs, including the Home Assistant lifecycle tests, must pass.
- Pyright runs with no findings. Suppressions are limited to:
  - `reportIncompatibleVariableOverride`, disabled in `pyproject.toml`, because Home
    Assistant declares entity properties as `cached_property` and integrations
    override them with plain properties;
  - `reportPrivateImportUsage` on the Home Assistant constants re-exported in
    `light.py` and `binary_sensor.py`; and
  - one `type: ignore[literal-required]` in `storage.py`, where a loop over fixed
    literal keys assigns validated values into a `TypedDict`.
- Ruff enforces a maximum McCabe complexity of 15.
- Branch coverage must stay at or above the `fail_under` floor in `pyproject.toml`.
  Raise the floor as coverage grows; never lower it to make a change pass.
- Before publication, also check for private keys, tokens, private IPs, sensitive
  archives, and large files that a pattern scan can miss. The public
  `devapi11.nuvehvac.com` hostname is an expected false positive.

## Home Assistant versions

- **Minimum:** `hacs.json` is the single source of the supported minimum. The README,
  deployment guide, and compatibility gate must match it; tests enforce this.
- **Development pin:** the `homeassistant` version in `pyproject.toml`. Renovate
  updates it, and CI tests both the pin (`check`) and the minimum (`compat`).
- **Raising the minimum:** do it only when the code needs a newer Home Assistant API,
  as with the 2026.11 rename of the climate temperature properties. Do it in its own
  pull request, with a changelog entry and a version bump at the next release.

## Release discipline

1. Keep `pyproject.toml`, the integration manifest, and the changelog version in
   sync; tests enforce this.
2. Run `scripts/check` from a clean worktree, and confirm CI is green on `main`.
3. Run `scripts/check_ha_compat.sh` with every version in a claimed Home Assistant
   range, if one is claimed beyond the minimum.
4. Build the deterministic component archive with `scripts/build_release.py` and
   publish it with its SHA-256 checksum as release assets on both Forgejo and GitHub.
5. Compare the complete staged and deployed component inventories before activation;
   never copy selected Python files from different revisions.
6. Run Home Assistant's configuration check, preserve a private rollback copy, and
   restart only Home Assistant Core when activation requires new Python modules.
7. Verify Core health, component hash parity, fresh thermostat telemetry, and control
   readiness without issuing an HVAC command.

Keep firmware, decompiler projects, captures, tokens, certificates, device IDs,
contractor data, and Home Assistant storage outside the repository.
