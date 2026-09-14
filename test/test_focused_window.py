"""Unit tests for focused window terminal detection (mocked — no compositor)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.platform import focused_window as fw_mod


@pytest.fixture(autouse=True)
def _reset_user_ids():
    """Reset user terminal IDs between tests."""
    fw_mod._user_terminal_ids = set()
    yield
    fw_mod._user_terminal_ids = set()


# ── _is_known_terminal ─────────────────────────────────────────────────


class TestIsKnownTerminal:
    def test_common_terminals(self):
        for app_id in ("foot", "kitty", "alacritty", "ghostty", "wezterm", "konsole"):
            assert fw_mod._is_known_terminal(app_id), f"{app_id} should be detected as terminal"

    def test_case_insensitive(self):
        assert fw_mod._is_known_terminal("Foot")
        assert fw_mod._is_known_terminal("KITTY")
        assert fw_mod._is_known_terminal("Alacritty")

    def test_non_terminal(self):
        assert not fw_mod._is_known_terminal("firefox")
        assert not fw_mod._is_known_terminal("zen")
        assert not fw_mod._is_known_terminal("code")

    def test_reverse_dns_last_segment(self):
        """Reverse-DNS app_ids match via their last segment."""
        assert fw_mod._is_known_terminal("com.mitchellh.ghostty")
        assert fw_mod._is_known_terminal("org.codeberg.dnkl.foot")
        assert fw_mod._is_known_terminal("com.example.kitty")
        # Non-terminal reverse-DNS should not match
        assert not fw_mod._is_known_terminal("org.mozilla.firefox")
        assert not fw_mod._is_known_terminal("com.google.chrome")

    def test_user_overrides(self):
        assert not fw_mod._is_known_terminal("my-custom-term")
        fw_mod.set_user_terminal_ids(["my-custom-term"])
        assert fw_mod._is_known_terminal("my-custom-term")

    def test_user_overrides_case_insensitive(self):
        fw_mod.set_user_terminal_ids(["MyTerm"])
        assert fw_mod._is_known_terminal("myterm")
        assert fw_mod._is_known_terminal("MYTERM")

    def test_user_overrides_empty_and_none(self):
        fw_mod.set_user_terminal_ids(None)
        assert fw_mod._user_terminal_ids == set()
        fw_mod.set_user_terminal_ids(["", "  ", "valid-term"])
        assert "valid-term" in fw_mod._user_terminal_ids
        assert "" not in fw_mod._user_terminal_ids

    def test_windows_terminals(self):
        for app_id in ("windowsterminal", "cmd", "powershell", "pwsh", "conhost", "wt"):
            assert fw_mod._is_known_terminal(app_id), f"{app_id} should be detected as terminal"

    def test_gnome_terminals(self):
        for app_id in ("org.gnome.terminal", "org.gnome.console", "kgx", "org.gnome.ptyxis"):
            assert fw_mod._is_known_terminal(app_id), f"{app_id} should be detected as terminal"


# ── Niri focused window ───────────────────────────────────────────────


class TestNiriFocusedAppId:
    def test_niri_returns_app_id(self):
        niri_output = json.dumps({"app_id": "foot", "title": "zsh", "is_focused": True})
        with (
            patch.dict("os.environ", {"NIRI_SOCKET": "/run/niri.sock"}),
            patch("shutil.which", return_value="/usr/bin/niri"),
            patch.object(fw_mod, "_run_command", return_value=niri_output),
        ):
            assert fw_mod._get_niri_focused_app_id() == "foot"

    def test_niri_returns_none_when_no_socket(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(fw_mod, "_desktop_names", return_value=set()),
        ):
            assert fw_mod._get_niri_focused_app_id() is None

    def test_niri_returns_none_on_empty_output(self):
        with (
            patch.dict("os.environ", {"NIRI_SOCKET": "/run/niri.sock"}),
            patch("shutil.which", return_value="/usr/bin/niri"),
            patch.object(fw_mod, "_run_command", return_value=None),
        ):
            assert fw_mod._get_niri_focused_app_id() is None


# ── Sway focused window ──────────────────────────────────────────────


class TestSwayFocusedAppId:
    def test_sway_finds_focused_leaf(self):
        tree = {
            "nodes": [
                {
                    "nodes": [
                        {"app_id": "kitty", "focused": True},
                    ]
                }
            ]
        }
        with (
            patch.dict("os.environ", {"SWAYSOCK": "/run/sway.sock"}),
            patch("shutil.which", return_value="/usr/bin/swaymsg"),
            patch.object(fw_mod, "_run_command", return_value=json.dumps(tree)),
        ):
            assert fw_mod._get_sway_focused_app_id() == "kitty"

    def test_sway_returns_none_when_no_socket(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(fw_mod, "_desktop_names", return_value=set()),
        ):
            assert fw_mod._get_sway_focused_app_id() is None


# ── Hyprland focused window ──────────────────────────────────────────


class TestHyprlandFocusedAppId:
    def test_hyprland_returns_class(self):
        output = json.dumps({"class": "Alacritty", "title": "zsh"})
        with (
            patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "abc123"}),
            patch("shutil.which", return_value="/usr/bin/hyprctl"),
            patch.object(fw_mod, "_run_command", return_value=output),
        ):
            assert fw_mod._get_hyprland_focused_app_id() == "Alacritty"

    def test_hyprland_returns_none_when_no_env(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(fw_mod, "_desktop_names", return_value=set()),
        ):
            assert fw_mod._get_hyprland_focused_app_id() is None


# ── is_focused_app_terminal integration ──────────────────────────────


class TestIsFocusedAppTerminal:
    def test_terminal_detected_on_linux(self):
        with (
            patch.object(fw_mod, "is_linux", return_value=True),
            patch.object(fw_mod, "is_wayland", return_value=True),
            patch.object(fw_mod, "is_windows", return_value=False),
            patch.object(fw_mod, "_get_niri_focused_app_id", return_value="foot"),
        ):
            assert fw_mod.is_focused_app_terminal() is True

    def test_non_terminal_detected_on_linux(self):
        with (
            patch.object(fw_mod, "is_linux", return_value=True),
            patch.object(fw_mod, "is_wayland", return_value=True),
            patch.object(fw_mod, "is_windows", return_value=False),
            patch.object(fw_mod, "_get_niri_focused_app_id", return_value="firefox"),
            patch.object(fw_mod, "_get_sway_focused_app_id", return_value=None),
            patch.object(fw_mod, "_get_hyprland_focused_app_id", return_value=None),
        ):
            assert fw_mod.is_focused_app_terminal() is False

    def test_detection_unavailable_returns_false(self):
        with (
            patch.object(fw_mod, "is_linux", return_value=True),
            patch.object(fw_mod, "is_wayland", return_value=True),
            patch.object(fw_mod, "is_windows", return_value=False),
            patch.object(fw_mod, "_get_niri_focused_app_id", return_value=None),
            patch.object(fw_mod, "_get_sway_focused_app_id", return_value=None),
            patch.object(fw_mod, "_get_hyprland_focused_app_id", return_value=None),
        ):
            assert fw_mod.is_focused_app_terminal() is False

    def test_windows_terminal_detected(self):
        with (
            patch.object(fw_mod, "is_linux", return_value=False),
            patch.object(fw_mod, "is_wayland", return_value=False),
            patch.object(fw_mod, "is_windows", return_value=True),
            patch.object(fw_mod, "_get_windows_focused_process_name", return_value="windowsterminal"),
        ):
            assert fw_mod.is_focused_app_terminal() is True

    def test_windows_non_terminal(self):
        with (
            patch.object(fw_mod, "is_linux", return_value=False),
            patch.object(fw_mod, "is_wayland", return_value=False),
            patch.object(fw_mod, "is_windows", return_value=True),
            patch.object(fw_mod, "_get_windows_focused_process_name", return_value="chrome"),
        ):
            assert fw_mod.is_focused_app_terminal() is False
