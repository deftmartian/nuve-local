#!/usr/bin/env python3
"""Inventory first-party Nuve firmware symbols by subsystem.

The report is intentionally an index, not proof of behavior. Use its function
names and addresses to select bounded decompilation targets from the same binary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

SUBSYSTEMS: dict[str, tuple[str, ...]] = {
    "startup_and_state": (
        "NUVE::DeviceConfig",
        "NUVE::System",
        "NUVE::StorageMonitor",
        "DeviceControllerCPP",
        "DeviceInfo",
        "UserData",
        "FileIO",
        "PlatformTools",
        "QSCoreCpp",
        "QSObjectCpp",
        "QSRepositoryCpp",
        "StorageController",
        "DateTimeManager",
        "ScreenSaverManager",
    ),
    "control_and_hvac": (
        "Scheme",
        "SchemeDataProvider",
        "BaseScheme",
        "HumidityScheme",
        "ScheduleCPP",
        "Relay",
        "SystemSetup",
        "SystemAccessories",
        "PerfTestService",
        "NUVE::CurrentStage",
        "NUVE::Timing",
    ),
    "hardware_and_sensors": (
        "DeviceIOController",
        "UARTConnection",
        "GpioHandler",
        "NRFWatchdog",
        "AmbientEstimator",
        "CPULoadSimulator",
        "NUVE::Hardware",
        "NUVE::Sensors",
    ),
    "api_and_sync": (
        "DeviceAPI",
        "DevApiExecutor",
        "HttpExecutor",
        "RestApiExecutor",
        "ProtoBaseManager",
        "ProtoDataManager",
        "LiveDataManager",
        "EventDataManager",
        "DataParser",
        "NUVE::Sync",
    ),
    "network": (
        "NetworkManager",
        "NetworkInterface",
        "NmCli",
        "NmcliInterface",
        "NmcliObserver",
        "Nmcli",
        "WifiInfo",
        "ProcessExecutor",
    ),
    "weather_and_ui_services": (
        "WeatherService",
        "WeatherData",
        "ImageController",
        "QRCodeGenerator",
        "AppUtilities",
        "UtilityHelper",
    ),
    "update_and_recovery": (
        "UpdateManager",
        "RecoveryUpdater",
        "NUVE::senderProcess",
        "IUpdateStrategy",
        "ClientSpecificUpdateStrategy",
        "LegacyUpdateStrategy",
    ),
    "firmware_contract": ("AppSpecCPP",),
}

_LINE = re.compile(r"^([0-9a-fA-F]+)\s+([A-Za-z])\s+(.+)$")
_THUNK = re.compile(r"^(?:non-virtual thunk to |virtual thunk to |covariant return thunk to )")
_FUNCTION_SYMBOL_TYPES = frozenset("tTwW")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _symbols(path: Path) -> list[tuple[int, str, str]]:
    completed = subprocess.run(
        ["nm", "-C", "--defined-only", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    result: list[tuple[int, str, str]] = []
    for line in completed.stdout.splitlines():
        match = _LINE.match(line)
        if match:
            result.append((int(match.group(1), 16), match.group(2), match.group(3)))
    return result


def _matches_class(symbol: str, class_name: str) -> bool:
    clean = _THUNK.sub("", symbol)
    return bool(re.search(rf"(?:^|::){re.escape(class_name)}::", clean))


def inventory(path: Path) -> dict[str, object]:
    symbols = _symbols(path)
    report: dict[str, object] = {
        "binary": path.name,
        "sha256": _sha256(path),
        "defined_symbols": len(symbols),
        "subsystems": {},
    }
    assigned: set[tuple[int, str]] = set()
    first_party_function_addresses: set[int] = set()
    subsystems: dict[str, object] = {}
    for subsystem, classes in SUBSYSTEMS.items():
        class_symbols: dict[str, list[dict[str, object]]] = defaultdict(list)
        for address, symbol_type, symbol in symbols:
            for class_name in classes:
                if _matches_class(symbol, class_name):
                    class_symbols[class_name].append(
                        {
                            "address": f"0x{address:08x}",
                            "type": symbol_type,
                            "symbol": symbol,
                        }
                    )
                    assigned.add((address, symbol))
                    break
        subsystems[subsystem] = {
            "symbol_count": sum(len(items) for items in class_symbols.values()),
            "function_address_count": len(
                {
                    int(item["address"], 16)
                    for items in class_symbols.values()
                    for item in items
                    if item["type"] in _FUNCTION_SYMBOL_TYPES
                }
            ),
            "classes": dict(sorted(class_symbols.items())),
        }
        first_party_function_addresses.update(
            address
            for address, symbol_type, symbol in symbols
            if symbol_type in _FUNCTION_SYMBOL_TYPES
            and any(_matches_class(symbol, class_name) for class_name in classes)
        )
    report["subsystems"] = subsystems
    report["first_party_symbol_row_count"] = sum(
        details["symbol_count"] for details in subsystems.values()
    )
    report["first_party_unique_symbol_count"] = len(assigned)
    report["first_party_function_address_count"] = len(first_party_function_addresses)

    qml = [symbol for _, _, symbol in symbols if "QmlCacheGeneratedCode::" in symbol]
    report["qml_cache_symbol_count"] = len(qml)
    report["unassigned_qualified_prefixes"] = Counter(
        symbol.split("::", 1)[0]
        for address, _, symbol in symbols
        if "::" in symbol
        and (address, symbol) not in assigned
        and not symbol.startswith(("std::", "google::", "absl::", "QmlCacheGeneratedCode::"))
    ).most_common(25)
    return report


def _markdown(report: dict[str, object]) -> str:
    lines = [
        f"# Symbol inventory: `{report['binary']}`",
        "",
        f"- SHA-256: `{report['sha256']}`",
        f"- Defined symbols: {report['defined_symbols']}",
        f"- Generated QML-cache symbols: {report['qml_cache_symbol_count']}",
        f"- Selected first-party symbol rows: {report['first_party_symbol_row_count']}",
        (f"- Unique selected address/name identities: {report['first_party_unique_symbol_count']}"),
        (
            "- Unique selected first-party function addresses: "
            f"{report['first_party_function_address_count']}"
        ),
        "",
        "This inventory locates review targets; it does not establish behavior by itself.",
        "",
    ]
    subsystems = report["subsystems"]
    assert isinstance(subsystems, dict)
    for subsystem, raw_details in subsystems.items():
        details = raw_details
        assert isinstance(details, dict)
        lines.extend([f"## {subsystem.replace('_', ' ').title()}", ""])
        classes = details["classes"]
        assert isinstance(classes, dict)
        lines.append(f"Unique function addresses in subsystem: {details['function_address_count']}")
        lines.append("")
        lines.append("| Class | Symbols | Representative functions |")
        lines.append("| --- | ---: | --- |")
        for class_name, raw_items in classes.items():
            items = raw_items
            assert isinstance(items, list)
            representatives = []
            for item in items:
                symbol = str(item["symbol"])
                if any(
                    skip in symbol
                    for skip in ("qt_metac", "staticMetaObject", "typeinfo", "vtable")
                ):
                    continue
                representatives.append(f"`{item['address']}` {symbol}")
                if len(representatives) == 4:
                    break
            representative_text = "<br>".join(representatives) or "metadata only"
            lines.append(f"| `{class_name}` | {len(items)} | {representative_text} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args()
    try:
        report = inventory(args.binary)
    except (OSError, subprocess.CalledProcessError) as err:
        parser.error(str(err))
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
