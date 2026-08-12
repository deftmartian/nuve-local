"""Tests for exact Nuve JSON protocol parsing and rendering."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.nuve_local.protocol import (
    NuveProtocolError,
    next_revision,
    parse_auto_mode_baseline,
    parse_auto_mode_upload,
    parse_current_sensors_upload,
    parse_current_stages_upload,
    parse_settings_upload,
    render_auto_mode_bootstrap_response,
    render_auto_mode_response,
    render_current_sensors_ack,
    render_monitor_reset_response,
    render_monitor_wake_response,
    render_settings_ack,
    render_settings_bootstrap_response,
    render_settings_response,
)
from tests.helpers import settings_upload as make_settings_upload

SERIAL = "00-000-000000"


def settings_upload() -> dict[str, object]:
    """Return a complete synthetic 1.5.7.4 settings upload."""
    return make_settings_upload(SERIAL)


def test_settings_upload_round_trip_uses_double_singular_get_shape() -> None:
    incoming = settings_upload()
    parsed = parse_settings_upload(incoming, serial=SERIAL)
    incoming["temp"] = 99

    response = render_settings_response(
        serial=SERIAL,
        revision="2026-08-09 03:45:01",
        settings=parsed,
        technician_url="https://contractor.invalid/preserved",
        temp_correction_version=2,
    )

    assert response["sn"] == SERIAL
    assert response["setting"]["last_update"] == "2026-08-09 03:45:01"
    assert response["temp"] == 21.5
    assert "zip" not in response["setting"]
    assert response["setting"]["backlight"]["on"] is True
    assert response["setting"]["brightness_mode"] is False
    assert response["setting"]["tempCorrectionVersion"] == 2
    assert response["vacation"]["is_enable"] is False
    assert "settings" not in response
    assert response["schedule"] == {}
    assert response["schedule2"] == {}
    assert response["messages"] == []
    assert response["qr_url"] == "https://contractor.invalid/preserved"
    assert render_settings_ack("2026-08-09 03:45:01") == {
        "setting": {"last_update": "2026-08-09 03:45:01"}
    }


def test_monitor_resync_responses_never_supply_desired_hvac_state() -> None:
    common = {
        "serial": SERIAL,
        "revision": "2026-08-10 13:00:00",
        "technician_url": "https://deftmartian.dev",
        "messages": [],
    }
    reset = render_monitor_reset_response(**common)
    wake = render_monitor_wake_response(
        **common,
        command_time="2026-08-10 13:00:01",
    )

    forbidden = {"temp", "mode_id", "fan", "system", "schedule", "schedule2"}
    for response in (reset, wake):
        assert response["hold"] is False
        assert response["hold_period"] == {}
        assert not forbidden.intersection(response)
        assert response["qr_url"] == "https://deftmartian.dev"
    assert reset["setting"] == {"last_update": "2026-08-10 13:00:00"}
    assert wake["setting"] == {
        "last_update": "2026-08-10 13:00:00",
        "command": "push_live_data",
        "command_time": "2026-08-10 13:00:01",
    }


def test_settings_upload_rejects_wrong_serial_missing_state_and_bad_types() -> None:
    wrong = settings_upload()
    wrong["sn"] = "wrong"
    with pytest.raises(NuveProtocolError, match="serial"):
        parse_settings_upload(wrong, serial=SERIAL)

    missing = settings_upload()
    del missing["system"]
    with pytest.raises(NuveProtocolError, match="system"):
        parse_settings_upload(missing, serial=SERIAL)

    bad = settings_upload()
    bad["mode_id"] = True
    with pytest.raises(NuveProtocolError, match="mode_id"):
        parse_settings_upload(bad, serial=SERIAL)

    bad_air_quality = settings_upload()
    bad_air_quality["co2_id"] = 0
    with pytest.raises(NuveProtocolError, match="co2_id"):
        parse_settings_upload(bad_air_quality, serial=SERIAL)

    subminute_night_mode = settings_upload()
    subminute_night_mode["settings"]["nightModeStart"] = "22:00:01"
    with pytest.raises(NuveProtocolError, match="HH:MM"):
        parse_settings_upload(subminute_night_mode, serial=SERIAL)

    incomplete_system = settings_upload()
    del incomplete_system["system"]["heat_min_on_time"]
    with pytest.raises(NuveProtocolError, match="HVAC system"):
        parse_settings_upload(incomplete_system, serial=SERIAL)

    wrong_system_serial = settings_upload()
    wrong_system_serial["system"]["sn"] = "wrong"
    with pytest.raises(NuveProtocolError, match="system serial"):
        parse_settings_upload(wrong_system_serial, serial=SERIAL)

    invalid_manual_heat = settings_upload()
    invalid_manual_heat["system"]["dualFuelManualHeating"] = True
    with pytest.raises(NuveProtocolError, match="dualFuelManualHeating"):
        parse_settings_upload(invalid_manual_heat, serial=SERIAL)

    with pytest.raises(NuveProtocolError, match="co2_id"):
        parse_current_sensors_upload({"current_humidity": 40, "current_temp": 21, "co2_id": 0})


def test_current_sensor_ack_stringifies_native_double_fields() -> None:
    assert render_current_sensors_ack(
        {"current_humidity": "61.9688", "current_temp": 23, "co2_id": 1}
    ) == {
        "current_humidity": "61.9688",
        "current_temp": "23",
        "co2_id": 1,
    }

    assert (
        parse_current_stages_upload(
            {
                "current_fan_status": 1,
                "current_heating_stage": 0,
                "current_cooling_stage": 0,
            }
        )["current_fan_status"]
        == 1
    )
    with pytest.raises(NuveProtocolError, match="current_fan_status"):
        parse_current_stages_upload(
            {
                "current_fan_status": True,
                "current_heating_stage": 0,
                "current_cooling_stage": 0,
            }
        )

    converted_target = settings_upload()
    converted_target["temp"] = 21.914333181193637
    assert parse_settings_upload(converted_target, serial=SERIAL)["temp"] == pytest.approx(
        21.914333181193637
    )

    converted_vacation_target = settings_upload()
    converted_vacation_target["temp"] = 32.2222222222
    assert parse_settings_upload(converted_vacation_target, serial=SERIAL)["temp"] == pytest.approx(
        32.2222222222
    )

    raw_dissipation = settings_upload()
    raw_dissipation["system"]["heat_dissipation_time"] = 0.3
    assert parse_settings_upload(raw_dissipation, serial=SERIAL)["system"][
        "heat_dissipation_time"
    ] == pytest.approx(0.3)

    invalid_default_heat = settings_upload()
    invalid_default_heat["system"]["dualFuelHeatingModeDefault"] = 3
    with pytest.raises(NuveProtocolError, match="dualFuelHeatingModeDefault"):
        parse_settings_upload(invalid_default_heat, serial=SERIAL)

    out_of_range_target = settings_upload()
    out_of_range_target["temp"] = 35.1
    with pytest.raises(NuveProtocolError, match="supported range"):
        parse_settings_upload(out_of_range_target, serial=SERIAL)

    invalid_aux_delay = settings_upload()
    invalid_aux_delay["system"]["turnAuxOnUnreaching"] = 20
    with pytest.raises(NuveProtocolError, match="supported values"):
        parse_settings_upload(invalid_aux_delay, serial=SERIAL)

    invalid_correction = settings_upload()
    invalid_correction["system"]["tempCorrection"] = 5
    with pytest.raises(NuveProtocolError, match="supported range"):
        parse_settings_upload(invalid_correction, serial=SERIAL)

    fahrenheit_derived = settings_upload()
    fahrenheit_derived["system"].update(
        {
            "dualFuelThreshold": 18.3333333333,
            "aux_lockout_threshold": 26.6666666667,
            "heat_deadband": 0.5555555556,
            "cool_deadband": 2.2222222222,
        }
    )
    fahrenheit_derived["vacation"].update(
        {"min_temp": 3.888888888888889, "max_temp": 32.2222222222}
    )
    parsed_fahrenheit = parse_settings_upload(fahrenheit_derived, serial=SERIAL)
    assert parsed_fahrenheit["vacation"]["max_temp"] == pytest.approx(32.2222222222)
    assert parsed_fahrenheit["vacation"]["min_temp"] == pytest.approx(3.888888888888889)


def test_auto_mode_upload_and_get_have_distinct_shapes() -> None:
    incoming = {
        "auto_temp_low": 19.5,
        "auto_temp_high": 23.5,
        "is_active": True,
        "mode": "auto",
    }
    parsed = parse_auto_mode_upload(incoming, serial=SERIAL)
    response = render_auto_mode_response(revision="2026-08-09 03:45:01", settings=parsed)

    assert response == {
        "last_update": "2026-08-09 03:45:01",
        "auto_temp_low": 19.5,
        "auto_temp_high": 23.5,
    }
    assert parse_auto_mode_baseline(response) == {
        "auto_temp_low": 19.5,
        "auto_temp_high": 23.5,
    }

    assert parse_auto_mode_baseline({"auto_temp_low": 4.0, "auto_temp_high": 32.0}) == {
        "auto_temp_low": 4.0,
        "auto_temp_high": 32.0,
    }

    converted = parse_auto_mode_upload(
        {
            "auto_temp_low": 19.4444444444,
            "auto_temp_high": 23.3333333333,
            "is_active": True,
            "mode": "auto",
        },
        serial=SERIAL,
    )
    assert converted["auto_temp_low"] == pytest.approx(19.4444444444)
    assert converted["auto_temp_high"] == pytest.approx(23.3333333333)


def test_bootstrap_responses_are_minimal_and_do_not_contain_hvac_values() -> None:
    revision = "2026-08-09 03:45:01"

    technician_url = "https://contractor.invalid/preserved"
    settings = render_settings_bootstrap_response(
        serial=SERIAL,
        revision=revision,
        technician_url=technician_url,
    )
    auto = render_auto_mode_bootstrap_response(revision=revision)

    assert settings == {
        "sn": SERIAL,
        "hold": False,
        "hold_period": {},
        "setting": {"last_update": revision},
        "qr_url": technician_url,
        "messages": [],
    }
    assert not {
        "temp",
        "humidity",
        "mode_id",
        "fan",
        "system",
        "schedule",
        "schedule2",
    }.intersection(settings)
    assert auto == {
        "last_update": revision,
        "auto_temp_low": {},
        "auto_temp_high": {},
    }


def test_revision_is_utc_second_resolution_and_strictly_increasing() -> None:
    assert (
        next_revision(
            "2026-08-09 03:45:01",
            now=datetime(2026, 8, 9, 3, 45, 1, 900000, tzinfo=UTC),
        )
        == "2026-08-09 03:45:02"
    )

    with pytest.raises(NuveProtocolError, match="last_update"):
        next_revision(
            "2026-08-09T03:45:01Z",
            now=datetime(2026, 8, 9, 3, 45, 2, tzinfo=UTC),
        )
