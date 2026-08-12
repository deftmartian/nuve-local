"""Constants for the Nuve Local integration."""

from __future__ import annotations

DOMAIN = "nuve_local"
PLATFORMS = [
    "binary_sensor",
    "button",
    "climate",
    "light",
    "number",
    "select",
    "sensor",
    "switch",
    "time",
]

BACKLIGHT_KEYS = frozenset({"on", "hue", "value", "shadeIndex"})
DISPLAY_SETTINGS_KEYS = frozenset(
    {
        "brightness",
        "brightness_mode",
        "timeFormat",
        "tofEnabled",
        "ledBlinkingEnabled",
        "nightModeEnabled",
        "nightModeStart",
        "nightModeEnd",
    }
)

CONF_LISTEN_HOST = "listen_host"
CONF_LISTEN_PORT = "listen_port"
CONF_API_HOSTNAME = "api_hostname"
CONF_THERMOSTAT_IP = "thermostat_ip"
CONF_TRUSTED_PROXY_IP = "trusted_proxy_ip"
CONF_SERIAL = "serial"
CONF_CERTIFICATE = "certificate"
CONF_PRIVATE_KEY = "private_key"
CONF_TOKEN_SHA256 = "token_sha256"
CONF_DEPLOYMENT_PROFILE = "deployment_profile"
CONF_PAIRING_DEADLINE = "pairing_deadline"
CONF_AUTOMATIC_BASELINE_CAPTURE = "automatic_baseline_capture"
CONF_OUTDOOR_TEMPERATURE_ENTITY = "outdoor_temperature_entity"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_CONTRACTOR_BRAND = "contractor_brand"
CONF_CONTRACTOR_PHONE = "contractor_phone"
CONF_CONTRACTOR_URL = "contractor_url"
CONF_CONTRACTOR_LOGO_PATH = "contractor_logo_path"
CONF_CONTROL_ENABLED = "control_enabled"
CONF_BOOTSTRAP_FIRMWARE_VERSION = "bootstrap_firmware_version"
CONF_BOOTSTRAP_TECHNICIAN_URL = "bootstrap_technician_url"
CONF_BOOTSTRAP_METADATA_CONFIRMED = "bootstrap_metadata_confirmed"
CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED = "bootstrap_no_update_confirmed"
CONF_TEMP_CORRECTION_VERSION = "temp_correction_version"

DEFAULT_LISTEN_PORT = 18443
DEFAULT_API_HOSTNAME = ""
DEFAULT_CONTROL_ENABLED = False
DEFAULT_DEPLOYMENT_PROFILE = "reverse_proxy"
DEFAULT_AUTOMATIC_BASELINE_CAPTURE = True

DEPLOYMENT_PROFILE_REVERSE_PROXY = "reverse_proxy"
DEPLOYMENT_PROFILE_DIRECT_TLS = "direct_tls"
DEPLOYMENT_PROFILES = frozenset({DEPLOYMENT_PROFILE_REVERSE_PROXY, DEPLOYMENT_PROFILE_DIRECT_TLS})

MAX_REQUEST_SIZE = 1024 * 1024
MAX_CONTRACTOR_LOGO_SIZE = 1024 * 1024
TOKEN_PATTERN = r"[0-9a-fA-F]{64}"
EXPECTED_HOSTS = frozenset({"devapi.nuvehvac.com", "devapi11.nuvehvac.com"})
LIVENESS_TIMEOUT_SECONDS = 135
REQUEST_TIMEOUT_SECONDS = 10
MAX_CONCURRENT_REQUESTS = 4
COMMAND_TIMEOUT_SECONDS = 75
# In online mode the 1.5.x firmware emits sparse changes every ten seconds but
# only forces an unchanged full snapshot once per hour. Keep a ten-minute
# delivery margin around that firmware cadence. Command confirmation has its own
# COMMAND_TIMEOUT_SECONDS limit and still requires a post-delivery sample.
MONITOR_MAX_AGE_SECONDS = 70 * 60
MONITOR_FUTURE_SKEW_SECONDS = 30
# Operational fail-closed policy: weather older than fifteen minutes is not
# described as fresh to compressor/AUX lockout logic. Operators should select a
# local source that reports at least twice inside this window.
OUTDOOR_MAX_AGE_SECONDS = 900
FORECAST_REFRESH_MINUTES = 45
BOOTSTRAP_WINDOW_SECONDS = 120
PAIRING_WINDOW_SECONDS = 5 * 60
TEMP_CORRECTION_VERSIONS_BY_FIRMWARE = {
    "1.5.7.4": frozenset({1, 2}),
    "1.5.8": frozenset({1, 2}),
    "1.6.1.1": frozenset({1, 2, 3}),
}
BOOTSTRAP_FIRMWARE_ALLOWLIST = frozenset(TEMP_CORRECTION_VERSIONS_BY_FIRMWARE)
MIN_TARGET_TEMPERATURE = 18.0
MAX_TARGET_TEMPERATURE = 30.0
MIN_AUTO_TEMPERATURE = 4.0
MAX_AUTO_TEMPERATURE = 32.0
# Device-originated values can be Fahrenheit setpoints converted to repeating
# Celsius decimals. The exact reference firmware emits a 39 F disabled-vacation
# minimum as 3.888... C, while 90 F is about 32.22 C. Preserve those exact values
# rather than applying the narrower HA command grid at the ingestion boundary.
MIN_DEVICE_TEMPERATURE = (39.0 - 32.0) * 5.0 / 9.0
MAX_DEVICE_TEMPERATURE = 33.0
# The exact Home QV4 handlers increment/decrement the active setpoint slider by
# one display unit. HA-originated canonical-Celsius commands remain restricted to
# the live-proven whole-degree grid; device-originated values remain unquantized.
TARGET_TEMPERATURE_STEP = 1.0
FAN_MODE_IDS = frozenset({0, 1, 2})
MIN_FAN_WORKING_PER_HOUR = 10
MAX_FAN_WORKING_PER_HOUR = 60
HOLD_TYPE_IDS = frozenset({1, 2, 3})
FAN_HOLD_TYPE = 2
HOLD_PERIOD_NAMES = frozenset({"TwoHours", "FourHours", "UntilNextActivity", "UntilChanged"})
