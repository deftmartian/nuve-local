"""Repository-maintenance invariants."""

from __future__ import annotations

import json
import re
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


def _home_assistant_pin() -> str:
    dev = tomllib.loads((ROOT / "pyproject.toml").read_text())["dependency-groups"]["dev"]
    return next(spec.split("==", 1)[1] for spec in dev if spec.startswith("homeassistant=="))


def test_home_assistant_minimum_is_consistent() -> None:
    """hacs.json is the single source of the supported minimum; prose must follow it."""
    minimum = json.loads((ROOT / "hacs.json").read_text())["homeassistant"]
    readme = (ROOT / "README.md").read_text()
    deployment = (ROOT / "docs/deployment.md").read_text()

    claimed = {
        *re.findall(r"Home Assistant (\d{4}\.\d+\.\d+) or newer", readme),
        *re.findall(r"Home Assistant (\d{4}\.\d+\.\d+) or newer", deployment),
        *re.findall(r"Home%20Assistant-(\d{4}\.\d+\.\d+)%2B", readme),
    }
    assert claimed == {minimum}

    pin = tuple(int(part) for part in _home_assistant_pin().split("."))
    assert pin >= tuple(int(part) for part in minimum.split("."))


def test_docs_do_not_quote_a_stale_home_assistant_pin() -> None:
    """Renovate bumps the pin without touching prose, so prose must not drift from it."""
    pin = _home_assistant_pin()
    pages = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    stale = [
        f"{page.relative_to(ROOT)}: {quoted}"
        for page in pages
        for quoted in re.findall(r"pinned to `?(\d{4}\.\d+\.\d+)", page.read_text())
        if quoted != pin
    ]
    assert not stale


def test_english_translation_matches_source_strings() -> None:
    strings = json.loads((ROOT / "custom_components/nuve_local/strings.json").read_text())
    translation = json.loads(
        (ROOT / "custom_components/nuve_local/translations/en.json").read_text()
    )

    assert translation == strings


def test_public_markdown_links_resolve() -> None:
    """Research notes live in a private repository; public docs must not link to them."""
    pages = [ROOT / "README.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md"))]
    missing = []
    for page in pages:
        for target in re.findall(r"\]\(([^)\s]+)\)", page.read_text()):
            path = target.split("#", 1)[0]
            if not path or re.match(r"[a-z]+:", path):
                continue
            if not (page.parent / path).exists():
                missing.append(f"{page.relative_to(ROOT)} -> {target}")
    assert not missing
