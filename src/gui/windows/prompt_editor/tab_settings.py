#!/usr/bin/env python3
"""
Settings Tab Mixin for the Prompt Editor.

Provides the Settings tab UI for editing _settings objects across all tools.
"""

import tkinter as tk

from ...custom_widgets import TkScrollableFrame, create_section_header
from ...platform import HAVE_CTK, ctk
from ...themes import get_ctk_entry_colors, get_ctk_font, get_ctk_label_colors, get_ctk_textbox_colors


class SettingsTabMixin:
    """Mixin providing the Settings tab for PromptEditorWindow."""

    def _create_settings_tab(self, frame):
        """Create the Settings tab for _settings object."""
        if self.use_ctk:
            scroll_container = ctk.CTkScrollableFrame(frame, fg_color="transparent")
            scroll_frame = scroll_container
        else:
            scroll_container = TkScrollableFrame(frame, bg_color=self.colors.bg)
            scroll_frame = scroll_container.scrollable_frame
        scroll_container.pack(fill="both", expand=True, padx=15, pady=15)

        self.settings_widgets = {}

        # --- Helper for creating settings rows ---
        def add_setting_row(section_key, key, label, multiline=False, override_val=None):
            row = (
                ctk.CTkFrame(scroll_frame, fg_color="transparent")
                if self.use_ctk
                else tk.Frame(scroll_frame, bg=self.colors.bg)
            )
            row.pack(fill="x", pady=8)

            if self.use_ctk:
                ctk.CTkLabel(row, text=f"{label}:", font=get_ctk_font(12), **get_ctk_label_colors(self.colors)).pack(
                    anchor="w"
                )
            else:
                tk.Label(row, text=f"{label}:", font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg).pack(
                    anchor="w"
                )

            # Get value
            if section_key == "global":
                val = self.options_data.get("_global_settings", {}).get(key, "")
            else:
                val = self.options_data.get(section_key, {}).get("_settings", {}).get(key, "")

            if override_val is not None:
                val = override_val

            if not multiline and isinstance(val, str):
                val = val.replace("\n", "\\n")

            widget_key = f"{section_key}:{key}"

            if multiline:
                if self.use_ctk:
                    widget = ctk.CTkTextbox(
                        row, height=100, font=get_ctk_font(12), **get_ctk_textbox_colors(self.colors)
                    )
                    widget.bind("<KeyRelease>", lambda e: self._update_playground_preview())
                else:
                    widget = tk.Text(
                        row, height=4, font=("Consolas", 9), bg=self.colors.input_bg, fg=self.colors.fg, wrap="word"
                    )
                    widget.bind("<KeyRelease>", lambda e: self._update_playground_preview())
                widget.pack(fill="x", pady=(2, 0))

                if self.use_ctk:
                    widget.insert("0.0", str(val))
                else:
                    widget.insert("1.0", str(val))
                self.settings_widgets[widget_key] = ("text", widget)
                if hasattr(self, "_update_title"):
                    widget.bind("<KeyRelease>", lambda e, w=widget: self._update_title(), add="+")
            else:
                var = tk.StringVar(master=scroll_frame, value=str(val))
                var.trace_add("write", lambda *args: self._update_playground_preview())
                if self.use_ctk:
                    widget = ctk.CTkEntry(
                        row, textvariable=var, font=get_ctk_font(12), height=34, **get_ctk_entry_colors(self.colors)
                    )
                else:
                    widget = tk.Entry(
                        row, textvariable=var, font=("Segoe UI", 10), bg=self.colors.input_bg, fg=self.colors.fg
                    )
                widget.pack(fill="x", pady=(2, 0))
                self.settings_widgets[widget_key] = ("entry", var)
                if hasattr(self, "_update_title"):
                    var.trace_add("write", lambda *args: self._update_title())

        # =====================================================================
        # Global Settings
        # =====================================================================
        create_section_header(scroll_frame, "Global Settings", self.colors, "🌍")

        add_setting_row("global", "chat_window_system_instruction", "Chat Window System Instruction", True)

        # =====================================================================
        # Text Edit Tool Settings
        # =====================================================================
        if self.use_ctk:
            ctk.CTkFrame(scroll_frame, height=20, fg_color="transparent").pack()
        create_section_header(scroll_frame, "Text Edit Tool", self.colors, "✏️")

        tet_fields = [
            ("chat_system_instruction", "Direct Chat System Instruction", True),
            ("base_output_rules_edit", "Base Output Rules (Edit)", True),
            ("base_output_rules_general", "Base Output Rules (General)", True),
            ("text_delimiter", "Text Delimiter", False),
            ("text_delimiter_close", "Text Delimiter Close", False),
            ("custom_task_template", "Custom Task Template", False),
            ("ask_task_template", "Ask Task Template", False),
        ]
        for k, l, m in tet_fields:
            add_setting_row("text_edit_tool", k, l, m)

        # Popup settings for Text Edit
        row = (
            ctk.CTkFrame(scroll_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_frame, bg=self.colors.bg)
        )
        row.pack(fill="x", pady=(8, 0))
        if self.use_ctk:
            ctk.CTkLabel(
                row, text="Popup Layout:", font=get_ctk_font(12, "bold"), **get_ctk_label_colors(self.colors)
            ).pack(anchor="w")
        else:
            tk.Label(
                row, text="Popup Layout:", font=("Segoe UI", 9, "bold"), bg=self.colors.bg, fg=self.colors.fg
            ).pack(anchor="w")

        # Items per page
        row = (
            ctk.CTkFrame(scroll_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_frame, bg=self.colors.bg)
        )
        row.pack(fill="x", pady=4)
        if self.use_ctk:
            ctk.CTkLabel(row, text="Items per page:", font=get_ctk_font(12), **get_ctk_label_colors(self.colors)).pack(
                side="left"
            )
        else:
            tk.Label(row, text="Items per page:", font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg).pack(
                side="left"
            )

        tet_val = self.options_data.get("text_edit_tool", {}).get("_settings", {}).get("popup_items_per_page", 6)
        tet_items_var = tk.IntVar(master=scroll_frame, value=tet_val)
        if self.use_ctk:
            tet_items_entry = ctk.CTkEntry(
                row, textvariable=tet_items_var, width=60, font=get_ctk_font(12), **get_ctk_entry_colors(self.colors)
            )
            tet_items_entry.pack(side="left", padx=10)
            ctk.CTkLabel(
                row,
                text="(only if groups disabled)",
                font=get_ctk_font(11),
                **get_ctk_label_colors(self.colors, muted=True),
            ).pack(side="left")
        else:
            tet_items_entry = tk.Entry(row, textvariable=tet_items_var, width=5)
            tet_items_entry.pack(side="left", padx=10)
            tk.Label(
                row,
                text="(only if groups disabled)",
                font=("Segoe UI", 8),
                bg=self.colors.bg,
                fg=self.colors.blockquote,
            ).pack(side="left")
        self.settings_widgets["text_edit_tool:popup_items_per_page"] = ("int", tet_items_var)
        if hasattr(self, "_update_title"):
            tet_items_var.trace_add("write", lambda *args: self._update_title())

        # Use groups
        tet_grp_val = self.options_data.get("text_edit_tool", {}).get("_settings", {}).get("popup_use_groups", True)
        tet_grp_var = tk.BooleanVar(master=scroll_frame, value=tet_grp_val)

        def update_tet_items_state(*args):
            state = "disabled" if tet_grp_var.get() else "normal"
            tet_items_entry.configure(state=state)

        tet_grp_var.trace_add("write", update_tet_items_state)
        # Initial state
        update_tet_items_state()

        row = (
            ctk.CTkFrame(scroll_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_frame, bg=self.colors.bg)
        )
        row.pack(fill="x", pady=4)
        if self.use_ctk:
            ctk.CTkCheckBox(
                row,
                text="Use Groups",
                variable=tet_grp_var,
                font=get_ctk_font(12),
                text_color=self.colors.fg,
                fg_color=self.colors.accent,
            ).pack(anchor="w")
        else:
            tk.Checkbutton(row, text="Use Groups", variable=tet_grp_var).pack(anchor="w")
        self.settings_widgets["text_edit_tool:popup_use_groups"] = ("bool", tet_grp_var)
        if hasattr(self, "_update_title"):
            tet_grp_var.trace_add("write", lambda *args: self._update_title())

        # =====================================================================
        # Snip Tool Settings
        # =====================================================================
        if self.use_ctk:
            ctk.CTkFrame(scroll_frame, height=20, fg_color="transparent").pack()
        create_section_header(scroll_frame, "Snip Tool", self.colors, "✂️")

        add_setting_row("snip_tool", "custom_task_template", "Custom Task Template", False)

        # Allow Text Edit Actions
        row = (
            ctk.CTkFrame(scroll_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_frame, bg=self.colors.bg)
        )
        row.pack(fill="x", pady=8)

        allow_val = self.options_data.get("snip_tool", {}).get("_settings", {}).get("allow_text_edit_actions", True)
        allow_var = tk.BooleanVar(master=scroll_frame, value=allow_val)
        if self.use_ctk:
            ctk.CTkSwitch(
                row,
                text="Allow Text Edit Actions (show in Snip popup)",
                variable=allow_var,
                font=get_ctk_font(12),
                fg_color=self.colors.surface2,
                progress_color=self.colors.accent,
                text_color=self.colors.fg,
            ).pack(anchor="w")
        else:
            tk.Checkbutton(row, text="Allow Text Edit Actions", variable=allow_var).pack(anchor="w")
        self.settings_widgets["snip_tool:allow_text_edit_actions"] = ("bool", allow_var)
        if hasattr(self, "_update_title"):
            allow_var.trace_add("write", lambda *args: self._update_title())

        # Popup settings for Snip
        row = (
            ctk.CTkFrame(scroll_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_frame, bg=self.colors.bg)
        )
        row.pack(fill="x", pady=(8, 0))
        if self.use_ctk:
            ctk.CTkLabel(
                row, text="Popup Layout:", font=get_ctk_font(12, "bold"), **get_ctk_label_colors(self.colors)
            ).pack(anchor="w")
        else:
            tk.Label(
                row, text="Popup Layout:", font=("Segoe UI", 9, "bold"), bg=self.colors.bg, fg=self.colors.fg
            ).pack(anchor="w")

        # Items per page
        row = (
            ctk.CTkFrame(scroll_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_frame, bg=self.colors.bg)
        )
        row.pack(fill="x", pady=4)
        if self.use_ctk:
            ctk.CTkLabel(row, text="Items per page:", font=get_ctk_font(12), **get_ctk_label_colors(self.colors)).pack(
                side="left"
            )
        else:
            tk.Label(row, text="Items per page:", font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg).pack(
                side="left"
            )

        snip_val = self.options_data.get("snip_tool", {}).get("_settings", {}).get("popup_items_per_page", 6)
        snip_items_var = tk.IntVar(master=scroll_frame, value=snip_val)
        if self.use_ctk:
            snip_items_entry = ctk.CTkEntry(
                row, textvariable=snip_items_var, width=60, font=get_ctk_font(12), **get_ctk_entry_colors(self.colors)
            )
            snip_items_entry.pack(side="left", padx=10)
            ctk.CTkLabel(
                row,
                text="(only if groups disabled)",
                font=get_ctk_font(11),
                **get_ctk_label_colors(self.colors, muted=True),
            ).pack(side="left")
        else:
            snip_items_entry = tk.Entry(row, textvariable=snip_items_var, width=5)
            snip_items_entry.pack(side="left", padx=10)
            tk.Label(
                row,
                text="(only if groups disabled)",
                font=("Segoe UI", 8),
                bg=self.colors.bg,
                fg=self.colors.blockquote,
            ).pack(side="left")
        self.settings_widgets["snip_tool:popup_items_per_page"] = ("int", snip_items_var)
        if hasattr(self, "_update_title"):
            snip_items_var.trace_add("write", lambda *args: self._update_title())

        # Use groups
        snip_grp_val = self.options_data.get("snip_tool", {}).get("_settings", {}).get("popup_use_groups", True)
        snip_grp_var = tk.BooleanVar(master=scroll_frame, value=snip_grp_val)

        def update_snip_items_state(*args):
            state = "disabled" if snip_grp_var.get() else "normal"
            snip_items_entry.configure(state=state)

        snip_grp_var.trace_add("write", update_snip_items_state)
        # Initial state
        update_snip_items_state()

        row = (
            ctk.CTkFrame(scroll_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_frame, bg=self.colors.bg)
        )
        row.pack(fill="x", pady=4)
        if self.use_ctk:
            ctk.CTkCheckBox(
                row,
                text="Use Groups",
                variable=snip_grp_var,
                font=get_ctk_font(12),
                text_color=self.colors.fg,
                fg_color=self.colors.accent,
            ).pack(anchor="w")
        else:
            tk.Checkbutton(row, text="Use Groups", variable=snip_grp_var).pack(anchor="w")
        self.settings_widgets["snip_tool:popup_use_groups"] = ("bool", snip_grp_var)
        if hasattr(self, "_update_title"):
            snip_grp_var.trace_add("write", lambda *args: self._update_title())

        # =====================================================================
        # Audio Tool Settings
        # =====================================================================
        if self.use_ctk:
            ctk.CTkFrame(scroll_frame, height=20, fg_color="transparent").pack()
        create_section_header(scroll_frame, "Audio Tool", self.colors, "🎤")

        add_setting_row("audio_tool", "custom_task_template", "Custom Task Template", False)

        # Popup settings for Audio
        row = (
            ctk.CTkFrame(scroll_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_frame, bg=self.colors.bg)
        )
        row.pack(fill="x", pady=(8, 0))
        if self.use_ctk:
            ctk.CTkLabel(
                row, text="Popup Layout:", font=get_ctk_font(12, "bold"), **get_ctk_label_colors(self.colors)
            ).pack(anchor="w")
        else:
            tk.Label(
                row, text="Popup Layout:", font=("Segoe UI", 9, "bold"), bg=self.colors.bg, fg=self.colors.fg
            ).pack(anchor="w")

        # Items per page
        row = (
            ctk.CTkFrame(scroll_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_frame, bg=self.colors.bg)
        )
        row.pack(fill="x", pady=4)
        if self.use_ctk:
            ctk.CTkLabel(row, text="Items per page:", font=get_ctk_font(12), **get_ctk_label_colors(self.colors)).pack(
                side="left"
            )
        else:
            tk.Label(row, text="Items per page:", font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg).pack(
                side="left"
            )

        audio_val = self.options_data.get("audio_tool", {}).get("_settings", {}).get("items_per_page", 6)
        audio_items_var = tk.IntVar(master=scroll_frame, value=audio_val)
        if self.use_ctk:
            audio_items_entry = ctk.CTkEntry(
                row, textvariable=audio_items_var, width=60, font=get_ctk_font(12), **get_ctk_entry_colors(self.colors)
            )
            audio_items_entry.pack(side="left", padx=10)
            ctk.CTkLabel(
                row,
                text="(only if groups disabled)",
                font=get_ctk_font(11),
                **get_ctk_label_colors(self.colors, muted=True),
            ).pack(side="left")
        else:
            audio_items_entry = tk.Entry(row, textvariable=audio_items_var, width=5)
            audio_items_entry.pack(side="left", padx=10)
            tk.Label(
                row,
                text="(only if groups disabled)",
                font=("Segoe UI", 8),
                bg=self.colors.bg,
                fg=self.colors.blockquote,
            ).pack(side="left")
        self.settings_widgets["audio_tool:items_per_page"] = ("int", audio_items_var)
        if hasattr(self, "_update_title"):
            audio_items_var.trace_add("write", lambda *args: self._update_title())

        # Use groups (audio_tool is a window, not popup, so uses "use_groups")
        audio_grp_val = self.options_data.get("audio_tool", {}).get("_settings", {}).get("use_groups", True)
        audio_grp_var = tk.BooleanVar(master=scroll_frame, value=audio_grp_val)

        def update_audio_items_state(*args):
            state = "disabled" if audio_grp_var.get() else "normal"
            audio_items_entry.configure(state=state)

        audio_grp_var.trace_add("write", update_audio_items_state)
        # Initial state
        update_audio_items_state()

        row = (
            ctk.CTkFrame(scroll_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(scroll_frame, bg=self.colors.bg)
        )
        row.pack(fill="x", pady=4)
        if self.use_ctk:
            ctk.CTkCheckBox(
                row,
                text="Use Groups",
                variable=audio_grp_var,
                font=get_ctk_font(12),
                text_color=self.colors.fg,
                fg_color=self.colors.accent,
            ).pack(anchor="w")
        else:
            tk.Checkbutton(row, text="Use Groups", variable=audio_grp_var).pack(anchor="w")
        self.settings_widgets["audio_tool:use_groups"] = ("bool", audio_grp_var)
        if hasattr(self, "_update_title"):
            audio_grp_var.trace_add("write", lambda *args: self._update_title())

        # =====================================================================
        # TTS Tool Settings
        # =====================================================================
        if self.use_ctk:
            ctk.CTkFrame(scroll_frame, height=20, fg_color="transparent").pack()
        create_section_header(scroll_frame, "TTS Tool", self.colors, "🔊")

        add_setting_row("tts_tool", "director_system_prompt", "Director System Prompt", True)
        add_setting_row("tts_tool", "director_task_template", "Director Task Template", True)

    def _get_current_setting(self, section, key, default=None):
        """Get setting value from widgets (live) or data (stored)."""
        # Data value as fallback
        if section == "global":
            val = self.options_data.get("_global_settings", {}).get(key, default)
        else:
            val = self.options_data.get(section, {}).get("_settings", {}).get(key, default)

        # Check widget if exists
        widget_key = f"{section}:{key}"
        if hasattr(self, "settings_widgets") and widget_key in self.settings_widgets:
            w_type, w_obj = self.settings_widgets[widget_key]
            try:
                if w_type == "entry":  # w_obj is StringVar
                    val = w_obj.get()
                elif w_type == "text":  # w_obj is widget
                    if self.use_ctk:
                        val = w_obj.get("0.0", "end").strip()
                    else:
                        val = w_obj.get("1.0", "end").strip()
                elif w_type == "int":  # w_obj is IntVar
                    val = w_obj.get()
                elif w_type == "bool":  # w_obj is BooleanVar
                    val = w_obj.get()
            except Exception:
                pass

        return val
