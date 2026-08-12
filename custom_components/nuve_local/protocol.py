"""Pure parsers and renderers for the Nuve device synchronization API."""

from __future__ import annotations

import copy
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from .const import (
    FAN_MODE_IDS,
    MAX_DEVICE_TEMPERATURE,
    MAX_FAN_WORKING_PER_HOUR,
    MIN_DEVICE_TEMPERATURE,
    MIN_FAN_WORKING_PER_HOUR,
)
from .models import NuveMode

REVISION_FORMAT = "%Y-%m-%d %H:%M:%S"

REQUIRED_SETTINGS_KEYS = frozenset(
    {
        "temp",
        "humidity",
        "current_humidity",
        "current_temp",
        "co2_id",
        "hold",
        "hold_period",
        "mode_id",
        "fan",
        "backlight",
        "settings",
        "sensors",
        "messages",
        "system",
        "vacation",
        "firmware",
    }
)

DEVICE_SETTINGS_KEYS = frozenset(
    {
        "brightness",
        "brightness_mode",
        "speaker",
        "temperatureUnit",
        "timeFormat",
        "currentTimezone",
        "effectDst",
        "sleepModeLogo",
        "tofEnabled",
        "ledBlinkingEnabled",
        "setTimeAuto",
        "nightModeEnabled",
        "nightModeStart",
        "nightModeEnd",
    }
)

SYSTEM_SETTINGS_KEYS = frozenset(
    {
        "sn",
        "type",
        "coolStage",
        "heatStage",
        "heatPumpOBState",
        "heatPumpEmergency",
        "systemRunDelay",
        "dualFuelThreshold",
        "isAUXAuto",
        "dualFuelManualHeating",
        "dualFuelHeatingModeDefault",
        "emergencyMinimumTime",
        "auxiliaryHeating",
        "useAuxiliaryParallelHeatPump",
        "driveAux1AndETogether",
        "driveAuxAsEmergency",
        "runFanWithAuxiliary",
        "turnAuxOnUnreaching",
        "thermostatControlFan",
        "tempCorrection",
        "heatingControlByFurnace",
        "compressorLockout",
        "overcool",
        "diffToEngageAux",
        "heat_dissipation_time",
        "cool_dissipation_time",
        "fanWithAccessory",
        "systemAccessories",
        "heat_deadband",
        "cool_deadband",
        "aux_lockout",
        "aux_lockout_threshold",
        "wifiName",
        "wifiStrength",
        "heat_min_on_time",
        "cool_min_on_time",
    }
)


class NuveProtocolError(ValueError):
    """Raised when a device API payload does not match the recovered protocol."""


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_json(value: Any, *, path: str = "$", depth: int = 0) -> None:
    if depth > 20:
        raise NuveProtocolError(f"{path} is nested too deeply")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NuveProtocolError(f"{path} is not finite")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json(item, path=f"{path}[{index}]", depth=depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise NuveProtocolError(f"{path} contains a non-string key")
            _validate_json(item, path=f"{path}.{key}", depth=depth + 1)
        return
    raise NuveProtocolError(f"{path} contains an unsupported value")


def _object(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NuveProtocolError(f"{name} must be a JSON object")
    _validate_json(value)
    return value


def _number(value: Any, *, name: str, low: float, high: float) -> float:
    if not _is_number(value):
        raise NuveProtocolError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise NuveProtocolError(f"{name} is outside its supported range")
    return number


def _number_or_numeric_string(value: Any, *, name: str, low: float, high: float) -> float:
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError as err:
            raise NuveProtocolError(f"{name} must be numeric") from err
    return _number(value, name=name, low=low, high=high)


def _integer(
    value: Any,
    *,
    name: str,
    low: int | None = None,
    high: int | None = None,
    choices: set[int] | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NuveProtocolError(f"{name} must be an integer")
    if choices is not None and value not in choices:
        raise NuveProtocolError(f"{name} is outside its supported values")
    if (low is not None and value < low) or (high is not None and value > high):
        raise NuveProtocolError(f"{name} is outside its supported range")
    return value


def _boolean(value: Any, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise NuveProtocolError(f"{name} must be boolean")
    return value


def _string(value: Any, *, name: str) -> str:
    if not isinstance(value, str):
        raise NuveProtocolError(f"{name} must be a string")
    return value


def _half_step(value: Any, *, name: str, low: float, high: float) -> float:
    number = _number(value, name=name, low=low, high=high)
    if not math.isclose(number * 2, round(number * 2), abs_tol=1e-7):
        raise NuveProtocolError(f"{name} must use half-unit increments")
    return number


def _validate_device_settings(settings: dict[str, Any]) -> None:
    missing = DEVICE_SETTINGS_KEYS.difference(settings)
    if missing:
        raise NuveProtocolError("device settings are incomplete: " + ", ".join(sorted(missing)))
    _integer(settings["brightness"], name="settings.brightness", low=0, high=100)
    _integer(settings["brightness_mode"], name="settings.brightness_mode", choices={0, 1})
    _integer(settings["speaker"], name="settings.speaker", low=0, high=100)
    _integer(settings["temperatureUnit"], name="settings.temperatureUnit", choices={0, 1})
    _integer(settings["timeFormat"], name="settings.timeFormat", choices={0, 1})
    _string(settings["currentTimezone"], name="settings.currentTimezone")
    for key in ("nightModeStart", "nightModeEnd"):
        normalize_night_mode_time(settings[key], name=f"settings.{key}")
    for key in (
        "effectDst",
        "sleepModeLogo",
        "tofEnabled",
        "ledBlinkingEnabled",
        "setTimeAuto",
        "nightModeEnabled",
    ):
        _boolean(settings[key], name=f"settings.{key}")


def normalize_night_mode_time(value: Any, *, name: str) -> str:
    """Validate the firmware's minute value and return its HH:MM identity."""

    if (
        not isinstance(value, str)
        or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d(?::00)?", value) is None
    ):
        raise NuveProtocolError(f"{name} must be HH:MM or HH:MM:00")
    return value[:5]


def _validate_system_settings(system: dict[str, Any], *, serial: str) -> None:
    missing = SYSTEM_SETTINGS_KEYS.difference(system)
    if missing:
        raise NuveProtocolError("HVAC system state is incomplete: " + ", ".join(sorted(missing)))
    if system.get("sn") != serial:
        raise NuveProtocolError("settings system serial does not match")
    if system.get("type") not in {
        "traditional",
        "heat_pump",
        "cooling",
        "heating",
        "dual_fuel_heating",
    }:
        raise NuveProtocolError("system.type is invalid")
    _string(system["wifiName"], name="system.wifiName")
    _string(system["wifiStrength"], name="system.wifiStrength")
    _integer(system["coolStage"], name="system.coolStage", low=1, high=2)
    _integer(system["heatStage"], name="system.heatStage", low=1, high=3)
    _integer(system["heatPumpOBState"], name="system.heatPumpOBState", choices={0, 1})
    _integer(system["systemRunDelay"], name="system.systemRunDelay", choices={1, 2, 5})
    _integer(system["emergencyMinimumTime"], name="system.emergencyMinimumTime", low=2, high=5)
    _integer(
        system["turnAuxOnUnreaching"],
        name="system.turnAuxOnUnreaching",
        choices={15, 30, 45, 60},
    )
    _integer(
        system["dualFuelHeatingModeDefault"],
        name="system.dualFuelHeatingModeDefault",
        choices={0, 1, 2},
    )
    for key in (
        "heatPumpEmergency",
        "isAUXAuto",
        "auxiliaryHeating",
        "useAuxiliaryParallelHeatPump",
        "driveAux1AndETogether",
        "driveAuxAsEmergency",
        "runFanWithAuxiliary",
        "thermostatControlFan",
        "heatingControlByFurnace",
        "compressorLockout",
        "fanWithAccessory",
        "aux_lockout",
    ):
        _boolean(system[key], name=f"system.{key}")
    _integer(
        system["dualFuelManualHeating"],
        name="system.dualFuelManualHeating",
        choices={0, 1, 2},
    )
    # These values are canonical Celsius but can originate at Fahrenheit UI
    # endpoints. Preserve the exact converted device union rather than applying
    # only the Celsius screen bounds.
    _number(system["dualFuelThreshold"], name="system.dualFuelThreshold", low=-32, high=19)
    _number(system["aux_lockout_threshold"], name="system.aux_lockout_threshold", low=-18, high=27)
    _number(system["tempCorrection"], name="system.tempCorrection", low=-4, high=4)
    _number(system["overcool"], name="system.overcool", low=0, high=3)
    _number(system["diffToEngageAux"], name="system.diffToEngageAux", low=1, high=5)
    for key in ("heat_dissipation_time", "cool_dissipation_time"):
        _number(system[key], name=f"system.{key}", low=0, high=15)
    for key in ("heat_deadband", "cool_deadband"):
        _number(system[key], name=f"system.{key}", low=0.5, high=2.3)
    for key in ("heat_min_on_time", "cool_min_on_time"):
        _number(system[key], name=f"system.{key}", low=0, high=20)
    accessories = _object(system["systemAccessories"], name="system.systemAccessories")
    if set(accessories) != {"wire", "mode"}:
        raise NuveProtocolError("system.systemAccessories has an unexpected shape")
    if accessories["wire"] not in {"T1PWRD", "T1Short", "T2PWRD", "None"}:
        raise NuveProtocolError("system.systemAccessories.wire is invalid")
    _integer(accessories["mode"], name="system.systemAccessories.mode", choices={0, 1, 2})


def _validate_sensors(sensors: list[Any]) -> None:
    for index, value in enumerate(sensors):
        sensor = _object(value, name=f"sensors[{index}]")
        if set(sensor) != {"name", "location", "type", "uid"}:
            raise NuveProtocolError(f"sensors[{index}] has an unexpected shape")
        _string(sensor["name"], name=f"sensors[{index}].name")
        _string(sensor["uid"], name=f"sensors[{index}].uid")
        if sensor["location"] not in {"Office", "Bedroom"}:
            raise NuveProtocolError(f"sensors[{index}].location is invalid")
        if sensor["type"] not in {"OnBoard", "Wireless"}:
            raise NuveProtocolError(f"sensors[{index}].type is invalid")


def _validate_vacation(vacation: dict[str, Any]) -> None:
    required = {"min_humidity", "max_humidity", "min_temp", "max_temp", "is_enable"}
    if required.difference(vacation):
        raise NuveProtocolError("vacation state is incomplete")
    minimum_humidity = _number(
        vacation["min_humidity"], name="vacation.min_humidity", low=20, high=50
    )
    maximum_humidity = _number(
        vacation["max_humidity"], name="vacation.max_humidity", low=40, high=70
    )
    minimum_temp = _number(
        vacation["min_temp"],
        name="vacation.min_temp",
        low=MIN_DEVICE_TEMPERATURE,
        high=MAX_DEVICE_TEMPERATURE,
    )
    maximum_temp = _number(
        vacation["max_temp"],
        name="vacation.max_temp",
        low=MIN_DEVICE_TEMPERATURE,
        high=MAX_DEVICE_TEMPERATURE,
    )
    if maximum_humidity < minimum_humidity + 20:
        raise NuveProtocolError("vacation humidity range is invalid")
    if maximum_temp <= minimum_temp:
        raise NuveProtocolError("vacation temperature range is invalid")
    if vacation["is_enable"] not in {"t", "f"}:
        raise NuveProtocolError("vacation.is_enable is invalid")


def parse_settings_upload(value: Any, *, serial: str) -> dict[str, Any]:
    """Validate and copy a complete ``/api/sync/update`` device snapshot."""

    body = _object(value, name="settings upload")
    if body.get("sn") != serial:
        raise NuveProtocolError("settings upload serial does not match")
    missing = REQUIRED_SETTINGS_KEYS.difference(body)
    if missing:
        raise NuveProtocolError(f"settings upload is missing: {', '.join(sorted(missing))}")

    # Device-originated setpoints are not constrained to the UI's command step.
    # Fahrenheit conversion and the firmware's compensation model can produce
    # arbitrary finite Celsius values; preserve the exact uploaded value for a
    # mutation-free echo. HA-originated commands remain step-validated.
    # Normal setpoints are 18..30 C, while this upload field can carry the
    # firmware's wider vacation/schedule range. A Fahrenheit-configured unit
    # can convert 90 F to about 32.22 C, so preserve that exact device value.
    _number(
        body["temp"],
        name="temp",
        low=MIN_DEVICE_TEMPERATURE,
        high=MAX_DEVICE_TEMPERATURE,
    )
    _number(body["humidity"], name="humidity", low=0, high=100)
    _number_or_numeric_string(body["current_humidity"], name="current_humidity", low=0, high=100)
    _number_or_numeric_string(body["current_temp"], name="current_temp", low=-50, high=100)
    co2_id = body["co2_id"]
    if isinstance(co2_id, bool) or not isinstance(co2_id, int) or not 1 <= co2_id <= 3:
        raise NuveProtocolError("co2_id is invalid")
    if not isinstance(body["hold"], bool):
        raise NuveProtocolError("hold must be boolean")
    if not isinstance(body["hold_period"], str):
        raise NuveProtocolError("hold_period must be a string")

    mode = body["mode_id"]
    if isinstance(mode, bool) or not isinstance(mode, int) or mode not in set(NuveMode):
        raise NuveProtocolError("mode_id is invalid")

    fan = _object(body["fan"], name="fan")
    fan_mode = fan.get("mode")
    if isinstance(fan_mode, bool) or not isinstance(fan_mode, int) or fan_mode not in FAN_MODE_IDS:
        raise NuveProtocolError("fan.mode is invalid")
    work_per_hour = fan.get("workingPerHour")
    if (
        isinstance(work_per_hour, bool)
        or not isinstance(work_per_hour, int)
        or not MIN_FAN_WORKING_PER_HOUR <= work_per_hour <= MAX_FAN_WORKING_PER_HOUR
    ):
        raise NuveProtocolError("fan.workingPerHour is invalid")

    for key in ("backlight", "settings", "system", "vacation", "firmware"):
        _object(body[key], name=key)
    _validate_device_settings(body["settings"])
    backlight = body["backlight"]
    if not {"on", "hue", "value", "shadeIndex"}.issubset(backlight):
        raise NuveProtocolError("backlight is incomplete")
    if not isinstance(backlight["on"], bool):
        raise NuveProtocolError("backlight.on must be boolean")
    _number(backlight["hue"], name="backlight.hue", low=0, high=1)
    _number(backlight["value"], name="backlight.value", low=0, high=1)
    _integer(backlight["shadeIndex"], name="backlight.shadeIndex", low=0, high=5)

    system = body["system"]
    _validate_system_settings(system, serial=serial)
    for key in ("sensors", "messages"):
        if not isinstance(body[key], list):
            raise NuveProtocolError(f"{key} must be an array")
    _validate_sensors(body["sensors"])
    _validate_vacation(body["vacation"])
    firmware_version = body["firmware"].get("firmware-version")
    _string(firmware_version, name="firmware.firmware-version")

    return copy.deepcopy(body)


def parse_auto_mode_upload(value: Any, *, serial: str) -> dict[str, Any]:
    """Validate and copy a complete ``/api/sync/autoMode`` snapshot."""

    body = _object(value, name="auto-mode upload")
    if "sn" in body and body["sn"] != serial:
        raise NuveProtocolError("auto-mode upload serial does not match")
    required = {"auto_temp_low", "auto_temp_high", "is_active", "mode"}
    missing = required.difference(body)
    if missing:
        raise NuveProtocolError(f"auto-mode upload is missing: {', '.join(sorted(missing))}")

    low = _number(
        body["auto_temp_low"],
        name="auto_temp_low",
        low=MIN_DEVICE_TEMPERATURE,
        high=MAX_DEVICE_TEMPERATURE,
    )
    high = _number(
        body["auto_temp_high"],
        name="auto_temp_high",
        low=MIN_DEVICE_TEMPERATURE,
        high=MAX_DEVICE_TEMPERATURE,
    )
    if low >= high:
        raise NuveProtocolError("auto-mode low temperature must be below high temperature")
    if not isinstance(body["is_active"], bool):
        raise NuveProtocolError("auto-mode is_active must be boolean")
    mode = body["mode"]
    if not isinstance(mode, str) or mode not in {
        "cooling",
        "heating",
        "auto",
        "vacation",
        "off",
        "emergency_heat",
    }:
        raise NuveProtocolError("auto-mode mode is invalid")
    return copy.deepcopy(body)


def parse_auto_mode_baseline(value: Any) -> dict[str, float]:
    """Validate the two fields required to render a safe Auto-mode response."""

    body = _object(value, name="auto-mode baseline")
    missing = {"auto_temp_low", "auto_temp_high"}.difference(body)
    if missing:
        raise NuveProtocolError(f"auto-mode baseline is missing: {', '.join(sorted(missing))}")
    low = _number(
        body["auto_temp_low"],
        name="auto_temp_low",
        low=MIN_DEVICE_TEMPERATURE,
        high=MAX_DEVICE_TEMPERATURE,
    )
    high = _number(
        body["auto_temp_high"],
        name="auto_temp_high",
        low=MIN_DEVICE_TEMPERATURE,
        high=MAX_DEVICE_TEMPERATURE,
    )
    if low >= high:
        raise NuveProtocolError("auto-mode low temperature must be below high temperature")
    return {"auto_temp_low": low, "auto_temp_high": high}


def parse_device_settings_upload(value: Any) -> dict[str, Any]:
    """Validate the complete device-preferences partial upload."""

    body = _object(value, name="device-settings upload")
    _validate_device_settings(body)
    return copy.deepcopy(body)


def parse_system_settings_upload(value: Any, *, serial: str) -> dict[str, Any]:
    """Validate the complete HVAC-system partial upload."""

    body = _object(value, name="system-settings upload")
    _validate_system_settings(body, serial=serial)
    return copy.deepcopy(body)


def parse_current_sensors_upload(value: Any) -> dict[str, Any]:
    """Validate the current room-sensor partial report."""

    body = _object(value, name="current-sensors upload")
    required = {"current_humidity", "current_temp", "co2_id"}
    missing = required.difference(body)
    if missing:
        raise NuveProtocolError(f"current-sensors upload is missing: {', '.join(sorted(missing))}")
    _number_or_numeric_string(body["current_humidity"], name="current_humidity", low=0, high=100)
    _number_or_numeric_string(body["current_temp"], name="current_temp", low=-50, high=100)
    co2_id = body["co2_id"]
    if isinstance(co2_id, bool) or not isinstance(co2_id, int) or not 1 <= co2_id <= 3:
        raise NuveProtocolError("co2_id is invalid")
    return copy.deepcopy(body)


def parse_current_stages_upload(value: Any) -> dict[str, Any]:
    """Validate the current relay-stage partial report."""

    body = _object(value, name="current-stages upload")
    required = {"current_fan_status", "current_heating_stage", "current_cooling_stage"}
    missing = required.difference(body)
    if missing:
        raise NuveProtocolError(f"current-stages upload is missing: {', '.join(sorted(missing))}")
    # Sync::pushCurrentFanState accepts a C++ bool but constructs this JSON
    # value through the integer QJsonValue overload. The exact wire value is
    # therefore numeric 0/1, and the callback also reads it with toInt().
    _integer(body["current_fan_status"], name="current_fan_status", choices={0, 1})
    heating = body["current_heating_stage"]
    cooling = body["current_cooling_stage"]
    if isinstance(heating, bool) or not isinstance(heating, int) or not 0 <= heating <= 3:
        raise NuveProtocolError("current_heating_stage is invalid")
    if isinstance(cooling, bool) or not isinstance(cooling, int) or not 0 <= cooling <= 2:
        raise NuveProtocolError("current_cooling_stage is invalid")
    return copy.deepcopy(body)


def parse_revision(value: str) -> datetime:
    """Parse the firmware's UTC second-resolution revision."""

    try:
        return datetime.strptime(value, REVISION_FORMAT).replace(tzinfo=UTC)
    except (TypeError, ValueError) as err:
        raise NuveProtocolError("last_update is invalid") from err


def next_revision(previous: str | None, *, now: datetime) -> str:
    """Return a strictly increasing firmware-compatible UTC revision."""

    candidate = now.astimezone(UTC).replace(microsecond=0)
    if previous is not None:
        prior = parse_revision(previous)
        if candidate <= prior:
            candidate = prior + timedelta(seconds=1)
    return candidate.strftime(REVISION_FORMAT)


def render_settings_response(
    *,
    serial: str,
    revision: str,
    settings: dict[str, Any],
    technician_url: str,
    temp_correction_version: int,
) -> dict[str, Any]:
    """Render the safe device/server projection consumed by ``fetchSettings``."""

    inner_settings = copy.deepcopy(settings["settings"])
    inner_settings["backlight"] = copy.deepcopy(settings["backlight"])
    inner_settings["tempCorrectionVersion"] = temp_correction_version
    inner_settings["brightness_mode"] = bool(inner_settings["brightness_mode"])
    # Native fetchSettings reads its revision from data.setting.last_update.
    # QML receives the whole data object and reads every desired HVAC field
    # directly; only device/UI preferences belong inside singular `setting`.
    inner_settings["last_update"] = revision

    desired = {
        key: copy.deepcopy(settings[key])
        for key in (
            "temp",
            "humidity",
            "hold",
            "hold_period",
            "mode_id",
            "fan",
            "sensors",
            "system",
        )
    }
    # The device upload emits literal "t"/"f" strings, while the QML GET
    # consumer assigns this value directly into a typed bool property.  Echoing
    # the nonempty string "f" would therefore enable Vacation mode.  Perform
    # the exact vendor-side representation change explicitly.
    desired["vacation"] = copy.deepcopy(settings["vacation"])
    desired["vacation"]["is_enable"] = settings["vacation"]["is_enable"] == "t"
    for key in ("command", "command_time"):
        if key in settings:
            inner_settings[key] = copy.deepcopy(settings[key])
    desired["setting"] = inner_settings

    # Schedules and lock state are server-owned and absent from the full device
    # upload. Empty arrays erase local schedules. Non-array sentinels preserve
    # the arrays but request a schedule-endpoint refetch, so runtime permits this
    # whole response only when fresh monitor telemetry proves NoSchedule.
    desired["schedule"] = {}
    desired["schedule2"] = {}
    for key in ("locked", "pin"):
        if key in settings:
            desired[key] = copy.deepcopy(settings[key])

    return {
        "sn": serial,
        **desired,
        "qr_url": technician_url,
        "messages": copy.deepcopy(settings["messages"]),
    }


def render_settings_bootstrap_response(
    *, serial: str, revision: str, technician_url: str
) -> dict[str, Any]:
    """Render the one-shot, HVAC-non-applying initial-upload bridge.

    Firmware 1.5.7.4, 1.5.8, and 1.6.1.1 native sync code accepts this nonempty,
    serial-matched envelope as a successful fetch. Its QML handler reaches
    ``hold_period.split`` before any setting mutation and rejects the object
    value. Native/QML still update synchronization state, and ``appDataReady``
    processes ``qr_url`` outside that caught exception. The current technician URL
    is therefore echoed to preserve contractor metadata. This off-schema response is
    safe only during the short, explicitly armed capture window that leads to a
    device-originated full upload.
    """

    return {
        "sn": serial,
        "hold": False,
        "hold_period": {},
        "setting": {"last_update": revision},
        "qr_url": technician_url,
        "messages": [],
    }


def render_monitor_wake_response(
    *,
    serial: str,
    revision: str,
    technician_url: str,
    messages: list[Any],
    command_time: str,
) -> dict[str, Any]:
    """Safely request or repeat online monitor reporting without desired state.

    After a Home Assistant restart the integration forgets its
    in-memory full-monitor authority. The firmware, however, enables online
    protobuf reporting only after receiving ``push_live_data`` through the
    Settings channel. An active schedule also reuses a stable command pair because
    firmware ignores that repeat before mutating monitor state. This response
    uses the same proven first-handler trap as initial baseline capture, preserves
    known server-owned metadata, and places the command where native
    ``System::onAppDataReady`` consumes it. It never includes a temperature, mode,
    fan, system, schedule, or lock value.
    """

    return {
        "sn": serial,
        "hold": False,
        "hold_period": {},
        "setting": {
            "last_update": revision,
            "command": "push_live_data",
            "command_time": command_time,
        },
        "qr_url": technician_url,
        "messages": copy.deepcopy(messages),
    }


def render_monitor_reset_response(
    *,
    serial: str,
    revision: str,
    technician_url: str,
    messages: list[Any],
) -> dict[str, Any]:
    """Turn only the firmware monitor sender offline before a fresh wake.

    ``System::onAppDataReady`` calls ``attemptToRunCommand`` even when command
    and command_time are absent. Firmware then calls
    ``ProtoDataManager::setSendDataOnline(false)`` because the empty command is
    not ``push_live_data``. The next monitor-wake response transitions that
    flag back to true and creates a full monitor packet. The first-handler trap
    prevents this response from applying desired thermostat state.
    """

    return {
        "sn": serial,
        "hold": False,
        "hold_period": {},
        "setting": {"last_update": revision},
        "qr_url": technician_url,
        "messages": copy.deepcopy(messages),
    }


def render_settings_ack(revision: str) -> dict[str, Any]:
    """Acknowledge a settings upload with the revision the device stores."""

    return {"setting": {"last_update": revision}}


def render_auto_mode_response(*, revision: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Render the flat object consumed by ``fetchAutoMode``."""

    return {
        "last_update": revision,
        "auto_temp_low": settings["auto_temp_low"],
        "auto_temp_high": settings["auto_temp_high"],
    }


def render_auto_mode_bootstrap_response(*, revision: str) -> dict[str, Any]:
    """Render the non-applying companion required for combined fetch success.

    The firmware requires a nonempty Auto response after the settings fetch.
    Object operands make both numeric-difference checks evaluate false without
    supplying or changing unknown Auto setpoints.
    """

    return {
        "last_update": revision,
        "auto_temp_low": {},
        "auto_temp_high": {},
    }


def render_auto_mode_ack(revision: str) -> dict[str, Any]:
    """Acknowledge an auto-mode upload."""

    return {"last_update": revision}


def render_partial_settings_ack(revision: str) -> dict[str, Any]:
    """Acknowledge device/system partial settings uploads."""

    return {"last_update": revision}


def render_current_sensors_ack(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Echo sensor values in the string form consumed by firmware 1.5.x.

    The upload contains JSON numbers or numeric strings, but the native reply
    callback calls ``QJsonValue::toString().toDouble()`` for temperature and
    humidity. Echoing a JSON number therefore becomes zero and causes the
    thermostat to retry the report continuously.
    """

    return {
        "current_humidity": str(snapshot["current_humidity"]),
        "current_temp": str(snapshot["current_temp"]),
        "co2_id": snapshot["co2_id"],
    }
