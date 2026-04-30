#!/usr/bin/env python3
"""
Generation tab mixin for Settings Window (renamed from "Streaming").

Sections:
    📦 Model Presets — open preset manager
    🌊 Streaming — enable/disable streaming responses
    💭 Thinking / Reasoning — thinking mode, output format, budget/level
    ⌨️ Typing — typing delay and speed (moved from Tools tab)
    🧪 AI Parameters — temperature, max_tokens, top_p (moved from Provider tab)
"""

import tkinter as tk

from ...platform import HAVE_CTK, ctk
from ...themes import get_ctk_font, get_ctk_label_colors
from ...custom_widgets import create_section_header, create_emoji_button


class GenerationTabMixin:
    """Mixin providing the Generation tab for SettingsWindow."""

    def _create_generation_tab(self, frame):
        """Create the Generation settings tab (streaming + thinking + typing + AI params)."""
        content = self._create_tab_scroll_frame(frame)

        # --- Model Presets ---
        create_section_header(content, "📦 Model Presets", self.colors, top_padding=20)
        self._create_preset_manager_button(content)

        # --- Streaming ---
        create_section_header(content, "🌊 Streaming", self.colors)

        self._add_toggle_field(content, "streaming_enabled",
                               "Enable streaming responses",
                               self.config_data.config.get("streaming_enabled", True),
                               hint="Type answer word-by-word instead of waiting for full response")

        # --- Thinking / Reasoning ---
        create_section_header(content, "💭 Thinking / Reasoning", self.colors, top_padding=20)

        self._add_toggle_field(content, "thinking_enabled",
                               "Enable thinking mode",
                               self.config_data.config.get("thinking_enabled", False),
                               hint="Enable sending thinking parameters")

        self._add_dropdown_field(content, "thinking_output", "Thinking output:",
                                 self.config_data.config.get("thinking_output", "reasoning_content"),
                                 options=["filter", "raw", "reasoning_content"], size="md",
                                 hint="filter: Hide thinking content\n"
                                      "raw: Include thinking in main response\n"
                                      "reasoning_content: Separate field (collapsible in chat)")

        # --- Thinking Configuration ---
        create_section_header(content, "⚙️ Thinking Configuration", self.colors, top_padding=20)

        self._add_dropdown_field(content, "reasoning_effort", "Reasoning effort (OpenAI):",
                                 self.config_data.config.get("reasoning_effort", "high"),
                                 options=["low", "medium", "high"], size="sm",
                                 hint="How much the model thinks for reasoning/thinking models")

        self._add_spinbox_field(content, "thinking_budget", "Thinking budget:",
                               self.config_data.config.get("thinking_budget", -1),
                               -1, 100000,
                               hint="For Gemini 2.5 models. -1 = auto")

        self._add_dropdown_field(content, "thinking_level", "Thinking level (Gemini 3.x):",
                                 self.config_data.config.get("thinking_level", "high"),
                                 options=["low", "high"], size="sm",
                                 hint="For Gemini 3 models")

        # --- Typing (moved from Tools tab) ---
        create_section_header(content, "⌨️ Typing", self.colors, top_padding=20)

        self._add_spinbox_field(content, "streaming_typing_delay", "Typing delay (ms):",
                               self.config_data.config.get("streaming_typing_delay", 5),
                               1, 100, hint="Delay per character in replace mode")

        self._add_toggle_field(content, "streaming_typing_uncapped",
                               "Uncapped typing speed",
                               self.config_data.config.get("streaming_typing_uncapped", False),
                               hint="⚠️ No delay between chars. May overwhelm some apps.")

        # --- AI Parameters (moved from Provider tab) ---
        create_section_header(content, "🧪 AI Parameters", self.colors, top_padding=20)

        if self.use_ctk:
            ctk.CTkLabel(content,
                        text="Optional parameters passed to the model. Leave empty for model defaults.\n"
                             "You can add custom parameters in the [ai_params] section of config.ini",
                        font=get_ctk_font(11), justify="left",
                        **get_ctk_label_colors(self.colors, muted=True)
                        ).pack(anchor="w", pady=(0, 8))
        else:
            tk.Label(content,
                    text="Optional parameters passed to the model. Leave empty for model defaults.\n"
                         "You can add custom parameters in the [ai_params] section of config.ini",
                    font=("Segoe UI", 9), justify="left",
                    bg=self.colors.bg, fg=self.colors.blockquote).pack(anchor="w", pady=(0, 8))

        # Track which var keys belong to ai_params (prefixed with "ai_param_")
        if not hasattr(self, '_ai_param_keys'):
            self._ai_param_keys = set()

        # Temperature
        temp_val = self.config_data.ai_params.get("temperature", "")
        self._add_entry_field(content, "ai_param_temperature", "Temperature:",
                             str(temp_val) if temp_val != "" and temp_val is not None else "",
                             size="sm", hint="0.0–2.0. Controls randomness")
        self._ai_param_keys.add("ai_param_temperature")

        # Max tokens
        max_tok_val = self.config_data.ai_params.get("max_tokens", "")
        self._add_entry_field(content, "ai_param_max_tokens", "Max tokens:",
                             str(max_tok_val) if max_tok_val != "" and max_tok_val is not None else "",
                             size="sm", hint="Maximum output tokens")
        self._ai_param_keys.add("ai_param_max_tokens")

        # Top P
        top_p_val = self.config_data.ai_params.get("top_p", "")
        self._add_entry_field(content, "ai_param_top_p", "Top P:",
                             str(top_p_val) if top_p_val != "" and top_p_val is not None else "",
                             size="sm", hint="0.0–1.0. Nucleus sampling threshold")
        self._ai_param_keys.add("ai_param_top_p")

    def _create_preset_manager_button(self, parent):
        """Create a button to open the Model Preset Manager dialog."""
        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=4)

        if self.use_ctk:
            ctk.CTkLabel(row,
                        text="Configure model presets for per-action overrides (provider, model, temperature, etc.)",
                        font=get_ctk_font(11), justify="left",
                        **get_ctk_label_colors(self.colors, muted=True)
                        ).pack(side="left", padx=(0, 12))

        btn = create_emoji_button(
            row, "Manage Presets", "📦", self.colors, "primary", 160, 36,
            command=self._open_preset_manager
        )
        btn.pack(side="left" if not self.use_ctk else "left")

        if not self.use_ctk:
            tk.Label(row,
                    text="Configure model presets for per-action overrides",
                    font=("Segoe UI", 9), bg=self.colors.bg, fg=self.colors.blockquote
                    ).pack(side="left", padx=(12, 0))

    def _open_preset_manager(self):
        """Open the PresetManagerDialog from the prompt_editor package."""
        try:
            from ..prompt_editor import PresetManagerDialog
            PresetManagerDialog(self.root, colors=self.colors)
        except Exception as e:
            print(f"[Settings] Error opening preset manager: {e}")
