#!/usr/bin/env python3
"""
API Keys tab mixin for Settings Window.

Provides a nested tabview (Google / OpenRouter / Custom) with key list,
add/remove/reorder buttons, and masked key display.
"""

import tkinter as tk

from ...platform import HAVE_CTK, ctk
from ...themes import get_ctk_font, get_ctk_label_colors, get_ctk_entry_colors
from ...custom_widgets import ScrollableButtonList, create_emoji_button


class KeysTabMixin:
    """Mixin providing the API Keys tab for SettingsWindow."""

    def _create_keys_tab(self, frame):
        """Create the API Keys settings tab."""
        container = ctk.CTkFrame(frame, fg_color="transparent") if self.use_ctk else tk.Frame(frame, bg=self.colors.bg)
        container.pack(fill="both", expand=True, padx=15, pady=15)

        # Create inner tabview for provider keys
        if self.use_ctk:
            keys_tabview = ctk.CTkTabview(
                container,
                fg_color=self.colors.bg,
                segmented_button_fg_color=self.colors.surface0,
                segmented_button_selected_color=self.colors.accent,
                segmented_button_unselected_color=self.colors.surface0,
                text_color=self.colors.fg
            )
            keys_tabview.pack(fill="both", expand=True)

            for provider in ["google", "openrouter", "custom"]:
                keys_tabview.add(provider.capitalize())
                self._create_keys_section(keys_tabview.tab(provider.capitalize()), provider)
        else:
            from tkinter import ttk
            keys_tabview = ttk.Notebook(container)
            keys_tabview.pack(fill="both", expand=True)

            for provider in ["google", "openrouter", "custom"]:
                frame_tab = tk.Frame(keys_tabview, bg=self.colors.bg)
                keys_tabview.add(frame_tab, text=provider.capitalize())
                self._create_keys_section(frame_tab, provider)

    def _create_keys_section(self, parent, provider: str):
        """Create a key management section for a provider."""
        container = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Instructions
        if self.use_ctk:
            ctk.CTkLabel(
                container,
                text=f"Manage {provider} API keys (keys are masked for security).",
                font=get_ctk_font(12),
                **get_ctk_label_colors(self.colors, muted=True)
            ).pack(anchor="w", pady=(0, 12))
        else:
            tk.Label(container, text=f"Manage {provider} API keys (keys are masked for security)",
                    font=("Segoe UI", 9), bg=self.colors.bg, fg=self.colors.blockquote).pack(anchor="w", pady=(0, 10))

        # Key list
        if self.use_ctk:
            listbox = ScrollableButtonList(
                container, self.colors, command=None,
                corner_radius=8, fg_color=self.colors.input_bg
            )
        else:
            listbox = ScrollableButtonList(container, self.colors, command=None, bg=self.colors.input_bg)
        listbox.pack(fill="both", expand=True)

        def refresh_keys_list():
            listbox.clear()
            for i, key_data in enumerate(self.widgets[f"keys_{provider}_data"]):
                masked = self._mask_key(key_data)
                listbox.add_item(str(i), masked, "🔑")

        # Initialize with config data
        self.widgets[f"keys_{provider}_data"] = list(self.config_data.keys.get(provider, []))
        refresh_keys_list()

        self.widgets[f"keys_{provider}_listbox"] = listbox
        self.widgets[f"keys_{provider}_refresh"] = refresh_keys_list

        # Input frame for key + name
        input_frame = ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=self.colors.bg)
        input_frame.pack(fill="x", pady=(10, 0))

        if self.use_ctk:
            ctk.CTkLabel(
                input_frame, text="API Key:",
                font=get_ctk_font(12),
                **get_ctk_label_colors(self.colors)
            ).pack(side="left", padx=(0, 4))

            entry_var = tk.StringVar(master=self.root)
            key_entry = ctk.CTkEntry(
                input_frame, textvariable=entry_var,
                font=get_ctk_font(12), width=280, height=36,
                placeholder_text="Paste key here...",
                **get_ctk_entry_colors(self.colors)
            )
            key_entry.pack(side="left", padx=(0, 12))

            ctk.CTkLabel(
                input_frame, text="Name:",
                font=get_ctk_font(12),
                **get_ctk_label_colors(self.colors)
            ).pack(side="left", padx=(0, 4))

            name_var = tk.StringVar(master=self.root)
            name_entry = ctk.CTkEntry(
                input_frame, textvariable=name_var,
                font=get_ctk_font(12), width=140, height=36,
                placeholder_text="Optional...",
                **get_ctk_entry_colors(self.colors)
            )
            name_entry.pack(side="left", padx=(0, 8))
        else:
            entry_var = tk.StringVar(master=self.root)
            key_entry = tk.Entry(input_frame, textvariable=entry_var,
                                font=("Consolas", 10), width=35,
                                bg=self.colors.input_bg, fg=self.colors.fg)
            key_entry.insert(0, "API key...")
            key_entry.configure(fg=self.colors.blockquote)
            key_entry.pack(side="left", padx=(0, 6))

            name_var = tk.StringVar(master=self.root)
            name_entry = tk.Entry(input_frame, textvariable=name_var,
                                 font=("Segoe UI", 10), width=15,
                                 bg=self.colors.input_bg, fg=self.colors.fg)
            name_entry.insert(0, "Name...")
            name_entry.configure(fg=self.colors.blockquote)
            name_entry.pack(side="left", padx=(0, 6))

            def on_key_focus_in(e):
                if key_entry.get() == "API key...":
                    key_entry.delete(0, "end")
                    key_entry.configure(fg=self.colors.fg)

            def on_key_focus_out(e):
                if not key_entry.get():
                    key_entry.insert(0, "API key...")
                    key_entry.configure(fg=self.colors.blockquote)

            def on_name_focus_in(e):
                if name_entry.get() == "Name...":
                    name_entry.delete(0, "end")
                    name_entry.configure(fg=self.colors.fg)

            def on_name_focus_out(e):
                if not name_entry.get():
                    name_entry.insert(0, "Name...")
                    name_entry.configure(fg=self.colors.blockquote)

            key_entry.bind('<FocusIn>', on_key_focus_in)
            key_entry.bind('<FocusOut>', on_key_focus_out)
            name_entry.bind('<FocusIn>', on_name_focus_in)
            name_entry.bind('<FocusOut>', on_name_focus_out)

        # Button frame
        btn_frame = ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=self.colors.bg)
        btn_frame.pack(fill="x", pady=(8, 0))

        def add_key():
            key = entry_var.get().strip()
            name = name_var.get().strip()
            if key == "API key...":
                key = ""
            if name == "Name...":
                name = ""
            if key:
                self.widgets[f"keys_{provider}_data"].append({
                    "key": key,
                    "name": name
                })
                refresh_keys_list()
                entry_var.set("")
                name_var.set("")
                if self.use_ctk:
                    key_entry.configure(placeholder_text="API key...")
                    name_entry.configure(placeholder_text="Name (optional)...")
                else:
                    key_entry.delete(0, "end")
                    key_entry.insert(0, "API key...")
                    key_entry.configure(fg=self.colors.blockquote)
                    name_entry.delete(0, "end")
                    name_entry.insert(0, "Name...")
                    name_entry.configure(fg=self.colors.blockquote)

        def remove_key():
            selected_id = listbox.get_selected()
            if selected_id:
                idx = int(selected_id)
                del self.widgets[f"keys_{provider}_data"][idx]
                refresh_keys_list()

        def move_key_up():
            selected_id = listbox.get_selected()
            if selected_id:
                idx = int(selected_id)
                keys = self.widgets[f"keys_{provider}_data"]
                if idx > 0:
                    keys[idx], keys[idx-1] = keys[idx-1], keys[idx]
                    refresh_keys_list()
                    listbox.select(str(idx-1))

        def move_key_down():
            selected_id = listbox.get_selected()
            if selected_id:
                idx = int(selected_id)
                keys = self.widgets[f"keys_{provider}_data"]
                if idx < len(keys) - 1:
                    keys[idx], keys[idx+1] = keys[idx+1], keys[idx]
                    refresh_keys_list()
                    listbox.select(str(idx+1))

        create_emoji_button(btn_frame, "Add", "", self.colors, "success", 70, 36, add_key).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "Remove", "", self.colors, "danger", 80, 36, remove_key).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "⬆", "", self.colors, "secondary", 40, 36, move_key_up).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "⬇", "", self.colors, "secondary", 40, 36, move_key_down).pack(side="left", padx=3)

    def _mask_key(self, key_data: dict) -> str:
        """Mask an API key for display, including name if present."""
        key = key_data.get("key", "")
        name = key_data.get("name", "")

        if len(key) <= 8:
            masked = "*" * len(key)
        else:
            masked = key[:4] + "..." + key[-4:]

        if name:
            return f"{masked} ({name})"
        return masked
