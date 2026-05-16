#!/usr/bin/env python3
"""
Core Settings Window for AIPromptBridge.

Composes all tab mixins into a single SettingsWindow class.
Handles window lifecycle, save/reset logic, and threading.

Classes:
    SettingsWindow: Main settings window composing all tab mixins.
    AttachedSettingsWindow: Settings as child of GUICoordinator root.

Functions:
    create_attached_settings_window(): Factory for attached settings.
    show_settings_window(): Thread-safe shortcut to show settings.
"""

import os
import time
import threading
import queue
import tkinter as tk
from tkinter import messagebox
from typing import Dict, Optional, Any

from ...platform import HAVE_CTK, ctk
from ...themes import (
    ThemeColors, get_colors, sync_ctk_appearance,
    get_ctk_font, get_ctk_label_colors,
)
from ...core import get_next_window_id, register_window, unregister_window
from ...custom_widgets import upgrade_tabview_with_icons, create_emoji_button
from ..utils import set_window_icon

# Import emoji renderer for CTkImage support
try:
    from ...emoji_renderer import get_emoji_renderer, HAVE_PIL
    HAVE_EMOJI = HAVE_PIL and HAVE_CTK
except ImportError:
    HAVE_EMOJI = False
    get_emoji_renderer = None

# Local imports
from .config_io import ConfigData, parse_config_full, save_config_full
from .widgets import FormFieldsMixin
from .tab_general import GeneralTabMixin
from .tab_provider import ProviderTabMixin
from .tab_generation import GenerationTabMixin
from .tab_tools import ToolsTabMixin
from .tab_tts import TTSTabMixin
from .tab_keys import KeysTabMixin
from .tab_theme import ThemeTabMixin


def _can_use_ctk() -> bool:
    """Check if CustomTkinter can be safely used."""
    return HAVE_CTK


class SettingsWindow(
    FormFieldsMixin,
    GeneralTabMixin,
    ProviderTabMixin,
    GenerationTabMixin,
    ToolsTabMixin,
    TTSTabMixin,
    KeysTabMixin,
    ThemeTabMixin,
):
    """
    Standalone settings window using CustomTkinter.
    Composes all tab mixins for a modular, maintainable UI.
    """

    def __init__(self, master=None, on_close=None):
        self.window_id = get_next_window_id()
        self.window_tag = f"settings_{self.window_id}"

        self.master = master
        self.on_close_callback = on_close
        self.colors = get_colors()
        self.root = None
        self._destroyed = False

        # Config data
        self.config_data: Optional[ConfigData] = None
        self.original_config: Dict[str, Any] = {}

        # Widget references for saving
        self.widgets: Dict[str, Any] = {}
        self.vars: Dict[str, tk.Variable] = {}

        # Theme preview
        self.preview_frame: Optional[Any] = None

        # Queue for thread-safe callbacks (used when running standalone)
        self._callback_queue: queue.Queue = queue.Queue()

        # Determine if we can use CTk
        self.use_ctk = _can_use_ctk()

    def show(self, initial_tab: str = None):
        """
        Create and show the settings window.

        Args:
            initial_tab: Name of the tab to select initially (e.g. "API Keys")
        """
        if self.use_ctk:
            sync_ctk_appearance()

        # Load current config
        self.config_data = parse_config_full()
        self.original_config = dict(self.config_data.config)

        # Load from web_server if available (in-memory values)
        try:
            from .... import web_server
            for key, value in web_server.CONFIG.items():
                self.config_data.config[key] = value
            for key, value in web_server.AI_PARAMS.items():
                self.config_data.ai_params[key] = value
        except (ImportError, AttributeError):
            pass

        if self.master:
            if self.use_ctk:
                self.root = ctk.CTkToplevel(self.master)
                self.root.configure(fg_color=self.colors.bg)
            else:
                self.root = tk.Toplevel(self.master)
                self.root.configure(bg=self.colors.bg)
        else:
            if self.use_ctk:
                self.root = ctk.CTk()
                self.root.configure(fg_color=self.colors.bg)
            else:
                self.root = tk.Tk()
                self.root.configure(bg=self.colors.bg)

        self.root.title("AIPromptBridge Settings")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)

        set_window_icon(self.root)

        # Position window
        offset = (self.window_id % 3) * 30
        self.root.geometry(f"+{100 + offset}+{100 + offset}")

        # Main container
        main_container = ctk.CTkFrame(self.root, fg_color=self.colors.bg) if self.use_ctk else tk.Frame(self.root, bg=self.colors.bg)
        main_container.pack(fill="both", expand=True, padx=10, pady=5)

        # Title bar (pack first)
        self._create_title_bar(main_container)

        # Button bar (pack BEFORE notebook with side="bottom" to reserve space)
        self._create_button_bar(main_container)

        # Notebook (tabs) - pack last to fill remaining space
        self._create_notebook(main_container)

        # Select initial tab if specified
        if initial_tab and self.use_ctk:
            try:
                self.tabview.set(initial_tab)
            except ValueError:
                found = False
                known_tabs = list(self._tab_configs.keys())
                for tab_name in known_tabs:
                    if initial_tab in tab_name:
                        try:
                            self.tabview.set(tab_name)
                            found = True
                            break
                        except ValueError:
                            pass
                if not found:
                    print(f"[Settings] Could not find initial tab '{initial_tab}'")

        # Ensure content for the active tab is loaded
        if self.use_ctk:
            self._load_tab_content(self.tabview.get())

        # Register and bind
        register_window(self.window_tag)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind('<Escape>', lambda e: self._close())

        # Focus
        self.root.lift()
        self.root.focus_force()

        if self.root:
            self.root.report_callback_exception = self._handle_callback_error

        # Event loop (only if standalone)
        if not self.master:
            self._run_event_loop()

    def _handle_callback_error(self, exc, val, tb):
        """Handle exceptions in callbacks to suppress noise on exit."""
        import traceback
        err_msg = "".join(traceback.format_exception_only(exc, val))
        if "invalid command name" in err_msg:
            return
        print(f"Exception in Tkinter callback:\n{err_msg}")
        traceback.print_tb(tb)

    def _run_event_loop(self):
        """Run event loop without blocking other Tk instances."""
        try:
            while self.root is not None and not self._destroyed:
                try:
                    if not self.root.winfo_exists():
                        break
                    self.root.update()
                    self._process_callback_queue()
                    time.sleep(0.01)
                except tk.TclError:
                    break
        except Exception:
            pass
        finally:
            self._safe_destroy()

    def _process_callback_queue(self):
        """Process any pending callbacks from background threads."""
        try:
            while True:
                callback = self._callback_queue.get_nowait()
                if callback and callable(callback):
                    try:
                        callback()
                    except Exception as e:
                        print(f"[Settings] Error in queued callback: {e}")
        except queue.Empty:
            pass

    def _schedule_callback(self, callback):
        """
        Schedule a callback to run on the GUI thread.
        Works both when attached to master and when standalone.
        """
        if self._destroyed:
            return

        if self.master:
            try:
                from ...core import GUICoordinator

                def safe_wrapper():
                    if not self._destroyed:
                        try:
                            callback()
                        except tk.TclError:
                            pass

                GUICoordinator.get_instance().run_on_gui_thread(safe_wrapper)
            except Exception as e:
                print(f"[Settings] Failed to schedule callback via GUICoordinator: {e}")
        else:
            self._callback_queue.put(callback)

    def _create_title_bar(self, parent):
        """Create the title bar."""
        title_frame = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        title_frame.pack(fill="x", pady=(0, 10))

        if self.use_ctk:
            title_text = "⚙️ Settings"
            title_label_kwargs = {
                "text": title_text,
                "font": get_ctk_font(24, "bold"),
                "text_color": self.colors.fg
            }

            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                emoji_img = renderer.get_ctk_image("⚙️", size=32)
                if emoji_img:
                    title_label_kwargs["text"] = "Settings"
                    title_label_kwargs["image"] = emoji_img
                    title_label_kwargs["compound"] = "left"

            ctk.CTkLabel(title_frame, **title_label_kwargs).pack(side="left")

            ctk.CTkLabel(
                title_frame,
                text="Edit config.ini",
                font=get_ctk_font(14),
                **get_ctk_label_colors(self.colors, muted=True)
            ).pack(side="left", padx=(20, 0))
        else:
            tk.Label(title_frame, text="⚙️ Settings",
                    font=("Segoe UI", 16, "bold"),
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            tk.Label(title_frame, text="Edit config.ini",
                    font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))

    def _create_notebook(self, parent):
        """Create the tabbed notebook with lazy tab loading."""
        if self.use_ctk:
            self.tabview = ctk.CTkTabview(
                parent,
                fg_color=self.colors.bg,
                segmented_button_fg_color=self.colors.surface0,
                segmented_button_selected_color=self.colors.accent,
                segmented_button_selected_hover_color=self.colors.lavender,
                segmented_button_unselected_color=self.colors.surface0,
                segmented_button_unselected_hover_color=self.colors.surface1,
                text_color=self.colors.fg,
                corner_radius=8,
                command=self._on_tab_changed
            )
            self.tabview.pack(fill="both", expand=True, pady=(0, 2))

            # Tab configs: name -> (method_name, is_loaded)
            self._tab_configs = {
                "⚙️ General": ("_create_general_tab", False),
                "🌐 Provider": ("_create_provider_tab", False),
                "⚡ Generation": ("_create_generation_tab", False),
                "🔧 Tools": ("_create_tools_tab", False),
                "🗣️ TTS": ("_create_tts_tab", False),
                "🔑 API Keys": ("_create_keys_tab", False),
                "🎨 Theme": ("_create_theme_tab", False),
            }

            for tab_name in self._tab_configs.keys():
                self.tabview.add(tab_name)

            upgrade_tabview_with_icons(self.tabview)

            # Only create the first tab's content immediately
            self._load_tab_content("⚙️ General")
        else:
            from tkinter import ttk
            style = ttk.Style(self.root)
            style.theme_use('clam')
            self.tabview = ttk.Notebook(parent)
            self.tabview.pack(fill="both", expand=True, pady=(0, 2))

            tabs = ["General", "Provider", "Generation", "Tools", "TTS", "API Keys", "Theme"]
            frames = {}
            for tab_name in tabs:
                frame = tk.Frame(self.tabview, bg=self.colors.bg)
                self.tabview.add(frame, text=tab_name)
                frames[tab_name] = frame

            self._create_general_tab(frames["General"])
            self._create_provider_tab(frames["Provider"])
            self._create_generation_tab(frames["Generation"])
            self._create_tools_tab(frames["Tools"])
            self._create_tts_tab(frames["TTS"])
            self._create_keys_tab(frames["API Keys"])
            self._create_theme_tab(frames["Theme"])

    def _on_tab_changed(self):
        """Handle tab change event — lazy load tab content."""
        if not self.use_ctk or not hasattr(self, '_tab_configs'):
            return
        current_tab = self.tabview.get()
        self._load_tab_content(current_tab)

    def _load_tab_content(self, tab_name: str):
        """Load content for a tab if not already loaded."""
        if not hasattr(self, '_tab_configs') or tab_name not in self._tab_configs:
            return

        method_name, is_loaded = self._tab_configs[tab_name]
        if is_loaded:
            return

        self._tab_configs[tab_name] = (method_name, True)

        tab_frame = self.tabview.tab(tab_name)
        create_method = getattr(self, method_name, None)
        if create_method and callable(create_method):
            create_method(tab_frame)

    def _create_button_bar(self, parent):
        """Create the bottom button bar."""
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        btn_frame.pack(fill="x", side="bottom", pady=(5, 0))

        create_emoji_button(
            btn_frame, "Save", "💾", self.colors, "success", 120, 42, self._save
        ).pack(side="left", padx=6)

        create_emoji_button(
            btn_frame, "Cancel", "✖️", self.colors, "secondary", 110, 42, self._close
        ).pack(side="left", padx=6)

        if self.use_ctk:
            self.status_label = ctk.CTkLabel(
                btn_frame, text="", font=get_ctk_font(13),
                text_color=self.colors.accent_green
            )
        else:
            self.status_label = tk.Label(btn_frame, text="", font=("Segoe UI", 10),
                                        bg=self.colors.bg, fg=self.colors.accent_green)
        self.status_label.pack(side="left", padx=20)

        create_emoji_button(
            btn_frame, "Reset to Defaults", "🔄", self.colors, "danger", 160, 42, self._reset_to_defaults
        ).pack(side="right", padx=6)

    # =========================================================================
    # Save / Reset / Close
    # =========================================================================

    def _validate(self) -> tuple:
        """Validate all fields. Returns (is_valid, error_message)."""
        try:
            port_var = self.vars.get("port")
            if port_var:
                port = int(port_var.get())
                if port < 1 or port > 65535:
                    return False, "Port must be between 1 and 65535"
        except ValueError:
            return False, "Port must be a number"
        return True, ""

    def _save(self):
        """Save all settings."""
        is_valid, error = self._validate()
        if not is_valid:
            messagebox.showerror("Validation Error", error, parent=self.root)
            return

        # Collect values from widgets
        for key, var in self.vars.items():
            if key in ["run_at_startup", "unlock_server_settings"]:
                continue

            try:
                value = var.get()
            except tk.TclError:
                value = self.widgets.get(f"{key}_default", "")

            # Handle spinbox fields
            if f"{key}_default" in self.widgets:
                try:
                    str_val = str(value).strip()
                    if str_val:
                        value = int(str_val)
                    else:
                        value = self.widgets[f"{key}_default"]
                except (ValueError, TypeError):
                    value = self.widgets[f"{key}_default"]

            # Handle port
            if key == "port":
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    value = 5000

            # Handle TTS voice (strip extra info)
            if key == "tts_default_voice" and isinstance(value, str) and " — " in value:
                value = value.split(" — ")[0]

            # Handle gemini_endpoint empty -> None
            if key == "gemini_endpoint" and isinstance(value, str) and not value.strip():
                value = None

            # Route ai_param_ prefixed keys to ai_params dict
            if hasattr(self, '_ai_param_keys') and key in self._ai_param_keys:
                param_name = key[len("ai_param_"):]
                str_val = str(value).strip() if value is not None else ""
                if str_val:
                    try:
                        if '.' in str_val:
                            self.config_data.ai_params[param_name] = float(str_val)
                        else:
                            self.config_data.ai_params[param_name] = int(str_val)
                    except ValueError:
                        self.config_data.ai_params[param_name] = str_val
                else:
                    self.config_data.ai_params.pop(param_name, None)
            else:
                self.config_data.config[key] = value

        # Save API keys via KeyStore (pool-based)
        if hasattr(self, '_save_keys_to_store'):
            self._save_keys_to_store()

        # Cleanup transient keys
        self.config_data.config.pop("run_at_startup", None)
        self.config_data.config.pop("unlock_server_settings", None)

        # Save to file
        if save_config_full(self.config_data):
            try:
                from .... import web_server
                for key, value in self.config_data.config.items():
                    web_server.CONFIG[key] = value

                # Hot-reload API keys from KeyStore
                try:
                    from ....key_store import KeyStore
                    key_store = KeyStore.get_instance()
                    web_server.KEY_MANAGERS = key_store.build_key_managers()
                    total_keys = sum(km.get_key_count() for km in web_server.KEY_MANAGERS.values())
                    print(f"[Settings] Reloaded API keys ({total_keys} total)")
                except Exception as e:
                    print(f"[Settings] Note: Could not hot-reload API keys: {e}")

                # Sync AI parameters
                web_server.AI_PARAMS.clear()
                web_server.AI_PARAMS.update(self.config_data.ai_params)
                if self.config_data.ai_params:
                    print(f"[Settings] AI params: {self.config_data.ai_params}")

                # Notify config change listeners
                from ....config import notify_config_change
                notify_config_change("_bulk_update")

            except (ImportError, AttributeError) as e:
                print(f"[Settings] Note: Could not update in-memory config: {e}")

            if self.use_ctk:
                self.status_label.configure(text="✅ Settings saved!", text_color=self.colors.accent_green)
            else:
                self.status_label.configure(text="✅ Settings saved!", fg=self.colors.accent_green)

            self.root.after(1500, self._close)
        else:
            if self.use_ctk:
                self.status_label.configure(text="❌ Failed to save", text_color=self.colors.accent_red)
            else:
                self.status_label.configure(text="❌ Failed to save", fg=self.colors.accent_red)

    def _reset_to_defaults(self):
        """Reset configuration to default values after confirmation."""
        from ....config import DEFAULT_CONFIG

        confirm = messagebox.askyesno(
            "Reset to Defaults",
            "Are you sure you want to reset all settings to their default values?\n\n"
            "This will NOT delete your API keys, but all other settings will be restored to defaults.\n\n"
            "⚠️ This action cannot be undone!",
            icon="warning",
            parent=self.root
        )

        if not confirm:
            return

        try:
            for key, default_value in DEFAULT_CONFIG.items():
                self.config_data.config[key] = default_value

                if key in self.vars:
                    var = self.vars[key]
                    if isinstance(var, tk.BooleanVar):
                        var.set(default_value if isinstance(default_value, bool) else False)
                    elif isinstance(var, tk.StringVar):
                        if isinstance(default_value, (int, float)):
                            var.set(str(default_value))
                        else:
                            var.set(str(default_value) if default_value is not None else "")

            # Clear AI parameters
            self.config_data.ai_params.clear()
            if hasattr(self, '_ai_param_keys'):
                for ap_key in self._ai_param_keys:
                    if ap_key in self.vars:
                        self.vars[ap_key].set("")

            # Update theme preview if available
            if self.preview_frame:
                self._update_theme_preview()

            if self.use_ctk:
                self.status_label.configure(text="🔄 Reset to defaults. Click Save to apply.", text_color=self.colors.accent_yellow)
            else:
                self.status_label.configure(text="🔄 Reset to defaults. Click Save to apply.", fg=self.colors.accent_yellow)

            print("[Settings] Configuration reset to defaults. Save to apply changes.")

        except Exception as e:
            print(f"[Settings] Error resetting to defaults: {e}")
            if self.use_ctk:
                self.status_label.configure(text=f"❌ Reset failed: {e}", text_color=self.colors.accent_red)
            else:
                self.status_label.configure(text=f"❌ Reset failed: {e}", fg=self.colors.accent_red)

    def _safe_destroy(self):
        """Safely destroy the window and cleanup."""
        try:
            if self.root:
                try:
                    import sys
                    import contextlib

                    @contextlib.contextmanager
                    def start_suppress_stderr():
                        old_stderr = sys.stderr
                        sys.stderr = open(os.devnull, "w")
                        try:
                            yield
                        finally:
                            sys.stderr.close()
                            sys.stderr = old_stderr

                    with start_suppress_stderr():
                        if self.root.winfo_exists():
                            self.root.destroy()
                except Exception:
                    try:
                        self.root.destroy()
                    except Exception:
                        pass
        except Exception:
            pass
        self.root = None
        unregister_window(self.window_tag)

    def _close(self):
        """Close the settings window."""
        self._destroyed = True

        if self.on_close_callback:
            try:
                self.on_close_callback()
            except Exception as e:
                print(f"[Settings] Error in on_close callback: {e}")

        if self.master:
            self._safe_destroy()


# =============================================================================
# Entry Points
# =============================================================================

class AttachedSettingsWindow:
    """
    Settings window as Toplevel attached to GUICoordinator's root.
    Used for centralized GUI threading.
    """

    def __init__(self, parent_root, on_close=None, initial_tab=None):
        self.parent_root = parent_root
        settings = SettingsWindow(master=parent_root, on_close=on_close)
        settings.show(initial_tab=initial_tab)


def create_attached_settings_window(parent_root, on_close=None, initial_tab=None):
    """Create a settings window (called on GUI thread)."""
    AttachedSettingsWindow(parent_root, on_close, initial_tab)


def show_settings_window():
    """Show settings window - can be called from any thread."""
    def run():
        settings = SettingsWindow()
        settings.show()

    threading.Thread(target=run, daemon=True).start()
