#!/usr/bin/env python3
"""
Provider tab mixin for Settings Window.

Sections:
🔌 Connection Profile — active profile selector + manage button
🔑 Key Pool Assignments — per-provider pool assignment
🔄 Request Settings — retries, delay, timeout
"""

import tkinter as tk

from ...platform import HAVE_CTK, ctk
from ...themes import get_ctk_font, get_ctk_label_colors
from ...custom_widgets import create_section_header, create_emoji_button


class ProviderTabMixin:
    """Mixin providing the Provider tab for SettingsWindow."""

    def _create_provider_tab(self, frame):
        """Create the Provider settings tab."""
        content = self._create_tab_scroll_frame(frame)

        # --- Connection Profile ---
        create_section_header(content, "🔌 Connection Profile", self.colors)
        self._create_profile_selector(content)

        # --- Key Pool Assignments ---
        create_section_header(content, "🔑 Key Pool Assignments", self.colors, top_padding=20)

        if self.use_ctk:
            ctk.CTkLabel(content,
                        text="Assign which key pool each provider draws API keys from.",
                        font=get_ctk_font(11), justify="left",
                        **get_ctk_label_colors(self.colors, muted=True)
                        ).pack(anchor="w", pady=(0, 8))
        else:
            tk.Label(content,
                    text="Assign which key pool each provider draws API keys from.",
                    font=("Segoe UI", 9), justify="left",
                    bg=self.colors.bg, fg=self.colors.blockquote).pack(anchor="w", pady=(0, 8))

        self._create_pool_assignment_dropdown(content, "custom")
        self._create_pool_assignment_dropdown(content, "openrouter")
        self._create_pool_assignment_dropdown(content, "google")

        # --- Request Settings ---
        create_section_header(content, "🔄 Request Settings", self.colors, top_padding=20)
    
        self._add_spinbox_field(content, "max_retries", "Max retries:",
            self.config_data.config.get("max_retries", 3),
            0, 10, hint="Retries before giving up on API calls")
    
        self._add_spinbox_field(content, "retry_delay", "Retry delay (s):",
            self.config_data.config.get("retry_delay", 5),
            1, 60, hint="Seconds between retries")
    
        self._add_spinbox_field(content, "request_timeout", "Request timeout (s):",
            self.config_data.config.get("request_timeout", 120),
            10, 600, hint="Timeout for API requests (overridden by active profile)")

    # -------------------------------------------------------------------------
    # Connection Profile selector
    # -------------------------------------------------------------------------

    def _create_profile_selector(self, parent):
        """Active profile dropdown + Manage Profiles button."""
        from src.connection_profiles import ProfileStore
        from .widgets import LABEL_WIDTH, DROPDOWN_WIDTH_MD

        store = ProfileStore.get_instance()
        profile_names = store.get_profile_names()
        active_name = store.get_active_profile_name()

        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=4)

        if self.use_ctk:
            ctk.CTkLabel(
                row, text="Active Profile:",
                font=get_ctk_font(13), width=LABEL_WIDTH, anchor="w",
                **get_ctk_label_colors(self.colors)
            ).pack(side="left")

            self._profile_var = tk.StringVar(master=self.root, value=active_name)
            dd = ctk.CTkComboBox(
                row, variable=self._profile_var, values=profile_names,
                width=DROPDOWN_WIDTH_MD, height=34, state="readonly",
                font=get_ctk_font(13),
                fg_color=self.colors.input_bg,
                border_color=self.colors.surface1,
                button_color=self.colors.surface1,
                button_hover_color=self.colors.accent,
                dropdown_fg_color=self.colors.surface0,
                text_color=self.colors.fg,
                command=self._on_profile_selected
            )
            dd.pack(side="left", padx=(8, 0))
            self._profile_dropdown = dd
        else:
            tk.Label(
                row, text="Active Profile:",
                font=("Segoe UI", 10), width=LABEL_WIDTH // 8, anchor="w",
                bg=self.colors.bg, fg=self.colors.fg
            ).pack(side="left")

            self._profile_var = tk.StringVar(master=self.root, value=active_name)
            from tkinter import ttk
            dd = ttk.Combobox(
                row, textvariable=self._profile_var, values=profile_names,
                width=DROPDOWN_WIDTH_MD // 10, state="readonly"
            )
            dd.pack(side="left", padx=(8, 0))
            dd.bind('<<ComboboxSelected>>', lambda e: self._on_profile_selected(self._profile_var.get()))
            self._profile_dropdown = dd

        # Status label
        if self.use_ctk:
            self._profile_status = ctk.CTkLabel(
                row, text="", font=get_ctk_font(11),
                text_color=self.colors.accent_green
            )
        else:
            self._profile_status = tk.Label(
                row, text="", font=("Segoe UI", 9),
                bg=self.colors.bg, fg=self.colors.accent_green
            )
        self._profile_status.pack(side="left", padx=(12, 0))

        # Manage Profiles button
        btn_row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        btn_row.pack(fill="x", pady=(4, 8))

        create_emoji_button(
            btn_row, "Manage Profiles", "🔌", self.colors, "primary", 170, 36,
            command=self._open_connection_manager
        ).pack(side="left")

        hint_text = "Create, edit, and test connection profiles"
        if self.use_ctk:
            ctk.CTkLabel(btn_row, text=hint_text,
                        font=get_ctk_font(11), justify="left",
                        **get_ctk_label_colors(self.colors, muted=True)
                        ).pack(side="left", padx=(12, 0))
        else:
            tk.Label(btn_row, text=hint_text,
                    font=("Segoe UI", 9),
                    bg=self.colors.bg, fg=self.colors.blockquote
                    ).pack(side="left", padx=(12, 0))

    def _on_profile_selected(self, name: str = None):
        """Handle profile selection from dropdown."""
        if not name:
            name = self._profile_var.get()
        if not name:
            return

        try:
            from ....web_server import switch_active_profile
            if switch_active_profile(name):
                status_text = f"⭐ Switched to '{name}'"
                color = self.colors.accent_green
            else:
                status_text = f"Profile '{name}' not found"
                color = self.colors.accent_red
        except Exception as e:
            status_text = f"Error: {str(e)[:30]}"
            color = self.colors.accent_red

        if self.use_ctk:
            self._profile_status.configure(text=status_text, text_color=color)
        else:
            self._profile_status.configure(text=status_text, fg=color)

    def _open_connection_manager(self):
        """Open the Connection Profile Manager window."""
        try:
            from ..connection_manager import ConnectionProfileManager
            ConnectionProfileManager(self.root, colors=self.colors,
                                     on_close=self._refresh_profile_dropdown)
        except Exception as e:
            print(f"[Settings] Error opening connection manager: {e}")

    def _refresh_profile_dropdown(self):
        """Refresh profile dropdown after connection manager closes."""
        try:
            from src.connection_profiles import ProfileStore
            store = ProfileStore.get_instance()
            names = store.get_profile_names()
            active = store.get_active_profile_name()
            self._profile_var.set(active)
            if self.use_ctk:
                self._profile_dropdown.configure(values=names)
            else:
                self._profile_dropdown.configure(values=names)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Pool assignment dropdown (per-provider)
    # -------------------------------------------------------------------------

    def _create_pool_assignment_dropdown(self, parent, provider: str):
        """Add a Key Pool dropdown to a provider section."""
        from src.key_store import KeyStore
        from .widgets import LABEL_WIDTH, DROPDOWN_WIDTH_MD
        key_store = KeyStore.get_instance()

        pool_ids = key_store.get_all_pool_ids()
        pool_display = [self._pool_label_for(key_store, pid) for pid in pool_ids]
        current_pool = key_store.get_provider_pool_id(provider)

        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=4)

        label_text = f"{provider.title()} Key Pool:"

        if self.use_ctk:
            ctk.CTkLabel(
                row, text=label_text,
                font=get_ctk_font(13), width=LABEL_WIDTH, anchor="w",
                **get_ctk_label_colors(self.colors)
            ).pack(side="left")

            var = tk.StringVar(master=self.root, value=self._pool_label_for(key_store, current_pool))
            dd = ctk.CTkComboBox(
                row, variable=var, values=pool_display,
                width=DROPDOWN_WIDTH_MD, height=34, state="readonly",
                font=get_ctk_font(13),
                fg_color=self.colors.input_bg,
                border_color=self.colors.surface1,
                button_color=self.colors.surface1,
                button_hover_color=self.colors.accent,
                dropdown_fg_color=self.colors.surface0,
                text_color=self.colors.fg
            )
            dd.pack(side="left", padx=(8, 0))
        else:
            tk.Label(
                row, text=label_text,
                font=("Segoe UI", 10), width=LABEL_WIDTH // 8, anchor="w",
                bg=self.colors.bg, fg=self.colors.fg
            ).pack(side="left")

            var = tk.StringVar(master=self.root, value=self._pool_label_for(key_store, current_pool))
            from tkinter import ttk
            dd = ttk.Combobox(
                row, textvariable=var, values=pool_display,
                width=DROPDOWN_WIDTH_MD // 10, state="readonly"
            )
            dd.pack(side="left", padx=(8, 0))

        # Store for save flow to read
        if "keys_provider_pool_vars" not in self.widgets:
            self.widgets["keys_provider_pool_vars"] = {}
        self.widgets["keys_provider_pool_vars"][provider] = (var, pool_ids)
        self.widgets[f"keys_provider_{provider}_dropdown"] = dd

    @staticmethod
    def _pool_label_for(key_store, pool_id: str) -> str:
        """Format a pool ID for display."""
        name = key_store.get_pool_display_name(pool_id)
        return f"{name} ({pool_id})" if name != pool_id else pool_id
