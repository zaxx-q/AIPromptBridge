#!/usr/bin/env python3
"""
Theme tab mixin for Settings Window.

Sections (in display order):
    👁️ Preview — live theme preview (shown first for immediate feedback)
    🎨 UI Theme — theme + mode dropdowns
    🎨 Chat Colors — user/assistant message background overrides (moved from General)
    🔧 Framework — force standard Tk toggle
"""

import tkinter as tk

from ...custom_widgets import create_section_header
from ...platform import HAVE_CTK, ctk
from ...themes import (
    ThemeColors,
    ThemeRegistry,
    get_ctk_combobox_colors,
    get_ctk_entry_colors,
    get_ctk_font,
    get_ctk_label_colors,
    list_themes,
)
from .widgets import LABEL_WIDTH


class ThemeTabMixin:
    """Mixin providing the Theme tab for SettingsWindow."""

    def _create_theme_tab(self, frame):
        """Create the Theme settings tab."""
        content = self._create_tab_scroll_frame(frame)

        # --- Preview (shown first for immediate visual feedback) ---
        create_section_header(content, "👁️ Preview", self.colors)

        if self.use_ctk:
            self.preview_frame = ctk.CTkFrame(
                content,
                fg_color=self.colors.surface0,
                corner_radius=10,
                border_width=1,
                border_color=self.colors.border,
            )
        else:
            self.preview_frame = tk.Frame(
                content, bg=self.colors.surface0, highlightbackground=self.colors.border, highlightthickness=1
            )
        self.preview_frame.pack(fill="x", pady=5)

        # We'll populate the preview after the theme vars are created below
        self._preview_needs_init = True

        # --- UI Theme ---
        create_section_header(content, "🎨 UI Theme", self.colors, top_padding=20)

        self._add_dropdown_field(
            content,
            "ui_theme",
            "Theme:",
            self.config_data.config.get("ui_theme", "catppuccin"),
            options=list_themes(),
            size="md",
            command=lambda x: self._update_theme_preview(),
        )

        self._add_dropdown_field(
            content,
            "ui_theme_mode",
            "Mode:",
            self.config_data.config.get("ui_theme_mode", "auto"),
            options=["auto", "dark", "light"],
            size="sm",
            command=lambda x: self._update_theme_preview(),
        )

        # --- Chat Colors (moved from General tab) ---
        create_section_header(content, "🎨 Chat Colors", self.colors, top_padding=20)

        self._add_entry_field(
            content,
            "chat_user_bg_color",
            "User msg background:",
            self.config_data.config.get("chat_user_bg_color") or "",
            size="sm",
            hint="Hex color override (e.g. #1e3a5f). Empty = theme default",
        )

        self._add_entry_field(
            content,
            "chat_assistant_bg_color",
            "Assistant msg background:",
            self.config_data.config.get("chat_assistant_bg_color") or "",
            size="sm",
            hint="Hex color override (e.g. #1e3e2e). Empty = theme default",
        )

        # --- Framework (moved to bottom — rarely changed) ---
        create_section_header(content, "🔧 Framework", self.colors, top_padding=20)

        self._add_toggle_field(
            content,
            "ui_force_standard_tk",
            "Force Standard Tkinter (Disable Modern UI)",
            self.config_data.config.get("ui_force_standard_tk", False),
            hint="⚠️ Restart required. Use if CustomTkinter causes performance issues.",
        )

        # Now that vars are created, populate the preview
        if self._preview_needs_init:
            self._update_theme_preview()
            self._preview_needs_init = False

    def _update_theme_preview(self, event=None):
        """Update the theme preview."""
        if not self.preview_frame:
            return

        # Clear preview
        for widget in self.preview_frame.winfo_children():
            widget.destroy()

        # Get preview colors
        theme_name = self.vars["ui_theme"].get()
        mode = self.vars["ui_theme_mode"].get()

        if mode == "auto":
            is_dark = ThemeRegistry.is_dark_mode()
        else:
            is_dark = mode == "dark"

        preview_colors = ThemeRegistry.get_theme(theme_name, "dark" if is_dark else "light")

        # Update preview frame background
        if self.use_ctk:
            self.preview_frame.configure(fg_color=preview_colors.bg)
        else:
            self.preview_frame.configure(bg=preview_colors.bg)

        # Add sample elements
        inner = (
            ctk.CTkFrame(self.preview_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(self.preview_frame, bg=preview_colors.bg)
        )
        inner.pack(fill="both", expand=True, padx=15, pady=15)

        # Title
        if self.use_ctk:
            ctk.CTkLabel(
                inner,
                text=f"Theme: {theme_name.title()} ({'Dark' if is_dark else 'Light'})",
                font=get_ctk_font(16, "bold"),
                text_color=preview_colors.fg,
            ).pack(anchor="w")

            ctk.CTkLabel(
                inner,
                text="This is how text will look in this theme.",
                font=get_ctk_font(13),
                text_color=preview_colors.fg,
            ).pack(anchor="w", pady=(8, 0))

            ctk.CTkLabel(
                inner,
                text="Muted/secondary text appears like this.",
                font=get_ctk_font(12),
                text_color=preview_colors.blockquote,
            ).pack(anchor="w")
        else:
            tk.Label(
                inner,
                text=f"Theme: {theme_name.title()} ({'Dark' if is_dark else 'Light'})",
                font=("Segoe UI", 12, "bold"),
                bg=preview_colors.bg,
                fg=preview_colors.fg,
            ).pack(anchor="w")
            tk.Label(
                inner,
                text="This is how text will look in this theme.",
                font=("Segoe UI", 10),
                bg=preview_colors.bg,
                fg=preview_colors.fg,
            ).pack(anchor="w", pady=(5, 0))
            tk.Label(
                inner,
                text="Muted/secondary text appears like this.",
                font=("Segoe UI", 9),
                bg=preview_colors.bg,
                fg=preview_colors.blockquote,
            ).pack(anchor="w")

        # Sample buttons row
        btn_row = ctk.CTkFrame(inner, fg_color="transparent") if self.use_ctk else tk.Frame(inner, bg=preview_colors.bg)
        btn_row.pack(anchor="w", pady=(10, 0))

        for label, color in [
            ("Primary", preview_colors.accent),
            ("Success", preview_colors.accent_green),
            ("Warning", preview_colors.accent_yellow),
            ("Danger", preview_colors.accent_red),
        ]:
            fg = preview_colors.accent_fg
            if self.use_ctk:
                ctk.CTkLabel(
                    btn_row,
                    text=label,
                    font=get_ctk_font(12),
                    fg_color=color,
                    text_color=fg,
                    corner_radius=6,
                    padx=14,
                    pady=5,
                ).pack(side="left", padx=4)
            else:
                tk.Label(btn_row, text=label, font=("Segoe UI", 9), bg=color, fg=fg, padx=10, pady=3).pack(
                    side="left", padx=2
                )

        # Sample input
        if self.use_ctk:
            sample_entry = ctk.CTkEntry(
                inner,
                font=get_ctk_font(12),
                width=240,
                height=34,
                fg_color=preview_colors.input_bg,
                text_color=preview_colors.fg,
                border_color=preview_colors.border,
            )
            sample_entry.pack(anchor="w", pady=(12, 0))
            sample_entry.insert(0, "Sample input field")
        else:
            sample_entry = tk.Entry(inner, font=("Segoe UI", 10), bg=preview_colors.input_bg, fg=preview_colors.fg)
            sample_entry.insert(0, "Sample input field")
            sample_entry.pack(anchor="w", pady=(10, 0))
