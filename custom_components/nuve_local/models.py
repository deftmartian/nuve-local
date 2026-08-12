"""In-memory state models for Nuve Local."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum


class NuveMode(IntEnum):
    """Running modes used by both Nuve JSON and monitor telemetry."""

    NONE = 0
    COOL = 1
    HEAT = 2
    AUTO = 3
    VACATION = 4
    OFF = 5
    EMERGENCY_HEAT = 6


class NuveSystemType(IntEnum):
    """HVAC equipment types reported by the thermostat."""

    NONE = 0
    TRADITIONAL = 1
    HEAT_PUMP = 2
    COOLING_ONLY = 3
    HEATING_ONLY = 4
    DUAL_FUEL_HEATING = 5


@dataclass(frozen=True, slots=True)
class MonitorRecord:
    """One record from a Nuve monitor protobuf upload."""

    timestamp: datetime | None
    fixed32: dict[int, float] = field(default_factory=dict)
    varints: dict[int, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NuveState:
    """The latest locally observed state of a thermostat."""

    available: bool = False
    last_seen: datetime | None = None
    sample_time: datetime | None = None
    current_temperature: float | None = None
    current_humidity: float | None = None
    target_temperature: float | None = None
    target_humidity: float | None = None
    auto_temperature_low: float | None = None
    auto_temperature_high: float | None = None
    mcu_temperature: float | None = None
    air_pressure: float | None = None
    air_quality_level: int | None = None
    cooling_stage: int | None = None
    heating_stage: int | None = None
    fan_active: bool | None = None
    led_active: bool | None = None
    system_type: NuveSystemType | None = None
    mode: NuveMode | None = None
    online: bool | None = None
    schedule_type: int | None = None
    settings_revision: str | None = None
    monitor_is_sync: bool = False
    raw_fixed32: dict[int, float] = field(default_factory=dict)
    raw_varints: dict[int, int] = field(default_factory=dict)
    records_received: int = 0
