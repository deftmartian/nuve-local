#!/usr/bin/env python3
"""Inventory non-secret security posture from an offline recovery root.

Only fixed configuration files and credential *states* are inspected. Password
verifiers, public/private keys, authorized-key contents, account names other than
the conventional root account, and arbitrary configuration values are never
emitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

SSHD_DIRECTIVE_ALLOWLIST = frozenset(
    {
        "allowagentforwarding",
        "allowtcpforwarding",
        "authorizedkeysfile",
        "challengeresponseauthentication",
        "gatewayports",
        "listenaddress",
        "passwordauthentication",
        "permitemptypasswords",
        "permitrootlogin",
        "permittunnel",
        "port",
        "usepam",
        "x11forwarding",
    }
)


def _read_text(root: Path, relative_path: str) -> str | None:
    path = root / relative_path
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def parse_sshd_directives(text: str) -> dict[str, list[str]]:
    """Return only explicit security-relevant directives from sshd_config."""

    directives: dict[str, list[str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition(" ")
        if not separator:
            name, separator, value = line.partition("\t")
        normalized = name.lower()
        if normalized in SSHD_DIRECTIVE_ALLOWLIST and value.strip():
            directives.setdefault(normalized, []).append(value.strip())
    return directives


def _credential_state(field: str) -> str:
    if not field:
        return "empty"
    if field.startswith(("!", "*")):
        return "locked"
    return "verifier_present"


def classify_shadow(text: str | None) -> dict[str, Any]:
    """Summarize credential states without returning names or verifier bytes."""

    if text is None:
        return {
            "present": False,
            "root_state": "missing_file",
            "account_count": 0,
            "state_counts": {},
        }

    states: Counter[str] = Counter()
    root_state = "missing_account"
    for line in text.splitlines():
        fields = line.split(":", 2)
        if len(fields) < 2:
            states["malformed"] += 1
            continue
        account, verifier = fields[:2]
        state = _credential_state(verifier)
        states[state] += 1
        if account == "root":
            root_state = state
    return {
        "present": True,
        "root_state": root_state,
        "account_count": sum(states.values()),
        "state_counts": dict(sorted(states.items())),
    }


def parse_systemd_values(text: str | None, key: str) -> list[str]:
    """Return repeated exact values for one non-secret unit key."""

    if text is None:
        return []
    values: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        name, separator, value = line.partition("=")
        if separator and name.strip().lower() == key.lower():
            values.append(value.strip())
    return values


def _enabled_symlink(root: Path, relative_path: str) -> dict[str, Any]:
    path = root / relative_path
    return {
        "present": path.exists() or path.is_symlink(),
        "symlink": path.is_symlink(),
    }


def _iptables_summary(text: str | None) -> dict[str, Any]:
    if text is None:
        return {"present": False, "bytes": 0, "sha256": None, "rule_lines": 0}
    rule_lines = sum(
        1
        for raw_line in text.splitlines()
        if raw_line.strip() and not raw_line.lstrip().startswith("#")
    )
    return {
        "present": True,
        "bytes": len(text.encode()),
        "sha256": _sha256_text(text),
        "rule_lines": rule_lines,
    }


def _credential_file_counts(root: Path) -> dict[str, int]:
    ssh_directory = root / "etc/ssh"
    root_ssh_directory = root / "root/.ssh"
    return {
        "host_private_keys": len(tuple(ssh_directory.glob("ssh_host_*_key"))),
        "host_public_keys": len(tuple(ssh_directory.glob("ssh_host_*_key.pub"))),
        "root_authorized_key_files": int((root_ssh_directory / "authorized_keys").is_file()),
    }


def _unit_text(root: Path, unit_name: str) -> str | None:
    for directory in ("etc/systemd/system", "lib/systemd/system"):
        text = _read_text(root, f"{directory}/{unit_name}")
        if text is not None:
            return text
    return None


def _enabled_socket_units(root: Path) -> list[dict[str, Any]]:
    wants = root / "etc/systemd/system/sockets.target.wants"
    if not wants.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(wants.glob("*.socket"), key=lambda candidate: candidate.name):
        text = _unit_text(root, path.name)
        records.append(
            {
                "unit": path.name,
                "accept": parse_systemd_values(text, "Accept"),
                "listen_stream": parse_systemd_values(text, "ListenStream"),
                "listen_datagram": parse_systemd_values(text, "ListenDatagram"),
                "listen_sequential_packet": parse_systemd_values(text, "ListenSequentialPacket"),
                "listen_netlink": parse_systemd_values(text, "ListenNetlink"),
            }
        )
    return records


def inventory_security(root: Path) -> dict[str, Any]:
    """Create a deterministic report without secrets for one offline root tree."""

    sshd_config = _read_text(root, "etc/ssh/sshd_config")
    readonly_config = _read_text(root, "etc/ssh/sshd_config_readonly")
    sshd_socket = _read_text(root, "lib/systemd/system/sshd.socket")
    sshd_service = _read_text(root, "lib/systemd/system/sshd@.service")
    iptables_rules = _read_text(root, "etc/iptables/iptables.rules")

    return {
        "schema_version": 1,
        "enabled_socket_units": _enabled_socket_units(root),
        "sshd": {
            "socket_enabled": _enabled_symlink(
                root, "etc/systemd/system/sockets.target.wants/sshd.socket"
            ),
            "listen_streams": parse_systemd_values(sshd_socket, "ListenStream"),
            "socket_accept": parse_systemd_values(sshd_socket, "Accept"),
            "service_exec_start": parse_systemd_values(sshd_service, "ExecStart"),
            "config_present": sshd_config is not None,
            "config_sha256": _sha256_text(sshd_config) if sshd_config is not None else None,
            "explicit_directives": (
                parse_sshd_directives(sshd_config) if sshd_config is not None else {}
            ),
            "readonly_config_present": readonly_config is not None,
            "credential_file_counts": _credential_file_counts(root),
        },
        "accounts": classify_shadow(_read_text(root, "etc/shadow")),
        "iptables": {
            "service_enabled": _enabled_symlink(
                root, "etc/systemd/system/multi-user.target.wants/iptables.service"
            ),
            "rules": _iptables_summary(iptables_rules),
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        type=Path,
        help="read-only mounted or extracted recovery-root directory",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.root.is_dir():
        raise SystemExit("root must be an existing directory")
    print(json.dumps(inventory_security(args.root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
