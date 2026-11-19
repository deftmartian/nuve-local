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
    """A direct-TLS server context that can pick up renewed certificate files.

    The listener keeps serving ``context``. Loading a new chain into an existing
    SSLContext affects only later handshakes, so renewal needs no socket restart.
    """

    def __init__(self, certificate: str, private_key: str) -> None:
        """Load the pair once; raise if it is missing or does not match."""

        self._certificate = certificate
        self._private_key = private_key
        self._signature = _file_signature(certificate, private_key)
        self.context = _context_from_paths(certificate, private_key)

    def reload_if_changed(self) -> bool:
        """Load the files again if they changed since the last successful load.

        Blocking: run in an executor. The new pair is validated in a throwaway
        context first, because a failed ``load_cert_chain`` can leave the live
        context holding a new certificate with the old key. On any error the live
        context keeps the previous pair and the error propagates, so the next
        check retries (for example after a renewal tool finishes writing).
        """

        signature = _file_signature(self._certificate, self._private_key)
        if signature == self._signature:
            return False
        _context_from_paths(self._certificate, self._private_key)
        self.context.load_cert_chain(self._certificate, self._private_key)
        self._signature = signature
        return True


async def async_load_certificate(
    hass: HomeAssistant,
    certificate: str,
    private_key: str,
) -> ReloadableCertificate:
    """Load the explicit certificate pair required by direct-TLS mode."""

    if not certificate or not private_key:
        raise ValueError("direct TLS requires a certificate and private key")
    return await hass.async_add_executor_job(ReloadableCertificate, certificate, private_key)
