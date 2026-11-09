#!/usr/bin/env python3
"""
Groups Tab Mixin for the Prompt Editor.

Provides the Groups tab UI and all group CRUD operations.

A group's actions are chosen with a two-pane picker instead of typing names:
the left pane lists the current tool's available actions (click one to add it),
the right pane shows what is in the group, in popup order (reorder / remove there).
"""

import tkinter as tk
from tkinter import messagebox
from typing import List, Optional

from ...custom_widgets import ScrollableButtonList, ask_themed_string, create_emoji_button, create_section_header
from ...platform import HAVE_CTK, ctk
from ...themes import get_ctk_entry_colors, get_ctk_font, get_ctk_label_colors, get_tk_font
from .data import get_group_action_choices, group_action_status

# Label shown in the tool switcher for each tool key.
_GROUP_TOOL_LABELS = {"text_edit_tool": "Text Edit Tool", "snip_tool": "Snip Tool", "audio_tool": "Audio Tool"}

# Id of the non-clickable hint row shown in an empty picker list. Real action keys never
# start with "_" (the popups skip those), so it cannot collide with an action name.
_EMPTY_ROW = "__empty__"

# Delay before the filter box re-filters, so fast typing doesn't rebuild the list per keystroke.
_FILTER_DEBOUNCE_MS = 150


class GroupsTabMixin:
    """Mixin providing the Groups tab for PromptEditorWindow."""

    # Working copy of the edited group's items; written back to options_data by "Save Group".
    _group_items: List[str]
    _group_edit_index: Optional[int] = None  # index of the group loaded in the editor, or None
    _group_tool_shown: Optional[str] = None  # tool the group list was last populated for
    _group_filter_job = None

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
        self.current_tool = next((key for key, label in _GROUP_TOOL_LABELS.items() if label == value), "audio_tool")
        self._group_tool_shown = self.current_tool

        self._refresh_group_list()
        # The group at the same index in the other tool must not stay highlighted over a blank editor
        self.group_listbox.selection_clear()
        self._clear_group_editor()

    def _clear_group_editor(self):
        """Reset the editor to its "no group selected" state."""
        self.group_widgets["name_var"].set("")
        self.group_widgets["enabled_var"].set(True)
        self._group_edit_index = None
        self._group_items = []

        entry = self.group_widgets.get("filter_entry")
        if entry is not None:
            entry.delete(0, "end")
        self._refresh_group_pickers(reset_available=True, reset_items=True)

    def _on_groups_tab_shown(self):
        """Called whenever the Groups tab is displayed (see PromptEditorWindow._on_tab_changed)."""
        if not getattr(self, "group_widgets", None) or not self.group_widgets.get("items_list"):
            return

        if self._group_tool_shown != self.current_tool:
            # The tool was changed on the Actions tab since this tab was last shown: follow it.
            self._group_tool_shown = self.current_tool
            switcher = getattr(self, "group_tool_switcher", None)
            if switcher is not None:
                switcher.set(_GROUP_TOOL_LABELS.get(self.current_tool, "Audio Tool"))
            self._refresh_group_list()
            self.group_listbox.selection_clear()
            self._clear_group_editor()
        else:
            # Actions may have been added, deleted or hidden meanwhile.
            self._refresh_group_pickers()

    def _create_groups_tab(self, frame):
        """Create the Groups editing tab."""
        self._group_items = []
        self._group_edit_index = None
        self._group_tool_shown = self.current_tool
        self._group_filter_job = None

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
                values=list(_GROUP_TOOL_LABELS.values()),
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
            # Sync with current tool if possible, defaulting to Audio Tool for anything unknown
            self.group_tool_switcher.set(_GROUP_TOOL_LABELS.get(self.current_tool, "Audio Tool"))
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

        # Items: pick from the tool's available actions, in popup order
        row = (
            ctk.CTkFrame(right_panel, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(right_panel, bg=self.colors.bg)
        )
        row.pack(fill="both", expand=True, pady=(8, 0))
        self._build_group_item_picker(row)

        # Save button
        create_emoji_button(
            right_panel, "Save Group", "💾", self.colors, "success", 150, 40, self._save_current_group
        ).pack(anchor="w", pady=(14, 0))

        self._refresh_group_pickers(reset_available=True, reset_items=True)

    def _build_group_item_picker(self, parent):
        """
        Build the two-pane action picker.

            Available actions (click to add)  |  In this group (select to reorder / remove)
            [ filter ...                   ]  |  [⬆] [⬇] [Remove]
            [ list                         ]  |  [ list ]
        """
        c = self.colors
        w = self.group_widgets

        grid = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=c.bg)
        grid.pack(fill="both", expand=True)
        grid.grid_columnconfigure(0, weight=1, uniform="group_picker")
        grid.grid_columnconfigure(1, weight=1, uniform="group_picker")
        grid.grid_rowconfigure(2, weight=1)

        def make_header(column: int, padx: tuple):
            if self.use_ctk:
                lbl = ctk.CTkLabel(grid, text="", font=get_ctk_font(13, "bold"), anchor="w", **get_ctk_label_colors(c))
            else:
                lbl = tk.Label(grid, text="", font=get_tk_font(10, "bold"), anchor="w", bg=c.bg, fg=c.fg)
            lbl.grid(row=0, column=column, sticky="w", padx=padx)
            return lbl

        w["available_header"] = make_header(0, (0, 6))
        w["items_header"] = make_header(1, (6, 0))

        # Row 1 left: filter box
        if self.use_ctk:
            # No textvariable here: CTkEntry only shows its placeholder when it has none.
            entry = ctk.CTkEntry(
                grid,
                placeholder_text="🔍 Filter actions...",
                font=get_ctk_font(13),
                height=34,
                **get_ctk_entry_colors(c),
            )
        else:
            entry = tk.Entry(grid, font=get_tk_font(10), bg=c.input_bg, fg=c.fg)
        entry.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(6, 6))
        entry.bind("<KeyRelease>", self._on_group_filter_changed)
        w["filter_entry"] = entry

        # Row 1 right: reorder / remove buttons
        toolbar = ctk.CTkFrame(grid, fg_color="transparent") if self.use_ctk else tk.Frame(grid, bg=c.bg)
        toolbar.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(6, 6))
        create_emoji_button(toolbar, "⬆", "", c, "secondary", 40, 34, lambda: self._move_group_item(-1)).pack(
            side="left", padx=(0, 6)
        )
        create_emoji_button(toolbar, "⬇", "", c, "secondary", 40, 34, lambda: self._move_group_item(1)).pack(
            side="left", padx=(0, 6)
        )
        create_emoji_button(toolbar, "Remove", "🗑️", c, "danger", 110, 34, self._remove_group_item).pack(side="left")

        # Row 2: the two lists
        if self.use_ctk:
            w["available_list"] = ScrollableButtonList(
                grid, c, command=self._on_group_action_pick, corner_radius=8, fg_color=c.input_bg
            )
            w["items_list"] = ScrollableButtonList(
                grid, c, command=self._on_group_item_select, corner_radius=8, fg_color=c.input_bg
            )
        else:
            w["available_list"] = ScrollableButtonList(grid, c, command=self._on_group_action_pick, bg=c.input_bg)
            w["items_list"] = ScrollableButtonList(grid, c, command=self._on_group_item_select, bg=c.input_bg)
        w["available_list"].grid(row=2, column=0, sticky="nsew", padx=(0, 6))
        w["items_list"].grid(row=2, column=1, sticky="nsew", padx=(6, 0))

        # Row 3: shown only when the group lists actions the popup will skip
        if self.use_ctk:
            w["flag_hint"] = ctk.CTkLabel(
                grid, text="", font=get_ctk_font(11), anchor="w", justify="left", **get_ctk_label_colors(c, muted=True)
            )
        else:
            w["flag_hint"] = tk.Label(
                grid, text="", font=get_tk_font(9), anchor="w", justify="left", bg=c.bg, fg=c.blockquote
            )
        w["flag_hint"].grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        w["flag_hint"].grid_remove()

    # ------------------------------------------------------------------
    # Picker rendering
    # ------------------------------------------------------------------

    def _refresh_group_pickers(self, reset_available: bool = False, reset_items: bool = False):
        """
        Rebuild both picker lists from the current tool's actions and the working copy of the group.

        Scroll positions (and the selection in the group list) are kept unless a reset is requested,
        so adding / removing / reordering doesn't throw the view back to the top.
        """
        w = getattr(self, "group_widgets", None)
        if not w or not w.get("items_list"):
            return
        available, items_list = w["available_list"], w["items_list"]

        tool_data = self.options_data.get(self.current_tool, {})
        editing = self._group_edit_index is not None

        # --- Right pane: what's in the group, in popup order ---
        scroll = 0.0 if reset_items else items_list.get_scroll_position()
        selected = None if reset_items else items_list.get_selected()
        items_list.clear()
        flagged = {"hidden": 0, "missing": 0}
        for i, name in enumerate(self._group_items):
            status = group_action_status(self.current_tool, tool_data, name)
            if status == "ok":
                items_list.add_item(str(i), name, tool_data[name].get("icon") or None)
            else:
                flagged[status] += 1
                marker = "⊘" if status == "hidden" else "⚠"
                items_list.add_item(str(i), f"{marker} {name}", None, dimmed=True)
        if editing and not self._group_items:
            items_list.add_item(_EMPTY_ROW, "Nothing yet - click an action on the left", None, dimmed=True)
        if selected:
            items_list.select(selected)
        items_list.set_scroll_position(scroll)

        # --- Left pane: actions that can still be added ---
        query = w["filter_entry"].get().strip().lower() if w.get("filter_entry") else ""
        in_group = set(self._group_items)
        scroll = 0.0 if reset_available else available.get_scroll_position()
        available.clear()
        shown = 0
        if editing:
            for name, icon in get_group_action_choices(self.current_tool, tool_data):
                if name in in_group or (query and query not in name.lower()):
                    continue
                available.add_item(name, name, icon or None)
                shown += 1
        if shown == 0:
            if not editing:
                message = "Select or add a group first"
            elif query:
                message = "No matching actions"
            else:
                message = "No more actions to add"
            available.add_item(_EMPTY_ROW, message, None, dimmed=True)
        available.set_scroll_position(scroll)

        # --- Headers and the "won't show" hint ---
        w["available_header"].configure(text=f"Available actions ({shown}) - click to add")
        w["items_header"].configure(text=f"In this group ({len(self._group_items)}) - select to edit")

        notes = []
        if flagged["hidden"]:
            notes.append(f"⊘ {flagged['hidden']} hidden")
        if flagged["missing"]:
            notes.append(f"⚠ {flagged['missing']} not found")
        if notes:
            w["flag_hint"].configure(
                text=f"{', '.join(notes)}: the popup skips these. Remove them, or unhide / recreate the action."
            )
            w["flag_hint"].grid()
        else:
            w["flag_hint"].grid_remove()

    # ------------------------------------------------------------------
    # Picker interaction
    # ------------------------------------------------------------------

    def _on_group_filter_changed(self, _event=None):
        """Re-filter the available list shortly after the user stops typing."""
        if self._group_filter_job is not None:
            try:
                self.root.after_cancel(self._group_filter_job)
            except (tk.TclError, AttributeError):
                pass
        self._group_filter_job = self.root.after(_FILTER_DEBOUNCE_MS, self._apply_group_filter)

    def _apply_group_filter(self):
        self._group_filter_job = None
        try:
            self._refresh_group_pickers(reset_available=True)
        except tk.TclError:
            pass  # window closed while the timer was pending

    def _on_group_action_pick(self, name):
        """An action was clicked in the available list: append it to the group."""
        if name == _EMPTY_ROW or self._group_edit_index is None:
            self.group_widgets["available_list"].selection_clear()
            return

        self._group_items.append(name)
        self._refresh_group_pickers()
        self.group_widgets["items_list"].see(str(len(self._group_items) - 1))

    def _on_group_item_select(self, item_id):
        """A row was clicked in the group list (selection itself is all the buttons need)."""
        if item_id == _EMPTY_ROW:
            self.group_widgets["items_list"].selection_clear()

    def _selected_group_item_index(self) -> Optional[int]:
        """Index in the working copy of the selected group-list row, or None."""
        items_list = self.group_widgets.get("items_list")
        try:
            index = int(items_list.get_selected()) if items_list else None
        except (TypeError, ValueError):
            return None
        return index if index is not None and 0 <= index < len(self._group_items) else None

    def _move_group_item(self, delta: int):
        """Move the selected action up (-1) or down (+1) within the group."""
        index = self._selected_group_item_index()
        if index is None:
            return
        target = index + delta
        if not 0 <= target < len(self._group_items):
            return

        self._group_items[index], self._group_items[target] = self._group_items[target], self._group_items[index]
        self._refresh_group_pickers()
        items_list = self.group_widgets["items_list"]
        items_list.select(str(target))
        items_list.see(str(target))

    def _remove_group_item(self):
        """Remove the selected action from the group (it returns to the available list)."""
        index = self._selected_group_item_index()
        if index is None:
            return

        del self._group_items[index]
        self._refresh_group_pickers()
        if self._group_items:
            # Select the neighbour that slid into place so several can be removed in a row
            neighbour = str(min(index, len(self._group_items) - 1))
            items_list = self.group_widgets["items_list"]
            items_list.select(neighbour)
            items_list.see(neighbour)

    # ------------------------------------------------------------------
    # Group CRUD
    # ------------------------------------------------------------------

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

            # Edit a copy; the group itself only changes on "Save Group"
            self._group_edit_index = index
            self._group_items = list(grp.get("items", []))
            self._refresh_group_pickers(reset_available=True, reset_items=True)

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
            # Open it straight away so actions can be picked for it
            self.group_listbox.select(str(idx))

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
                if not self.group_listbox.get_selected():
                    # Nothing took its place (it was the last group): don't leave it open in the editor
                    self._clear_group_editor()
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
            items = list(self._group_items)

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
