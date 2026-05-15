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

import queue
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Optional

from ...platform import HAVE_CTK, ctk
from ...themes import (
    ThemeColors, get_colors,
    get_ctk_button_colors, get_ctk_frame_colors, get_ctk_entry_colors,
    get_ctk_textbox_colors, get_ctk_combobox_colors, get_ctk_label_colors,
    get_ctk_font
)
from ...custom_widgets import (
    ScrollableButtonList, ScrollableComboBox, create_emoji_button,
    TkScrollableFrame, ask_themed_string
)
from ..utils import set_window_icon

try:
    from ...emoji_renderer import get_emoji_renderer, HAVE_PIL
    HAVE_EMOJI = HAVE_PIL and HAVE_CTK
except ImportError:
    HAVE_EMOJI = False


# Profile fields: (key, label, field_type, options)
PROFILE_FIELDS = [
    ("provider", "Provider", "combobox", ["google", "openrouter", "custom"]),
    ("model", "Model", "model_dropdown", None),
    ("streaming", "Streaming", "toggle", None),
    ("thinking", "Thinking", "toggle", None),
    ("thinking_budget", "Thinking Budget", "entry", None),
    ("thinking_level", "Thinking Level", "combobox", ["", "low", "high"]),
    ("reasoning_effort", "Reasoning Effort", "combobox", ["", "low", "medium", "high"]),
    ("temperature", "Temperature", "entry", None),
    ("max_tokens", "Max Tokens", "entry", None),
    ("request_timeout", "Request Timeout (s)", "entry", None),
    ("custom_url", "Custom URL", "entry", None),
    ("gemini_endpoint", "Gemini Endpoint", "entry", None),
    ("api_key_name", "API Key Name", "entry", None),
    ("api_key_pool", "API Key Pool", "combobox", None),
]

PROVIDER_FIELD_VISIBILITY = {
    "custom_url": {"custom"},
    "gemini_endpoint": {"google"},
    "thinking_budget": {"google"},
    "thinking_level": {"google"},
    "reasoning_effort": {"custom", "openrouter"},
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
        self._fields_container = None
        self._destroyed = False

        self.title("Connection Profiles")
        self.geometry("780x740")
        self.minsize(680, 580)
        self.transient(parent)
        self.grab_set()

        if self.use_ctk:
            self.configure(fg_color=self.colors.bg)
        else:
            self.configure(bg=self.colors.bg)

        self.withdraw()
        from ..utils import set_dark_titlebar
        set_dark_titlebar(self)
        set_window_icon(self)

        # Resolve api_key_pool options from KeyStore
        self.profile_fields = []
        try:
            from ....key_store import KeyStore
            pools = KeyStore.get_instance().get_all_pool_ids()
        except Exception:
            pools = []
        for field in PROFILE_FIELDS:
            if field[0] == "api_key_pool":
                self.profile_fields.append(("api_key_pool", "API Key Pool", "combobox", [""] + pools))
            else:
                self.profile_fields.append(field)

        self._build_ui()
        self._refresh_list()
        self.deiconify()

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
            else:
                self._build_entry_field(row, key, label, c)

        # --- Summary Panel ---
        if self.use_ctk:
            ctk.CTkFrame(editor, fg_color=c.surface1, height=1).pack(fill="x", pady=(10, 5))
        else:
            tk.Frame(editor, bg=c.surface1, height=1).pack(fill="x", pady=(10, 5))

        summary_frame = ctk.CTkFrame(editor, fg_color=c.surface0, corner_radius=8) if self.use_ctk else tk.Frame(editor, bg=c.surface0)
        summary_frame.pack(fill="x", pady=(0, 5))

        if self.use_ctk:
            ctk.CTkLabel(summary_frame, text="📋 Profile Summary", font=get_ctk_font(11, "bold"),
                        **get_ctk_label_colors(c)).pack(anchor="w", padx=10, pady=(6, 2))
            self._summary_label = ctk.CTkLabel(
                summary_frame, text="No profile selected",
                font=get_ctk_font(10), justify="left", anchor="w",
                wraplength=400,
                **get_ctk_label_colors(c, muted=True)
            )
            self._summary_label.pack(anchor="w", padx=10, pady=(0, 6))
        else:
            tk.Label(summary_frame, text="📋 Profile Summary", font=("Segoe UI", 9, "bold"),
                    bg=c.surface0, fg=c.fg).pack(anchor="w", padx=10, pady=(6, 2))
            self._summary_label = tk.Label(
                summary_frame, text="No profile selected",
                font=("Segoe UI", 8), justify="left", anchor="w",
                wraplength=400,
                bg=c.surface0, fg=c.blockquote
            )
            self._summary_label.pack(anchor="w", padx=10, pady=(0, 6))

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

    def _build_toggle_field(self, row, key: str, label: str, c: ThemeColors):
        """Build a toggle (checkbox) field — always has a value, no enable checkbox."""
        var = tk.BooleanVar(value=False)

        if self.use_ctk:
            ctk.CTkLabel(row, text=f"{label}:", font=get_ctk_font(12), width=150, anchor="w",
                        **get_ctk_label_colors(c)).pack(side="left")
            ctk.CTkCheckBox(row, text="Enabled", variable=var,
                            font=get_ctk_font(12), text_color=c.fg, fg_color=c.accent
                            ).pack(side="left", padx=(8, 0))
        else:
            tk.Label(row, text=f"{label}:", font=("Segoe UI", 9), width=14, anchor="w",
                    bg=c.bg, fg=c.fg).pack(side="left")
            tk.Checkbutton(row, text="Enabled", variable=var,
                           bg=c.bg, fg=c.fg, selectcolor=c.input_bg).pack(side="left", padx=(5, 0))

        self.field_widgets[key] = {"var": var, "type": "toggle"}

    def _build_model_dropdown_field(self, row, key: str, label: str, c: ThemeColors):
        """Build model dropdown with refresh button."""
        var = tk.StringVar()

        if self.use_ctk:
            ctk.CTkLabel(row, text=f"{label}:", font=get_ctk_font(12), width=150, anchor="w",
                        **get_ctk_label_colors(c)).pack(side="left")
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
            tk.Label(row, text=f"{label}:", font=("Segoe UI", 9), width=14, anchor="w",
                    bg=c.bg, fg=c.fg).pack(side="left")
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

        self.field_widgets[key] = {"var": var, "type": "model_dropdown", "widget": dropdown}

    def _build_combobox_field(self, row, key: str, label: str, options: list, c: ThemeColors):
        """Build a combobox/dropdown field."""
        var = tk.StringVar()
        command = self._on_provider_change if key == "provider" else None

        if self.use_ctk:
            ctk.CTkLabel(row, text=f"{label}:", font=get_ctk_font(12), width=150, anchor="w",
                        **get_ctk_label_colors(c)).pack(side="left")
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
            tk.Label(row, text=f"{label}:", font=("Segoe UI", 9), width=14, anchor="w",
                    bg=c.bg, fg=c.fg).pack(side="left")
            combo = ttk_local.Combobox(row, textvariable=var, values=options or [],
                                       state="readonly", width=18)
            combo.pack(side="left", padx=(5, 0))
            if command:
                combo.bind('<<ComboboxSelected>>', lambda e: command(var.get()))

        self.field_widgets[key] = {"var": var, "type": "combobox"}

    def _build_entry_field(self, row, key: str, label: str, c: ThemeColors):
        """Build a text entry field."""
        var = tk.StringVar()

        if self.use_ctk:
            ctk.CTkLabel(row, text=f"{label}:", font=get_ctk_font(12), width=150, anchor="w",
                        **get_ctk_label_colors(c)).pack(side="left")
            ctk.CTkEntry(row, textvariable=var, font=get_ctk_font(12),
                         height=30, width=250, **get_ctk_entry_colors(c)
                         ).pack(side="left", padx=(8, 0))
        else:
            tk.Label(row, text=f"{label}:", font=("Segoe UI", 9), width=14, anchor="w",
                    bg=c.bg, fg=c.fg).pack(side="left")
            tk.Entry(row, textvariable=var, font=("Segoe UI", 9),
                     bg=c.input_bg, fg=c.fg, width=25).pack(side="left", padx=(5, 0))

        self.field_widgets[key] = {"var": var, "type": "entry"}

    # ─── Provider-aware visibility ────────────────────────────────────────

    def _on_provider_change(self, provider: str = None):
        if not provider:
            provider_info = self.field_widgets.get("provider")
            provider = provider_info["var"].get() if provider_info else ""

        for key, _, _, _ in self.profile_fields:
            row = self.field_rows.get(key)
            if row:
                row.pack_forget()

        for key, _, _, _ in self.profile_fields:
            row = self.field_rows.get(key)
            if not row:
                continue
            allowed = PROVIDER_FIELD_VISIBILITY.get(key)
            if allowed is None or not provider or provider in allowed:
                row.pack(fill="x", pady=3)

    # ─── Model fetching ──────────────────────────────────────────────────

    def _refresh_models(self):
        provider_info = self.field_widgets.get("provider")
        provider = provider_info["var"].get() if provider_info else ""
        if not provider:
            self._set_model_status("Select provider first", "error")
            return

        custom_url_info = self.field_widgets.get("custom_url")
        custom_url_value = custom_url_info["var"].get() if custom_url_info else ""

        gemini_endpoint_info = self.field_widgets.get("gemini_endpoint")
        gemini_endpoint_value = gemini_endpoint_info["var"].get() if gemini_endpoint_info else ""

        self._set_model_status("🔄 Loading...", "info")

        def _fetch():
            try:
                from ....config import load_config
                from ....key_store import KeyStore
                from ....key_manager import KeyManager
                from ....api_client import get_provider_for_type

                config, _, _ = load_config()
                key_store = KeyStore.get_instance()
                keys_data = key_store.get_pool_for_provider(provider)
                key_strings = [kd["key"] for kd in keys_data if kd.get("key")]
                if not key_strings:
                    self._schedule_ui(lambda: self._set_model_status("No API keys", "error"))
                    return

                temp_km = KeyManager(key_strings, provider)
                temp_config = {"request_timeout": 30}

                if provider == "custom":
                    url = custom_url_value or config.get("custom_url", "")
                    if url:
                        temp_config["custom_url"] = url
                    else:
                        self._schedule_ui(lambda: self._set_model_status("No custom URL", "error"))
                        return
                elif provider == "google":
                    endpoint = gemini_endpoint_value or config.get("gemini_endpoint", "")
                    if endpoint:
                        temp_config["gemini_endpoint"] = endpoint

                provider_instance = get_provider_for_type(provider, temp_km, temp_config)
                models, error = provider_instance.fetch_models()

                if error:
                    err_msg = str(error)[:35]
                    self._schedule_ui(lambda: self._set_model_status(err_msg, "error"))
                    return

                if not models:
                    self._schedule_ui(lambda: self._set_model_status("No models", "warning"))
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
                self._schedule_ui(lambda: self._set_model_status(err_msg, "error"))

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
            from ...core import GUICoordinator
            GUICoordinator.get_instance().run_on_gui_thread(safe_wrapper)
        except Exception:
            try:
                if self.winfo_exists():
                    self.after(0, safe_wrapper)
            except Exception:
                pass

    # ─── Summary ──────────────────────────────────────────────────────────

    def _update_summary(self):
        if not self._summary_label:
            return

        provider_info = self.field_widgets.get("provider")
        provider = provider_info["var"].get() if provider_info else ""

        parts = []
        for key, label, field_type, _ in self.profile_fields:
            widget_info = self.field_widgets.get(key)
            if not widget_info:
                continue
            allowed = PROVIDER_FIELD_VISIBILITY.get(key)
            if allowed and provider and provider not in allowed:
                continue

            if field_type == "toggle":
                val = "ON" if widget_info["var"].get() else "OFF"
                parts.append(f"{label}={val}")
            else:
                val = widget_info["var"].get().strip()
                if val:
                    display_val = val[:25] + "…" if len(val) > 25 else val
                    parts.append(f"{label}={display_val}")

        text = ", ".join(parts) if parts else "No profile selected"

        # Show active profile indicator
        from ....connection_profiles import ProfileStore
        store = ProfileStore.get_instance()
        active_name = store.get_active_profile_name()
        if self.current_profile and self.current_profile == active_name:
            text = f"⭐ ACTIVE PROFILE\n{text}"

        self._summary_label.configure(text=text)

    # ─── Test profile ─────────────────────────────────────────────────────

    def _test_profile(self):
        profile_data = self._collect_profile_values()
        if not profile_data.get("provider") and not profile_data.get("model"):
            messagebox.showinfo("Test Profile", "Set at least a provider or model to test.", parent=self)
            return

        from ...windows.prompt_editor.dialogs import TestResultDialog
        dialog = TestResultDialog(self, self.colors)

        def _test_thread():
            try:
                from ....config import load_config
                from ....key_manager import KeyManager
                from ....api_client import call_api_stream_unified

                config, ai_params_loaded, _ = load_config()
                ai_params = {k: v for k, v in ai_params_loaded.items() if v is not None}

                from ....key_store import KeyStore
                key_store = KeyStore.get_instance()
                key_managers = key_store.build_key_managers()

                provider = profile_data.get("provider") or config.get("default_provider", "google")
                model = profile_data.get("model") or config.get(f"{provider}_model", "")

                if "streaming" in profile_data:
                    config["streaming_enabled"] = profile_data["streaming"]
                if "thinking" in profile_data:
                    config["thinking_enabled"] = profile_data["thinking"]
                for field in ("thinking_budget", "thinking_level", "reasoning_effort",
                              "request_timeout", "custom_url", "gemini_endpoint"):
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
                thinking_output = config.get("thinking_output", "reasoning_content")

                messages = [{"role": "user", "content": "Say 'Hello! Profile test successful.' in exactly those words."}]

                def stream_callback(type_, content):
                    if type_ == "text":
                        dialog.append_text(content)
                    elif type_ == "thinking":
                        dialog.append_thinking(content)
                    elif type_ == "error":
                        dialog.append_error(str(content))

                call_api_stream_unified(
                    provider_type=provider,
                    messages=messages,
                    model=model,
                    config=config,
                    ai_params=ai_params,
                    key_managers=key_managers,
                    callback=stream_callback,
                    thinking_enabled=thinking_enabled,
                    thinking_output=thinking_output,
                )
            except Exception as e:
                dialog.append_error(str(e))

        threading.Thread(target=_test_thread, daemon=True).start()

    # ─── Set as Active ────────────────────────────────────────────────────

    def _set_as_active(self):
        if not self.current_profile:
            messagebox.showinfo("Set Active", "Select a profile first.", parent=self)
            return

        from ....web_server import switch_active_profile
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
            elif widget_info["type"] in ("entry", "combobox", "model_dropdown"):
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
        from ....connection_profiles import ProfileStore
        store = ProfileStore.get_instance()
        active = store.get_active_profile_name()

        self.profile_listbox.clear()
        for name in store.get_profile_names():
            icon = "⭐" if name == active else "🔌"
            self.profile_listbox.add_item(name, name, icon)

    def _on_profile_select(self, name):
        from ....connection_profiles import ProfileStore
        self.current_profile = name
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
            else:
                str_val = str(val) if val is not None and val != "" else ""
                # Convert None to empty string for display
                if str_val == "None":
                    str_val = ""
                widget_info["var"].set(str_val)

        self._on_provider_change(profile_data.get("provider", ""))
        self._update_summary()

    def _save_profile(self):
        from ....connection_profiles import ProfileStore
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Please enter a profile name.", parent=self)
            return

        profile_data = self._collect_profile_values()
        desc = self.description_var.get().strip()
        if desc:
            profile_data["description"] = desc

        store = ProfileStore.get_instance()

        # Handle rename
        if self.current_profile and self.current_profile != name:
            store.rename_profile(self.current_profile, name)

        store.set_profile_from_dict(name, profile_data)
        self.current_profile = name
        self._refresh_list()
        self.profile_listbox.select(name)
        self._update_summary()

        # If this is the active profile, apply changes live
        active = store.get_active_profile_name()
        if name == active:
            from ....web_server import switch_active_profile
            switch_active_profile(name)

        self.save_status.configure(text=f"✅ Saved '{name}'")

    def _new_profile(self):
        name = ask_themed_string(self, "New Profile", "Enter profile name:", self.colors)
        if name:
            from ....connection_profiles import ProfileStore, ConnectionProfile
            store = ProfileStore.get_instance()
            store.set_profile(name, ConnectionProfile())
            self.current_profile = name
            self._refresh_list()
            self.profile_listbox.select(name)
            self._on_profile_select(name)

    def _duplicate_profile(self):
        if not self.current_profile:
            return
        name = ask_themed_string(self, "Duplicate Profile", "Enter new profile name:", self.colors)
        if name:
            from ....connection_profiles import ProfileStore
            store = ProfileStore.get_instance()
            source = store.get_profile_dict(self.current_profile) or {}
            store.set_profile_from_dict(name, dict(source))
            self.current_profile = name
            self.name_var.set(name)
            self._refresh_list()
            self.profile_listbox.select(name)
            self.save_status.configure(text=f"✅ Duplicated as '{name}'")

    def _delete_profile(self):
        if not self.current_profile:
            return
        if messagebox.askyesno("Delete Profile", f"Delete profile '{self.current_profile}'?", parent=self):
            from ....connection_profiles import ProfileStore
            store = ProfileStore.get_instance()
            store.delete_profile(self.current_profile)
            self.current_profile = None
            self.name_var.set("")
            self.description_var.set("")
            for widget_info in self.field_widgets.values():
                if widget_info["type"] == "toggle":
                    widget_info["var"].set(False)
                else:
                    widget_info["var"].set("")
            self._refresh_list()
            self._update_summary()

    def destroy(self):
        self._destroyed = True
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
