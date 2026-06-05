#!/usr/bin/env python3
"""
Actions Tab Mixin for the Prompt Editor.

Provides the Actions tab UI and all action CRUD operations.
"""

import copy
import tkinter as tk
from tkinter import messagebox

from ...custom_widgets import (
    ScrollableButtonList,
    ScrollableComboBox,
    TkScrollableFrame,
    ask_themed_string,
    create_emoji_button,
    create_section_header,
)
from ...platform import HAVE_CTK, ctk
from ...themes import (
    get_ctk_button_colors,
    get_ctk_combobox_colors,
    get_ctk_entry_colors,
    get_ctk_font,
    get_ctk_label_colors,
    get_ctk_textbox_colors,
)


class ActionsTabMixin:
    """Mixin providing the Actions tab for PromptEditorWindow."""

    def _create_actions_tab(self, frame):
        """Create the Actions editing tab."""
        # Container with left/right panes
        container = ctk.CTkFrame(frame, fg_color="transparent") if self.use_ctk else tk.Frame(frame, bg=self.colors.bg)
        container.pack(fill="both", expand=True, padx=15, pady=15)

        # Left panel: action list (fixed width)
        left_panel = (
            ctk.CTkFrame(container, fg_color="transparent", width=260)
            if self.use_ctk
            else tk.Frame(container, bg=self.colors.bg, width=260)
        )
        left_panel.pack(side="left", fill="y", padx=(0, 15))
        left_panel.pack_propagate(False)

        create_section_header(left_panel, "Actions", self.colors, "⚡")

        # Tool Switcher
        if self.use_ctk:
            self.tool_switcher = ctk.CTkSegmentedButton(
                left_panel,
                values=["Text Edit Tool", "Snip Tool", "Audio Tool"],
                command=self._on_tool_switch,
                font=get_ctk_font(12, "bold"),
                fg_color=self.colors.bg,
                selected_color=self.colors.accent,
                selected_hover_color=self.colors.accent,
                unselected_color=self.colors.surface0,
                unselected_hover_color=self.colors.surface1,
                text_color=self.colors.fg,
                text_color_disabled=self.colors.surface2,
            )
            self.tool_switcher.set("Text Edit Tool")
            self.tool_switcher.pack(fill="x", pady=(0, 10))

        # List container - using ScrollableButtonList
        if self.use_ctk:
            self.action_listbox = ScrollableButtonList(
                left_panel, self.colors, command=self._on_action_select, corner_radius=8, fg_color=self.colors.input_bg
            )
        else:
            self.action_listbox = ScrollableButtonList(
                left_panel, self.colors, command=self._on_action_select, bg=self.colors.input_bg
            )
        self.action_listbox.pack(fill="both", expand=True)

        # Action buttons
        btn_frame = (
            ctk.CTkFrame(left_panel, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(left_panel, bg=self.colors.bg)
        )
        btn_frame.pack(fill="x", pady=(12, 0))

        # Buttons using shared helper
        create_emoji_button(btn_frame, "Add", "➕", self.colors, "success", 70, 34, self._add_action).pack(
            side="left", padx=3
        )
        create_emoji_button(btn_frame, "", "📋", self.colors, "secondary", 40, 34, self._duplicate_action).pack(
            side="left", padx=3
        )
        create_emoji_button(btn_frame, "", "🗑️", self.colors, "danger", 40, 34, self._delete_action).pack(
            side="left", padx=3
        )
        create_emoji_button(btn_frame, "⬆", "", self.colors, "secondary", 40, 34, self._move_action_up).pack(
            side="left", padx=3
        )
        create_emoji_button(btn_frame, "⬇", "", self.colors, "secondary", 40, 34, self._move_action_down).pack(
            side="left", padx=3
        )

        # Right panel: action editor
        right_panel = (
            ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=self.colors.bg)
        )
        right_panel.pack(side="left", fill="both", expand=True)

        create_section_header(right_panel, "Edit Action", self.colors, "✏️")

        # Editor form in scrollable frame
        if self.use_ctk:
            editor_container = ctk.CTkScrollableFrame(right_panel, fg_color="transparent")
            editor_scroll = editor_container
        else:
            editor_container = TkScrollableFrame(right_panel, bg_color=self.colors.bg)
            editor_scroll = editor_container.scrollable_frame
        editor_container.pack(fill="both", expand=True)

        # Action name (read-only label)
        row_frame = (
            ctk.CTkFrame(editor_scroll, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(editor_scroll, bg=self.colors.bg)
        )
        row_frame.pack(fill="x", pady=8)

        if self.use_ctk:
            ctk.CTkLabel(
                row_frame,
                text="Name:",
                font=get_ctk_font(13),
                width=120,
                anchor="w",
                **get_ctk_label_colors(self.colors),
            ).pack(side="left")
            self.editor_widgets["name"] = ctk.CTkLabel(
                row_frame, text="(select an action)", font=get_ctk_font(13, "bold"), **get_ctk_label_colors(self.colors)
            )
        else:
            tk.Label(
                row_frame,
                text="Name:",
                font=("Segoe UI", 10),
                width=12,
                anchor="w",
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(side="left")
            self.editor_widgets["name"] = tk.Label(
                row_frame,
                text="(select an action)",
                font=("Segoe UI", 10, "bold"),
                bg=self.colors.bg,
                fg=self.colors.fg,
            )
        self.editor_widgets["name"].pack(side="left", padx=(10, 0))

        # Icon field
        row_frame = (
            ctk.CTkFrame(editor_scroll, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(editor_scroll, bg=self.colors.bg)
        )
        row_frame.pack(fill="x", pady=8)

        if self.use_ctk:
            ctk.CTkLabel(
                row_frame,
                text="Icon:",
                font=get_ctk_font(13),
                width=120,
                anchor="w",
                **get_ctk_label_colors(self.colors),
            ).pack(side="left")
            self.editor_widgets["icon_var"] = tk.StringVar(master=self.root)
            self.editor_widgets["icon_entry"] = ctk.CTkEntry(
                row_frame,
                textvariable=self.editor_widgets["icon_var"],
                font=get_ctk_font(16),
                width=70,
                height=34,
                placeholder_text="📋",
                **get_ctk_entry_colors(self.colors),
            )
            self.editor_widgets["icon_entry"].pack(side="left", padx=(12, 8))
            ctk.CTkLabel(
                row_frame, text="(paste emoji here — Ctrl+V)", font=get_ctk_font(11), text_color=self.colors.surface2
            ).pack(side="left", padx=(4, 0))
        else:
            tk.Label(
                row_frame,
                text="Icon:",
                font=("Segoe UI", 10),
                width=12,
                anchor="w",
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(side="left")
            self.editor_widgets["icon_var"] = tk.StringVar(master=self.root)
            self.editor_widgets["icon_entry"] = tk.Entry(
                row_frame,
                textvariable=self.editor_widgets["icon_var"],
                font=("Segoe UI", 12),
                width=5,
                bg=self.colors.input_bg,
                fg=self.colors.fg,
            )
            self.editor_widgets["icon_entry"].pack(side="left", padx=(10, 5))
            tk.Label(
                row_frame,
                text="(paste emoji here — Ctrl+V)",
                font=("Segoe UI", 9),
                bg=self.colors.bg,
                fg=self.colors.surface2,
            ).pack(side="left", padx=(4, 0))

        # Prompt type dropdown (Text Edit Tool only)
        self.prompt_type_frame = (
            ctk.CTkFrame(editor_scroll, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(editor_scroll, bg=self.colors.bg)
        )
        self.prompt_type_frame.pack(fill="x", pady=8)

        if self.use_ctk:
            ctk.CTkLabel(
                self.prompt_type_frame,
                text="Type:",
                font=get_ctk_font(13),
                width=120,
                anchor="w",
                **get_ctk_label_colors(self.colors),
            ).pack(side="left")
            self.editor_widgets["prompt_type_var"] = tk.StringVar(master=self.root, value="edit")
            self.editor_widgets["prompt_type"] = ctk.CTkComboBox(
                self.prompt_type_frame,
                variable=self.editor_widgets["prompt_type_var"],
                values=["edit", "general"],
                width=180,
                height=34,
                state="readonly",
                font=get_ctk_font(13),
                **get_ctk_combobox_colors(self.colors),
            )
            self.editor_widgets["prompt_type"].pack(side="left", padx=(12, 0))
        else:
            from tkinter import ttk

            tk.Label(
                self.prompt_type_frame,
                text="Type:",
                font=("Segoe UI", 10),
                width=12,
                anchor="w",
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(side="left")
            self.editor_widgets["prompt_type_var"] = tk.StringVar(master=self.root, value="edit")
            self.editor_widgets["prompt_type"] = ttk.Combobox(
                self.prompt_type_frame,
                textvariable=self.editor_widgets["prompt_type_var"],
                values=["edit", "general"],
                state="readonly",
                width=15,
            )
            self.editor_widgets["prompt_type"].pack(side="left", padx=(10, 0))

        # System prompt (multiline)
        row_frame = (
            ctk.CTkFrame(editor_scroll, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(editor_scroll, bg=self.colors.bg)
        )
        row_frame.pack(fill="x", pady=8)

        if self.use_ctk:
            ctk.CTkLabel(
                row_frame, text="System Prompt:", font=get_ctk_font(13), anchor="w", **get_ctk_label_colors(self.colors)
            ).pack(anchor="w")
            self.editor_widgets["system_prompt"] = ctk.CTkTextbox(
                row_frame, height=140, font=get_ctk_font(12), **get_ctk_textbox_colors(self.colors)
            )
            self.editor_widgets["system_prompt"].pack(fill="x", pady=(8, 0))
        else:
            tk.Label(
                row_frame, text="System Prompt:", font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg
            ).pack(anchor="w")
            self.editor_widgets["system_prompt"] = tk.Text(
                row_frame, font=("Consolas", 10), height=6, bg=self.colors.input_bg, fg=self.colors.fg, wrap="word"
            )
            self.editor_widgets["system_prompt"].pack(fill="x", pady=(5, 0))

        # Task field
        row_frame = (
            ctk.CTkFrame(editor_scroll, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(editor_scroll, bg=self.colors.bg)
        )
        row_frame.pack(fill="x", pady=8)

        if self.use_ctk:
            ctk.CTkLabel(
                row_frame,
                text="Task:",
                font=get_ctk_font(13),
                width=120,
                anchor="w",
                **get_ctk_label_colors(self.colors),
            ).pack(side="left")
            self.editor_widgets["task_var"] = tk.StringVar()
            self.editor_widgets["task"] = ctk.CTkEntry(
                row_frame,
                textvariable=self.editor_widgets["task_var"],
                font=get_ctk_font(13),
                height=34,
                **get_ctk_entry_colors(self.colors),
            )
            self.editor_widgets["task"].pack(side="left", fill="x", expand=True, padx=(12, 0))
        else:
            tk.Label(
                row_frame,
                text="Task:",
                font=("Segoe UI", 10),
                width=12,
                anchor="w",
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(side="left")
            self.editor_widgets["task_var"] = tk.StringVar()
            self.editor_widgets["task"] = tk.Entry(
                row_frame,
                textvariable=self.editor_widgets["task_var"],
                font=("Segoe UI", 10),
                bg=self.colors.input_bg,
                fg=self.colors.fg,
            )
            self.editor_widgets["task"].pack(side="left", fill="x", expand=True, padx=(10, 0))

        # Show in chat checkbox (label varies by tool)
        self.show_chat_frame = (
            ctk.CTkFrame(editor_scroll, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(editor_scroll, bg=self.colors.bg)
        )
        self.show_chat_frame.pack(fill="x", pady=10)

        self.editor_widgets["show_chat_var"] = tk.BooleanVar()
        if self.use_ctk:
            self.editor_widgets["show_chat"] = ctk.CTkCheckBox(
                self.show_chat_frame,
                text="Show response in chat window instead of typing/replacing text",
                variable=self.editor_widgets["show_chat_var"],
                font=get_ctk_font(13),
                text_color=self.colors.fg,
                fg_color=self.colors.accent,
            )
        else:
            self.editor_widgets["show_chat"] = tk.Checkbutton(
                self.show_chat_frame,
                text="Show response in chat window instead of typing/replacing text",
                variable=self.editor_widgets["show_chat_var"],
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.fg,
                selectcolor=self.colors.input_bg,
            )
        self.editor_widgets["show_chat"].pack(anchor="w")

        # Compare prompts checkbox (Text Edit Tool and Snip Tool)
        self.compare_prompts_frame = (
            ctk.CTkFrame(editor_scroll, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(editor_scroll, bg=self.colors.bg)
        )
        # Initially shown for text_edit_tool (the default)

        self.editor_widgets["compare_prompts_var"] = tk.BooleanVar()
        if self.use_ctk:
            self.editor_widgets["compare_prompts"] = ctk.CTkCheckBox(
                self.compare_prompts_frame,
                text="Compare mode",
                variable=self.editor_widgets["compare_prompts_var"],
                font=get_ctk_font(13),
                text_color=self.colors.fg,
                fg_color=self.colors.accent,
            )
        else:
            self.editor_widgets["compare_prompts"] = tk.Checkbutton(
                self.compare_prompts_frame,
                text="Compare mode",
                variable=self.editor_widgets["compare_prompts_var"],
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.fg,
                selectcolor=self.colors.input_bg,
            )
        self.editor_widgets["compare_prompts"].pack(anchor="w")

        # Show compare_prompts frame initially (text_edit_tool is default)
        self.compare_prompts_frame.pack(fill="x", pady=10)

        # Connection Profile dropdown (all tools)
        self.profile_frame = (
            ctk.CTkFrame(editor_scroll, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(editor_scroll, bg=self.colors.bg)
        )
        self.profile_frame.pack(fill="x", pady=8)

        if self.use_ctk:
            ctk.CTkLabel(
                self.profile_frame,
                text="Connection Profile:",
                font=get_ctk_font(13),
                width=120,
                anchor="w",
                **get_ctk_label_colors(self.colors),
            ).pack(side="left")
        else:
            tk.Label(
                self.profile_frame,
                text="Connection Profile:",
                font=("Segoe UI", 10),
                width=12,
                anchor="w",
                bg=self.colors.bg,
                fg=self.colors.fg,
            ).pack(side="left")

        self.editor_widgets["profile_var"] = tk.StringVar(master=self.root, value="(None)")

        def _tooltip_callback(name: str) -> str:
            from ..utils import get_profile_tooltip_text

            return get_profile_tooltip_text(name)

        self.editor_widgets["profile_combo"] = ScrollableComboBox(
            self.profile_frame,
            colors=self.colors,
            values=["(None)"],
            variable=self.editor_widgets["profile_var"],
            width=220,
            height=34,
            font_size=13,
            state="readonly",
            item_tooltip_callback=_tooltip_callback,
        )
        self.editor_widgets["profile_combo"].pack(side="left", padx=(12, 8) if self.use_ctk else (10, 5))

        # Tooltip for the closed combobox entry
        from ...popups import Tooltip
        from ..utils import get_profile_tooltip_text

        self._profile_combo_tooltip = Tooltip(
            self.editor_widgets["profile_combo"].entry,
            get_profile_tooltip_text(self.editor_widgets["profile_var"].get()),
            delay_ms=400,
        )

        if self.use_ctk:
            ctk.CTkButton(
                self.profile_frame,
                text="Manage...",
                font=get_ctk_font(12),
                width=90,
                height=34,
                **get_ctk_button_colors(self.colors, "secondary"),
                command=self._open_profile_manager,
            ).pack(side="left")
        else:
            tk.Button(
                self.profile_frame,
                text="Manage...",
                font=("Segoe UI", 9),
                bg=self.colors.surface1,
                fg=self.colors.fg,
                command=self._open_profile_manager,
            ).pack(side="left")

        # Trace profile changes
        self.editor_widgets["profile_var"].trace_add("write", self._on_profile_var_changed)

        # Refresh profile dropdown values
        self._refresh_profile_dropdown()
        self._refresh_action_list()

        # Save action button - OUTSIDE scrollable frame so it's always visible
        btn_frame = (
            ctk.CTkFrame(right_panel, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(right_panel, bg=self.colors.bg)
        )
        btn_frame.pack(fill="x", pady=(10, 0), side="bottom")

        create_emoji_button(
            btn_frame, "Save Action", "💾", self.colors, "success", 150, 40, self._save_current_action
        ).pack(side="left")

        if self.use_ctk:
            self.editor_widgets["save_status"] = ctk.CTkLabel(
                btn_frame, text="", font=get_ctk_font(12), text_color=self.colors.accent_green
            )
        else:
            self.editor_widgets["save_status"] = tk.Label(
                btn_frame, text="", font=("Segoe UI", 9), bg=self.colors.bg, fg=self.colors.accent_green
            )
        self.editor_widgets["save_status"].pack(side="left", padx=15)

    def _refresh_action_list(self):
        """Refresh the action scrollable list based on current tool."""
        if not self.action_listbox:
            return

        selected = self.action_listbox.get_selected()
        self.action_listbox.clear()

        tool_data = self.options_data.get(self.current_tool, {})

        for name in tool_data.keys():
            if name == "_settings":
                continue
            icon = tool_data[name].get("icon", "")
            self.action_listbox.add_item(name, name, icon)

        if selected and selected in tool_data:
            self.action_listbox.select(selected)
        else:
            self.editor_widgets["name"].configure(text="(select an action)")
            self._clear_editor()

    def _clear_editor(self):
        """Clear the editor fields."""
        if not hasattr(self, "editor_widgets") or not self.editor_widgets:
            return

        self.editor_widgets["icon_var"].set("")
        self.editor_widgets["prompt_type_var"].set("edit")
        self.editor_widgets["task_var"].set("")
        self.editor_widgets["show_chat_var"].set(False)
        if "compare_prompts_var" in self.editor_widgets:
            self.editor_widgets["compare_prompts_var"].set(False)

        if self.use_ctk:
            self.editor_widgets["system_prompt"].delete("0.0", "end")
        else:
            self.editor_widgets["system_prompt"].delete("1.0", "end")

    def _update_editor_visibility(self):
        """Show/hide editor fields based on current tool."""
        if not hasattr(self, "prompt_type_frame"):
            return

        is_text_edit = self.current_tool == "text_edit_tool"
        is_snip = self.current_tool == "snip_tool"
        is_audio = self.current_tool == "audio_tool"

        # prompt_type: Text Edit only
        if is_text_edit:
            self.prompt_type_frame.pack(fill="x", pady=8)
        else:
            self.prompt_type_frame.pack_forget()

        # compare_prompts: Text Edit and Snip Tool
        if hasattr(self, "compare_prompts_frame"):
            if is_text_edit or is_snip:
                self.compare_prompts_frame.pack(fill="x", pady=10)
            else:
                self.compare_prompts_frame.pack_forget()

        # Update checkbox label based on tool (per user requirement)
        if hasattr(self, "editor_widgets") and "show_chat" in self.editor_widgets:
            if is_text_edit:
                new_text = "Show response in chat window instead of typing/replacing text"
            elif is_snip:
                new_text = "Show response in chat window instead of copy to clipboard"
            else:  # audio_tool
                new_text = "Show response in chat window instead of in result panel"

            if self.use_ctk:
                self.editor_widgets["show_chat"].configure(text=new_text)
            else:
                self.editor_widgets["show_chat"].configure(text=new_text)

    def _on_tool_switch(self, value):
        """Handle tool switching."""
        if value == "Text Edit Tool":
            self.current_tool = "text_edit_tool"
        elif value == "Snip Tool":
            self.current_tool = "snip_tool"
        else:  # Audio Tool
            self.current_tool = "audio_tool"

        # Clear current selection and refresh list
        self.current_action = None
        self._refresh_action_list()
        self._update_editor_visibility()

    def _on_action_select(self, action_name):
        """Handle action selection."""
        if not action_name:
            return

        self.current_action = action_name
        tool_data = self.options_data.get(self.current_tool, {})
        action_data = tool_data.get(action_name, {})

        # Populate editor
        if self.use_ctk:
            self.editor_widgets["name"].configure(text=action_name)
        else:
            self.editor_widgets["name"].configure(text=action_name)

        self.editor_widgets["icon_var"].set(action_data.get("icon", ""))

        if self.use_ctk:
            self.editor_widgets["system_prompt"].delete("0.0", "end")
            self.editor_widgets["system_prompt"].insert("0.0", action_data.get("system_prompt", ""))
        else:
            self.editor_widgets["system_prompt"].delete("1.0", "end")
            self.editor_widgets["system_prompt"].insert("1.0", action_data.get("system_prompt", ""))

        self.editor_widgets["task_var"].set(action_data.get("task", ""))

        # Handle different field names per tool
        if self.current_tool == "text_edit_tool":
            self.editor_widgets["prompt_type_var"].set(action_data.get("prompt_type", "edit"))
            self.editor_widgets["show_chat_var"].set(action_data.get("show_chat_window_instead_of_replace", False))
            if "compare_prompts_var" in self.editor_widgets:
                self.editor_widgets["compare_prompts_var"].set(action_data.get("compare_prompts", False))
        else:  # snip_tool or audio_tool
            self.editor_widgets["prompt_type_var"].set("edit")  # Not used but keep default
            self.editor_widgets["show_chat_var"].set(action_data.get("show_chat_window", True))
            if self.current_tool == "snip_tool" and "compare_prompts_var" in self.editor_widgets:
                self.editor_widgets["compare_prompts_var"].set(action_data.get("compare_prompts", False))

        # Load connection profile (all tools)
        if "profile_var" in self.editor_widgets:
            profile_name = action_data.get("connection_profile", "") or ""
            self.editor_widgets["profile_var"].set(profile_name if profile_name else "(None)")

            # Update tooltip
            if hasattr(self, "_profile_combo_tooltip"):
                from ..utils import get_profile_tooltip_text

                self._profile_combo_tooltip.text = get_profile_tooltip_text(profile_name)

        # Update field visibility
        self._update_editor_visibility()

    def _refresh_profile_dropdown(self):
        """Refresh the connection profile dropdown values from profile store."""
        from ....connection_profiles import ProfileStore

        profile_names = ProfileStore.get_instance().get_profile_names()
        values = ["(None)", *profile_names]

        if "profile_combo" in self.editor_widgets:
            combo = self.editor_widgets["profile_combo"]
            combo.configure(values=values)

        # Also sync to the playground tab if it exists
        if hasattr(self, "_refresh_playground_profiles"):
            self._refresh_playground_profiles()

    def _open_profile_manager(self):
        """Open the Manage Profiles dialog."""
        try:
            from ..connection_manager import ConnectionProfileManager

            ConnectionProfileManager(self.root, colors=self.colors, on_close=self._refresh_profile_dropdown)
        except Exception as e:
            print(f"[PromptEditor] Error opening connection manager: {e}")

    def _on_profile_var_changed(self, *args):
        """Update profile combo tooltip when selection changes."""
        if hasattr(self, "_profile_combo_tooltip") and "profile_var" in self.editor_widgets:
            from ..utils import get_profile_tooltip_text

            name = self.editor_widgets["profile_var"].get()
            self._profile_combo_tooltip.text = get_profile_tooltip_text(name)

    def _add_action(self):
        """Add a new action."""
        name = ask_themed_string(self.root, "New Action", "Enter action name:", self.colors)
        tool_data = self.options_data.setdefault(self.current_tool, {})

        if name and name not in tool_data:
            tool_data[name] = {
                "_is_default": False,
                "icon": "⚡",
                "prompt_type": "edit",
                "system_prompt": "",
                "task": "",
                "show_chat_window_instead_of_replace": False,
            }
            self.action_listbox.add_item(name, name, "⚡")
            self.action_listbox.select(name)

    def _duplicate_action(self):
        """Duplicate selected action."""
        if not self.current_action:
            return

        tool_data = self.options_data.get(self.current_tool, {})
        new_name = f"{self.current_action}_copy"
        counter = 1
        while new_name in tool_data:
            counter += 1
            new_name = f"{self.current_action}_copy{counter}"

        tool_data[new_name] = copy.deepcopy(tool_data[self.current_action])
        tool_data[new_name]["_is_default"] = False

        icon = tool_data[new_name].get("icon", "")
        self.action_listbox.add_item(new_name, new_name, icon)

    def _delete_action(self):
        """Delete selected action."""
        if not self.current_action:
            return

        if messagebox.askyesno("Delete Action", f"Delete action '{self.current_action}'?", parent=self.root):
            tool_data = self.options_data.get(self.current_tool, {})

            # Check if this was a default action before removing
            from ...prompts import DEFAULT_AUDIO_ACTIONS, DEFAULT_SNIP_ACTIONS, DEFAULT_TEXT_EDIT_ACTIONS

            is_default = False
            if self.current_tool == "text_edit_tool" and self.current_action in DEFAULT_TEXT_EDIT_ACTIONS:
                is_default = True
            elif self.current_tool == "snip_tool" and self.current_action in DEFAULT_SNIP_ACTIONS:
                is_default = True
            elif self.current_tool == "audio_tool" and self.current_action in DEFAULT_AUDIO_ACTIONS:
                is_default = True

            if is_default:
                _settings = tool_data.setdefault("_settings", {})
                deleted_defaults = _settings.setdefault("deleted_defaults", [])
                if self.current_action not in deleted_defaults:
                    deleted_defaults.append(self.current_action)

            if self.current_action in tool_data:
                del tool_data[self.current_action]
            self.action_listbox.delete(self.current_action)
            self.current_action = None
            if self.use_ctk:
                self.editor_widgets["name"].configure(text="(select an action)")
            else:
                self.editor_widgets["name"].configure(text="(select an action)")

    def _move_action_up(self):
        """Move selected action up."""
        if not self.current_action:
            return

        tool_data = self.options_data.get(self.current_tool, {})
        display_keys = [k for k in tool_data.keys() if k != "_settings"]
        if self.current_action not in display_keys:
            return

        idx = display_keys.index(self.current_action)
        if idx > 0:
            # Swap
            display_keys[idx], display_keys[idx - 1] = display_keys[idx - 1], display_keys[idx]

            # Reconstruct dictionary
            new_data = {}
            for k in display_keys:
                new_data[k] = tool_data[k]

            # append _settings if exists
            if "_settings" in tool_data:
                new_data["_settings"] = tool_data["_settings"]

            self.options_data[self.current_tool] = new_data
            self._refresh_action_list()
            self.action_listbox.select(self.current_action)

    def _move_action_down(self):
        """Move selected action down."""
        if not self.current_action:
            return

        tool_data = self.options_data.get(self.current_tool, {})
        display_keys = [k for k in tool_data.keys() if k != "_settings"]
        if self.current_action not in display_keys:
            return

        idx = display_keys.index(self.current_action)
        if idx < len(display_keys) - 1:
            # Swap
            display_keys[idx], display_keys[idx + 1] = display_keys[idx + 1], display_keys[idx]

            # Reconstruct dictionary
            new_data = {}
            for k in display_keys:
                new_data[k] = tool_data[k]

            if "_settings" in tool_data:
                new_data["_settings"] = tool_data["_settings"]

            self.options_data[self.current_tool] = new_data
            self._refresh_action_list()
            self.action_listbox.select(self.current_action)

    def _save_current_action(self):
        """Save the currently edited action."""
        if not self.current_action:
            return

        if self.use_ctk:
            system_prompt = self.editor_widgets["system_prompt"].get("0.0", "end").strip()
        else:
            system_prompt = self.editor_widgets["system_prompt"].get("1.0", "end").strip()

        # Build action dict with common fields
        action_dict = {
            "_is_default": False,
            "icon": self.editor_widgets["icon_var"].get(),
            "system_prompt": system_prompt,
            "task": self.editor_widgets["task_var"].get(),
        }

        # Tool-specific fields
        if self.current_tool == "text_edit_tool":
            action_dict["prompt_type"] = self.editor_widgets["prompt_type_var"].get()
            action_dict["show_chat_window_instead_of_replace"] = self.editor_widgets["show_chat_var"].get()
            if "compare_prompts_var" in self.editor_widgets:
                action_dict["compare_prompts"] = self.editor_widgets["compare_prompts_var"].get()
        elif self.current_tool == "snip_tool":
            action_dict["show_chat_window"] = self.editor_widgets["show_chat_var"].get()
            if "compare_prompts_var" in self.editor_widgets:
                action_dict["compare_prompts"] = self.editor_widgets["compare_prompts_var"].get()
        else:  # audio_tool
            action_dict["show_chat_window"] = self.editor_widgets["show_chat_var"].get()

        # Save connection profile (all tools)
        if "profile_var" in self.editor_widgets:
            profile_val = self.editor_widgets["profile_var"].get()
            if profile_val and profile_val != "(None)":
                action_dict["connection_profile"] = profile_val

        tool_data = self.options_data.setdefault(self.current_tool, {})
        tool_data[self.current_action] = action_dict

        # Refresh UI list to update icons
        self._refresh_action_list()

        if self.use_ctk:
            self.editor_widgets["save_status"].configure(
                text=f"✅ Saved '{self.current_action}'", text_color=self.colors.accent_green
            )
        else:
            self.editor_widgets["save_status"].configure(
                text=f"✅ Saved '{self.current_action}'", fg=self.colors.accent_green
            )
