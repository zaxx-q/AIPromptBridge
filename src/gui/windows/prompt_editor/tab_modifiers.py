#!/usr/bin/env python3
"""
Modifiers Tab Mixin for the Prompt Editor.

Provides the Modifiers tab UI and all modifier CRUD operations.
"""

import tkinter as tk
from tkinter import messagebox

from ...custom_widgets import ScrollableButtonList, ask_themed_string, create_emoji_button, create_section_header
from ...platform import HAVE_CTK, ctk
from ...themes import (
    get_ctk_button_colors,
    get_ctk_entry_colors,
    get_ctk_font,
    get_ctk_label_colors,
    get_ctk_textbox_colors,
)

# Import emoji renderer for CTkImage support (Windows color emoji fix)
try:
    from ...emoji_renderer import HAVE_PIL, get_emoji_renderer
    HAVE_EMOJI = HAVE_PIL and HAVE_CTK
except ImportError:
    HAVE_EMOJI = False
    get_emoji_renderer = None


class ModifiersTabMixin:
    """Mixin providing the Modifiers tab for PromptEditorWindow."""

    def _create_modifiers_tab(self, frame):
        """Create the Modifiers editing tab."""
        container = ctk.CTkFrame(frame, fg_color="transparent") if self.use_ctk else tk.Frame(frame, bg=self.colors.bg)
        container.pack(fill="both", expand=True, padx=15, pady=15)

        # Left panel: modifier list
        left_panel = ctk.CTkFrame(container, fg_color="transparent", width=260) if self.use_ctk else tk.Frame(container, bg=self.colors.bg, width=260)
        left_panel.pack(side="left", fill="y", padx=(0, 15))
        left_panel.pack_propagate(False)

        create_section_header(left_panel, "Modifiers", self.colors, "🎛️")

        # Modifier List - using ScrollableButtonList
        if self.use_ctk:
            self.modifier_listbox = ScrollableButtonList(
                left_panel, self.colors, command=self._on_modifier_select,
                corner_radius=8, fg_color=self.colors.input_bg
            )
        else:
            self.modifier_listbox = ScrollableButtonList(
                left_panel, self.colors, command=self._on_modifier_select,
                bg=self.colors.input_bg
            )
        self.modifier_listbox.pack(fill="both", expand=True)

        # Populate modifiers
        settings = self.options_data.get("_global_settings", {})
        modifiers = settings.get("modifiers", [])
        for i, mod in enumerate(modifiers):
            icon = mod.get('icon', '')
            label = mod.get('label', mod.get('key', ''))
            self.modifier_listbox.add_item(str(i), label, icon)

        # Buttons
        btn_frame = ctk.CTkFrame(left_panel, fg_color="transparent") if self.use_ctk else tk.Frame(left_panel, bg=self.colors.bg)
        btn_frame.pack(fill="x", pady=(12, 0))

        create_emoji_button(btn_frame, "Add", "➕", self.colors, "success", 70, 34, self._add_modifier).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "", "🗑️", self.colors, "danger", 40, 34, self._delete_modifier).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "⬆", "", self.colors, "secondary", 40, 34, self._move_modifier_up).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "⬇", "", self.colors, "secondary", 40, 34, self._move_modifier_down).pack(side="left", padx=3)

        # Right panel: modifier editor
        right_panel = ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=self.colors.bg)
        right_panel.pack(side="left", fill="both", expand=True)

        create_section_header(right_panel, "Edit Modifier", self.colors, "✏️")

        self.modifier_widgets = {}

        # Key, Icon, Label, Tooltip fields
        for field_key, field_label, width in [
            ("key_var", "Key:", 180),
            ("icon_var", "Icon:", 80),
            ("label_var", "Label:", 220),
            ("tooltip_var", "Tooltip:", 340)
        ]:
            row = ctk.CTkFrame(right_panel, fg_color="transparent") if self.use_ctk else tk.Frame(right_panel, bg=self.colors.bg)
            row.pack(fill="x", pady=6)

            if self.use_ctk:
                ctk.CTkLabel(row, text=field_label, font=get_ctk_font(13), width=100, anchor="w",
                            **get_ctk_label_colors(self.colors)).pack(side="left")
                self.modifier_widgets[field_key] = tk.StringVar(master=self.root)
                ctk.CTkEntry(row, textvariable=self.modifier_widgets[field_key],
                            font=get_ctk_font(12), width=width, height=34,
                            **get_ctk_entry_colors(self.colors)).pack(side="left", padx=(12, 0))
            else:
                tk.Label(row, text=field_label, font=("Segoe UI", 10), width=10, anchor="w",
                        bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
                self.modifier_widgets[field_key] = tk.StringVar(master=self.root)
                tk.Entry(row, textvariable=self.modifier_widgets[field_key],
                        font=("Segoe UI", 10), width=width//8,
                        bg=self.colors.input_bg, fg=self.colors.fg).pack(side="left", padx=(10, 0))

        # Injection (multiline)
        row = ctk.CTkFrame(right_panel, fg_color="transparent") if self.use_ctk else tk.Frame(right_panel, bg=self.colors.bg)
        row.pack(fill="x", pady=8)

        if self.use_ctk:
            ctk.CTkLabel(row, text="Injection:", font=get_ctk_font(13),
                        **get_ctk_label_colors(self.colors)).pack(anchor="w")
            self.modifier_widgets["injection"] = ctk.CTkTextbox(
                row, height=100, font=get_ctk_font(12),
                **get_ctk_textbox_colors(self.colors)
            )
        else:
            tk.Label(row, text="Injection:", font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w")
            self.modifier_widgets["injection"] = tk.Text(
                row, height=4, font=("Consolas", 9),
                bg=self.colors.input_bg, fg=self.colors.fg, wrap="word"
            )
        self.modifier_widgets["injection"].pack(fill="x", pady=(2, 0))

        # Forces chat window toggle
        row = ctk.CTkFrame(right_panel, fg_color="transparent") if self.use_ctk else tk.Frame(right_panel, bg=self.colors.bg)
        row.pack(fill="x", pady=8)

        self.modifier_widgets["forces_chat_var"] = tk.BooleanVar()
        if self.use_ctk:
            ctk.CTkCheckBox(row, text="Forces chat window",
                           variable=self.modifier_widgets["forces_chat_var"],
                           font=get_ctk_font(13), text_color=self.colors.fg,
                           fg_color=self.colors.accent).pack(anchor="w")
        else:
            tk.Checkbutton(row, text="Forces chat window",
                          variable=self.modifier_widgets["forces_chat_var"],
                          font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg,
                          selectcolor=self.colors.input_bg).pack(anchor="w")

        # Default for Tools section
        row = ctk.CTkFrame(right_panel, fg_color="transparent") if self.use_ctk else tk.Frame(right_panel, bg=self.colors.bg)
        row.pack(fill="x", pady=(8, 0))

        if self.use_ctk:
            ctk.CTkLabel(row, text="Default for Tools:", font=get_ctk_font(13),
                        **get_ctk_label_colors(self.colors)).pack(anchor="w")
        else:
            tk.Label(row, text="Default for Tools:", font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w")

        tools_row = ctk.CTkFrame(right_panel, fg_color="transparent") if self.use_ctk else tk.Frame(right_panel, bg=self.colors.bg)
        tools_row.pack(fill="x", pady=4)

        self.modifier_widgets["default_text_edit_var"] = tk.BooleanVar()
        self.modifier_widgets["default_snip_var"] = tk.BooleanVar()
        self.modifier_widgets["default_audio_var"] = tk.BooleanVar()

        tool_checkboxes = [
            ("default_text_edit_var", "✏️", "TextEdit"),
            ("default_snip_var", "✂️", "SnipTool"),
            ("default_audio_var", "🎤", "AudioTool"),
        ]

        for var_key, emoji_char, label_text in tool_checkboxes:
            if self.use_ctk:
                pair = ctk.CTkFrame(tools_row, fg_color="transparent")
                pair.pack(side="left", padx=(0, 12))

                ctk.CTkCheckBox(pair, text="",
                               variable=self.modifier_widgets[var_key],
                               font=get_ctk_font(12), text_color=self.colors.fg,
                               fg_color=self.colors.accent, width=20, height=20).pack(side="left")

                # Render emoji as color image via emoji renderer
                emoji_img = None
                if HAVE_EMOJI:
                    renderer = get_emoji_renderer()
                    emoji_img = renderer.get_ctk_image(emoji_char, size=16)

                if emoji_img:
                    ctk.CTkLabel(pair, text="", image=emoji_img, width=16).pack(side="left", padx=(2, 0))

                ctk.CTkLabel(pair, text=label_text, font=get_ctk_font(12),
                            **get_ctk_label_colors(self.colors)).pack(side="left", padx=(2, 0))
            else:
                tk.Checkbutton(tools_row, text=f"{emoji_char} {label_text}",
                              variable=self.modifier_widgets[var_key],
                              font=("Segoe UI", 9), bg=self.colors.bg, fg=self.colors.fg,
                              selectcolor=self.colors.input_bg).pack(side="left", padx=(0, 8))

        # Save button
        create_emoji_button(
            right_panel, "Save Modifier", "💾", self.colors, "success", 160, 40, self._save_current_modifier
        ).pack(anchor="w", pady=(18, 0))

    def _on_modifier_select(self, mod_id_str):
        """Handle modifier selection."""
        try:
            index = int(mod_id_str)
        except ValueError:
            return

        settings = self.options_data.get("_global_settings", {})
        modifiers = settings.get("modifiers", [])

        if 0 <= index < len(modifiers):
            mod = modifiers[index]
            self.modifier_widgets["key_var"].set(mod.get("key", ""))
            self.modifier_widgets["icon_var"].set(mod.get("icon", ""))
            self.modifier_widgets["label_var"].set(mod.get("label", ""))
            self.modifier_widgets["tooltip_var"].set(mod.get("tooltip", ""))

            if self.use_ctk:
                self.modifier_widgets["injection"].delete("0.0", "end")
                self.modifier_widgets["injection"].insert("0.0", mod.get("injection", ""))
            else:
                self.modifier_widgets["injection"].delete("1.0", "end")
                self.modifier_widgets["injection"].insert("1.0", mod.get("injection", ""))

            self.modifier_widgets["forces_chat_var"].set(mod.get("forces_chat_window", False))

            # Load default_tools checkboxes
            default_tools = mod.get("default_tools", [])
            self.modifier_widgets["default_text_edit_var"].set("text_edit_tool" in default_tools)
            self.modifier_widgets["default_snip_var"].set("snip_tool" in default_tools)
            self.modifier_widgets["default_audio_var"].set("audio_tool" in default_tools)

    def _add_modifier(self):
        """Add a new modifier."""
        key = ask_themed_string(self.root, "New Modifier", "Enter modifier key:", self.colors)
        if key:
            settings = self.options_data.setdefault("_global_settings", {})
            modifiers = settings.setdefault("modifiers", [])
            modifiers.append({
                "key": key,
                "icon": "🔧",
                "label": key.title(),
                "tooltip": "",
                "injection": "",
                "forces_chat_window": False
            })
            idx = len(modifiers) - 1
            self.modifier_listbox.add_item(str(idx), key.title(), "🔧")

    def _delete_modifier(self):
        """Delete selected modifier."""
        selected_id = self.modifier_listbox.get_selected()
        if not selected_id:
            return

        try:
            index = int(selected_id)
        except ValueError:
            return

        settings = self.options_data.get("_global_settings", {})
        modifiers = settings.get("modifiers", [])

        if 0 <= index < len(modifiers):
            if messagebox.askyesno("Delete Modifier", "Delete this modifier?", parent=self.root):
                deleted_mod = modifiers[index]
                mod_key = deleted_mod.get("key")

                # Check if it was a default modifier
                from ...prompts import DEFAULT_GLOBAL_SETTINGS
                is_default = any(d.get("key") == mod_key for d in DEFAULT_GLOBAL_SETTINGS.get("modifiers", []))

                if is_default and mod_key:
                    deleted_modifiers = settings.setdefault("deleted_modifiers", [])
                    if mod_key not in deleted_modifiers:
                        deleted_modifiers.append(mod_key)

                del modifiers[index]
                # Rebuild list because indices shifted
                self.modifier_listbox.clear()
                for i, mod in enumerate(modifiers):
                    self.modifier_listbox.add_item(str(i), mod.get('label', mod.get('key', '')), mod.get('icon', ''))

    def _move_modifier_up(self):
        """Move selected modifier up."""
        selected_id = self.modifier_listbox.get_selected()
        if not selected_id:
            return

        try:
            index = int(selected_id)
        except ValueError:
            return

        settings = self.options_data.get("_global_settings", {})
        modifiers = settings.get("modifiers", [])

        if 0 < index < len(modifiers):
            modifiers[index], modifiers[index-1] = modifiers[index-1], modifiers[index]

            # Refresh list
            self.modifier_listbox.clear()
            for i, mod in enumerate(modifiers):
                self.modifier_listbox.add_item(str(i), mod.get('label', mod.get('key', '')), mod.get('icon', ''))

            # Restore selection (now at index-1)
            self.modifier_listbox.select(str(index-1))

    def _move_modifier_down(self):
        """Move selected modifier down."""
        selected_id = self.modifier_listbox.get_selected()
        if not selected_id:
            return

        try:
            index = int(selected_id)
        except ValueError:
            return

        settings = self.options_data.get("_global_settings", {})
        modifiers = settings.get("modifiers", [])

        if 0 <= index < len(modifiers) - 1:
            modifiers[index], modifiers[index+1] = modifiers[index+1], modifiers[index]

            # Refresh list
            self.modifier_listbox.clear()
            for i, mod in enumerate(modifiers):
                self.modifier_listbox.add_item(str(i), mod.get('label', mod.get('key', '')), mod.get('icon', ''))

            # Restore selection (now at index+1)
            self.modifier_listbox.select(str(index+1))

    def _save_current_modifier(self):
        """Save the currently edited modifier."""
        selected_id = self.modifier_listbox.get_selected()
        if not selected_id:
            return

        try:
            index = int(selected_id)
        except ValueError:
            return

        settings = self.options_data.get("_global_settings", {})
        modifiers = settings.get("modifiers", [])

        if 0 <= index < len(modifiers):
            if self.use_ctk:
                injection = self.modifier_widgets["injection"].get("0.0", "end").strip()
            else:
                injection = self.modifier_widgets["injection"].get("1.0", "end").strip()

            # Build default_tools list from checkboxes
            default_tools = []
            if self.modifier_widgets["default_text_edit_var"].get():
                default_tools.append("text_edit_tool")
            if self.modifier_widgets["default_snip_var"].get():
                default_tools.append("snip_tool")
            if self.modifier_widgets["default_audio_var"].get():
                default_tools.append("audio_tool")

            modifiers[index] = {
                "key": self.modifier_widgets["key_var"].get(),
                "icon": self.modifier_widgets["icon_var"].get(),
                "label": self.modifier_widgets["label_var"].get(),
                "tooltip": self.modifier_widgets["tooltip_var"].get(),
                "injection": injection,
                "forces_chat_window": self.modifier_widgets["forces_chat_var"].get(),
                "default_tools": default_tools
            }

            # Rebuild list to update display
            self.modifier_listbox.clear()
            for i, mod in enumerate(modifiers):
                self.modifier_listbox.add_item(str(i), mod.get('label', mod.get('key', '')), mod.get('icon', ''))
            self.modifier_listbox.select(str(index))
