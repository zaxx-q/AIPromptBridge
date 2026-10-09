#!/usr/bin/env python3
"""Tests for high-DPI window centering, onboarding wizard geometry, and snip overlay configuration."""

from unittest.mock import MagicMock, patch

from src.gui.windows.utils import center_window


class TestCenterWindowDpi:
    """Test center_window DPI awareness and screen clamping."""

    def test_center_window_scale_1_0(self):
        """Standard 100% scale (scale=1.0) on 1920x1080 screen."""
        mock_win = MagicMock()
        mock_win.winfo_screenwidth.return_value = 1920
        mock_win.winfo_screenheight.return_value = 1080
        mock_win._get_window_scaling.return_value = 1.0

        w, h = center_window(mock_win, 720, 560)
        assert w == 720
        assert h == 560
        # Expected: x = (1920 - 720) // 2 = 600, y = (1080 - 560) // 2 = 260
        mock_win.geometry.assert_called_with("720x560+600+260")

    def test_center_window_scale_1_5_on_900p(self):
        """150% display scaling on 1600x900 screen (logical 1066x600)."""
        mock_win = MagicMock()
        mock_win.winfo_screenwidth.return_value = 1600
        mock_win.winfo_screenheight.return_value = 900
        mock_win._get_window_scaling.return_value = 1.5

        w, h = center_window(mock_win, 720, 560)
        # Logical screen: w = 1600 // 1.5 = 1066, h = 900 // 1.5 = 600
        # max_w = int(1066 * 0.92) = 980
        # max_h = int(600 * 0.88) = 528
        assert w == 720
        assert h == 528  # Bounded to 88% of logical height so Next button is not cut off!
        # x = (1066 - 720) // 2 = 173
        # y = (600 - 528) // 2 = 36
        mock_win.geometry.assert_called_with("720x528+173+36")

    def test_center_window_scale_1_5_on_1080p(self):
        """150% display scaling on 1920x1080 screen (logical 1280x720)."""
        mock_win = MagicMock()
        mock_win.winfo_screenwidth.return_value = 1920
        mock_win.winfo_screenheight.return_value = 1080
        mock_win._get_window_scaling.return_value = 1.5

        w, h = center_window(mock_win, 720, 560)
        # Logical screen: w = 1920 // 1.5 = 1280, h = 1080 // 1.5 = 720
        # max_w = int(1280 * 0.92) = 1177
        # max_h = int(720 * 0.88) = 633
        assert w == 720
        assert h == 560
        # x = (1280 - 720) // 2 = 280
        # y = (720 - 560) // 2 = 80
        mock_win.geometry.assert_called_with("720x560+280+80")

    def test_center_window_fallback_tk(self):
        """Standard Tk (no _get_window_scaling attribute)."""
        mock_win = MagicMock(spec=["update_idletasks", "winfo_screenwidth", "winfo_screenheight", "geometry"])
        mock_win.winfo_screenwidth.return_value = 1600
        mock_win.winfo_screenheight.return_value = 900

        w, h = center_window(mock_win, 720, 560)
        assert w == 720
        assert h == 560
        # x = (1600 - 720) // 2 = 440, y = (900 - 560) // 2 = 170
        mock_win.geometry.assert_called_with("720x560+440+170")


class TestScreenSnipOverlayDpi:
    """Test screen snip overlay avoids Tk -fullscreen bug and uses proper borderless geometry."""

    @patch("src.gui.screen_snip.ImageGrab.grab")
    @patch("src.gui.screen_snip.tk.Toplevel")
    @patch("src.gui.screen_snip.tk.Canvas")
    @patch("src.gui.screen_snip.ImageTk.PhotoImage")
    def test_screen_snip_overlay_window_setup(self, mock_photo, mock_canvas_cls, mock_toplevel_cls, mock_grab):
        """Verify overlay uses overrideredirect without -fullscreen attribute."""
        from PIL import Image

        from src.gui.screen_snip import ScreenSnipOverlay

        mock_img = Image.new("RGB", (1600, 900))
        mock_grab.return_value = mock_img

        mock_root = MagicMock()
        mock_toplevel_cls.return_value = mock_root
        mock_canvas = MagicMock()
        mock_canvas_cls.return_value = mock_canvas

        parent_root = MagicMock()

        overlay = ScreenSnipOverlay(parent_root, on_capture=MagicMock(), on_cancel=MagicMock())

        # overrideredirect must be True
        mock_root.overrideredirect.assert_called_with(True)

        # attributes("-fullscreen", True) must NOT have been called
        for call_args in mock_root.attributes.call_args_list:
            assert "-fullscreen" not in call_args[0]

        # topmost must be set
        mock_root.attributes.assert_any_call("-topmost", True)

        # Geometry must contain 1600x900
        geom_call = mock_root.geometry.call_args[0][0]
        assert "1600x900" in geom_call

        overlay._close()


class TestPopupDpi:
    """Test popup placement uses the full Windows virtual desktop."""

    @patch("ctypes.windll", create=True)
    @patch("src.gui.popups.sys.platform", "win32")
    def test_popup_clamping_allows_negative_monitor_coordinates(self, mock_windll):
        from src.gui.popups import _clamp_popup_position

        user32 = mock_windll.user32
        user32.GetSystemMetrics.side_effect = [-1920, -200, 3840, 1200]

        root = MagicMock()
        assert _clamp_popup_position(root, 1900, 900, 400, 300) == (1510, 690)

    @patch("ctypes.windll", create=True)
    @patch("src.gui.popups.sys.platform", "win32")
    def test_popup_position_uses_native_physical_coordinates(self, mock_windll):
        from src.gui.popups import _place_popup_window

        root = MagicMock()
        root.winfo_id.return_value = 123
        mock_windll.user32.GetParent.return_value = 456

        _place_popup_window(root, 1400, 800)

        root.geometry.assert_called_once_with("+1400+800")
        mock_windll.user32.SetWindowPos.assert_called_once_with(456, 0, 1400, 800, 0, 0, 0x0015)
