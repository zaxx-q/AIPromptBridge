"""Unit tests for Linux IPC trigger protocol and client/server round-trip.

Uses a temporary Unix socket path and a background server thread.
Does not start the full application.
"""

from __future__ import annotations

import socket
import time
from pathlib import Path

from src.platform.ipc import (
    KNOWN_TRIGGERS,
    TriggerServer,
    _bind_listen_socket,
    decode_message,
    encode_reply_error,
    encode_reply_ok,
    encode_trigger,
    get_socket_path,
    parse_reply,
    send_trigger,
)


def test_encode_trigger_normalizes_name():
    assert encode_trigger("Snip") == b"snip\n"
    assert encode_trigger("  TEXTEDIT  ") == b"textedit\n"


def test_decode_message_bare_and_trigger_prefix():
    assert decode_message(b"snip\n") == "snip"
    assert decode_message(b"trigger snip\n") == "snip"
    assert decode_message(b"TRIGGER Audio\n") == "audio"
    assert decode_message(b"  chat  ") == "chat"
    assert decode_message(b"") == ""


def test_encode_and_parse_replies():
    assert parse_reply(encode_reply_ok()) == (True, "ok")
    ok, msg = parse_reply(encode_reply_error("tool unavailable"))
    assert ok is False
    assert msg == "tool unavailable"
    ok, msg = parse_reply(b"error not ready\n")
    assert ok is False
    assert msg == "not ready"


def test_known_triggers_include_core_tools():
    for name in ("snip", "textedit", "audio", "tts", "chat", "browser"):
        assert name in KNOWN_TRIGGERS


def test_send_trigger_no_server(tmp_path: Path):
    sock_path = str(tmp_path / "missing.sock")
    ok, msg = send_trigger("snip", socket_path=sock_path, timeout=1.0)
    assert ok is False
    assert "No running AIPromptBridge instance" in msg or "Cannot connect" in msg


def test_send_trigger_rejects_unknown(tmp_path: Path):
    ok, msg = send_trigger("not-a-real-trigger", socket_path=str(tmp_path / "x.sock"))
    assert ok is False
    assert "unknown trigger" in msg


def test_client_server_round_trip(tmp_path: Path):
    """Fake server thread handles snip → ok and missing tool → error."""
    sock_path = str(tmp_path / "aipromptbridge-test.sock")
    received: list[str] = []

    def handler(name: str):
        received.append(name)
        if name == "snip":
            return True, ""
        if name == "audio":
            return False, "tool unavailable"
        return False, f"unexpected {name}"

    server = TriggerServer(handler=handler, socket_path=sock_path)
    server.start()
    try:
        # Brief wait for listen thread
        deadline = time.time() + 2.0
        while time.time() < deadline and not Path(sock_path).exists():
            time.sleep(0.01)

        ok, msg = send_trigger("snip", socket_path=sock_path, timeout=2.0)
        assert ok is True
        assert msg == "ok"
        assert received == ["snip"]

        ok, msg = send_trigger("audio", socket_path=sock_path, timeout=2.0)
        assert ok is False
        assert msg == "tool unavailable"
        assert received == ["snip", "audio"]
    finally:
        server.stop()

    # Socket path should be cleaned up
    assert not Path(sock_path).exists()


def test_server_rejects_unknown_trigger(tmp_path: Path):
    sock_path = str(tmp_path / "aipromptbridge-unknown.sock")
    server = TriggerServer(handler=lambda n: (True, ""), socket_path=sock_path)
    server.start()
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline and not Path(sock_path).exists():
            time.sleep(0.01)

        # Bypass send_trigger's client-side known-trigger check
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(2.0)
            sock.connect(sock_path)
            sock.sendall(b"notreal\n")
            data = sock.recv(4096)
        finally:
            sock.close()

        ok, msg = parse_reply(data)
        assert ok is False
        assert "unknown trigger" in msg
    finally:
        server.stop()


def test_detect_helpers():
    from src.platform.detect import is_linux, is_wayland, is_windows

    # Sanity: mutually exclusive for windows vs linux on this host
    assert is_windows() is False or is_linux() is False
    # is_wayland is always bool
    assert isinstance(is_wayland(), bool)


def test_get_socket_path_xdg(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    path = get_socket_path()
    assert path == "/run/user/1000/aipromptbridge.sock"


def test_get_socket_path_tmp_fallback(monkeypatch):
    import os

    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    path = get_socket_path()
    if hasattr(os, "getuid"):
        uid = os.getuid()
        assert path == f"/tmp/aipromptbridge-{uid}.sock"
    else:
        assert path == "/tmp/aipromptbridge.sock"


def test_bind_listen_socket_sets_permissions(tmp_path: Path):
    import os
    import sys

    sock_path = str(tmp_path / "perm_test.sock")
    sock = _bind_listen_socket(sock_path)
    try:
        if sys.platform != "win32":
            mode = os.stat(sock_path).st_mode & 0o777
            assert mode == 0o600
    finally:
        sock.close()
