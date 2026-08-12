"""Validated projection from Home Assistant weather data to Nuve firmware data."""

from __future__ import annotations

import copy
import math
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.const import UnitOfTemperature
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

_CONDITION_ICONS: dict[str, tuple[str, str]] = {
    "sunny": ("01", "clear sky"),
    "clear-night": ("01", "clear sky"),
    "partlycloudy": ("02", "partly cloudy"),
    "cloudy": ("04", "cloudy"),
    "fog": ("50", "fog"),
    "rainy": ("10", "rain"),
    "pouring": ("09", "heavy rain"),
    "lightning": ("11", "thunderstorm"),
    "lightning-rainy": ("11", "thunderstorm with rain"),
    "snowy": ("13", "snow"),
    "snowy-rainy": ("13", "snow and rain"),
}


def display_location_name(value: Any) -> str | None:
    """Return a concise thermostat title from a weather entity name."""

    if not isinstance(value, str) or not (name := value.strip()):
        return None
    suffix = " forecast"
    if name.casefold().endswith(suffix) and len(name) > len(suffix):
        name = name[: -len(suffix)].rstrip()
    return name or None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _temperature_c(value: Any, unit: Any) -> float | None:
    numeric = _finite_number(value)
    if numeric is None or not isinstance(unit, str) or not unit:
        return None
    try:
        converted = TemperatureConverter.convert(
            numeric,
            unit,
            UnitOfTemperature.CELSIUS,
        )
    except TypeError, ValueError:
        return None
    return round(converted, 2) if math.isfinite(converted) and -90 <= converted <= 65 else None


def _local_forecast_date(value: Any, zone: ZoneInfo) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
    except ValueError:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone).date()


def condition_weather(condition: Any, is_daytime: Any = None) -> dict[str, str] | None:
    """Return the firmware weather item for one HA condition."""

    if not isinstance(condition, str) or condition not in _CONDITION_ICONS:
        return None
    icon_base, description = _CONDITION_ICONS[condition]
    suffix = "n" if condition == "clear-night" or is_daytime is False else "d"
    return {"icon": f"{icon_base}{suffix}", "description": description}


def _bounded_number(value: Any, *, minimum: float, maximum: float) -> float | None:
    """Return one finite number inside an inclusive protocol range."""

    numeric = _finite_number(value)
    return numeric if numeric is not None and minimum <= numeric <= maximum else None


def _forecast_row(
    item: dict[str, Any],
    *,
    forecast_date: date,
    today: date,
    zone: ZoneInfo,
    temperature_unit: Any,
    current_temperature: float | None,
    current_weather: dict[str, str] | None,
    current_humidity: float | None,
) -> dict[str, Any] | None:
    """Project one complete HA daily row into canonical Nuve weather data."""

    minimum = _temperature_c(item.get("templow"), temperature_unit)
    maximum = _temperature_c(item.get("temperature"), temperature_unit)
    weather = condition_weather(item.get("condition"), item.get("is_daytime"))
    if forecast_date == today:
        weather = weather or current_weather
        # Some daily providers omit today's high after its forecast period has
        # elapsed. The current observation is the only defensible fallback.
        if minimum is None and maximum is not None and current_temperature is not None:
            minimum = min(maximum, current_temperature)
        elif maximum is None and minimum is not None and current_temperature is not None:
            maximum = max(minimum, current_temperature)
        elif minimum is None and maximum is None and current_temperature is not None:
            minimum = maximum = current_temperature
    if minimum is None or maximum is None or minimum > maximum or weather is None:
        return None
    row: dict[str, Any] = {
        "dt": int(datetime.combine(forecast_date, time(hour=12), zone).timestamp()),
        "temp": {"day": maximum, "min": minimum, "max": maximum},
        "weather": [weather],
    }
    humidity = _bounded_number(item.get("humidity"), minimum=0, maximum=100)
    if humidity is None and forecast_date == today:
        humidity = current_humidity
    if humidity is not None:
        row["humidity"] = humidity
    return row


def build_forecast_payload(
    forecasts: Any,
    *,
    temperature_unit: Any,
    time_zone: str,
    city_name: str,
    country: str | None,
    current_temperature_c: Any = None,
    current_condition: Any = None,
    current_humidity: Any = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return a firmware-safe daily forecast, or None for the proven no-op."""

    if not isinstance(forecasts, list) or not isinstance(city_name, str) or not city_name:
        return None
    try:
        zone = ZoneInfo(time_zone)
    except KeyError, ZoneInfoNotFoundError:
        return None
    now_local = (now or dt_util.now()).astimezone(zone)
    today = now_local.date()
    current_temperature = _bounded_number(current_temperature_c, minimum=-90, maximum=65)
    current_weather = condition_weather(current_condition)
    current_humidity_value = _bounded_number(current_humidity, minimum=0, maximum=100)
    rows_by_date: dict[date, dict[str, Any]] = {}
    for item in forecasts:
        if not isinstance(item, dict):
            continue
        forecast_date = _local_forecast_date(item.get("datetime"), zone)
        if forecast_date is None or forecast_date < today or forecast_date in rows_by_date:
            continue
        row = _forecast_row(
            item,
            forecast_date=forecast_date,
            today=today,
            zone=zone,
            temperature_unit=temperature_unit,
            current_temperature=current_temperature,
            current_weather=current_weather,
            current_humidity=current_humidity_value,
        )
        if row is not None:
            rows_by_date[forecast_date] = row

    rows = [rows_by_date[item] for item in sorted(rows_by_date)[:7]]
    if not rows:
        return None
    offset = now_local.utcoffset()
    return {
        "city": {
            "name": city_name,
            "country": country if isinstance(country, str) else "",
            "timezone": int(offset.total_seconds()) if offset is not None else 0,
        },
        "list": rows,
    }


def firmware_forecast_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Project canonical daily bounds into the firmware's high-first cards.

    Firmware 1.5.8 renders ``temp.min`` as the first, bold value and
    ``temp.max`` as the second value without labels. Swap only those two wire
    members so the card follows the conventional emphasized-high/low order.
    The canonical cache remains low/high for the labeled current-weather row.
    """

    projected = copy.deepcopy(payload)
    rows = projected.get("list")
    if not isinstance(rows, list):
        return projected
    for row in rows:
        temperature = row.get("temp") if isinstance(row, dict) else None
        if not isinstance(temperature, dict):
            continue
        low = temperature.get("min")
        high = temperature.get("max")
        if (
            isinstance(low, int | float)
            and not isinstance(low, bool)
            and math.isfinite(low)
            and isinstance(high, int | float)
            and not isinstance(high, bool)
            and math.isfinite(high)
            and low <= high
        ):
            temperature["min"], temperature["max"] = high, low
    return projected
