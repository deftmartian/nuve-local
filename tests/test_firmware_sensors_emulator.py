"""Independent checks for exact-1.5.8 remote-sensor behavior."""

from __future__ import annotations

from scripts.emulate_firmware_sensors import (
    Sensor,
    add_runtime_sensor,
    begin_pairing_countdown,
    build_settings_sensor,
    build_settings_sensors,
    check_server_sensors,
    remove_runtime_sensor,
    startup_runtime_sensors,
)


def test_pairing_button_only_starts_the_ui_countdown() -> None:
    attempt = begin_pairing_countdown()
    assert attempt.countdown_started
    assert not attempt.native_pairing_called
    assert not attempt.sensor_emitted


def test_startup_discards_the_private_runtime_array_instead_of_copying_server_rows() -> None:
    server_rows = [{"name": "reference", "location": "Office"}]
    assert startup_runtime_sensors(server_rows) == []


def test_settings_response_sensor_check_is_observational_only() -> None:
    runtime = [Sensor(name="local")]
    server = [{"name": "server", "location": "Office", "type": "Wireless", "uid": "x"}]
    assert check_server_sensors(runtime, server, editing=False) is None
    assert runtime == [Sensor(name="local")]
    assert server[0]["name"] == "server"


def test_add_is_private_runtime_only_and_has_no_uid_field() -> None:
    runtime: list[Sensor] = []
    sensor = Sensor(name="Room", sensor_type=1, location=9)
    add_runtime_sensor(runtime, sensor)
    assert runtime == [sensor]
    assert not hasattr(sensor, "uid")


def test_upload_collapses_all_nonzero_locations_and_uses_one_literal_uid() -> None:
    assert build_settings_sensor(Sensor(name="Unknown", location=0)) == {
        "name": "Unknown",
        "location": "Office",
        "type": "OnBoard",
        "uid": "213137",
    }
    for location in range(1, 14):
        assert build_settings_sensor(Sensor(name="Any", sensor_type=1, location=location)) == {
            "name": "Any",
            "location": "Bedroom",
            "type": "Wireless",
            "uid": "213137",
        }


def test_upload_uses_runtime_array_not_server_array() -> None:
    runtime = [Sensor(name="Runtime", sensor_type=1, location=2)]
    assert build_settings_sensors(runtime) == [
        {
            "name": "Runtime",
            "location": "Bedroom",
            "type": "Wireless",
            "uid": "213137",
        }
    ]


def test_remove_looks_up_identity_in_public_array_then_splices_runtime_index() -> None:
    target = Sensor(name="server object")
    runtime = [Sensor(name="wrong index"), target]
    assert remove_runtime_sensor(runtime, [], target) is None
    assert len(runtime) == 2

    removed = remove_runtime_sensor(runtime, [target], target)
    assert removed is not target
    assert removed.name == "wrong index"
    assert runtime == [target]
