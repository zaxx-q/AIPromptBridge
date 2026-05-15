#!/usr/bin/env python3
"""
General tab mixin for Settings Window.

Sections:
    🖥️ Windows Startup — run at startup toggle + info
    🧠 Behavior — chat behavior, session settings, image format
    ⬆️ Updates — auto-check + check now button
    🖥️ Server Settings — locked host/port fields
"""

import tkinter as tk
from typing import Callable

from ...platform import HAVE_CTK, ctk
from ...themes import get_ctk_font, get_ctk_label_colors
from ...custom_widgets import create_section_header
from .widgets import ToggleSwitch, LABEL_WIDTH


class GeneralTabMixin:
    """Mixin providing the General tab for SettingsWindow."""

    def _create_general_tab(self, frame):
        """Create the General settings tab."""
        content = self._create_tab_scroll_frame(frame)

        # --- Windows Startup ---
        create_section_header(content, "🖥️ Windows Startup", self.colors)
        self._add_startup_toggle_field(content, "run_at_startup",
                               "Run at Windows startup",
                               hint="Launch AIPromptBridge when Windows starts")
        self._add_startup_info_label(content)

        # --- Behavior ---
        create_section_header(content, "🧠 Behavior", self.colors, top_padding=20)

        self._add_toggle_field(content, "show_ai_response_in_chat_window",
                               "Show AI response in chat window",
                               self.config_data.config.get("show_ai_response_in_chat_window", False),
                               hint="For direct chat popup and endpoint requests. Actions/modifiers override this.")

        self._add_toggle_field(content, "chat_use_origin_system_prompt",
                               "Use origin system prompt in chat",
                               self.config_data.config.get("chat_use_origin_system_prompt", True),
                               hint="Use the action's system prompt for follow-up messages instead of global one")

        self._add_toggle_field(content, "chat_message_bg_enabled",
                               "Chat message background coloring",
                               self.config_data.config.get("chat_message_bg_enabled", True),
                               hint="Enable colored backgrounds for user/assistant messages (disable for transparent)")

        self._add_toggle_field(content, "profile_selector_enabled",
                               "Use connection profiles in dropdowns",
                               self.config_data.config.get("profile_selector_enabled", True),
                               hint="When enabled and profiles are defined, model dropdowns show profile names instead of the full model list")

        # Session auto-save
        self._add_dropdown_field(content, "auto_save_session", "New session auto-creation:",
                                 self.config_data.config.get("auto_save_session", "on_attachment"),
                                 options=["on_attachment", "always_window", "on_followup"],
                                 size="md",
                                 hint="When to auto-create sessions. Sessions are ALWAYS saved on AI response or reply.\n"
                                      "• on_followup: Only when receiving AI response or sending reply\n"
                                      "• on_attachment: When chat window has attachments\n"
                                      "• always_window: Whenever a new chat window opens from Tools")

        # Max sessions
        self._add_spinbox_field(content, "max_sessions", "Max sessions:",
                               self.config_data.config.get("max_sessions", 200),
                               1, 1000, hint="Maximum chat sessions to keep")

        # Session image settings
        self._add_dropdown_field(content, "session_image_format", "Image format:",
                                 self.config_data.config.get("session_image_format", "webp"),
                                 options=["webp", "png", "jpg"], size="sm",
                                 hint="Storage format for chat attachments")

        self._add_spinbox_field(content, "session_image_quality", "Image quality (1-100):",
                               self.config_data.config.get("session_image_quality", 85),
                               1, 100, hint="Compression level for webp/jpg")

        # --- Updates ---
        create_section_header(content, "⬆️ Updates", self.colors, top_padding=20)

        self._add_toggle_field(content, "update_check_enabled",
                               "Check for updates on startup",
                               self.config_data.config.get("update_check_enabled", True),
                               hint="Automatically check GitHub for new versions at launch")

        # Check Now button + status label
        self._create_update_check_row(content)

        # --- Server Settings (locked) ---
        create_section_header(content, "🖥️ Server Settings", self.colors, top_padding=20)
        self._create_server_settings_section(content)

    def _create_update_check_row(self, parent):
        """Create the Check Now button and status label."""
        update_row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        update_row.pack(fill="x", pady=4)

        if self.use_ctk:
            from ...themes import get_ctk_button_colors
            check_btn = ctk.CTkButton(
                update_row, text="Check Now", width=120, height=32,
                font=get_ctk_font(13),
                fg_color=self.colors.accent,
                hover_color=self.colors.surface2,
                text_color="#ffffff",
                command=self._on_check_updates_now,
            )
            check_btn.pack(side="left")

            self._update_status_label = ctk.CTkLabel(
                update_row, text="", font=get_ctk_font(11),
                **get_ctk_label_colors(self.colors, muted=True)
            )
            self._update_status_label.pack(side="left", padx=(15, 0))
        else:
            check_btn = tk.Button(
                update_row, text="Check Now",
                font=("Segoe UI", 10),
                bg=self.colors.accent, fg="#ffffff",
                activebackground=self.colors.surface1,
                activeforeground="#ffffff",
                relief="flat", padx=12, pady=4,
                command=self._on_check_updates_now,
            )
            check_btn.pack(side="left")

            self._update_status_label = tk.Label(
                update_row, text="", font=("Segoe UI", 9),
                bg=self.colors.bg, fg=self.colors.blockquote
            )
            self._update_status_label.pack(side="left", padx=(15, 0))

        # Show cached update info if available
        try:
            from ....updater import get_cached_update_info
            cached = get_cached_update_info()
            if cached:
                self._update_status_label.configure(
                    text=f"⬆️ Update available: v{cached.version}"
                )
        except Exception:
            pass

    def _on_check_updates_now(self):
        """Handle the 'Check Now' button click in the Updates section."""
        if hasattr(self, '_update_status_label'):
            self._update_status_label.configure(text="Checking...")

        def _check_thread():
            try:
                from ....updater import check_for_update
                from ....utils import is_compiled
                from ....version import __version__

                info = check_for_update()

                def _update_ui():
                    if not hasattr(self, '_update_status_label'):
                        return
                    if info:
                        self._update_status_label.configure(
                            text=f"⬆️ v{info.version} available! "
                                 f"{'(compiled: can auto-update)' if is_compiled() else info.release_url}"
                        )
                    else:
                        self._update_status_label.configure(
                            text=f"✅ Up to date (v{__version__})"
                        )

                # Schedule UI update on main thread
                self._schedule_callback(_update_ui)

            except Exception as e:
                err_msg = str(e)
                def _show_error():
                    if hasattr(self, '_update_status_label'):
                        self._update_status_label.configure(text=f"❌ Check failed: {err_msg}")
                self._schedule_callback(_show_error)

        import threading
        threading.Thread(target=_check_thread, daemon=True).start()

    def _create_server_settings_section(self, parent):
        """Create server settings with unlock checkbox."""
        # Unlock checkbox
        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=(0, 5))

        self.vars["unlock_server_settings"] = tk.BooleanVar(master=self.root, value=False)

        if self.use_ctk:
            checkbox = ctk.CTkCheckBox(
                row, text="Unlock server settings (advanced)",
                variable=self.vars["unlock_server_settings"],
                font=get_ctk_font(13), text_color=self.colors.fg,
                checkbox_height=20, checkbox_width=20, corner_radius=6,
                fg_color=self.colors.accent, hover_color=self.colors.accent,
                command=self._on_server_settings_unlock
            )
            checkbox.pack(side="left")

            ctk.CTkLabel(row, text="⚠️ Port auto-switches if occupied. Restart required.",
                         font=get_ctk_font(11),
                         **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(15, 0))
        else:
            checkbox = tk.Checkbutton(
                row, text="Unlock server settings (advanced)",
                variable=self.vars["unlock_server_settings"],
                font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg,
                activebackground=self.colors.bg, activeforeground=self.colors.fg,
                selectcolor=self.colors.bg,
                command=self._on_server_settings_unlock
            )
            checkbox.pack(side="left")

            tk.Label(row, text="⚠️ Port auto-switches if occupied. Restart required.",
                    font=("Segoe UI", 9),
                    bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))

        # Host and Port fields
        self._add_entry_field(parent, "host", "Host:",
                             self.config_data.config.get("host", "127.0.0.1"), size="sm")

        self._add_entry_field(parent, "port", "Port:",
                             str(self.config_data.config.get("port", 5000)), size="sm")

        # Initially lock fields
        self._on_server_settings_unlock()

    def _on_server_settings_unlock(self):
        """Toggle enabled state of server settings fields."""
        unlocked = self.vars["unlock_server_settings"].get()
        state = "normal" if unlocked else "disabled"

        if "host" in self.widgets:
            self.widgets["host"].configure(state=state)
            if self.use_ctk:
                text_color = self.colors.fg if unlocked else self.colors.surface2
                self.widgets["host"].configure(text_color=text_color)

        if "port" in self.widgets:
            self.widgets["port"].configure(state=state)
            if self.use_ctk:
                text_color = self.colors.fg if unlocked else self.colors.surface2
                self.widgets["port"].configure(text_color=text_color)

    def _add_startup_toggle_field(self, parent, key: str, label: str, hint: str = None):
        """Add a startup toggle field that reads/writes to registry immediately."""
        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=4)

        # Read current startup state from registry
        try:
            from ....startup_manager import is_startup_enabled
            current_value = is_startup_enabled()
        except Exception:
            current_value = False

        self.vars[key] = tk.BooleanVar(master=self.root, value=current_value)

        if self.use_ctk:
            self.widgets[key] = ctk.CTkSwitch(
                row, text=label, variable=self.vars[key],
                font=get_ctk_font(13), text_color=self.colors.fg,
                fg_color=self.colors.surface2,
                progress_color=self.colors.accent,
                button_color="#ffffff",
                button_hover_color="#f0f0f0",
                command=self._on_startup_toggle
            )
            self.widgets[key].pack(side="left")

            if hint:
                ctk.CTkLabel(row, text=hint, font=get_ctk_font(11),
                            **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(15, 0))
        else:
            tk.Label(row, text=label, font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            toggle = ToggleSwitch(row, self.vars[key], self.colors, command=self._on_startup_toggle)
            toggle.pack(side="left", padx=(10, 0))
            self.widgets[key] = toggle

            if hint:
                tk.Label(row, text=hint, font=("Segoe UI", 9),
                        bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))

    def _on_startup_toggle(self):
        """Handle Windows startup toggle change immediately."""
        startup_key = "run_at_startup"
        if startup_key not in self.vars:
            return

        try:
            from ....startup_manager import set_startup
            enabled = self.vars[startup_key].get()
            success, message = set_startup(enabled)

            if not success and enabled:
                if self.use_ctk:
                    self.status_label.configure(text=f"❌ {message}", text_color=self.colors.accent_red)
                else:
                    self.status_label.configure(text=f"❌ {message}", fg=self.colors.accent_red)
                self.vars[startup_key].set(False)
            else:
                if self.use_ctk:
                    self.status_label.configure(text=f"✅ {message}", text_color=self.colors.accent_green)
                else:
                    self.status_label.configure(text=f"✅ {message}", fg=self.colors.accent_green)

        except Exception as e:
            print(f"[Settings] Startup toggle error: {e}")
            if self.use_ctk:
                self.status_label.configure(text=f"❌ Error: {e}", text_color=self.colors.accent_red)
            else:
                self.status_label.configure(text=f"❌ Error: {e}", fg=self.colors.accent_red)

    def _add_startup_info_label(self, parent):
        """Add an info label showing current startup target."""
        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=(0, 4))

        # Get startup info
        try:
            from ....startup_manager import get_startup_info
            info = get_startup_info()

            if info["path"]:
                mode_text = f" ({info['mode']} mode)" if info["mode"] else ""
                path_short = info["path"]
                if len(path_short) > 50:
                    path_short = "..." + path_short[-47:]
                info_text = f"Target: {path_short}{mode_text}"
            else:
                info_text = "Launcher not found (running in development mode?)"
        except Exception as e:
            info_text = f"Error: {e}"

        if self.use_ctk:
            ctk.CTkLabel(row, text=info_text, font=get_ctk_font(11),
                        **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(32, 0))
        else:
            tk.Label(row, text=info_text, font=("Segoe UI", 9),
                    bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(32, 0))
