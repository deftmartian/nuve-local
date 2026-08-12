"""Independent daily-weather projection tests."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.nuve_local.weather import (
    build_forecast_payload,
    display_location_name,
    firmware_forecast_payload,
)


def test_display_location_removes_only_the_generic_forecast_suffix() -> None:
    assert display_location_name("Amherst Forecast") == "Amherst"
    assert display_location_name("  Coastal forecast  ") == "Coastal"
    assert display_location_name("Forecast House") == "Forecast House"
    assert display_location_name(3) is None


def test_daily_forecast_is_converted_sorted_deduplicated_and_bounded() -> None:
    payload = build_forecast_payload(
        [
            {
                "datetime": "2026-08-10T04:00:00+00:00",
                "temperature": 68.0,
                "templow": 50.0,
                "humidity": 70,
                "condition": "partlycloudy",
            },
            {
                "datetime": "2026-08-10T12:00:00+00:00",
                "temperature": 86.0,
                "templow": 32.0,
                "condition": "sunny",
            },
            {
                "datetime": "2026-08-09",
                "temperature": 64.4,
                "templow": 48.2,
                "condition": "rainy",
                "is_daytime": False,
            },
            {
                "datetime": "2026-08-08",
                "temperature": 70.0,
                "templow": 50.0,
                "condition": "sunny",
            },
            {
                "datetime": "2026-08-11",
                "temperature": 40.0,
                "templow": 50.0,
                "condition": "sunny",
            },
            {
                "datetime": "2026-08-12",
                "temperature": 65.0,
                "templow": 50.0,
                "condition": "windy",
            },
        ],
        temperature_unit="°F",
        time_zone="America/Halifax",
        city_name="Amherst",
        country="CA",
        now=datetime(2026, 8, 9, 12, tzinfo=UTC),
    )

    assert payload == {
        "city": {"name": "Amherst", "country": "CA", "timezone": -10800},
        "list": [
            {
                "dt": 1786287600,
                "temp": {"day": 18.0, "min": 9.0, "max": 18.0},
                "weather": [{"icon": "10n", "description": "rain"}],
            },
            {
                "dt": 1786374000,
                "temp": {"day": 20.0, "min": 10.0, "max": 20.0},
                "humidity": 70.0,
                "weather": [{"icon": "02d", "description": "partly cloudy"}],
            },
        ],
    }


def test_today_uses_current_observation_for_a_missing_elapsed_high() -> None:
    payload = build_forecast_payload(
        [
            {
                "datetime": "2026-08-09T19:00:00+00:00",
                "temperature": None,
                "templow": 21.0,
                "condition": "lightning-rainy",
            },
            {
                "datetime": "2026-08-10T19:00:00+00:00",
                "temperature": 27.0,
                "templow": 19.0,
                "condition": "sunny",
            },
        ],
        temperature_unit="°C",
        time_zone="America/Halifax",
        city_name="Amherst",
        country="CA",
        current_temperature_c=22.0,
        current_condition="partlycloudy",
        current_humidity=88,
        now=datetime(2026, 8, 9, 23, tzinfo=UTC),
    )

    assert payload is not None
    assert payload["list"][0] == {
        "dt": 1786287600,
        "temp": {"day": 22.0, "min": 21.0, "max": 22.0},
        "humidity": 88.0,
        "weather": [{"icon": "11d", "description": "thunderstorm with rain"}],
    }


def test_firmware_forecast_cards_project_high_before_low_without_mutating_cache() -> None:
    cached = {
        "list": [
            {"temp": {"day": 27.0, "min": 19.0, "max": 27.0}},
            {"temp": {"day": 24.0, "min": 17.0, "max": 24.0}},
        ]
    }

    projected = firmware_forecast_payload(cached)

    assert [row["temp"] for row in projected["list"]] == [
        {"day": 27.0, "min": 27.0, "max": 19.0},
        {"day": 24.0, "min": 24.0, "max": 17.0},
    ]
    assert cached["list"][0]["temp"] == {"day": 27.0, "min": 19.0, "max": 27.0}


def test_forecast_fails_closed_without_complete_supported_rows() -> None:
    assert (
        build_forecast_payload(
            [
                {
                    "datetime": "2026-08-10",
                    "temperature": 20.0,
                    "templow": 10.0,
                    "condition": "exceptional",
                }
            ],
            temperature_unit="°C",
            time_zone="America/Halifax",
            city_name="Amherst",
            country="CA",
            now=datetime(2026, 8, 9, 12, tzinfo=UTC),
        )
        is None
    )
    assert (
        build_forecast_payload(
            [],
            temperature_unit=None,
            time_zone="America/Halifax",
            city_name="Amherst",
            country="CA",
        )
        is None
    )
