"""Unit tests for Wayland clipboard service (mocked subprocess — no compositor)."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from src.platform import clipboard as clipboard_mod
from src.platform.clipboard import (
    copy_bytes,
    copy_rich_text,
    copy_text,
    get_selected_text_wayland,
    has_primary_selection,
    is_wl_clipboard_available,
    list_types,
    paste_bytes,
    paste_text,
)


@pytest.fixture(autouse=True)
def _reset_clipboard_cache():
    """Reset process-lifetime binary cache between tests."""
    clipboard_mod._wl_copy_path = None
    clipboard_mod._wl_paste_path = None
    clipboard_mod._availability_checked = False
    clipboard_mod._missing_warned = False
    yield
    clipboard_mod._wl_copy_path = None
    clipboard_mod._wl_paste_path = None
    clipboard_mod._availability_checked = False
    clipboard_mod._missing_warned = False


def _completed(
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_is_wl_clipboard_available_false_when_missing():
    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", return_value=None),
    ):
        assert is_wl_clipboard_available() is False
        assert has_primary_selection() is False


def test_is_wl_clipboard_available_true_when_both_present():
    def which(name: str):
        return f"/usr/bin/{name}" if name in ("wl-copy", "wl-paste") else None

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", side_effect=which),
    ):
        assert is_wl_clipboard_available() is True
        assert has_primary_selection() is True


def test_is_wl_clipboard_available_false_on_non_linux():
    with patch.object(clipboard_mod, "is_linux", return_value=False):
        assert is_wl_clipboard_available() is False
        assert copy_text("hi") is False
        assert paste_text() == ""
        assert list_types() == []
        assert paste_bytes("image/png") == b""
        assert copy_bytes(b"x", "image/png") is False
        assert copy_rich_text("<p>x</p>", "x") is False
        assert get_selected_text_wayland() == ""


def test_copy_text_invokes_wl_copy_without_primary_by_default():
    def which(name: str):
        return f"/usr/bin/{name}"

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", side_effect=which),
        patch.object(clipboard_mod.subprocess, "run", return_value=_completed()) as run,
    ):
        assert copy_text("hello") is True
        args = run.call_args[0][0]
        assert args[0] == "/usr/bin/wl-copy"
        assert "--primary" not in args
        assert run.call_args[1]["input"] == b"hello"


def test_copy_text_includes_primary_flag():
    def which(name: str):
        return f"/usr/bin/{name}"

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", side_effect=which),
        patch.object(clipboard_mod.subprocess, "run", return_value=_completed()) as run,
    ):
        assert copy_text("sel", primary=True) is True
        args = run.call_args[0][0]
        assert "--primary" in args
        assert run.call_args[1]["input"] == b"sel"


def test_paste_text_decodes_and_uses_no_newline():
    def which(name: str):
        return f"/usr/bin/{name}"

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", side_effect=which),
        patch.object(
            clipboard_mod.subprocess,
            "run",
            return_value=_completed(stdout="café".encode()),
        ) as run,
    ):
        assert paste_text() == "café"
        args = run.call_args[0][0]
        assert args[0] == "/usr/bin/wl-paste"
        assert "--no-newline" in args
        assert "--primary" not in args

        run.reset_mock()
        run.return_value = _completed(stdout=b"hello")
        assert paste_text(primary=True) == "hello"
        args = run.call_args[0][0]
        assert "--primary" in args
        assert "--no-newline" in args


def test_paste_text_empty_on_nonzero_exit():
    def which(name: str):
        return f"/usr/bin/{name}"

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", side_effect=which),
        patch.object(clipboard_mod.subprocess, "run", return_value=_completed(returncode=1)),
    ):
        assert paste_text() == ""
        assert paste_text(primary=True) == ""


def test_missing_binary_safe_failure_no_crash():
    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", return_value=None),
    ):
        assert copy_text("x") is False
        assert paste_text() == ""
        assert list_types() == []
        assert paste_bytes("text/plain") == b""
        assert copy_bytes(b"data", "image/png") is False
        assert copy_rich_text("<p>x</p>", "x") is False
        assert get_selected_text_wayland() == ""


def test_list_types_parses_lines():
    def which(name: str):
        return f"/usr/bin/{name}"

    out = b"text/plain;charset=utf-8\nimage/png\n\ntext/html\n"
    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", side_effect=which),
        patch.object(clipboard_mod.subprocess, "run", return_value=_completed(stdout=out)) as run,
    ):
        types = list_types(primary=True)
        assert types == ["text/plain;charset=utf-8", "image/png", "text/html"]
        args = run.call_args[0][0]
        assert "--list-types" in args
        assert "--primary" in args


def test_paste_bytes_and_copy_bytes_pass_mime():
    def which(name: str):
        return f"/usr/bin/{name}"

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", side_effect=which),
        patch.object(
            clipboard_mod.subprocess,
            "run",
            return_value=_completed(stdout=b"\x89PNG"),
        ) as run,
    ):
        assert paste_bytes("image/png") == b"\x89PNG"
        args = run.call_args[0][0]
        assert "--type" in args
        assert "image/png" in args

        run.return_value = _completed()
        assert copy_bytes(b"\x89PNG", "image/png", primary=False) is True
        args = run.call_args[0][0]
        assert args[0] == "/usr/bin/wl-copy"
        assert "--type" in args
        assert "image/png" in args
        assert run.call_args[1]["input"] == b"\x89PNG"


def test_copy_rich_text_offers_html_mime():
    def which(name: str):
        return f"/usr/bin/{name}"

    html = "<html><body><strong>café</strong></body></html>"
    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", side_effect=which),
        patch.object(clipboard_mod.subprocess, "run", return_value=_completed()) as run,
    ):
        assert copy_rich_text(html, "café") is True
        args = run.call_args[0][0]
        assert args[0] == "/usr/bin/wl-copy"
        assert "--type" in args
        assert "text/html" in args
        assert run.call_args[1]["input"] == html.encode("utf-8")


def test_copy_rich_text_rejects_empty_html():
    with patch.object(clipboard_mod, "is_linux", return_value=True):
        assert copy_rich_text("", "plain") is False


def test_get_selected_text_wayland_prefers_primary():
    def which(name: str):
        return f"/usr/bin/{name}"

    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        # Primary has content
        if "--primary" in args and "--list-types" not in args:
            return _completed(stdout=b"primary-selected")
        return _completed(stdout=b"clipboard-text")

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", side_effect=which),
        patch.object(clipboard_mod.subprocess, "run", side_effect=fake_run),
    ):
        assert get_selected_text_wayland() == "primary-selected"
        # First paste should be primary
        assert any("--primary" in c for c in calls)


def test_get_selected_text_wayland_falls_back_to_clipboard_when_primary_empty():
    def which(name: str):
        return f"/usr/bin/{name}"

    def fake_run(args, **kwargs):
        if "--primary" in args:
            return _completed(returncode=1, stdout=b"")
        return _completed(stdout=b"user-copied-text")

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", side_effect=which),
        patch.object(clipboard_mod.subprocess, "run", side_effect=fake_run),
    ):
        assert get_selected_text_wayland() == "user-copied-text"


def test_get_selected_text_wayland_returns_empty_when_both_empty():
    def which(name: str):
        return f"/usr/bin/{name}"

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", side_effect=which),
        patch.object(clipboard_mod.subprocess, "run", return_value=_completed(returncode=1)),
    ):
        assert get_selected_text_wayland() == ""


def test_copy_text_timeout_returns_false():
    def which(name: str):
        return f"/usr/bin/{name}"

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", side_effect=which),
        patch.object(
            clipboard_mod.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="wl-copy", timeout=3),
        ),
    ):
        assert copy_text("slow") is False


def test_timeout_passed_to_subprocess():
    def which(name: str):
        return f"/usr/bin/{name}"

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod.shutil, "which", side_effect=which),
        patch.object(clipboard_mod.subprocess, "run", return_value=_completed()) as run,
    ):
        copy_text("x")
        assert run.call_args[1]["timeout"] == clipboard_mod._DEFAULT_TIMEOUT
        assert run.call_args[1]["check"] is False
        # wl-copy must not capture pipes (forked server would hang otherwise)
        assert run.call_args[1]["stdout"] is subprocess.DEVNULL
        assert run.call_args[1]["stderr"] is subprocess.DEVNULL
