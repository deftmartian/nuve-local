"""Minimal decoders for Nuve protobuf uploads.

The thermostat sends monitor and UI-event envelopes containing repeated field-1
records. Only fields confirmed by firmware descriptors and captures are
accepted or promoted. Event targets are validated and then discarded.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Iterator
from datetime import UTC, datetime

from .models import MonitorRecord, NuveMode, NuveState, NuveSystemType


class ProtobufDecodeError(ValueError):
    """Raised when a protobuf payload is malformed or unsupported."""


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for byte_index in range(10):
        if offset >= len(data):
            raise ProtobufDecodeError("truncated varint")
        byte = data[offset]
        offset += 1
        if byte_index == 9 and byte > 1:
            raise ProtobufDecodeError("varint exceeds 64 bits")
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ProtobufDecodeError("varint exceeds 64 bits")


def _decode_int64(value: int) -> int:
    """Interpret one protobuf varint as a signed two's-complement int64."""

    return value - (1 << 64) if value >= 1 << 63 else value


def iter_fields(data: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    """Yield ``(field_number, wire_type, value)`` from a protobuf message."""

    offset = 0
    while offset < len(data):
        key, offset = _read_varint(data, offset)
        field_number = key >> 3
        wire_type = key & 0x07
        if field_number == 0:
            raise ProtobufDecodeError("field number zero is invalid")

        if wire_type == 0:
            value, offset = _read_varint(data, offset)
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise ProtobufDecodeError("truncated fixed64")
            value = int.from_bytes(data[offset:end], "little")
            offset = end
        elif wire_type == 2:
            length, offset = _read_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ProtobufDecodeError("truncated length-delimited field")
            value = data[offset:end]
            offset = end
        elif wire_type == 5:
            end = offset + 4
            if end > len(data):
                raise ProtobufDecodeError("truncated fixed32")
            value = int.from_bytes(data[offset:end], "little")
            offset = end
        else:
            raise ProtobufDecodeError(f"unsupported wire type {wire_type}")
        yield field_number, wire_type, value


def _decode_timestamp(data: bytes) -> datetime | None:
    for field_number, wire_type, value in iter_fields(data):
        if field_number == 1 and wire_type == 0 and isinstance(value, int):
            try:
                return datetime.fromtimestamp(value, tz=UTC)
            except OverflowError, OSError, ValueError:
                return None
    return None


def _validate_event_timestamp(data: bytes) -> None:
    """Validate an embedded ``google.protobuf.Timestamp`` message."""

    seconds = 0
    nanos = 0
    seen: set[int] = set()
    for field_number, wire_type, value in iter_fields(data):
        if field_number not in (1, 2) or wire_type != 0 or not isinstance(value, int):
            raise ProtobufDecodeError("event timestamp contains an unsupported field")
        if field_number in seen:
            raise ProtobufDecodeError("event timestamp contains a duplicate field")
        seen.add(field_number)
        if field_number == 1:
            seconds = _decode_int64(value)
        else:
            nanos = _decode_int64(value)

    # These are the bounds defined by google.protobuf.Timestamp.
    if not -62_135_596_800 <= seconds <= 253_402_300_799:
        raise ProtobufDecodeError("event timestamp seconds are out of range")
    if not 0 <= nanos <= 999_999_999:
        raise ProtobufDecodeError("event timestamp nanos are out of range")


def _validate_event(data: bytes) -> None:
    """Validate one exact ``Event`` record without retaining its target."""

    seen: set[int] = set()
    for field_number, wire_type, value in iter_fields(data):
        if field_number in seen:
            raise ProtobufDecodeError("event contains a duplicate field")
        seen.add(field_number)

        if field_number == 1 and wire_type == 2 and isinstance(value, bytes):
            _validate_event_timestamp(value)
        elif field_number == 2 and wire_type == 0 and isinstance(value, int):
            if value not in (0, 1, 2, 3):
                raise ProtobufDecodeError("event name is not defined by the firmware schema")
        elif field_number == 3 and wire_type == 2 and isinstance(value, bytes):
            try:
                value.decode("utf-8")
            except UnicodeDecodeError as err:
                raise ProtobufDecodeError("event target is not valid UTF-8") from err
        else:
            raise ProtobufDecodeError("event contains an unsupported field")

    if 1 not in seen or 2 not in seen:
        raise ProtobufDecodeError("event is missing its timestamp or name")


def decode_event_payload(payload: bytes) -> int:
    """Validate an ``EventList`` upload and return only its event count.

    Targets can identify UI destinations or contractor actions. They are never
    returned, logged, persisted, or exposed as Home Assistant state.
    """

    event_count = 0
    for field_number, wire_type, value in iter_fields(payload):
        if field_number != 1 or wire_type != 2 or not isinstance(value, bytes):
            raise ProtobufDecodeError("event envelope contains an unsupported field")
        _validate_event(value)
        event_count += 1
    if event_count == 0:
        raise ProtobufDecodeError("event envelope contains no events")
    return event_count


def decode_record(data: bytes) -> MonitorRecord:
    """Decode one nested monitor record."""

    timestamp: datetime | None = None
    fixed32: dict[int, float] = {}
    varints: dict[int, int] = {}
    for field_number, wire_type, value in iter_fields(data):
        if field_number == 1 and wire_type == 2 and isinstance(value, bytes):
            timestamp = _decode_timestamp(value)
        elif wire_type == 5 and isinstance(value, int):
            decoded = struct.unpack("<f", value.to_bytes(4, "little"))[0]
            if math.isfinite(decoded):
                fixed32[field_number] = decoded
        elif wire_type == 0 and isinstance(value, int):
            varints[field_number] = value
    return MonitorRecord(timestamp=timestamp, fixed32=fixed32, varints=varints)


def decode_monitor_payload(payload: bytes, *, received_at: datetime) -> NuveState:
    """Decode a Nuve monitor envelope into the latest merged state."""

    records: list[MonitorRecord] = []
    for field_number, wire_type, value in iter_fields(payload):
        if field_number == 1 and wire_type == 2 and isinstance(value, bytes):
            records.append(decode_record(value))
    if not records:
        raise ProtobufDecodeError("monitor envelope contains no field-1 records")

    fixed32: dict[int, float] = {}
    varints: dict[int, int] = {}
    sample_time: datetime | None = None
    is_sync = False
    for record in records:
        if record.varints.get(13) == 1:
            fixed32.clear()
            varints.clear()
            is_sync = True
        fixed32.update(record.fixed32)
        varints.update(record.varints)
        if record.timestamp is not None:
            sample_time = record.timestamp

    def plausible(field_number: int, low: float, high: float) -> float | None:
        value = fixed32.get(field_number)
        return value if value is not None and low <= value <= high else None

    def bounded_int(field_number: int, low: int, high: int) -> int | None:
        value = varints.get(field_number)
        return value if value is not None and low <= value <= high else None

    def enum_int(field_number: int, choices: frozenset[int]) -> int | None:
        value = varints.get(field_number)
        return value if value in choices else None

    mode_value = bounded_int(15, 0, 6)
    system_type_value = bounded_int(14, 0, 5)

    return NuveState(
        available=True,
        last_seen=received_at,
        sample_time=sample_time,
        target_temperature=plausible(2, -50, 100),
        target_humidity=plausible(3, 0, 100),
        current_temperature=plausible(4, -50, 100),
        current_humidity=plausible(5, 0, 100),
        mcu_temperature=plausible(6, -50, 150),
        air_pressure=plausible(7, 300, 1200),
        air_quality_level=bounded_int(8, 0, 3),
        cooling_stage=bounded_int(9, 0, 2),
        heating_stage=bounded_int(10, 0, 3),
        fan_active=(bool(varints[11]) if varints.get(11) in (0, 1) else None),
        led_active=(bool(varints[12]) if varints.get(12) in (0, 1) else None),
        system_type=(NuveSystemType(system_type_value) if system_type_value is not None else None),
        mode=NuveMode(mode_value) if mode_value is not None else None,
        online=(bool(varints[16]) if varints.get(16) in (0, 1) else None),
        auto_temperature_low=plausible(17, -50, 100),
        auto_temperature_high=plausible(18, -50, 100),
        # The recovered descriptor declares only Sleep/Wake/Home/Away/Hold/None
        # as 0/1/2/3/8/9. Values 4..7 are not named wire states.
        schedule_type=enum_int(19, frozenset({0, 1, 2, 3, 8, 9})),
        monitor_is_sync=is_sync,
        raw_fixed32=fixed32,
        raw_varints=varints,
        records_received=len(records),
    )
