"""Tests for explicit Nuve baseline capture arming."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from homeassistant.const import EntityCategory
from homeassistant.exceptions import ServiceValidationError

from custom_components.nuve_local.button import NuveBaselineCaptureButton
from custom_components.nuve_local.models import NuveState
from custom_components.nuve_local.runtime import NuveRuntime
from tests.helpers import attach_memory_persistence


def test_baseline_capture_button_requires_a_paired_online_device() -> None:
    async def scenario() -> None:
        runtime = NuveRuntime(
            serial="00-000-000000",
            bootstrap_firmware_version="1.5.7.4",
            bootstrap_technician_url="https://contractor.invalid/preserved",
            bootstrap_metadata_confirmed=True,
            bootstrap_no_update_confirmed=True,
        )
        attach_memory_persistence(runtime)
        entity = NuveBaselineCaptureButton(runtime)
        assert entity.entity_category == EntityCategory.CONFIG
        assert entity.entity_registry_enabled_default is False
        assert entity.available is False
        with pytest.raises(ServiceValidationError):
            await entity.async_press()

        runtime.paired = True
        now = datetime.now(UTC)
        await runtime.async_process_monitor_state(
            NuveState(
                available=True,
                last_seen=now,
                sample_time=now,
                current_temperature=21.0,
                records_received=1,
            )
        )
        assert entity.available is True
        await entity.async_press()
        assert runtime.bootstrap_status == "armed"
        await runtime.async_shutdown()

    asyncio.run(scenario())
