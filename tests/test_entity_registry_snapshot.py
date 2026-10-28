"""Guard: every entity's registry-facing identity and presentation stays unchanged."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from custom_components.nuve_local.const import PLATFORMS
from custom_components.nuve_local.data import NuveRuntimeData
from tests.helpers import ready_runtime

SNAPSHOT = Path(__file__).parent / "snapshots" / "entities.json"
SERIAL = "00-000-000000"
ATTRIBUTES = (
    "translation_key",
    "entity_category",
    "entity_registry_enabled_default",
    "device_class",
    "native_unit_of_measurement",
    "state_class",
    "suggested_display_precision",
    "icon",
    "options",
    "native_min_value",
    "native_max_value",
    "native_step",
    "mode",
    "has_entity_name",
)


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return getattr(value, "value", value)
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return str(value)


async def _collect() -> list[dict[str, Any]]:
    runtime = await ready_runtime()
    entry = SimpleNamespace(runtime_data=NuveRuntimeData(runtime=runtime, server=None))  # type: ignore[arg-type]
    rows: list[dict[str, Any]] = []
    for platform in PLATFORMS:
        module = importlib.import_module(f"custom_components.nuve_local.{platform}")
        entities: list[Any] = []
        await module.async_setup_entry(None, entry, entities.extend)
        for entity in entities:
            unique_id = entity.unique_id
            assert unique_id.startswith(f"{SERIAL}_")
            rows.append(
                {
                    "platform": platform,
                    "unique_id_suffix": unique_id.removeprefix(f"{SERIAL}_"),
                    **{name: _plain(getattr(entity, name, None)) for name in ATTRIBUTES},
                }
            )
    await runtime.async_shutdown()
    return sorted(rows, key=lambda row: (row["platform"], row["unique_id_suffix"]))


def test_entity_registry_identity_and_presentation_are_unchanged() -> None:
    rows = asyncio.run(_collect())
    assert len({(row["platform"], row["unique_id_suffix"]) for row in rows}) == len(rows)
    expected = json.loads(SNAPSHOT.read_text())
    assert rows == expected
