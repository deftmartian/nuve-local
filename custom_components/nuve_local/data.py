"""Typed per-entry runtime data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .runtime import NuveRuntime
    from .server import NuveApiServer
    from .sources import ForecastRefresh


@dataclass(slots=True)
class NuveRuntimeData:
    """Objects owned by one loaded Nuve Local config entry."""

    runtime: NuveRuntime
    server: NuveApiServer
    forecast_refresh: ForecastRefresh | None = None


type NuveConfigEntry = ConfigEntry[NuveRuntimeData]
