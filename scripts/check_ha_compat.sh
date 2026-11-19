#!/usr/bin/env bash
# Run the full test suite against Home Assistant versions in disposable environments.
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_dir"

# Defaults to the advertised minimum in hacs.json, so the gate always tests
# what users are promised. Override with: scripts/check_ha_compat.sh 2026.11.0 2026.11.1
python_bin=${PYTHON:-3.14}
py() { uv run --no-project --python "$python_bin" python "$@"; }

versions=("$(py -c 'import json; print(json.load(open("hacs.json"))["homeassistant"])')")
if (($# > 0)); then
  versions=("$@")
fi

pytest_spec=$(py - <<'EOF'
import tomllib

with open("pyproject.toml", "rb") as f:
    dev = tomllib.load(f)["dependency-groups"]["dev"]
print(next(d for d in dev if d.startswith("pytest==")))
EOF
)
work=""
cleanup() {
  if [[ -n "$work" ]]; then
    rm -rf -- "$work"
    work=""
  fi
}
trap cleanup EXIT

echo "Home Assistant compatibility gate"
echo "Python: $python_bin"
echo "Versions: ${versions[*]}"
echo "Tests: full suite"

for version in "${versions[@]}"; do
  work=$(mktemp -d "${TMPDIR:-/tmp}/nuve-ha-${version}-XXXXXX")
  echo
  echo "== ${version} in ${work} =="
  uv venv --python "$python_bin" "$work/venv"
  uv pip install --python "$work/venv/bin/python" \
    "homeassistant==${version}" \
    "$pytest_spec" \
    "voluptuous-serialize"
  PYTHONPATH="$repo_dir" "$work/venv/bin/python" -m pytest -q --tb=line
  cleanup
done

echo
echo "Home Assistant compatibility gate passed for: ${versions[*]}"
