#!/usr/bin/env python3
"""
Fast Linux IPC trigger client (stdlib only).

Used by the outer Linux launcher for ``AIPromptBridge --trigger <name>`` so
hotkey binds do **not** start the full Nuitka binary (~3s). Protocol matches
``src.platform.ipc`` (one-line UTF-8 request/reply over AF_UNIX).

When run from a source checkout that has ``src/platform/ipc.py``, prefer that
module (single source of truth). Release packages ship this file next to the
outer launcher without the full ``src/`` tree; the inlined client below is used
then and must stay in sync with ``KNOWN_TRIGGERS`` / ``send_trigger``.

Usage:
  python3 aipb_trigger.py snip
  python3 aipb_trigger.py --trigger textedit
  AIPromptBridge --trigger snip   # launcher execs this script
"""

from __future__ import annotations

import contextlib
import os
import socket
import sys
from typing import Sequence

# Keep in sync with src.platform.ipc.KNOWN_TRIGGERS (enforced by tests).
KNOWN_TRIGGERS = (
    "snip",
    "textedit",
    "audio",
    "tts",
    "chat",
    "browser",
    "settings",
    "prompts",
)

SOCKET_NAME = "aipromptbridge.sock"


def get_socket_path() -> str:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if runtime_dir:
        return os.path.join(runtime_dir, SOCKET_NAME)
    try:
        uid = os.getuid()
        return os.path.join("/tmp", f"aipromptbridge-{uid}.sock")
    except AttributeError:
        return os.path.join("/tmp", SOCKET_NAME)


def send_trigger(
    name: str,
    socket_path: str | None = None,
    timeout: float = 5.0,
) -> tuple[bool, str]:
    """Connect to the running instance, send a trigger, return (ok, message)."""
    path = socket_path or get_socket_path()
    trigger = name.strip().lower()
    if not trigger:
        return False, "missing trigger name"
    if trigger not in KNOWN_TRIGGERS:
        return False, f"unknown trigger: {trigger}"

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except (OSError, AttributeError) as e:
        return False, f"Unix sockets not available: {e}"

    try:
        sock.settimeout(timeout)
        try:
            sock.connect(path)
        except (FileNotFoundError, ConnectionRefusedError):
            return (
                False,
                "No running AIPromptBridge instance found. Start the app first, then retry --trigger.",
            )
        except OSError as e:
            return (
                False,
                f"Cannot connect to AIPromptBridge IPC socket ({path}): {e}. Is the app running?",
            )

        sock.sendall(f"{trigger}\n".encode())
        chunks: list[bytes] = []
        while True:
            try:
                part = sock.recv(4096)
            except TimeoutError:
                return False, "timeout waiting for reply from running instance"
            if not part:
                break
            chunks.append(part)
            if b"\n" in part:
                break
        return _parse_reply(b"".join(chunks))
    finally:
        with contextlib.suppress(OSError):
            sock.close()


def _parse_reply(data: bytes) -> tuple[bool, str]:
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return False, "empty reply"
    if "\n" in text:
        text = text.split("\n", 1)[0].strip()
    lower = text.lower()
    if lower == "ok":
        return True, "ok"
    if lower.startswith("error"):
        detail = text[5:].strip() if len(text) > 5 else "unknown error"
        return False, detail or "unknown error"
    return False, text


def _resolve_trigger_name(argv: Sequence[str]) -> tuple[str | None, str | None]:
    """
    Parse CLI args into (trigger_name, error_message).

    Accepts:
      aipb_trigger.py snip
      aipb_trigger.py --trigger snip
      aipb_trigger.py --trigger=snip
    """
    args = [a for a in argv if a]
    if not args:
        return None, "missing trigger name (e.g. snip, textedit, audio)"

    if args[0] in ("-h", "--help"):
        return None, "help"

    if args[0] == "--trigger":
        if len(args) < 2:
            return None, "missing trigger name after --trigger"
        return args[1].strip().lower(), None

    if args[0].startswith("--trigger="):
        return args[0].split("=", 1)[1].strip().lower(), None

    if args[0].startswith("-"):
        return None, f"unknown option: {args[0]}"

    return args[0].strip().lower(), None


def cli_main(argv: Sequence[str] | None = None) -> int:
    """CLI entry: exit 0 on ok, 1 on error. Quiet on success (niri-friendly)."""
    raw = list(sys.argv[1:] if argv is None else argv)
    name, err = _resolve_trigger_name(raw)
    if err == "help":
        triggers = ", ".join(KNOWN_TRIGGERS)
        print(
            "Usage: aipb_trigger.py <trigger> | aipb_trigger.py --trigger <trigger>\n"
            f"Triggers: {triggers}\n"
            "Requires a running AIPromptBridge instance (does not auto-start).",
            file=sys.stderr,
        )
        return 0
    if err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    assert name is not None

    if sys.platform == "win32":
        print(
            "error: IPC --trigger is only available on Linux (Windows uses tray / global hotkeys).",
            file=sys.stderr,
        )
        return 1

    ok, message = send_trigger(name)
    if ok:
        return 0
    print(f"error: trigger {name}: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    # Always use the inlined stdlib client (no import of src/) so compositor
    # binds stay in the tens of milliseconds. KNOWN_TRIGGERS is kept in sync
    # with src.platform.ipc by unit tests.
    raise SystemExit(cli_main())
