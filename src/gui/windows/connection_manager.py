#!/usr/bin/env python3
"""
Connection Profile Manager window.

Standalone window for managing connection profiles (provider, model,
streaming, thinking, AI params, etc.). Accessible from system tray,
terminal, and settings window.

Usage:
    from src.gui.windows.connection_manager import ConnectionProfileManager
    ConnectionProfileManager(parent_root, colors)
"""

import threading
import tkinter as tk
from tkinter import messagebox
from typing import List, Optional

from ..platform import HAVE_CTK, ctk
from ..themes import (
    ThemeColors, get_colors,
    get_ctk_entry_colors,
    get_ctk_combobox_colors, get_ctk_label_colors,
    get_ctk_font
)
from ..custom_widgets import (
    ScrollableButtonList, ScrollableComboBox, create_emoji_button,
    TkScrollableFrame, ask_themed_string
)
from ..popups import Tooltip
from .utils import set_window_icon
from ...model_defaults import get_fallback_models

try:
    from ..emoji_renderer import get_emoji_renderer, HAVE_PIL, prepare_emoji_content
    HAVE_EMOJI = HAVE_PIL and HAVE_CTK
except ImportError:
    HAVE_EMOJI = False
    prepare_emoji_content = None


# Profile fields: (key, label, field_type, options)
PROFILE_FIELDS = [
    ("provider", "Provider", "combobox", ["google", "anthropic", "openai", "openrouter", "xai", "mistral", "cohere", "custom"]),
    ("model", "Model", "model_dropdown", None),
    ("streaming", "Streaming", "toggle", None),
    ("thinking", "Thinking", "toggle", None),
    ("thinking_budget", "Thinking Budget", "entry", None),
    ("thinking_level", "Thinking Level", "combobox", ["", "low", "high"]),
    ("reasoning_effort", "Reasoning Effort", "combobox", ["", "low", "medium", "high"]),
    ("temperature", "Temperature", "entry", None),
    ("max_tokens", "Max Tokens", "entry", None),
    ("request_timeout", "Request Timeout (s)", "entry", None),
    ("base_url", "Base URL", "entry", None),
    ("api_key_name", "API Key Name", "key_name_dropdown", None),
    ("api_key_pool", "API Key Pool", "combobox", None),
]

PROVIDER_FIELD_VISIBILITY = {
    "thinking_budget": {"google"},
    "thinking_level": {"google"},
    "reasoning_effort": {"openai", "openrouter", "xai", "mistral", "cohere", "custom"},
}

# Thinking sub-fields that require thinking toggle to be ON
THINKING_FIELDS = {"thinking_budget", "thinking_level", "reasoning_effort"}

# Required fields (bold label)
REQUIRED_FIELDS = {"provider", "model"}

# Conditionally required fields: {key: {provider_values}}
CONDITIONAL_REQUIRED = {"base_url": {"custom"}}

# Help text for field tooltips
FIELD_HELP = {
    "provider": "API provider for this profile. Required.",
    "model": "Model ID to use. Required. Click 🔄 to fetch available models.",
    "streaming": "Stream responses token-by-token instead of waiting for the full response.",
    "thinking": "Enable sending thinking parameters. When enabled, thinking-related fields below become available.",
    "thinking_budget": "Token budget for thinking (Gemini 2.5 models only). -1 = auto/unlimited. Leave empty for default.",
    "thinking_level": "Thinking intensity (Gemini 3.x models only). Leave empty for default.",
    "reasoning_effort": "Reasoning effort (OpenAI-compatible APIs only). Leave empty for default.",
    "temperature": "Controls randomness (0.0-2.0). Leave empty to use model default.",
    "max_tokens": "Maximum output tokens. Leave empty to use model default.",
    "request_timeout": "Request timeout in seconds. Leave empty to use the global timeout from settings.",
    "base_url": "Custom base URL for the API endpoint. Leave empty to use the provider's default URL.",
    "api_key_name": "Use a specific named key from the pool. When set, key rotation is disabled and only this key will be used. Leave empty to use pool rotation.",
    "api_key_pool": "Override which key pool this profile uses. Leave empty to use provider default.",
}

# Summary row icons
SUMMARY_ICONS = {
    "provider": "📡",
    "model": "🤖",
    "streaming": "🌊",
    "thinking": "💭",
    "request_timeout": "⏱️",
    "base_url": "🔗",
    "temperature": "🌡️",
    "max_tokens": "📏",
    "thinking_budget": "🧠",
    "thinking_level": "💡",
    "reasoning_effort": "🔬",
    "api_key_name": "🔑",
    "api_key_pool": "🗝️",
}


class ConnectionProfileManager(ctk.CTkToplevel if HAVE_CTK else tk.Toplevel):
    """
    Window for creating, editing, and deleting connection profiles.

    Profiles are complete — every field always has a value (no sparse overrides).
    """

    def __init__(self, parent, colors: ThemeColors = None, on_close=None):
        super().__init__(parent)
        self.colors = colors or get_colors()
        self.on_close = on_close
        self.use_ctk = HAVE_CTK
        self.field_widgets = {}
        self.field_rows = {}
        self.current_profile = None
        self._model_status_label = None
        self._model_dropdown_widget = None
        self._summary_label = None
        self._summary_frame = None
        self._summary_widgets: List = []
        self._fields_container = None
        self._destroyed = False
        self._last_saved_values: Optional[dict] = None
        self._custom_url_label = None
        self._api_key_name_dropdown = None
        self._ignore_select_event = False

        self.title("Connection Profiles")
        self.geometry("780x740")
        self.minsize(680, 580)
        self.transient(parent)

        if self.use_ctk:
            self.configure(fg_color=self.colors.bg)
        else:
            self.configure(bg=self.colors.bg)

        self.withdraw()
        from .utils import set_dark_titlebar
        set_dark_titlebar(self)
        set_window_icon(self)

        # Resolve api_key_pool options from KeyStore
        self.profile_fields = []
        try:
            from ...key_store import KeyStore
            pools = KeyStore.get_instance().get_all_pool_ids()
        except Exception:
            pools = []
        for field in PROFILE_FIELDS:
            if field[0] == "api_key_pool":
                self.profile_fields.append(("api_key_pool", "API Key Pool", "combobox", [""] + pools))
            else:
                self.profile_fields.append(field)

        self._build_ui()

        # Subscribe to KeyStore changes to refresh key name options
        try:
            from ...key_store import KeyStore
            self._keystore_callback = self._on_keystore_changed
            KeyStore.get_instance().subscribe(self._keystore_callback)
        except Exception:
            self._keystore_callback = None

        # Trace api_key_pool changes to update key name options
        pool_info = self.field_widgets.get("api_key_pool")
        if pool_info:
            pool_info["var"].trace_add("write", lambda *_: self._update_api_key_name_options())

        # Trace name and description changes for unsaved indicator
        self.name_var.trace_add("write", lambda *_: self._check_unsaved())
        self.description_var.trace_add("write", lambda *_: self._check_unsaved())

        self._refresh_list()
        self.deiconify()

        # Intercept window close for unsaved changes guard
        self.protocol("WM_DELETE_WINDOW", self._on_close_attempt)

    # ─── Build UI ─────────────────────────────────────────────────────────

    def _build_ui(self):
        c = self.colors

        # Title
        if self.use_ctk:
            ctk.CTkLabel(self, text="🔌  Connection Profiles", font=get_ctk_font(16, "bold"),
                        **get_ctk_label_colors(c)).pack(anchor="w", padx=20, pady=(15, 10))
        else:
            tk.Label(self, text="🔌  Connection Profiles", font=("Segoe UI", 14, "bold"),
                    bg=c.bg, fg=c.fg).pack(anchor="w", padx=20, pady=(15, 10))

        # Main container: left list + right editor
        container = ctk.CTkFrame(self, fg_color="transparent") if self.use_ctk else tk.Frame(self, bg=c.bg)
        container.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        # Left panel: profile list
        left = ctk.CTkFrame(container, fg_color="transparent", width=200) if self.use_ctk else tk.Frame(container, bg=c.bg, width=200)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        self.profile_listbox = ScrollableButtonList(
            left, c, command=self._on_profile_select,
            **({"corner_radius": 8, "fg_color": c.input_bg} if self.use_ctk else {"bg": c.input_bg})
        )
        self.profile_listbox.pack(fill="both", expand=True)

        # List buttons
        btn_frame = ctk.CTkFrame(left, fg_color="transparent") if self.use_ctk else tk.Frame(left, bg=c.bg)
        btn_frame.pack(fill="x", pady=(8, 0))

        create_emoji_button(btn_frame, "New", "➕", c, "success", 70, 30, self._new_profile).pack(side="left", padx=2)
        create_emoji_button(btn_frame, "", "📋", c, "secondary", 35, 30, self._duplicate_profile).pack(side="left", padx=2)
        create_emoji_button(btn_frame, "", "🗑️", c, "danger", 35, 30, self._delete_profile).pack(side="left", padx=2)

        # Right panel: editor
        right = ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=c.bg)
        right.pack(side="left", fill="both", expand=True)

        # Scrollable editor area
        if self.use_ctk:
            scroll_frame = ctk.CTkScrollableFrame(right, fg_color="transparent")
            editor = scroll_frame
        else:
            scroll_frame = TkScrollableFrame(right, bg_color=c.bg)
            editor = scroll_frame.scrollable_frame if hasattr(scroll_frame, 'scrollable_frame') else scroll_frame
        scroll_frame.pack(fill="both", expand=True)

        # --- Profile Name ---
        row = ctk.CTkFrame(editor, fg_color="transparent") if self.use_ctk else tk.Frame(editor, bg=c.bg)
        row.pack(fill="x", pady=5)
        if self.use_ctk:
            ctk.CTkLabel(row, text="Profile Name:", font=get_ctk_font(13, "bold"), width=130, anchor="w",
                        **get_ctk_label_colors(c)).pack(side="left")
            self.name_var = tk.StringVar()
            self.name_entry = ctk.CTkEntry(row, textvariable=self.name_var, font=get_ctk_font(13),
                                           height=32, **get_ctk_entry_colors(c))
            self.name_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        else:
            tk.Label(row, text="Profile Name:", font=("Segoe UI", 10, "bold"), width=14, anchor="w",
                    bg=c.bg, fg=c.fg).pack(side="left")
            self.name_var = tk.StringVar()
            self.name_entry = tk.Entry(row, textvariable=self.name_var, font=("Segoe UI", 10),
                                       bg=c.input_bg, fg=c.fg)
            self.name_entry.pack(side="left", fill="x", expand=True, padx=(5, 0))

        # --- Description ---
        row = ctk.CTkFrame(editor, fg_color="transparent") if self.use_ctk else tk.Frame(editor, bg=c.bg)
        row.pack(fill="x", pady=3)
        if self.use_ctk:
            ctk.CTkLabel(row, text="Description:", font=get_ctk_font(12), width=130, anchor="w",
                        **get_ctk_label_colors(c)).pack(side="left")
            self.description_var = tk.StringVar()
            ctk.CTkEntry(row, textvariable=self.description_var, font=get_ctk_font(12),
                         height=30, placeholder_text="Notes about this profile...",
                         **get_ctk_entry_colors(c)).pack(side="left", fill="x", expand=True, padx=(8, 0))
        else:
            tk.Label(row, text="Description:", font=("Segoe UI", 9), width=14, anchor="w",
                    bg=c.bg, fg=c.fg).pack(side="left")
            self.description_var = tk.StringVar()
            tk.Entry(row, textvariable=self.description_var, font=("Segoe UI", 9),
                     bg=c.input_bg, fg=c.fg).pack(side="left", fill="x", expand=True, padx=(5, 0))

        # Separator
        if self.use_ctk:
            ctk.CTkFrame(editor, fg_color=c.surface1, height=1).pack(fill="x", pady=8)
        else:
            tk.Frame(editor, bg=c.surface1, height=1).pack(fill="x", pady=8)

        # Fields container
        self._fields_container = ctk.CTkFrame(editor, fg_color="transparent") if self.use_ctk else tk.Frame(editor, bg=c.bg)
        self._fields_container.pack(fill="x")

        # Build fields
        for key, label, field_type, options in self.profile_fields:
            row = ctk.CTkFrame(self._fields_container, fg_color="transparent") if self.use_ctk else tk.Frame(self._fields_container, bg=c.bg)
            row.pack(fill="x", pady=3)
            self.field_rows[key] = row

            if field_type == "toggle":
                self._build_toggle_field(row, key, label, c)
            elif field_type == "model_dropdown":
                self._build_model_dropdown_field(row, key, label, c)
            elif field_type == "combobox":
                self._build_combobox_field(row, key, label, options, c)
            elif field_type == "key_name_dropdown":
                self._build_key_name_dropdown_field(row, key, label, c)
            else:
                self._build_entry_field(row, key, label, c)

        # --- Summary Panel ---
        if self.use_ctk:
            ctk.CTkFrame(editor, fg_color=c.surface1, height=1).pack(fill="x", pady=(10, 4))
        else:
            tk.Frame(editor, bg=c.surface1, height=1).pack(fill="x", pady=(10, 4))
    
        self._summary_frame = ctk.CTkFrame(editor, fg_color=c.surface0, corner_radius=8) if self.use_ctk else tk.Frame(editor, bg=c.surface0)
        self._summary_frame.pack(fill="x", pady=(0, 5))
    
        # Summary header
        if self.use_ctk:
            if HAVE_EMOJI and prepare_emoji_content:
                title_content = prepare_emoji_content("📋 Profile Summary", size=14)
                ctk.CTkLabel(self._summary_frame, font=get_ctk_font(13, "bold"),
                    **title_content, **get_ctk_label_colors(c)).pack(anchor="w", padx=12, pady=(8, 2))
            else:
                ctk.CTkLabel(self._summary_frame, text="Profile Summary", font=get_ctk_font(13, "bold"),
                    **get_ctk_label_colors(c)).pack(anchor="w", padx=12, pady=(8, 2))
        else:
            tk.Label(self._summary_frame, text="Profile Summary", font=("Segoe UI", 11, "bold"),
                bg=c.surface0, fg=c.fg).pack(anchor="w", padx=12, pady=(8, 2))
    
        # Summary content area (rebuilt dynamically in _update_summary)
        self._summary_content = ctk.CTkFrame(self._summary_frame, fg_color="transparent") if self.use_ctk else tk.Frame(self._summary_frame, bg=c.surface0)
        self._summary_content.pack(fill="x", padx=12, pady=(0, 8))

        # --- Action Buttons ---
        btn_row = ctk.CTkFrame(right, fg_color="transparent") if self.use_ctk else tk.Frame(right, bg=c.bg)
        btn_row.pack(fill="x", pady=(10, 5))

        create_emoji_button(btn_row, "Save", "💾", c, "success", 100, 34, self._save_profile).pack(side="left", padx=(0, 4))
        create_emoji_button(btn_row, "Test", "🧪", c, "primary", 90, 34, self._test_profile).pack(side="left", padx=4)
        create_emoji_button(btn_row, "Set Active", "⭐", c, "secondary", 120, 34, self._set_as_active).pack(side="left", padx=4)

        if self.use_ctk:
            self.save_status = ctk.CTkLabel(btn_row, text="", font=get_ctk_font(11),
                                            text_color=c.accent_green)
        else:
            self.save_status = tk.Label(btn_row, text="", font=("Segoe UI", 9),
                                        bg=c.bg, fg=c.accent_green)
        self.save_status.pack(side="left", padx=12)

        self._on_provider_change("")

    # ─── Field Builders ───────────────────────────────────────────────────

    def _add_help_icon(self, parent, key: str, c: ThemeColors):
        """Add a '?' help tooltip icon between label and input widget."""
        help_text = FIELD_HELP.get(key, "")
        if not help_text:
            return
        if self.use_ctk:
            help_label = ctk.CTkLabel(parent, text="?", font=get_ctk_font(11, "bold"),
                width=18, text_color=c.accent, cursor="hand2")
        else:
            help_label = tk.Label(parent, text="?", font=("Segoe UI", 9, "bold"),
                bg=c.bg, fg=c.accent, cursor="question_arrow")
        help_label.pack(side="left", padx=(2, 0))
        Tooltip(help_label, help_text)

    def _build_toggle_field(self, row, key: str, label: str, c: ThemeColors):
        """Build a toggle (checkbox) field — always has a value, no enable checkbox."""
        var = tk.BooleanVar(value=False)
        is_required = key in REQUIRED_FIELDS

        if self.use_ctk:
            font = get_ctk_font(12, "bold") if is_required else get_ctk_font(12)
            ctk.CTkLabel(row, text=f"{label}:", font=font, width=150, anchor="w",
                **get_ctk_label_colors(c)).pack(side="left")
            self._add_help_icon(row, key, c)
            ctk.CTkCheckBox(row, text="Enabled", variable=var,
                font=get_ctk_font(12), text_color=c.fg, fg_color=c.accent
            ).pack(side="left", padx=(8, 0))
        else:
            font = ("Segoe UI", 9, "bold") if is_required else ("Segoe UI", 9)
            tk.Label(row, text=f"{label}:", font=font, width=14, anchor="w",
                bg=c.bg, fg=c.fg).pack(side="left")
            self._add_help_icon(row, key, c)
            tk.Checkbutton(row, text="Enabled", variable=var,
                bg=c.bg, fg=c.fg, selectcolor=c.input_bg).pack(side="left", padx=(5, 0))

        # Thinking toggle controls visibility of thinking sub-fields
        if key == "thinking":
            var.trace_add("write", lambda *_: self._on_provider_change())

        # Track unsaved changes
        var.trace_add("write", lambda *_: self._check_unsaved())

        self.field_widgets[key] = {"var": var, "type": "toggle"}

    def _build_model_dropdown_field(self, row, key: str, label: str, c: ThemeColors):
        """Build model dropdown with refresh button."""
        var = tk.StringVar()
        is_required = key in REQUIRED_FIELDS

        if self.use_ctk:
            font = get_ctk_font(12, "bold") if is_required else get_ctk_font(12)
            ctk.CTkLabel(row, text=f"{label}:", font=font, width=150, anchor="w",
                **get_ctk_label_colors(c)).pack(side="left")
            self._add_help_icon(row, key, c)
            dropdown = ScrollableComboBox(
                row, colors=c, variable=var, values=[],
                width=220, height=30, font_size=12
            )
            dropdown.pack(side="left", padx=(8, 0))
            self._model_dropdown_widget = dropdown

            create_emoji_button(
                row, "", "🔄", c, "secondary", 34, 30,
                command=self._refresh_models
            ).pack(side="left", padx=(6, 0))

            self._model_status_label = ctk.CTkLabel(
                row, text="", font=get_ctk_font(10), width=120,
                **get_ctk_label_colors(c, muted=True)
            )
            self._model_status_label.pack(side="left", padx=(6, 0))
        else:
            from tkinter import ttk as ttk_local
            font = ("Segoe UI", 9, "bold") if is_required else ("Segoe UI", 9)
            tk.Label(row, text=f"{label}:", font=font, width=14, anchor="w",
                bg=c.bg, fg=c.fg).pack(side="left")
            self._add_help_icon(row, key, c)
            dropdown = ttk_local.Combobox(row, textvariable=var, values=[], width=22)
            dropdown.pack(side="left", padx=(5, 0))
            self._model_dropdown_widget = dropdown

            tk.Button(row, text="🔄", font=("Segoe UI", 9),
                bg=c.surface1, fg=c.fg,
                command=self._refresh_models).pack(side="left", padx=(4, 0))

            self._model_status_label = tk.Label(
                row, text="", font=("Segoe UI", 8),
                bg=c.bg, fg=c.blockquote, width=14
            )
            self._model_status_label.pack(side="left", padx=(4, 0))

        # Track unsaved changes
        var.trace_add("write", lambda *_: self._check_unsaved())

        self.field_widgets[key] = {"var": var, "type": "model_dropdown", "widget": dropdown}

    def _build_combobox_field(self, row, key: str, label: str, options: list, c: ThemeColors):
        """Build a combobox/dropdown field."""
        var = tk.StringVar()
        command = self._on_provider_change if key == "provider" else None
        is_required = key in REQUIRED_FIELDS

        if self.use_ctk:
            font = get_ctk_font(12, "bold") if is_required else get_ctk_font(12)
            ctk.CTkLabel(row, text=f"{label}:", font=font, width=150, anchor="w",
                **get_ctk_label_colors(c)).pack(side="left")
            self._add_help_icon(row, key, c)
            combo_kwargs = {
                "variable": var, "values": options or [],
                "width": 200, "height": 30, "state": "readonly",
                "font": get_ctk_font(12), **get_ctk_combobox_colors(c)
            }
            if command:
                combo_kwargs["command"] = command
            ctk.CTkComboBox(row, **combo_kwargs).pack(side="left", padx=(8, 0))
        else:
            from tkinter import ttk as ttk_local
            font = ("Segoe UI", 9, "bold") if is_required else ("Segoe UI", 9)
            tk.Label(row, text=f"{label}:", font=font, width=14, anchor="w",
                bg=c.bg, fg=c.fg).pack(side="left")
            self._add_help_icon(row, key, c)
            combo = ttk_local.Combobox(row, textvariable=var, values=options or [],
                state="readonly", width=18)
            combo.pack(side="left", padx=(5, 0))
            if command:
                combo.bind('<<ComboboxSelected>>', lambda e: command(var.get()))

        # Track unsaved changes
        var.trace_add("write", lambda *_: self._check_unsaved())

        self.field_widgets[key] = {"var": var, "type": "combobox"}

    def _build_entry_field(self, row, key: str, label: str, c: ThemeColors):
        """Build a text entry field."""
        var = tk.StringVar()
        is_required = key in REQUIRED_FIELDS

        if self.use_ctk:
            font = get_ctk_font(12, "bold") if is_required else get_ctk_font(12)
            lbl = ctk.CTkLabel(row, text=f"{label}:", font=font, width=150, anchor="w",
                **get_ctk_label_colors(c))
            lbl.pack(side="left")
            self._add_help_icon(row, key, c)
            ctk.CTkEntry(row, textvariable=var, font=get_ctk_font(12),
                height=30, width=250, **get_ctk_entry_colors(c)
            ).pack(side="left", padx=(8, 0))
        else:
            font = ("Segoe UI", 9, "bold") if is_required else ("Segoe UI", 9)
            lbl = tk.Label(row, text=f"{label}:", font=font, width=14, anchor="w",
                bg=c.bg, fg=c.fg)
            lbl.pack(side="left")
            self._add_help_icon(row, key, c)
            tk.Entry(row, textvariable=var, font=("Segoe UI", 9),
                bg=c.input_bg, fg=c.fg, width=25).pack(side="left", padx=(5, 0))

        # Store label reference for base_url dynamic bold
        if key == "base_url":
            self._custom_url_label = lbl

        # Track unsaved changes
        var.trace_add("write", lambda *_: self._check_unsaved())

        self.field_widgets[key] = {"var": var, "type": "entry"}

    def _build_key_name_dropdown_field(self, row, key: str, label: str, c: ThemeColors):
        """Build a key name dropdown field with auto-populated options from KeyStore."""
        var = tk.StringVar()
        is_required = key in REQUIRED_FIELDS

        if self.use_ctk:
            font = get_ctk_font(12, "bold") if is_required else get_ctk_font(12)
            ctk.CTkLabel(row, text=f"{label}:", font=font, width=150, anchor="w",
                         **get_ctk_label_colors(c)).pack(side="left")
            self._add_help_icon(row, key, c)
            dropdown = ScrollableComboBox(
                row, colors=c, variable=var, values=[],
                width=220, height=30, font_size=12,
                state="normal"
            )
            dropdown.pack(side="left", padx=(8, 0))
            self._api_key_name_dropdown = dropdown
        else:
            font = ("Segoe UI", 9, "bold") if is_required else ("Segoe UI", 9)
            tk.Label(row, text=f"{label}:", font=font, width=14, anchor="w",
                     bg=c.bg, fg=c.fg).pack(side="left")
            self._add_help_icon(row, key, c)
            dropdown = ScrollableComboBox(
                row, colors=c, variable=var, values=[],
                width=220, height=30, font_size=10,
                state="normal"
            )
            dropdown.pack(side="left", padx=(5, 0))
            self._api_key_name_dropdown = dropdown

        # Track unsaved changes
        var.trace_add("write", lambda *_: self._check_unsaved())

        self.field_widgets[key] = {"var": var, "type": "key_name_dropdown", "widget": dropdown}

    # ─── Provider-aware visibility ────────────────────────────────────────

    def _on_provider_change(self, provider: str = None):
        if not provider:
            provider_info = self.field_widgets.get("provider")
            provider = provider_info["var"].get() if provider_info else ""

        # Check thinking toggle state
        thinking_info = self.field_widgets.get("thinking")
        thinking_enabled = thinking_info["var"].get() if thinking_info else False

        for key, _, _, _ in self.profile_fields:
            row = self.field_rows.get(key)
            if row:
                row.pack_forget()

        for key, _, _, _ in self.profile_fields:
            row = self.field_rows.get(key)
            if not row:
                continue
            # Provider visibility check
            allowed = PROVIDER_FIELD_VISIBILITY.get(key)
            provider_ok = (allowed is None or not provider or provider in allowed)
            # Thinking sub-fields: also require thinking to be enabled
            thinking_ok = (key not in THINKING_FIELDS) or thinking_enabled

            if provider_ok and thinking_ok:
                row.pack(fill="x", pady=3)

        # Dynamic bold for base_url label when provider is custom
        if self._custom_url_label:
            is_cond_required = False
            for ckey, cproviders in CONDITIONAL_REQUIRED.items():
                if ckey == "base_url" and provider in cproviders:
                    is_cond_required = True
                    break
            if is_cond_required:
                if self.use_ctk:
                    self._custom_url_label.configure(font=get_ctk_font(12, "bold"))
                else:
                    self._custom_url_label.configure(font=("Segoe UI", 9, "bold"))
            else:
                if self.use_ctk:
                    self._custom_url_label.configure(font=get_ctk_font(12))
                else:
                    self._custom_url_label.configure(font=("Segoe UI", 9))

        # Update summary when provider changes
        self._update_summary()

        # Refresh key name options when provider changes
        self._update_api_key_name_options()

        # Populate model dropdown with fallback list so it's never empty
        fallback = get_fallback_models(provider)
        if fallback and self._model_dropdown_widget:
            model_info = self.field_widgets.get("model")
            current_model = model_info["var"].get() if model_info else ""
            self._model_dropdown_widget.configure(values=fallback)
            # Only override if the current model field is empty/blank
            if model_info and not current_model.strip():
                model_info["var"].set(fallback[0])

    # ─── Key Name Options ────────────────────────────────────────────────

    def _update_api_key_name_options(self, *args):
        """Refresh the API Key Name dropdown options based on selected pool/provider."""
        if not self._api_key_name_dropdown or self._destroyed:
            return

        try:
            from ...key_store import KeyStore
            key_store = KeyStore.get_instance()

            # Resolve pool ID
            pool_info = self.field_widgets.get("api_key_pool")
            pool_id = pool_info["var"].get().strip() if pool_info else ""

            if not pool_id:
                # Use provider's default pool
                provider_info = self.field_widgets.get("provider")
                provider = provider_info["var"].get() if provider_info else ""
                pool_id = key_store.get_provider_pool_id(provider) if provider else ""

            # Fetch key names from pool
            names = []
            if pool_id and key_store.pool_exists(pool_id):
                keys_data = key_store.get_pool(pool_id)
                seen = set()
                for kd in keys_data:
                    name = kd.get("name", "")
                    if name and name not in seen:
                        names.append(name)
                        seen.add(name)

            self._api_key_name_dropdown.configure(values=[""] + names)
        except Exception:
            pass

    def _on_keystore_changed(self):
        """Called when KeyStore is modified — refresh key name options on GUI thread."""
        self._schedule_ui(self._update_api_key_name_options)

    # ─── Model fetching ──────────────────────────────────────────────────

    def _refresh_models(self):
        provider_info = self.field_widgets.get("provider")
        provider = provider_info["var"].get() if provider_info else ""
        if not provider:
            self._set_model_status("Select provider first", "error")
            return

        base_url_info = self.field_widgets.get("base_url")
        base_url_value = base_url_info["var"].get() if base_url_info else ""
    
        api_key_pool_info = self.field_widgets.get("api_key_pool")
        api_key_pool_value = api_key_pool_info["var"].get().strip() if api_key_pool_info else ""
    
        api_key_name_info = self.field_widgets.get("api_key_name")
        api_key_name_value = api_key_name_info["var"].get().strip() if api_key_name_info else ""

        self._set_model_status("🔄 Loading...", "info")

        def _fetch():
            try:
                from ...key_store import KeyStore
                from ...key_manager import KeyManager
                from ...providers import create_provider
                from ... import web_server as _ws
    
                key_store = KeyStore.get_instance()
    
                # Resolve key manager using profile's api_key_pool and api_key_name
                # (mirrors the logic in _test_profile)
                if api_key_pool_value:
                    temp_km = key_store.build_key_manager_for_pool(api_key_pool_value, provider)
                    if not temp_km or not temp_km.has_keys():
                        _pool_err = api_key_pool_value
                        self._schedule_ui(lambda p=_pool_err: self._set_model_status(f"Pool '{p}' has no keys", "error"))
                        return
                else:
                    keys_data = key_store.get_pool_for_provider(provider)
                    key_strings = [kd["key"] for kd in keys_data if kd.get("key")]
                    if not key_strings:
                        self._schedule_ui(lambda: self._set_model_status("No API keys", "error"))
                        return
                    temp_km = KeyManager(key_strings, provider)
    
                if api_key_name_value:
                    source_pool = api_key_pool_value or key_store.get_provider_pool_id(provider)
                    pool_keys = key_store.get_pool(source_pool)
                    matched = [kd for kd in pool_keys if kd.get("name") == api_key_name_value and kd.get("key")]
                    if matched:
                        temp_km = KeyManager(
                            [kd["key"] for kd in matched], provider,
                            key_names=[kd["name"] for kd in matched]
                        )
                    else:
                        _key_err = api_key_name_value
                        self._schedule_ui(lambda k=_key_err: self._set_model_status(f"Key '{k}' not found", "error"))
                        return
                temp_config = {"request_timeout": 30}
    
                if base_url_value:
                    temp_config["base_url"] = base_url_value
                else:
                    temp_config["base_url"] = _ws.get_active_setting("base_url", "")
                
                if provider == "custom" and not temp_config["base_url"]:
                    self._schedule_ui(lambda: self._set_model_status("No base URL", "error"))
                    return

                provider_instance = create_provider(provider, temp_km, temp_config)
                models, error = provider_instance.fetch_models()

                if error:
                    err_msg = str(error)[:35]
                    fallback = get_fallback_models(provider)

                    def _fallback_with_error(msg=err_msg, fb=fallback):
                        if self._destroyed:
                            return
                        if self._model_dropdown_widget and fb:
                            self._model_dropdown_widget.configure(values=fb)
                            model_info = self.field_widgets.get("model")
                            # Only overwrite if current is empty
                            if model_info and not model_info["var"].get().strip():
                                model_info["var"].set(fb[0])
                        self._set_model_status(msg, "error")

                    self._schedule_ui(_fallback_with_error)
                    return

                if not models:
                    fallback = get_fallback_models(provider)

                    def _fallback_no_models(fb=fallback):
                        if self._destroyed:
                            return
                        if self._model_dropdown_widget and fb:
                            self._model_dropdown_widget.configure(values=fb)
                            model_info = self.field_widgets.get("model")
                            # Only overwrite if current is empty
                            if model_info and not model_info["var"].get().strip():
                                model_info["var"].set(fb[0])
                        self._set_model_status("No models", "warning")

                    self._schedule_ui(_fallback_no_models)
                    return

                model_ids = [m.get("id", str(m)) for m in models]

                def _update():
                    if self._destroyed:
                        return
                    if self._model_dropdown_widget:
                        self._model_dropdown_widget.configure(values=model_ids)
                    self._set_model_status(f"✅ {len(model_ids)} models", "success")

                self._schedule_ui(_update)

            except Exception as e:
                err_msg = str(e)[:30]
                fallback = get_fallback_models(provider)

                def _fallback_on_exception(msg=err_msg, fb=fallback):
                    if self._destroyed:
                        return
                    if self._model_dropdown_widget and fb:
                        self._model_dropdown_widget.configure(values=fb)
                        model_info = self.field_widgets.get("model")
                        # Only overwrite if current is empty
                        if model_info and not model_info["var"].get().strip():
                            model_info["var"].set(fb[0])
                    self._set_model_status(msg, "error")

                self._schedule_ui(_fallback_on_exception)

        threading.Thread(target=_fetch, daemon=True).start()

    def _set_model_status(self, text: str, level: str = "info"):
        if not self._model_status_label:
            return
        c = self.colors
        color_map = {
            "error": c.accent_red,
            "success": c.accent_green,
            "warning": getattr(c, "accent_yellow", c.accent),
            "info": c.accent,
        }
        color = color_map.get(level, c.blockquote)
        if self.use_ctk:
            self._model_status_label.configure(text=text, text_color=color)
        else:
            self._model_status_label.configure(text=text, fg=color)

    def _schedule_ui(self, callback):
        if self._destroyed:
            return
        def safe_wrapper():
            if not self._destroyed:
                try:
                    callback()
                except Exception:
                    pass
        try:
            from ..core import GUICoordinator
            GUICoordinator.get_instance().run_on_gui_thread(safe_wrapper)
        except Exception:
            try:
                if self.winfo_exists():
                    self.after(0, safe_wrapper)
            except Exception:
                pass

    # ─── Summary ──────────────────────────────────────────────────────────

    def _update_summary(self):
        if not self._summary_content:
            return

        # Destroy old summary widgets
        for w in self._summary_widgets:
            try:
                w.destroy()
            except Exception:
                pass
        self._summary_widgets.clear()

        c = self.colors
        provider_info = self.field_widgets.get("provider")
        provider = provider_info["var"].get() if provider_info else ""

        # Check if thinking is enabled for sub-field visibility
        thinking_info = self.field_widgets.get("thinking")
        thinking_enabled = thinking_info["var"].get() if thinking_info else False

        # Show active profile indicator
        from ...connection_profiles import ProfileStore
        store = ProfileStore.get_instance()
        active_name = store.get_active_profile_name()
        is_active = self.current_profile and self.current_profile == active_name

        if not self.current_profile:
            if self.use_ctk:
                lbl = ctk.CTkLabel(self._summary_content, text="No profile selected",
                    font=get_ctk_font(12), **get_ctk_label_colors(c, muted=True))
                lbl.pack(anchor="w", pady=(2, 0))
                self._summary_widgets.append(lbl)
            else:
                lbl = tk.Label(self._summary_content, text="No profile selected",
                    font=("Segoe UI", 10), bg=c.surface0, fg=c.blockquote)
                lbl.pack(anchor="w", pady=(2, 0))
                self._summary_widgets.append(lbl)
            return

        # Active profile header
        if is_active:
            if self.use_ctk:
                if HAVE_EMOJI and prepare_emoji_content:
                    active_content = prepare_emoji_content("⭐ Active Profile", size=13)
                    active_lbl = ctk.CTkLabel(self._summary_content,
                        font=get_ctk_font(12, "bold"),
                        **active_content, **get_ctk_label_colors(c))
                else:
                    active_lbl = ctk.CTkLabel(self._summary_content,
                        text="★ Active Profile", font=get_ctk_font(12, "bold"),
                        **get_ctk_label_colors(c))
                active_lbl.pack(anchor="w", pady=(2, 0))
                self._summary_widgets.append(active_lbl)
            else:
                active_lbl = tk.Label(self._summary_content, text="★ Active Profile",
                    font=("Segoe UI", 10, "bold"), bg=c.surface0, fg=c.accent)
                active_lbl.pack(anchor="w", pady=(2, 0))
                self._summary_widgets.append(active_lbl)

        # Grid container for key-value rows
        grid_frame = ctk.CTkFrame(self._summary_content, fg_color="transparent") if self.use_ctk else tk.Frame(self._summary_content, bg=c.surface0)
        grid_frame.pack(fill="x", pady=(4, 0))
        self._summary_widgets.append(grid_frame)
        grid_frame.columnconfigure(2, weight=1)

        # Build icon + key-value rows using grid for tight alignment
        grid_row = 0
        for key, label, field_type, _ in self.profile_fields:
            widget_info = self.field_widgets.get(key)
            if not widget_info:
                continue
            # Provider visibility check
            allowed = PROVIDER_FIELD_VISIBILITY.get(key)
            if allowed and provider and provider not in allowed:
                continue
            # Thinking sub-fields visibility
            if key in THINKING_FIELDS and not thinking_enabled:
                continue

            # Get display value
            if field_type == "toggle":
                val = "ON" if widget_info["var"].get() else "OFF"
            else:
                val = widget_info["var"].get().strip()
                if not val:
                    continue  # Skip empty optional fields
                if len(val) > 40:
                    val = val[:38] + "…"

            icon = SUMMARY_ICONS.get(key, "  ")

            if self.use_ctk:
                if HAVE_EMOJI and prepare_emoji_content:
                    icon_content = prepare_emoji_content(icon, size=13)
                    icon_lbl = ctk.CTkLabel(grid_frame, font=get_ctk_font(12),
                        width=24, **icon_content, **get_ctk_label_colors(c))
                else:
                    icon_lbl = ctk.CTkLabel(grid_frame, text=icon, font=get_ctk_font(12),
                        width=24, **get_ctk_label_colors(c))
                icon_lbl.grid(row=grid_row, column=0, sticky="w", pady=1)
                self._summary_widgets.append(icon_lbl)

                key_lbl = ctk.CTkLabel(grid_frame, text=f"{label}:", font=get_ctk_font(12),
                    anchor="w", **get_ctk_label_colors(c, muted=True))
                key_lbl.grid(row=grid_row, column=1, sticky="w", padx=(0, 12), pady=1)
                self._summary_widgets.append(key_lbl)

                val_lbl = ctk.CTkLabel(grid_frame, text=val, font=get_ctk_font(12, "bold"),
                    anchor="w", **get_ctk_label_colors(c))
                val_lbl.grid(row=grid_row, column=2, sticky="w", pady=1)
                self._summary_widgets.append(val_lbl)
            else:
                icon_lbl = tk.Label(grid_frame, text=icon, font=("Segoe UI", 10),
                    bg=c.surface0, fg=c.fg, width=3)
                icon_lbl.grid(row=grid_row, column=0, sticky="w", pady=1)
                self._summary_widgets.append(icon_lbl)

                key_lbl = tk.Label(grid_frame, text=f"{label}:", font=("Segoe UI", 10),
                    bg=c.surface0, fg=c.blockquote, anchor="w")
                key_lbl.grid(row=grid_row, column=1, sticky="w", padx=(0, 10), pady=1)
                self._summary_widgets.append(key_lbl)

                val_lbl = tk.Label(grid_frame, text=val, font=("Segoe UI", 10, "bold"),
                    bg=c.surface0, fg=c.fg, anchor="w")
                val_lbl.grid(row=grid_row, column=2, sticky="w", pady=1)
                self._summary_widgets.append(val_lbl)

            grid_row += 1

    # ─── Unsaved Changes ────────────────────────────────────────────────

    def _check_unsaved(self):
        if self._last_saved_values is None:
            return
        try:
            indicator = "● " if self._is_dirty() else ""
            self.title(f"{indicator}Connection Profiles")
        except Exception:
            pass

    def _is_dirty(self) -> bool:
        """Check if the current form values differ from the last saved state."""
        if self._last_saved_values is None:
            return False
        current = self._collect_profile_values()
        current["name"] = self.name_var.get().strip()
        current["description"] = self.description_var.get().strip()
        return current != self._last_saved_values

    def _prompt_unsaved_if_dirty(self) -> bool:
        """Prompt user about unsaved changes. Returns True to proceed, False to abort."""
        if not self._is_dirty():
            return True
        result = messagebox.askyesnocancel(
            "Unsaved Changes",
            f"You have unsaved changes to profile '{self.current_profile}'.\n\n"
            "Save changes before proceeding?",
            parent=self
        )
        if result is True:  # Yes — save
            return self._save_profile()
        elif result is False:  # No — discard
            return True
        else:  # Cancel
            return False

    # ─── Test profile ─────────────────────────────────────────────────────

    def _test_profile(self):
        profile_data = self._collect_profile_values()
        if not profile_data.get("provider") and not profile_data.get("model"):
            messagebox.showinfo("Test Profile", "Set at least a provider or model to test.", parent=self)
            return

        from .prompt_editor.dialogs import TestResultDialog
        dialog = TestResultDialog(self, self.colors)

        def _test_thread():
            try:
                from ...key_manager import KeyManager
                from ...request_pipeline import (
                    RequestPipeline, RequestContext, RequestOrigin, StreamCallback
                )
                from ... import web_server as _ws
    
                # Build config from profile data directly (no load_config needed)
                config = {}
                ai_params = {}
    
                from ...key_store import KeyStore
                key_store = KeyStore.get_instance()
                key_managers = key_store.build_key_managers()
    
                provider = profile_data.get("provider") or _ws.get_active_setting("provider", "google")
                model = profile_data.get("model") or _ws.get_active_setting("model", "")
    
                config["default_provider"] = provider
                config[f"{provider}_model"] = model
    
                if "streaming" in profile_data:
                    config["streaming_enabled"] = profile_data["streaming"]
                if "thinking" in profile_data:
                    config["thinking_enabled"] = profile_data["thinking"]
                for field in ("thinking_budget", "thinking_level", "reasoning_effort",
                              "request_timeout", "base_url"):
                    if field in profile_data and profile_data[field]:
                        config[field] = profile_data[field]
                if "temperature" in profile_data and profile_data["temperature"] is not None:
                    ai_params["temperature"] = profile_data["temperature"]
                if "max_tokens" in profile_data and profile_data["max_tokens"] is not None:
                    ai_params["max_tokens"] = profile_data["max_tokens"]

                pool_override = profile_data.get("api_key_pool")
                key_name_override = profile_data.get("api_key_name")

                if pool_override:
                    custom_km = key_store.build_key_manager_for_pool(pool_override, provider)
                    if custom_km and custom_km.has_keys():
                        key_managers = dict(key_managers)
                        key_managers[provider] = custom_km
                    else:
                        dialog.append_error(f"Pool '{pool_override}' has no usable keys")
                        return

                if key_name_override:
                    source_pool = pool_override or key_store.get_provider_pool_id(provider)
                    pool_keys = key_store.get_pool(source_pool)
                    matched = [kd for kd in pool_keys if kd.get("name") == key_name_override and kd.get("key")]
                    if matched:
                        custom_km = KeyManager([kd["key"] for kd in matched], provider,
                                               key_names=[kd["name"] for kd in matched])
                        key_managers = dict(key_managers)
                        key_managers[provider] = custom_km
                    else:
                        dialog.append_error(f"Key named '{key_name_override}' not found")
                        return

                thinking_enabled = config.get("thinking_enabled", False)
            
                messages = [{"role": "user", "content": "Say 'Hello! Profile test successful.' in exactly those words."}]
            
                # Create RequestContext for pipeline logging
                ctx = RequestContext(
                    origin=RequestOrigin.POPUP_PROMPT,
                    provider=provider,
                    model=model,
                    streaming=True,
                    thinking_enabled=thinking_enabled,
                )

                # Build StreamCallback for the dialog
                usage_data = {}

                callbacks = StreamCallback(
                    on_text=lambda content: dialog.append_text(content),
                    on_thinking=lambda content: dialog.append_thinking(content),
                    on_error=lambda content: dialog.append_error(str(content)),
                    on_usage=lambda u: usage_data.update(u),
                )

                # Execute through RequestPipeline
                ctx = RequestPipeline.execute_unified_stream(
                    ctx=ctx,
                    messages=messages,
                    config=config,
                    ai_params=ai_params,
                    key_managers=key_managers,
                    callbacks=callbacks,
                )

                # Check for errors in the return context
                if ctx.error:
                    dialog.append_error(ctx.error)

                # Mark completion with usage
                final_usage = ctx.usage if hasattr(ctx, 'usage') else None
                if not final_usage and usage_data:
                    final_usage = usage_data
                elif not final_usage:
                    # Build from ctx fields
                    final_usage = {
                        "prompt_tokens": ctx.input_tokens,
                        "completion_tokens": ctx.output_tokens,
                        "total_tokens": ctx.total_tokens,
                        "estimated": ctx.estimated,
                    }
                dialog.mark_done(usage=final_usage)

            except Exception as e:
                dialog.append_error(str(e))

        threading.Thread(target=_test_thread, daemon=True).start()

    # ─── Set as Active ────────────────────────────────────────────────────

    def _set_as_active(self):
        if not self.current_profile:
            messagebox.showinfo("Set Active", "Select a profile first.", parent=self)
            return

        from ...web_server import switch_active_profile
        if switch_active_profile(self.current_profile):
            self._refresh_list()
            self._update_summary()
            if self.use_ctk:
                self.save_status.configure(text=f"⭐ '{self.current_profile}' is now active", text_color=self.colors.accent_green)
            else:
                self.save_status.configure(text=f"⭐ '{self.current_profile}' is now active", fg=self.colors.accent_green)
        else:
            messagebox.showwarning("Set Active", f"Profile '{self.current_profile}' not found.", parent=self)

    # ─── Collect form values ──────────────────────────────────────────────

    def _collect_profile_values(self) -> dict:
        profile = {}
        for key, widget_info in self.field_widgets.items():
            if widget_info["type"] == "toggle":
                profile[key] = widget_info["var"].get()
            elif widget_info["type"] in ("entry", "combobox", "model_dropdown", "key_name_dropdown"):
                val = widget_info["var"].get().strip()
                if key == "temperature":
                    try:
                        profile[key] = float(val) if val else None
                    except ValueError:
                        profile[key] = None
                elif key in ("thinking_budget", "max_tokens", "request_timeout"):
                    try:
                        profile[key] = int(val) if val else None
                    except ValueError:
                        profile[key] = None
                else:
                    profile[key] = val
        return profile

    # ─── CRUD ─────────────────────────────────────────────────────────────

    def _refresh_list(self):
        from ...connection_profiles import ProfileStore
        store = ProfileStore.get_instance()
        active = store.get_active_profile_name()

        self.profile_listbox.clear()
        for name in store.get_profile_names():
            icon = "⭐" if name == active else "🔌"
            self.profile_listbox.add_item(name, name, icon)

    def _on_profile_select(self, name):
        # Skip entirely when reverting selection (avoid reloading and losing unsaved changes)
        if self._ignore_select_event:
            return

        # Guard: check for unsaved changes before switching profiles
        if not self._prompt_unsaved_if_dirty():
            # Revert listbox selection without triggering recursive call
            self._ignore_select_event = True
            if self.current_profile:
                self.profile_listbox.select(self.current_profile)
            else:
                self.profile_listbox.selection_clear()
            self._ignore_select_event = False
            return

        from ...connection_profiles import ProfileStore
        self.current_profile = name
        # Reset saved state before loading to prevent trace callbacks
        # from briefly showing the dirty indicator during field population
        self._last_saved_values = None
        store = ProfileStore.get_instance()
        profile_data = store.get_profile_dict(name) or {}

        self.name_var.set(name)
        self.description_var.set(profile_data.get("description", ""))

        for key, widget_info in self.field_widgets.items():
            val = profile_data.get(key)
            if widget_info["type"] == "toggle":
                widget_info["var"].set(bool(val) if val is not None else False)
            elif widget_info["type"] == "model_dropdown":
                str_val = str(val) if val is not None else ""
                widget_info["var"].set(str_val)
                w = widget_info.get("widget")
                if w and hasattr(w, "set"):
                    w.set(str_val)
            elif widget_info["type"] == "key_name_dropdown":
                str_val = str(val) if val is not None and val != "" else ""
                if str_val == "None":
                    str_val = ""
                widget_info["var"].set(str_val)
                w = widget_info.get("widget")
                if w and hasattr(w, "set"):
                    w.set(str_val)
            else:
                str_val = str(val) if val is not None and val != "" else ""
                # Convert None to empty string for display
                if str_val == "None":
                    str_val = ""
                widget_info["var"].set(str_val)

        self._on_provider_change(profile_data.get("provider", ""))
        self._update_summary()

        # Track saved state for unsaved indicator
        self._last_saved_values = self._collect_profile_values()
        self._last_saved_values["name"] = name.strip()
        self._last_saved_values["description"] = self.description_var.get().strip()
        self.title("Connection Profiles")

    def _save_profile(self) -> bool:
        from ...connection_profiles import ProfileStore
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Please enter a profile name.", parent=self)
            return False

        profile_data = self._collect_profile_values()
        desc = self.description_var.get().strip()
        if desc:
            profile_data["description"] = desc

        # Validate required fields
        errors = []
        if not profile_data.get("provider"):
            errors.append("Provider is required")
        if not profile_data.get("model"):
            errors.append("Model is required")
        if profile_data.get("provider") == "custom" and not profile_data.get("base_url"):
            errors.append("Base URL is required for custom provider")

        if errors:
            messagebox.showwarning("Validation", "\n".join(errors), parent=self)
            return False

        store = ProfileStore.get_instance()

        # Handle rename
        if self.current_profile and self.current_profile != name:
            store.rename_profile(self.current_profile, name)

        store.set_profile_from_dict(name, profile_data)
        self.current_profile = name
        self._refresh_list()
        # Ignore select event to avoid re-triggering _on_profile_select
        # (which would check dirty state before we update _last_saved_values)
        self._ignore_select_event = True
        self.profile_listbox.select(name)
        self._ignore_select_event = False
        self._update_summary()

        # If this is the active profile, apply changes live
        active = store.get_active_profile_name()
        if name == active:
            from ...web_server import switch_active_profile
            switch_active_profile(name)

        # Update saved state and clear unsaved indicator
        self._last_saved_values = self._collect_profile_values()
        self._last_saved_values["name"] = name.strip()
        self._last_saved_values["description"] = self.description_var.get().strip()
        self.title("Connection Profiles")

        self.save_status.configure(text=f"✅ Saved '{name}'")
        return True

    def _new_profile(self):
        if not self._prompt_unsaved_if_dirty():
            return
        # Reset dirty state so _on_profile_select won't re-prompt
        self._last_saved_values = None
        name = ask_themed_string(self, "New Profile", "Enter profile name:", self.colors)
        if name:
            from ...connection_profiles import ProfileStore, ConnectionProfile
            store = ProfileStore.get_instance()
            store.set_profile(name, ConnectionProfile())
            self.current_profile = name
            self._refresh_list()
            self._ignore_select_event = True
            self.profile_listbox.select(name)
            self._ignore_select_event = False
            self._on_profile_select(name)

    def _duplicate_profile(self):
        if not self.current_profile:
            return
        if not self._prompt_unsaved_if_dirty():
            return
        # Reset dirty state so _on_profile_select won't re-prompt
        self._last_saved_values = None
        name = ask_themed_string(self, "Duplicate Profile", "Enter new profile name:", self.colors)
        if name:
            from ...connection_profiles import ProfileStore
            store = ProfileStore.get_instance()
            source = store.get_profile_dict(self.current_profile) or {}
            store.set_profile_from_dict(name, dict(source))
            self.current_profile = name
            self.name_var.set(name)
            self._refresh_list()
            self._ignore_select_event = True
            self.profile_listbox.select(name)
            self._ignore_select_event = False
            self._on_profile_select(name)
            self.save_status.configure(text=f"✅ Duplicated as '{name}'")

    def _delete_profile(self):
        if not self.current_profile:
            return
        if messagebox.askyesno("Delete Profile", f"Delete profile '{self.current_profile}'?", parent=self):
            from ...connection_profiles import ProfileStore
            store = ProfileStore.get_instance()
            store.delete_profile(self.current_profile)
            self.current_profile = None
            self.name_var.set("")
            self.description_var.set("")
            for widget_info in self.field_widgets.values():
                if widget_info["type"] == "toggle":
                    widget_info["var"].set(False)
                elif widget_info["type"] == "key_name_dropdown":
                    widget_info["var"].set("")
                    w = widget_info.get("widget")
                    if w and hasattr(w, "set"):
                        w.set("")
                else:
                    widget_info["var"].set("")
            self._refresh_list()
            self._update_summary()
            self._last_saved_values = None
            self.title("Connection Profiles")
    
    def _on_close_attempt(self):
        """Handle window close — check for unsaved changes first."""
        if not self._prompt_unsaved_if_dirty():
            return  # User cancelled — keep window open
        self.destroy()
    
    def destroy(self):
        self._destroyed = True
        # Unsubscribe from KeyStore notifications
        if hasattr(self, '_keystore_callback') and self._keystore_callback:
            try:
                from ...key_store import KeyStore
                KeyStore.get_instance().unsubscribe(self._keystore_callback)
            except Exception:
                pass
        if self.on_close:
            self.on_close()
        super().destroy()


# ─── Attached window helpers (match settings_window pattern) ──────────────

class AttachedConnectionManager:
    """ConnectionProfileManager as Toplevel attached to GUICoordinator's root."""

    def __init__(self, parent_root, on_close=None):
        self.parent_root = parent_root
        ConnectionProfileManager(parent_root, on_close=on_close)


def create_attached_connection_manager(parent_root, on_close=None):
    """Create a connection manager window (called on GUI thread)."""
    AttachedConnectionManager(parent_root, on_close)
