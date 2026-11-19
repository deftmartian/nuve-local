"""Cached outdoor-condition and forecast projections served to the thermostat."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..const import MAX_OUTDOOR_TEMPERATURE, MIN_OUTDOOR_TEMPERATURE, OUTDOOR_MAX_AGE_SECONDS
from .rules import valid_humidity


def observation_is_fresh(observed_at: datetime | None, *, now: datetime | None = None) -> bool:
    """Return whether an outdoor observation is recent enough to serve.

    The single freshness rule shared by source selection and the served value: an
    observation is fresh for OUTDOOR_MAX_AGE_SECONDS, and a future timestamp is not.
    """

    if observed_at is None:
        return False
    age = ((now or datetime.now(UTC)) - observed_at).total_seconds()
    return 0 <= age <= OUTDOOR_MAX_AGE_SECONDS


@dataclass(slots=True)
class OutdoorConditions:
    """The latest validated outdoor observation, or an explicit unavailable state."""

    temperature_c: float | None = None
    observed_at: datetime | None = None
    humidity_percent: float | None = None
    weather: dict[str, str] | None = None
    location_name: str = "Local outdoor sensor"
    source: str = "unavailable"

    @property
    def is_fresh(self) -> bool:
        """Return whether the projected outdoor temperature is safe to serve."""

        return self.temperature_c is not None and observation_is_fresh(self.observed_at)

    def update(
        self,
        temperature_c: float | None,
        name: str,
        *,
        humidity_percent: float | None,
        weather: dict[str, str] | None,
        observed_at: datetime | None,
        source: str,
    ) -> None:
        """Validate and store one observation; an invalid temperature clears it."""

        if (
            temperature_c is None
            or not math.isfinite(temperature_c)
            or not MIN_OUTDOOR_TEMPERATURE <= temperature_c <= MAX_OUTDOOR_TEMPERATURE
        ):
            self.temperature_c = None
            self.observed_at = None
            self.humidity_percent = None
            self.weather = None
            self.location_name = name
            self.source = "unavailable"
            return
        if humidity_percent is not None and not valid_humidity(humidity_percent):
            humidity_percent = None
        if (
            not isinstance(weather, dict)
            or set(weather) != {"icon", "description"}
            or not all(isinstance(value, str) and value for value in weather.values())
        ):
            weather = None
        self.temperature_c = temperature_c
        self.observed_at = observed_at or datetime.now(UTC)
        self.humidity_percent = humidity_percent
        self.weather = copy.deepcopy(weather)
        self.location_name = name
        self.source = source


@dataclass(slots=True)
class ForecastCache:
    """The last already-validated forecast and its fetch status."""

    payload: dict[str, Any] | None = None
    updated_at: datetime | None = None
    status: str = "not_configured"

    @property
    def healthy(self) -> bool:
        """Return whether a validated forecast is available for the device."""

        return self.payload is not None and self.status == "ok"

    def update(
        self, payload: dict[str, Any] | None, *, status: str, updated_at: datetime | None
    ) -> None:
        """Store one forecast result, or the firmware-safe no-op when payload is None."""

        self.payload = copy.deepcopy(payload) if payload is not None else None
        self.status = status
        self.updated_at = updated_at or datetime.now(UTC)
