#!/usr/bin/env python3
"""
Widgets and form field helpers for Settings Window.

Provides:
    ToggleSwitch: Custom Tk canvas toggle switch widget (non-CTk fallback).
    FormFieldsMixin: Mixin providing standardized form field methods with
                     uniform layout constants for consistent UI across all tabs.

Layout Constants:
    LABEL_WIDTH: Standard label width (200px)
    ENTRY_WIDTH_SM/MD/LG: Entry field sizes (100/200/350px)
    DROPDOWN_WIDTH_SM/MD/LG: Dropdown sizes (140/200/300px)
"""

import tkinter as tk
from typing import Any, Callable, List, Optional

from ...custom_widgets import ScrollableComboBox
from ...platform import HAVE_CTK, ctk
from ...themes import (
    ThemeColors,
    get_ctk_combobox_colors,
    get_ctk_entry_colors,
    get_ctk_font,
    get_ctk_label_colors,
)

# =============================================================================
# Layout Constants — used by all tab mixins for uniform appearance
# =============================================================================

LABEL_WIDTH = 200  # All labels same width for alignment
ENTRY_WIDTH_SM = 100  # Small: ports, numbers, short values
ENTRY_WIDTH_MD = 200  # Medium: hotkeys, colors, short strings
ENTRY_WIDTH_LG = 350  # Large: URLs, paths, model names
DROPDOWN_WIDTH_SM = 140  # Small: 2-3 short options
DROPDOWN_WIDTH_MD = 200  # Medium: provider names, formats
DROPDOWN_WIDTH_LG = 300  # Large: model names, voices
HINT_WRAP_LENGTH = 600  # Max hint text width before wrapping


# =============================================================================
# Custom Toggle Switch (Tk canvas fallback)
# =============================================================================


class ToggleSwitch(tk.Canvas):
    """Custom toggle switch widget for non-CTk mode."""

    def __init__(
        self, parent, variable: tk.BooleanVar, colors: ThemeColors, command: Optional[Callable] = None, **kwargs
    ):
        self.width = kwargs.pop("width", 50)
        self.height = kwargs.pop("height", 24)
        super().__init__(parent, width=self.width, height=self.height, highlightthickness=0, **kwargs)

        self.variable = variable
        self.colors = colors
        self.command = command

        self.configure(bg=colors.bg)
        self.bind("<Button-1>", self._toggle)
        self.variable.trace_add("write", lambda *args: self._draw())
        self._draw()

    def _draw(self):
        """Draw the toggle switch."""
        self.delete("all")

        is_on = self.variable.get()

        # Track
        track_color = self.colors.accent_green if is_on else self.colors.surface1
        self.create_oval(2, 2, self.height - 2, self.height - 2, fill=track_color, outline=track_color)
        self.create_oval(
            self.width - self.height + 2, 2, self.width - 2, self.height - 2, fill=track_color, outline=track_color
        )
        self.create_rectangle(
            self.height // 2, 2, self.width - self.height // 2, self.height - 2, fill=track_color, outline=track_color
        )

        # Knob
        knob_x = self.width - self.height // 2 - 4 if is_on else self.height // 2 + 4
        self.create_oval(knob_x - 8, 4, knob_x + 8, self.height - 4, fill="#ffffff", outline="#ffffff")

    def _toggle(self, event=None):
        """Toggle the switch."""
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()


# =============================================================================
# Form Fields Mixin — standardized field creation with uniform layout
# =============================================================================


class FormFieldsMixin:
    """
    Mixin providing standardized form field methods.

    Requires the host class to have:
        self.use_ctk: bool
        self.colors: ThemeColors
        self.root: Tk/CTk root window
        self.vars: Dict[str, tk.Variable]
        self.widgets: Dict[str, Any]
    """

    def _add_entry_field(self, parent, key: str, label: str, value: str, size: str = "md", hint: str | None = None):
        """
        Add a text entry field with uniform layout.

        Args:
            parent: Parent widget
            key: Config key name
            label: Display label
            value: Current value
            size: "sm", "md", or "lg"
            hint: Optional hint text (displayed below the field)
        """
        width_map = {"sm": ENTRY_WIDTH_SM, "md": ENTRY_WIDTH_MD, "lg": ENTRY_WIDTH_LG}
        width = width_map.get(size, ENTRY_WIDTH_MD)

        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=4)

        self.vars[key] = tk.StringVar(master=self.root, value=value)

        if self.use_ctk:
            ctk.CTkLabel(
                row,
                text=label,
                font=get_ctk_font(13),
                width=LABEL_WIDTH,
                anchor="w",
                **get_ctk_label_colors(self.colors),
            ).pack(side="left")
            entry = ctk.CTkEntry(
                row,
                textvariable=self.vars[key],
                font=get_ctk_font(13),
                width=width,
                height=34,
                **get_ctk_entry_colors(self.colors),
            )
            entry.pack(side="left", padx=(8, 0))
            self.widgets[key] = entry
        else:
            tk.Label(
                row,
                text=label,
                font=("Segoe UI", 10),
                width=LABEL_WIDTH // 8,
                anchor="w",
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(side="left")
            entry = tk.Entry(
                row,
                textvariable=self.vars[key],
                font=("Segoe UI", 10),
                width=width // 8,
                bg=self.colors.input_bg,
                fg=self.colors.fg,
            )
            entry.pack(side="left", padx=(8, 0), ipady=4)
            self.widgets[key] = entry

        if hint:
            self._add_hint(parent, hint)

    def _add_toggle_field(
        self, parent, key: str, label: str, value: bool, hint: str | None = None, command: Callable | None = None
    ):
        """
        Add a toggle switch field with uniform layout.

        Args:
            parent: Parent widget
            key: Config key name
            label: Display label
            value: Current boolean value
            hint: Optional hint text
            command: Optional callback on toggle
        """
        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=4)

        self.vars[key] = tk.BooleanVar(master=self.root, value=value)

        if self.use_ctk:
            switch_kwargs = {
                "text": label,
                "variable": self.vars[key],
                "font": get_ctk_font(13),
                "text_color": self.colors.fg,
                "fg_color": self.colors.surface2,
                "progress_color": self.colors.accent,
                "button_color": "#ffffff",
                "button_hover_color": "#f0f0f0",
            }
            if command:
                switch_kwargs["command"] = command
            self.widgets[key] = ctk.CTkSwitch(row, **switch_kwargs)
            self.widgets[key].pack(side="left")
        else:
            tk.Label(row, text=label, font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            toggle = ToggleSwitch(row, self.vars[key], self.colors, command=command)
            toggle.pack(side="left", padx=(10, 0))
            self.widgets[key] = toggle

        if hint:
            # Short hints go inline, long hints go below
            if len(hint) < 60:
                self._add_inline_hint(row, hint)
            else:
                self._add_hint(parent, hint)

    def _add_spinbox_field(
        self, parent, key: str, label: str, value: int, min_val: int, max_val: int, hint: str | None = None
    ):
        """
        Add a spinbox/number entry field with uniform layout.

        Args:
            parent: Parent widget
            key: Config key name
            label: Display label
            value: Current integer value
            min_val: Minimum value
            max_val: Maximum value
            hint: Optional hint text
        """
        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=4)

        # Use StringVar to avoid TclError when field is cleared
        self.vars[key] = tk.StringVar(master=self.root, value=str(value) if value is not None else "")

        # Store metadata for validation and default value restoration
        self.widgets[f"{key}_default"] = value
        self.widgets[f"{key}_min"] = min_val
        self.widgets[f"{key}_max"] = max_val

        if self.use_ctk:
            ctk.CTkLabel(
                row,
                text=label,
                font=get_ctk_font(13),
                width=LABEL_WIDTH,
                anchor="w",
                **get_ctk_label_colors(self.colors),
            ).pack(side="left")
            entry = ctk.CTkEntry(
                row,
                textvariable=self.vars[key],
                font=get_ctk_font(13),
                width=ENTRY_WIDTH_SM,
                height=34,
                **get_ctk_entry_colors(self.colors),
            )
            entry.pack(side="left", padx=(8, 0))
            self.widgets[key] = entry
        else:
            from tkinter import ttk

            tk.Label(
                row,
                text=label,
                font=("Segoe UI", 10),
                width=LABEL_WIDTH // 8,
                anchor="w",
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(side="left")
            spinbox = ttk.Spinbox(row, textvariable=self.vars[key], from_=min_val, to=max_val, width=10)
            spinbox.pack(side="left", padx=(8, 0))
            self.widgets[key] = spinbox

        if hint:
            self._add_inline_hint(row, hint)

    def _add_dropdown_field(
        self,
        parent,
        key: str,
        label: str,
        value: str,
        options: List[str],
        size: str = "sm",
        hint: str | None = None,
        command: Callable | None = None,
    ):
        """
        Add a dropdown/combobox field with uniform layout.

        Args:
            parent: Parent widget
            key: Config key name
            label: Display label
            value: Current value
            options: List of dropdown options
            size: "sm", "md", or "lg"
            hint: Optional hint text
            command: Optional callback on selection change
        """
        width_map = {"sm": DROPDOWN_WIDTH_SM, "md": DROPDOWN_WIDTH_MD, "lg": DROPDOWN_WIDTH_LG}
        width = width_map.get(size, DROPDOWN_WIDTH_SM)

        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=4)

        self.vars[key] = tk.StringVar(master=self.root, value=value)

        if self.use_ctk:
            ctk.CTkLabel(
                row,
                text=label,
                font=get_ctk_font(13),
                width=LABEL_WIDTH,
                anchor="w",
                **get_ctk_label_colors(self.colors),
            ).pack(side="left")
            combo_kwargs = {
                "variable": self.vars[key],
                "values": options,
                "width": width,
                "height": 34,
                "state": "readonly",
                "font": get_ctk_font(13),
                **get_ctk_combobox_colors(self.colors),
            }
            if command:
                combo_kwargs["command"] = command
            combo = ctk.CTkComboBox(row, **combo_kwargs)
            combo.pack(side="left", padx=(8, 0))
            self.widgets[key] = combo
        else:
            from tkinter import ttk

            tk.Label(
                row,
                text=label,
                font=("Segoe UI", 10),
                width=LABEL_WIDTH // 8,
                anchor="w",
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(side="left")
            combo = ttk.Combobox(row, textvariable=self.vars[key], values=options, state="readonly", width=width // 10)
            if command:
                combo.bind("<<ComboboxSelected>>", lambda e: command(self.vars[key].get()))
            combo.pack(side="left", padx=(8, 0))
            self.widgets[key] = combo

        if hint:
            if len(hint) < 60:
                self._add_inline_hint(row, hint)
            else:
                self._add_hint(parent, hint)

    def _add_scrollable_dropdown_field(
        self, parent, key: str, label: str, value: str, options: List[str], size: str = "lg", hint: str | None = None
    ):
        """
        Add a scrollable dropdown field (for long lists like voices/models).

        Args:
            parent: Parent widget
            key: Config key name
            label: Display label
            value: Current value
            options: List of dropdown options
            size: "sm", "md", or "lg"
            hint: Optional hint text
        """
        width_map = {"sm": DROPDOWN_WIDTH_SM, "md": DROPDOWN_WIDTH_MD, "lg": DROPDOWN_WIDTH_LG}
        width = width_map.get(size, DROPDOWN_WIDTH_LG)

        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=4)

        self.vars[key] = tk.StringVar(master=self.root, value=value)

        if self.use_ctk:
            ctk.CTkLabel(
                row,
                text=label,
                font=get_ctk_font(13),
                width=LABEL_WIDTH,
                anchor="w",
                **get_ctk_label_colors(self.colors),
            ).pack(side="left")

            dropdown = ScrollableComboBox(
                row, colors=self.colors, variable=self.vars[key], values=options, width=width, height=34, font_size=13
            )
            dropdown.pack(side="left", padx=(8, 0))
            self.widgets[key] = dropdown
        else:
            from tkinter import ttk

            tk.Label(
                row,
                text=label,
                font=("Segoe UI", 10),
                width=LABEL_WIDTH // 8,
                anchor="w",
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(side="left")

            combo = ttk.Combobox(row, textvariable=self.vars[key], values=options, state="readonly", width=width // 10)
            combo.pack(side="left", padx=(8, 0))
            self.widgets[key] = combo

        if hint:
            self._add_inline_hint(row, hint)

    # -------------------------------------------------------------------------
    # Hint helpers
    # -------------------------------------------------------------------------

    def _add_hint(self, parent, text: str):
        """Add a hint label below the current row, with wrapping."""
        if self.use_ctk:
            ctk.CTkLabel(
                parent,
                text=text,
                font=get_ctk_font(11),
                wraplength=HINT_WRAP_LENGTH,
                justify="left",
                anchor="w",
                **get_ctk_label_colors(self.colors, muted=True),
            ).pack(fill="x", padx=(LABEL_WIDTH + 10, 0), pady=(0, 2), anchor="w")
        else:
            tk.Label(
                parent,
                text=text,
                font=("Segoe UI", 9),
                wraplength=HINT_WRAP_LENGTH,
                justify="left",
                anchor="w",
                bg=self.colors.bg,
                fg=self.colors.blockquote,
            ).pack(fill="x", padx=(LABEL_WIDTH + 10, 0), pady=(0, 2), anchor="w")

    def _add_inline_hint(self, row, text: str):
        """Add a short hint label inline (same row as the field)."""
        if self.use_ctk:
            ctk.CTkLabel(row, text=text, font=get_ctk_font(11), **get_ctk_label_colors(self.colors, muted=True)).pack(
                side="left", padx=(12, 0)
            )
        else:
            tk.Label(row, text=text, font=("Segoe UI", 9), bg=self.colors.bg, fg=self.colors.blockquote).pack(
                side="left", padx=(12, 0)
            )

    # -------------------------------------------------------------------------
    # Scrollable content frame helper
    # -------------------------------------------------------------------------

    def _create_tab_scroll_frame(self, frame):
        """
        Create a scrollable frame inside a tab frame.

        Returns:
            content_parent: The frame to add widgets to.
        """
        from ...custom_widgets import TkScrollableFrame

        if self.use_ctk:
            scroll_frame = ctk.CTkScrollableFrame(frame, fg_color="transparent")
            content_parent = scroll_frame
        else:
            scroll_frame = TkScrollableFrame(frame, bg_color=self.colors.bg)
            content_parent = scroll_frame.scrollable_frame

        scroll_frame.pack(fill="both", expand=True, padx=20, pady=20)
        return content_parent
