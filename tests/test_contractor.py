"""Contractor-logo input validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from custom_components.nuve_local.contractor import (
    ContractorLogoError,
    load_validated_contractor_logo,
)


def _write_png(path: Path, size: tuple[int, int], mode: str = "RGBA") -> None:
    Image.new(mode, size, (10, 20, 30, 255)).save(path, format="PNG")


def test_exact_thermostat_logo_shape_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "logo.png"
    _write_png(path, (750, 375))

    assert load_validated_contractor_logo(str(path)) == path.read_bytes()


def test_wrong_dimensions_or_color_mode_fail_closed(tmp_path: Path) -> None:
    wrong_size = tmp_path / "wrong-size.png"
    _write_png(wrong_size, (751, 375))
    with pytest.raises(ContractorLogoError, match="750 by 375"):
        load_validated_contractor_logo(str(wrong_size))

    wrong_mode = tmp_path / "wrong-mode.png"
    _write_png(wrong_mode, (750, 375), mode="RGB")
    with pytest.raises(ContractorLogoError, match="RGBA"):
        load_validated_contractor_logo(str(wrong_mode))
