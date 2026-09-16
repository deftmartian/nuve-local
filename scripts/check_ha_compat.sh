#!/usr/bin/env bash
# Run a bounded Home Assistant compatibility gate in disposable environments.
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_dir"

versions=(
  "2026.7.4"
  "2026.8.1"
  "2026.9.2"
)
# Override with: scripts/check_ha_compat.sh 2026.7.4 2026.9.2
if (($# > 0)); then
  versions=("$@")
fi

python_bin=${PYTHON:-python3.14}
tests=(
  tests/test_ha_lifecycle.py
  tests/test_runtime.py
  tests/test_config_flow.py
  tests/test_setup.py
)

echo "Home Assistant compatibility gate"
echo "Python: $python_bin"
echo "Versions: ${versions[*]}"
echo "Tests: ${tests[*]}"

for version in "${versions[@]}"; do
  work=$(mktemp -d "${TMPDIR:-/tmp}/nuve-ha-${version}-XXXXXX")
  echo
  echo "== ${version} in ${work} =="
  uv venv --python "$python_bin" "$work/venv"
  uv pip install --python "$work/venv/bin/python" \
    "homeassistant==${version}" \
    "pytest==9.1.1" \
    "cryptography==48.0.1" \
    "voluptuous-serialize"
  PYTHONPATH="$repo_dir" "$work/venv/bin/python" -m pytest "${tests[@]}" -q --tb=line
  rm -rf "$work"
done

echo
echo "Home Assistant compatibility gate passed for: ${versions[*]}"
