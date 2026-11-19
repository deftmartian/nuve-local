"""Outdoor source selection: freshness, fallback, and the periodic re-check."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.nuve_local.const import OUTDOOR_MAX_AGE_SECONDS
from custom_components.nuve_local.runtime import NuveRuntime
from custom_components.nuve_local.sources import register_outdoor_updates

SENSOR = "sensor.outdoor"
WEATHER = "weather.local"
FRESH = timedelta(minutes=1)
STALE = timedelta(seconds=OUTDOOR_MAX_AGE_SECONDS + 60)


@dataclass
class FakeState:
    state: str
    attributes: dict[str, Any]
    name: str
    last_reported: datetime


@dataclass
class FakeStates:
    states: dict[str, FakeState] = field(default_factory=dict)

    def get(self, entity_id: str) -> FakeState | None:
        return self.states.get(entity_id)


@dataclass
class FakeHass:
    states: FakeStates = field(default_factory=FakeStates)


def _sensor(celsius: float, age: timedelta) -> FakeState:
    return FakeState(
        state=str(celsius),
        attributes={"unit_of_measurement": "°C"},
        name="Outdoor sensor",
        last_reported=datetime.now(UTC) - age,
    )


def _weather(celsius: float, age: timedelta) -> FakeState:
    return FakeState(
        state="cloudy",
        attributes={"temperature": celsius, "temperature_unit": "°C", "humidity": 80},
        name="Local Forecast",
        last_reported=datetime.now(UTC) - age,
    )


@dataclass
class Harness:
    hass: FakeHass
    runtime: NuveRuntime
    recheck: Any
    notifications: list[None]


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Any:
    def build(*, sensor: FakeState | None, weather: FakeState | None) -> Harness:
        hass = FakeHass()
        if sensor is not None:
            hass.states.states[SENSOR] = sensor
        if weather is not None:
            hass.states.states[WEATHER] = weather
        runtime = NuveRuntime(serial="00-000-000000")
        notifications: list[None] = []
        runtime.async_subscribe(lambda: notifications.append(None))
        intervals: list[Any] = []
        monkeypatch.setattr(
            "custom_components.nuve_local.sources.async_track_state_change_event",
            lambda *args, **kwargs: lambda: None,
        )
        monkeypatch.setattr(
            "custom_components.nuve_local.sources.async_track_state_report_event",
            lambda *args, **kwargs: lambda: None,
        )

        def track_interval(hass: Any, action: Any, interval: timedelta, **kwargs: Any) -> Any:
            intervals.append((action, interval))
            return lambda: None

        monkeypatch.setattr(
            "custom_components.nuve_local.sources.async_track_time_interval", track_interval
        )
        unsubs = register_outdoor_updates(
            hass,  # type: ignore[arg-type]
            runtime,
            outdoor_entity_id=SENSOR if sensor is not None else None,
            weather_entity_id=WEATHER if weather is not None else None,
        )
        assert len(unsubs) == 3
        [(recheck, interval)] = intervals
        assert interval == timedelta(seconds=60)
        return Harness(hass, runtime, recheck, notifications)

    return build


def test_a_fresh_override_sensor_wins(harness: Any) -> None:
    h = harness(sensor=_sensor(4.0, FRESH), weather=_weather(9.0, FRESH))

    assert h.runtime.outdoor_sources_configured is True
    assert h.runtime.outdoor_source == "override_sensor"
    assert h.runtime.outdoor_temperature_c == pytest.approx(4.0)
    assert h.runtime.outdoor_is_fresh is True


def test_a_quiet_override_sensor_falls_back_to_a_fresh_weather_entity(harness: Any) -> None:
    h = harness(sensor=_sensor(4.0, STALE), weather=_weather(9.0, FRESH))

    assert h.runtime.outdoor_source == "weather_entity"
    assert h.runtime.outdoor_temperature_c == pytest.approx(9.0)
    assert h.runtime.outdoor_is_fresh is True


def test_when_nothing_is_fresh_the_preferred_source_is_kept_and_reported_stale(
    harness: Any,
) -> None:
    h = harness(sensor=_sensor(4.0, STALE), weather=_weather(9.0, STALE))

    assert h.runtime.outdoor_source == "override_sensor"
    assert h.runtime.outdoor_temperature_c == pytest.approx(4.0)
    assert h.runtime.outdoor_is_fresh is False


def test_the_recheck_switches_source_when_the_override_goes_quiet(harness: Any) -> None:
    h = harness(sensor=_sensor(4.0, FRESH), weather=_weather(9.0, FRESH))
    assert h.runtime.outdoor_source == "override_sensor"

    # No state event: the sensor simply stops reporting.
    h.hass.states.states[SENSOR].last_reported = datetime.now(UTC) - STALE
    before = len(h.notifications)
    h.recheck(None)

    assert h.runtime.outdoor_source == "weather_entity"
    assert h.runtime.outdoor_is_fresh is True
    assert len(h.notifications) == before + 1


def test_the_recheck_publishes_expiry_once_and_is_otherwise_quiet(harness: Any) -> None:
    h = harness(sensor=_sensor(4.0, FRESH), weather=None)

    # Nothing changed: no notification, so entities are not rewritten every minute.
    before = len(h.notifications)
    h.recheck(None)
    assert len(h.notifications) == before

    # The only source ages past the limit: publish the change to stale once.
    h.hass.states.states[SENSOR].last_reported = datetime.now(UTC) - STALE
    h.recheck(None)
    assert h.runtime.outdoor_is_fresh is False
    assert len(h.notifications) == before + 1

    h.recheck(None)
    assert len(h.notifications) == before + 1

    # The sensor reports again (seen here by the recheck): fresh is published.
    h.hass.states.states[SENSOR].last_reported = datetime.now(UTC)
    h.recheck(None)
    assert h.runtime.outdoor_is_fresh is True
    assert len(h.notifications) == before + 2


def test_unusable_sources_still_project_unavailable(harness: Any) -> None:
    sensor = _sensor(4.0, FRESH)
    sensor.state = "unavailable"
    h = harness(sensor=sensor, weather=None)

    assert h.runtime.outdoor_temperature_c is None
    assert h.runtime.outdoor_is_fresh is False
