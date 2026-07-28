#!/usr/bin/env python3
"""Tests for Linux StatusNotifierItem tray helpers (no live host required)."""

from unittest.mock import MagicMock, patch

import pytest

from src.platform import status_notifier as sn


class TestStatusNotifierHelpers:
    def test_image_to_icon_pixmap_argb(self):
        from PIL import Image

        img = Image.new("RGBA", (8, 8), (10, 20, 30, 255))
        pixmaps = sn.image_to_icon_pixmap(img, sizes=(8,))
        assert len(pixmaps) == 1
        w, h, data = pixmaps[0]
        assert w == 8 and h == 8
        assert len(data) == 8 * 8 * 4
        # First pixel ARGB network order
        assert data[0:4] == bytes([255, 10, 20, 30])

    def test_is_status_notifier_available_matches_jeepney(self):
        assert sn.is_status_notifier_available() is (sn.is_linux() and sn.HAVE_JEEPNEY)

    def test_tray_menu_entry_defaults(self):
        entry = sn.TrayMenuEntry(label="Quit", callback=lambda: None, default=False)
        assert entry.label == "Quit"
        sep = sn.TrayMenuEntry(label=None)
        assert sep.label is None


class TestStatusNotifierIconUnit:
    def test_build_layout_includes_items_and_separators(self):
        if not sn.HAVE_JEEPNEY:
            pytest.skip("jeepney not installed")

        from PIL import Image

        img = Image.new("RGBA", (16, 16), (66, 133, 244, 255))
        calls = []
        menu = [
            sn.TrayMenuEntry(label="Session Browser", callback=lambda: calls.append("sb"), default=True),
            sn.TrayMenuEntry(label=None),
            sn.TrayMenuEntry(label="Quit", callback=lambda: calls.append("quit")),
        ]
        icon = sn.StatusNotifierIcon(image=img, menu=menu)
        rev, root = icon._build_layout()
        assert rev == 1
        root_id, root_props, children = root
        assert root_id == 0
        assert root_props["children-display"][1] == "submenu"
        assert len(children) == 3
        # children are variants ("(ia{sv}av)", struct)
        assert children[0][1][0] == 1
        assert children[0][1][1]["label"][1] == "Session Browser"
        assert children[1][1][1]["type"][1] == "separator"
        assert children[2][1][1]["label"][1] == "Quit"

    def test_update_menu_bumps_revision(self):
        if not sn.HAVE_JEEPNEY:
            pytest.skip("jeepney not installed")

        from PIL import Image

        img = Image.new("RGBA", (16, 16), (0, 0, 0, 255))
        icon = sn.StatusNotifierIcon(image=img, menu=[sn.TrayMenuEntry(label="A")])
        icon._conn = MagicMock()  # allow LayoutUpdated emit
        icon.update_menu([sn.TrayMenuEntry(label="B"), sn.TrayMenuEntry(label="C")])
        rev, root = icon._build_layout()
        assert rev == 2
        assert len(root[2]) == 2

    def test_handle_get_all_item_props(self):
        if not sn.HAVE_JEEPNEY:
            pytest.skip("jeepney not installed")

        from jeepney import DBusAddress, MessageType, new_method_call
        from PIL import Image

        img = Image.new("RGBA", (16, 16), (1, 2, 3, 255))
        icon = sn.StatusNotifierIcon(image=img, title="T", app_id="app")
        sent = []
        icon._conn = MagicMock()
        icon._conn.send = lambda m: sent.append(m)

        addr = DBusAddress(sn.ITEM_PATH, bus_name=":1.0", interface=sn.IFACE_PROPS)
        msg = new_method_call(addr, "GetAll", "s", (sn.IFACE_ITEM,))
        icon._handle(msg)
        assert sent, "expected a reply"
        reply = sent[0]
        assert reply.header.message_type == MessageType.method_return
        props = reply.body[0]
        assert props["Title"][1] == "T"
        assert props["Id"][1] == "app"
        assert props["Menu"][1] == sn.MENU_PATH
        assert props["ItemIsMenu"][1] is True


class TestTrayAppSniIntegration:
    def test_build_sni_menu_hides_console_and_adds_quit(self):
        from src.tray import TrayApp

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
            patch("src.tray.HAVE_STATUS_NOTIFIER", True),
        ):
            tray = TrayApp(allow_console_toggle=True)
            if tray._build_sni_menu_entries is None:
                pytest.skip("SNI menu builder unavailable")
            entries = tray._build_sni_menu_entries()
            labels = [e.label for e in entries]
            assert None in labels  # separators
            assert "Quit" in labels
            assert not any(l and "Toggle Console" in l for l in labels)
            assert any(l and "Session Browser" in l for l in labels)
            assert any(l and "Screen Snip" in l for l in labels)
            assert any(e.default for e in entries if e.label and "Session Browser" in e.label)

    def test_update_tray_menu_sni(self):
        from src.tray import TrayApp

        config_mock = {
            "text_edit_tool_enabled": True,
            "screen_snip_enabled": False,
            "audio_tool_enabled": False,
            "tts_enabled": False,
        }
        mock_sni = MagicMock()
        with (
            patch("src.tray.is_windows", return_value=False),
            patch("src.tray.is_linux", return_value=True),
            patch("src.web_server.CONFIG", config_mock),
            patch("src.tray.HAVE_SYSTRAY", True),
            patch("src.tray.HAVE_STATUS_NOTIFIER", True),
            patch("src.tray.TrayMenuEntry", sn.TrayMenuEntry),
        ):
            tray = TrayApp(allow_console_toggle=False)
            tray._sni_icon = mock_sni
            tray.update_tray_menu()
            assert mock_sni.update_menu.called
