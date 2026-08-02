"""Unit tests for Wayland hybrid selection capture (mocked — no compositor)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.platform import clipboard as clipboard_mod
from src.platform.clipboard import capture_selection_for_textedit, capture_selection_hybrid, get_selected_text_wayland


@pytest.fixture(autouse=True)
def _reset_clipboard_cache():
    """Reset process-lifetime binary cache and hybrid warn flags between tests."""
    clipboard_mod._wl_copy_path = None
    clipboard_mod._wl_paste_path = None
    clipboard_mod._availability_checked = False
    clipboard_mod._missing_warned = False
    clipboard_mod._hybrid_wlrctl_missing_warned = False
    clipboard_mod._hybrid_fail_warned = False
    yield
    clipboard_mod._wl_copy_path = None
    clipboard_mod._wl_paste_path = None
    clipboard_mod._availability_checked = False
    clipboard_mod._missing_warned = False
    clipboard_mod._hybrid_wlrctl_missing_warned = False
    clipboard_mod._hybrid_fail_warned = False


def test_hybrid_returns_primary_without_ctrl_c():
    """Primary non-empty → never injects Ctrl+C."""
    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod, "get_selected_text_wayland", return_value="primary-text") as mock_get,
        patch("src.platform.input.copy_via_clipboard_shortcut") as mock_copy,
        patch("src.platform.input.is_wlrctl_available", return_value=True),
    ):
        result = capture_selection_hybrid()
        assert result == "primary-text"
        mock_get.assert_called_once()
        mock_copy.assert_not_called()


def test_hybrid_returns_readonly_clipboard_without_ctrl_c():
    """Primary empty but clipboard has text → no Ctrl+C."""
    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod, "get_selected_text_wayland", return_value="already-copied"),
        patch("src.platform.input.copy_via_clipboard_shortcut") as mock_copy,
    ):
        result = capture_selection_hybrid()
        assert result == "already-copied"
        mock_copy.assert_not_called()


def test_hybrid_ctrl_c_path_captures_and_restores():
    """Primary empty, clipboard empty → Ctrl+C, poll new text, restore backup."""
    # paste_text sequence:
    # 1) get_selected_text_wayland uses paste (mocked away via get_selected_text_wayland)
    # Inside _capture_via_ctrl_c:
    # - backup = paste_text() → ""
    # - after Ctrl+C, poll paste_text() → "keyboard-selected"
    # - finally copy_text(backup)
    paste_calls = {"n": 0}

    def fake_paste(*, primary: bool = False) -> str:
        paste_calls["n"] += 1
        # First call is backup; subsequent polls return captured text
        if paste_calls["n"] == 1:
            return ""
        return "keyboard-selected"

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod, "get_selected_text_wayland", return_value=""),
        patch.object(clipboard_mod, "paste_text", side_effect=fake_paste),
        patch.object(clipboard_mod, "copy_text", return_value=True) as mock_restore,
        patch("src.platform.input.is_wlrctl_available", return_value=True),
        patch("src.platform.input.copy_via_clipboard_shortcut", return_value=True) as mock_ctrl_c,
        patch.object(clipboard_mod.time, "sleep"),  # speed up poll loop
    ):
        result = capture_selection_hybrid(timeout=0.05, poll_interval=0.001)
        assert result == "keyboard-selected"
        mock_ctrl_c.assert_called()
        # Restore called with empty backup
        mock_restore.assert_called()
        assert mock_restore.call_args[0][0] == ""


def test_hybrid_ctrl_c_detects_change_from_nonempty_backup():
    """When clipboard had prior content, only accept different text after Ctrl+C."""
    paste_seq = iter(["prior-clipboard", "prior-clipboard", "new-selection"])

    def fake_paste(*, primary: bool = False) -> str:
        try:
            return next(paste_seq)
        except StopIteration:
            return "new-selection"

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod, "get_selected_text_wayland", return_value=""),
        patch.object(clipboard_mod, "paste_text", side_effect=fake_paste),
        patch.object(clipboard_mod, "copy_text", return_value=True) as mock_restore,
        patch("src.platform.input.is_wlrctl_available", return_value=True),
        patch("src.platform.input.copy_via_clipboard_shortcut", return_value=True),
        patch.object(clipboard_mod.time, "sleep"),
    ):
        result = capture_selection_hybrid(timeout=0.1, poll_interval=0.001)
        assert result == "new-selection"
        # Restore original clipboard content
        assert mock_restore.call_args[0][0] == "prior-clipboard"


def test_hybrid_wlrctl_missing_returns_empty_no_crash():
    """wlrctl missing → empty string, no exception."""
    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod, "get_selected_text_wayland", return_value=""),
        patch("src.platform.input.is_wlrctl_available", return_value=False),
        patch("src.platform.input.copy_via_clipboard_shortcut") as mock_copy,
    ):
        result = capture_selection_hybrid()
        assert result == ""
        mock_copy.assert_not_called()


def test_hybrid_ctrl_c_inject_failure_returns_empty_and_restores():
    """Ctrl+C inject fails → empty, still restores clipboard."""
    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod, "get_selected_text_wayland", return_value=""),
        patch.object(clipboard_mod, "paste_text", return_value="backup-data"),
        patch.object(clipboard_mod, "copy_text", return_value=True) as mock_restore,
        patch("src.platform.input.is_wlrctl_available", return_value=True),
        patch("src.platform.input.copy_via_clipboard_shortcut", return_value=False),
    ):
        result = capture_selection_hybrid()
        assert result == ""
        mock_restore.assert_called_with("backup-data")


def test_hybrid_allow_ctrl_c_false_skips_inject():
    """allow_ctrl_c=False → same as read-only get_selected_text_wayland."""
    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod, "get_selected_text_wayland", return_value="") as mock_get,
        patch("src.platform.input.copy_via_clipboard_shortcut") as mock_copy,
    ):
        result = capture_selection_hybrid(allow_ctrl_c=False)
        assert result == ""
        mock_get.assert_called_once()
        mock_copy.assert_not_called()


def test_textedit_capture_excludes_regular_clipboard_fallback():
    """TextEdit does not mistake unrelated copied text for a live selection."""
    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod, "get_selected_text_wayland", return_value="") as mock_get,
        patch("src.platform.input.is_wlrctl_available", return_value=False),
    ):
        assert capture_selection_for_textedit() == ""

    mock_get.assert_called_once_with(include_clipboard=False)


def test_hybrid_non_linux_returns_empty():
    with patch.object(clipboard_mod, "is_linux", return_value=False):
        assert capture_selection_hybrid() == ""


def test_hybrid_resend_after_sends_ctrl_c_twice():
    """Slow-app path re-sends Ctrl+C once after resend_after."""
    # Stay empty until after the resend has fired, then yield text.
    ctrl_c_count = {"n": 0}
    paste_after_resend = {"ready": False}

    def fake_ctrl_c() -> bool:
        ctrl_c_count["n"] += 1
        # Second call is the mid-poll resend
        if ctrl_c_count["n"] >= 2:
            paste_after_resend["ready"] = True
        return True

    def fake_paste(*, primary: bool = False) -> str:
        if paste_after_resend["ready"]:
            return "late-text"
        return ""

    # Make time advance so resend_after triggers before timeout
    t = {"now": 0.0}

    def fake_time():
        return t["now"]

    def fake_sleep(dt):
        t["now"] += max(dt, 0.05)

    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod, "get_selected_text_wayland", return_value=""),
        patch.object(clipboard_mod, "paste_text", side_effect=fake_paste),
        patch.object(clipboard_mod, "copy_text", return_value=True),
        patch("src.platform.input.is_wlrctl_available", return_value=True),
        patch("src.platform.input.copy_via_clipboard_shortcut", side_effect=fake_ctrl_c),
        patch.object(clipboard_mod.time, "time", side_effect=fake_time),
        patch.object(clipboard_mod.time, "sleep", side_effect=fake_sleep),
    ):
        result = capture_selection_hybrid(
            timeout=1.0,
            poll_interval=0.15,
            resend_after=0.25,
        )
        assert result == "late-text"
        # Initial + one resend
        assert ctrl_c_count["n"] >= 2


def test_get_selected_text_wayland_still_read_only():
    """Existing helper must not gain Ctrl+C side effects."""
    with (
        patch.object(clipboard_mod, "is_linux", return_value=True),
        patch.object(clipboard_mod, "paste_text", side_effect=lambda primary=False: ""),
        patch("src.platform.input.copy_via_clipboard_shortcut") as mock_copy,
    ):
        assert get_selected_text_wayland() == ""
        mock_copy.assert_not_called()


# ── play_sound Linux path ──────────────────────────────────────────────────


def test_play_sound_linux_uses_paplay():
    from pathlib import Path

    from src import utils as utils_mod

    fake_path = MagicMock(spec=Path)
    fake_path.exists.return_value = True
    fake_path.__str__ = lambda self: "/tmp/snip.wav"  # type: ignore[method-assign]

    with (
        patch.object(utils_mod, "_resolve_sound_path", return_value=fake_path),
        patch.object(utils_mod.sys, "platform", "linux"),
        patch("shutil.which", side_effect=lambda n: "/usr/bin/paplay" if n == "paplay" else None),
        patch("subprocess.Popen") as mock_popen,
    ):
        assert utils_mod.play_sound("assets/snip.wav", async_play=True) is True
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "/usr/bin/paplay"
        assert cmd[1] == "/tmp/snip.wav"


def test_play_sound_linux_falls_back_to_ffplay():
    from pathlib import Path

    from src import utils as utils_mod

    fake_path = MagicMock(spec=Path)
    fake_path.exists.return_value = True
    fake_path.__str__ = lambda self: "/tmp/snip.wav"  # type: ignore[method-assign]

    def which(name: str):
        if name == "ffplay":
            return "/usr/bin/ffplay"
        return None

    with (
        patch.object(utils_mod, "_resolve_sound_path", return_value=fake_path),
        patch.object(utils_mod.sys, "platform", "linux"),
        patch("shutil.which", side_effect=which),
        patch("subprocess.Popen") as mock_popen,
    ):
        assert utils_mod.play_sound("assets/snip.wav") is True
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "/usr/bin/ffplay"
        assert "-nodisp" in cmd
        assert "-autoexit" in cmd


def test_play_sound_linux_no_player_returns_false():
    from pathlib import Path

    from src import utils as utils_mod

    fake_path = MagicMock(spec=Path)
    fake_path.exists.return_value = True
    fake_path.__str__ = lambda self: "/tmp/snip.wav"  # type: ignore[method-assign]

    with (
        patch.object(utils_mod, "_resolve_sound_path", return_value=fake_path),
        patch.object(utils_mod.sys, "platform", "linux"),
        patch("shutil.which", return_value=None),
        patch("subprocess.Popen") as mock_popen,
    ):
        assert utils_mod.play_sound("assets/snip.wav") is False
        mock_popen.assert_not_called()
