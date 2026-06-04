#!/usr/bin/env python3
"""
Playground Tab Mixin for the Prompt Editor.

Provides the Playground tab for testing prompts with live preview,
image/audio handling, and API testing.
"""

import base64
import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Dict

import pyperclip

from ...custom_widgets import TkScrollableFrame, create_emoji_button, create_section_header
from ...platform import HAVE_CTK, ctk
from ...themes import (
    get_ctk_button_colors,
    get_ctk_combobox_colors,
    get_ctk_entry_colors,
    get_ctk_font,
    get_ctk_label_colors,
    get_ctk_textbox_colors,
)
from .dialogs import TestResultDialog

# Import emoji renderer for CTkImage support (Windows color emoji fix)
try:
    from ...emoji_renderer import HAVE_PIL, get_emoji_renderer

    HAVE_EMOJI = HAVE_PIL and HAVE_CTK
except ImportError:
    HAVE_EMOJI = False
    get_emoji_renderer = None


class PlaygroundTabMixin:
    """Mixin providing the Playground tab for PromptEditorWindow."""

    def _create_playground_tab(self, frame):
        """Create the Playground tab for testing prompts."""
        container = ctk.CTkFrame(frame, fg_color="transparent") if self.use_ctk else tk.Frame(frame, bg=self.colors.bg)
        container.pack(fill="both", expand=True, padx=15, pady=15)

        # Left panel: Configuration
        left_panel = (
            ctk.CTkFrame(container, fg_color="transparent", width=450)
            if self.use_ctk
            else tk.Frame(container, bg=self.colors.bg, width=450)
        )
        left_panel.pack(side="left", fill="y", padx=(0, 15))
        left_panel.pack_propagate(False)

        if self.use_ctk:
            scroll_container = ctk.CTkScrollableFrame(left_panel, fg_color="transparent")
            scroll_left = scroll_container
        else:
            scroll_container = TkScrollableFrame(left_panel, bg_color=self.colors.bg)
            scroll_left = scroll_container.scrollable_frame
        scroll_container.pack(fill="both", expand=True)

        # Mode selector
        create_section_header(scroll_left, "Mode", self.colors, "🎯")

        self.playground_mode_var = tk.StringVar(master=self.root, value="action_text")
        mode_frame = (
            ctk.CTkFrame(scroll_left, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_left, bg=self.colors.bg)
        )
        mode_frame.pack(anchor="w", pady=(0, 15))

        if self.use_ctk:
            ctk.CTkRadioButton(
                mode_frame,
                text="Text Action",
                variable=self.playground_mode_var,
                value="action_text",
                font=get_ctk_font(13),
                text_color=self.colors.fg,
                fg_color=self.colors.accent,
                command=self._on_playground_mode_change,
            ).pack(side="left", padx=(0, 15))
            ctk.CTkRadioButton(
                mode_frame,
                text="Snip Action",
                variable=self.playground_mode_var,
                value="action_snip",
                font=get_ctk_font(13),
                text_color=self.colors.fg,
                fg_color=self.colors.accent,
                command=self._on_playground_mode_change,
            ).pack(side="left", padx=(0, 15))
            ctk.CTkRadioButton(
                mode_frame,
                text="Audio Action",
                variable=self.playground_mode_var,
                value="action_audio",
                font=get_ctk_font(13),
                text_color=self.colors.fg,
                fg_color=self.colors.accent,
                command=self._on_playground_mode_change,
            ).pack(side="left", padx=(0, 15))
            ctk.CTkRadioButton(
                mode_frame,
                text="🔊 TTS",
                variable=self.playground_mode_var,
                value="tts",
                font=get_ctk_font(13),
                text_color=self.colors.fg,
                fg_color=self.colors.accent,
                command=self._on_playground_mode_change,
            ).pack(side="left")
        else:
            tk.Radiobutton(
                mode_frame,
                text="Text Action",
                variable=self.playground_mode_var,
                value="action_text",
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.fg,
                command=self._on_playground_mode_change,
            ).pack(side="left", padx=(0, 15))
            tk.Radiobutton(
                mode_frame,
                text="Snip Action",
                variable=self.playground_mode_var,
                value="action_snip",
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.fg,
                command=self._on_playground_mode_change,
            ).pack(side="left", padx=(0, 15))
            tk.Radiobutton(
                mode_frame,
                text="Audio Action",
                variable=self.playground_mode_var,
                value="action_audio",
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.fg,
                command=self._on_playground_mode_change,
            ).pack(side="left", padx=(0, 15))
            tk.Radiobutton(
                mode_frame,
                text="🔊 TTS",
                variable=self.playground_mode_var,
                value="tts",
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.fg,
                command=self._on_playground_mode_change,
            ).pack(side="left")

        # Action config frame
        self.action_config_frame = (
            ctk.CTkFrame(scroll_left, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_left, bg=self.colors.bg)
        )
        self.action_config_frame.pack(fill="x", pady=(0, 10))

        if self.use_ctk:
            ctk.CTkLabel(
                self.action_config_frame,
                text="Select Action:",
                font=get_ctk_font(13),
                **get_ctk_label_colors(self.colors),
            ).pack(anchor="w", pady=(0, 8))
        else:
            tk.Label(
                self.action_config_frame,
                text="Select Action:",
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(anchor="w", pady=(0, 5))

        self.playground_action_var = tk.StringVar()
        # Populated dynamically

        if self.use_ctk:
            self.playground_action_combo = ctk.CTkComboBox(
                self.action_config_frame,
                variable=self.playground_action_var,
                values=[],
                width=340,
                height=34,
                state="readonly",
                font=get_ctk_font(13),
                **get_ctk_combobox_colors(self.colors),
                command=lambda x: self._on_playground_action_change(),
            )
        else:
            from tkinter import ttk

            self.playground_action_combo = ttk.Combobox(
                self.action_config_frame, textvariable=self.playground_action_var, values=[], state="readonly", width=35
            )
            self.playground_action_combo.bind("<<ComboboxSelected>>", self._on_playground_action_change)
        self.playground_action_combo.pack(anchor="w", pady=(0, 10))

        # Custom input (for custom actions)
        self.custom_input_frame = (
            ctk.CTkFrame(self.action_config_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(self.action_config_frame, bg=self.colors.bg)
        )
        # Initially hidden

        if self.use_ctk:
            ctk.CTkLabel(
                self.custom_input_frame,
                text="Custom Prompt:",
                font=get_ctk_font(12),
                **get_ctk_label_colors(self.colors),
            ).pack(anchor="w", pady=(0, 2))
            self.playground_custom_var = tk.StringVar()
            self.playground_custom_entry = ctk.CTkEntry(
                self.custom_input_frame,
                textvariable=self.playground_custom_var,
                font=get_ctk_font(12),
                height=32,
                **get_ctk_entry_colors(self.colors),
            )
            self.playground_custom_entry.pack(fill="x")
            self.playground_custom_entry.bind("<KeyRelease>", lambda e: self._update_playground_preview())
        else:
            tk.Label(
                self.custom_input_frame,
                text="Custom Prompt:",
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(anchor="w", pady=(0, 2))
            self.playground_custom_var = tk.StringVar()
            self.playground_custom_entry = tk.Entry(
                self.custom_input_frame,
                textvariable=self.playground_custom_var,
                font=("Segoe UI", 10),
                bg=self.colors.input_bg,
                fg=self.colors.fg,
            )
            self.playground_custom_entry.pack(fill="x")
            self.playground_custom_entry.bind("<KeyRelease>", lambda e: self._update_playground_preview())

        # Modifiers section
        if self.use_ctk:
            # Header with emoji image
            kwargs = {"text": " Modifiers:", "font": get_ctk_font(13), **get_ctk_label_colors(self.colors)}
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                img = renderer.get_ctk_image("🎛️", size=18)
                if img:
                    kwargs["image"] = img
                    kwargs["compound"] = "left"

            ctk.CTkLabel(self.action_config_frame, **kwargs).pack(anchor="w", pady=(8, 8))

            self.playground_mod_scroll = ctk.CTkScrollableFrame(
                self.action_config_frame, height=120, fg_color="transparent"
            )
            mod_scroll_target = self.playground_mod_scroll
        else:
            tk.Label(
                self.action_config_frame,
                text="🎛️ Modifiers:",
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(anchor="w", pady=(8, 5))
            self.playground_mod_scroll = TkScrollableFrame(self.action_config_frame, bg_color=self.colors.bg)
            self.playground_mod_scroll.canvas.configure(height=120)
            mod_scroll_target = self.playground_mod_scroll.scrollable_frame

        self.playground_mod_scroll.pack(fill="x")

        # Populate modifier checkboxes
        self.playground_modifier_vars = {}
        settings = self.options_data.get("_global_settings", {})
        modifiers = settings.get("modifiers", [])

        for mod in modifiers:
            key = mod.get("key")
            label = mod.get("label", key)
            if key:
                var = tk.BooleanVar()
                self.playground_modifier_vars[key] = var

                if self.use_ctk:
                    ctk.CTkCheckBox(
                        mod_scroll_target,
                        text=label,
                        variable=var,
                        font=get_ctk_font(12),
                        text_color=self.colors.fg,
                        fg_color=self.colors.accent,
                        command=self._update_playground_preview,
                    ).pack(anchor="w", pady=3)
                else:
                    tk.Checkbutton(
                        mod_scroll_target,
                        text=label,
                        variable=var,
                        font=("Segoe UI", 10),
                        bg=self.colors.bg,
                        fg=self.colors.fg,
                        selectcolor=self.colors.input_bg,
                        command=self._update_playground_preview,
                    ).pack(anchor="w")

        # Snip Image Frame (inside action_config_frame, shown only for Snip mode)
        self.snip_image_frame = (
            ctk.CTkFrame(self.action_config_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(self.action_config_frame, bg=self.colors.bg)
        )
        # Initially hidden - shown only for action_snip mode

        if self.use_ctk:
            snip_img_header = None
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                snip_img_header = renderer.get_ctk_image("🖼️", size=18)
            ctk.CTkLabel(
                self.snip_image_frame,
                text=" Image for Snip Test:",
                image=snip_img_header,
                compound="left",
                font=get_ctk_font(13),
                **get_ctk_label_colors(self.colors),
            ).pack(anchor="w", pady=(8, 8))
        else:
            tk.Label(
                self.snip_image_frame,
                text="🖼️ Image for Snip Test:",
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(anchor="w", pady=(5, 5))

        # Image container
        if self.use_ctk:
            self.image_container_frame = ctk.CTkFrame(
                self.snip_image_frame,
                fg_color=self.colors.surface0,
                corner_radius=6,
                border_width=1,
                border_color=self.colors.border,
            )
        else:
            self.image_container_frame = tk.Frame(
                self.snip_image_frame,
                bg=self.colors.surface0,
                highlightbackground=self.colors.border,
                highlightthickness=1,
            )
        self.image_container_frame.pack(fill="x", pady=(0, 10))

        self.playground_camera_icon = None
        if self.use_ctk:
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                self.playground_camera_icon = renderer.get_ctk_image("📷", size=48)

            self.image_drop_zone = ctk.CTkLabel(
                self.image_container_frame,
                text=" No image selected",
                image=self.playground_camera_icon,
                compound="top",
                font=get_ctk_font(13),
                text_color=self.colors.blockquote,
            )
        else:
            self.image_drop_zone = tk.Label(
                self.image_container_frame,
                text="📷 No image selected",
                font=("Segoe UI", 10),
                bg=self.colors.surface0,
                fg=self.colors.blockquote,
            )
        self.image_drop_zone.pack(fill="both", expand=True, padx=10, pady=20)

        # Image buttons
        btn_row = (
            ctk.CTkFrame(self.snip_image_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(self.snip_image_frame, bg=self.colors.bg)
        )
        btn_row.pack(fill="x", pady=(0, 10))

        create_emoji_button(
            btn_row, "Select", "📁", self.colors, "secondary", 90, 34, self._select_playground_image
        ).pack(side="left", padx=3)
        create_emoji_button(btn_row, "Snip", "✂️", self.colors, "primary", 90, 34, self._snip_playground_image).pack(
            side="left", padx=3
        )
        create_emoji_button(
            btn_row, "Paste", "📋", self.colors, "secondary", 90, 34, self._paste_playground_image
        ).pack(side="left", padx=3)
        create_emoji_button(btn_row, "Clear", "🗑️", self.colors, "danger", 80, 34, self._clear_playground_image).pack(
            side="left", padx=3
        )

        # Audio Recording Frame (inside action_config_frame, shown only for Audio mode)
        self.audio_record_frame = (
            ctk.CTkFrame(self.action_config_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(self.action_config_frame, bg=self.colors.bg)
        )
        # Initially hidden - shown only for action_audio mode

        if self.use_ctk:
            audio_header_img = None
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                audio_header_img = renderer.get_ctk_image("🎙️", size=18)
            ctk.CTkLabel(
                self.audio_record_frame,
                text=" Audio Recording:",
                image=audio_header_img,
                compound="left",
                font=get_ctk_font(13),
                **get_ctk_label_colors(self.colors),
            ).pack(anchor="w", pady=(8, 8))
        else:
            tk.Label(
                self.audio_record_frame,
                text="🎙️ Audio Recording:",
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(anchor="w", pady=(5, 5))

        # Device selection row
        device_row = (
            ctk.CTkFrame(self.audio_record_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(self.audio_record_frame, bg=self.colors.bg)
        )
        device_row.pack(fill="x", pady=(0, 8))

        if self.use_ctk:
            ctk.CTkLabel(
                device_row, text="Device:", font=get_ctk_font(12), width=60, **get_ctk_label_colors(self.colors)
            ).pack(side="left")
            self.playground_audio_device_var = tk.StringVar()
            self.playground_audio_device_combo = ctk.CTkComboBox(
                device_row,
                variable=self.playground_audio_device_var,
                values=["(Loading...)"],
                width=280,
                height=32,
                state="readonly",
                font=get_ctk_font(12),
                **get_ctk_combobox_colors(self.colors),
            )
            self.playground_audio_device_combo.pack(side="left", padx=(8, 8), fill="x", expand=True)

            # Refresh button
            refresh_img = None
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                refresh_img = renderer.get_ctk_image("🔄", size=16)
            ctk.CTkButton(
                device_row,
                text="",
                image=refresh_img,
                width=32,
                height=32,
                **get_ctk_button_colors(self.colors, "secondary"),
                command=self._refresh_audio_devices,
            ).pack(side="left")
        else:
            tk.Label(device_row, text="Device:", font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg).pack(
                side="left"
            )
            self.playground_audio_device_var = tk.StringVar()
            from tkinter import ttk

            self.playground_audio_device_combo = ttk.Combobox(
                device_row,
                textvariable=self.playground_audio_device_var,
                values=["(Loading...)"],
                state="readonly",
                width=35,
            )
            self.playground_audio_device_combo.pack(side="left", padx=(8, 8), fill="x", expand=True)
            tk.Button(
                device_row, text="🔄", command=self._refresh_audio_devices, bg=self.colors.surface1, fg=self.colors.fg
            ).pack(side="left")

        # Recording controls row
        record_row = (
            ctk.CTkFrame(self.audio_record_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(self.audio_record_frame, bg=self.colors.bg)
        )
        record_row.pack(fill="x", pady=(0, 8))

        self.playground_record_btn = create_emoji_button(
            record_row, "Record", "🔴", self.colors, "primary", 100, 36, self._toggle_playground_recording
        )
        self.playground_record_btn.pack(side="left", padx=(0, 8))

        create_emoji_button(
            record_row, "Upload", "📁", self.colors, "secondary", 100, 36, self._select_playground_audio_file
        ).pack(side="left", padx=(0, 8))

        # Duration label
        if self.use_ctk:
            self.playground_audio_duration = ctk.CTkLabel(
                record_row, text="00:00", font=get_ctk_font(14, "bold"), text_color=self.colors.fg
            )
        else:
            self.playground_audio_duration = tk.Label(
                record_row, text="00:00", font=("Segoe UI", 12, "bold"), bg=self.colors.bg, fg=self.colors.fg
            )
        self.playground_audio_duration.pack(side="left", padx=(0, 15))

        # Clear button
        self.playground_audio_clear_btn = create_emoji_button(
            record_row, "Clear", "🗑️", self.colors, "danger", 80, 36, self._clear_playground_audio
        )
        self.playground_audio_clear_btn.pack(side="left")

        # Audio status label
        if self.use_ctk:
            self.playground_audio_status = ctk.CTkLabel(
                self.audio_record_frame,
                text="No audio recorded",
                font=get_ctk_font(12),
                text_color=self.colors.blockquote,
            )
        else:
            self.playground_audio_status = tk.Label(
                self.audio_record_frame,
                text="No audio recorded",
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.blockquote,
            )
        self.playground_audio_status.pack(anchor="w", pady=(0, 5))

        # Initialize audio state
        self.playground_audio_data = None
        self.playground_audio_mime = None
        self.playground_is_recording = False
        self.playground_recorder = None
        self.playground_record_start = None
        self.playground_audio_devices = []

        # Sample text container (for hiding/showing)
        self.sample_text_container = (
            ctk.CTkFrame(scroll_left, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_left, bg=self.colors.bg)
        )
        self.sample_text_container.pack(fill="x")

        if self.use_ctk:
            sample_img = None
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                sample_img = renderer.get_ctk_image("📄", size=18)

            ctk.CTkLabel(
                self.sample_text_container,
                text=" Sample Text:",
                image=sample_img,
                compound="left",
                font=get_ctk_font(13),
                **get_ctk_label_colors(self.colors),
            ).pack(anchor="w", pady=(12, 8))
            self.playground_sample_text = ctk.CTkTextbox(
                self.sample_text_container, height=120, font=get_ctk_font(12), **get_ctk_textbox_colors(self.colors)
            )
        else:
            tk.Label(
                self.sample_text_container,
                text="📄 Sample Text:",
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(anchor="w", pady=(10, 5))
            self.playground_sample_text = tk.Text(
                self.sample_text_container,
                height=5,
                font=("Segoe UI", 10),
                bg=self.colors.input_bg,
                fg=self.colors.fg,
                wrap="word",
            )
        self.playground_sample_text.pack(fill="x", pady=(0, 10))

        # Bind sample text changes
        if self.use_ctk:
            self.playground_sample_text.insert("0.0", "The quick brown fox jumps over the lazy dog.")
            self.playground_sample_text.bind("<KeyRelease>", lambda e: self._update_playground_preview())
        else:
            self.playground_sample_text.insert("1.0", "The quick brown fox jumps over the lazy dog.")
            self.playground_sample_text.bind("<KeyRelease>", lambda e: self._update_playground_preview())

        # Standard API Settings container (hidden in TTS mode)
        self.standard_api_container = (
            ctk.CTkFrame(scroll_left, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_left, bg=self.colors.bg)
        )
        self.standard_api_container.pack(fill="x")

        # API Settings section (below sample text)
        create_section_header(self.standard_api_container, "API Settings", self.colors, "⚙️")

        api_frame = (
            ctk.CTkFrame(self.standard_api_container, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(self.standard_api_container, bg=self.colors.bg)
        )
        api_frame.pack(fill="x", pady=(0, 10))

        # Provider & Model
        if self.use_ctk:
            ctk.CTkLabel(
                api_frame,
                text="Provider:",
                font=get_ctk_font(12),
                width=80,
                anchor="w",
                **get_ctk_label_colors(self.colors),
            ).pack(side="left")
            self.playground_provider_var = tk.StringVar(value="google")
            ctk.CTkComboBox(
                api_frame,
                variable=self.playground_provider_var,
                values=["google", "openrouter", "custom"],
                width=130,
                height=32,
                state="readonly",
                font=get_ctk_font(12),
                **get_ctk_combobox_colors(self.colors),
            ).pack(side="left", padx=(8, 15))

            ctk.CTkLabel(
                api_frame,
                text="Model:",
                font=get_ctk_font(12),
                width=60,
                anchor="w",
                **get_ctk_label_colors(self.colors),
            ).pack(side="left")
            self.playground_model_var = tk.StringVar()
            ctk.CTkEntry(
                api_frame,
                textvariable=self.playground_model_var,
                font=get_ctk_font(12),
                height=32,
                **get_ctk_entry_colors(self.colors),
            ).pack(side="left", padx=(8, 0), fill="x", expand=True)
        else:
            from tkinter import ttk

            tk.Label(api_frame, text="Provider:", font=("Segoe UI", 9), bg=self.colors.bg, fg=self.colors.fg).pack(
                side="left"
            )
            self.playground_provider_var = tk.StringVar(value="google")
            ttk.Combobox(
                api_frame,
                textvariable=self.playground_provider_var,
                values=["google", "openrouter", "custom"],
                state="readonly",
                width=12,
            ).pack(side="left", padx=(5, 10))

            tk.Label(api_frame, text="Model:", font=("Segoe UI", 9), bg=self.colors.bg, fg=self.colors.fg).pack(
                side="left"
            )
            self.playground_model_var = tk.StringVar()
            tk.Entry(
                api_frame,
                textvariable=self.playground_model_var,
                font=("Segoe UI", 9),
                bg=self.colors.input_bg,
                fg=self.colors.fg,
                width=15,
            ).pack(side="left", padx=(5, 0), fill="x", expand=True)

        # Load defaults from active profile
        try:
            from .... import web_server as _ws

            default_provider = _ws.get_active_setting("provider", "google")
            self.playground_provider_var.set(default_provider)
            self.playground_model_var.set(_ws.get_active_setting("model", ""))
        except:
            pass

        # Test button
        btn_frame = (
            ctk.CTkFrame(self.standard_api_container, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(self.standard_api_container, bg=self.colors.bg)
        )
        btn_frame.pack(fill="x", pady=(10, 0))

        if self.use_ctk:
            test_text = "🧪 Test with API"
            test_img = None

            # Initialize status icons cache
            self.status_icons = {}

            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                test_img = renderer.get_ctk_image("🧪", size=20)
                if test_img:
                    test_text = "Test with API"

                # Pre-cache status icons to prevent GC/TclError
                self.status_icons["loading"] = renderer.get_ctk_image("⏳", size=16)
                self.status_icons["success"] = renderer.get_ctk_image("✅", size=16)

            ctk.CTkButton(
                btn_frame,
                text=test_text,
                image=test_img,
                compound="left" if test_img else None,
                font=get_ctk_font(14),
                width=160,
                height=42,
                **get_ctk_button_colors(self.colors, "primary"),
                command=self._test_playground_with_api,
            ).pack(side="left", padx=(0, 15))
            self.playground_test_status = ctk.CTkLabel(
                btn_frame, text="", font=get_ctk_font(12), text_color=self.colors.fg
            )
        else:
            tk.Button(
                btn_frame,
                text="🧪 Test with API",
                font=("Segoe UI", 10),
                bg=self.colors.accent,
                fg=self.colors.accent_fg,
                command=self._test_playground_with_api,
            ).pack(side="left", padx=(0, 10))
            self.playground_test_status = tk.Label(
                btn_frame, text="", font=("Segoe UI", 9), bg=self.colors.bg, fg=self.colors.fg
            )
        self.playground_test_status.pack(side="left")

        # TTS Playground container (hidden by default, shown only in TTS mode)
        self.tts_playground_frame = (
            ctk.CTkFrame(scroll_left, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_left, bg=self.colors.bg)
        )
        # Initially hidden - shown only when TTS mode is selected
        self._create_tts_playground_controls(self.tts_playground_frame)

        # TTS state initialization
        self.tts_pg_audio_data = None  # WAV audio bytes
        self.tts_pg_pcm_data = None  # PCM audio bytes
        self.tts_pg_audio_duration = 0.0
        self.tts_pg_is_playing = False
        self.tts_pg_playback_position = 0.0
        self.tts_pg_is_generating = False
        self.tts_pg_is_directing = False
        self.tts_pg_recorder = None

        # Right panel: Preview
        right_panel = (
            ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=self.colors.bg)
        )
        right_panel.pack(side="left", fill="both", expand=True)

        # System prompt preview
        sys_header = (
            ctk.CTkFrame(right_panel, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(right_panel, bg=self.colors.bg)
        )
        sys_header.pack(fill="x", pady=(0, 5))

        if self.use_ctk:
            # Header with emoji image
            kwargs = {
                "text": " System Prompt Preview",
                "font": get_ctk_font(14, "bold"),
                "text_color": self.colors.accent,
            }
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                img = renderer.get_ctk_image("📝", size=20)
                if img:
                    kwargs["image"] = img
                    kwargs["compound"] = "left"

            ctk.CTkLabel(sys_header, **kwargs).pack(side="left")
            ctk.CTkButton(
                sys_header,
                text="Copy",
                font=get_ctk_font(12),
                width=80,
                height=30,
                **get_ctk_button_colors(self.colors, "secondary"),
                command=lambda: self._copy_preview("system"),
            ).pack(side="right")
            self.playground_system_preview = ctk.CTkTextbox(
                right_panel, font=get_ctk_font(12), state="disabled", **get_ctk_textbox_colors(self.colors)
            )
        else:
            tk.Label(
                sys_header,
                text="📝 System Prompt Preview",
                font=("Segoe UI", 11, "bold"),
                bg=self.colors.bg,
                fg=self.colors.accent,
            ).pack(side="left")
            tk.Button(
                sys_header, text="📋 Copy", font=("Segoe UI", 8), command=lambda: self._copy_preview("system")
            ).pack(side="right")
            self.playground_system_preview = tk.Text(
                right_panel,
                font=("Consolas", 10),
                bg=self.colors.surface0,
                fg=self.colors.fg,
                wrap="word",
                state="disabled",
            )
        self.playground_system_preview.pack(fill="both", expand=True, pady=(0, 10))

        # User message preview
        user_header = (
            ctk.CTkFrame(right_panel, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(right_panel, bg=self.colors.bg)
        )
        user_header.pack(fill="x", pady=(0, 5))

        if self.use_ctk:
            # Header with emoji image
            kwargs = {
                "text": " User Message Preview",
                "font": get_ctk_font(14, "bold"),
                "text_color": self.colors.accent,
            }
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                img = renderer.get_ctk_image("💬", size=20)
                if img:
                    kwargs["image"] = img
                    kwargs["compound"] = "left"

            ctk.CTkLabel(user_header, **kwargs).pack(side="left")
            ctk.CTkButton(
                user_header,
                text="Copy",
                font=get_ctk_font(12),
                width=80,
                height=30,
                **get_ctk_button_colors(self.colors, "secondary"),
                command=lambda: self._copy_preview("user"),
            ).pack(side="right")
            self.playground_user_preview = ctk.CTkTextbox(
                right_panel, font=get_ctk_font(12), state="disabled", **get_ctk_textbox_colors(self.colors)
            )
        else:
            tk.Label(
                user_header,
                text="💬 User Message Preview",
                font=("Segoe UI", 11, "bold"),
                bg=self.colors.bg,
                fg=self.colors.accent,
            ).pack(side="left")
            tk.Button(
                user_header, text="📋 Copy", font=("Segoe UI", 8), command=lambda: self._copy_preview("user")
            ).pack(side="right")
            self.playground_user_preview = tk.Text(
                right_panel,
                font=("Consolas", 10),
                bg=self.colors.surface0,
                fg=self.colors.fg,
                wrap="word",
                state="disabled",
            )
        self.playground_user_preview.pack(fill="both", expand=True)

        # Metadata Footer
        meta_frame = (
            ctk.CTkFrame(right_panel, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(right_panel, bg=self.colors.bg)
        )
        meta_frame.pack(fill="x", pady=(10, 0))

        if self.use_ctk:
            meta_img = None
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                meta_img = renderer.get_ctk_image("📊", size=18)

            self.playground_meta_label = ctk.CTkLabel(
                meta_frame,
                text=" Tokens: ~0 | Type: edit | Mode: Replace",
                image=meta_img,
                compound="left",
                font=get_ctk_font(12),
                text_color=self.colors.blockquote,
            )
        else:
            self.playground_meta_label = tk.Label(
                meta_frame,
                text="📊 Tokens: ~0 | Type: edit | Mode: Replace",
                font=("Segoe UI", 9),
                bg=self.colors.bg,
                fg=self.colors.blockquote,
            )
        self.playground_meta_label.pack(anchor="w")

        # Initial preview update and population
        self._populate_playground_actions("action_text")
        self.root.after(100, self._update_playground_preview)

    def _populate_playground_actions(self, mode):
        """Populate the action combo box based on selected mode."""
        if mode == "action_text":
            tool_key = "text_edit_tool"
        elif mode == "action_snip":
            tool_key = "snip_tool"
        else:  # action_audio
            tool_key = "audio_tool"
        tool_data = self.options_data.get(tool_key, {})

        # Get actions (exclude _settings)
        actions = [k for k in sorted(tool_data.keys()) if k != "_settings"]

        if self.use_ctk:
            self.playground_action_combo.configure(values=actions)
            if actions:
                self.playground_action_combo.set(actions[0])
                self.playground_action_var.set(actions[0])
            else:
                self.playground_action_combo.set("")
                self.playground_action_var.set("")
        else:
            self.playground_action_combo["values"] = actions
            if actions:
                self.playground_action_combo.current(0)
            else:
                self.playground_action_var.set("")

        # Trigger preview update
        self._on_playground_action_change()

    def _on_playground_mode_change(self):
        """Handle mode switch between text, snip, audio, and TTS."""
        mode = self.playground_mode_var.get()

        if mode == "tts":
            # TTS mode: hide standard controls, show TTS controls
            self.action_config_frame.pack_forget()
            self.sample_text_container.pack_forget()
            self.snip_image_frame.pack_forget()
            self.audio_record_frame.pack_forget()
            self.standard_api_container.pack_forget()
            self.tts_playground_frame.pack(fill="x")
            self._update_tts_playground_preview()
            return

        # Non-TTS modes: hide TTS controls, show standard controls
        self.tts_playground_frame.pack_forget()
        self.standard_api_container.pack(fill="x")

        # Always show action config frame
        self.action_config_frame.pack(fill="x", pady=(0, 10))
        self._populate_playground_actions(mode)

        # Show/Hide mode-specific containers
        if mode == "action_text":
            self.sample_text_container.pack(fill="x", pady=(15, 0))
            self.snip_image_frame.pack_forget()
            self.audio_record_frame.pack_forget()
        elif mode == "action_snip":
            self.sample_text_container.pack_forget()
            self.snip_image_frame.pack(fill="x", pady=(8, 0))
            self.audio_record_frame.pack_forget()
        elif mode == "action_audio":
            self.sample_text_container.pack_forget()
            self.snip_image_frame.pack_forget()
            self.audio_record_frame.pack(fill="x", pady=(8, 0))
            # Initialize audio devices on first switch to audio mode
            self._refresh_audio_devices()

        self._update_playground_preview()

    def _on_playground_action_change(self, event=None):
        """Handle action selection change."""
        action_name = self.playground_action_var.get()
        if action_name in ("_Custom", "_Ask"):
            self.custom_input_frame.pack(fill="x", pady=(5, 0))
        else:
            self.custom_input_frame.pack_forget()
        self._update_playground_preview()

    def _update_playground_preview(self, event=None):
        """
        Update the live preview based on current action configuration.
        Matches logic in text_edit_tool.py _process_option.
        """
        # Guard: Playground tab may not be loaded yet (lazy loading)
        if not hasattr(self, "playground_mode_var"):
            return

        mode = self.playground_mode_var.get()
        if mode == "tts":
            self._update_tts_playground_preview()
            return

        action_name = self.playground_action_var.get()
        if not action_name:
            return

        if mode == "action_text":
            tool_key = "text_edit_tool"
        elif mode == "action_snip":
            tool_key = "snip_tool"
        else:  # action_audio
            tool_key = "audio_tool"
        tool_data = self.options_data.get(tool_key, {})
        action_data = tool_data.get(action_name, {})

        # Determine global vs tool settings
        global_settings = self.options_data.get("_global_settings", {})

        # --- 1. System Prompt Construction ---
        system_parts = []

        # Get base system prompt from action
        if self.current_action == action_name:
            # Use live editor value
            if self.use_ctk:
                sys_prompt = self.editor_widgets["system_prompt"].get("0.0", "end").strip()
            else:
                sys_prompt = self.editor_widgets["system_prompt"].get("1.0", "end").strip()
        else:
            sys_prompt = action_data.get("system_prompt", "")

        if sys_prompt:
            system_parts.append(sys_prompt)

        # Add modifier injections (always appended)
        modifier_injections = []
        for key, var in self.playground_modifier_vars.items():
            if var.get():
                for mod in global_settings.get("modifiers", []):
                    if mod.get("key") == key:
                        injection = mod.get("injection", "")
                        if injection:
                            modifier_injections.append(injection)

        if modifier_injections:
            system_parts.append("\n".join(modifier_injections))

        full_system = "\n\n".join(system_parts)

        # --- 2. User Message Construction ---
        user_parts = []

        # Get task
        custom_input = self.playground_custom_var.get()
        task = ""

        if action_name == "_Custom" and custom_input:
            template = self._get_current_setting(
                tool_key, "custom_task_template", "Apply the following change to the text: {custom_input}"
            )
            task = template.format(custom_input=custom_input)
        elif action_name == "_Ask" and custom_input:
            template = self._get_current_setting(
                tool_key, "ask_task_template", "Answer the following question about the text: {custom_input}"
            )
            task = template.format(custom_input=custom_input)
        else:
            if self.current_action == action_name:
                task = self.editor_widgets["task_var"].get()
            else:
                task = action_data.get("task", "")

            # Handle {input} placeholder for other actions if they use it
            if "{input}" in task and custom_input:
                task = task.replace("{input}", custom_input)

        if task:
            user_parts.append(task)

        # Add output rules based on type
        if self.current_action == action_name:
            prompt_type = self.editor_widgets["prompt_type_var"].get()
        else:
            prompt_type = action_data.get("prompt_type", "edit")

        if prompt_type == "general":
            output_rules = self._get_current_setting(tool_key, "base_output_rules_general", "")
        else:
            output_rules = self._get_current_setting(tool_key, "base_output_rules_edit", "")

        if output_rules:
            user_parts.append(output_rules)

        # Add text with delimiters
        text_delimiter = self._get_current_setting(tool_key, "text_delimiter", "\n\n<text_to_process>\n")
        text_delimiter_close = self._get_current_setting(tool_key, "text_delimiter_close", "\n</text_to_process>")

        if self.use_ctk:
            sample_text = self.playground_sample_text.get("0.0", "end").strip()
        else:
            sample_text = self.playground_sample_text.get("1.0", "end").strip()

        user_message = "\n\n".join(user_parts)
        if sample_text and mode == "action_text":
            user_message += text_delimiter + sample_text + text_delimiter_close

        self._set_preview_text(self.playground_system_preview, full_system, "system")
        self._set_preview_text(self.playground_user_preview, user_message, "user")

        # Update metadata
        total_chars = len(full_system) + len(user_message)
        token_estimate = total_chars // 4

        # Determine show_chat status based on tool type
        if self.current_action == action_name:
            show_chat = self.editor_widgets["show_chat_var"].get()
        else:
            # Use correct field name based on tool
            if mode == "action_text":
                show_chat = action_data.get("show_chat_window_instead_of_replace", False)
            else:  # snip_tool or audio_tool
                show_chat = action_data.get("show_chat_window", True)

        # Determine response mode label based on tool type
        if show_chat:
            response_mode = "Chat Window"
        else:
            if mode == "action_text":
                response_mode = "Replace"
            elif mode == "action_snip":
                response_mode = "Copy"
            else:  # action_audio
                response_mode = "Result Panel"

        # Build metadata text - Type is only for TextEditTool
        if mode == "action_text":
            meta_text = f"📊 Tokens: ~{token_estimate} | Type: {prompt_type} | Mode: {response_mode}"
        else:
            meta_text = f"📊 Tokens: ~{token_estimate} | Mode: {response_mode}"

        if self.use_ctk:
            self.playground_meta_label.configure(text=meta_text)
        else:
            self.playground_meta_label.configure(text=meta_text)

    def _set_preview_text(self, widget, text, preview_type):
        """Helper to set preview text."""
        if self.use_ctk:
            widget.configure(state="normal")
            widget.delete("0.0", "end")
            widget.insert("0.0", text)
            widget.configure(state="disabled")
        else:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
            widget.configure(state="disabled")

    def _copy_preview(self, preview_type):
        """Copy preview content to clipboard."""
        widget = self.playground_system_preview if preview_type == "system" else self.playground_user_preview
        if self.use_ctk:
            content = widget.get("0.0", "end").strip()
        else:
            content = widget.get("1.0", "end").strip()
        try:
            pyperclip.copy(content)
            if self.use_ctk:
                ok_img = self.status_icons.get("success") if hasattr(self, "status_icons") else None
                self.playground_test_status.configure(
                    text=" Copied!", image=ok_img, compound="left", text_color=self.colors.accent_green
                )
            else:
                self.playground_test_status.configure(text="✅ Copied!", fg=self.colors.accent_green)
            self.root.after(2000, lambda: self._clear_test_status())
        except Exception as e:
            if self.use_ctk:
                self.playground_test_status.configure(text=f"❌ Copy failed: {e}", text_color=self.colors.accent_red)
            else:
                self.playground_test_status.configure(text=f"❌ Copy failed: {e}", fg=self.colors.accent_red)

    # --- Image Handling ---

    def _select_playground_image(self):
        """Select an image file for playground testing."""
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp")])
        if path:
            self._load_playground_image(path)

    def _paste_playground_image(self):
        """Paste image from clipboard."""
        try:
            from PIL import Image, ImageGrab

            img = ImageGrab.grabclipboard()
            if img:
                if img.mode == "RGBA":
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    bg.paste(img, mask=img.split()[3])
                    img = bg

                from io import BytesIO

                buffered = BytesIO()
                img.save(buffered, format="JPEG")
                img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")

                self.playground_image_base64 = img_str
                self.playground_image_mime = "image/jpeg"
                self.playground_image_name = "Pasted Image"

                self._show_image_preview(img)
                self._update_playground_preview()
            else:
                messagebox.showinfo("Paste", "No image in clipboard", parent=self.root)
        except Exception as e:
            messagebox.showerror("Paste Error", str(e), parent=self.root)

    def _load_playground_image(self, filepath):
        """Load image from file."""
        try:
            from io import BytesIO

            from PIL import Image

            img = Image.open(filepath)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            buffered = BytesIO()
            img.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")

            self.playground_image_base64 = img_str
            self.playground_image_mime = "image/jpeg"
            self.playground_image_name = os.path.basename(filepath)

            self._show_image_preview(img)
            self._update_playground_preview()
        except ImportError:
            with open(filepath, "rb") as f:
                img_bytes = f.read()
                self.playground_image_base64 = base64.b64encode(img_bytes).decode("utf-8")
                self.playground_image_mime = "image/jpeg"
                self.playground_image_name = os.path.basename(filepath)
                self._show_image_preview_text_only(os.path.basename(filepath), f"{len(img_bytes) // 1024} KB")
                self._update_playground_preview()
        except Exception as e:
            messagebox.showerror("Image Error", f"Failed to load image: {e}", parent=self.root)

    def _show_image_preview(self, pil_image):
        """Show thumbnail preview of image."""
        try:
            if self.use_ctk:
                ctk_img = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(100, 100))
                self.image_drop_zone.configure(image=ctk_img, text="")
                self.image_drop_zone._image = ctk_img  # Keep reference
            else:
                from PIL import ImageTk

                pil_image.thumbnail((100, 100))
                tk_img = ImageTk.PhotoImage(pil_image)
                self.image_drop_zone.configure(image=tk_img, text="")
                self.image_drop_zone.image = tk_img
        except Exception:
            self.image_drop_zone.configure(text=f"📷 {self.playground_image_name}")

    def _show_image_preview_text_only(self, filename, size):
        """Fallback preview."""
        self.image_drop_zone.configure(text=f"📷 {filename}\n({size})")

    def _clear_playground_image(self):
        """Clear the selected image."""
        self.playground_image_base64 = None
        self.playground_image_mime = None
        self.playground_image_name = None
        if self.use_ctk:
            # Restore camera icon
            self.image_drop_zone.configure(image=self.playground_camera_icon, text=" No image selected")
        else:
            self.image_drop_zone.configure(image="", text="📷 No image selected")
            if hasattr(self.image_drop_zone, "image"):
                self.image_drop_zone.image = None
        self._update_playground_preview()

    def _snip_playground_image(self):
        """Capture screen snip and store as playground image (without testing)."""
        # Hide window to allow capture
        self.root.iconify()

        try:
            from ...core import GUICoordinator

            GUICoordinator.get_instance().request_snip_overlay(
                on_capture=self._on_playground_snip_image_captured, on_cancel=self._on_playground_snip_image_cancelled
            )
        except Exception as e:
            self.root.deiconify()
            messagebox.showerror("Error", f"Failed to start snip: {e}", parent=self.root)

    def _on_playground_snip_image_cancelled(self):
        """Handle snip image capture cancellation."""
        self.root.deiconify()
        if self.use_ctk:
            self.playground_test_status.configure(text="Snip cancelled", image=None, text_color=self.colors.surface2)
        else:
            self.playground_test_status.configure(text="Snip cancelled", fg=self.colors.surface2)

    def _on_playground_snip_image_captured(self, result):
        """Handle captured snip for image selection (not auto-test)."""
        # Restore window
        self.root.deiconify()

        # Store capture data
        self.playground_image_base64 = result.image_base64
        self.playground_image_mime = result.mime_type
        self.playground_image_name = f"Snip_{int(time.time())}.png"

        # Show preview
        try:
            from io import BytesIO

            from PIL import Image

            img_data = base64.b64decode(result.image_base64)
            pil_image = Image.open(BytesIO(img_data))
            self._show_image_preview(pil_image)
        except Exception:
            # Fallback to text preview
            self._show_image_preview_text_only(self.playground_image_name, "Captured")

        # Update preview
        self._update_playground_preview()

        # Update status
        if self.use_ctk:
            self.playground_test_status.configure(
                text="✅ Image captured", image=None, text_color=self.colors.accent_green
            )
        else:
            self.playground_test_status.configure(text="✅ Image captured", fg=self.colors.accent_green)
        self.root.after(2000, self._clear_test_status)

    def _on_playground_snip_captured(self, result):
        """Handle captured snip for Playground test."""
        # Restore window
        self.root.deiconify()

        # Store capture data
        self.playground_image_base64 = result.image_base64
        self.playground_image_mime = result.mime_type
        self.playground_image_name = f"Snip_{int(time.time())}.png"

        # Proceed with test
        self._continue_snip_test()

    def _on_playground_snip_cancelled(self):
        """Handle snip cancellation."""
        self.root.deiconify()
        if self.use_ctk:
            self.playground_test_status.configure(
                text="❌ Snipping cancelled", image=None, text_color=self.colors.surface2
            )
        else:
            self.playground_test_status.configure(text="❌ Snipping cancelled", fg=self.colors.surface2)

    # --- Audio Recording Methods ---

    def _select_playground_audio_file(self):
        """Open file dialog to upload an audio file."""
        file_path = filedialog.askopenfilename(
            title="Select Audio File", filetypes=[("Audio Files", "*.wav *.mp3 *.ogg *.m4a *.aac *.flac")]
        )
        if file_path:
            self._load_playground_audio(file_path)

    def _load_playground_audio(self, filepath):
        """Load audio from file."""
        try:
            with open(filepath, "rb") as f:
                data = f.read()

            self.playground_audio_data = data

            ext = os.path.splitext(filepath)[1].lower()
            mime_map = {
                ".wav": "audio/wav",
                ".mp3": "audio/mp3",
                ".ogg": "audio/ogg",
                ".m4a": "audio/m4a",
                ".aac": "audio/aac",
                ".flac": "audio/flac",
            }
            self.playground_audio_mime = mime_map.get(ext, "audio/wav")

            # Update UI
            filename = os.path.basename(filepath)
            size_kb = len(data) // 1024

            status_text = f"File: {filename} ({size_kb} KB)"

            if self.use_ctk:
                self.playground_audio_status.configure(text=status_text, text_color=self.colors.accent_green)
                self.playground_audio_duration.configure(text="FILE")
            else:
                self.playground_audio_status.configure(text=status_text, fg=self.colors.accent_green)
                self.playground_audio_duration.configure(text="FILE")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load audio: {e}", parent=self.root)

    def _refresh_audio_devices(self):
        """Refresh the list of available audio input devices."""
        try:
            from ....audio import get_default_input_device, list_input_devices

            devices = list_input_devices()
            self.playground_audio_devices = devices

            device_names = [d.get_display_name() for d in devices]

            if self.use_ctk:
                self.playground_audio_device_combo.configure(
                    values=device_names if device_names else ["(No devices found)"]
                )
            else:
                self.playground_audio_device_combo["values"] = device_names if device_names else ["(No devices found)"]

            # Try to set default device
            if devices:
                try:
                    default = get_default_input_device()
                    if default:
                        default_name = default.get_display_name()
                        if default_name in device_names:
                            self.playground_audio_device_var.set(default_name)
                        else:
                            self.playground_audio_device_var.set(device_names[0])
                    else:
                        self.playground_audio_device_var.set(device_names[0])
                except Exception:
                    self.playground_audio_device_var.set(device_names[0])
            else:
                self.playground_audio_device_var.set("(No devices found)")

        except ImportError:
            if self.use_ctk:
                self.playground_audio_device_combo.configure(values=["(Audio module not available)"])
            else:
                self.playground_audio_device_combo["values"] = ["(Audio module not available)"]
            self.playground_audio_device_var.set("(Audio module not available)")
        except Exception as e:
            print(f"[PromptEditor] Error loading audio devices: {e}")
            if self.use_ctk:
                self.playground_audio_device_combo.configure(values=[f"(Error: {str(e)[:30]})"])
            else:
                self.playground_audio_device_combo["values"] = [f"(Error: {str(e)[:30]})"]

    def _toggle_playground_recording(self):
        """Toggle audio recording on/off."""
        if self.playground_is_recording:
            self._stop_playground_recording()
        else:
            self._start_playground_recording()

    def _start_playground_recording(self):
        """Start audio recording."""
        try:
            from ....audio import AudioRecorder, list_input_devices

            # Find selected device
            selected_name = self.playground_audio_device_var.get()
            device = None
            for d in self.playground_audio_devices:
                if d.get_display_name() == selected_name:
                    device = d
                    break

            if not device:
                messagebox.showerror("Recording Error", "Please select an audio device.", parent=self.root)
                return

            # Create recorder with device
            self.playground_recorder = AudioRecorder(device)

            # Start stream and recording (Unified API)
            self.playground_recorder.start_stream()
            self.playground_recorder.start_recording_unified()

            self.playground_is_recording = True
            self.playground_record_start = time.time()

            # Update UI
            if self.use_ctk:
                self.playground_record_btn.configure(text="⏹️ Stop")
                self.playground_audio_status.configure(text="Recording...", text_color=self.colors.accent_red)
            else:
                self.playground_record_btn.configure(text="⏹️ Stop")
                self.playground_audio_status.configure(text="Recording...", fg=self.colors.accent_red)

            # Start duration update
            self._update_playground_recording_duration()

        except ImportError as e:
            messagebox.showerror("Recording Error", f"Audio module not available: {e}", parent=self.root)
        except Exception as e:
            messagebox.showerror("Recording Error", f"Failed to start recording: {e}", parent=self.root)

    def _stop_playground_recording(self):
        """Stop audio recording and save data."""
        if not self.playground_recorder:
            return

        try:
            # Stop recording (Unified API)
            audio_data = self.playground_recorder.stop_recording_unified()
            self.playground_recorder.stop_stream()

            self.playground_is_recording = False
            if audio_data:
                self.playground_audio_data = audio_data
                self.playground_audio_mime = "audio/wav"

                # Calculate duration
                duration = time.time() - self.playground_record_start if self.playground_record_start else 0
                size_kb = len(audio_data) // 1024

                # Update UI
                status_text = f"Recorded: {self._format_playground_duration(duration)} ({size_kb} KB)"
                if self.use_ctk:
                    self.playground_record_btn.configure(text="🔴 Record")
                    self.playground_audio_status.configure(text=status_text, text_color=self.colors.accent_green)
                else:
                    self.playground_record_btn.configure(text="🔴 Record")
                    self.playground_audio_status.configure(text=status_text, fg=self.colors.accent_green)
            else:
                if self.use_ctk:
                    self.playground_record_btn.configure(text="🔴 Record")
                    self.playground_audio_status.configure(
                        text="Recording failed - no audio data", text_color=self.colors.accent_red
                    )
                else:
                    self.playground_record_btn.configure(text="🔴 Record")
                    self.playground_audio_status.configure(
                        text="Recording failed - no audio data", fg=self.colors.accent_red
                    )

        except Exception as e:
            print(f"[PromptEditor] Error stopping recording: {e}")
            if self.use_ctk:
                self.playground_record_btn.configure(text="🔴 Record")
                self.playground_audio_status.configure(text=f"Error: {str(e)[:40]}", text_color=self.colors.accent_red)
            else:
                self.playground_record_btn.configure(text="🔴 Record")
                self.playground_audio_status.configure(text=f"Error: {str(e)[:40]}", fg=self.colors.accent_red)
        finally:
            if self.playground_recorder:
                try:
                    self.playground_recorder.cleanup()
                except:
                    pass
            self.playground_recorder = None

    def _update_playground_recording_duration(self):
        """Update the recording duration display."""
        if not self.playground_is_recording:
            return

        duration = time.time() - self.playground_record_start if self.playground_record_start else 0
        duration_text = self._format_playground_duration(duration)

        if self.use_ctk:
            self.playground_audio_duration.configure(text=duration_text)
        else:
            self.playground_audio_duration.configure(text=duration_text)

        # Schedule next update
        if self.playground_is_recording and self.root:
            self.root.after(100, self._update_playground_recording_duration)

    def _format_playground_duration(self, seconds: float) -> str:
        """Format duration in MM:SS format."""
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

    def _clear_playground_audio(self):
        """Clear recorded or loaded audio data."""
        # Stop recording if in progress
        if self.playground_is_recording:
            self._stop_playground_recording()

        self.playground_audio_data = None
        self.playground_audio_mime = None

        if self.use_ctk:
            self.playground_audio_duration.configure(text="00:00")
            self.playground_audio_status.configure(text="No audio", text_color=self.colors.blockquote)
        else:
            self.playground_audio_duration.configure(text="00:00")
            self.playground_audio_status.configure(text="No audio", fg=self.colors.blockquote)

    # --- API Testing ---

    def _test_playground_with_api(self):
        """Send the current prompt to the API for testing (Streaming)."""
        # Ensure preview is up to date with any edits
        self._update_playground_preview()

        mode = self.playground_mode_var.get()

        # Snip mode: Use existing image (don't auto-snip)
        if mode == "action_snip":
            if not self.playground_image_base64:
                messagebox.showinfo(
                    "Image Required", "Please select or snip an image before testing.", parent=self.root
                )
                return
            # Proceed directly to test with existing image
            self._continue_snip_test()
            return

        # Audio mode: Check for recorded or loaded audio
        if mode == "action_audio" and not self.playground_audio_data:
            messagebox.showinfo("Audio Required", "Please record or upload audio before testing.", parent=self.root)
            return

        if self.use_ctk:
            try:
                status_img = self.status_icons.get("loading") if hasattr(self, "status_icons") else None
                self.playground_test_status.configure(
                    text=" Sending request...", image=status_img, compound="left", text_color=self.colors.fg
                )
            except Exception:
                try:
                    self.playground_test_status.configure(
                        text="⏳ Sending request...", image=None, compound="left", text_color=self.colors.fg
                    )
                except:
                    pass
        else:
            self.playground_test_status.configure(text="⏳ Sending request...", fg=self.colors.fg)
        self.root.update()

        params = {}

        try:
            if mode == "action_audio":
                params = self._prepare_audio_request()
            else:  # action_text
                params = self._prepare_text_request()

            if params.get("error"):
                raise ValueError(params["error"])

            self._run_streaming_test(params)

        except Exception as e:
            if self.use_ctk:
                self.playground_test_status.configure(text=f"❌ Error: {e}", text_color=self.colors.accent_red)
            else:
                self.playground_test_status.configure(text=f"❌ Error: {e}", fg=self.colors.accent_red)

    def _continue_snip_test(self):
        """Continue with API test after snip capture."""
        try:
            if self.use_ctk:
                self.playground_test_status.configure(
                    text="⏳ Sending request...", image=None, text_color=self.colors.fg
                )
            else:
                self.playground_test_status.configure(text="⏳ Sending request...", fg=self.colors.fg)
            self.root.update()
        except Exception as e:
            print(f"Warning: Failed to update status label: {e}")

        try:
            params = self._prepare_snip_request()
            if params.get("error"):
                raise ValueError(params["error"])

            self._run_streaming_test(params)

        except Exception as e:
            if self.use_ctk:
                self.playground_test_status.configure(text=f"❌ Error: {e}", text_color=self.colors.accent_red)
            else:
                self.playground_test_status.configure(text=f"❌ Error: {e}", fg=self.colors.accent_red)

    def _prepare_text_request(self) -> Dict:
        """Prepare params for text action request."""
        if self.use_ctk:
            system_prompt = self.playground_system_preview.get("0.0", "end").strip()
            user_message = self.playground_user_preview.get("0.0", "end").strip()
        else:
            system_prompt = self.playground_system_preview.get("1.0", "end").strip()
            user_message = self.playground_user_preview.get("1.0", "end").strip()

        from ....messages import build_text_message

        messages = build_text_message(user_message, system_prompt)

        return self._get_request_config(messages)

    def _prepare_snip_request(self) -> Dict:
        """Prepare params for snip action request (multimodal)."""
        if not self.playground_image_base64:
            return {"error": "No image selected. Snip actions require an image."}

        if self.use_ctk:
            system_prompt = self.playground_system_preview.get("0.0", "end").strip()
            user_message = self.playground_user_preview.get("0.0", "end").strip()
        else:
            system_prompt = self.playground_system_preview.get("1.0", "end").strip()
            user_message = self.playground_user_preview.get("1.0", "end").strip()

        from ....messages import build_image_message

        messages = build_image_message(
            image_b64=self.playground_image_base64,
            mime_type=self.playground_image_mime,
            task=user_message,
            system_prompt=system_prompt,
        )

        return self._get_request_config(messages)

    def _prepare_audio_request(self) -> Dict:
        """Prepare params for audio action request."""
        if not self.playground_audio_data:
            return {"error": "No audio data. Please record or upload audio."}

        if self.use_ctk:
            system_prompt = self.playground_system_preview.get("0.0", "end").strip()
            user_message = self.playground_user_preview.get("0.0", "end").strip()
        else:
            system_prompt = self.playground_system_preview.get("1.0", "end").strip()
            user_message = self.playground_user_preview.get("1.0", "end").strip()

        # Convert raw audio bytes to base64 string for the API
        audio_b64 = base64.b64encode(self.playground_audio_data).decode("utf-8")

        from ....messages import build_audio_message

        messages = build_audio_message(
            audio_b64=audio_b64,
            mime_type=self.playground_audio_mime or "audio/wav",
            task=user_message,
            system_prompt=system_prompt,
        )

        return self._get_request_config(messages)

    def _get_request_config(self, messages) -> Dict:
        """Helper to get common request config."""
        from .... import web_server as _ws
        from ....key_store import KeyStore
        from ....profile_resolver import resolve_profile

        key_store = KeyStore.get_instance()
        key_managers = key_store.build_key_managers()

        # Resolve profile to get merged config with connection keys
        resolved = resolve_profile(None, _ws.CONFIG, _ws.AI_PARAMS, key_managers)

        provider = self.playground_provider_var.get()
        model = self.playground_model_var.get()

        return {
            "messages": messages,
            "provider": provider,
            "model": model,
            "config": resolved.config,
            "ai_params": resolved.ai_params,
            "key_managers": resolved.key_managers,
        }

    def _run_streaming_test(self, params):
        """Run the streaming test in a background thread."""
        dialog = TestResultDialog(self.root, self.colors)

        # Define thread target
        def _target():
            try:
                from ....request_pipeline import RequestContext, RequestOrigin, RequestPipeline, StreamCallback

                # Check for thinking support in config to show proper UI
                thinking_enabled = params["config"].get("thinking_enabled", False)

                ctx = RequestContext(
                    origin=RequestOrigin.POPUP_PROMPT,
                    provider=params["provider"],
                    model=params["model"],
                    streaming=True,
                    thinking_enabled=thinking_enabled,
                )

                usage_data = {}

                callbacks = StreamCallback(
                    on_text=lambda content: dialog.append_text(content),
                    on_thinking=lambda content: dialog.append_thinking(content),
                    on_error=lambda content: dialog.append_error(str(content)),
                    on_usage=lambda u: usage_data.update(u),
                )

                ctx = RequestPipeline.execute_unified_stream(
                    ctx=ctx,
                    messages=params["messages"],
                    config=params["config"],
                    ai_params=params["ai_params"],
                    key_managers=params["key_managers"],
                    callbacks=callbacks,
                )

                if ctx.error:
                    dialog.append_error(ctx.error)

                final_usage = (
                    {
                        "prompt_tokens": ctx.input_tokens,
                        "completion_tokens": ctx.output_tokens,
                        "total_tokens": ctx.total_tokens,
                        "estimated": ctx.estimated,
                    }
                    if ctx.input_tokens or ctx.output_tokens
                    else (usage_data or None)
                )
                dialog.mark_done(usage=final_usage)

                # Update main window status
                self.queue.put(self._update_status_success)

            except Exception as e:
                dialog.append_error(str(e))
                self.queue.put(lambda: self._update_status_error(str(e)))

        # Start thread
        threading.Thread(target=_target, daemon=True).start()

    def _update_status_success(self):
        """Update test button status to success."""
        renderer = get_emoji_renderer() if HAVE_EMOJI else None
        if self.use_ctk:
            ok_img = renderer.get_ctk_image("✅", size=16) if renderer else None
            self.playground_test_status.configure(
                text=" Success!", image=ok_img, compound="left", text_color=self.colors.accent_green
            )
        else:
            self.playground_test_status.configure(text="✅ Success!", fg=self.colors.accent_green)
        self.root.after(3000, lambda: self._clear_test_status())

    def _update_status_error(self, error):
        """Update test button status to error."""
        if self.use_ctk:
            self.playground_test_status.configure(text=f"❌ Error: {error[:30]}...", text_color=self.colors.accent_red)
        else:
            self.playground_test_status.configure(text=f"❌ Error: {error[:30]}...", fg=self.colors.accent_red)

    def _clear_test_status(self):
        """Clear the test status label."""
        try:
            if self.use_ctk:
                self.playground_test_status.configure(text="", image=None)
            else:
                self.playground_test_status.configure(text="")
        except Exception:
            pass
