#!/usr/bin/env python3
"""Independent exact-1.5.8 QtQuickStream persistence model.

This research helper models only the recovered load gates, fallback order, property
filter, and direct truncating-write consequences. It does not read private device
configuration.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

QS_URL_PREFIX = "qqs:/"
SYNTHETIC_ROOT_ID = "{00000000-0000-4000-8000-000000000001}"


class ConfigSource(StrEnum):
    PRIMARY = "primary"
    LEGACY_RELATIVE = "legacy_relative"
    RECOVERY = "recovery"
    DEFAULT_DEVICE = "default_device"


@dataclass(frozen=True)
class LoadSelection:
    source: ConfigSource
    repository: dict[str, Any] | None


@dataclass(frozen=True)
class PersistedScheduleState:
    schedules: tuple[dict[str, Any], ...]
    schedules_v2: tuple[dict[str, Any], ...]
    hold_type: Any
    hold_period: dict[str, Any]
    hold_start_time: dict[str, Any]
    dropped_references: tuple[str, ...]


def decode_repository(blob: bytes) -> dict[str, Any] | None:
    """Apply loadFromFile's empty/JSON/root gates and fail closed on exceptions."""

    if not blob:
        return None
    try:
        parsed = json.loads(blob)
    except UnicodeDecodeError, json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or not parsed.get("root"):
        return None
    return parsed


def choose_startup_repository(
    *, primary: bytes, legacy_relative: bytes, recovery: bytes
) -> LoadSelection:
    """Choose the first valid candidate in the exact UiSession startup order."""

    for source, blob in (
        (ConfigSource.PRIMARY, primary),
        (ConfigSource.LEGACY_RELATIVE, legacy_relative),
        (ConfigSource.RECOVERY, recovery),
    ):
        if repository := decode_repository(blob):
            return LoadSelection(source=source, repository=repository)
    return LoadSelection(source=ConfigSource.DEFAULT_DEVICE, repository=None)


def storage_property_allowed(name: str) -> bool:
    """Model QSSerializer's exact underscore and objectName blacklist."""

    return not (name.startswith("_") or name.endswith("_") or name == "objectName")


def _storage_properties(properties: Mapping[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in properties.items() if storage_property_allowed(name)}


def build_schedule_hold_repository(
    *,
    schedules: Sequence[Mapping[str, Any]],
    schedules_v2: Sequence[Mapping[str, Any]],
    hold_type: int,
    hold_period: Mapping[str, Any],
    hold_start_time: Mapping[str, Any],
) -> bytes:
    """Build a deterministic synthetic graph with the exact recovered QS shape."""

    repository: dict[str, Any] = {}
    v1_urls = _append_schedule_rows(repository, schedules, generation="v1")
    v2_urls = _append_schedule_rows(repository, schedules_v2, generation="v2")
    root_id = SYNTHETIC_ROOT_ID
    repository[root_id] = {
        "qsType": "Device",
        "schedules": v1_urls,
        "schedulesV2": v2_urls,
        "holdType": hold_type,
        "holdPeriod": dict(hold_period),
        "holdStartTime": dict(hold_start_time),
    }
    repository["root"] = f"{QS_URL_PREFIX}{root_id}"
    return json.dumps(repository, indent=4, sort_keys=True).encode()


def _append_schedule_rows(
    repository: dict[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    generation: str,
) -> list[str]:
    urls = []
    for index, row in enumerate(rows, start=1):
        generation_marker = "1" if generation == "v1" else "2"
        object_id = f"{{00000000-0000-4000-8000-{generation_marker}{index:011}}}"
        repository[object_id] = {
            "qsType": "ScheduleCPP",
            **_storage_properties(row),
        }
        urls.append(f"{QS_URL_PREFIX}{object_id}")
    return urls


def _resolve_object(
    value: Any,
    repository: Mapping[str, Any],
    dropped: list[str],
) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.startswith(QS_URL_PREFIX):
        return None
    object_id = value[len(QS_URL_PREFIX) :]
    resolved = repository.get(object_id)
    if not isinstance(resolved, Mapping):
        dropped.append(value)
        return None
    return dict(resolved)


def _resolve_schedule_array(
    value: Any,
    repository: Mapping[str, Any],
    dropped: list[str],
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        resolved
        for item in value
        if (resolved := _resolve_object(item, repository, dropped)) is not None
    )


def decode_schedule_hold_state(blob: bytes) -> PersistedScheduleState | None:
    """Resolve the recovered root arrays/maps, including silent dangling-ref drops."""

    repository = decode_repository(blob)
    if repository is None:
        return None
    dropped: list[str] = []
    root = _resolve_object(repository["root"], repository, dropped)
    if root is None:
        return None
    hold_period = root.get("holdPeriod")
    hold_start_time = root.get("holdStartTime")
    return PersistedScheduleState(
        schedules=_resolve_schedule_array(root.get("schedules"), repository, dropped),
        schedules_v2=_resolve_schedule_array(root.get("schedulesV2"), repository, dropped),
        hold_type=root.get("holdType"),
        hold_period=dict(hold_period) if isinstance(hold_period, Mapping) else {},
        hold_start_time=(dict(hold_start_time) if isinstance(hold_start_time, Mapping) else {}),
        dropped_references=tuple(dropped),
    )


def interrupted_direct_write(replacement: bytes, *, bytes_written: int) -> bytes:
    """Model WriteOnly|Truncate followed by an interrupted partial write."""

    if not 0 <= bytes_written <= len(replacement):
        raise ValueError("bytes_written is outside the replacement")
    return replacement[:bytes_written]


def firmware_reports_write_success(qiodevice_result: int) -> bool:
    """Model FileIO::write's exact nonzero-return test, including -1 and partial writes."""

    return qiodevice_result != 0
