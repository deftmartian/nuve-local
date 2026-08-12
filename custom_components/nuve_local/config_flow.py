"""Config and options flows for Nuve Local."""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from typing import Any, override
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.helpers import selector

from .commissioning import deployment_profile, new_pairing_deadline, pairing_window_is_open
from .const import (
    BOOTSTRAP_FIRMWARE_ALLOWLIST,
    CONF_API_HOSTNAME,
    CONF_AUTOMATIC_BASELINE_CAPTURE,
    CONF_BOOTSTRAP_FIRMWARE_VERSION,
    CONF_BOOTSTRAP_METADATA_CONFIRMED,
    CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED,
    CONF_BOOTSTRAP_TECHNICIAN_URL,
    CONF_CERTIFICATE,
    CONF_CONTRACTOR_BRAND,
    CONF_CONTRACTOR_LOGO_PATH,
    CONF_CONTRACTOR_PHONE,
    CONF_CONTRACTOR_URL,
    CONF_CONTROL_ENABLED,
    CONF_DEPLOYMENT_PROFILE,
    CONF_LISTEN_HOST,
    CONF_LISTEN_PORT,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PAIRING_DEADLINE,
    CONF_PRIVATE_KEY,
    CONF_SERIAL,
    CONF_TEMP_CORRECTION_VERSION,
    CONF_THERMOSTAT_IP,
    CONF_TOKEN_SHA256,
    CONF_TRUSTED_PROXY_IP,
    CONF_WEATHER_ENTITY,
    DEFAULT_API_HOSTNAME,
    DEFAULT_AUTOMATIC_BASELINE_CAPTURE,
    DEFAULT_CONTROL_ENABLED,
    DEFAULT_DEPLOYMENT_PROFILE,
    DEFAULT_LISTEN_PORT,
    DEPLOYMENT_PROFILE_DIRECT_TLS,
    DEPLOYMENT_PROFILE_REVERSE_PROXY,
    DEPLOYMENT_PROFILES,
    DOMAIN,
    TEMP_CORRECTION_VERSIONS_BY_FIRMWARE,
)

_DNS_NAME = re.compile(
    r"(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?"
)
_OPEN_PAIRING_WINDOW = "open_pairing_window"


def _profile_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=sorted(DEPLOYMENT_PROFILES),
            translation_key="deployment_profile",
        )
    )


def _profile_schema(default: str = DEFAULT_DEPLOYMENT_PROFILE) -> vol.Schema:
    """Return the small first step that selects one network topology."""

    return vol.Schema({vol.Required(CONF_DEPLOYMENT_PROFILE, default=default): _profile_selector()})


def _connection_schema(profile: str, defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return only the fields needed to establish the selected listener path."""

    defaults = defaults or {}
    fields: dict[Any, Any] = {
        vol.Required(CONF_THERMOSTAT_IP, default=defaults.get(CONF_THERMOSTAT_IP, "")): str,
        vol.Required(CONF_SERIAL, default=defaults.get(CONF_SERIAL, "")): str,
        vol.Required(
            CONF_API_HOSTNAME,
            default=defaults.get(CONF_API_HOSTNAME, DEFAULT_API_HOSTNAME),
        ): str,
        vol.Optional(CONF_LISTEN_HOST, default=defaults.get(CONF_LISTEN_HOST, "")): str,
    }
    if profile == DEPLOYMENT_PROFILE_REVERSE_PROXY:
        fields[
            vol.Required(
                CONF_TRUSTED_PROXY_IP,
                default=defaults.get(CONF_TRUSTED_PROXY_IP, ""),
            )
        ] = str
    else:
        fields[vol.Required(CONF_CERTIFICATE, default=defaults.get(CONF_CERTIFICATE, ""))] = str
        fields[vol.Required(CONF_PRIVATE_KEY, default=defaults.get(CONF_PRIVATE_KEY, ""))] = str
    return vol.Schema(fields)


def _commissioning_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return the firmware checks required before the first state capture."""

    defaults = defaults or {}
    correction = defaults.get(CONF_TEMP_CORRECTION_VERSION)
    if correction is not None:
        correction = str(correction)
    return vol.Schema(
        {
            vol.Required(
                CONF_BOOTSTRAP_FIRMWARE_VERSION,
                default=defaults.get(CONF_BOOTSTRAP_FIRMWARE_VERSION, ""),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=sorted(BOOTSTRAP_FIRMWARE_ALLOWLIST))
            ),
            vol.Required(
                CONF_TEMP_CORRECTION_VERSION,
                default=correction or "",
            ): selector.SelectSelector(selector.SelectSelectorConfig(options=["1", "2", "3"])),
            vol.Optional(
                CONF_BOOTSTRAP_TECHNICIAN_URL,
                default=defaults.get(CONF_BOOTSTRAP_TECHNICIAN_URL, ""),
            ): str,
            vol.Required(
                CONF_BOOTSTRAP_METADATA_CONFIRMED,
                default=defaults.get(CONF_BOOTSTRAP_METADATA_CONFIRMED, False),
            ): bool,
            vol.Required(
                CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED,
                default=defaults.get(CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED, False),
            ): bool,
            vol.Required(
                CONF_AUTOMATIC_BASELINE_CAPTURE,
                default=defaults.get(
                    CONF_AUTOMATIC_BASELINE_CAPTURE,
                    DEFAULT_AUTOMATIC_BASELINE_CAPTURE,
                ),
            ): bool,
        }
    )


def _optional_entity_marker(key: str, defaults: dict[str, Any]) -> vol.Optional:
    value = defaults.get(key)
    if value:
        return vol.Optional(key, description={"suggested_value": value})
    return vol.Optional(key)


def _sources_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Return optional Home Assistant weather sources."""

    return vol.Schema(
        {
            _optional_entity_marker(CONF_OUTDOOR_TEMPERATURE_ENTITY, defaults): (
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor"], device_class="temperature")
                )
            ),
            _optional_entity_marker(CONF_WEATHER_ENTITY, defaults): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["weather"])
            ),
        }
    )


def _contractor_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Return optional private contractor display configuration."""

    return vol.Schema(
        {
            vol.Optional(
                CONF_CONTRACTOR_BRAND, default=defaults.get(CONF_CONTRACTOR_BRAND, "")
            ): str,
            vol.Optional(
                CONF_CONTRACTOR_PHONE, default=defaults.get(CONF_CONTRACTOR_PHONE, "")
            ): str,
            vol.Optional(CONF_CONTRACTOR_URL, default=defaults.get(CONF_CONTRACTOR_URL, "")): str,
            vol.Optional(
                CONF_CONTRACTOR_LOGO_PATH,
                default=defaults.get(CONF_CONTRACTOR_LOGO_PATH, ""),
            ): str,
        }
    )


def _network_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Return the full listener configuration form."""

    return vol.Schema(
        {
            vol.Required(
                CONF_DEPLOYMENT_PROFILE,
                default=deployment_profile(defaults),
            ): _profile_selector(),
            vol.Required(CONF_THERMOSTAT_IP, default=defaults.get(CONF_THERMOSTAT_IP, "")): str,
            vol.Optional(
                CONF_TRUSTED_PROXY_IP,
                default=defaults.get(CONF_TRUSTED_PROXY_IP, ""),
            ): str,
            vol.Required(CONF_LISTEN_HOST, default=defaults.get(CONF_LISTEN_HOST, "")): str,
            vol.Required(
                CONF_LISTEN_PORT, default=defaults.get(CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Required(
                CONF_API_HOSTNAME,
                default=defaults.get(CONF_API_HOSTNAME, DEFAULT_API_HOSTNAME),
            ): str,
            vol.Optional(CONF_CERTIFICATE, default=defaults.get(CONF_CERTIFICATE, "")): str,
            vol.Optional(CONF_PRIVATE_KEY, default=defaults.get(CONF_PRIVATE_KEY, "")): str,
        }
    )


def _control_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_CONTROL_ENABLED,
                default=defaults.get(CONF_CONTROL_ENABLED, DEFAULT_CONTROL_ENABLED),
            ): bool
        }
    )


def _pairing_schema() -> vol.Schema:
    return vol.Schema({vol.Required(_OPEN_PAIRING_WINDOW, default=False): bool})


def _strict_optional_integer(value: Any) -> int | str:
    """Coerce an optional integer without accepting booleans or truncating reals."""

    if value == "":
        return ""
    if isinstance(value, bool):
        raise vol.Invalid("boolean is not an integer setting")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text and text.lstrip("+-").isdigit():
            return int(text)
    raise vol.Invalid("expected an integer setting")


def _normalize_temp_correction_version(user_input: dict[str, Any]) -> dict[str, str]:
    """Normalize the serializable selector value before semantic validation."""

    try:
        user_input[CONF_TEMP_CORRECTION_VERSION] = _strict_optional_integer(
            user_input.get(CONF_TEMP_CORRECTION_VERSION, "")
        )
    except vol.Invalid:
        return {CONF_TEMP_CORRECTION_VERSION: "invalid_temp_correction_version"}
    return {}


def _normalize_contractor_values(user_input: dict[str, Any]) -> None:
    """Trim optional display values without inventing missing metadata."""

    for key in (
        CONF_CONTRACTOR_BRAND,
        CONF_CONTRACTOR_PHONE,
        CONF_CONTRACTOR_URL,
        CONF_CONTRACTOR_LOGO_PATH,
    ):
        if isinstance(value := user_input.get(key), str):
            user_input[key] = value.strip()


def _detect_listen_host(target_ip: str) -> str:
    """Return the local address selected by the kernel route without sending data."""

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((target_ip, 9))
        local_ip = str(probe.getsockname()[0])
    ipaddress.ip_address(local_ip)
    return local_ip


def _valid_api_hostname(value: Any) -> bool:
    """Accept one hostname or IPv4 address, never a URL, path, or port."""

    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        return ipaddress.ip_address(value).version == 4
    except ValueError:
        return _DNS_NAME.fullmatch(value) is not None


def _normalize_api_hostname(value: str) -> str:
    """Return the canonical hostname stored in config entries and options."""

    return value.lower().rstrip(".")


def _validate_network_config(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate addressing, TLS pairing, and the configured API hostname."""

    errors: dict[str, str] = {}
    for key in (CONF_THERMOSTAT_IP, CONF_LISTEN_HOST):
        try:
            ipaddress.ip_address(user_input[key])
        except KeyError, ValueError:
            errors[key] = "invalid_ip"
    trusted_proxy_ip = user_input.get(CONF_TRUSTED_PROXY_IP, "")
    if trusted_proxy_ip:
        try:
            ipaddress.ip_address(trusted_proxy_ip)
        except ValueError:
            errors[CONF_TRUSTED_PROXY_IP] = "invalid_ip"
    if CONF_SERIAL in user_input and not user_input[CONF_SERIAL].strip():
        errors[CONF_SERIAL] = "invalid_serial"

    certificate = user_input.get(CONF_CERTIFICATE, "").strip()
    private_key = user_input.get(CONF_PRIVATE_KEY, "").strip()
    if bool(certificate) != bool(private_key):
        errors[CONF_CERTIFICATE] = "certificate_pair_required"
    api_hostname = user_input.get(CONF_API_HOSTNAME, DEFAULT_API_HOSTNAME)
    if not _valid_api_hostname(api_hostname):
        errors[CONF_API_HOSTNAME] = "invalid_api_hostname"
    return errors


def _validate_profile_network(user_input: dict[str, Any]) -> dict[str, str]:
    """Require one complete and unambiguous TLS topology."""

    profile = user_input.get(CONF_DEPLOYMENT_PROFILE)
    if profile not in DEPLOYMENT_PROFILES:
        return {CONF_DEPLOYMENT_PROFILE: "invalid_deployment_profile"}
    if profile == DEPLOYMENT_PROFILE_REVERSE_PROXY:
        if not user_input.get(CONF_TRUSTED_PROXY_IP):
            return {CONF_TRUSTED_PROXY_IP: "trusted_proxy_required"}
        return {}
    if user_input.get(CONF_TRUSTED_PROXY_IP):
        return {CONF_TRUSTED_PROXY_IP: "direct_profile_disallows_proxy"}
    if not user_input.get(CONF_CERTIFICATE) or not user_input.get(CONF_PRIVATE_KEY):
        return {CONF_CERTIFICATE: "direct_profile_requires_certificate"}
    return {}


def _prepare_network_config(
    profile: str, user_input: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Normalize one profile submission and derive the listener address when omitted."""

    prepared = dict(user_input)
    prepared[CONF_DEPLOYMENT_PROFILE] = profile
    for key in (
        CONF_THERMOSTAT_IP,
        CONF_TRUSTED_PROXY_IP,
        CONF_LISTEN_HOST,
        CONF_API_HOSTNAME,
        CONF_CERTIFICATE,
        CONF_PRIVATE_KEY,
        CONF_SERIAL,
    ):
        if isinstance(value := prepared.get(key), str):
            prepared[key] = value.strip()
    prepared.setdefault(CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT)
    prepared.setdefault(CONF_TRUSTED_PROXY_IP, "")
    prepared.setdefault(CONF_CERTIFICATE, "")
    prepared.setdefault(CONF_PRIVATE_KEY, "")

    errors: dict[str, str] = {}
    if not prepared.get(CONF_LISTEN_HOST):
        target = (
            prepared.get(CONF_TRUSTED_PROXY_IP)
            if profile == DEPLOYMENT_PROFILE_REVERSE_PROXY
            else prepared.get(CONF_THERMOSTAT_IP)
        )
        try:
            prepared[CONF_LISTEN_HOST] = _detect_listen_host(str(target))
        except OSError, ValueError:
            errors[CONF_LISTEN_HOST] = "listen_address_unavailable"
    errors.update(_validate_network_config(prepared))
    errors.update(_validate_profile_network(prepared))
    if CONF_API_HOSTNAME not in errors:
        prepared[CONF_API_HOSTNAME] = _normalize_api_hostname(prepared[CONF_API_HOSTNAME])
    if not errors and profile == DEPLOYMENT_PROFILE_REVERSE_PROXY:
        prepared[CONF_CERTIFICATE] = ""
        prepared[CONF_PRIVATE_KEY] = ""
    elif not errors:
        prepared[CONF_TRUSTED_PROXY_IP] = ""
    if CONF_SERIAL in prepared:
        prepared[CONF_SERIAL] = prepared[CONF_SERIAL].strip()
    return prepared, errors


def _validate_bootstrap_config(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate explicitly attested firmware bootstrap metadata."""

    errors: dict[str, str] = {}
    if not user_input.get(CONF_BOOTSTRAP_METADATA_CONFIRMED):
        errors[CONF_BOOTSTRAP_METADATA_CONFIRMED] = "commissioning_confirmation_required"
    if not user_input.get(CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED):
        errors[CONF_BOOTSTRAP_NO_UPDATE_CONFIRMED] = "commissioning_confirmation_required"
    if user_input.get(CONF_BOOTSTRAP_FIRMWARE_VERSION) not in BOOTSTRAP_FIRMWARE_ALLOWLIST:
        errors[CONF_BOOTSTRAP_FIRMWARE_VERSION] = "invalid_bootstrap_firmware"
    technician_url = user_input.get(CONF_BOOTSTRAP_TECHNICIAN_URL)
    if (
        not isinstance(technician_url, str)
        or len(technician_url) > 2048
        or any(ord(character) < 32 for character in technician_url)
    ):
        errors[CONF_BOOTSTRAP_TECHNICIAN_URL] = "invalid_technician_url"
    temp_correction_version = user_input.get(CONF_TEMP_CORRECTION_VERSION)
    firmware_version = user_input.get(CONF_BOOTSTRAP_FIRMWARE_VERSION)
    allowed = (
        TEMP_CORRECTION_VERSIONS_BY_FIRMWARE.get(firmware_version, frozenset())
        if isinstance(firmware_version, str)
        else frozenset()
    )
    if (
        not isinstance(temp_correction_version, int)
        or isinstance(temp_correction_version, bool)
        or temp_correction_version not in allowed
    ):
        errors[CONF_TEMP_CORRECTION_VERSION] = "invalid_temp_correction_version"
    return errors


def _validate_contractor_config(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate optional private contractor display configuration."""

    errors: dict[str, str] = {}
    contractor_values = {
        key: user_input.get(key, "")
        for key in (
            CONF_CONTRACTOR_BRAND,
            CONF_CONTRACTOR_PHONE,
            CONF_CONTRACTOR_LOGO_PATH,
        )
    }
    configured = {
        key: isinstance(value, str) and bool(value.strip())
        for key, value in contractor_values.items()
    }
    if any(configured.values()) and not all(configured.values()):
        errors[CONF_CONTRACTOR_BRAND] = "contractor_fields_incomplete"
    for key, value in contractor_values.items():
        if isinstance(value, str) and (len(value) > 1024 or any(ord(char) < 32 for char in value)):
            errors[key] = "invalid_contractor_value"
    logo_path = contractor_values[CONF_CONTRACTOR_LOGO_PATH]
    if isinstance(logo_path, str) and logo_path and not Path(logo_path).is_absolute():
        errors[CONF_CONTRACTOR_LOGO_PATH] = "invalid_contractor_value"
    contractor_url = user_input.get(CONF_CONTRACTOR_URL, "")
    if contractor_url and not _valid_contractor_url(contractor_url):
        errors[CONF_CONTRACTOR_URL] = "invalid_contractor_url"
    return errors


def _valid_contractor_url(value: Any) -> bool:
    """Accept a size-limited HTTPS URL for the Technician Access QR code."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 2048
        or any(ord(character) <= 32 for character in value)
    ):
        return False
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and hostname is not None
        and port != 0
        and parsed.username is None
        and parsed.password is None
    )


def _control_ready(config_entry: ConfigEntry) -> bool:
    """Return whether the live runtime satisfies every control activation gate."""

    runtime = getattr(config_entry, "runtime_data", None)
    return runtime is not None and runtime.can_enable_control


def _control_is_being_enabled(defaults: dict[str, Any], user_input: dict[str, Any]) -> bool:
    """Return whether this submission transitions control from off to on."""

    return bool(user_input.get(CONF_CONTROL_ENABLED)) and not bool(
        defaults.get(CONF_CONTROL_ENABLED)
    )


class NuveLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create one clean Nuve Local deployment entry."""

    VERSION = 2

    def __init__(self) -> None:
        self._entry_data: dict[str, Any] = {}

    @override
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            profile = user_input.get(CONF_DEPLOYMENT_PROFILE)
            if profile in DEPLOYMENT_PROFILES:
                self._entry_data = {CONF_DEPLOYMENT_PROFILE: profile}
                return await getattr(self, f"async_step_{profile}")()
        return self.async_show_form(step_id="user", data_schema=_profile_schema())

    async def async_step_reverse_proxy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_step_connection(DEPLOYMENT_PROFILE_REVERSE_PROXY, user_input)

    async def async_step_direct_tls(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_step_connection(DEPLOYMENT_PROFILE_DIRECT_TLS, user_input)

    async def _async_step_connection(
        self, profile: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            prepared, errors = _prepare_network_config(profile, user_input)
            if not errors:
                self._entry_data = prepared
                return await self.async_step_commissioning()
        return self.async_show_form(
            step_id=profile,
            data_schema=_connection_schema(profile, user_input),
            errors=errors,
        )

    async def async_step_commissioning(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            commissioning = dict(user_input)
            errors = _normalize_temp_correction_version(commissioning)
            errors.update(_validate_bootstrap_config(commissioning))
            if not errors:
                serial = self._entry_data[CONF_SERIAL]
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                data = {
                    **self._entry_data,
                    **commissioning,
                    CONF_CONTROL_ENABLED: False,
                    CONF_PAIRING_DEADLINE: new_pairing_deadline(),
                }
                return self.async_create_entry(title=f"Nuve Samo {serial}", data=data)
        return self.async_show_form(
            step_id="commissioning",
            data_schema=_commissioning_schema(user_input),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> NuveLocalOptionsFlow:
        return NuveLocalOptionsFlow()


class NuveLocalOptionsFlow(OptionsFlowWithReload):
    """Separate readiness, optional settings, and advanced network changes."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "status",
                "control",
                "pairing",
                "sources",
                "contractor",
                "commissioning",
                "network",
            ],
        )

    @property
    def _defaults(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    def _save(self, values: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **values})

    async def async_step_status(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_init()
        defaults = self._defaults
        runtime = self.config_entry.runtime_data
        server = getattr(runtime, "server", None)
        return self.async_show_form(
            step_id="status",
            data_schema=vol.Schema({}),
            description_placeholders={
                "profile": deployment_profile(defaults),
                "listener": "running" if getattr(server, "is_running", False) else "stopped",
                "pairing": "paired"
                if runtime.paired
                else ("window open" if pairing_window_is_open(defaults) else "window closed"),
                "settings": "ready" if runtime.has_settings_baseline else "waiting",
                "auto": "ready" if runtime.has_auto_mode_baseline else "waiting",
                "monitor": "fresh" if runtime.monitor_is_fresh else "waiting or stale",
                "control": runtime.control_block_reason,
            },
        )

    async def async_step_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        defaults = self._defaults
        errors: dict[str, str] = {}
        if user_input is not None:
            if _control_is_being_enabled(defaults, user_input) and not _control_ready(
                self.config_entry
            ):
                errors["base"] = "control_not_ready"
            if not errors:
                return self._save(user_input)
        return self.async_show_form(
            step_id="control",
            data_schema=_control_schema(user_input or defaults),
            errors=errors,
        )

    async def async_step_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if not user_input.get(_OPEN_PAIRING_WINDOW):
                return await self.async_step_init()
            data = dict(self.config_entry.data)
            data.pop(CONF_TOKEN_SHA256, None)
            data.pop(CONF_PAIRING_DEADLINE, None)
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            return self._save({CONF_PAIRING_DEADLINE: new_pairing_deadline()})
        return self.async_show_form(step_id="pairing", data_schema=_pairing_schema())

    async def async_step_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            values = dict(user_input)
            values[CONF_OUTDOOR_TEMPERATURE_ENTITY] = values.get(CONF_OUTDOOR_TEMPERATURE_ENTITY)
            values[CONF_WEATHER_ENTITY] = values.get(CONF_WEATHER_ENTITY)
            return self._save(values)
        return self.async_show_form(step_id="sources", data_schema=_sources_schema(self._defaults))

    async def async_step_contractor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            values = dict(user_input)
            _normalize_contractor_values(values)
            errors = _validate_contractor_config(values)
            if not errors:
                return self._save(values)
        return self.async_show_form(
            step_id="contractor",
            data_schema=_contractor_schema(user_input or self._defaults),
            errors=errors,
        )

    async def async_step_commissioning(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            values = dict(user_input)
            errors = _normalize_temp_correction_version(values)
            errors.update(_validate_bootstrap_config(values))
            if not errors:
                return self._save(values)
        return self.async_show_form(
            step_id="commissioning",
            data_schema=_commissioning_schema(user_input or self._defaults),
            errors=errors,
        )

    async def async_step_network(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            values, errors = _prepare_network_config(
                str(user_input.get(CONF_DEPLOYMENT_PROFILE)), user_input
            )
            values.pop(CONF_SERIAL, None)
            if not errors:
                return self._save(values)
        return self.async_show_form(
            step_id="network",
            data_schema=_network_schema(user_input or self._defaults),
            errors=errors,
        )
