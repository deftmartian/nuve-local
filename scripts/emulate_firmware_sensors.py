#!/usr/bin/env python3
"""Independent exact-1.5.8 remote-sensor UI and upload model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Sensor:
    name: str = ""
    sensor_type: int = 0
    strength: int = 100
    battery: int = 100
    location: int = 0


@dataclass(frozen=True)
class PairingAttempt:
    countdown_started: bool
    native_pairing_called: bool
    sensor_emitted: bool


def begin_pairing_countdown() -> PairingAttempt:
    """Model the Pair page's Ok action in the exact compiled QML."""

    return PairingAttempt(
        countdown_started=True,
        native_pairing_called=False,
        sensor_emitted=False,
    )


def startup_runtime_sensors(server_sensors: list[Any]) -> list[Sensor]:
    """Model SensorController.onCompleted: log public rows but copy none."""

    for sensor in server_sensors:
        getattr(sensor, "name", None)
        getattr(sensor, "location", None)
    return []


def check_server_sensors(
    runtime_sensors: list[Sensor], server_sensors: list[Any], *, editing: bool
) -> None:
    """Model DeviceController.checkSensors, which never changes either array."""

    for sensor in server_sensors:
        for field in ("location", "name", "type", "uid", "locationsd"):
            sensor.get(field) if isinstance(sensor, dict) else getattr(sensor, field, None)
    if editing:
        return
    runtime_sensors[:] = runtime_sensors


def add_runtime_sensor(runtime_sensors: list[Sensor], sensor: Sensor) -> None:
    runtime_sensors.append(sensor)


def remove_runtime_sensor(
    runtime_sensors: list[Sensor], server_sensors: list[Any], sensor: Sensor
) -> Sensor | None:
    """Model the public-array identity lookup followed by private-array splice."""

    index = next((index for index, item in enumerate(server_sensors) if item is sensor), -1)
    if index < 0 or index >= len(runtime_sensors):
        return None
    return runtime_sensors.pop(index)


def build_settings_sensor(sensor: Sensor) -> dict[str, str]:
    """Model DeviceController.pushToServer's four-field sensor projection."""

    return {
        "name": sensor.name,
        "location": "Office" if sensor.location == 0 else "Bedroom",
        "type": "OnBoard" if sensor.sensor_type == 0 else "Wireless",
        "uid": "213137",
    }


def build_settings_sensors(runtime_sensors: list[Sensor]) -> list[dict[str, str]]:
    return [build_settings_sensor(sensor) for sensor in runtime_sensors]
