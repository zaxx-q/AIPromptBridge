#!/usr/bin/env python3
"""
Generation tab mixin for Settings Window.

Sections:
    ⌨️ Typing — typing delay and speed
"""

import tkinter as tk

from ...platform import HAVE_CTK, ctk
from ...themes import get_ctk_font, get_ctk_label_colors
from ...custom_widgets import create_section_header


class GenerationTabMixin:
    """Mixin providing the Generation tab for SettingsWindow."""

    def _create_generation_tab(self, frame):
        """Create the Generation settings tab (typing settings only)."""
        content = self._create_tab_scroll_frame(frame)

        # --- Typing ---
        create_section_header(content, "⌨️ Typing", self.colors)

        if self.use_ctk:
            ctk.CTkLabel(content,
                        text="Controls typing speed when streaming text into other applications via replace mode.",
                        font=get_ctk_font(11), justify="left",
                        **get_ctk_label_colors(self.colors, muted=True)
                        ).pack(anchor="w", pady=(0, 8))
        else:
            tk.Label(content,
                    text="Controls typing speed when streaming text into other applications via replace mode.",
                    font=("Segoe UI", 9), justify="left",
                    bg=self.colors.bg, fg=self.colors.blockquote).pack(anchor="w", pady=(0, 8))

        self._add_spinbox_field(content, "streaming_typing_delay", "Typing delay (ms):",
                               self.config_data.config.get("streaming_typing_delay", 5),
                               1, 100, hint="Delay per character in replace mode")

        self._add_toggle_field(content, "streaming_typing_uncapped",
                               "Uncapped typing speed",
                               self.config_data.config.get("streaming_typing_uncapped", False),
                               hint="⚠️ No delay between chars. May overwhelm some apps.")
