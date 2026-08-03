#!/usr/bin/env python3
"""
Tools tab mixin for Settings Window.

Sections:
    ✏️ TextEditTool — enable, hotkeys (Windows) / IPC triggers (Linux)
    📸 ScreenSnip — enable, hotkey / trigger
    🎤 Audio Tool — enable, hotkey / trigger, device, loopback, level meter style
    ⌨️ Typing — typing delay and speed
"""

import tkinter as tk

from src.platform.detect import is_linux

from ...custom_widgets import create_section_header
from ...platform import HAVE_CTK, ctk
from ...themes import get_ctk_font, get_ctk_label_colors, get_tk_font


class ToolsTabMixin:
    """Mixin providing the Tools tab for SettingsWindow."""

    def _create_tools_tab(self, frame):
        """Create the Tools settings tab (TextEditTool + ScreenSnip + Audio + Typing)."""
        content = self._create_tab_scroll_frame(frame)
        linux = is_linux()

        if linux:
            self._add_linux_trigger_reference(content)

        # --- TextEditTool ---
        create_section_header(content, "✏️ TextEditTool", self.colors, top_padding=20 if linux else 0)

        self._add_toggle_field(
            content,
            "text_edit_tool_enabled",
            "Enable TextEditTool",
            self.config_data.config.get("text_edit_tool_enabled", True),
            hint="⚠️ Restart required",
        )

        if linux:
            self._add_linux_trigger_line(content, "textedit")
        else:
            self._add_entry_field(
                content,
                "text_edit_tool_hotkey",
                "Activation hotkey:",
                self.config_data.config.get("text_edit_tool_hotkey", "ctrl+space"),
                size="md",
                hint="⚠️ Restart required",
            )

            self._add_entry_field(
                content,
                "text_edit_tool_abort_hotkey",
                "Abort hotkey:",
                self.config_data.config.get("text_edit_tool_abort_hotkey", "escape"),
                size="md",
                hint="⚠️ Restart required",
            )

        self._add_toggle_field(
            content,
            "text_edit_slow_app_retry",
            "Slow app text capture retry",
            self.config_data.config.get("text_edit_slow_app_retry", False),
            hint="Enable for Obsidian/Anki/XMind if text capture fails. Adds delay when no text is selected.",
        )

        # --- ScreenSnip ---
        create_section_header(content, "📸 ScreenSnip", self.colors, top_padding=20)

        self._add_toggle_field(
            content,
            "screen_snip_enabled",
            "Enable ScreenSnip",
            self.config_data.config.get("screen_snip_enabled", True),
            hint="⚠️ Restart required",
        )

        if linux:
            self._add_linux_trigger_line(content, "snip")
        else:
            self._add_entry_field(
                content,
                "screen_snip_hotkey",
                "ScreenSnip hotkey:",
                self.config_data.config.get("screen_snip_hotkey", "ctrl+alt+x"),
                size="md",
                hint="⚠️ Restart required",
            )

        # --- Audio Tool ---
        create_section_header(content, "🎤 Audio Tool", self.colors, top_padding=20)

        self._add_toggle_field(
            content,
            "audio_tool_enabled",
            "Enable Audio Tool",
            self.config_data.config.get("audio_tool_enabled", True),
            hint="⚠️ Restart required",
        )

        if linux:
            self._add_linux_trigger_line(content, "audio")
        else:
            self._add_entry_field(
                content,
                "audio_tool_hotkey",
                "Audio Tool hotkey:",
                self.config_data.config.get("audio_tool_hotkey", "ctrl+alt+a"),
                size="md",
                hint="⚠️ Restart required",
            )

        self._add_entry_field(
            content,
            "audio_default_device",
            "Default device:",
            self.config_data.config.get("audio_default_device") or "default",
            size="lg",
            hint="Partial name match ('default' = system default)",
        )

        self._add_toggle_field(
            content,
            "audio_default_loopback",
            "Default to loopback (system audio)",
            self.config_data.config.get("audio_default_loopback", True),
            hint="Record what you hear instead of microphone",
        )

        self._add_dropdown_field(
            content,
            "audio_level_meter_style",
            "Level meter style:",
            self.config_data.config.get("audio_level_meter_style", "canvas"),
            options=["canvas", "progressbar"],
            size="sm",
            hint="Visual style of recording meter",
        )

        # --- Typing ---
        create_section_header(content, "⌨️ Typing", self.colors, top_padding=20)

        if self.use_ctk:
            ctk.CTkLabel(
                content,
                text="Controls typing speed when streaming AI responses into other applications via replace mode.\n0 = no limit (as fast as the server streams). Increase if apps get overwhelmed.",
                font=get_ctk_font(11),
                justify="left",
                **get_ctk_label_colors(self.colors, muted=True),
            ).pack(anchor="w", pady=(0, 8))
        else:
            tk.Label(
                content,
                text="Controls typing speed when streaming AI responses into other applications via replace mode.\n0 = no limit (as fast as the server streams). Increase if apps get overwhelmed.",
                font=get_tk_font(9),
                justify="left",
                bg=self.colors.bg,
                fg=self.colors.blockquote,
            ).pack(anchor="w", pady=(0, 8))

        self._add_spinbox_field(
            content,
            "streaming_typing_delay",
            "Typing speed cap (ms):",
            self.config_data.config.get("streaming_typing_delay", 0),
            0,
            100,
            hint="Delay per character. 0 = no limit. Useful if apps get overwhelmed by fast input.",
        )

    def _add_linux_trigger_reference(self, parent):
        """Read-only block listing IPC --trigger commands for compositor binds."""
        create_section_header(parent, "⌨️ IPC Triggers (Linux)", self.colors)

        intro = (
            "Global hotkeys are not registered on Wayland. Bind your compositor to a "
            "running instance (does not start the app). Full command list:"
        )
        if self.use_ctk:
            ctk.CTkLabel(
                parent,
                text=intro,
                font=get_ctk_font(11),
                justify="left",
                wraplength=560,
                **get_ctk_label_colors(self.colors, muted=True),
            ).pack(anchor="w", pady=(0, 6))
        else:
            tk.Label(
                parent,
                text=intro,
                font=get_tk_font(9),
                justify="left",
                wraplength=560,
                bg=self.colors.bg,
                fg=self.colors.blockquote,
            ).pack(anchor="w", pady=(0, 6))

        try:
            from ....startup_manager import (
                format_trigger_command_display,
                get_project_root,
                list_trigger_commands,
            )

            rows = list_trigger_commands()
            root = get_project_root()
        except Exception:
            rows = []
            root = None

        if rows:
            lines = []
            for name, _cmd in rows:
                # Short display form (source: uv run…; compiled: binary --trigger…)
                lines.append(f"  {name:<10}  {format_trigger_command_display(name)}")
            body = "\n".join(lines)
            if root is not None:
                example = format_trigger_command_display("textedit")
                body += f"\n\nProject root: {root}"
                body += f'\n\nniri example:\n  bind "Mod+Shift+T" {{ spawn-sh "cd {root} && {example}"; }}'
        else:
            body = "  (Could not resolve start command — check install / project root.)"

        if self.use_ctk:
            ctk.CTkLabel(
                parent,
                text=body,
                font=get_ctk_font(11),
                justify="left",
                **get_ctk_label_colors(self.colors, muted=True),
            ).pack(anchor="w", pady=(0, 4))
        else:
            tk.Label(
                parent,
                text=body,
                font=("Consolas", 9),
                justify="left",
                bg=self.colors.bg,
                fg=self.colors.blockquote,
            ).pack(anchor="w", pady=(0, 4))

    def _add_linux_trigger_line(self, parent, trigger: str):
        """Single muted line under a tool: Trigger: … --trigger <name>."""
        try:
            from ....startup_manager import format_trigger_command_display

            text = f"Trigger: {format_trigger_command_display(trigger)}"
        except Exception:
            text = f"Trigger: --trigger {trigger}"
        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=(0, 4))

        if self.use_ctk:
            ctk.CTkLabel(
                row,
                text=text,
                font=get_ctk_font(11),
                **get_ctk_label_colors(self.colors, muted=True),
            ).pack(side="left", padx=(0, 0))
        else:
            tk.Label(
                row,
                text=text,
                font=get_tk_font(9),
                bg=self.colors.bg,
                fg=self.colors.blockquote,
            ).pack(side="left")
