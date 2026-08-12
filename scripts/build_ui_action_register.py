#!/usr/bin/env python3
"""Build a public QML handler register from a private QV4 inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

_HANDLER = re.compile(r"^on[A-Z][A-Za-z0-9_]*$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OPERATION_NAME_FIELDS = (
    "named_reads",
    "named_writes",
    "named_calls",
    "named_constructs",
    "named_deletes",
)
_OPERATION_COUNT_FIELDS = (
    "named_call_count",
    "dynamic_call_count",
    "named_construct_count",
    "unresolved_construct_count",
    "element_read_count",
    "element_write_count",
    "delete_count",
    "control_flow_count",
    "throw_count",
    "object_creation_count",
)

_USER_INPUT_HANDLERS = {
    "onAccepted",
    "onActivated",
    "onButtonClicked",
    "onCanceled",
    "onCheckedChanged",
    "onClicked",
    "onDownloadClicked",
    "onEditingFinished",
    "onEnterPressed",
    "onLongPressed",
    "onMoved",
    "onPressAndHold",
    "onPressed",
    "onRejected",
    "onReleased",
    "onReturnPressed",
    "onSingleTapped",
    "onTapped",
    "onToggled",
}
_LIFECYCLE_HANDLERS = {
    "onAboutToHide",
    "onClosed",
    "onCompleted",
    "onDestruction",
    "onHid",
    "onLoaded",
    "onOpened",
    "onReady",
}
_DOMAIN_PATTERNS = (
    ("schedule", ("schedule",)),
    (
        "lock-access",
        (
            "unlockpage",
            "lockpage",
            "pinkeyboard",
            "passwordtextfield",
            "enteredpin",
            "sendpin",
            "clearpin",
            "forgetpin",
            "lockingdevice",
            "lockstate",
        ),
    ),
    ("factory-reset", ("resetfactory", "factoryreset", "removeconfigurationsavedfiles")),
    (
        "software-update",
        (
            "updatemanager",
            "systemupdate",
            "backdoorupdate",
            "partialupdate",
            "downloadstarted",
            "newupdateavailable",
            "nrfupdate",
            "updatenotificationpopup",
            "updateinterruptionpopup",
            "installconfirmationpopup",
            "softwarechangelog",
            "downloadclicked",
            "checkedswupdate",
        ),
    ),
    ("performance-test", ("perftest",)),
    (
        "equipment-test",
        ("testequipment", "relaytest", "startrelay", "stoprelay", "istestrunning"),
    ),
    ("service-control", ("stopdevice",)),
    (
        "installer-service",
        (
            "servicetitan",
            "warrantyreplacement",
            "contractor",
            "initialsetup",
            "installlog",
            "installationtype",
            "residencetype",
            "devicelocation",
            "zipcode",
            "whereinstalled",
        ),
    ),
    ("persistence", ("savesettings", "savetofile", "qsrepository", "fileio")),
    (
        "remote-api",
        (
            "toserver",
            "fromserver",
            "protodatamanager",
            "deviceapi",
            "pushsuccess",
            "pushfailed",
            "settingsfetched",
            "schedulefetched",
            "fetchsettings",
            "senddata",
            "fetchuserdata",
            "manageendpoint",
            "getendpoint",
            "mobileapppage",
            "sync",
        ),
    ),
    (
        "network-wifi",
        ("wifi", "networkinterface", "hasinternet", "ssid", "networklog"),
    ),
    (
        "sensor-radio",
        (
            "sensorcontroller",
            "sensorhealth",
            "addsensor",
            "sensorpair",
            "sensorspage",
            "sensorinfopage",
            "nrf",
            "co2",
        ),
    ),
    (
        "hvac-setting",
        (
            "systemmode",
            "requestedtemp",
            "settemperature",
            "sethumidity",
            "fanwork",
            "fanmode",
            "dualfuel",
            "systemtype",
            "systemrun",
            "systemminimum",
            "systemtemperature",
            "systemdissipation",
            "systemovercool",
            "systemaccessories",
            "systemage",
            "wiringpage",
            "ashrae",
            "vacationmode",
            "setvacation",
            "dfh",
            "auxiliarystatus",
            "currentfanstate",
            "automodepush",
            "limitedmode",
            "settingspage",
            "systemsetuppage",
            "applytomodel",
            "saveclicked",
            "fanbutton",
            "selectfanduration",
            "temperaturestepper",
            "manualbuttons",
        ),
    ),
    ("weather", ("weatherpage", "fetchcurrentweather", "fetchforecastweather")),
    (
        "system-clock",
        (
            "datetimepage",
            "selecttimezone",
            "timezone",
            "checktoupdatedevicedatetime",
        ),
    ),
    ("storage-maintenance", ("storagemanager", "logpartitioncleared")),
    ("display-power", ("backlight", "brightness", "screensaver", "nightmode")),
    ("navigation", ("stackhandler", "mainstack", "pushpage", "goback", "showhome")),
    ("message-popup", ("popup", "toast", "message", "alert")),
)

_FALLBACK_DOMAIN_BY_CATEGORY = {
    "application-root": "application-lifecycle",
    "core-controller": "application-state",
    "application-view": "application-ui-state",
    "application-popup": "message-popup",
    "application-component": "application-ui-state",
    "ui-infrastructure": "ui-local-state",
    "ui-toolkit": "ui-local-state",
    "persistence-framework": "persistence",
    "diagnostic-page": "diagnostic-test",
    "other": "other-qml-state",
}

_REVIEWED_CONSEQUENCES = {
    "2117a5456445fe57a851ecf09aa452a8d3a2a59d166d4c6f5475bb69d5151c8e": {
        "ui-aab701d46b404c6d": "diagnostic-local-indexed-state",
        "ui-3484face58e03f3e": "diagnostic-local-indexed-state",
        "ui-eea19fd0068068a6": "diagnostic-local-indexed-state",
    }
}


class RegisterError(ValueError):
    """The private inventory is incomplete or internally inconsistent."""


def _unit_category(symbol: str) -> str:
    rules = (
        ("_Stherm_Main_qml", "application-root"),
        ("_Stherm_qml_Core_", "core-controller"),
        ("_Stherm_qml_View_Test_", "diagnostic-page"),
        ("_Stherm_qml_View_", "application-view"),
        ("_Stherm_qml_UiCore_PopUps_", "application-popup"),
        ("_Stherm_qml_UiCore_Components_", "application-component"),
        ("_Stherm_qml_UiCore_", "ui-infrastructure"),
        ("_QtQuickStream_", "persistence-framework"),
        ("_Ronia_", "ui-toolkit"),
    )
    return next((category for marker, category in rules if marker in symbol), "other")


def _trigger_class(handler: str, object_type: str, source: str) -> str:
    if object_type == "Connections" or (source == "declared-handler" and handler.startswith("on")):
        return "signal-callback"
    if object_type == "Timer" or handler in {"onTriggered", "onStopped", "onRunningChanged"}:
        return "timer"
    if handler in _USER_INPUT_HANDLERS or handler.endswith("Selected"):
        return "user-input"
    if handler in _LIFECYCLE_HANDLERS:
        return "lifecycle"
    if handler.endswith(("Changed", "Updated")):
        return "state-change"
    return "custom-signal"


def _effect_domains(
    symbol: str, handler: str, identifiers: list[str], *, effect_free_stub: bool
) -> list[str]:
    if effect_free_stub:
        return ["none"]
    terms = " ".join(sorted({symbol, handler, *identifiers})).lower()
    domains = {
        domain
        for domain, patterns in _DOMAIN_PATTERNS
        if any(pattern in terms for pattern in patterns)
    }
    category = _unit_category(symbol)
    if category == "diagnostic-page":
        domains.add("diagnostic-test")
    if category == "persistence-framework":
        domains.add("persistence")
    if not domains:
        domains.add(_FALLBACK_DOMAIN_BY_CATEGORY[category])
    return sorted(domains)


def _integration_disposition(domains: list[str]) -> list[str]:
    unsupported = {
        "equipment-test": "unsupported-equipment-test",
        "factory-reset": "unsupported-reset",
        "installer-service": "unsupported-installer",
        "lock-access": "unsupported-lock",
        "performance-test": "unsupported-performance-test",
        "schedule": "unsupported-schedule",
        "software-update": "unsupported-update",
        "diagnostic-test": "unsupported-diagnostic",
        "storage-maintenance": "unsupported-storage-maintenance",
        "system-clock": "unsupported-system-clock",
        "service-control": "unsupported-service-control",
    }
    dispositions = [unsupported[domain] for domain in domains if domain in unsupported]
    return dispositions or ["firmware-ui-evidence-only"]


def _semantic_disposition(identifiers: list[str], *, effect_free_stub: bool) -> str:
    if identifiers:
        return "identifier-level-map"
    return "effect-free-stub" if effect_free_stub else "unresolved-no-identifier"


def _closure_function_indices(
    function: dict[str, Any], functions: list[dict[str, Any]]
) -> list[int]:
    pending = [function["index"]]
    visited: set[int] = set()
    while pending:
        function_index = pending.pop()
        if function_index in visited:
            continue
        if not isinstance(function_index, int) or not 0 <= function_index < len(functions):
            raise RegisterError("closure function index is outside its unit")
        visited.add(function_index)
        current = functions[function_index]
        closure_indices = current.get("closure_indices", [])
        if not isinstance(closure_indices, list) or not all(
            isinstance(value, int) for value in closure_indices
        ):
            raise RegisterError("closure indices are malformed")
        pending.extend(closure_indices)
    return sorted(visited)


def _identifier_references(
    function_indices: list[int], functions: list[dict[str, Any]]
) -> list[str]:
    """Collect identifiers from one exact transitive function set."""

    return sorted(
        {
            value
            for function_index in function_indices
            for value in functions[function_index].get("referenced_names", [])
            if isinstance(value, str) and _IDENTIFIER.fullmatch(value)
        }
    )


def _operation_map(function_indices: list[int], functions: list[dict[str, Any]]) -> dict[str, Any]:
    names = {field: set() for field in _OPERATION_NAME_FIELDS}
    counts = Counter()
    for function_index in function_indices:
        summary = functions[function_index].get("operation_summary")
        if not isinstance(summary, dict):
            raise RegisterError("QV4 inventory has no operation summary")
        for field in _OPERATION_NAME_FIELDS:
            values = summary.get(field)
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise RegisterError("QV4 operation names are malformed")
            names[field].update(value for value in values if _IDENTIFIER.fullmatch(value))
        for field in _OPERATION_COUNT_FIELDS:
            value = summary.get(field)
            if not isinstance(value, int) or value < 0:
                raise RegisterError("QV4 operation count is malformed")
            counts[field] += value
    return {
        **{field: sorted(values) for field, values in names.items()},
        **{field: counts[field] for field in _OPERATION_COUNT_FIELDS},
    }


def _consequence_disposition(operation_map: dict[str, Any], *, effect_free_stub: bool) -> str:
    if effect_free_stub:
        return "effect-free"
    if operation_map["dynamic_call_count"] or operation_map["unresolved_construct_count"]:
        return "dynamic-effect-target"
    if operation_map["element_write_count"]:
        return "indexed-state-write"
    if (
        operation_map["named_calls"]
        or operation_map["named_constructs"]
        or operation_map["named_writes"]
        or operation_map["named_deletes"]
        or operation_map["delete_count"]
    ):
        return "named-effect-boundary"
    return "local-computation-or-read"


def _action_id(key: str) -> str:
    return "ui-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _base_action(
    unit: dict[str, Any],
    qml_object: dict[str, Any] | None,
    function: dict[str, Any],
    functions: list[dict[str, Any]],
    *,
    handler: str,
    source: str,
    key: str,
) -> dict[str, Any]:
    symbol = unit["symbol"]
    object_type = qml_object["inherited_type"] if qml_object is not None else ""
    function_indices = _closure_function_indices(function, functions)
    identifiers = _identifier_references(function_indices, functions)
    operation_map = _operation_map(function_indices, functions)
    effect_free_stub = bool(function.get("is_effect_free_stub"))
    domains = _effect_domains(symbol, handler, identifiers, effect_free_stub=effect_free_stub)
    return {
        "id": _action_id(key),
        "unit": symbol,
        "unit_category": _unit_category(symbol),
        "source": source,
        "object_index": qml_object["index"] if qml_object is not None else None,
        "object_type": object_type,
        "object_id": qml_object["id_name"] if qml_object is not None else "",
        "handler": handler,
        "function_index": function["index"],
        "source_line": function["source_line"],
        "source_column": function["source_column"],
        "trigger_class": _trigger_class(handler, object_type, source),
        "referenced_identifiers": identifiers,
        "transitive_closure_count": len(function_indices) - 1,
        "operation_map": operation_map,
        "consequence_disposition": _consequence_disposition(
            operation_map, effect_free_stub=effect_free_stub
        ),
        "is_effect_free_stub": effect_free_stub,
        "effect_domains": domains,
        "semantic_disposition": _semantic_disposition(
            identifiers, effect_free_stub=effect_free_stub
        ),
        "integration_disposition": _integration_disposition(domains),
    }


def _validate_counts(report: dict[str, Any]) -> None:
    units = report.get("units")
    if report.get("schema_version", 0) < 4 or not isinstance(units, list):
        raise RegisterError("QV4 inventory schema version 4 or newer is required")
    if report.get("unit_count") != len(units):
        raise RegisterError("unit count does not match the inventory")
    symbols = [unit.get("symbol") for unit in units]
    if len(set(symbols)) != len(symbols):
        raise RegisterError("unit symbols are not unique")
    expected = {
        "function_count": sum(len(unit.get("functions", [])) for unit in units),
        "qml_object_count": sum(len(unit.get("qml_objects", [])) for unit in units),
        "qml_binding_count": sum(len(unit.get("qml_bindings", [])) for unit in units),
    }
    for name, value in expected.items():
        if report.get(name) != value:
            raise RegisterError(f"{name} does not match the inventory")


def _apply_reviewed_consequences(actions: list[dict[str, Any]], binary_sha256: str) -> None:
    reviewed = _REVIEWED_CONSEQUENCES.get(binary_sha256, {})
    matched: set[str] = set()
    for action in actions:
        disposition = reviewed.get(action["id"])
        if disposition is None:
            continue
        if action["consequence_disposition"] != "indexed-state-write" or not action[
            "unit"
        ].endswith("_View_Test_TouchTestPage_qml"):
            raise RegisterError("reviewed consequence no longer matches its exact action")
        action["consequence_disposition"] = disposition
        action["review_evidence"] = "exact-instruction-review"
        matched.add(action["id"])
    if matched != set(reviewed):
        raise RegisterError("reviewed consequence action is absent from the exact inventory")


def build_register(report: dict[str, Any]) -> dict[str, Any]:
    """Build a register with one record for every bound or declared QML handler."""

    _validate_counts(report)
    actions = []
    for unit in report["units"]:
        functions = unit["functions"]
        objects = {item["index"]: item for item in unit["qml_objects"]}
        function_owners: dict[int, dict[str, Any]] = {}
        for qml_object in unit["qml_objects"]:
            for function_index in qml_object.get("function_indices", []):
                if not 0 <= function_index < len(functions):
                    raise RegisterError("QML object function index is outside its unit")
                if function_index in function_owners:
                    raise RegisterError("QV4 function has more than one QML object owner")
                function_owners[function_index] = qml_object

        bound_indices = set()
        for binding in unit["qml_bindings"]:
            handler = binding["property"]
            if binding["type"] != "script" or not _HANDLER.fullmatch(handler):
                continue
            function_index = binding.get("function_index")
            if not isinstance(function_index, int) or not 0 <= function_index < len(functions):
                raise RegisterError("script handler binding has an invalid function index")
            qml_object = objects.get(binding["object_index"])
            if qml_object is None:
                raise RegisterError("script handler binding has an invalid object index")
            bound_indices.add(function_index)
            key = f"{unit['symbol']}|binding|{binding['object_index']}|{binding['index']}"
            actions.append(
                _base_action(
                    unit,
                    qml_object,
                    functions[function_index],
                    functions,
                    handler=handler,
                    source="script-binding",
                    key=key,
                )
            )

        for function in functions:
            handler = function["name"]
            if not _HANDLER.fullmatch(handler) or function["index"] in bound_indices:
                continue
            qml_object = function_owners.get(function["index"])
            key = f"{unit['symbol']}|function|{function['index']}"
            actions.append(
                _base_action(
                    unit,
                    qml_object,
                    function,
                    functions,
                    handler=handler,
                    source="declared-handler",
                    key=key,
                )
            )

    actions.sort(
        key=lambda action: (
            action["unit"],
            action["source_line"],
            action["source_column"],
            action["function_index"],
            action["handler"],
        )
    )
    ids = [action["id"] for action in actions]
    if len(ids) != len(set(ids)):
        raise RegisterError("generated action identifiers are not unique")
    _apply_reviewed_consequences(actions, report["binary_sha256"])

    action_counts = Counter(action["unit"] for action in actions)
    source_category_counts = Counter(_unit_category(unit["symbol"]) for unit in report["units"])
    action_category_counts = Counter(
        _unit_category(unit["symbol"]) for unit in report["units"] if action_counts[unit["symbol"]]
    )
    unit_summaries = []
    for unit in report["units"]:
        if not action_counts[unit["symbol"]]:
            continue
        unit_actions = [action for action in actions if action["unit"] == unit["symbol"]]
        unit_summaries.append(
            {
                "unit": unit["symbol"],
                "unit_category": _unit_category(unit["symbol"]),
                "action_count": len(unit_actions),
                "trigger_counts": dict(
                    sorted(Counter(action["trigger_class"] for action in unit_actions).items())
                ),
                "effect_domains": sorted(
                    {domain for action in unit_actions for domain in action["effect_domains"]}
                ),
                "unresolved_action_count": sum(
                    action["semantic_disposition"] == "unresolved-no-identifier"
                    for action in unit_actions
                ),
            }
        )

    return {
        "schema_version": 3,
        "source_binary_sha256": report["binary_sha256"],
        "source_unit_corpus_sha256": report["unit_corpus_sha256"],
        "source_inventory_schema_version": report["schema_version"],
        "source_unit_count": report["unit_count"],
        "source_function_count": report["function_count"],
        "source_qml_object_count": report["qml_object_count"],
        "source_qml_binding_count": report["qml_binding_count"],
        "action_count": len(actions),
        "action_corpus_sha256": hashlib.sha256(
            json.dumps(actions, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "action_unit_count": len(unit_summaries),
        "non_action_unit_count": report["unit_count"] - len(unit_summaries),
        "source_unit_category_counts": dict(sorted(source_category_counts.items())),
        "action_unit_category_counts": dict(sorted(action_category_counts.items())),
        "source_counts": dict(sorted(Counter(action["source"] for action in actions).items())),
        "trigger_counts": dict(
            sorted(Counter(action["trigger_class"] for action in actions).items())
        ),
        "semantic_disposition_counts": dict(
            sorted(Counter(action["semantic_disposition"] for action in actions).items())
        ),
        "consequence_disposition_counts": dict(
            sorted(Counter(action["consequence_disposition"] for action in actions).items())
        ),
        "integration_disposition_counts": dict(
            sorted(
                Counter(
                    disposition
                    for action in actions
                    for disposition in action["integration_disposition"]
                ).items()
            )
        ),
        "effect_domain_counts": dict(
            sorted(
                Counter(domain for action in actions for domain in action["effect_domains"]).items()
            )
        ),
        "units": unit_summaries,
        "actions": actions,
    }


def _count_table(title: str, values: dict[str, int]) -> list[str]:
    lines = [f"### {title}", "", "| Class | Count |", "|---|---:|"]
    lines.extend(f"| `{name}` | {count} |" for name, count in values.items())
    lines.append("")
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    """Render the public register summary and every action-bearing QV4 unit."""

    unresolved = [
        action
        for action in report["actions"]
        if action["semantic_disposition"] == "unresolved-no-identifier"
    ]
    stubs = [
        action
        for action in report["actions"]
        if action["semantic_disposition"] == "effect-free-stub"
    ]
    reviewed = [action for action in report["actions"] if action.get("review_evidence")]
    dynamic_effects = [
        action
        for action in report["actions"]
        if action["consequence_disposition"] in {"dynamic-effect-target", "indexed-state-write"}
    ]
    unit_label = "action-bearing unit" if report["action_unit_count"] == 1 else "units"
    lines = [
        "# UI action register",
        "",
        "## Scope and result",
        "",
        f"This register maps every recognized UI event handler in the 1.5.8 application "
        f"ELF `{report['source_binary_sha256']}`.",
        "",
        f"It found **{report['action_count']} handlers in "
        f"{report['action_unit_count']} {unit_label}**: "
        f"{report['source_counts']['script-binding']} bound `onX` expressions and "
        f"{report['source_counts']['declared-handler']} declared callbacks. Each entry "
        "records its trigger, owner, named operations, effect area, consequence, and "
        "Nuve Local status.",
        "",
        f"Action-corpus SHA-256: `{report['action_corpus_sha256']}`. QV4 unit-corpus "
        f"SHA-256: `{report['source_unit_corpus_sha256']}`.",
        "",
        "The register maps encoded UI operations, not runtime success or electrical effects. "
        f"{len(unresolved)} handlers expose neither an identifier reference nor a proven "
        "effect-free body. "
        f"{len(stubs)} no-identifier handlers contain only context/return instructions and "
        "are effect-free. Subsystem pages cover high-risk behavior.",
        "",
        "## Construction rule",
        "",
        "An action is a QML script-binding property or object-owned compiled function "
        "matching `^on[A-Z][A-Za-z0-9_]*$`. The register follows `LoadClosure` targets "
        "within each unit and derives stable IDs from unit and function coordinates.",
        "",
        "Only operation names and counts are retained. Source text, compiled bodies, "
        "translations, credentials, device data, and endpoint values are excluded. Domain "
        "tags help search the register; they are not call-graph proof.",
        "",
        "The private corpus holds the full action-level JSON. This summary includes counts, "
        "action-bearing units, effect-free handlers, and reviewed indexed writes.",
        "",
        "## Coverage",
        "",
        "| Measure | Count |",
        "|---|---:|",
        f"| QV4 units | {report['source_unit_count']} |",
        f"| Action-bearing units | {report['action_unit_count']} |",
        f"| Units without a recognized handler | {report['non_action_unit_count']} |",
        f"| Registered actions | {report['action_count']} |",
        f"| Identifier-level maps | "
        f"{report['semantic_disposition_counts'].get('identifier-level-map', 0)} |",
        f"| Effect-free stubs | "
        f"{report['semantic_disposition_counts'].get('effect-free-stub', 0)} |",
        f"| No-identifier unknowns | "
        f"{report['semantic_disposition_counts'].get('unresolved-no-identifier', 0)} |",
        f"| Operation-level maps | {report['action_count']} |",
        f"| Unresolved dynamic/indexed effect targets | {len(dynamic_effects)} |",
        "",
    ]
    lines.extend(_count_table("Trigger classes", report["trigger_counts"]))
    lines.extend(_count_table("Consequence dispositions", report["consequence_disposition_counts"]))
    lines.extend(_count_table("Effect-domain tags", report["effect_domain_counts"]))
    lines.extend(
        _count_table(
            "Nuve Local integration dispositions",
            report["integration_disposition_counts"],
        )
    )
    lines.extend(
        [
            "Disposition counts can overlap because one handler can enter more than one "
            "offline-only family. Schedule, lock, reset, updater, installer, diagnostic, "
            "performance-test, equipment-test, service-control, storage-maintenance, and "
            "system-clock actions remain unsupported in Nuve Local regardless of how well "
            "their firmware UI paths are mapped.",
            "",
            "Detailed protocol and risk analysis is in "
            "[scheduling-protocol.md](scheduling-protocol.md), "
            "[lock-protocol.md](lock-protocol.md), "
            "[application-update.md](application-update.md), "
            "[installer-private-api.md](installer-private-api.md), and "
            "[performance-test.md](performance-test.md).",
            "",
            "## Action-bearing unit register",
            "",
            "The unit value is the exact ELF symbol suffix used as canonical identity; firmware "
            "spelling errors are preserved. `U` is the number of handlers that expose neither "
            "an identifier map nor a proven effect-free body; it is zero in this corpus.",
            "",
            "| Exact unit | Category | Actions | U | Trigger counts | Effect domains |",
            "|---|---|---:|---:|---|---|",
        ]
    )
    for unit in report["units"]:
        triggers = ", ".join(f"{name}={count}" for name, count in unit["trigger_counts"].items())
        domains = ", ".join(unit["effect_domains"])
        lines.append(
            f"| `{unit['unit']}` | `{unit['unit_category']}` | {unit['action_count']} | "
            f"{unit['unresolved_action_count']} | {triggers} | {domains} |"
        )
    lines.extend(
        [
            "",
            "## Effect-free handler stubs",
            "",
            "These handlers and every exact nested closure contain only call-context, "
            "register/undefined load, return, and context-cleanup instructions. They perform "
            "no property read/write, call, construction, arithmetic, branch, or signal action.",
            "",
            "| Stable ID | Exact unit | Owner | Handler | Line |",
            "|---|---|---|---|---:|",
        ]
    )
    for action in stubs:
        owner = action["object_type"] or "unowned"
        lines.append(
            f"| `{action['id']}` | `{action['unit']}` | `{owner}` | "
            f"`{action['handler']}` | {action['source_line']} |"
        )
    lines.extend(
        [
            "",
            "## Exact reviewed indexed writes",
            "",
            "These exact-hash diagnostic handlers use indexed writes only on their "
            "touch-test point/string arrays. Targeted instruction review found no native, "
            "persistence, network, schedule, or HVAC call target.",
            "",
            "| Stable ID | Exact unit | Handler | Disposition |",
            "|---|---|---|---|",
        ]
    )
    lines.extend(
        f"| `{action['id']}` | `{action['unit']}` | `{action['handler']}` | "
        f"`{action['consequence_disposition']}` |"
        for action in reviewed
    )
    lines.extend(
        [
            "",
            "## No-identifier unknowns",
            "",
            "These handlers are structurally located but expose neither a resolvable identifier "
            "nor a proven effect-free body. Closing them requires instruction/branch review and, "
            "where static evidence stops, isolated emulation or explicitly authorized live "
            "observation.",
            "",
            "| Stable ID | Exact unit | Owner | Handler | Line |",
            "|---|---|---|---|---:|",
        ]
    )
    for action in unresolved:
        owner = action["object_type"] or "unowned"
        lines.append(
            f"| `{action['id']}` | `{action['unit']}` | `{owner}` | "
            f"`{action['handler']}` | {action['source_line']} |"
        )
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "Generate the private schema-v4 QV4 inventory and then this register:",
            "",
            "```bash",
            ".venv/bin/python .agents/skills/analyze-nuve-firmware/scripts/inventory_qt6_qv4.py \\",
            "  /path/to/appStherm-1.5.8 --instruction-header "
            "/path/to/qt-6.4.0-qv4instr_moth_p.h \\",
            "  > /private/path/QV4-1.5.8-INVENTORY.private.json",
            ".venv/bin/python scripts/build_ui_action_register.py \\",
            "  /private/path/QV4-1.5.8-INVENTORY.private.json \\",
            "  > /private/path/UI-ACTION-REGISTER-1.5.8.private.json",
            "```",
            "",
            "Regenerate this Markdown with `--format markdown`. Hashes and counts must match "
            "before comparison. No command in this workflow contacts a thermostat or network "
            "service.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path, help="private QV4 inventory JSON")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()
    try:
        report = build_register(json.loads(args.inventory.read_text()))
    except (OSError, json.JSONDecodeError, RegisterError) as error:
        parser.error(str(error))
    if args.format == "markdown":
        print(render_markdown(report), end="")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
