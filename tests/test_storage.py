"""Tests for private baseline integrity and recovery metadata."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from custom_components.nuve_local.protocol import NuveProtocolError
from custom_components.nuve_local.storage import (
    NuveBaselineStore,
    _build_storage_envelope,
    validate_stored_baselines,
)
from tests.helpers import settings_upload

SERIAL = "00-000-000000"
REVISION = "2026-08-09 06:00:00"


def _data() -> dict[str, object]:
    return {
        "settings": settings_upload(SERIAL),
        "settings_revision": REVISION,
        "auto_mode": {"auto_temp_low": 19.0, "auto_temp_high": 23.0},
        "auto_mode_revision": "2026-08-09 06:00:01",
    }


def test_storage_envelope_binds_serial_hashes_and_immutable_initial_capture() -> None:
    first_at = datetime(2026, 8, 9, 6, 0, tzinfo=UTC)
    first = _build_storage_envelope(_data(), serial=SERIAL, previous=None, saved_at=first_at)
    restored = validate_stored_baselines(first, serial=SERIAL, require_envelope=True)
    assert restored["settings"]["temp"] == 21.5
    assert first["complete"] is True
    assert first["serial_binding"] == SERIAL
    assert first["initial_capture"]["settings"]["temp"] == 21.5
    assert first["previous_good"] is None

    changed = _data()
    changed["settings"]["temp"] = 22.0
    second = _build_storage_envelope(
        changed,
        serial=SERIAL,
        previous=first,
        saved_at=first_at + timedelta(minutes=1),
    )
    assert second["initial_capture"] == first["initial_capture"]
    assert second["previous_good"]["settings"]["temp"] == 21.5


def test_corrupt_current_baseline_recovers_previous_good_copy() -> None:
    first = _build_storage_envelope(
        _data(),
        serial=SERIAL,
        previous=None,
        saved_at=datetime(2026, 8, 9, 6, 0, tzinfo=UTC),
    )
    changed = _data()
    changed["settings"]["temp"] = 22.0
    second = _build_storage_envelope(
        changed,
        serial=SERIAL,
        previous=first,
        saved_at=datetime(2026, 8, 9, 6, 1, tzinfo=UTC),
    )
    corrupt = copy.deepcopy(second)
    corrupt["settings"]["temp"] = 30.0

    restored = validate_stored_baselines(corrupt, serial=SERIAL)
    assert restored["settings"]["temp"] == 21.5
    assert validate_stored_baselines(second, serial="different") == {"persistence_fault": True}


def test_uncertain_command_delivery_boundary_survives_validation() -> None:
    delivered_at = datetime(2026, 8, 9, 6, 0, 2, tzinfo=UTC)
    data = _data()
    data["uncertain_command"] = {
        "kind": "settings",
        "desired": {"temp": 22.0},
        "delivered_at": delivered_at.isoformat(),
        "revision": "2026-08-09 06:00:02",
    }
    envelope = _build_storage_envelope(
        data,
        serial=SERIAL,
        previous=None,
        saved_at=delivered_at,
    )

    restored = validate_stored_baselines(envelope, serial=SERIAL, require_envelope=True)
    assert restored["uncertain_command"] == {
        "kind": "settings",
        "desired": {"temp": 22.0},
        "delivered_at": delivered_at,
        "revision": "2026-08-09 06:00:02",
    }

    data["uncertain_command"]["delivered_at"] = None
    provisional = _build_storage_envelope(
        data,
        serial=SERIAL,
        previous=envelope,
        saved_at=delivered_at,
    )
    restored = validate_stored_baselines(provisional, serial=SERIAL, require_envelope=True)
    assert restored["uncertain_command"]["delivered_at"] is None


def test_uncertain_scheduled_fan_command_survives_validation() -> None:
    saved_at = datetime(2026, 8, 9, 6, 0, 2, tzinfo=UTC)
    data = _data()
    data["uncertain_command"] = {
        "kind": "settings",
        "desired": {
            "fan": {"mode": 1, "workingPerHour": 40},
            "hold_period": "1: TwoHours; 2: UntilChanged",
        },
        "delivered_at": None,
        "revision": "2026-08-09 06:00:02",
    }
    envelope = _build_storage_envelope(
        data,
        serial=SERIAL,
        previous=None,
        saved_at=saved_at,
    )

    restored = validate_stored_baselines(envelope, serial=SERIAL, require_envelope=True)
    assert restored["uncertain_command"]["desired"] == data["uncertain_command"]["desired"]


@pytest.mark.parametrize("section", ["backlight", "settings"])
def test_uncertain_display_command_survives_validation(section: str) -> None:
    saved_at = datetime(2026, 8, 9, 6, 0, 2, tzinfo=UTC)
    data = _data()
    data["uncertain_command"] = {
        "kind": "settings",
        "desired": {section: copy.deepcopy(data["settings"][section])},
        "delivered_at": saved_at.isoformat(),
        "revision": "2026-08-09 06:00:02",
    }
    envelope = _build_storage_envelope(
        data,
        serial=SERIAL,
        previous=None,
        saved_at=saved_at,
    )

    restored = validate_stored_baselines(envelope, serial=SERIAL, require_envelope=True)
    assert restored["uncertain_command"]["desired"] == data["uncertain_command"]["desired"]


@pytest.mark.parametrize(
    "desired",
    [
        {"fan": {"mode": 3, "workingPerHour": 40}},
        {"fan": {"mode": 1, "workingPerHour": 9}},
        {"fan": {"mode": 1, "workingPerHour": 40}, "hold_period": "2: Forever"},
        {"fan": {"mode": 1, "workingPerHour": 40}, "temp": 22.0},
    ],
)
def test_uncertain_fan_command_rejects_unproven_state(desired: dict[str, Any]) -> None:
    data = _data()
    data["uncertain_command"] = {
        "kind": "settings",
        "desired": desired,
        "delivered_at": None,
        "revision": "2026-08-09 06:00:02",
    }
    envelope = _build_storage_envelope(
        data,
        serial=SERIAL,
        previous=None,
        saved_at=datetime(2026, 8, 9, 6, 0, 2, tzinfo=UTC),
    )

    with pytest.raises(NuveProtocolError, match="uncertain fan"):
        validate_stored_baselines(envelope, serial=SERIAL, require_envelope=True)


class _UnderlyingStore:
    version = 1
    minor_version = 1
    key = "nuve_local.test.baselines"

    def __init__(
        self,
        path: Path,
        *,
        swallow_write: bool = False,
        defer_write: bool = False,
    ) -> None:
        self.path = str(path)
        self.swallow_write = swallow_write
        self.defer_write = defer_write
        self.persisted: dict[str, Any] | None = None
        self._data: dict[str, Any] | None = None

    async def async_save(self, data: dict[str, Any]) -> None:
        if self.defer_write:
            self._data = copy.deepcopy(data)
            return
        if not self.swallow_write:
            self.persisted = copy.deepcopy(data)
            Path(self.path).write_text(
                json.dumps(
                    {
                        "version": self.version,
                        "minor_version": self.minor_version,
                        "key": self.key,
                        "data": data,
                    }
                )
            )

    async def async_load(self) -> dict[str, Any] | None:
        if self._data is not None:
            return copy.deepcopy(self._data)
        return copy.deepcopy(self.persisted)


class _FakeHass:
    async def async_add_executor_job(self, target: Any, *args: Any) -> Any:
        return target(*args)


def _baseline_store(underlying: _UnderlyingStore) -> NuveBaselineStore:
    store = object.__new__(NuveBaselineStore)
    store._hass = _FakeHass()
    store._serial = SERIAL
    store._last_good_envelope = None
    store._store = underlying
    return store


def test_store_requires_verified_readback_before_accepting_commit(tmp_path: Path) -> None:
    async def scenario() -> None:
        swallowed = _baseline_store(
            _UnderlyingStore(tmp_path / "swallowed.json", swallow_write=True)
        )
        with pytest.raises(NuveProtocolError, match="commit could not be verified"):
            await swallowed.async_save(_data())
        assert swallowed._last_good_envelope is None

        deferred = _baseline_store(_UnderlyingStore(tmp_path / "deferred.json", defer_write=True))
        with pytest.raises(NuveProtocolError, match="deferred"):
            await deferred.async_save(_data())
        assert deferred._last_good_envelope is None

        durable = _baseline_store(_UnderlyingStore(tmp_path / "durable.json"))
        await durable.async_save(_data())
        assert durable._last_good_envelope is not None

    import asyncio

    asyncio.run(scenario())


def test_load_distinguishes_clean_start_from_existing_corrupt_storage(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        absent_underlying = _UnderlyingStore(tmp_path / "absent.json")
        absent = _baseline_store(absent_underlying)
        assert await absent.async_load(serial=SERIAL) == {}
        assert absent._last_good_envelope is None

        malformed_path = tmp_path / "malformed.json"
        malformed_path.write_text("{")
        malformed = _baseline_store(_UnderlyingStore(malformed_path))
        assert await malformed.async_load(serial=SERIAL) == {"persistence_fault": True}

        corrupt_envelope = _build_storage_envelope(
            _data(),
            serial=SERIAL,
            previous=None,
            saved_at=datetime(2026, 8, 9, 6, 0, tzinfo=UTC),
        )
        corrupt_envelope["settings"]["temp"] = 30.0
        corrupt_underlying = _UnderlyingStore(tmp_path / "corrupt.json")
        corrupt_underlying.persisted = corrupt_envelope
        corrupt = _baseline_store(corrupt_underlying)
        assert await corrupt.async_load(serial=SERIAL) == {"persistence_fault": True}

    import asyncio

    asyncio.run(scenario())


def test_load_retains_valid_empty_envelope_and_latches_previous_recovery(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        saved_at = datetime(2026, 8, 9, 6, 0, tzinfo=UTC)
        empty_envelope = _build_storage_envelope(
            {}, serial=SERIAL, previous=None, saved_at=saved_at
        )
        empty_underlying = _UnderlyingStore(tmp_path / "empty.json")
        empty_underlying.persisted = empty_envelope
        empty = _baseline_store(empty_underlying)
        assert await empty.async_load(serial=SERIAL) == {}
        assert empty._last_good_envelope == empty_envelope

        first = _build_storage_envelope(_data(), serial=SERIAL, previous=None, saved_at=saved_at)
        second_data = _data()
        second_data["settings"]["temp"] = 22.0
        second = _build_storage_envelope(
            second_data,
            serial=SERIAL,
            previous=first,
            saved_at=saved_at + timedelta(minutes=1),
        )
        second["settings"]["temp"] = 30.0
        recovered_underlying = _UnderlyingStore(tmp_path / "recovered.json")
        recovered_underlying.persisted = second
        recovered = _baseline_store(recovered_underlying)
        restored = await recovered.async_load(serial=SERIAL)
        assert restored["settings"]["temp"] == 21.5
        assert restored["recovered_from_previous"] is True
        assert recovered._last_good_envelope == {
            key: value for key, value in first.items() if key != "previous_good"
        }

        both_bad = copy.deepcopy(second)
        both_bad["previous_good"]["settings"]["temp"] = 31.0
        both_bad_underlying = _UnderlyingStore(tmp_path / "both-bad.json")
        both_bad_underlying.persisted = both_bad
        bad = _baseline_store(both_bad_underlying)
        assert await bad.async_load(serial=SERIAL) == {"persistence_fault": True}

    import asyncio

    asyncio.run(scenario())
