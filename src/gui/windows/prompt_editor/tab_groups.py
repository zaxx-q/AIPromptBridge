#!/usr/bin/env python3
"""
Groups Tab Mixin for the Prompt Editor.

Provides the Groups tab UI and all group CRUD operations.
"""

import tkinter as tk
from tkinter import messagebox

from ...custom_widgets import ScrollableButtonList, ask_themed_string, create_emoji_button, create_section_header
from ...platform import HAVE_CTK, ctk
from ...themes import get_ctk_entry_colors, get_ctk_font, get_ctk_label_colors, get_ctk_textbox_colors, get_tk_font


class GroupsTabMixin:
    """Mixin providing the Groups tab for PromptEditorWindow."""

    def _refresh_group_list(self):
        """Refresh the group list based on current tool."""
        if not self.group_listbox:
            return

        selected = self.group_listbox.get_selected()
        self.group_listbox.clear()

        # Get groups for current tool
        tool_data = self.options_data.get(self.current_tool, {})
        settings = tool_data.get("_settings", {})
        groups = settings.get("popup_groups", [])

        for i, grp in enumerate(groups):
            name = grp.get("name", "Unnamed")
            self.group_listbox.add_item(str(i), name, None)

        if selected:
            # Try to restore selection if index valid
            try:
                idx = int(selected)
                if idx < len(groups):
                    self.group_listbox.select(selected)
            except ValueError:
                pass

    def _on_group_tool_switch(self, value):
        """Handle tool switching in Groups tab."""
        if value == "Text Edit Tool":
            self.current_tool = "text_edit_tool"
        elif value == "Snip Tool":
            self.current_tool = "snip_tool"
        else:  # Audio Tool
            self.current_tool = "audio_tool"

        self._refresh_group_list()
        # Clear editor fields
        self.group_widgets["name_var"].set("")
        if self.use_ctk:
            self.group_widgets["items"].delete("0.0", "end")
        else:
            self.group_widgets["items"].delete("1.0", "end")

    def _create_groups_tab(self, frame):
        """Create the Groups editing tab."""
        container = ctk.CTkFrame(frame, fg_color="transparent") if self.use_ctk else tk.Frame(frame, bg=self.colors.bg)
        container.pack(fill="both", expand=True, padx=15, pady=15)

        # Left panel: group list
        left_panel = (
            ctk.CTkFrame(container, fg_color="transparent", width=260)
            if self.use_ctk
            else tk.Frame(container, bg=self.colors.bg, width=260)
        )
        left_panel.pack(side="left", fill="y", padx=(0, 15))
        left_panel.pack_propagate(False)

        create_section_header(left_panel, "Groups", self.colors, "📁")

        # Tool Switcher for Groups
        if self.use_ctk:
            self.group_tool_switcher = ctk.CTkSegmentedButton(
                left_panel,
                values=["Text Edit Tool", "Snip Tool", "Audio Tool"],
                command=self._on_group_tool_switch,
                font=get_ctk_font(12, "bold"),
                fg_color=self.colors.bg,
                selected_color=self.colors.accent,
                selected_hover_color=self.colors.accent,
                unselected_color=self.colors.surface0,
                unselected_hover_color=self.colors.surface1,
                text_color=self.colors.fg,
                text_color_disabled=self.colors.surface2,
            )
            # Sync with current tool if possible, defaulting to Text Edit
            if self.current_tool == "text_edit_tool":
                current_val = "Text Edit Tool"
            elif self.current_tool == "snip_tool":
                current_val = "Snip Tool"
            else:
                current_val = "Audio Tool"
            self.group_tool_switcher.set(current_val)
            self.group_tool_switcher.pack(fill="x", pady=(0, 10))

        # Group List - using ScrollableButtonList
        if self.use_ctk:
            self.group_listbox = ScrollableButtonList(
                left_panel, self.colors, command=self._on_group_select, corner_radius=8, fg_color=self.colors.input_bg
            )
        else:
            self.group_listbox = ScrollableButtonList(
                left_panel, self.colors, command=self._on_group_select, bg=self.colors.input_bg
            )
        self.group_listbox.pack(fill="both", expand=True)

        # Populate groups
        self._refresh_group_list()

        # Buttons
        btn_frame = (
            ctk.CTkFrame(left_panel, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(left_panel, bg=self.colors.bg)
        )
        btn_frame.pack(fill="x", pady=(12, 0))

        create_emoji_button(btn_frame, "Add", "➕", self.colors, "success", 70, 34, self._add_group).pack(
            side="left", padx=3
        )
        create_emoji_button(btn_frame, "", "🗑️", self.colors, "danger", 40, 34, self._delete_group).pack(
            side="left", padx=3
        )
        create_emoji_button(btn_frame, "⬆", "", self.colors, "secondary", 40, 34, self._move_group_up).pack(
            side="left", padx=3
        )
        create_emoji_button(btn_frame, "⬇", "", self.colors, "secondary", 40, 34, self._move_group_down).pack(
            side="left", padx=3
        )

        # Right panel: group editor
        right_panel = (
            ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=self.colors.bg)
        )
        right_panel.pack(side="left", fill="both", expand=True)

        create_section_header(right_panel, "Edit Group", self.colors, "✏️")

        self.group_widgets = {}

        # Name field
        row = (
            ctk.CTkFrame(right_panel, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(right_panel, bg=self.colors.bg)
        )
        row.pack(fill="x", pady=8)

        if self.use_ctk:
            ctk.CTkLabel(
                row, text="Name:", font=get_ctk_font(13), width=100, anchor="w", **get_ctk_label_colors(self.colors)
            ).pack(side="left")
            self.group_widgets["name_var"] = tk.StringVar(master=self.root)
            ctk.CTkEntry(
                row,
                textvariable=self.group_widgets["name_var"],
                font=get_ctk_font(13),
                width=240,
                height=34,
                **get_ctk_entry_colors(self.colors),
            ).pack(side="left", padx=(12, 0))
        else:
            tk.Label(
                row, text="Name:", font=get_tk_font(10), width=10, anchor="w", bg=self.colors.bg, fg=self.colors.fg
            ).pack(side="left")
            self.group_widgets["name_var"] = tk.StringVar()
            tk.Entry(
                row,
                textvariable=self.group_widgets["name_var"],
                font=get_tk_font(10),
                width=25,
                bg=self.colors.input_bg,
                fg=self.colors.fg,
            ).pack(side="left", padx=(10, 0))

        # Enabled checkbox
        row = (
            ctk.CTkFrame(right_panel, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(right_panel, bg=self.colors.bg)
        )
        row.pack(fill="x", pady=8)

        self.group_widgets["enabled_var"] = tk.BooleanVar(value=True)
        if self.use_ctk:
            self.group_widgets["enabled_checkbox"] = ctk.CTkCheckBox(
                row,
                text="Enabled (show this group in the corresponding tool)",
                variable=self.group_widgets["enabled_var"],
                font=get_ctk_font(13),
                text_color=self.colors.fg,
                fg_color=self.colors.accent,
            )
        else:
            self.group_widgets["enabled_checkbox"] = tk.Checkbutton(
                row,
                text="Enabled (show this group in the corresponding tool)",
                variable=self.group_widgets["enabled_var"],
                font=get_tk_font(10),
                bg=self.colors.bg,
                fg=self.colors.fg,
                selectcolor=self.colors.input_bg,
            )
        self.group_widgets["enabled_checkbox"].pack(anchor="w")

        # Items (one per line)
        row = (
            ctk.CTkFrame(right_panel, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(right_panel, bg=self.colors.bg)
        )
        row.pack(fill="both", expand=True, pady=8)

        if self.use_ctk:
            ctk.CTkLabel(
                row,
                text="Items (one action name per line):",
                font=get_ctk_font(13),
                **get_ctk_label_colors(self.colors),
            ).pack(anchor="w")
            self.group_widgets["items"] = ctk.CTkTextbox(
                row, font=get_ctk_font(12), **get_ctk_textbox_colors(self.colors)
            )
        else:
            tk.Label(
                row,
                text="Items (one action name per line):",
                font=get_tk_font(10),
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(anchor="w")
            self.group_widgets["items"] = tk.Text(
                row, font=get_tk_font(10), bg=self.colors.input_bg, fg=self.colors.fg, wrap="word"
            )
        self.group_widgets["items"].pack(fill="both", expand=True, pady=(2, 0))

        # Save button
        create_emoji_button(
            right_panel, "Save Group", "💾", self.colors, "success", 150, 40, self._save_current_group
        ).pack(anchor="w", pady=(18, 0))

    def _on_group_select(self, group_id_str):
        """Handle group selection."""
        try:
            index = int(group_id_str)
        except ValueError:
            return

        settings = self.options_data.get(self.current_tool, {}).get("_settings", {})
        groups = settings.get("popup_groups", [])

        if 0 <= index < len(groups):
            grp = groups[index]
            self.group_widgets["name_var"].set(grp.get("name", ""))
            self.group_widgets["enabled_var"].set(grp.get("enabled", True))
            items = grp.get("items", [])

            if self.use_ctk:
                self.group_widgets["items"].delete("0.0", "end")
                self.group_widgets["items"].insert("0.0", "\n".join(items))
            else:
                self.group_widgets["items"].delete("1.0", "end")
                self.group_widgets["items"].insert("1.0", "\n".join(items))

    def _add_group(self):
        """Add a new group."""
        name = ask_themed_string(self.root, "New Group", "Enter group name:", self.colors)
        if name:
            tool_data = self.options_data.setdefault(self.current_tool, {})
            settings = tool_data.setdefault("_settings", {})
            groups = settings.setdefault("popup_groups", [])
            groups.append({"name": name, "items": []})
            idx = len(groups) - 1
            self.group_listbox.add_item(str(idx), name, None)
            self._update_title()

    def _delete_group(self):
        """Delete selected group."""
        selected_id = self.group_listbox.get_selected()
        if not selected_id:
            return

        try:
            index = int(selected_id)
        except ValueError:
            return

        settings = self.options_data.get(self.current_tool, {}).get("_settings", {})
        groups = settings.get("popup_groups", [])

        if 0 <= index < len(groups):
            if messagebox.askyesno("Delete Group", "Delete this group?", parent=self.root):
                deleted_group = groups[index]
                g_name = deleted_group.get("name")

                # Check if it was a default group
                from ...prompts import PromptsConfig

                defaults = PromptsConfig.get_instance()._get_defaults()
                tool_defaults = defaults.get(self.current_tool, {}).get("_settings", {}).get("popup_groups", [])

                if any(dg.get("name") == g_name for dg in tool_defaults):
                    deleted_groups = settings.setdefault("deleted_groups", [])
                    if g_name and g_name not in deleted_groups:
                        deleted_groups.append(g_name)

                del groups[index]
                self._refresh_group_list()
                self._update_title()

    def _move_group_up(self):
        """Move selected group up."""
        selected_id = self.group_listbox.get_selected()
        if not selected_id:
            return

        try:
            index = int(selected_id)
        except ValueError:
            return

        settings = self.options_data.get(self.current_tool, {}).get("_settings", {})
        groups = settings.get("popup_groups", [])

        if 0 < index < len(groups):
            groups[index], groups[index - 1] = groups[index - 1], groups[index]

            self._refresh_group_list()
            self.group_listbox.select(str(index - 1))
            self._update_title()

    def _move_group_down(self):
        """Move selected group down."""
        selected_id = self.group_listbox.get_selected()
        if not selected_id:
            return

        try:
            index = int(selected_id)
        except ValueError:
            return

        settings = self.options_data.get(self.current_tool, {}).get("_settings", {})
        groups = settings.get("popup_groups", [])

        if 0 <= index < len(groups) - 1:
            groups[index], groups[index + 1] = groups[index + 1], groups[index]

            self._refresh_group_list()
            self.group_listbox.select(str(index + 1))
            self._update_title()

    def _save_current_group(self):
        """Save the currently edited group."""
        selected_id = self.group_listbox.get_selected()
        if not selected_id:
            return

        try:
            index = int(selected_id)
        except ValueError:
            return

        settings = self.options_data.get(self.current_tool, {}).get("_settings", {})
        groups = settings.get("popup_groups", [])

        if 0 <= index < len(groups):
            if self.use_ctk:
                items_text = self.group_widgets["items"].get("0.0", "end").strip()
            else:
                items_text = self.group_widgets["items"].get("1.0", "end").strip()
            items = [item.strip() for item in items_text.split("\n") if item.strip()]

            old_group = groups[index]
            old_name = old_group.get("name")
            new_name = self.group_widgets["name_var"].get()

            groups[index] = {"name": new_name, "enabled": self.group_widgets["enabled_var"].get(), "items": items}

            # Check for deleted default items and name tracking
            from ...prompts import PromptsConfig

            defaults = PromptsConfig.get_instance()._get_defaults()
            tool_defaults = defaults.get(self.current_tool, {}).get("_settings", {}).get("popup_groups", [])

            # If renamed, consider the old default group deleted to avoid duplicate spawn
            is_default = any(dg.get("name") == old_name for dg in tool_defaults)
            if is_default and old_name != new_name:
                deleted_groups = settings.setdefault("deleted_groups", [])
                if old_name not in deleted_groups:
                    deleted_groups.append(old_name)

            # Check for deleted items within the default group
            target_name = new_name if old_name == new_name else old_name
            default_g = next((dg for dg in tool_defaults if dg.get("name") == target_name), None)

            if default_g and old_name == new_name:
                default_items = default_g.get("items", [])
                deleted_items = [di for di in default_items if di not in items]

                deleted_group_items = settings.setdefault("deleted_group_items", {})
                group_deleted = deleted_group_items.setdefault(new_name, [])

                for di in deleted_items:
                    if di not in group_deleted:
                        group_deleted.append(di)
                for item in items:
                    if item in group_deleted:
                        group_deleted.remove(item)

            self._refresh_group_list()
            self.group_listbox.select(str(index))
            self._update_title()
