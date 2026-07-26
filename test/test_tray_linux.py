#!/usr/bin/env python3
"""Tests for Linux pystray tray backend helpers and menu construction."""

from unittest.mock import MagicMock, patch

import pytest

from src.tray import (
    HAVE_INFI_SYSTRAY,
    HAVE_PYSTRAY,
    HAVE_SYSTRAY,
    TrayApp,
    load_tray_image,
)


class TestTrayAvailability:
    def test_have_systray_matches_platform_backend(self):
        """HAVE_SYSTRAY is True only when the OS-specific backend is importable."""
        from src.platform.detect import is_linux, is_windows

        if is_linux():
            assert HAVE_SYSTRAY is HAVE_PYSTRAY
            # Windows-only package should not force HAVE_SYSTRAY on Linux
            if not HAVE_INFI_SYSTRAY:
                assert HAVE_SYSTRAY is HAVE_PYSTRAY
        elif is_windows():
            assert HAVE_SYSTRAY is HAVE_INFI_SYSTRAY
        else:
            assert HAVE_SYSTRAY is False

    def test_load_tray_image_fallback_without_path(self):
        image = load_tray_image(None)
        assert image.mode == "RGBA"
        assert image.size[0] <= 64
        assert image.size[1] <= 64

    def test_load_tray_image_from_icon_ico(self):
        from pathlib import Path

        icon = Path(__file__).resolve().parent.parent / "icon.ico"
        if not icon.exists():
            pytest.skip("icon.ico not present")
        image = load_tray_image(str(icon))
        assert image.mode == "RGBA"
        assert max(image.size) <= 64

    def test_load_tray_image_missing_file_falls_back(self):
        image = load_tray_image("/nonexistent/path/icon.ico")
        assert image.mode == "RGBA"


class TestTrayMenuLinux:
    def test_console_toggle_hidden_on_linux(self):
        config_mock = {
            "text_edit_tool_enabled": True,
            "screen_snip_enabled": True,
            "audio_tool_enabled": True,
            "tts_enabled": True,
        }
        with (
            patch("src.tray.is_windows", return_value=False),
            patch("src.tray.is_linux", return_value=True),
            patch("src.web_server.CONFIG", config_mock),
            patch("src.tray.HAVE_SYSTRAY", True),
        ):
            tray = TrayApp(allow_console_toggle=True)
            assert tray.allow_console_toggle is False
            opts = tray.build_menu_options()
            names = [o[0] for o in opts]
            assert not any("Toggle Console" in n for n in names)
            assert any("Session Browser" in n for n in names)
            assert any("Screen Snip" in n for n in names)
            assert any("Settings" in n for n in names)

    def test_tool_toggles_affect_menu_items(self):
        config_mock = {
            "text_edit_tool_enabled": False,
            "screen_snip_enabled": True,
            "audio_tool_enabled": False,
            "tts_enabled": True,
        }
        with (
            patch("src.tray.is_windows", return_value=False),
            patch("src.tray.is_linux", return_value=True),
            patch("src.web_server.CONFIG", config_mock),
            patch("src.tray.HAVE_SYSTRAY", True),
        ):
            tray = TrayApp(allow_console_toggle=False)
            opts = tray.build_menu_options()
            names = [o[0] for o in opts]
            assert not any("Direct Chat" in n for n in names)
            assert any("Snip" in n for n in names)
            assert not any("Audio Analyzer" in n for n in names)
            assert any("TTS" in n for n in names)

    def test_build_pystray_menu_includes_quit_and_default(self):
        if not HAVE_PYSTRAY:
            pytest.skip("pystray not installed")

        config_mock = {
            "text_edit_tool_enabled": True,
            "screen_snip_enabled": True,
            "audio_tool_enabled": False,
            "tts_enabled": False,
        }
        with (
            patch("src.tray.is_windows", return_value=False),
            patch("src.tray.is_linux", return_value=True),
            patch("src.web_server.CONFIG", config_mock),
            patch("src.tray.HAVE_SYSTRAY", True),
            patch("src.tray.HAVE_PYSTRAY", True),
        ):
            tray = TrayApp(allow_console_toggle=False)
            menu = tray._build_pystray_menu()
            texts = []
            default_texts = []
            for item in menu:
                try:
                    text = item.text
                    if callable(text):
                        text = text(item)
                except Exception:
                    continue
                if not text or text.startswith("-"):
                    continue
                texts.append(text)
                default = item.default
                if callable(default):
                    default = default(item)
                if default:
                    default_texts.append(text)

            assert any("Session Browser" in t for t in texts)
            assert any("Screen Snip" in t for t in texts)
            assert any("Quit" in t for t in texts)
            assert not any("Toggle Console" in t for t in texts)
            assert any("Session Browser" in t for t in default_texts)

    def test_update_tray_menu_pystray(self):
        if not HAVE_PYSTRAY:
            pytest.skip("pystray not installed")

        config_mock = {
            "text_edit_tool_enabled": True,
            "screen_snip_enabled": False,
            "audio_tool_enabled": False,
            "tts_enabled": False,
        }
        mock_icon = MagicMock()
        with (
            patch("src.tray.is_windows", return_value=False),
            patch("src.tray.is_linux", return_value=True),
            patch("src.web_server.CONFIG", config_mock),
            patch("src.tray.HAVE_SYSTRAY", True),
            patch("src.tray.HAVE_PYSTRAY", True),
        ):
            tray = TrayApp(allow_console_toggle=False)
            tray._pystray_icon = mock_icon
            tray.update_tray_menu()
            assert mock_icon.update_menu.called
            assert mock_icon.menu is not None

    def test_start_linux_constructs_icon_without_run_blocking(self):
        if not HAVE_PYSTRAY:
            pytest.skip("pystray not installed")

        config_mock = {
            "text_edit_tool_enabled": True,
            "screen_snip_enabled": True,
            "audio_tool_enabled": True,
            "tts_enabled": True,
        }
        mock_icon_instance = MagicMock()
        mock_icon_cls = MagicMock(return_value=mock_icon_instance)

        with (
            patch("src.tray.is_windows", return_value=False),
            patch("src.tray.is_linux", return_value=True),
            patch("src.tray.HAVE_SYSTRAY", True),
            patch("src.tray.HAVE_INFI_SYSTRAY", False),
            patch("src.tray.HAVE_PYSTRAY", True),
            patch("src.tray.PystrayIcon", mock_icon_cls),
            patch("src.web_server.CONFIG", config_mock),
            patch("src.tray.subscribe_config_change", create=True),
            patch("src.config.subscribe_config_change"),
        ):
            tray = TrayApp(allow_console_toggle=True, show_edit_file_items=False)
            result = tray.start(hide_console_on_start=False)
            assert result is True
            mock_icon_cls.assert_called_once()
            call_kwargs = mock_icon_cls.call_args
            # Icon(name, image, title, menu) — positional
            args = call_kwargs[0]
            assert args[0] == "aipromptbridge"
            assert args[2] == "AIPromptBridge"
            mock_icon_instance.run.assert_called_once()
