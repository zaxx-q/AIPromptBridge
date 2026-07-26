"""Unit tests for Wayland input service (mocked subprocess — no compositor)."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from src.platform import input as input_mod
from src.platform.input import (
    copy_via_clipboard_shortcut,
    is_wlrctl_available,
    paste_via_clipboard_shortcut,
    press_chord,
    type_text,
)


@pytest.fixture(autouse=True)
def _reset_input_cache():
    """Reset process-lifetime binary cache between tests."""
    input_mod._wlrctl_path = None
    input_mod._availability_checked = False
    input_mod._missing_warned = False
    yield
    input_mod._wlrctl_path = None
    input_mod._availability_checked = False
    input_mod._missing_warned = False


def _completed(
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_is_wlrctl_available_false_when_missing():
    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value=None),
    ):
        assert is_wlrctl_available() is False


def test_is_wlrctl_available_true_when_present():
    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value="/usr/bin/wlrctl"),
    ):
        assert is_wlrctl_available() is True


def test_is_wlrctl_available_false_on_non_linux():
    with patch.object(input_mod, "is_linux", return_value=False):
        assert is_wlrctl_available() is False
        assert type_text("hi") is False
        assert press_chord(["CTRL"], "v") is False
        assert paste_via_clipboard_shortcut() is False
        assert copy_via_clipboard_shortcut() is False


def test_missing_binary_safe_failure_no_crash():
    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value=None),
    ):
        assert type_text("hello") is False
        assert press_chord(["CTRL"], "v") is False
        assert paste_via_clipboard_shortcut() is False
        assert copy_via_clipboard_shortcut() is False


def test_paste_chord_argv():
    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value="/usr/bin/wlrctl"),
        patch.object(input_mod.subprocess, "run", return_value=_completed()) as run,
    ):
        assert paste_via_clipboard_shortcut() is True
        args = run.call_args[0][0]
        assert args[0] == "/usr/bin/wlrctl"
        assert "keyboard" in args
        assert "type" in args
        assert "v" in args
        # modifiers CTRL as documented by wlrctl man page
        assert "modifiers" in args
        mod_idx = args.index("modifiers")
        assert args[mod_idx + 1] == "CTRL"
        assert run.call_args[1]["timeout"] == input_mod._CHORD_TIMEOUT
        assert run.call_args[1]["check"] is False
        assert run.call_args[1].get("shell") in (None, False)


def test_copy_chord_argv():
    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value="/usr/bin/wlrctl"),
        patch.object(input_mod.subprocess, "run", return_value=_completed()) as run,
    ):
        assert copy_via_clipboard_shortcut() is True
        args = run.call_args[0][0]
        assert args[0] == "/usr/bin/wlrctl"
        assert "keyboard" in args
        assert "type" in args
        assert "c" in args
        assert "modifiers" in args
        assert "CTRL" in args


def test_press_chord_normalizes_modifier_aliases():
    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value="/usr/bin/wlrctl"),
        patch.object(input_mod.subprocess, "run", return_value=_completed()) as run,
    ):
        assert press_chord(["control", "shift"], "a") is True
        args = run.call_args[0][0]
        mod_idx = args.index("modifiers")
        assert args[mod_idx + 1] == "CTRL,SHIFT"


def test_type_text_simple_argv():
    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value="/usr/bin/wlrctl"),
        patch.object(input_mod.subprocess, "run", return_value=_completed()) as run,
    ):
        assert type_text("hello from wlrctl") is True
        args = run.call_args[0][0]
        assert args == ["/usr/bin/wlrctl", "keyboard", "type", "hello from wlrctl"]
        assert run.call_args[1]["timeout"] == input_mod._TYPE_TIMEOUT


def test_type_text_empty_string_succeeds_without_subprocess():
    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value="/usr/bin/wlrctl"),
        patch.object(input_mod.subprocess, "run", return_value=_completed()) as run,
    ):
        assert type_text("") is True
        run.assert_not_called()


def test_type_text_chunks_long_strings():
    # Two full chunks + remainder
    long_text = "a" * (input_mod._TYPE_CHUNK_SIZE * 2 + 50)
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return _completed()

    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value="/usr/bin/wlrctl"),
        patch.object(input_mod.subprocess, "run", side_effect=fake_run),
    ):
        assert type_text(long_text) is True
        assert len(calls) == 3
        # Each call is a single type of a chunk (not per-character)
        lengths = [len(c[3]) for c in calls]
        assert lengths == [
            input_mod._TYPE_CHUNK_SIZE,
            input_mod._TYPE_CHUNK_SIZE,
            50,
        ]
        for c in calls:
            assert c[0] == "/usr/bin/wlrctl"
            assert c[1:3] == ["keyboard", "type"]


def test_type_text_newlines_use_shift_enter():
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return _completed()

    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value="/usr/bin/wlrctl"),
        patch.object(input_mod.subprocess, "run", side_effect=fake_run),
    ):
        assert type_text("hi\nthere") is True
        # text, shift+enter newline, text
        assert len(calls) == 3
        assert calls[0] == ["/usr/bin/wlrctl", "keyboard", "type", "hi"]
        assert calls[1][1:3] == ["keyboard", "type"]
        assert calls[1][3] == "\n"
        assert "modifiers" in calls[1]
        assert "SHIFT" in calls[1]
        assert calls[2] == ["/usr/bin/wlrctl", "keyboard", "type", "there"]


def test_type_text_skips_carriage_returns():
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return _completed()

    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value="/usr/bin/wlrctl"),
        patch.object(input_mod.subprocess, "run", side_effect=fake_run),
    ):
        assert type_text("a\r\nb\rc") is True
        # \r\n -> one newline; lone \r stripped; so: "a", nl, "bc"
        assert len(calls) == 3
        assert calls[0][3] == "a"
        assert calls[1][3] == "\n"
        assert calls[2][3] == "bc"


def test_type_text_abort_check_stops_between_chunks():
    long_text = "x" * (input_mod._TYPE_CHUNK_SIZE + 10)
    calls = 0

    def fake_run(args, **kwargs):
        nonlocal calls
        calls += 1
        return _completed()

    # Abort after first unit
    state = {"n": 0}

    def abort_check():
        state["n"] += 1
        return state["n"] > 1

    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value="/usr/bin/wlrctl"),
        patch.object(input_mod.subprocess, "run", side_effect=fake_run),
    ):
        assert type_text(long_text, abort_check=abort_check) is False
        assert calls == 1  # second chunk never typed


def test_type_text_nonzero_exit_returns_false():
    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value="/usr/bin/wlrctl"),
        patch.object(input_mod.subprocess, "run", return_value=_completed(returncode=1)),
    ):
        assert type_text("fail") is False


def test_type_text_timeout_returns_false():
    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value="/usr/bin/wlrctl"),
        patch.object(
            input_mod.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="wlrctl", timeout=15),
        ),
    ):
        assert type_text("slow") is False


def test_never_uses_shell_true():
    with (
        patch.object(input_mod, "is_linux", return_value=True),
        patch.object(input_mod.shutil, "which", return_value="/usr/bin/wlrctl"),
        patch.object(input_mod.subprocess, "run", return_value=_completed()) as run,
    ):
        type_text("safe; rm -rf /")
        # String is a single argv element — not interpreted by a shell
        args = run.call_args[0][0]
        assert args[3] == "safe; rm -rf /"
        assert run.call_args[1].get("shell") in (None, False)
