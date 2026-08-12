"""Setup-time safety and lifecycle tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.nuve_local import (
    _validated_outdoor_temperature_c,
    async_setup_entry,
    async_unload_entry,
)


@pytest.fixture(autouse=True)
def stub_repairs_manager(monkeypatch: Any) -> None:
    """Keep setup fakes focused on integration lifecycle, not HA's registry internals."""

    class FakeRepairManager:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def start(self) -> None:
            pass

        def shutdown(self) -> None:
            pass

    monkeypatch.setattr(
        "custom_components.nuve_local.repairs.NuveRepairManager",
        FakeRepairManager,
    )


def test_outdoor_temperature_requires_an_explicit_valid_unit() -> None:
    assert _validated_outdoor_temperature_c("50", "°F") == pytest.approx(10.0)
    with pytest.raises(ValueError, match="missing its unit"):
        _validated_outdoor_temperature_c("50", None)


@dataclass
class FakeBus:
    def async_listen_once(self, event: str, callback: Any) -> Any:
        return lambda: None


@dataclass
class FakeConfigEntries:
    async def async_forward_entry_setups(self, entry: Any, platforms: list[str]) -> None:
        raise AssertionError("platform setup must not run after listener start fails")


@dataclass
class FakeHass:
    bus: FakeBus = field(default_factory=FakeBus)
    config_entries: FakeConfigEntries = field(default_factory=FakeConfigEntries)


@dataclass
class FakeEntry:
    data: dict[str, Any]
    options: dict[str, Any] = field(default_factory=dict)
    entry_id: str = "test-entry"
    runtime_data: Any = None
    unload_callbacks: list[Any] = field(default_factory=list)

    def async_on_unload(self, callback: Any) -> None:
        self.unload_callbacks.append(callback)


def test_listener_start_failure_cleans_restored_bootstrap_timer(monkeypatch: Any) -> None:
    async def scenario() -> None:
        now = datetime.now(UTC)
        revision = now.strftime("%Y-%m-%d %H:%M:%S")

        class FakeStore:
            def __init__(self, hass: Any, entry_id: str, *, serial: str) -> None:
                pass

            async def async_load(self, *, serial: str) -> dict[str, Any]:
                return {
                    "settings_revision_floor": revision,
                    "auto_revision_floor": revision,
                    "bootstrap": {
                        "revision": revision,
                        "armed_at": now.isoformat(),
                        "expires_at": (now + timedelta(minutes=1)).isoformat(),
                        "settings_served": False,
                        "auto_served": False,
                    },
                }

        stopped = False

        async def failing_start(self: Any) -> None:
            raise OSError("synthetic bind failure")

        async def tracked_stop(self: Any) -> None:
            nonlocal stopped
            stopped = True
            await self._runtime.async_shutdown()

        monkeypatch.setattr("custom_components.nuve_local.storage.NuveBaselineStore", FakeStore)
        monkeypatch.setattr(
            "custom_components.nuve_local.server.NuveApiServer.async_start", failing_start
        )
        monkeypatch.setattr(
            "custom_components.nuve_local.server.NuveApiServer.async_stop", tracked_stop
        )
        entry = FakeEntry(
            data={
                "serial": "00-000-000000",
                "thermostat_ip": "192.0.2.23",
                "api_hostname": "nuve-local.example.net",
                "listen_host": "127.0.0.1",
                "listen_port": 18443,
            }
        )

        with pytest.raises(OSError, match="synthetic bind failure"):
            await async_setup_entry(FakeHass(), entry)  # type: ignore[arg-type]
        assert stopped is True
        assert entry.runtime_data._stopped is True
        assert entry.runtime_data._bootstrap_timer is None

    asyncio.run(scenario())


def test_successful_setup_and_unload_own_the_server_lifecycle(monkeypatch: Any) -> None:
    async def scenario() -> None:
        lifecycle: list[str] = []

        class FakeStore:
            def __init__(self, hass: Any, entry_id: str, *, serial: str) -> None:
                pass

            async def async_load(self, *, serial: str) -> dict[str, Any]:
                return {}

        class FakeServer:
            def __init__(self, **kwargs: Any) -> None:
                self._runtime = kwargs["runtime"]

            async def async_save_candidate(self, candidate: dict[str, Any]) -> None:
                return None

            async def async_start(self) -> None:
                lifecycle.append("started")

            async def async_stop(self) -> None:
                lifecycle.append("stopped")
                await self._runtime.async_shutdown()

        class SuccessfulConfigEntries:
            async def async_forward_entry_setups(self, entry: Any, platforms: list[str]) -> None:
                lifecycle.append("platforms_forwarded")

            async def async_unload_platforms(self, entry: Any, platforms: list[str]) -> bool:
                lifecycle.append("platforms_unloaded")
                return True

        @dataclass
        class LifecycleHass:
            bus: FakeBus = field(default_factory=FakeBus)
            config_entries: SuccessfulConfigEntries = field(default_factory=SuccessfulConfigEntries)

        monkeypatch.setattr("custom_components.nuve_local.storage.NuveBaselineStore", FakeStore)
        monkeypatch.setattr("custom_components.nuve_local.server.NuveApiServer", FakeServer)
        entry = FakeEntry(
            data={
                "serial": "00-000-000000",
                "thermostat_ip": "192.0.2.23",
                "listen_host": "127.0.0.1",
                "listen_port": 18443,
            }
        )
        hass = LifecycleHass()

        assert await async_setup_entry(hass, entry) is True  # type: ignore[arg-type]
        assert lifecycle == ["started", "platforms_forwarded"]
        assert await async_unload_entry(hass, entry) is True  # type: ignore[arg-type]
        assert lifecycle == ["started", "platforms_forwarded", "platforms_unloaded", "stopped"]
        assert entry.runtime_data._stopped is True

    asyncio.run(scenario())


def test_failed_platform_unload_preserves_the_running_server() -> None:
    async def scenario() -> None:
        stopped = False

        class FakeServer:
            async def async_stop(self) -> None:
                nonlocal stopped
                stopped = True

        class RefusingConfigEntries:
            async def async_unload_platforms(self, entry: Any, platforms: list[str]) -> bool:
                return False

        @dataclass
        class UnloadHass:
            config_entries: RefusingConfigEntries = field(default_factory=RefusingConfigEntries)

        entry = FakeEntry(data={})
        entry.runtime_data = type("Runtime", (), {"server": FakeServer()})()

        assert await async_unload_entry(UnloadHass(), entry) is False  # type: ignore[arg-type]
        assert stopped is False

    asyncio.run(scenario())


def test_platform_setup_failure_stops_the_listener(monkeypatch: Any) -> None:
    async def scenario() -> None:
        lifecycle: list[str] = []

        class FakeStore:
            def __init__(self, hass: Any, entry_id: str, *, serial: str) -> None:
                pass

            async def async_load(self, *, serial: str) -> dict[str, Any]:
                return {}

        class FakeServer:
            def __init__(self, **kwargs: Any) -> None:
                self._runtime = kwargs["runtime"]

            async def async_save_candidate(self, candidate: dict[str, Any]) -> None:
                return None

            async def async_start(self) -> None:
                lifecycle.append("started")

            async def async_stop(self) -> None:
                lifecycle.append("stopped")
                await self._runtime.async_shutdown()

        class FailingConfigEntries:
            async def async_forward_entry_setups(self, entry: Any, platforms: list[str]) -> None:
                raise RuntimeError("synthetic platform failure")

        @dataclass
        class FailingHass:
            bus: FakeBus = field(default_factory=FakeBus)
            config_entries: FailingConfigEntries = field(default_factory=FailingConfigEntries)

        monkeypatch.setattr("custom_components.nuve_local.storage.NuveBaselineStore", FakeStore)
        monkeypatch.setattr("custom_components.nuve_local.server.NuveApiServer", FakeServer)
        entry = FakeEntry(
            data={
                "serial": "00-000-000000",
                "thermostat_ip": "192.0.2.23",
                "listen_host": "127.0.0.1",
                "listen_port": 18443,
            }
        )

        with pytest.raises(RuntimeError, match="synthetic platform failure"):
            await async_setup_entry(FailingHass(), entry)  # type: ignore[arg-type]
        assert lifecycle == ["started", "stopped"]
        assert entry.runtime_data._stopped is True

    asyncio.run(scenario())


def test_setup_uses_current_override_and_caches_daily_weather(monkeypatch: Any) -> None:
    async def scenario() -> None:
        @dataclass
        class FakeState:
            state: str
            attributes: dict[str, Any]
            name: str
            last_reported: datetime

        now = datetime.now(UTC)
        state_map = {
            "sensor.outdoor": FakeState(
                state="68",
                attributes={"unit_of_measurement": "°F", "humidity": 55},
                name="Garden sensor",
                last_reported=now,
            ),
            "weather.local": FakeState(
                state="partlycloudy",
                attributes={
                    "temperature": 12,
                    "temperature_unit": "°C",
                    "humidity": 70,
                },
                name="Amherst",
                last_reported=now,
            ),
        }

        class FakeStates:
            def get(self, entity_id: str) -> Any:
                return state_map.get(entity_id)

        class FakeServices:
            calls: list[tuple[Any, ...]] = []

            async def async_call(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                self.calls.append((args, kwargs))
                return {
                    "weather.local": {
                        "forecast": [
                            {
                                "datetime": now.date().isoformat(),
                                "temperature": 24,
                                "templow": 17,
                                "humidity": 70,
                                "condition": "partlycloudy",
                            }
                        ]
                    }
                }

        class SuccessfulConfigEntries:
            async def async_forward_entry_setups(self, entry: Any, platforms: list[str]) -> None:
                return None

        @dataclass
        class FakeConfig:
            time_zone: str = "America/Halifax"
            country: str = "CA"

        @dataclass
        class WeatherHass:
            bus: FakeBus = field(default_factory=FakeBus)
            config_entries: SuccessfulConfigEntries = field(default_factory=SuccessfulConfigEntries)
            states: FakeStates = field(default_factory=FakeStates)
            services: FakeServices = field(default_factory=FakeServices)
            config: FakeConfig = field(default_factory=FakeConfig)
            created_tasks: list[asyncio.Task[Any]] = field(default_factory=list)

            def async_create_task(self, coro: Any, name: str) -> asyncio.Task[Any]:
                task = asyncio.create_task(coro, name=name)
                self.created_tasks.append(task)
                return task

        class FakeStore:
            def __init__(self, hass: Any, entry_id: str, *, serial: str) -> None:
                pass

            async def async_load(self, *, serial: str) -> dict[str, Any]:
                return {}

        class FakeServer:
            def __init__(self, **kwargs: Any) -> None:
                self._runtime = kwargs["runtime"]

            async def async_save_candidate(self, candidate: dict[str, Any]) -> None:
                return None

            async def async_start(self) -> None:
                return None

            async def async_stop(self) -> None:
                await self._runtime.async_shutdown()

        monkeypatch.setattr("custom_components.nuve_local.storage.NuveBaselineStore", FakeStore)
        monkeypatch.setattr("custom_components.nuve_local.server.NuveApiServer", FakeServer)
        state_change_callbacks: list[Any] = []

        def track_state_change(*args: Any, **kwargs: Any) -> Any:
            state_change_callbacks.append(args[2])
            return lambda: None

        monkeypatch.setattr(
            "homeassistant.helpers.event.async_track_state_change_event",
            track_state_change,
        )
        monkeypatch.setattr(
            "homeassistant.helpers.event.async_track_state_report_event",
            lambda *args, **kwargs: lambda: None,
        )
        monkeypatch.setattr(
            "homeassistant.helpers.event.async_track_time_interval",
            lambda *args, **kwargs: lambda: None,
        )
        entry = FakeEntry(
            data={
                "serial": "00-000-000000",
                "thermostat_ip": "192.0.2.23",
                "listen_host": "127.0.0.1",
                "listen_port": 18443,
                "outdoor_temperature_entity": "sensor.outdoor",
                "weather_entity": "weather.local",
            }
        )
        hass = WeatherHass()

        assert await async_setup_entry(hass, entry) is True  # type: ignore[arg-type]
        runtime = entry.runtime_data
        assert runtime.outdoor_temperature_c == pytest.approx(20.0)
        assert runtime.outdoor_source == "override_sensor"
        assert runtime.outdoor_location_name == "Amherst"
        assert runtime.outdoor_humidity_percent == 55.0
        assert runtime.outdoor_weather == {
            "icon": "02d",
            "description": "partly cloudy",
        }
        assert runtime.forecast_healthy is True
        assert runtime.forecast_payload is not None
        assert runtime.forecast_payload["city"] == {
            "name": "Amherst",
            "country": "CA",
            "timezone": -10800,
        }
        assert runtime.forecast_payload["list"][0]["temp"] == {
            "day": 24.0,
            "min": 17.0,
            "max": 24.0,
        }
        assert len(hass.services.calls) == 1
        args, kwargs = hass.services.calls[0]
        assert args == ("weather", "get_forecasts", {"type": "daily"})
        assert kwargs == {
            "blocking": True,
            "target": {"entity_id": "weather.local"},
            "return_response": True,
        }
        assert len(state_change_callbacks) == 2
        state_change_callbacks[-1]()
        await asyncio.gather(*hass.created_tasks)
        assert len(hass.services.calls) == 2
        assert runtime.forecast_healthy is True
        await runtime.async_shutdown()

    asyncio.run(scenario())
