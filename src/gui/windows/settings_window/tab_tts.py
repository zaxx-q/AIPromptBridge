#!/usr/bin/env python3
"""
TTS tab mixin for Settings Window.

Sections:
    🗣️ Text-to-Speech — enable, hotkey (Windows) / IPC trigger (Linux), model, voice
    🎬 AI Director — enable, auto-run, model
    💾 Export & Playback — format, directory, autoplay
    🌐 Endpoint — use official endpoint toggle
"""

import tkinter as tk

from src.platform.detect import is_linux

from ...custom_widgets import create_section_header
from ...platform import HAVE_CTK, ctk
from ...themes import get_ctk_font, get_ctk_label_colors


class TTSTabMixin:
    """Mixin providing the TTS tab for SettingsWindow."""

    def _create_tts_tab(self, frame):
        """Create the TTS settings tab."""
        content = self._create_tab_scroll_frame(frame)

        # Import TTS constants
        from ....audio.tts_constants import TTS_MODELS, get_voice_list

        tts_models = TTS_MODELS
        tts_voices = get_voice_list()

        # --- General TTS Settings ---
        create_section_header(content, "🗣️ Text-to-Speech", self.colors)

        self._add_toggle_field(
            content,
            "tts_enabled",
            "Enable TTS",
            self.config_data.config.get("tts_enabled", True),
            hint="Enable Gemini Text-to-Speech features (Restart required)",
        )

        if is_linux():
            # Reuse Tools-tab helper when mixed in on SettingsWindow
            if hasattr(self, "_add_linux_trigger_line"):
                self._add_linux_trigger_line(content, "tts")
            else:
                try:
                    from ....startup_manager import format_trigger_command_display

                    text = f"Trigger: {format_trigger_command_display('tts')}"
                except Exception:
                    text = "Trigger: --trigger tts"
                row = (
                    ctk.CTkFrame(content, fg_color="transparent")
                    if self.use_ctk
                    else tk.Frame(content, bg=self.colors.bg)
                )
                row.pack(fill="x", pady=(0, 4))
                if self.use_ctk:
                    ctk.CTkLabel(
                        row, text=text, font=get_ctk_font(11), **get_ctk_label_colors(self.colors, muted=True)
                    ).pack(side="left")
                else:
                    tk.Label(row, text=text, font=("Segoe UI", 9), bg=self.colors.bg, fg=self.colors.blockquote).pack(
                        side="left"
                    )
        else:
            self._add_entry_field(
                content,
                "tts_hotkey",
                "Activation hotkey:",
                self.config_data.config.get("tts_hotkey", "ctrl+alt+t"),
                size="md",
                hint="⚠️ Restart required",
            )

        # Model Dropdown
        self._add_dropdown_field(
            content,
            "tts_default_model",
            "Default Model:",
            self.config_data.config.get("tts_default_model", tts_models[0]),
            options=tts_models,
            size="lg",
        )

        # Voice Dropdown (scrollable for long list)
        # The stored config value is just the name (e.g. "Kore"), but UI shows "Kore — Female, Firm"
        current_voice = self.config_data.config.get("tts_default_voice", "Kore")
        current_voice_display = current_voice
        for v in tts_voices:
            if v.startswith(current_voice + " ") or v == current_voice:
                current_voice_display = v
                break

        self._add_scrollable_dropdown_field(
            content, "tts_default_voice", "Default Voice:", current_voice_display, options=tts_voices, size="lg"
        )

        # --- AI Director ---
        create_section_header(content, "🎬 AI Director", self.colors, top_padding=20)

        self._add_toggle_field(
            content,
            "tts_director_enabled",
            "Enable AI Director",
            self.config_data.config.get("tts_director_enabled", True),
            hint="Generate style instructions for expressive speech",
        )

        self._add_toggle_field(
            content,
            "tts_director_auto_mode",
            "Auto-run Director",
            self.config_data.config.get("tts_director_auto_mode", False),
            hint="Automatically run director before generating audio",
        )

        # AI Director Profile
        from ....connection_profiles import ProfileStore

        profile_names = ProfileStore.get_instance().get_profile_names()
        current_profile = self.config_data.config.get("tts_director_profile", "")
        current_profile_display = current_profile if current_profile in profile_names else "(Use Active)"

        self._add_scrollable_dropdown_field(
            content,
            "tts_director_profile",
            "Director Connection Profile:",
            current_profile_display,
            options=["(Use Active)", *profile_names],
            size="lg",
            hint="Override Connection for TTS instructions generation",
        )

        # --- Export & Playback ---
        create_section_header(content, "💾 Export & Playback", self.colors, top_padding=20)

        self._add_dropdown_field(
            content,
            "audio_output_format",
            "Audio output format:",
            self.config_data.config.get("audio_output_format", "ogg"),
            options=["ogg", "mp3", "wav", "flac", "m4a"],
            size="sm",
            hint="Format for TTS & Audio Analyzer saved files (ogg = Opus, m4a = AAC)",
        )

        self._add_entry_field(
            content,
            "tts_save_directory",
            "Save directory:",
            self.config_data.config.get("tts_save_directory", "audio_output"),
            size="lg",
            hint="Folder to save generated audio files",
        )

        self._add_toggle_field(
            content,
            "tts_autoplay",
            "Autoplay audio",
            self.config_data.config.get("tts_autoplay", True),
            hint="Play audio immediately after generation",
        )

        # --- Endpoint ---
        create_section_header(content, "🌐 Endpoint", self.colors, top_padding=20)

        self._add_toggle_field(
            content,
            "tts_use_official_endpoint",
            "Use Official Google Endpoint",
            self.config_data.config.get("tts_use_official_endpoint", False),
            hint="Always use official Google API for TTS, ignoring base_url",
        )
