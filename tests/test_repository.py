"""Repository-maintenance invariants."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_release_versions_are_consistent() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    manifest = json.loads((ROOT / "custom_components/nuve_local/manifest.json").read_text())
    changelog = (ROOT / "CHANGELOG.md").read_text()

    version = project["project"]["version"]
    assert manifest["version"] == version
    assert f"## {version} -" in changelog


def test_english_translation_matches_source_strings() -> None:
    strings = json.loads((ROOT / "custom_components/nuve_local/strings.json").read_text())
    translation = json.loads(
        (ROOT / "custom_components/nuve_local/translations/en.json").read_text()
    )

    assert translation == strings
