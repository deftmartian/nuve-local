"""Tests for the schema-independent Nuve protobuf decoder."""

from __future__ import annotations

import struct
from datetime import UTC, datetime

import pytest

from custom_components.nuve_local.protobuf import (
    ProtobufDecodeError,
    decode_event_payload,
    decode_monitor_payload,
)


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _field_varint(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _field_bytes(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _field_float(number: int, value: float) -> bytes:
    return _varint((number << 3) | 5) + struct.pack("<f", value)


def _record(timestamp: int, *fields: bytes) -> bytes:
    timestamp_message = _field_varint(1, timestamp)
    return _field_bytes(1, timestamp_message) + b"".join(fields)


def _event(*, timestamp: int = 1_786_237_105, name: int = 1, target: bytes = b"home") -> bytes:
    return b"".join(
        (
            _field_bytes(1, _field_varint(1, timestamp)),
            _field_varint(2, name),
            _field_bytes(3, target),
        )
    )


def test_decode_event_payload_validates_records_and_returns_only_count() -> None:
    payload = _field_bytes(1, _event()) + _field_bytes(
        1, _event(timestamp=1_786_237_106, name=3, target=b"")
    )

    assert decode_event_payload(payload) == 2


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        _field_bytes(1, _field_varint(2, 1)),
        _field_bytes(1, _field_bytes(1, _field_varint(1, 1))),
        _field_bytes(1, _event(name=4)),
        _field_bytes(1, _event(target=b"\xff")),
        _field_bytes(1, _event() + _field_varint(4, 1)),
        _field_bytes(1, _event() + _field_varint(2, 1)),
        _field_varint(1, 1),
    ],
)
def test_decode_event_payload_rejects_malformed_or_unknown_fields(payload: bytes) -> None:
    with pytest.raises(ProtobufDecodeError):
        decode_event_payload(payload)


def test_decode_monitor_payload_merges_incremental_records() -> None:
    first = _record(
        1_786_237_105,
        _field_float(2, 21.0),
        _field_float(3, 45.0),
        _field_float(4, 21.5),
        _field_float(5, 53.0),
        _field_float(6, 32.0),
        _field_float(7, 1010.0),
        _field_float(17, 20.0),
        _field_float(18, 23.0),
        _field_varint(9, 0),
        _field_varint(10, 1),
        _field_varint(11, 1),
        _field_varint(13, 1),
        _field_varint(14, 2),
        _field_varint(15, 2),
    )
    second = _record(1_786_237_106, _field_float(5, 54.0), _field_varint(16, 1))
    payload = _field_bytes(1, first) + _field_bytes(1, second)
    received_at = datetime(2026, 8, 9, 1, 0, tzinfo=UTC)

    state = decode_monitor_payload(payload, received_at=received_at)

    assert state.target_temperature == 21.0
    assert state.target_humidity == 45.0
    assert state.current_temperature == 21.5
    assert state.current_humidity == 54.0
    assert state.mcu_temperature == 32.0
    assert state.air_pressure == 1010.0
    assert state.auto_temperature_low == 20.0
    assert state.auto_temperature_high == 23.0
    assert state.heating_stage == 1
    assert state.fan_active is True
    assert state.monitor_is_sync is True
    assert state.raw_varints[14] == 2
    assert state.raw_varints[16] == 1
    assert state.sample_time == datetime.fromtimestamp(1_786_237_106, tz=UTC)
    assert state.last_seen == received_at
    assert state.records_received == 2


@pytest.mark.parametrize("payload", [b"", b"\x0a\x05\x08", b"\x0b"])
def test_decode_monitor_payload_rejects_malformed_payload(payload: bytes) -> None:
    with pytest.raises(ProtobufDecodeError):
        decode_monitor_payload(payload, received_at=datetime.now(UTC))


def test_out_of_range_promoted_value_remains_in_diagnostics() -> None:
    record = _record(1_786_237_105, _field_float(5, 150.0))
    state = decode_monitor_payload(
        _field_bytes(1, record), received_at=datetime(2026, 8, 9, tzinfo=UTC)
    )

    assert state.current_humidity is None
    assert state.raw_fixed32[5] == 150.0


def test_schedule_type_promotes_only_descriptor_enum_values() -> None:
    valid = _record(1_786_237_105, _field_varint(19, 8))
    undefined = _record(1_786_237_106, _field_varint(19, 4))

    valid_state = decode_monitor_payload(
        _field_bytes(1, valid), received_at=datetime(2026, 8, 9, tzinfo=UTC)
    )
    undefined_state = decode_monitor_payload(
        _field_bytes(1, undefined), received_at=datetime(2026, 8, 9, tzinfo=UTC)
    )

    assert valid_state.schedule_type == 8
    assert undefined_state.schedule_type is None
    assert undefined_state.raw_varints[19] == 4
