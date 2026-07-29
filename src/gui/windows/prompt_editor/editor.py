#!/usr/bin/env python3
"""
Core Prompt Editor Window for AIPromptBridge.

Composes all tab mixins into the main PromptEditorWindow class.
Handles window lifecycle, tab routing, save/reset/close operations.
"""

import copy
import json
import queue
import threading
import time
import tkinter as tk
from typing import Any, Dict, Optional

from ...core import get_next_window_id, register_window, unregister_window
from ...custom_widgets import create_emoji_button, upgrade_tabview_with_icons
from ...platform import HAVE_CTK, ctk
from ...themes import (
    ThemeColors,
    get_colors,
    get_ctk_button_colors,
    get_ctk_font,
    get_ctk_label_colors,
    sync_ctk_appearance,
)
from ..utils import set_window_icon
from .data import load_options, save_options
from .tab_actions import ActionsTabMixin
from .tab_groups import GroupsTabMixin
from .tab_modifiers import ModifiersTabMixin
from .tab_playground import PlaygroundTabMixin
from .tab_settings import SettingsTabMixin
from .tab_tts_playground import TTSPlaygroundMixin

# Import emoji renderer for CTkImage support (Windows color emoji fix)
try:
    from ...emoji_renderer import HAVE_PIL, get_emoji_renderer

    HAVE_EMOJI = HAVE_PIL and HAVE_CTK
except ImportError:
    HAVE_EMOJI = False
    get_emoji_renderer = None


# =============================================================================
# Prompt Editor Window (CTk version)
# =============================================================================


class PromptEditorWindow(
    ActionsTabMixin,
    SettingsTabMixin,
    ModifiersTabMixin,
    GroupsTabMixin,
    PlaygroundTabMixin,
    TTSPlaygroundMixin,
):
    """
    Standalone prompt editor window using CustomTkinter.
    Composed from tab mixins for modularity.
    """

    def __init__(self, master=None):
        self.window_id = get_next_window_id()
        self.window_tag = f"prompt_editor_{self.window_id}"

        self.master = master
        self.colors = get_colors()
        self.root = None  # type: ignore
        self._destroyed = False

        # Data
        self.options_data: Dict = {}
        self.current_tool: str = "text_edit_tool"  # Default tool
        self.current_action: Optional[str] = None

        # Playground image data
        self.playground_image_base64: Optional[str] = None
        self.playground_image_mime: Optional[str] = None
        self.playground_image_name: Optional[str] = None

        # Queue for thread-safe updates
        self.queue = queue.Queue()

        # Widget references
        self.action_listbox = None
        self.editor_widgets: Dict[str, Any] = {}

        # Determine if we can use CTk (must be in main thread)
        self.use_ctk = HAVE_CTK

        # Unsaved changes tracking
        self._saved_options_snapshot: Optional[str] = None
        self._saved_settings_snapshot: Optional[Dict[str, Any]] = None

    def show(self):
        """Create and show the prompt editor window."""
        # Only sync CTk if we can use it
        if self.use_ctk:
            sync_ctk_appearance()

        # Load current options
        self.options_data = load_options()

        if self.master:
            # Attached mode - child window
            if self.use_ctk:
                self.root = ctk.CTkToplevel(self.master)
                self.root.configure(fg_color=self.colors.bg)
            else:
                self.root = tk.Toplevel(self.master)
                self.root.configure(bg=self.colors.bg)
        else:
            # Standalone mode - root window
            if self.use_ctk:
                self.root = ctk.CTk()
                self.root.configure(fg_color=self.colors.bg)
            else:
                self.root = tk.Tk()
                self.root.configure(bg=self.colors.bg)

        if self.use_ctk:
            try:
                from ...ctk_bootstrap import ensure_ctk_window_ready

                ensure_ctk_window_ready(self.root)
            except Exception:
                pass

        self.root.title("AIPromptBridge Prompt Editor")
        self.root.geometry("1000x825")
        self.root.minsize(900, 600)

        # Set icon
        set_window_icon(self.root)

        # Position window
        offset = (self.window_id % 3) * 30
        self.root.geometry(f"+{80 + offset}+{80 + offset}")

        # Main container
        main_container = (
            ctk.CTkFrame(self.root, fg_color=self.colors.bg) if self.use_ctk else tk.Frame(self.root, bg=self.colors.bg)
        )
        main_container.pack(fill="both", expand=True, padx=10, pady=5)

        # Title bar (pack first at top)
        self._create_title_bar(main_container)

        # Button bar (pack BEFORE main content with side="bottom" to reserve space)
        self._create_button_bar(main_container)

        # Main content with tabview - pack last to fill remaining space
        self._create_main_content(main_container)

        # Register and bind
        register_window(self.window_tag)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Escape>", lambda e: self._close())

        # Start queue polling
        self._check_queue_editor()

        # Focus
        self.root.lift()
        self.root.focus_force()

        # Take initial snapshot for unsaved changes tracking
        self._take_snapshot()

        # Event loop (only if standalone)
        if not self.master:
            self._run_event_loop()

    def _check_queue_editor(self):
        """Poll the queue for editor updates."""
        try:
            while True:
                task = self.queue.get_nowait()
                try:
                    task()
                except Exception as e:
                    print(f"Error in editor queue task: {e}")
        except queue.Empty:
            pass

        try:
            if self.root and self.root.winfo_exists():
                self.root.after(50, self._check_queue_editor)
        except Exception:
            pass

    def _run_event_loop(self):
        """Run event loop without blocking other Tk instances."""
        try:
            while self.root is not None and not self._destroyed:
                try:
                    if not self.root.winfo_exists():
                        break
                    self.root.update()
                    time.sleep(0.01)
                except tk.TclError:
                    break
        except Exception:
            pass

    def _take_snapshot(self):
        """Take a snapshot of current state for dirty comparison."""
        try:
            self._saved_options_snapshot = json.dumps(self.options_data, sort_keys=True, ensure_ascii=False)
        except Exception:
            self._saved_options_snapshot = None
        # Snapshot settings widgets if they exist
        if hasattr(self, "settings_widgets") and self.settings_widgets:
            self._saved_settings_snapshot = self._snapshot_settings_widgets()
        else:
            self._saved_settings_snapshot = {}

    def _snapshot_settings_widgets(self) -> dict:
        """Capture current settings widget values."""
        snapshot = {}
        if not hasattr(self, "settings_widgets"):
            return snapshot
        for widget_key, (widget_type, widget) in self.settings_widgets.items():
            try:
                if widget_type == "entry":
                    snapshot[widget_key] = widget.get()
                elif widget_type == "text":
                    if self.use_ctk:
                        snapshot[widget_key] = widget.get("0.0", "end").strip()
                    else:
                        snapshot[widget_key] = widget.get("1.0", "end").strip()
                elif widget_type == "int":
                    snapshot[widget_key] = widget.get()
                elif widget_type == "bool":
                    snapshot[widget_key] = widget.get()
            except Exception:
                pass
        return snapshot

    def _is_dirty(self) -> bool:
        """Check if options data or settings widgets have changed since last save/load."""
        if self._saved_options_snapshot is None:
            return False
        try:
            current = json.dumps(self.options_data, sort_keys=True, ensure_ascii=False)
            if current != self._saved_options_snapshot:
                return True
        except Exception:
            return False

        # Also check settings widgets (they don't mutate options_data until save)
        if hasattr(self, "_saved_settings_snapshot") and hasattr(self, "settings_widgets"):
            current_settings = self._snapshot_settings_widgets()
            if current_settings != self._saved_settings_snapshot:
                return True

        return False

    def _update_title(self):
        """Update title bar with dirty indicator."""
        if self._destroyed or not self.root:
            return
        try:
            indicator = "● " if self._is_dirty() else ""
            self.root.title(f"{indicator}AIPromptBridge Prompt Editor")
        except Exception:
            pass

    def _prompt_unsaved_if_dirty(self) -> bool:
        """Prompt user about unsaved changes. Returns True to proceed, False to abort."""
        if not self._is_dirty():
            return True
        from tkinter import messagebox

        result = messagebox.askyesnocancel(
            "Unsaved Changes",
            "You have unsaved changes to prompts configuration.\n\nSave changes before closing?",
            parent=self.root,
        )
        if result is True:  # Yes — save
            self._save_all()
            return True
        elif result is False:  # No — discard
            return True
        else:  # Cancel
            return False

    def _create_title_bar(self, parent):
        """Create the title bar."""
        title_frame = (
            ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        )
        title_frame.pack(fill="x", pady=(0, 10))

        if self.use_ctk:
            # Title with emoji image support
            title_text = "✏️ Prompt Editor"
            title_label_kwargs = {
                "text": title_text,
                "font": get_ctk_font(24, "bold"),
                **get_ctk_label_colors(self.colors),
            }

            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                emoji_img = renderer.get_ctk_image("✏️", size=32)
                if emoji_img:
                    title_label_kwargs["text"] = "Prompt Editor"
                    title_label_kwargs["image"] = emoji_img
                    title_label_kwargs["compound"] = "left"

            ctk.CTkLabel(title_frame, **title_label_kwargs).pack(side="left")

            ctk.CTkLabel(
                title_frame,
                text="Edit prompts.json",
                font=get_ctk_font(14),
                **get_ctk_label_colors(self.colors, muted=True),
            ).pack(side="left", padx=(20, 0))
        else:
            tk.Label(
                title_frame, text="✏️ Prompt Editor", font=("Segoe UI", 16, "bold"), bg=self.colors.bg, fg=self.colors.fg
            ).pack(side="left")
            tk.Label(
                title_frame,
                text="Edit prompts.json",
                font=("Segoe UI", 10),
                bg=self.colors.bg,
                fg=self.colors.blockquote,
            ).pack(side="left", padx=(15, 0))

    def _create_main_content(self, parent):
        """Create the main content area with tabview."""
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
                command=self._on_tab_changed,
            )
            self.tabview.pack(fill="both", expand=True, pady=(0, 2))

            # Lazy loading configuration
            self._tab_configs = {
                "⚡ Actions": ("_create_actions_tab", False),
                "📁 Groups": ("_create_groups_tab", False),
                "⚙️ Settings": ("_create_settings_tab", False),
                "🎛️ Modifiers": ("_create_modifiers_tab", False),
                "🧪 Playground": ("_create_playground_tab", False),
            }

            # Create tabs (empty initially)
            for tab_name in self._tab_configs.keys():
                self.tabview.add(tab_name)

            # Upgrade tabs with images and larger font
            upgrade_tabview_with_icons(self.tabview)

            # Load the first tab immediately
            first_tab = "⚡ Actions"
            self._load_tab_content(first_tab)
        else:
            # Fallback to ttk.Notebook
            from tkinter import ttk

            style = ttk.Style(self.root)
            style.theme_use("clam")
            self.tabview = ttk.Notebook(parent)
            self.tabview.pack(fill="both", expand=True, pady=(0, 2))

            actions_frame = tk.Frame(self.tabview, bg=self.colors.bg)
            groups_frame = tk.Frame(self.tabview, bg=self.colors.bg)
            settings_frame = tk.Frame(self.tabview, bg=self.colors.bg)
            modifiers_frame = tk.Frame(self.tabview, bg=self.colors.bg)
            playground_frame = tk.Frame(self.tabview, bg=self.colors.bg)

            self.tabview.add(actions_frame, text="Actions")
            self.tabview.add(groups_frame, text="Groups")
            self.tabview.add(settings_frame, text="Settings")
            self.tabview.add(modifiers_frame, text="Modifiers")
            self.tabview.add(playground_frame, text="🧪 Playground")

            self._create_actions_tab(actions_frame)
            self._create_groups_tab(groups_frame)
            self._create_settings_tab(settings_frame)
            self._create_modifiers_tab(modifiers_frame)
            self._create_playground_tab(playground_frame)

    def _on_tab_changed(self):
        """Handle tab change event - lazy load tab content."""
        if not self.use_ctk or not hasattr(self, "_tab_configs"):
            return

        current_tab = self.tabview.get()
        self._load_tab_content(current_tab)

    def _load_tab_content(self, tab_name: str):
        """Load content for a tab if not already loaded."""
        if not hasattr(self, "_tab_configs") or tab_name not in self._tab_configs:
            return

        method_name, is_loaded = self._tab_configs[tab_name]

        if is_loaded:
            return  # Already loaded

        # Mark as loaded first to prevent re-entry
        self._tab_configs[tab_name] = (method_name, True)

        # Get tab frame
        tab_frame = self.tabview.tab(tab_name)

        # Call creation method
        create_method = getattr(self, method_name, None)
        if create_method and callable(create_method):
            try:
                create_method(tab_frame)
            except Exception as e:
                print(f"[PromptEditor] Error loading tab '{tab_name}': {e}")
                import traceback

                traceback.print_exc()

        # Update settings snapshot to include newly created widgets
        if hasattr(self, "settings_widgets") and self.settings_widgets:
            self._saved_settings_snapshot = self._snapshot_settings_widgets()

    def _create_button_bar(self, parent):
        """Create the bottom button bar."""
        btn_frame = (
            ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        )
        # Pack with side="bottom" to ensure button bar is visible at all window sizes
        btn_frame.pack(fill="x", side="bottom", pady=(5, 0))

        create_emoji_button(btn_frame, "Save All", "💾", self.colors, "success", 140, 42, self._save_all).pack(
            side="left", padx=6
        )

        create_emoji_button(btn_frame, "Cancel", "✖️", self.colors, "secondary", 120, 42, self._close).pack(
            side="left", padx=6
        )

        create_emoji_button(
            btn_frame, "Reset to Defaults", "🔄", self.colors, "danger", 160, 42, self._reset_to_defaults
        ).pack(side="right", padx=6)

        if self.use_ctk:
            self.status_label = ctk.CTkLabel(
                btn_frame, text="", font=get_ctk_font(13), text_color=self.colors.accent_green
            )
        else:
            self.status_label = tk.Label(
                btn_frame, text="", font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.accent_green
            )
        self.status_label.pack(side="left", padx=20)

    def _save_all(self):
        """Save all options to file."""
        # Save settings from widgets
        if hasattr(self, "settings_widgets"):
            for widget_key, (widget_type, widget) in self.settings_widgets.items():
                if ":" in widget_key:
                    section, key = widget_key.split(":", 1)
                else:
                    section, key = "text_edit_tool", widget_key

                # Get the value
                val = None
                if widget_type == "entry":
                    val = widget.get()
                    if isinstance(val, str):
                        val = val.replace("\\n", "\n")
                elif widget_type == "text":
                    if self.use_ctk:
                        val = widget.get("0.0", "end").strip()
                    else:
                        val = widget.get("1.0", "end").strip()
                elif widget_type == "int":
                    val = widget.get()
                elif widget_type == "bool":
                    val = widget.get()

                # Update the data structure
                if val is not None:
                    if section == "global":
                        target = self.options_data.setdefault("_global_settings", {})
                    else:
                        section_data = self.options_data.setdefault(section, {})
                        target = section_data.setdefault("_settings", {})

                    # Track string modifications
                    if isinstance(val, str):
                        try:
                            from ...prompts import PromptsConfig

                            defaults = PromptsConfig.get_instance()._get_defaults()

                            if section == "global":
                                default_target = defaults.get("_global_settings", {})
                            else:
                                default_target = defaults.get(section, {}).get("_settings", {})

                            if key in default_target and isinstance(default_target[key], str):
                                modified_settings = target.setdefault("modified_settings", [])
                                if val != default_target[key]:
                                    if key not in modified_settings:
                                        modified_settings.append(key)
                                else:
                                    if key in modified_settings:
                                        modified_settings.remove(key)
                        except Exception as e:
                            print(f"[PromptEditor] Error tracking setting modification for '{key}': {e}")

                    target[key] = val

        # Save to file
        if save_options(self.options_data):
            if self.use_ctk:
                self.status_label.configure(text="✅ All options saved!", text_color=self.colors.accent_green)
            else:
                self.status_label.configure(text="✅ All options saved!", fg=self.colors.accent_green)

            print("[PromptEditor] Prompt configuration hot-reloaded")

            # Update snapshot after successful save
            self._take_snapshot()
            self.root.title("AIPromptBridge Prompt Editor")

            # Close after brief delay
            self.root.after(1000, self._close)
        else:
            if self.use_ctk:
                self.status_label.configure(text="❌ Failed to save", text_color=self.colors.accent_red)
            else:
                self.status_label.configure(text="❌ Failed to save", fg=self.colors.accent_red)

    def _reset_to_defaults(self):
        """Reset all prompts configuration to defaults in-memory. Requires Save All to persist."""
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Reset to Defaults",
            "This will reset ALL prompts, actions, modifiers, and settings to their default values.\n\n"
            "You will need to click 'Save All' to apply the changes to prompts.json.\n\n"
            "Are you sure you want to continue?",
            parent=self.root,
        ):
            return

        try:
            from ...prompts import get_prompts_config

            # Get fresh defaults WITHOUT saving to file
            config = get_prompts_config()
            self.options_data = config._get_defaults()

            # Clear current selection
            self.current_action = None

            # Reset all loaded tabs so they rebuild with new data
            if self.use_ctk and hasattr(self, "_tab_configs"):
                current_tab = self.tabview.get()

                for tab_name, (method_name, is_loaded) in list(self._tab_configs.items()):
                    if is_loaded:
                        # Destroy tab content
                        tab_frame = self.tabview.tab(tab_name)
                        for widget in tab_frame.winfo_children():
                            widget.destroy()
                        # Mark as not loaded
                        self._tab_configs[tab_name] = (method_name, False)

                # Reset widget references that tabs depend on
                self.action_listbox = None
                self.editor_widgets = {}
                if hasattr(self, "settings_widgets"):
                    self.settings_widgets = {}
                if hasattr(self, "modifier_listbox"):
                    self.modifier_listbox = None
                if hasattr(self, "modifier_widgets"):
                    self.modifier_widgets = {}
                if hasattr(self, "group_listbox"):
                    self.group_listbox = None
                if hasattr(self, "group_widgets"):
                    self.group_widgets = {}

                # Reload the current tab
                self._load_tab_content(current_tab)
            else:
                # Non-CTk fallback: refresh what we can
                if self.action_listbox:
                    self._refresh_action_list()
                self._clear_editor()

            # Update status - tell user to Save All
            if self.use_ctk:
                self.status_label.configure(
                    text="🔄 Reset to defaults. Click Save All to apply.", text_color=self.colors.accent_yellow
                )
            else:
                self.status_label.configure(
                    text="🔄 Reset to defaults. Click Save All to apply.", fg=self.colors.accent_yellow
                )

            print("[PromptEditor] Configuration reset to defaults in editor. Click Save All to apply.")
            self._update_title()

        except Exception as e:
            if self.use_ctk:
                self.status_label.configure(text=f"❌ Reset failed: {e}", text_color=self.colors.accent_red)
            else:
                self.status_label.configure(text=f"❌ Reset failed: {e}", fg=self.colors.accent_red)
            from tkinter import messagebox

            messagebox.showerror("Reset Failed", f"Failed to reset configuration: {e}", parent=self.root)

    def _close(self):
        """Close the prompt editor window."""
        if not self._prompt_unsaved_if_dirty():
            return  # User cancelled

        # Cleanup TTS recorder
        if hasattr(self, "tts_pg_recorder") and self.tts_pg_recorder:
            try:
                self.tts_pg_recorder.cleanup()
            except Exception:
                pass
            self.tts_pg_recorder = None

        self._destroyed = True
        unregister_window(self.window_tag)
        try:
            if self.root:
                self.root.destroy()
        except tk.TclError:
            pass
        self.root = None


# =============================================================================
# Wrapper Classes
# =============================================================================


class AttachedPromptEditorWindow:
    """
    Prompt editor window as Toplevel attached to GUICoordinator's root.
    Used for centralized GUI threading.
    """

    def __init__(self, parent_root):
        self.parent_root = parent_root
        # Run directly on GUI thread as a child window
        editor = PromptEditorWindow(master=parent_root)
        editor.show()


def create_attached_prompt_editor_window(parent_root):
    """Create a prompt editor window (called on GUI thread)."""
    AttachedPromptEditorWindow(parent_root)


def show_prompt_editor():
    """Show prompt editor window - can be called from any thread."""

    def run():
        editor = PromptEditorWindow()
        editor.show()

    threading.Thread(target=run, daemon=True).start()
