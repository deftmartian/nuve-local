"""Tests for the canonical fan-circulation number entity."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from homeassistant.const import EntityCategory
from homeassistant.exceptions import ServiceValidationError

from custom_components.nuve_local.number import NuveFanWorkingPerHour
from tests.helpers import (
    accept_settings_snapshot,
    ready_runtime_158,
    settings_upload,
)


def test_fan_minutes_per_hour_is_not_optimistic() -> None:
    async def scenario() -> None:
        runtime = await ready_runtime_158()
        entity = NuveFanWorkingPerHour(runtime)
        assert entity.entity_category == EntityCategory.CONFIG
        assert entity.native_value == 30

        task = asyncio.create_task(entity.async_set_native_value(40))
        await asyncio.sleep(0)
        response = await runtime.async_get_settings_response(requested_at=datetime.now(UTC))
        assert response["fan"] == {"mode": 0, "workingPerHour": 40}
        baseline = settings_upload(runtime.serial)
        assert response["temp"] == baseline["temp"]
        assert response["mode_id"] == baseline["mode_id"]
        assert response["system"] == baseline["system"]
        assert entity.native_value == 30

        await asyncio.sleep(0.002)
        upload = settings_upload(runtime.serial)
        upload["firmware"]["firmware-version"] = "1.5.8"
        upload["fan"] = {"mode": 0, "workingPerHour": 40}
        accept_settings_snapshot(runtime, upload, received_at=datetime.now(UTC))
        await task
        assert entity.native_value == 40
        await runtime.async_shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize("value", [9, 10.5, 61, float("nan")])
def test_fan_minutes_per_hour_rejects_invalid_values(value: float) -> None:
    async def scenario() -> None:
        runtime = await ready_runtime_158()
        entity = NuveFanWorkingPerHour(runtime)
        with pytest.raises(ServiceValidationError):
            await entity.async_set_native_value(value)
        await runtime.async_shutdown()

    asyncio.run(scenario())
