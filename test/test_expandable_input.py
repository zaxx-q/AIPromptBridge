"""Unit tests for ExpandableInput component."""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from src.gui.custom_widgets import ExpandableInput
from src.gui.platform import HAVE_CTK
from src.gui.themes import CATPPUCCIN_DARK


@pytest.fixture
def dummy_colors():
    return CATPPUCCIN_DARK


def _create_root():
    try:
        root = tk.Tk()
        root.withdraw()
        return root
    except tk.TclError:
        pytest.skip("Tkinter TclError (no display available)")


@pytest.mark.parametrize("is_ctk", [True, False] if HAVE_CTK else [False])
def test_expandable_input_initial_state(is_ctk, dummy_colors):
    """Verify widget starts in single-line mode and get() returns empty string when only placeholder is shown."""
    root = _create_root()
    try:
        on_submit = MagicMock()
        on_expand = MagicMock()
        exp_input = ExpandableInput(
            root,
            placeholder="Test placeholder...",
            colors=dummy_colors,
            on_submit=on_submit,
            on_expand=on_expand,
            is_ctk=is_ctk,
        )

        assert exp_input.is_expanded is False
        assert exp_input.get() == ""
        assert exp_input.winfo_exists() is True

        exp_input.destroy()
    finally:
        root.destroy()


@pytest.mark.parametrize("is_ctk", [True, False] if HAVE_CTK else [False])
def test_expandable_input_preserves_text_on_expand(is_ctk, dummy_colors):
    """Verify single-line text is preserved when expanding to multi-line mode."""
    root = _create_root()
    try:
        on_submit = MagicMock()
        on_expand = MagicMock()
        exp_input = ExpandableInput(
            root,
            placeholder="Type here...",
            colors=dummy_colors,
            on_submit=on_submit,
            on_expand=on_expand,
            is_ctk=is_ctk,
        )

        # Set text in single-line mode
        exp_input.insert(0, "Custom prompt instructions")
        assert exp_input.get() == "Custom prompt instructions"

        # Expand to multi-line mode
        exp_input.expand()

        assert exp_input.is_expanded is True
        assert exp_input.get() == "Custom prompt instructions"
        on_expand.assert_called_once()

        exp_input.destroy()
    finally:
        root.destroy()


@pytest.mark.parametrize("is_ctk", [True, False] if HAVE_CTK else [False])
def test_expandable_input_multiline_support(is_ctk, dummy_colors):
    """Verify multi-line text input preserves inner newlines when expanded."""
    root = _create_root()
    try:
        on_submit = MagicMock()
        on_expand = MagicMock()
        exp_input = ExpandableInput(
            root,
            placeholder="Multi-line...",
            colors=dummy_colors,
            on_submit=on_submit,
            on_expand=on_expand,
            is_ctk=is_ctk,
        )

        exp_input.expand()
        assert exp_input.is_expanded is True

        multiline_text = "Line 1: Refactor this\nLine 2: Add tests\nLine 3: Update docs"
        exp_input.set_text(multiline_text)

        assert exp_input.get() == multiline_text

        exp_input.destroy()
    finally:
        root.destroy()


@pytest.mark.parametrize("is_ctk", [True, False] if HAVE_CTK else [False])
def test_expandable_input_keyboard_events_expanded(is_ctk, dummy_colors):
    """Verify Enter submits, Shift+Enter permits newlines, and Ctrl+Enter submits in expanded mode."""
    root = _create_root()
    try:
        on_submit = MagicMock()
        exp_input = ExpandableInput(
            root,
            placeholder="Enter test...",
            colors=dummy_colors,
            on_submit=on_submit,
            is_ctk=is_ctk,
        )
        exp_input.expand()

        # 1. Plain Enter (state = 0): should call on_submit and return "break"
        event_plain = MagicMock()
        event_plain.state = 0
        res_plain = exp_input._on_return_handler(event_plain)
        assert res_plain == "break"
        assert on_submit.call_count == 1

        # 2. Shift+Enter (state = 0x1): should NOT call on_submit and return None (allows newline)
        on_submit.reset_mock()
        event_shift = MagicMock()
        event_shift.state = 0x1
        res_shift = exp_input._on_return_handler(event_shift)
        assert res_shift is None
        assert on_submit.call_count == 0

        # 3. Ctrl+Enter (state = 0x4): should call on_submit and return "break"
        on_submit.reset_mock()
        event_ctrl = MagicMock()
        event_ctrl.state = 0x4
        res_ctrl = exp_input._on_ctrl_return_handler(event_ctrl)
        assert res_ctrl == "break"
        assert on_submit.call_count == 1

        exp_input.destroy()
    finally:
        root.destroy()


@pytest.mark.parametrize("is_ctk", [True, False] if HAVE_CTK else [False])
def test_expandable_input_double_click_triggers_expand(is_ctk, dummy_colors):
    """Verify double-click expands the widget from single-line to multi-line mode."""
    root = _create_root()
    try:
        on_expand = MagicMock()
        exp_input = ExpandableInput(
            root,
            placeholder="Double click me...",
            colors=dummy_colors,
            on_expand=on_expand,
            is_ctk=is_ctk,
        )

        assert exp_input.is_expanded is False

        # Simulate double click
        res = exp_input._on_double_click()
        assert res == "break"
        assert exp_input.is_expanded is True
        on_expand.assert_called_once()

        # Second double click when already expanded should return None (allowing text selection)
        res_second = exp_input._on_double_click()
        assert res_second is None

        exp_input.destroy()
    finally:
        root.destroy()


@pytest.mark.parametrize("is_ctk", [True, False] if HAVE_CTK else [False])
def test_expandable_input_focus_placeholder_toggle(is_ctk, dummy_colors):
    """Verify placeholder is cleared on focus in and restored on focus out if empty."""
    root = _create_root()
    try:
        exp_input = ExpandableInput(
            root,
            placeholder="Focus test...",
            colors=dummy_colors,
            is_ctk=is_ctk,
        )

        # In single line mode
        if not is_ctk:
            assert exp_input.entry.get() == "Focus test..."
            exp_input._on_entry_focus_in()
            assert exp_input.entry.get() == ""
            exp_input._on_entry_focus_out()
            assert exp_input.entry.get() == "Focus test..."

        # In expanded mode
        exp_input.expand()
        assert exp_input.is_expanded is True
        exp_input._on_tb_focus_in()
        assert exp_input.get() == ""

        # Typing something
        exp_input.insert(0, "Hello")
        assert exp_input.get() == "Hello"
        exp_input._on_tb_focus_out()
        assert exp_input.get() == "Hello"

        # Clearing and focus out restores placeholder
        exp_input.delete(0, "end")
        exp_input._on_tb_focus_out()
        assert exp_input.get() == ""
        assert exp_input._has_placeholder is True

        exp_input.destroy()
    finally:
        root.destroy()
