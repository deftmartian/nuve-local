"""Configured TLS certificate handling for the direct Nuve listener."""

from __future__ import annotations

import ssl
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def _context_from_paths(certificate: str, private_key: str) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate, private_key)
    return context


async def async_create_ssl_context(
    hass: HomeAssistant,
    certificate: str,
    private_key: str,
) -> ssl.SSLContext:
    """Load the explicit certificate pair required by direct-TLS mode."""

    if not certificate or not private_key:
        raise ValueError("direct TLS requires a certificate and private key")
    return await hass.async_add_executor_job(_context_from_paths, certificate, private_key)
