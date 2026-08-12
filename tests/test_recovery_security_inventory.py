from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "inventory_recovery_security.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("inventory_recovery_security", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def security_module():
    return _load_module()


def _write(root: Path, relative_path: str, text: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _fixture_root(tmp_path: Path) -> Path:
    _write(
        tmp_path,
        "etc/ssh/sshd_config",
        """# PasswordAuthentication no
PermitRootLogin yes
PermitEmptyPasswords yes
UsePAM yes
X11Forwarding yes
Subsystem sftp /secret/path-that-must-not-leak
""",
    )
    _write(tmp_path, "etc/ssh/sshd_config_readonly", "HostKey /private/key\n")
    _write(
        tmp_path,
        "lib/systemd/system/sshd.socket",
        "[Socket]\nListenStream=22\nAccept=yes\n",
    )
    _write(
        tmp_path,
        "lib/systemd/system/sshd@.service",
        "[Service]\nExecStart=-/usr/sbin/sshd -i $SSHD_OPTS\n",
    )
    _write(
        tmp_path,
        "lib/systemd/system/rpcbind.socket",
        "[Socket]\nListenStream=/run/rpcbind.sock\nListenStream=111\nListenDatagram=111\n",
    )
    _write(tmp_path, "etc/iptables/iptables.rules", "# intentionally empty\n")
    _write(
        tmp_path,
        "etc/shadow",
        "root:$6$private-verifier:1:2:3:4:5:6:7\n"
        "privateaccount:!:1:2:3:4:5:6:7\n"
        "empty::1:2:3:4:5:6:7\n",
    )
    ssh_want = tmp_path / "etc/systemd/system/sockets.target.wants/sshd.socket"
    ssh_want.parent.mkdir(parents=True)
    ssh_want.symlink_to("/lib/systemd/system/sshd.socket")
    (ssh_want.parent / "rpcbind.socket").symlink_to("/lib/systemd/system/rpcbind.socket")
    firewall_want = tmp_path / "etc/systemd/system/multi-user.target.wants/iptables.service"
    firewall_want.parent.mkdir(parents=True)
    firewall_want.symlink_to("/lib/systemd/system/iptables.service")
    return tmp_path


def test_inventory_reports_security_state_without_secret_material(
    tmp_path: Path, security_module
) -> None:
    report = security_module.inventory_security(_fixture_root(tmp_path))

    assert report["sshd"]["socket_enabled"] == {"present": True, "symlink": True}
    assert report["sshd"]["listen_streams"] == ["22"]
    assert report["sshd"]["socket_accept"] == ["yes"]
    assert report["sshd"]["explicit_directives"] == {
        "permitemptypasswords": ["yes"],
        "permitrootlogin": ["yes"],
        "usepam": ["yes"],
        "x11forwarding": ["yes"],
    }
    assert report["accounts"] == {
        "present": True,
        "root_state": "verifier_present",
        "account_count": 3,
        "state_counts": {"empty": 1, "locked": 1, "verifier_present": 1},
    }
    assert report["iptables"]["rules"]["rule_lines"] == 0
    assert report["enabled_socket_units"] == [
        {
            "unit": "rpcbind.socket",
            "accept": [],
            "listen_stream": ["/run/rpcbind.sock", "111"],
            "listen_datagram": ["111"],
            "listen_sequential_packet": [],
            "listen_netlink": [],
        },
        {
            "unit": "sshd.socket",
            "accept": ["yes"],
            "listen_stream": ["22"],
            "listen_datagram": [],
            "listen_sequential_packet": [],
            "listen_netlink": [],
        },
    ]

    rendered = json.dumps(report)
    assert "private-verifier" not in rendered
    assert "privateaccount" not in rendered
    assert "empty" in rendered  # state class, not the fixture account name
    assert "secret/path" not in rendered
    assert "/private/key" not in rendered


def test_missing_files_are_explicit(tmp_path: Path, security_module) -> None:
    report = security_module.inventory_security(tmp_path)

    assert report["sshd"]["config_present"] is False
    assert report["sshd"]["listen_streams"] == []
    assert report["accounts"]["root_state"] == "missing_file"
    assert report["iptables"]["rules"] == {
        "present": False,
        "bytes": 0,
        "sha256": None,
        "rule_lines": 0,
    }


@pytest.mark.parametrize(
    ("field", "expected"),
    [("", "empty"), ("!", "locked"), ("*LK*", "locked"), ("$6$hash", "verifier_present")],
)
def test_credential_state_classes(field: str, expected: str, security_module) -> None:
    assert security_module._credential_state(field) == expected


def test_malformed_shadow_rows_are_counted_without_echo(
    security_module,
) -> None:
    report = security_module.classify_shadow("bad-row\nroot:!:\n")

    assert report["root_state"] == "locked"
    assert report["state_counts"] == {"locked": 1, "malformed": 1}
