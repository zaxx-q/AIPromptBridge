#!/usr/bin/env python3
"""
Endpoints tab mixin for Settings Window.

Sections:
    🔧 Flask Endpoints — enable/disable toggle
    🔗 Endpoint Prompts — list + editor for prompts.json endpoints
"""

import tkinter as tk

from ...platform import HAVE_CTK, ctk
from ...themes import (
    get_ctk_font, get_ctk_label_colors,
    get_ctk_button_colors, get_ctk_textbox_colors,
)
from ...custom_widgets import ScrollableButtonList, create_section_header


class EndpointsTabMixin:
    """Mixin providing the Endpoints tab for SettingsWindow."""

    def _create_endpoints_tab(self, frame):
        """Create the Endpoints settings tab with prompts.json support."""
        # Load endpoint prompts from prompts.json
        from ...prompts import PromptsConfig
        self._prompts_config = PromptsConfig.get_instance()
        self._endpoint_prompts = dict(self._prompts_config.get_endpoint_prompts())

        if self.use_ctk:
            scroll_frame = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        else:
            scroll_frame = tk.Frame(frame, bg=self.colors.bg)
        scroll_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # Flask Endpoints toggle
        create_section_header(scroll_frame, "🔧 Flask Endpoints", self.colors)

        self._add_toggle_field(scroll_frame, "flask_endpoints_enabled",
                              "Enable Flask API Endpoints",
                              self.config_data.config.get("flask_endpoints_enabled", True),
                              hint="⚠️ Restart required. Enable/disable all Flask API endpoints.")

        # Main container for endpoint editor
        container = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        container.pack(fill="both", expand=True, pady=(15, 0))

        # Left: endpoint list (widened from 240 to 280)
        left_panel = ctk.CTkFrame(container, fg_color="transparent", width=280) if self.use_ctk else tk.Frame(container, bg=self.colors.bg, width=280)
        left_panel.pack(side="left", fill="y", padx=(0, 15))
        left_panel.pack_propagate(False)

        create_section_header(left_panel, "🔗 Endpoint Prompts", self.colors)

        if self.use_ctk:
            ctk.CTkLabel(
                left_panel,
                text="Edit prompts from prompts.json",
                font=get_ctk_font(11),
                **get_ctk_label_colors(self.colors, muted=True)
            ).pack(anchor="w", pady=(0, 8))
        else:
            tk.Label(left_panel, text="Edit prompts from prompts.json",
                    font=("Segoe UI", 9), bg=self.colors.bg,
                    fg=self.colors.blockquote).pack(anchor="w", pady=(0, 8))

        # Endpoints List
        if self.use_ctk:
            self.endpoint_listbox = ScrollableButtonList(
                left_panel, self.colors, command=self._on_endpoint_select,
                corner_radius=8, fg_color=self.colors.input_bg
            )
        else:
            self.endpoint_listbox = ScrollableButtonList(left_panel, self.colors, command=self._on_endpoint_select, bg=self.colors.input_bg)
        self.endpoint_listbox.pack(fill="both", expand=True)

        # Populate endpoints from prompts.json
        for name in sorted(self._endpoint_prompts.keys()):
            self.endpoint_listbox.add_item(name, name, "🔗")

        # Right: prompt editor
        right_panel = ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=self.colors.bg)
        right_panel.pack(side="left", fill="both", expand=True)

        if self.use_ctk:
            ctk.CTkLabel(right_panel, text="Prompt", font=get_ctk_font(14, "bold"),
                        text_color=self.colors.accent).pack(anchor="w", pady=(0, 12))

            self.endpoint_text = ctk.CTkTextbox(
                right_panel, font=get_ctk_font(12), height=300,
                **get_ctk_textbox_colors(self.colors)
            )
        else:
            tk.Label(right_panel, text="Prompt", font=("Segoe UI", 11, "bold"),
                    bg=self.colors.bg, fg=self.colors.accent).pack(anchor="w", pady=(0, 10))

            self.endpoint_text = tk.Text(
                right_panel, font=("Segoe UI", 10), height=15,
                bg=self.colors.input_bg, fg=self.colors.fg, wrap="word"
            )
        self.endpoint_text.pack(fill="both", expand=True, pady=(0, 10))

        # Button row
        btn_frame = ctk.CTkFrame(right_panel, fg_color="transparent") if self.use_ctk else tk.Frame(right_panel, bg=self.colors.bg)
        btn_frame.pack(fill="x")

        if self.use_ctk:
            ctk.CTkButton(
                btn_frame, text="Save Prompt", font=get_ctk_font(13),
                width=140, height=38, **get_ctk_button_colors(self.colors, "success"),
                command=self._save_endpoint
            ).pack(side="left", padx=4)

            self.endpoint_status = ctk.CTkLabel(btn_frame, text="", font=get_ctk_font(12),
                                                text_color=self.colors.accent_green)
        else:
            tk.Button(btn_frame, text="Save Prompt", font=("Segoe UI", 10),
                     bg=self.colors.accent_green, fg="#ffffff",
                     command=self._save_endpoint).pack(side="left", padx=2)
            self.endpoint_status = tk.Label(btn_frame, text="", font=("Segoe UI", 9),
                                           bg=self.colors.bg, fg=self.colors.accent_green)
        self.endpoint_status.pack(side="left", padx=15)

    def _on_endpoint_select(self, name):
        """Handle endpoint selection."""
        if name:
            prompt = self._endpoint_prompts.get(name, "")
            if self.use_ctk:
                self.endpoint_text.delete("0.0", "end")
                self.endpoint_text.insert("0.0", prompt)
            else:
                self.endpoint_text.delete("1.0", "end")
                self.endpoint_text.insert("1.0", prompt)

    def _save_endpoint(self):
        """Save the currently edited endpoint to prompts.json."""
        name = self.endpoint_listbox.get_selected()
        if name:
            if self.use_ctk:
                prompt = self.endpoint_text.get("0.0", "end").strip()
            else:
                prompt = self.endpoint_text.get("1.0", "end").strip()

            self._endpoint_prompts[name] = prompt

            if self._save_endpoint_prompts():
                if self.use_ctk:
                    self.endpoint_status.configure(text=f"✅ Saved '{name}'", text_color=self.colors.accent_green)
                else:
                    self.endpoint_status.configure(text=f"✅ Saved '{name}'", fg=self.colors.accent_green)
            else:
                if self.use_ctk:
                    self.endpoint_status.configure(text="❌ Failed to save", text_color=self.colors.accent_red)
                else:
                    self.endpoint_status.configure(text="❌ Failed to save", fg=self.colors.accent_red)

    def _save_endpoint_prompts(self) -> bool:
        """Save endpoint prompts to prompts.json (only endpoints section)."""
        import json
        import shutil
        from pathlib import Path

        prompts_file = Path("prompts.json")

        try:
            if prompts_file.exists():
                with open(prompts_file, 'r', encoding='utf-8') as f:
                    prompts_data = json.load(f)
            else:
                prompts_data = {}

            # Preserve _settings if it exists
            existing_settings = {}
            if "endpoints" in prompts_data and "_settings" in prompts_data["endpoints"]:
                existing_settings = prompts_data["endpoints"]["_settings"]

            prompts_data["endpoints"] = {
                "_settings": existing_settings,
                **self._endpoint_prompts
            }

            # Create backup
            if prompts_file.exists():
                shutil.copy2(prompts_file, prompts_file.with_suffix('.json.bak'))

            with open(prompts_file, 'w', encoding='utf-8') as f:
                json.dump(prompts_data, f, indent=2, ensure_ascii=False)

            # Reload PromptsConfig
            self._prompts_config.reload()

            # Update web_server ENDPOINTS if available
            try:
                from .... import web_server
                for endpoint_name, prompt in self._endpoint_prompts.items():
                    web_server.ENDPOINTS[endpoint_name] = prompt
                print(f"[Settings] Reloaded {len(self._endpoint_prompts)} endpoint prompt(s)")
            except (ImportError, AttributeError):
                pass

            return True
        except Exception as e:
            print(f"[Settings] Error saving endpoint prompts: {e}")
            return False
