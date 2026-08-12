"""Local endpoint used by a Nuve Samo thermostat."""

from __future__ import annotations

import asyncio
import copy
import hmac
import json
import logging
import math
import ssl
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiohttp import web
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .auth import extract_bearer_token, is_allowed_source, is_expected_host, token_sha256
from .certificate import async_create_ssl_context
from .commissioning import deployment_profile, pairing_window_is_open
from .const import (
    CONF_API_HOSTNAME,
    CONF_CERTIFICATE,
    CONF_CONTRACTOR_BRAND,
    CONF_CONTRACTOR_PHONE,
    CONF_LISTEN_HOST,
    CONF_LISTEN_PORT,
    CONF_PAIRING_DEADLINE,
    CONF_PRIVATE_KEY,
    CONF_SERIAL,
    CONF_THERMOSTAT_IP,
    CONF_TOKEN_SHA256,
    CONF_TRUSTED_PROXY_IP,
    DEPLOYMENT_PROFILE_DIRECT_TLS,
    MAX_CONCURRENT_REQUESTS,
    MAX_REQUEST_SIZE,
    REQUEST_TIMEOUT_SECONDS,
)
from .contractor import contractor_logo_signature
from .protobuf import ProtobufDecodeError, decode_event_payload, decode_monitor_payload
from .protocol import (
    NuveProtocolError,
    parse_auto_mode_upload,
    parse_current_sensors_upload,
    parse_current_stages_upload,
    parse_device_settings_upload,
    parse_settings_upload,
    parse_system_settings_upload,
    render_auto_mode_ack,
    render_current_sensors_ack,
    render_partial_settings_ack,
    render_settings_ack,
)
from .runtime import ControlNotReadyError, NuveRuntime, PersistenceUnavailableError
from .weather import firmware_forecast_payload

if TYPE_CHECKING:
    from .storage import NuveBaselineStore

_LOGGER = logging.getLogger(__name__)
_REQUEST_TOKEN_FINGERPRINT = web.RequestKey("nuve_token_fingerprint", str)


async def _async_listener_ssl_context(
    hass: HomeAssistant, config: dict[str, Any]
) -> ssl.SSLContext | None:
    """Return TLS only when Home Assistant is the thermostat-facing endpoint."""

    if deployment_profile(config) != DEPLOYMENT_PROFILE_DIRECT_TLS:
        return None
    return await async_create_ssl_context(
        hass,
        config.get(CONF_CERTIFICATE, ""),
        config.get(CONF_PRIVATE_KEY, ""),
    )


def _devapi_success_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Wrap one callback body in the wire envelope required by DevApiExecutor."""

    return {"success": True, "status": "ok", "data": data}


class NuveApiServer:
    """A narrowly authenticated HTTPS listener for one thermostat."""

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        entry: ConfigEntry,
        runtime: NuveRuntime,
        config: dict[str, Any],
        baseline_store: NuveBaselineStore | None = None,
        contractor_logo_bytes: bytes | None = None,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._runtime = runtime
        self._config = config
        self._baseline_store = baseline_store
        self._runner: web.AppRunner | None = None
        self._token_lock = asyncio.Lock()
        self._baseline_lock = runtime._transaction_lock
        self._request_slots = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self._logged_first_settings_upload = False
        self._contractor_logo_bytes = contractor_logo_bytes
        configured_hostname = str(config[CONF_API_HOSTNAME]).lower().rstrip(".")
        self._expected_hosts = {configured_hostname}
        if baseline_store is not None:
            runtime.async_set_persistence_listener(self.async_save_candidate)

    @property
    def is_running(self) -> bool:
        """Return whether the dedicated listener owns an active app runner."""

        return self._runner is not None

    async def async_start(self) -> None:
        """Start the profile-specific dedicated listener."""

        ssl_context = await _async_listener_ssl_context(self._hass, self._config)

        app = self._create_app()

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(
            self._runner,
            self._config[CONF_LISTEN_HOST],
            self._config[CONF_LISTEN_PORT],
            ssl_context=ssl_context,
        )
        try:
            await site.start()
        except Exception:
            await self._runner.cleanup()
            self._runner = None
            raise
        _LOGGER.info(
            "Nuve local listener started on %s:%s",
            self._config[CONF_LISTEN_HOST],
            self._config[CONF_LISTEN_PORT],
        )

    def _create_app(self) -> web.Application:
        """Build the isolated HTTP application for this entry."""

        app = web.Application(client_max_size=MAX_REQUEST_SIZE, middlewares=[self._security])
        app.router.add_get("/", self._root)
        app.router.add_get("/api/sync/getSettings", self._get_settings)
        app.router.add_post("/api/sync/update", self._update_settings)
        app.router.add_get("/api/sync/autoMode", self._get_auto_mode)
        app.router.add_post("/api/sync/autoMode", self._update_auto_mode)
        app.router.add_get("/api/sync/getContractorInfo", self._get_contractor_info)
        app.router.add_get("/api/contractor-logo", self._contractor_logo)
        app.router.add_get("/api/weather-current", self._weather_current)
        app.router.add_get("/api/weather-forecast", self._weather_forecast)
        app.router.add_get("/api/designTemperature", self._design_temperature)
        app.router.add_post("/api/device/settings", self._update_device_settings)
        app.router.add_post("/api/device/system", self._update_system_settings)
        app.router.add_post("/api/device/current-sensors", self._update_current_sensors)
        app.router.add_post("/api/device/current-stages", self._update_current_stages)
        app.router.add_post("/api/device/wifi-off", self._wifi_off)
        app.router.add_post("/api/monitor/data", self._monitor_data)
        app.router.add_post("/api/monitor/event", self._monitor_event)
        app.router.add_post("/api/monitor/report", self._monitor_report)
        app.router.add_route("*", "/{tail:.*}", self._unknown)
        return app

    async def async_stop(self) -> None:
        """Stop the listener and release its socket."""

        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        await self._runtime.async_shutdown()

    @web.middleware
    async def _security(self, request: web.Request, handler: Any) -> web.StreamResponse:
        peername = request.transport.get_extra_info("peername") if request.transport else None
        peer_ip = peername[0] if peername else None
        if not is_allowed_source(
            peer_ip=peer_ip,
            thermostat_ip=self._config[CONF_THERMOSTAT_IP],
            trusted_proxy_ip=self._config.get(CONF_TRUSTED_PROXY_IP),
            forwarded_for=request.headers.getall("X-Forwarded-For", []),
        ):
            self._runtime.rejected_requests += 1
            raise web.HTTPForbidden(text="source not allowed")

        if not is_expected_host(request.host, self._expected_hosts):
            self._runtime.rejected_requests += 1
            raise web.HTTPBadRequest(text="unexpected host")

        self._runtime.count_endpoint(request.method, request.path)
        if request.path == "/":
            return await handler(request)

        if (
            request.path != "/api/sync/update"
            and request.query.get("sn") != self._config[CONF_SERIAL]
        ):
            self._runtime.rejected_requests += 1
            raise web.HTTPNotFound(text="unknown thermostat")

        if request.path == "/api/contractor-logo":
            expected_fingerprint = self._entry.data.get(CONF_TOKEN_SHA256)
            expected_signature = (
                contractor_logo_signature(
                    token_fingerprint=expected_fingerprint,
                    serial=self._config[CONF_SERIAL],
                )
                if expected_fingerprint is not None
                else None
            )
            presented_signature = request.query.get("sig", "")
            if expected_signature is None or not hmac.compare_digest(
                expected_signature, presented_signature
            ):
                self._runtime.rejected_requests += 1
                raise web.HTTPUnauthorized(text="invalid contractor logo signature")
            return await self._call_handler(request, handler)

        token = extract_bearer_token(request.headers.get("Authorization", ""))
        if token is None:
            self._runtime.rejected_requests += 1
            raise web.HTTPUnauthorized(text="invalid bearer token")

        presented_sha256 = token_sha256(token)
        request[_REQUEST_TOKEN_FINGERPRINT] = presented_sha256
        expected_sha256 = self._entry.data.get(CONF_TOKEN_SHA256)
        if expected_sha256 is None:
            if not pairing_window_is_open(self._config):
                self._runtime.rejected_requests += 1
                raise web.HTTPUnauthorized(text="pairing window is closed")
            async with self._token_lock:
                expected_sha256 = self._entry.data.get(CONF_TOKEN_SHA256)
                if expected_sha256 is None:
                    response = await self._call_handler(request, handler)
                    if response.status < 400:
                        data = {**self._entry.data, CONF_TOKEN_SHA256: presented_sha256}
                        data.pop(CONF_PAIRING_DEADLINE, None)
                        options = dict(self._entry.options)
                        options.pop(CONF_PAIRING_DEADLINE, None)
                        self._hass.config_entries.async_update_entry(
                            self._entry,
                            data=data,
                            options=options,
                        )
                        self._config[CONF_TOKEN_SHA256] = presented_sha256
                        self._config.pop(CONF_PAIRING_DEADLINE, None)
                        self._runtime.async_set_paired()
                        _LOGGER.info(
                            "Learned bearer-token fingerprint for Nuve thermostat %s",
                            self._runtime.serial,
                        )
                        self._runtime.async_note_authenticated_contact(datetime.now(UTC))
                    return response

        if not hmac.compare_digest(expected_sha256, presented_sha256):
            self._runtime.rejected_requests += 1
            raise web.HTTPUnauthorized(text="bearer token does not match")

        # The source, serial/route, and persisted token all match. Record the
        # authenticated contact before the handler so a current device poll can
        # participate in the delivery-time safety check.
        self._runtime.async_note_authenticated_contact(datetime.now(UTC))
        return await self._call_handler(request, handler)

    async def _call_handler(self, request: web.Request, handler: Any) -> web.StreamResponse:
        """Run a validated route within the listener's resource limits."""

        async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
            async with self._request_slots:
                return await handler(request)

    async def _root(self, request: web.Request) -> web.Response:
        return web.json_response({"success": True, "status": "ok", "connected": True})

    async def _empty_sync(self, request: web.Request) -> web.Response:
        # Captures prove these polling paths but not their command schema. Returning
        # an empty data object avoids fabricating a thermostat configuration.
        return web.json_response(_devapi_success_payload({}))

    async def _get_contractor_info(self, request: web.Request) -> web.Response:
        """Return the exact stock metadata/download contract when explicitly configured."""

        if not self._runtime.contractor_info_ready or self._contractor_logo_bytes is None:
            return web.json_response(
                {"success": False, "status": "unsupported"},
                status=404,
            )
        hostname = str(self._config[CONF_API_HOSTNAME])
        port = int(self._config[CONF_LISTEN_PORT])
        authority = hostname if port == 443 else f"{hostname}:{port}"
        token_fingerprint = request[_REQUEST_TOKEN_FINGERPRINT]
        logo_query = urlencode(
            {
                "sn": self._config[CONF_SERIAL],
                "sig": contractor_logo_signature(
                    token_fingerprint=token_fingerprint,
                    serial=self._config[CONF_SERIAL],
                ),
            }
        )
        logo_url = f"https://{authority}/api/contractor-logo?{logo_query}"
        return web.json_response(
            _devapi_success_payload(
                {
                    "brand": self._config[CONF_CONTRACTOR_BRAND],
                    "phone": self._config[CONF_CONTRACTOR_PHONE],
                    "logo": logo_url,
                }
            )
        )

    async def _contractor_logo(self, request: web.Request) -> web.Response:
        """Serve the setup-validated PNG through the signed firmware flow."""

        if not self._runtime.contractor_info_ready or self._contractor_logo_bytes is None:
            raise web.HTTPNotFound(text="contractor logo is not configured")
        return web.Response(
            body=self._contractor_logo_bytes,
            content_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    async def _get_settings(self, request: web.Request) -> web.StreamResponse:
        response: web.StreamResponse | None = None

        async def send_command(body: dict[str, Any]) -> None:
            nonlocal response
            response = await self._write_json_response(request, body)

        try:
            body = await self._runtime.async_get_settings_response(
                requested_at=datetime.now(UTC), response_sender=send_command
            )
        except PersistenceUnavailableError as err:
            if response is not None and response.prepared:
                _LOGGER.error(
                    "Nuve settings command was sent but its final delivery boundary "
                    "could not be persisted; control is latched off"
                )
                return response
            raise web.HTTPServiceUnavailable(text="canonical persistence unavailable") from err
        if response is not None:
            return response
        return web.json_response(_devapi_success_payload(body))

    async def _update_settings(self, request: web.Request) -> web.Response:
        if not self._logged_first_settings_upload:
            _LOGGER.warning(
                "Received authenticated Nuve full settings upload (%s bytes declared)",
                request.content_length,
            )
            self._logged_first_settings_upload = True
        body = await self._json_object(request)
        try:
            snapshot = parse_settings_upload(body, serial=self._runtime.serial)
        except NuveProtocolError as err:
            _LOGGER.warning("Rejected Nuve full settings upload: %s", err)
            raise web.HTTPBadRequest(text=str(err)) from err
        received_at = datetime.now(UTC)
        async with self._baseline_lock:
            revision, candidate = self._runtime.prepare_settings_snapshot(
                snapshot, received_at=received_at
            )
            await self._persist_and_commit(
                candidate,
                lambda: self._runtime.async_accept_settings_snapshot(
                    snapshot,
                    received_at=received_at,
                    prepared_revision=revision,
                ),
                family="settings",
            )
        return web.json_response(_devapi_success_payload(render_settings_ack(revision)))

    async def _get_auto_mode(self, request: web.Request) -> web.StreamResponse:
        response: web.StreamResponse | None = None

        async def send_command(body: dict[str, Any]) -> None:
            nonlocal response
            response = await self._write_json_response(request, body)

        try:
            body = await self._runtime.async_get_auto_mode_response(
                requested_at=datetime.now(UTC), response_sender=send_command
            )
        except PersistenceUnavailableError as err:
            if response is not None and response.prepared:
                _LOGGER.error(
                    "Nuve Auto command was sent but its final delivery boundary "
                    "could not be persisted; control is latched off"
                )
                return response
            raise web.HTTPServiceUnavailable(text="canonical persistence unavailable") from err
        if response is not None:
            return response
        return web.json_response(_devapi_success_payload(body))

    @staticmethod
    async def _write_json_response(
        request: web.Request, body: dict[str, Any]
    ) -> web.StreamResponse:
        """Write one command body before its confirmation boundary is finalized."""

        payload = json.dumps(
            _devapi_success_payload(body),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        response = web.StreamResponse(status=200)
        response.content_type = "application/json"
        response.content_length = len(payload)
        await response.prepare(request)
        await response.write(payload)
        await response.write_eof()
        return response

    async def _update_auto_mode(self, request: web.Request) -> web.Response:
        body = await self._json_object(request)
        try:
            snapshot = parse_auto_mode_upload(body, serial=self._runtime.serial)
        except NuveProtocolError as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        received_at = datetime.now(UTC)
        async with self._baseline_lock:
            revision, candidate = self._runtime.prepare_auto_mode_snapshot(
                snapshot, received_at=received_at
            )
            await self._persist_and_commit(
                candidate,
                lambda: self._runtime.async_accept_auto_mode_snapshot(
                    snapshot,
                    received_at=received_at,
                    prepared_revision=revision,
                ),
                family="auto",
            )
        return web.json_response(_devapi_success_payload(render_auto_mode_ack(revision)))

    async def _update_device_settings(self, request: web.Request) -> web.Response:
        body = await self._json_object(request)
        try:
            snapshot = parse_device_settings_upload(body)
        except NuveProtocolError as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        async with self._baseline_lock:
            received_at = datetime.now(UTC)
            try:
                revision, candidate, full = self._runtime.prepare_partial_settings(
                    "settings", snapshot, received_at=received_at
                )
            except ControlNotReadyError as err:
                raise web.HTTPConflict(text="full settings baseline is not available") from err
            await self._persist_and_commit(
                candidate,
                lambda: self._runtime.async_accept_partial_settings(
                    "settings",
                    snapshot,
                    received_at=received_at,
                    prepared_snapshot=full,
                    prepared_revision=revision,
                ),
                family="settings",
            )
        return web.json_response(_devapi_success_payload(render_partial_settings_ack(revision)))

    async def _update_system_settings(self, request: web.Request) -> web.Response:
        body = await self._json_object(request)
        try:
            snapshot = parse_system_settings_upload(body, serial=self._runtime.serial)
        except NuveProtocolError as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        async with self._baseline_lock:
            received_at = datetime.now(UTC)
            try:
                revision, candidate, full = self._runtime.prepare_partial_settings(
                    "system", snapshot, received_at=received_at
                )
            except ControlNotReadyError as err:
                raise web.HTTPConflict(text="full settings baseline is not available") from err
            await self._persist_and_commit(
                candidate,
                lambda: self._runtime.async_accept_partial_settings(
                    "system",
                    snapshot,
                    received_at=received_at,
                    prepared_snapshot=full,
                    prepared_revision=revision,
                ),
                family="settings",
            )
        return web.json_response(_devapi_success_payload(render_partial_settings_ack(revision)))

    async def _update_current_sensors(self, request: web.Request) -> web.Response:
        body = await self._json_object(request)
        try:
            snapshot = parse_current_sensors_upload(body)
        except NuveProtocolError as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        async with self._baseline_lock:
            self._runtime.async_accept_current_sensors(snapshot, received_at=datetime.now(UTC))
        return web.json_response(_devapi_success_payload(render_current_sensors_ack(snapshot)))

    async def _update_current_stages(self, request: web.Request) -> web.Response:
        body = await self._json_object(request)
        try:
            snapshot = parse_current_stages_upload(body)
        except NuveProtocolError as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        async with self._baseline_lock:
            self._runtime.async_accept_current_stages(snapshot)
        return web.json_response(_devapi_success_payload(snapshot))

    @staticmethod
    async def _json_object(request: web.Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError, TypeError:
            raise web.HTTPBadRequest(text="invalid JSON") from None
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="JSON body must be an object")
        return body

    async def _wifi_off(self, request: web.Request) -> web.Response:
        body = await self._json_object(request)
        if body != {"manual_off": False}:
            raise web.HTTPBadRequest(text="unexpected wifi-off request")
        return web.json_response(_devapi_success_payload({}))

    async def _monitor_data(self, request: web.Request) -> web.Response:
        payload = await request.read()
        try:
            state = decode_monitor_payload(payload, received_at=datetime.now(UTC))
        except ProtobufDecodeError as err:
            _LOGGER.warning("Rejected malformed Nuve monitor payload: %s", err)
            raise web.HTTPBadRequest(text="malformed monitor payload") from err
        try:
            await self._runtime.async_process_monitor_state(state)
        except PersistenceUnavailableError as err:
            raise web.HTTPServiceUnavailable(text="canonical persistence unavailable") from err
        return web.json_response(_devapi_success_payload({}))

    async def _monitor_event(self, request: web.Request) -> web.Response:
        """Acknowledge a validated UI-event batch without retaining its targets."""

        payload = await request.read()
        try:
            decode_event_payload(payload)
        except ProtobufDecodeError as err:
            _LOGGER.warning("Rejected malformed Nuve event payload: %s", err)
            raise web.HTTPBadRequest(text="malformed event payload") from err
        return web.json_response(_devapi_success_payload({}))

    async def _async_save_baselines(self) -> None:
        """Persist only device-originated or telemetry-confirmed snapshots."""

        async with self._baseline_lock:
            await self._async_save_baselines_unlocked()

    async def _async_save_baselines_unlocked(self) -> None:
        """Persist while the caller owns the baseline serialization lock."""

        if self._baseline_store is not None:
            await self._baseline_store.async_save(self._runtime.persistent_baselines())

    async def _async_save_candidate(self, candidate: dict[str, Any]) -> None:
        """Persist a prepared full upload before mutating the live runtime."""

        if self._baseline_store is None:
            raise RuntimeError("Nuve baseline persistence is unavailable")
        await self._baseline_store.async_save(candidate)

    async def _persist_and_commit(
        self,
        candidate: dict[str, Any],
        commit: Callable[[], object],
        *,
        family: Literal["settings", "auto"],
    ) -> None:
        """Finish an exact durable write before exposing its runtime commit."""

        started_at = datetime.now(UTC)
        self._runtime._trace_event("persistence", family=family, result="started", at=started_at)
        if self._runtime.persistence_fault_latched:
            self._runtime._trace_elapsed_event(
                "persistence", started_at, family=family, result="unavailable"
            )
            raise web.HTTPServiceUnavailable(text="canonical persistence requires reload")
        task = asyncio.create_task(
            self._async_save_candidate(candidate), name="Persist Nuve canonical state"
        )
        cancelled = False
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as outer_cancel:
            if task.cancelled():
                self._runtime._latch_persistence_fault()
                self._runtime._trace_elapsed_event(
                    "persistence", started_at, family=family, result="cancelled"
                )
                raise web.HTTPServiceUnavailable(
                    text="canonical persistence task was cancelled"
                ) from outer_cancel
            cancelled = True
            try:
                await task
            except asyncio.CancelledError as inner_cancel:
                self._runtime._latch_persistence_fault()
                self._runtime._trace_elapsed_event(
                    "persistence", started_at, family=family, result="cancelled"
                )
                raise web.HTTPServiceUnavailable(
                    text="canonical persistence task was cancelled"
                ) from inner_cancel
            except Exception:
                self._runtime._latch_persistence_fault()
                self._runtime._trace_elapsed_event(
                    "persistence", started_at, family=family, result="failed"
                )
                raise
        except Exception:
            self._runtime._latch_persistence_fault()
            self._runtime._trace_elapsed_event(
                "persistence", started_at, family=family, result="failed"
            )
            raise web.HTTPServiceUnavailable(text="canonical persistence unavailable") from None

        try:
            commit()
        except Exception:
            # Disk now contains the candidate but runtime did not complete its
            # matching transition.  Stop all canonical traffic until reload.
            self._runtime._latch_persistence_fault()
            self._runtime._trace_elapsed_event(
                "persistence", started_at, family=family, result="commit_failed"
            )
            raise web.HTTPServiceUnavailable(text="canonical commit requires reload") from None
        self._runtime.persistence_healthy = True
        self._runtime._trace_elapsed_event(
            "persistence",
            started_at,
            family=family,
            result="committed_after_cancel" if cancelled else "committed",
        )
        if cancelled:
            raise asyncio.CancelledError

    async def async_save_candidate(self, candidate: dict[str, Any]) -> None:
        """Persist one coordinator-locked candidate for the runtime."""

        await self._async_save_candidate(candidate)

    async def async_save_baselines(self) -> None:
        """Persist runtime state at command and shutdown boundaries."""

        await self._async_save_baselines()

    async def _monitor_report(self, request: web.Request) -> web.Response:
        body = await self._json_object(request)
        if "data" not in body:
            raise web.HTTPBadRequest(text="monitor report is missing data")
        return web.json_response(_devapi_success_payload({}))

    async def _weather_current(self, request: web.Request) -> web.Response:
        temperature_c = self._runtime.outdoor_temperature_c
        if not self._runtime.outdoor_is_fresh or temperature_c is None:
            return web.json_response({"success": False, "status": "unavailable"}, status=503)

        now = datetime.now(UTC)
        assert self._runtime.outdoor_observed_at is not None
        try:
            local_offset = now.astimezone(ZoneInfo(self._hass.config.time_zone)).utcoffset()
        except KeyError, ZoneInfoNotFoundError:
            local_offset = None
        # WeatherService consumes OpenWeather-compatible current conditions.
        # Missing numeric members silently convert to zero in Qt, so always
        # provide current-observation fallbacks for today's bounds.
        minimum = maximum = temperature_c
        forecast = self._runtime.forecast_payload
        if isinstance(forecast, dict):
            rows = forecast.get("list")
            if isinstance(rows, list) and rows:
                first = rows[0]
                row_temp = first.get("temp") if isinstance(first, dict) else None
                row_timestamp = first.get("dt") if isinstance(first, dict) else None
                try:
                    zone = ZoneInfo(self._hass.config.time_zone)
                    row_is_today = (
                        isinstance(row_timestamp, int | float)
                        and not isinstance(row_timestamp, bool)
                        and math.isfinite(row_timestamp)
                        and datetime.fromtimestamp(row_timestamp, UTC).astimezone(zone).date()
                        == now.astimezone(zone).date()
                    )
                except KeyError, OSError, OverflowError, ValueError, ZoneInfoNotFoundError:
                    row_is_today = False
                if row_is_today and isinstance(row_temp, dict):
                    candidate_min = row_temp.get("min")
                    candidate_max = row_temp.get("max")
                    if (
                        isinstance(candidate_min, int | float)
                        and not isinstance(candidate_min, bool)
                        and math.isfinite(candidate_min)
                        and isinstance(candidate_max, int | float)
                        and not isinstance(candidate_max, bool)
                        and math.isfinite(candidate_max)
                    ):
                        minimum = float(candidate_min)
                        maximum = float(candidate_max)
        main: dict[str, Any] = {
            "temp": temperature_c,
            "temp_min": minimum,
            "temp_max": maximum,
        }
        if self._runtime.outdoor_humidity_percent is not None:
            main["humidity"] = self._runtime.outdoor_humidity_percent
        data: dict[str, Any] = {
            "dt": int(self._runtime.outdoor_observed_at.timestamp()),
            "name": self._runtime.outdoor_location_name,
            "main": main,
            "timezone": int(local_offset.total_seconds()) if local_offset else 0,
        }
        country = getattr(self._hass.config, "country", None)
        if isinstance(country, str) and country:
            data["sys"] = {"country": country}
        if self._runtime.outdoor_weather is not None:
            data["weather"] = [copy.deepcopy(self._runtime.outdoor_weather)]
        return web.json_response(_devapi_success_payload(data))

    async def _design_temperature(self, request: web.Request) -> web.Response:
        # These values drive HVAC design logic and are Fahrenheit even on a
        # metric thermostat.  An empty DevApi data object is the firmware-proven
        # non-applying success response and avoids its ten-second retry loop.
        return web.json_response(_devapi_success_payload({}))

    async def _weather_forecast(self, request: web.Request) -> web.Response:
        # DevApiExecutor unwraps the outer data object before the recovered
        # forecast parser sees this list. An empty list touches no forecast
        # slot and resets the retry interval, so it remains the fail-closed
        # response whenever HA has no fully validated cached snapshot.
        payload = self._runtime.forecast_payload
        if not self._runtime.forecast_healthy or payload is None:
            payload = {"list": []}
        else:
            payload = firmware_forecast_payload(payload)
        return web.json_response(_devapi_success_payload(copy.deepcopy(payload)))

    async def _unknown(self, request: web.Request) -> web.Response:
        if request.method == "GET" and request.path == "/api/sync/client":
            _LOGGER.debug(
                "Nuve thermostat requested the intentionally unsupported private "
                "client-identity endpoint"
            )
        else:
            _LOGGER.warning(
                "Nuve thermostat requested unsupported endpoint %s %s",
                request.method,
                request.path,
            )
        return web.json_response({"success": False, "status": "unsupported"}, status=404)
