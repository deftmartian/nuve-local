"""Table-driven tests for every rule that rejects a stored baseline envelope.

Each case mutates one field of an otherwise valid envelope and then re-seals the
envelope-wide integrity hash, so the rule under test, not the hash check, is what
rejects it.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.nuve_local.protocol import NuveProtocolError
from custom_components.nuve_local.storage import (
    _build_storage_envelope,
    _canonical_hash,
    _durable_payload,
    validate_stored_baselines,
)
from tests.helpers import settings_upload

SERIAL = "00-000-000000"
REVISION = "2026-08-09 06:00:00"
ARMED_AT = datetime(2026, 8, 9, 6, 0, tzinfo=UTC)


def _seal(envelope: dict[str, Any]) -> dict[str, Any]:
    envelope["payload_sha256"] = _canonical_hash(_durable_payload(envelope))
    return envelope


def _bootstrap_envelope(**bootstrap_changes: Any) -> dict[str, Any]:
    """A pre-baseline envelope whose only state is an armed bootstrap journal."""

    bootstrap = {
        "revision": REVISION,
        "armed_at": ARMED_AT.isoformat(),
        "expires_at": (ARMED_AT + timedelta(minutes=10)).isoformat(),
        "settings_served": False,
        "auto_served": False,
        **bootstrap_changes,
    }
    data = {
        "settings_revision_floor": REVISION,
        "auto_revision_floor": REVISION,
        "bootstrap": bootstrap,
    }
    return _build_storage_envelope(data, serial=SERIAL, previous=None, saved_at=ARMED_AT)


def _baseline_envelope() -> dict[str, Any]:
    data = {
        "settings": settings_upload(SERIAL),
        "settings_revision": REVISION,
        "auto_mode": {"auto_temp_low": 19.0, "auto_temp_high": 23.0},
        "auto_mode_revision": "2026-08-09 06:00:01",
    }
    return _build_storage_envelope(data, serial=SERIAL, previous=None, saved_at=ARMED_AT)


def test_an_armed_bootstrap_journal_survives_a_restart() -> None:
    restored = validate_stored_baselines(_bootstrap_envelope(), serial=SERIAL)

    assert restored["bootstrap"] == {
        "revision": REVISION,
        "armed_at": ARMED_AT,
        "expires_at": ARMED_AT + timedelta(minutes=10),
        "settings_served": False,
        "auto_served": False,
    }
    assert restored["settings_revision_floor"] == REVISION


def test_a_partly_served_bootstrap_journal_is_kept() -> None:
    restored = validate_stored_baselines(_bootstrap_envelope(settings_served=True), serial=SERIAL)

    assert restored["bootstrap"]["settings_served"] is True
    assert restored["bootstrap"]["auto_served"] is False


def _set(key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(envelope: dict[str, Any]) -> None:
        envelope[key] = value

    return mutate


def _set_bootstrap(key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(envelope: dict[str, Any]) -> None:
        envelope["bootstrap"][key] = value

    return mutate


def _drop_bootstrap(key: str) -> Callable[[dict[str, Any]], None]:
    def mutate(envelope: dict[str, Any]) -> None:
        del envelope["bootstrap"][key]

    return mutate


BOOTSTRAP_REJECTIONS = {
    "journal is not an object": (_set("bootstrap", ["revision"]), "incompatible"),
    "unexpected key": (_set_bootstrap("extra", True), "unexpected shape"),
    "missing key": (_drop_bootstrap("auto_served"), "unexpected shape"),
    "revision is not text": (_set_bootstrap("revision", 20260809), "revision is invalid"),
    "revision is malformed": (_set_bootstrap("revision", "yesterday"), "last_update is invalid"),
    "armed_at is naive": (_set_bootstrap("armed_at", "2026-08-09T06:00:00"), "no timezone"),
    "expires_at is missing": (_set_bootstrap("expires_at", None), "expires_at is missing"),
    "expires before armed": (
        _set_bootstrap("expires_at", (ARMED_AT - timedelta(seconds=1)).isoformat()),
        "journal is invalid",
    ),
    "served flag is not boolean": (_set_bootstrap("settings_served", 1), "journal is invalid"),
    "auto served before settings": (_set_bootstrap("auto_served", True), "journal is invalid"),
    "settings floor missing": (_set("settings_revision_floor", None), "floor is missing"),
    "auto floor behind the journal": (
        _set("auto_revision_floor", "2026-08-09 05:00:00"),
        "floor is missing",
    ),
}


@pytest.mark.parametrize("case", BOOTSTRAP_REJECTIONS, ids=list(BOOTSTRAP_REJECTIONS))
def test_invalid_bootstrap_journals_are_rejected(case: str) -> None:
    mutate, message = BOOTSTRAP_REJECTIONS[case]
    envelope = _bootstrap_envelope()
    mutate(envelope)

    with pytest.raises(NuveProtocolError, match=message):
        validate_stored_baselines(_seal(envelope), serial=SERIAL)


def test_a_bootstrap_journal_cannot_coexist_with_a_settings_baseline() -> None:
    envelope = _baseline_envelope()
    envelope["bootstrap"] = copy.deepcopy(_bootstrap_envelope()["bootstrap"])
    envelope["settings_revision_floor"] = REVISION
    envelope["auto_revision_floor"] = "2026-08-09 06:00:01"

    with pytest.raises(NuveProtocolError, match="incompatible with settings"):
        validate_stored_baselines(_seal(envelope), serial=SERIAL)


ENVELOPE_REJECTIONS = {
    "legacy schema": (_set("storage_schema", 0), "legacy or unknown storage schema"),
    "commit id is not hex": (_set("commit_id", "not-a-commit"), "commit identity"),
    "completeness is not boolean": (_set("complete", "yes"), "completeness marker is invalid"),
    "completeness disagrees": (_set("complete", False), "does not match its contents"),
    "saved_at is naive": (_set("saved_at", "2026-08-09T06:00:00"), "saved_at has no timezone"),
    "settings revision floor regressed": (
        _set("settings_revision_floor", "2026-08-09 05:00:00"),
        "settings revision floor regressed",
    ),
    "auto revision floor regressed": (
        _set("auto_revision_floor", "2026-08-09 05:00:00"),
        "Auto revision floor regressed",
    ),
    "runtime metadata is not text": (_set("live_data_command_time", 7), "is invalid"),
    "settings hash mismatch": (_set("settings_sha256", "0" * 64), "settings integrity hash"),
    "settings without a revision": (_set("settings_revision", None), "revision is missing"),
    "auto without a revision": (_set("auto_mode_revision", None), "Auto revision is missing"),
    "auto hash mismatch": (_set("auto_mode_sha256", "0" * 64), "Auto integrity hash"),
    "initial capture missing": (_set("initial_capture", None), "initial settings capture"),
    "uncertain command not an object": (_set("uncertain_command", "x"), "must be an object"),
    "uncertain command kind unknown": (
        _set("uncertain_command", {"kind": "schedule", "desired": {}}),
        "kind or desired state",
    ),
    "uncertain command revision invalid": (
        _set("uncertain_command", {"kind": "settings", "desired": {"temp": 21}, "revision": 1}),
        "revision is invalid",
    ),
}


@pytest.mark.parametrize("case", ENVELOPE_REJECTIONS, ids=list(ENVELOPE_REJECTIONS))
def test_invalid_baseline_envelopes_are_rejected(case: str) -> None:
    mutate, message = ENVELOPE_REJECTIONS[case]
    envelope = _baseline_envelope()
    mutate(envelope)

    with pytest.raises(NuveProtocolError, match=message):
        validate_stored_baselines(_seal(envelope), serial=SERIAL)


def test_the_unmutated_baseline_envelope_is_valid() -> None:
    """Guard for the table above: every rejection must come from its mutation."""

    restored = validate_stored_baselines(_seal(_baseline_envelope()), serial=SERIAL)

    assert restored["settings_revision"] == REVISION
    assert restored["auto_mode"] == {"auto_temp_low": 19.0, "auto_temp_high": 23.0}
