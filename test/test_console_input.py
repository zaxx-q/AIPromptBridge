"""Unit tests for cross-platform console single-key input."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.platform import console_input as ci


@pytest.fixture(autouse=True)
def _reset_console_input_state():
    """Reset process-wide raw-mode depths between tests."""
    with ci._lock:
        ci._raw_depth = 0
        ci._suspend_depth = 0
        ci._saved_attrs = None
        ci._fd = None
        ci._msvcrt = None
        ci._msvcrt_checked = False
        ci._atexit_registered = False
    yield
    with ci._lock:
        ci._raw_depth = 0
        ci._suspend_depth = 0
        ci._saved_attrs = None
        ci._fd = None
        ci._msvcrt = None
        ci._msvcrt_checked = False


def test_is_console_input_available_false_when_not_tty():
    with (
        patch.object(ci, "is_windows", return_value=False),
        patch.object(ci.sys.stdin, "isatty", return_value=False),
    ):
        assert ci.is_console_input_available() is False


def test_is_console_input_available_true_on_windows_with_msvcrt():
    fake_msvcrt = MagicMock()
    with (
        patch.object(ci, "is_windows", return_value=True),
        patch.dict("sys.modules", {"msvcrt": fake_msvcrt}),
    ):
        # Force re-import path
        ci._msvcrt_checked = False
        ci._msvcrt = None
        # _load_msvcrt does `import msvcrt` — provide module
        with patch.object(ci, "_load_msvcrt", return_value=fake_msvcrt):
            assert ci.is_console_input_available() is True


def test_get_key_windows_returns_char():
    fake = MagicMock()
    fake.kbhit.side_effect = [True]
    fake.getch.return_value = b"S"

    with (
        patch.object(ci, "is_windows", return_value=True),
        patch.object(ci, "_load_msvcrt", return_value=fake),
    ):
        assert ci.get_key(timeout=0.0) == "s"


def test_get_key_windows_discards_extended_keys():
    fake = MagicMock()
    # First kbhit True → extended prefix; second kbhit for discard True
    fake.kbhit.side_effect = [True, True]
    fake.getch.side_effect = [b"\xe0", b"H"]  # arrow up

    with (
        patch.object(ci, "is_windows", return_value=True),
        patch.object(ci, "_load_msvcrt", return_value=fake),
    ):
        assert ci.get_key(timeout=0.0) is None


def test_get_key_windows_timeout_none():
    fake = MagicMock()
    fake.kbhit.return_value = False

    with (
        patch.object(ci, "is_windows", return_value=True),
        patch.object(ci, "_load_msvcrt", return_value=fake),
    ):
        assert ci.get_key(timeout=0.0) is None


def test_raw_console_unix_enable_disable_sync():
    fake_attrs = ["saved"]
    with (
        patch.object(ci, "is_windows", return_value=False),
        patch.object(ci, "_stdin_fd", return_value=0),
        patch.object(ci, "_unix_tcgetattr", return_value=fake_attrs) as get_attrs,
        patch.object(ci, "_unix_setcbreak") as setcbreak,
        patch.object(ci, "_unix_tcsetattr") as setattr_,
        patch.object(ci, "_ensure_atexit"),
    ):
        with ci.RawConsole() as keys:
            assert ci._raw_depth == 1
            assert ci._is_effectively_raw() is True
            get_attrs.assert_called_once()
            setcbreak.assert_called()

            with keys.cooked():
                assert ci._suspend_depth == 1
                assert ci._is_effectively_raw() is False
                # Restored cooked attrs while suspended
                setattr_.assert_called()

            assert ci._suspend_depth == 0
            assert ci._is_effectively_raw() is True

        assert ci._raw_depth == 0
        assert ci._saved_attrs is None


def test_nested_raw_under_cooked_becomes_effective():
    """Batch listener RawConsole under outer cooked() must get cbreak."""
    fake_attrs = ["saved"]
    # Nested with blocks intentionally model terminal cooked() + batch listener RawConsole.
    with (
        patch.object(ci, "is_windows", return_value=False),
        patch.object(ci, "_stdin_fd", return_value=0),
        patch.object(ci, "_unix_tcgetattr", return_value=fake_attrs),
        patch.object(ci, "_unix_setcbreak") as setcbreak,
        patch.object(ci, "_unix_tcsetattr"),
        patch.object(ci, "_ensure_atexit"),
        ci.RawConsole(),
        ci.RawConsole().cooked(),
    ):
        assert ci._is_effectively_raw() is False
        with ci.RawConsole():
            # raw_depth=2, suspend=1 → effectively raw
            assert ci._raw_depth == 2
            assert ci._suspend_depth == 1
            assert ci._is_effectively_raw() is True
            assert setcbreak.called


def test_get_key_unix_reads_os_byte():
    with (
        patch.object(ci, "is_windows", return_value=False),
        patch.object(ci, "_stdin_fd", return_value=0),
        patch.object(ci, "_enable_raw_unix", return_value=True),
        patch.object(ci, "_disable_raw_unix"),
        patch.object(ci, "_is_effectively_raw", return_value=True),
        patch("select.select", return_value=([0], [], [])),
        patch.object(ci.os, "read", return_value=b"H"),
    ):
        # hold_raw False path (no active RawConsole) still works via brief enable
        with ci._lock:
            ci._raw_depth = 0
        assert ci.get_key(timeout=0.1) == "h"


def test_get_key_unix_drains_escape():
    reads = [b"\x1b", b"[", b"A"]  # up arrow

    def fake_read(_fd, _n):
        return reads.pop(0) if reads else b""

    with (
        patch.object(ci, "is_windows", return_value=False),
        patch.object(ci, "_stdin_fd", return_value=0),
        patch.object(ci, "_enable_raw_unix", return_value=True),
        patch.object(ci, "_disable_raw_unix"),
        patch.object(ci, "_is_effectively_raw", return_value=True),
        patch("select.select", return_value=([0], [], [])),
        patch.object(ci.os, "read", side_effect=fake_read),
    ):
        with ci._lock:
            ci._raw_depth = 0
        assert ci.get_key(timeout=0.1) is None


def test_line_input_uses_cooked_and_input():
    with (
        patch.object(ci, "is_windows", return_value=False),
        patch.object(ci, "_stdin_fd", return_value=0),
        patch.object(ci, "_unix_tcgetattr", return_value=["attrs"]),
        patch.object(ci, "_unix_setcbreak"),
        patch.object(ci, "_unix_tcsetattr"),
        patch.object(ci, "_ensure_atexit"),
        patch("builtins.input", return_value="  hello  ") as inp,
        ci.RawConsole() as keys,
    ):
        assert keys.line_input("Name: ").strip() == "hello"
        inp.assert_called_once_with("Name: ")
