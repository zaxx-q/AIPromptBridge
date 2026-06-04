#!/usr/bin/env python3
"""
TTS tab mixin for Settings Window.

Sections:
    🗣️ Text-to-Speech — enable, hotkey, model, voice
    🎬 AI Director — enable, auto-run, model
    💾 Export & Playback — format, directory, autoplay
    🌐 Endpoint — use official endpoint toggle
"""

import tkinter as tk

from ...custom_widgets import create_section_header
from ...platform import HAVE_CTK, ctk
from ...themes import get_ctk_font, get_ctk_label_colors


class TTSTabMixin:
    """Mixin providing the TTS tab for SettingsWindow."""

    def _create_tts_tab(self, frame):
        """Create the TTS settings tab."""
        content = self._create_tab_scroll_frame(frame)

        # Import TTS constants
        try:
            from ....audio.tts_constants import TTS_MODELS, get_voice_list
            tts_models = TTS_MODELS
            tts_voices = get_voice_list()
        except ImportError:
            tts_models = ["gemini-2.5-flash-preview-tts"]
            tts_voices = ["Kore"]

        # --- General TTS Settings ---
        create_section_header(content, "🗣️ Text-to-Speech", self.colors)

        self._add_toggle_field(content, "tts_enabled",
                               "Enable TTS",
                               self.config_data.config.get("tts_enabled", True),
                               hint="Enable Gemini Text-to-Speech features (Restart required)")

        self._add_entry_field(content, "tts_hotkey", "Activation hotkey:",
                             self.config_data.config.get("tts_hotkey", "ctrl+alt+t"),
                             size="md", hint="⚠️ Restart required")

        # Model Dropdown
        self._add_dropdown_field(content, "tts_default_model", "Default Model:",
                                 self.config_data.config.get("tts_default_model", tts_models[0]),
                                 options=tts_models, size="lg")

        # Voice Dropdown (scrollable for long list)
        # The stored config value is just the name (e.g. "Kore"), but UI shows "Kore — Female, Firm"
        current_voice = self.config_data.config.get("tts_default_voice", "Kore")
        current_voice_display = current_voice
        for v in tts_voices:
            if v.startswith(current_voice + " ") or v == current_voice:
                current_voice_display = v
                break

        self._add_scrollable_dropdown_field(content, "tts_default_voice", "Default Voice:",
                                            current_voice_display, options=tts_voices, size="lg")

        # --- AI Director ---
        create_section_header(content, "🎬 AI Director", self.colors, top_padding=20)

        self._add_toggle_field(content, "tts_director_enabled",
                               "Enable AI Director",
                               self.config_data.config.get("tts_director_enabled", True),
                               hint="Generate style instructions for expressive speech")

        self._add_toggle_field(content, "tts_director_auto_mode",
                               "Auto-run Director",
                               self.config_data.config.get("tts_director_auto_mode", False),
                               hint="Automatically run director before generating audio")

        self._add_entry_field(content, "tts_director_model", "Director Model:",
                             self.config_data.config.get("tts_director_model", ""),
                             size="lg", hint="Override model (empty = use default provider)")

        # --- Export & Playback ---
        create_section_header(content, "💾 Export & Playback", self.colors, top_padding=20)

        self._add_dropdown_field(content, "audio_output_format", "Audio output format:",
                                 self.config_data.config.get("audio_output_format", "ogg"),
                                 options=["ogg", "mp3", "wav", "flac", "m4a"], size="sm",
                                 hint="Format for TTS & Audio Analyzer saved files (ogg = Opus, m4a = AAC)")

        self._add_entry_field(content, "tts_save_directory", "Save directory:",
                             self.config_data.config.get("tts_save_directory", "audio_output"),
                             size="lg", hint="Folder to save generated audio files")

        self._add_toggle_field(content, "tts_autoplay",
                               "Autoplay audio",
                               self.config_data.config.get("tts_autoplay", True),
                               hint="Play audio immediately after generation")

        # --- Endpoint ---
        create_section_header(content, "🌐 Endpoint", self.colors, top_padding=20)

        self._add_toggle_field(content, "tts_use_official_endpoint",
                               "Use Official Google Endpoint",
                               self.config_data.config.get("tts_use_official_endpoint", False),
                               hint="Always use official Google API for TTS, ignoring base_url")
