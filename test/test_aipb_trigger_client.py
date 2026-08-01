"""Tests for the fast stdlib IPC trigger client (scripts/aipb_trigger.py)."""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest

from src.platform.ipc import KNOWN_TRIGGERS, TriggerServer, send_trigger

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT_PATH = REPO_ROOT / "scripts" / "aipb_trigger.py"


def _load_aipb_trigger():
    """Load scripts/aipb_trigger.py as a module without executing __main__."""
    spec = importlib.util.spec_from_file_location("aipb_trigger_under_test", CLIENT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Avoid running the project-ipc prefer path at import of functions only —
    # loading the file defines functions; __main__ is not run.
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def trigger_mod():
    assert CLIENT_PATH.is_file(), f"missing {CLIENT_PATH}"
    return _load_aipb_trigger()


def test_client_known_triggers_match_ipc(trigger_mod):
    assert tuple(trigger_mod.KNOWN_TRIGGERS) == tuple(KNOWN_TRIGGERS)


def test_client_cli_help(trigger_mod):
    assert trigger_mod.cli_main(["--help"]) == 0


def test_client_cli_missing_name(trigger_mod):
    assert trigger_mod.cli_main([]) == 1


def test_client_cli_unknown_trigger(trigger_mod, tmp_path: Path):
    # Unknown rejected client-side without needing a server
    code = trigger_mod.cli_main(["not-a-real-trigger"])
    assert code == 1


def test_client_send_trigger_round_trip(trigger_mod, tmp_path: Path):
    sock_path = str(tmp_path / "aipb-client-test.sock")
    received: list[str] = []

    def handler(name: str):
        received.append(name)
        return True, ""

    server = TriggerServer(handler=handler, socket_path=sock_path)
    server.start()
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline and not Path(sock_path).exists():
            time.sleep(0.01)

        ok, msg = trigger_mod.send_trigger("snip", socket_path=sock_path, timeout=2.0)
        assert ok is True
        assert msg == "ok"
        assert received == ["snip"]

        # ipc.send_trigger should agree on the same socket
        ok2, msg2 = send_trigger("snip", socket_path=sock_path, timeout=2.0)
        assert ok2 is True
        assert msg2 == "ok"
    finally:
        server.stop()


def test_client_cli_main_with_server(trigger_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sock_path = str(tmp_path / "aipb-cli-test.sock")
    server = TriggerServer(handler=lambda n: (True, ""), socket_path=sock_path)
    server.start()
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline and not Path(sock_path).exists():
            time.sleep(0.01)

        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        # Point client at our temp sock by overriding get_socket_path via env:
        # SOCKET_NAME is fixed; put sock at XDG_RUNTIME_DIR/aipromptbridge.sock
        target = Path(tmp_path) / "aipromptbridge.sock"
        if Path(sock_path).exists() and not target.exists():
            # Server bound sock_path; rebind by stopping and using standard name
            pass
    finally:
        server.stop()

    # Use explicit socket via send_trigger; cli_main uses get_socket_path.
    # Re-run with socket at XDG path:
    sock_path = str(Path(tmp_path) / "aipromptbridge.sock")
    server = TriggerServer(handler=lambda n: (True, ""), socket_path=sock_path)
    server.start()
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline and not Path(sock_path).exists():
            time.sleep(0.01)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        assert trigger_mod.cli_main(["snip"]) == 0
        assert trigger_mod.cli_main(["--trigger", "textedit"]) == 0
    finally:
        server.stop()


def test_ipc_cli_main_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from src.platform import ipc as ipc_mod

    sock_path = str(Path(tmp_path) / "aipromptbridge.sock")
    server = TriggerServer(handler=lambda n: (True, ""), socket_path=sock_path)
    server.start()
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline and not Path(sock_path).exists():
            time.sleep(0.01)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        assert ipc_mod.cli_main(["snip"]) == 0
        assert ipc_mod.cli_main(["--trigger=audio"]) == 0
    finally:
        server.stop()


@pytest.mark.skipif(sys.platform == "win32", reason="Unix sockets")
def test_no_server_message(trigger_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    code = trigger_mod.cli_main(["snip"])
    assert code == 1
