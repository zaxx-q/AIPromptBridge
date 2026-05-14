#!/usr/bin/env python3
"""
Dialog windows for the Prompt Editor.

Standalone dialog classes that can be used independently:
- ThemedInputDialog / ask_themed_string: Themed text input dialog
- TestResultDialog: Streaming API test result viewer
- PresetManagerDialog: Model preset CRUD manager (usable outside prompt editor)
"""

import queue
import tkinter as tk
from tkinter import messagebox
from typing import Callable, Optional

from ...platform import HAVE_CTK, ctk
from ...themes import (
    ThemeColors, get_colors,
    get_ctk_button_colors, get_ctk_frame_colors, get_ctk_entry_colors,
    get_ctk_textbox_colors, get_ctk_combobox_colors, get_ctk_label_colors,
    get_ctk_font
)
from ...custom_widgets import ScrollableButtonList, ScrollableComboBox, create_emoji_button, TkScrollableFrame, ask_themed_string
from ..utils import set_window_icon


# Import emoji renderer for CTkImage support (Windows color emoji fix)
try:
    from ...emoji_renderer import get_emoji_renderer, HAVE_PIL
    HAVE_EMOJI = HAVE_PIL and HAVE_CTK
except ImportError:
    HAVE_EMOJI = False
    get_emoji_renderer = None





# =============================================================================
# Test Result Dialog (Streaming)
# =============================================================================

class TestResultDialog(ctk.CTkToplevel if HAVE_CTK else tk.Toplevel):
    """
    Streaming test result dialog.
    Supports real-time updates for text and thinking content.
    """
    
    def __init__(self, parent, colors):
        super().__init__(parent)
        self.colors = colors
        self.use_ctk = HAVE_CTK
        self.queue = queue.Queue()
        
        self.title("API Test Result")
        self.geometry("700x500")
        self.transient(parent)
        
        if self.use_ctk:
            self.configure(fg_color=colors.bg)
        else:
            self.configure(bg=colors.bg)

        set_window_icon(self)
            
        # Main content area
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent") if self.use_ctk else tk.Frame(self, bg=colors.bg)
        self.main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Output text area
        if self.use_ctk:
            self.output_box = ctk.CTkTextbox(
                self.main_frame, font=get_ctk_font(12),
                **get_ctk_textbox_colors(colors)
            )
        else:
            self.output_box = tk.Text(
                self.main_frame, font=("Consolas", 10),
                bg=colors.surface0, fg=colors.fg, wrap="word"
            )
        self.output_box.pack(fill="both", expand=True, pady=(0, 10))
        
        # Tags for styling (Tk only, CTk doesn't support tags in same way yet)
        if not self.use_ctk:
            self.output_box.tag_config("thinking", foreground=colors.blockquote, font=("Consolas", 9, "italic"))
            self.output_box.tag_config("error", foreground=colors.accent_red)
        
        # Close button
        if self.use_ctk:
            ctk.CTkButton(
                self.main_frame, text="Close", font=get_ctk_font(11),
                width=100, **get_ctk_button_colors(colors, "primary"),
                command=self.destroy
            ).pack()
        else:
            tk.Button(
                self.main_frame, text="Close", font=("Segoe UI", 10),
                bg=colors.accent, fg="#ffffff",
                command=self.destroy
            ).pack()
            
        # State
        self.thinking_started = False
        
        # Start message
        self._safe_insert("Waiting for response...\n\n")
        
        # Start queue polling
        self._check_queue()
        
    def _check_queue(self):
        """Poll the queue for updates."""
        try:
            while True:
                task = self.queue.get_nowait()
                try:
                    task()
                except Exception as e:
                    print(f"Error in queue task: {e}")
        except queue.Empty:
            pass
        
        try:
            if self.winfo_exists():
                self.after(50, self._check_queue)
        except Exception:
            pass
            
    def append_text(self, text):
        """Append normal response text."""
        # If we were thinking, close the block now that we have text
        if self.thinking_started:
            self.end_thinking()
            
        self._safe_insert(text)
        
    def append_thinking(self, text):
        """Append thinking/reasoning text."""
        if not self.thinking_started:
            self._safe_insert("\n========== THINKING ==========\n", "thinking")
            self.thinking_started = True
            
        self._safe_insert(text, "thinking")
        
    def end_thinking(self):
        """Mark end of thinking."""
        if self.thinking_started:
             self._safe_insert("\n========== THINKING END ==========\n\n", "thinking")
             self.thinking_started = False
        
    def append_error(self, text):
        """Append error message."""
        self._safe_insert(f"\n[Error] {text}\n", "error")
        
    def _safe_insert(self, text, tag=None):
        """Thread-safe text insertion via queue."""
        def _update():
            try:
                if self.use_ctk:
                    self.output_box.insert("end", text)
                    self.output_box.see("end")
                else:
                    self.output_box.insert("end", text, tag)
                    self.output_box.see("end")
            except Exception:
                pass
        
        self.queue.put(_update)


# =============================================================================
# Model Preset Manager Dialog
# =============================================================================

class PresetManagerDialog(ctk.CTkToplevel if HAVE_CTK else tk.Toplevel):
    """
    Dialog for creating, editing, and deleting model presets.

    Features:
    - Model dropdown with refresh button (fetches available models from provider)
    - Provider-aware field visibility (hides irrelevant fields per provider)
    - Description field for documenting preset purpose
    - Summary panel showing overridden vs. default fields
    - Test button to verify preset works via a quick API call
    - Populate from current config button

    Can be used standalone (outside of prompt editor) by providing
    a parent window and colors:

        from src.gui.windows.prompt_editor.dialogs import PresetManagerDialog
        from src.gui.themes import get_colors
        PresetManagerDialog(parent_window, get_colors())
    """

    PRESET_FIELDS = [
        ("provider", "Provider", "combobox", ["google", "openrouter", "custom"]),
        ("model", "Model", "model_dropdown", None),
        ("streaming", "Streaming", "checkbox", None),
        ("thinking", "Thinking", "checkbox", None),
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

    # Fields only visible for specific providers (others always visible)
    PROVIDER_FIELD_VISIBILITY = {
        "custom_url": {"custom"},
        "gemini_endpoint": {"google"},
        "thinking_budget": {"google"},
        "thinking_level": {"google"},
        "reasoning_effort": {"custom", "openrouter"},
    }

    def __init__(self, parent, colors: ThemeColors = None, on_close=None):
        super().__init__(parent)
        self.colors = colors or get_colors()
        self.on_close = on_close
        self.use_ctk = HAVE_CTK
        self.field_widgets = {}
        self.field_rows = {}  # Row frames keyed by field name (for visibility toggling)
        self.current_preset = None
        self._model_status_label = None
        self._model_dropdown_widget = None
        self._summary_label = None
        self._fields_container = None
        self._destroyed = False

        self.title("Manage Model Presets")
        self.geometry("750x720")
        self.minsize(650, 550)
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
        
        from ....key_store import KeyStore
        pools = KeyStore.get_instance().get_all_pool_ids()
        self.preset_fields = []
        for field in self.PRESET_FIELDS:
            if field[0] == "api_key_pool":
                self.preset_fields.append(("api_key_pool", "API Key Pool", "combobox", [""] + pools))
            else:
                self.preset_fields.append(field)
                
        self._build_ui()
        self._refresh_list()

        self.deiconify()

    def _build_ui(self):
        """Build the preset manager UI."""
        c = self.colors

        # Title
        if self.use_ctk:
            ctk.CTkLabel(self, text="⚙️  Model Presets", font=get_ctk_font(16, "bold"),
                        **get_ctk_label_colors(c)).pack(anchor="w", padx=20, pady=(15, 10))
        else:
            tk.Label(self, text="⚙️  Model Presets", font=("Segoe UI", 14, "bold"),
                    bg=c.bg, fg=c.fg).pack(anchor="w", padx=20, pady=(15, 10))

        # Main container: left list + right editor
        container = ctk.CTkFrame(self, fg_color="transparent") if self.use_ctk else tk.Frame(self, bg=c.bg)
        container.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        # Left panel: preset list
        left = ctk.CTkFrame(container, fg_color="transparent", width=200) if self.use_ctk else tk.Frame(container, bg=c.bg, width=200)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        self.preset_listbox = ScrollableButtonList(
            left, c, command=self._on_preset_select,
            **({"corner_radius": 8, "fg_color": c.input_bg} if self.use_ctk else {"bg": c.input_bg})
        )
        self.preset_listbox.pack(fill="both", expand=True)

        # Buttons
        btn_frame = ctk.CTkFrame(left, fg_color="transparent") if self.use_ctk else tk.Frame(left, bg=c.bg)
        btn_frame.pack(fill="x", pady=(8, 0))

        create_emoji_button(btn_frame, "New", "➕", c, "success", 70, 30, self._new_preset).pack(side="left", padx=2)
        create_emoji_button(btn_frame, "", "📋", c, "secondary", 35, 30, self._duplicate_preset).pack(side="left", padx=2)
        create_emoji_button(btn_frame, "", "🗑️", c, "danger", 35, 30, self._delete_preset).pack(side="left", padx=2)

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

        # --- Preset Name ---
        row = ctk.CTkFrame(editor, fg_color="transparent") if self.use_ctk else tk.Frame(editor, bg=c.bg)
        row.pack(fill="x", pady=5)
        if self.use_ctk:
            ctk.CTkLabel(row, text="Preset Name:", font=get_ctk_font(13, "bold"), width=130, anchor="w",
                        **get_ctk_label_colors(c)).pack(side="left")
            self.name_var = tk.StringVar()
            self.name_entry = ctk.CTkEntry(row, textvariable=self.name_var, font=get_ctk_font(13),
                                           height=32, **get_ctk_entry_colors(c))
            self.name_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        else:
            tk.Label(row, text="Preset Name:", font=("Segoe UI", 10, "bold"), width=14, anchor="w",
                    bg=c.bg, fg=c.fg).pack(side="left")
            self.name_var = tk.StringVar()
            self.name_entry = tk.Entry(row, textvariable=self.name_var, font=("Segoe UI", 10),
                                       bg=c.input_bg, fg=c.fg)
            self.name_entry.pack(side="left", fill="x", expand=True, padx=(5, 0))

        # --- Description Field ---
        row = ctk.CTkFrame(editor, fg_color="transparent") if self.use_ctk else tk.Frame(editor, bg=c.bg)
        row.pack(fill="x", pady=3)
        if self.use_ctk:
            ctk.CTkLabel(row, text="Description:", font=get_ctk_font(12), width=130, anchor="w",
                        **get_ctk_label_colors(c)).pack(side="left")
            self.description_var = tk.StringVar()
            ctk.CTkEntry(row, textvariable=self.description_var, font=get_ctk_font(12),
                         height=30, placeholder_text="Optional notes about this preset...",
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

        # Field note
        if self.use_ctk:
            ctk.CTkLabel(editor, text="Leave fields empty to use global defaults",
                        font=get_ctk_font(11), text_color=c.surface2).pack(anchor="w", pady=(0, 5))
        else:
            tk.Label(editor, text="Leave fields empty to use global defaults",
                    font=("Segoe UI", 9), bg=c.bg, fg=c.surface2).pack(anchor="w", pady=(0, 5))

        # --- Dedicated container for preset fields (for visibility reordering) ---
        self._fields_container = ctk.CTkFrame(editor, fg_color="transparent") if self.use_ctk else tk.Frame(editor, bg=c.bg)
        self._fields_container.pack(fill="x")

        # Build fields
        for key, label, field_type, options in self.preset_fields:
            row = ctk.CTkFrame(self._fields_container, fg_color="transparent") if self.use_ctk else tk.Frame(self._fields_container, bg=c.bg)
            row.pack(fill="x", pady=3)
            self.field_rows[key] = row

            if field_type == "checkbox":
                self._build_checkbox_field(row, key, label, c)

            elif field_type == "model_dropdown":
                self._build_model_dropdown_field(row, key, label, c)

            elif field_type == "combobox":
                self._build_combobox_field(row, key, label, options, c)

            else:  # entry
                self._build_entry_field(row, key, label, c)

        # --- Summary Panel ---
        if self.use_ctk:
            ctk.CTkFrame(editor, fg_color=c.surface1, height=1).pack(fill="x", pady=(10, 5))
        else:
            tk.Frame(editor, bg=c.surface1, height=1).pack(fill="x", pady=(10, 5))

        summary_frame = ctk.CTkFrame(editor, fg_color=c.surface0, corner_radius=8) if self.use_ctk else tk.Frame(editor, bg=c.surface0)
        summary_frame.pack(fill="x", pady=(0, 5))

        if self.use_ctk:
            ctk.CTkLabel(summary_frame, text="📋 Preset Summary", font=get_ctk_font(11, "bold"),
                        **get_ctk_label_colors(c)).pack(anchor="w", padx=10, pady=(6, 2))
            self._summary_label = ctk.CTkLabel(
                summary_frame, text="No preset loaded",
                font=get_ctk_font(10), justify="left", anchor="w",
                wraplength=400,
                **get_ctk_label_colors(c, muted=True)
            )
            self._summary_label.pack(anchor="w", padx=10, pady=(0, 6))
        else:
            tk.Label(summary_frame, text="📋 Preset Summary", font=("Segoe UI", 9, "bold"),
                    bg=c.surface0, fg=c.fg).pack(anchor="w", padx=10, pady=(6, 2))
            self._summary_label = tk.Label(
                summary_frame, text="No preset loaded",
                font=("Segoe UI", 8), justify="left", anchor="w",
                wraplength=400,
                bg=c.surface0, fg=c.blockquote
            )
            self._summary_label.pack(anchor="w", padx=10, pady=(0, 6))

        # --- Action Buttons Row ---
        btn_row = ctk.CTkFrame(right, fg_color="transparent") if self.use_ctk else tk.Frame(right, bg=c.bg)
        btn_row.pack(fill="x", pady=(10, 5))

        create_emoji_button(btn_row, "Save", "💾", c, "success", 100, 34, self._save_preset).pack(side="left", padx=(0, 4))
        create_emoji_button(btn_row, "Test", "🧪", c, "primary", 90, 34, self._test_preset).pack(side="left", padx=4)
        create_emoji_button(btn_row, "From Config", "⚡", c, "secondary", 130, 34, self._populate_from_config).pack(side="left", padx=4)

        if self.use_ctk:
            self.save_status = ctk.CTkLabel(btn_row, text="", font=get_ctk_font(11),
                                            text_color=c.accent_green)
        else:
            self.save_status = tk.Label(btn_row, text="", font=("Segoe UI", 9),
                                        bg=c.bg, fg=c.accent_green)
        self.save_status.pack(side="left", padx=12)

        # Apply initial provider visibility
        self._on_provider_change("")

    # -------------------------------------------------------------------------
    # Field builder helpers
    # -------------------------------------------------------------------------

    def _build_checkbox_field(self, row, key: str, label: str, c: ThemeColors):
        """Build a checkbox field with enable toggle."""
        var = tk.BooleanVar()
        enabled_var = tk.BooleanVar(value=False)

        if self.use_ctk:
            ctk.CTkCheckBox(row, text="", variable=enabled_var, width=20,
                            fg_color=c.accent, checkbox_width=18, checkbox_height=18
                            ).pack(side="left", padx=(0, 4))
            ctk.CTkLabel(row, text=f"{label}:", font=get_ctk_font(12), width=130, anchor="w",
                        **get_ctk_label_colors(c)).pack(side="left")
            ctk.CTkCheckBox(row, text="Enabled", variable=var,
                            font=get_ctk_font(12), text_color=c.fg, fg_color=c.accent
                            ).pack(side="left", padx=(8, 0))
        else:
            tk.Checkbutton(row, text="", variable=enabled_var,
                           bg=c.bg, selectcolor=c.input_bg).pack(side="left", padx=(0, 4))
            tk.Label(row, text=f"{label}:", font=("Segoe UI", 9), width=14, anchor="w",
                    bg=c.bg, fg=c.fg).pack(side="left")
            tk.Checkbutton(row, text="Enabled", variable=var,
                           bg=c.bg, fg=c.fg, selectcolor=c.input_bg).pack(side="left", padx=(5, 0))

        self.field_widgets[key] = {"var": var, "enabled_var": enabled_var, "type": "checkbox"}

    def _build_model_dropdown_field(self, row, key: str, label: str, c: ThemeColors):
        """Build a model dropdown field with refresh button."""
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

    # -------------------------------------------------------------------------
    # Provider-aware field visibility
    # -------------------------------------------------------------------------

    def _on_provider_change(self, provider: str = None):
        """Show/hide fields based on selected provider."""
        if not provider:
            provider_info = self.field_widgets.get("provider")
            provider = provider_info["var"].get() if provider_info else ""

        # Unpack all field rows, then re-pack visible ones in defined order
        for key, _, _, _ in self.preset_fields:
            row = self.field_rows.get(key)
            if row:
                row.pack_forget()

        for key, _, _, _ in self.preset_fields:
            row = self.field_rows.get(key)
            if not row:
                continue

            allowed = self.PROVIDER_FIELD_VISIBILITY.get(key)
            if allowed is None or not provider or provider in allowed:
                row.pack(fill="x", pady=3)

    # -------------------------------------------------------------------------
    # Model fetching
    # -------------------------------------------------------------------------

    def _refresh_models(self):
        """Fetch models from the selected provider in a background thread."""
        import threading

        # Collect all UI values on the main thread to avoid tk.StringVar
        # access from background threads (causes RuntimeError).
        provider_info = self.field_widgets.get("provider")
        provider = provider_info["var"].get() if provider_info else ""
        if not provider:
            self._set_model_status("❌ Select provider first", "error")
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
                    self._schedule_ui(lambda: self._set_model_status("❌ No API keys", "error"))
                    return

                temp_km = KeyManager(key_strings, provider)
                temp_config = {"request_timeout": 30}

                if provider == "custom":
                    url = custom_url_value or config.get("custom_url", "")
                    if url:
                        temp_config["custom_url"] = url
                    else:
                        self._schedule_ui(lambda: self._set_model_status("❌ No custom URL", "error"))
                        return
                elif provider == "google":
                    endpoint = gemini_endpoint_value or config.get("gemini_endpoint", "")
                    if endpoint:
                        temp_config["gemini_endpoint"] = endpoint

                provider_instance = get_provider_for_type(provider, temp_km, temp_config)
                models, error = provider_instance.fetch_models()

                if error:
                    err_msg = f"❌ {str(error)[:35]}"
                    self._schedule_ui(lambda: self._set_model_status(err_msg, "error"))
                    return

                if not models:
                    self._schedule_ui(lambda: self._set_model_status("⚠️ No models", "warning"))
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
                err_msg = f"❌ {str(e)[:30]}"
                self._schedule_ui(lambda: self._set_model_status(err_msg, "error"))

        threading.Thread(target=_fetch, daemon=True).start()

    def _set_model_status(self, text: str, level: str = "info"):
        """Update model fetch status label."""
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
        """Schedule a UI update on the main thread via GUICoordinator."""
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
            # Fallback if GUICoordinator not available
            try:
                if self.winfo_exists():
                    self.after(0, safe_wrapper)
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Summary panel
    # -------------------------------------------------------------------------

    def _update_summary(self):
        """Update the summary panel with current preset overrides."""
        if not self._summary_label:
            return

        overrides = []
        defaults = []
        provider_info = self.field_widgets.get("provider")
        provider = provider_info["var"].get() if provider_info else ""

        for key, label, field_type, _ in self.preset_fields:
            widget_info = self.field_widgets.get(key)
            if not widget_info:
                continue

            # Skip fields hidden for current provider
            allowed = self.PROVIDER_FIELD_VISIBILITY.get(key)
            if allowed and provider and provider not in allowed:
                continue

            if field_type == "checkbox":
                if widget_info.get("enabled_var") and widget_info["enabled_var"].get():
                    val = "on" if widget_info["var"].get() else "off"
                    overrides.append(f"{label}={val}")
                else:
                    defaults.append(label)
            else:
                val = widget_info["var"].get().strip()
                if val:
                    display_val = val[:25] + "…" if len(val) > 25 else val
                    overrides.append(f"{label}={display_val}")
                else:
                    defaults.append(label)

        if overrides:
            text = f"Overrides: {', '.join(overrides)}"
            if defaults:
                text += f"\nDefaults: {', '.join(defaults)}"
        else:
            text = "No overrides — all fields use global defaults"

        self._summary_label.configure(text=text)

    # -------------------------------------------------------------------------
    # Test preset
    # -------------------------------------------------------------------------

    def _test_preset(self):
        """Test the current preset by sending a minimal API request."""
        import threading

        preset = self._collect_preset_values()
        if not preset.get("provider") and not preset.get("model"):
            messagebox.showinfo("Test Preset", "Set at least a provider or model to test.", parent=self)
            return

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

                # Apply preset overrides to config
                provider = preset.get("provider") or config.get("default_provider", "google")
                model = preset.get("model") or config.get(f"{provider}_model", "")

                if "streaming" in preset:
                    config["streaming_enabled"] = preset["streaming"]
                if "thinking" in preset:
                    config["thinking_enabled"] = preset["thinking"]
                for field in ("thinking_budget", "thinking_level", "reasoning_effort",
                              "request_timeout", "custom_url", "gemini_endpoint"):
                    if field in preset:
                        config[field] = preset[field]
                if "temperature" in preset:
                    ai_params["temperature"] = preset["temperature"]
                if "max_tokens" in preset:
                    ai_params["max_tokens"] = preset["max_tokens"]

                # Handle api_key_pool / api_key_name overrides
                pool_override = preset.get("api_key_pool")
                key_name_override = preset.get("api_key_name")

                if pool_override:
                    # Build a KeyManager from the specified pool
                    custom_km = key_store.build_key_manager_for_pool(pool_override, provider)
                    if custom_km and custom_km.has_keys():
                        key_managers = dict(key_managers)
                        key_managers[provider] = custom_km
                    else:
                        dialog.append_error(f"Pool '{pool_override}' has no usable keys")
                        return

                if key_name_override:
                    # Filter the provider's key manager to only the named key
                    source_pool = pool_override or key_store.get_provider_pool_id(provider)
                    pool_keys = key_store.get_pool(source_pool)
                    matched = [kd for kd in pool_keys if kd.get("name") == key_name_override and kd.get("key")]
                    if matched:
                        custom_km = KeyManager([kd["key"] for kd in matched], provider,
                                               key_names=[kd["name"] for kd in matched])
                        key_managers = dict(key_managers)
                        key_managers[provider] = custom_km
                    else:
                        dialog.append_error(f"Key named '{key_name_override}' not found in pool '{source_pool}'")
                        return

                thinking_enabled = config.get("thinking_enabled", False)
                thinking_output = config.get("thinking_output", "reasoning_content")

                messages = [{"role": "user", "content": "Say 'Hello! Preset test successful.' in exactly those words."}]

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

    # -------------------------------------------------------------------------
    # Populate from config
    # -------------------------------------------------------------------------

    def _populate_from_config(self):
        """Fill all preset fields with current global config values."""
        try:
            from .... import web_server
            config = dict(web_server.CONFIG)
            ai_params = dict(web_server.AI_PARAMS)
        except (ImportError, AttributeError):
            try:
                from ....config import load_config
                config, ai_params, _ = load_config()
            except Exception:
                messagebox.showwarning("Error", "Could not load current config.", parent=self)
                return

        provider = config.get("default_provider", "google")

        field_map = {
            "provider": provider,
            "model": config.get(f"{provider}_model", ""),
            "streaming": config.get("streaming_enabled", True),
            "thinking": config.get("thinking_enabled", False),
            "thinking_budget": config.get("thinking_budget", ""),
            "thinking_level": config.get("thinking_level", ""),
            "reasoning_effort": config.get("reasoning_effort", ""),
            "temperature": ai_params.get("temperature", ""),
            "max_tokens": ai_params.get("max_tokens", ""),
            "request_timeout": config.get("request_timeout", ""),
            "custom_url": config.get("custom_url", ""),
            "gemini_endpoint": config.get("gemini_endpoint", ""),
        }

        for key, widget_info in self.field_widgets.items():
            val = field_map.get(key)
            if val is None:
                continue

            if widget_info["type"] == "checkbox":
                widget_info["enabled_var"].set(True)
                widget_info["var"].set(bool(val))
            elif widget_info["type"] == "model_dropdown":
                str_val = str(val) if val is not None and val != "" else ""
                widget_info["var"].set(str_val)
                w = widget_info.get("widget")
                if w and hasattr(w, "set"):
                    w.set(str_val)
            elif widget_info["type"] in ("entry", "combobox"):
                str_val = str(val) if val is not None and val != "" else ""
                widget_info["var"].set(str_val)

        self._on_provider_change(provider)
        self._update_summary()

        if self.use_ctk:
            self.save_status.configure(text="⚡ Populated from config", text_color=self.colors.accent)
        else:
            self.save_status.configure(text="⚡ Populated from config", fg=self.colors.accent)

    # -------------------------------------------------------------------------
    # Collect current form values
    # -------------------------------------------------------------------------

    def _collect_preset_values(self) -> dict:
        """Collect preset values from the form (without saving)."""
        preset = {}
        for key, widget_info in self.field_widgets.items():
            if widget_info["type"] == "checkbox":
                if widget_info["enabled_var"].get():
                    preset[key] = widget_info["var"].get()
            elif widget_info["type"] in ("entry", "combobox", "model_dropdown"):
                val = widget_info["var"].get().strip()
                if val:
                    if key in ("temperature",):
                        try:
                            preset[key] = float(val)
                        except ValueError:
                            preset[key] = val
                    elif key in ("thinking_budget", "max_tokens", "request_timeout"):
                        try:
                            preset[key] = int(val)
                        except ValueError:
                            preset[key] = val
                    else:
                        preset[key] = val
        return preset

    # -------------------------------------------------------------------------
    # CRUD operations
    # -------------------------------------------------------------------------

    def _refresh_list(self):
        """Refresh the preset list."""
        from ...prompts import get_prompts_config
        self.preset_listbox.clear()
        for name in get_prompts_config().get_preset_names():
            self.preset_listbox.add_item(name, name, "⚙️")

    def _on_preset_select(self, name):
        """Load preset into editor."""
        from ...prompts import get_prompts_config
        self.current_preset = name
        preset = get_prompts_config().get_model_preset(name) or {}

        self.name_var.set(name)
        self.description_var.set(preset.get("description", ""))

        for key, widget_info in self.field_widgets.items():
            val = preset.get(key)
            if widget_info["type"] == "checkbox":
                if val is not None:
                    widget_info["enabled_var"].set(True)
                    widget_info["var"].set(bool(val))
                else:
                    widget_info["enabled_var"].set(False)
                    widget_info["var"].set(False)
            elif widget_info["type"] == "model_dropdown":
                # Use .set() on the widget directly so ScrollableComboBox
                # updates both its internal state and the entry display.
                str_val = str(val) if val is not None else ""
                widget_info["var"].set(str_val)
                w = widget_info.get("widget")
                if w and hasattr(w, "set"):
                    w.set(str_val)
            else:
                widget_info["var"].set(str(val) if val is not None else "")

        # Update visibility and summary for loaded preset
        self._on_provider_change(preset.get("provider", ""))
        self._update_summary()

    def _save_preset(self):
        """Save the current preset."""
        from ...prompts import get_prompts_config
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Please enter a preset name.", parent=self)
            return

        preset = self._collect_preset_values()

        # Add description if provided
        desc = self.description_var.get().strip()
        if desc:
            preset["description"] = desc

        pc = get_prompts_config()

        # Handle rename
        if self.current_preset and self.current_preset != name:
            pc.delete_model_preset(self.current_preset)

        pc.set_model_preset(name, preset)
        self.current_preset = name
        self._refresh_list()
        self.preset_listbox.select(name)
        self._update_summary()

        self.save_status.configure(text=f"✅ Saved '{name}'")

    def _new_preset(self):
        """Create a new empty preset."""
        name = ask_themed_string(self, "New Preset", "Enter preset name:", self.colors)
        if name:
            self.current_preset = None
            self.name_var.set(name)
            self.description_var.set("")
            for widget_info in self.field_widgets.values():
                if widget_info["type"] == "checkbox":
                    widget_info["enabled_var"].set(False)
                    widget_info["var"].set(False)
                else:
                    widget_info["var"].set("")
            self._update_summary()

    def _duplicate_preset(self):
        """Duplicate the selected preset and save immediately."""
        if not self.current_preset:
            return
        name = ask_themed_string(self, "Duplicate Preset", "Enter new preset name:", self.colors)
        if name:
            from ...prompts import get_prompts_config
            pc = get_prompts_config()
            source = pc.get_model_preset(self.current_preset) or {}
            pc.set_model_preset(name, dict(source))
            self.current_preset = name
            self.name_var.set(name)
            self._refresh_list()
            self.preset_listbox.select(name)
            self.save_status.configure(text=f"✅ Duplicated as '{name}'")

    def _delete_preset(self):
        """Delete the selected preset."""
        if not self.current_preset:
            return
        if messagebox.askyesno("Delete Preset", f"Delete preset '{self.current_preset}'?", parent=self):
            from ...prompts import get_prompts_config
            get_prompts_config().delete_model_preset(self.current_preset)
            self.current_preset = None
            self.name_var.set("")
            self.description_var.set("")
            for widget_info in self.field_widgets.values():
                if widget_info["type"] == "checkbox":
                    widget_info["enabled_var"].set(False)
                    widget_info["var"].set(False)
                else:
                    widget_info["var"].set("")
            self._refresh_list()
            self._update_summary()

    def destroy(self):
        """Override destroy to call on_close callback."""
        self._destroyed = True
        if self.on_close:
            self.on_close()
        super().destroy()
