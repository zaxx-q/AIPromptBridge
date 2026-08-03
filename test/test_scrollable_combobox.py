"""Unit tests for ScrollableComboBox mousewheel scroll handling."""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from src.gui.custom_widgets import ScrollableComboBox
from src.gui.themes import CATPPUCCIN_DARK


@pytest.fixture
def dummy_colors():
    return CATPPUCCIN_DARK


def test_scrollable_combobox_mousewheel_open_dropdown(dummy_colors):
    """Test that _on_mousewheel scrolls dropdown text widget and returns 'break' when dropdown is open."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip("Tkinter TclError (no display available)")
        return

    try:
        combo = ScrollableComboBox(root, colors=dummy_colors, values=["item1", "item2", "item3", "item4", "item5"])
        combo._open_dropdown()

        assert combo._dropdown_open is True
        assert combo._text_widget is not None

        # Mock yview_scroll on text widget
        combo._text_widget.yview_scroll = MagicMock()

        # Simulate Linux scroll up (<Button-4>)
        event_btn4 = MagicMock()
        event_btn4.num = 4
        event_btn4.delta = 0
        res4 = combo._on_mousewheel(event_btn4)
        assert res4 == "break"
        combo._text_widget.yview_scroll.assert_called_with(-3, "units")

        # Simulate Linux scroll down (<Button-5>)
        event_btn5 = MagicMock()
        event_btn5.num = 5
        event_btn5.delta = 0
        res5 = combo._on_mousewheel(event_btn5)
        assert res5 == "break"
        combo._text_widget.yview_scroll.assert_called_with(3, "units")

        # Simulate Windows scroll down (<MouseWheel> delta=-120)
        event_win_down = MagicMock(spec=["delta"])
        event_win_down.delta = -120
        res_win = combo._on_mousewheel(event_win_down)
        assert res_win == "break"
        combo._text_widget.yview_scroll.assert_called_with(3, "units")

        combo._close_dropdown()
    finally:
        root.destroy()


def test_scrollable_combobox_mousewheel_closed_dropdown(dummy_colors):
    """Test that _on_mousewheel does not return 'break' when dropdown is closed."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip("Tkinter TclError (no display available)")
        return

    try:
        combo = ScrollableComboBox(root, colors=dummy_colors, values=["item1", "item2"])
        assert combo._dropdown_open is False

        event = MagicMock()
        event.num = 4
        event.delta = 0
        res = combo._on_mousewheel(event)
        assert res is None
    finally:
        root.destroy()
