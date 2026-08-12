"""Validation for the exact 1.5.8 stock contractor-logo download flow."""

from __future__ import annotations

import hashlib
import hmac
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .const import MAX_CONTRACTOR_LOGO_SIZE

CONTRACTOR_LOGO_SIZE = (750, 375)
_CONTRACTOR_LOGO_PURPOSE = b"nuve-local:contractor-logo:v1"


class ContractorLogoError(ValueError):
    """The configured image does not match the proven thermostat contract."""


def contractor_logo_signature(*, token_fingerprint: str, serial: str) -> str:
    """Bind the unauthenticated firmware download to this paired thermostat.

    Firmware 1.5.8 does not forward its bearer header from the authenticated
    contractor-info request to the subsequent image download. The persisted
    bearer-token fingerprint is still secret enough to key a purpose-specific
    HMAC, while the serial and normal source/Host gates prevent cross-device
    reuse.
    """

    message = b"\0".join((_CONTRACTOR_LOGO_PURPOSE, serial.encode()))
    return hmac.new(token_fingerprint.encode(), message, hashlib.sha256).hexdigest()


def load_validated_contractor_logo(path_value: str) -> bytes:
    """Load an exact-size RGBA PNG without retaining an open file handle."""

    path = Path(path_value)
    if not path.is_absolute() or not path.is_file():
        raise ContractorLogoError("contractor logo must be an existing absolute file")
    if path.stat().st_size > MAX_CONTRACTOR_LOGO_SIZE:
        raise ContractorLogoError("contractor logo exceeds the one-megabyte limit")
    data = path.read_bytes()
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG":
                raise ContractorLogoError("contractor logo must be PNG")
            if image.size != CONTRACTOR_LOGO_SIZE:
                raise ContractorLogoError("contractor logo must be 750 by 375 pixels")
            if image.mode != "RGBA":
                raise ContractorLogoError("contractor logo must use RGBA color")
    except (OSError, UnidentifiedImageError) as err:
        raise ContractorLogoError("contractor logo is not a valid PNG") from err
    return data
