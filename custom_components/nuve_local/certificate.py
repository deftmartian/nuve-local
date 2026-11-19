"""Configured TLS certificate handling for the direct Nuve listener."""

from __future__ import annotations

import os
import ssl
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

# (st_mtime_ns, st_size, st_ino) of the certificate and the private key. Comparing
# inodes as well as times catches a renewal tool that swaps files by rename or
# re-points a symlink (os.stat follows symlinks).
type FileSignature = tuple[tuple[int, int, int], tuple[int, int, int]]


def _context_from_paths(certificate: str, private_key: str) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate, private_key)
    return context


def _file_signature(certificate: str, private_key: str) -> FileSignature:
    def one(path: str) -> tuple[int, int, int]:
        stat = os.stat(path)
        return stat.st_mtime_ns, stat.st_size, stat.st_ino

    return one(certificate), one(private_key)


class ReloadableCertificate:
    """A direct-TLS listener context that can switch to renewed certificate files.

    The listener is built with ``context`` and that context is never modified
    after start: OpenSSL does not support changing a context while handshakes use
    it. A renewal is loaded into a complete, fresh context instead (in an
    executor), then published on the event loop. ``context``'s SNI callback, which
    runs on the event loop for every handshake, with or without SNI, points each
    new connection at the current context. Existing connections are unaffected.
    """

    def __init__(self, certificate: str, private_key: str) -> None:
        """Load the pair once; raise if it is missing or does not match."""

        self._certificate = certificate
        self._private_key = private_key
        self._signature = _file_signature(certificate, private_key)
        self.context = _context_from_paths(certificate, private_key)
        self._current = self.context
        self.context.sni_callback = self._select_current

    @property
    def current(self) -> ssl.SSLContext:
        """Return the context new handshakes are switched to."""

        return self._current

    def _select_current(
        self, ssl_object: ssl.SSLObject, _server_name: str | None, context: ssl.SSLContext
    ) -> None:
        if self._current is not context:
            ssl_object.context = self._current

    def load_if_changed(self) -> tuple[ssl.SSLContext, FileSignature] | None:
        """Build a fresh context if the files changed since the last publish.

        Blocking: run in an executor. Files are read once, into a new context, so
        a renewal written mid-check can only make this raise (and be retried); it
        can never leave a published context with a mismatched pair.
        """

        signature = _file_signature(self._certificate, self._private_key)
        if signature == self._signature:
            return None
        return _context_from_paths(self._certificate, self._private_key), signature

    def publish(self, context: ssl.SSLContext, signature: FileSignature) -> None:
        """Switch new handshakes to ``context``. Call on the event loop."""

        self._current = context
        self._signature = signature


async def async_load_certificate(
    hass: HomeAssistant,
    certificate: str,
    private_key: str,
) -> ReloadableCertificate:
    """Load the explicit certificate pair required by direct-TLS mode."""

    if not certificate or not private_key:
        raise ValueError("direct TLS requires a certificate and private key")
    return await hass.async_add_executor_job(ReloadableCertificate, certificate, private_key)
