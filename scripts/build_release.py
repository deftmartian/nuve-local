"""Build a deterministic archive of the tracked Home Assistant component."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPONENT = Path("custom_components/nuve_local")


def _tracked_component_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", str(COMPONENT)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return sorted(Path(item.decode()) for item in result.stdout.split(b"\0") if item)


def main() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    manifest = json.loads((ROOT / COMPONENT / "manifest.json").read_text())
    version = project["project"]["version"]
    if manifest["version"] != version:
        raise SystemExit("pyproject.toml and manifest.json versions differ")

    files = _tracked_component_files()
    if not files:
        raise SystemExit("no tracked component files found")

    output_dir = ROOT / "dist"
    output_dir.mkdir(exist_ok=True)
    archive = output_dir / f"nuve-local-v{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for relative in files:
            info = zipfile.ZipInfo(str(relative), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, (ROOT / relative).read_bytes())

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = archive.with_suffix(f"{archive.suffix}.sha256")
    checksum.write_text(f"{digest}  {archive.name}\n")
    print(f"built {archive.relative_to(ROOT)}")
    print(f"sha256 {digest}")


if __name__ == "__main__":
    main()
