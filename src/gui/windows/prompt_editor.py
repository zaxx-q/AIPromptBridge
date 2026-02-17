#!/usr/bin/env python3
"""
Prompt Editor Window for AIPromptBridge

Provides a GUI for editing text_edit_tool_options.json without opening the file directly.
Features:
- Action list with add/delete/duplicate
- Action editor (icon, prompt_type, system_prompt, task)
- Settings editor for _settings object
- Modifier and group management
- Playground for testing prompts with live preview

CustomTkinter Migration: Uses CTk widgets for modern UI.
"""

import json
import os
import sys
import time
import shutil
import threading
import queue
import base64
import tkinter as tk
from tkinter import messagebox, filedialog
from typing import Dict, Optional, List, Callable, Any
from pathlib import Path
import pyperclip

import threading

from ..platform import HAVE_CTK, ctk
from ..prompts import PROMPTS_FILE, reload_prompts

# Note: For class definitions that inherit from ctk or tk, we use HAVE_CTK
# since inheritance is determined at import time. For runtime widget creation,
# call HAVE_CTK to check both availability AND main thread.

from ..themes import (
    ThemeRegistry, ThemeColors, get_colors, sync_ctk_appearance,
    get_ctk_button_colors, get_ctk_frame_colors, get_ctk_entry_colors,
    get_ctk_textbox_colors, get_ctk_combobox_colors, get_ctk_label_colors,
    get_ctk_font
)
from ..core import get_next_window_id, register_window, unregister_window
from ..custom_widgets import ScrollableButtonList, upgrade_tabview_with_icons, create_section_header, create_emoji_button, TkScrollableFrame
from .utils import set_window_icon

# Import emoji renderer for CTkImage support (Windows color emoji fix)
try:
    from ..emoji_renderer import get_emoji_renderer, HAVE_PIL
    HAVE_EMOJI = HAVE_PIL and HAVE_CTK
except ImportError:
    HAVE_EMOJI = False
    get_emoji_renderer = None


# =============================================================================
# JSON Parser/Writer
# =============================================================================

OPTIONS_FILE = PROMPTS_FILE


def load_options(filepath: str = PROMPTS_FILE) -> Dict:
    """
    Load and parse options JSON.
    Uses centralized PromptsConfig which handles defaults if file is missing.
    """
    from ..prompts import get_prompts_config
    try:
        # Simply get the config from PromptsConfig which handles loading/defaults
        return get_prompts_config()._config
    except Exception as e:
        print(f"[PromptEditor] Error loading options: {e}")
        return {}


def save_options(data: Dict, filepath: str = OPTIONS_FILE) -> bool:
    """
    Save options with proper formatting.
    Creates a backup before saving.
    
    Returns:
        True if save was successful
    """
    try:
        # Create backup
        if Path(filepath).exists():
            backup_path = filepath + ".bak"
            shutil.copy2(filepath, backup_path)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        # Reload prompts in the main app
        reload_prompts()
        
        return True
    except Exception as e:
        print(f"[PromptEditor] Error saving options: {e}")
        return False


# =============================================================================
# Emoji Picker (CTk version)
# =============================================================================

COMMON_EMOJIS = [
    "💡", "🧒", "🤙", "📋", "🔑", "✏", "✨", "📝", "🔄", "💼",
    "😊", "😎", "✂", "📊", "→", "💬", "(◕‿◕)", "⚡", "❓",
    "🎨", "📖", "🔧", "⚙️", "🔍", "💾", "📁", "✅", "❌", "⭐",
    "🚀", "💪", "🎯", "📌", "🔔", "💡", "🎉", "👍", "👎", "🤔"
]


class EmojiPicker(ctk.CTkToplevel if HAVE_CTK else tk.Toplevel):
    """Simple emoji picker popup - CTk version."""
    
    def __init__(self, parent, callback: Callable[[str], None], colors: ThemeColors):
        super().__init__(parent)
        self.callback = callback
        self.colors = colors
        self.use_ctk = HAVE_CTK
        
        self.title("Pick Icon")
        self.geometry("450x340")
        self.transient(parent)
        self.grab_set()
        
        if self.use_ctk:
            self.configure(fg_color=colors.bg)
        else:
            self.configure(bg=colors.bg)
        
        # Main frame
        main_frame = ctk.CTkFrame(self, fg_color=colors.bg) if self.use_ctk else tk.Frame(self, bg=colors.bg)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Grid of emojis
        emoji_frame = ctk.CTkFrame(main_frame, fg_color=colors.bg) if self.use_ctk else tk.Frame(main_frame, bg=colors.bg)
        emoji_frame.pack(fill="both", expand=True)
        
        cols = 10
        for i, emoji in enumerate(COMMON_EMOJIS):
            row = i // cols
            col = i % cols
            if self.use_ctk:
                img = None
                btn_text = emoji
                if HAVE_EMOJI:
                    renderer = get_emoji_renderer()
                    img = renderer.get_ctk_image(emoji, size=24)
                    if img:
                        btn_text = ""

                btn = ctk.CTkButton(
                    emoji_frame,
                    text=btn_text,
                    image=img,
                    font=get_ctk_font(18),
                    width=40,
                    height=36,
                    corner_radius=6,
                    **get_ctk_button_colors(colors, "secondary"),
                    command=lambda em=emoji: self._select(em)
                )
            else:
                btn = tk.Label(
                    emoji_frame,
                    text=emoji,
                    font=("Segoe UI", 18),
                    bg=colors.surface0,
                    fg=colors.fg,
                    width=3,
                    height=1,
                    cursor="hand2"
                )
                btn.bind('<Button-1>', lambda e, em=emoji: self._select(em))
            btn.grid(row=row, column=col, padx=3, pady=3)
        
        # Custom entry section
        custom_frame = ctk.CTkFrame(main_frame, fg_color=colors.bg) if self.use_ctk else tk.Frame(main_frame, bg=colors.bg)
        custom_frame.pack(fill="x", pady=(15, 0))
        
        if self.use_ctk:
            ctk.CTkLabel(
                custom_frame,
                text="Custom:",
                font=get_ctk_font(12),
                **get_ctk_label_colors(colors)
            ).pack(side="left")
            
            self.custom_entry = ctk.CTkEntry(
                custom_frame,
                width=100,
                font=get_ctk_font(14),
                **get_ctk_entry_colors(colors)
            )
            self.custom_entry.pack(side="left", padx=10)
            
            ctk.CTkButton(
                custom_frame,
                text="Use",
                font=get_ctk_font(11),
                width=60,
                **get_ctk_button_colors(colors, "primary"),
                command=self._use_custom
            ).pack(side="left")
        else:
            tk.Label(custom_frame, text="Custom:", font=("Segoe UI", 11),
                    bg=colors.bg, fg=colors.fg).pack(side="left")
            self.custom_entry = tk.Entry(custom_frame, width=12, font=("Segoe UI", 14),
                                        bg=colors.input_bg, fg=colors.fg)
            self.custom_entry.pack(side="left", padx=8)
            tk.Button(custom_frame, text="Use", command=self._use_custom,
                     bg=colors.accent, fg="#ffffff").pack(side="left")
    
    def _select(self, emoji: str):
        """Select an emoji."""
        self.callback(emoji)
        self.destroy()
    
    def _use_custom(self):
        """Use custom text as icon."""
        text = self.custom_entry.get().strip()
        if text:
            self.callback(text)
            self.destroy()


# =============================================================================
# Themed Input Dialog (CTk version)
# =============================================================================

class ThemedInputDialog(ctk.CTkToplevel if HAVE_CTK else tk.Toplevel):
    """Themed dialog for getting text input from user."""
    
    def __init__(self, parent, title: str, prompt: str, colors: ThemeColors):
        super().__init__(parent)
        self.colors = colors
        self.result = None
        self.use_ctk = HAVE_CTK
        
        self.title(title)
        self.geometry("400x180")
        self.transient(parent)
        self.grab_set()
        
        if self.use_ctk:
            self.configure(fg_color=colors.bg)
        else:
            self.configure(bg=colors.bg)
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 200
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 90
        self.geometry(f"+{x}+{y}")
        
        # Main frame
        main_frame = ctk.CTkFrame(self, fg_color=colors.bg) if self.use_ctk else tk.Frame(self, bg=colors.bg)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Prompt label
        if self.use_ctk:
            ctk.CTkLabel(
                main_frame,
                text=prompt,
                font=get_ctk_font(12),
                **get_ctk_label_colors(colors)
            ).pack(anchor="w", pady=(0, 10))
            
            self.entry = ctk.CTkEntry(
                main_frame,
                width=360,
                height=36,
                font=get_ctk_font(12),
                **get_ctk_entry_colors(colors)
            )
            self.entry.pack(fill="x", pady=(0, 15))
        else:
            tk.Label(main_frame, text=prompt, font=("Segoe UI", 11),
                    bg=colors.bg, fg=colors.fg).pack(anchor="w", pady=(0, 10))
            self.entry = tk.Entry(main_frame, font=("Segoe UI", 11),
                                 bg=colors.input_bg, fg=colors.fg, width=40)
            self.entry.pack(fill="x", pady=(0, 15), ipady=6)
        
        self.entry.focus_set()
        
        # Buttons
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent") if self.use_ctk else tk.Frame(main_frame, bg=colors.bg)
        btn_frame.pack()
        
        if self.use_ctk:
            ctk.CTkButton(
                btn_frame,
                text="OK",
                font=get_ctk_font(11),
                width=80,
                **get_ctk_button_colors(colors, "primary"),
                command=self._ok
            ).pack(side="left", padx=5)
            
            ctk.CTkButton(
                btn_frame,
                text="Cancel",
                font=get_ctk_font(11),
                width=80,
                **get_ctk_button_colors(colors, "secondary"),
                command=self._cancel
            ).pack(side="left", padx=5)
        else:
            tk.Button(btn_frame, text="OK", command=self._ok,
                     bg=colors.accent, fg="#ffffff").pack(side="left", padx=5)
            tk.Button(btn_frame, text="Cancel", command=self._cancel,
                     bg=colors.surface1, fg=colors.fg).pack(side="left", padx=5)
        
        # Bindings
        self.entry.bind('<Return>', lambda e: self._ok())
        self.bind('<Escape>', lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
    
    def _ok(self):
        """Accept the input."""
        self.result = self.entry.get().strip()
        self.destroy()
    
    def _cancel(self):
        """Cancel the dialog."""
        self.result = None
        self.destroy()


def ask_themed_string(parent, title: str, prompt: str, colors: ThemeColors) -> Optional[str]:
    """Show a themed input dialog and return the result."""
    dialog = ThemedInputDialog(parent, title, prompt, colors)
    parent.wait_window(dialog)
    return dialog.result


# =============================================================================
# Test Result Dialog (Streaming)
# =============================================================================

class TestResultDialog(ctk.CTkToplevel if HAVE_CTK else tk.Toplevel):
    """
    Streaming test result dialog.
    Supports real-time updates for text and thinking content.
    """
    
    def __init__(self, parent, colors):
        super().__init__(parent)
        self.colors = colors
        self.use_ctk = HAVE_CTK
        self.queue = queue.Queue()
        
        self.title("API Test Result")
        self.geometry("700x500")
        self.transient(parent)
        
        if self.use_ctk:
            self.configure(fg_color=colors.bg)
        else:
            self.configure(bg=colors.bg)
            
        # Main content area
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent") if self.use_ctk else tk.Frame(self, bg=colors.bg)
        self.main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Output text area
        if self.use_ctk:
            self.output_box = ctk.CTkTextbox(
                self.main_frame, font=get_ctk_font(12),
                **get_ctk_textbox_colors(colors)
            )
        else:
            self.output_box = tk.Text(
                self.main_frame, font=("Consolas", 10),
                bg=colors.surface0, fg=colors.fg, wrap="word"
            )
        self.output_box.pack(fill="both", expand=True, pady=(0, 10))
        
        # Tags for styling (Tk only, CTk doesn't support tags in same way yet)
        if not self.use_ctk:
            self.output_box.tag_config("thinking", foreground=colors.blockquote, font=("Consolas", 9, "italic"))
            self.output_box.tag_config("error", foreground=colors.accent_red)
        
        # Close button
        if self.use_ctk:
            ctk.CTkButton(
                self.main_frame, text="Close", font=get_ctk_font(11),
                width=100, **get_ctk_button_colors(colors, "primary"),
                command=self.destroy
            ).pack()
        else:
            tk.Button(
                self.main_frame, text="Close", font=("Segoe UI", 10),
                bg=colors.accent, fg="#ffffff",
                command=self.destroy
            ).pack()
            
        # State
        self.thinking_started = False
        
        # Start message
        self._safe_insert("Waiting for response...\n\n")
        
        # Start queue polling
        self._check_queue()
        
    def _check_queue(self):
        """Poll the queue for updates."""
        try:
            while True:
                task = self.queue.get_nowait()
                try:
                    task()
                except Exception as e:
                    print(f"Error in queue task: {e}")
        except queue.Empty:
            pass
        
        try:
            if self.winfo_exists():
                self.after(50, self._check_queue)
        except Exception:
            pass
            
    def append_text(self, text):
        """Append normal response text."""
        # If we were thinking, close the block now that we have text
        if self.thinking_started:
            self.end_thinking()
            
        self._safe_insert(text)
        
    def append_thinking(self, text):
        """Append thinking/reasoning text."""
        if not self.thinking_started:
            self._safe_insert("\n========== THINKING ==========\n", "thinking")
            self.thinking_started = True
            
        self._safe_insert(text, "thinking")
        
    def end_thinking(self):
        """Mark end of thinking."""
        if self.thinking_started:
             self._safe_insert("\n========== THINKING END ==========\n\n", "thinking")
             self.thinking_started = False
        
    def append_error(self, text):
        """Append error message."""
        self._safe_insert(f"\n[Error] {text}\n", "error")
        
    def _safe_insert(self, text, tag=None):
        """Thread-safe text insertion via queue."""
        def _update():
            try:
                if self.use_ctk:
                    self.output_box.insert("end", text)
                    self.output_box.see("end")
                else:
                    self.output_box.insert("end", text, tag)
                    self.output_box.see("end")
            except Exception:
                pass
        
        self.queue.put(_update)


# =============================================================================
# Prompt Editor Window (CTk version)
# =============================================================================

class PromptEditorWindow:
    """
    Standalone prompt editor window using CustomTkinter.
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
        
        self.root.title("AIPromptBridge Prompt Editor")
        self.root.geometry("1000x736")
        self.root.minsize(900, 600)
        
        # Set icon
        set_window_icon(self.root)
        
        # Position window
        offset = (self.window_id % 3) * 30
        self.root.geometry(f"+{80 + offset}+{80 + offset}")
        
        # Main container
        main_container = ctk.CTkFrame(self.root, fg_color=self.colors.bg) if self.use_ctk else tk.Frame(self.root, bg=self.colors.bg)
        main_container.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Title bar (pack first at top)
        self._create_title_bar(main_container)
        
        # Button bar (pack BEFORE main content with side="bottom" to reserve space)
        # This ensures the button bar is visible even at minimum window size
        self._create_button_bar(main_container)
        
        # Main content with tabview - pack last to fill remaining space
        self._create_main_content(main_container)
        
        # Register and bind
        register_window(self.window_tag)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind('<Escape>', lambda e: self._close())
        
        # Start queue polling
        self._check_queue_editor()

        # Focus
        self.root.lift()
        self.root.focus_force()
        
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
    
    def _create_title_bar(self, parent):
        """Create the title bar."""
        title_frame = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        title_frame.pack(fill="x", pady=(0, 10))
        
        if self.use_ctk:
            # Title with emoji image support
            title_text = "✏️ Prompt Editor"
            title_label_kwargs = {
                "text": title_text,
                "font": get_ctk_font(24, "bold"),
                **get_ctk_label_colors(self.colors)
            }
            
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                emoji_img = renderer.get_ctk_image("✏️", size=32)
                if emoji_img:
                    title_label_kwargs["text"] = "Prompt Editor"
                    title_label_kwargs["image"] = emoji_img
                    title_label_kwargs["compound"] = "left"

            ctk.CTkLabel(
                title_frame,
                **title_label_kwargs
            ).pack(side="left")
            
            ctk.CTkLabel(
                title_frame,
                text="Edit prompts.json",
                font=get_ctk_font(14),
                **get_ctk_label_colors(self.colors, muted=True)
            ).pack(side="left", padx=(20, 0))
        else:
            tk.Label(title_frame, text="✏️ Prompt Editor",
                    font=("Segoe UI", 16, "bold"),
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            tk.Label(title_frame, text="Edit prompts.json",
                    font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))
    
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
                command=self._on_tab_changed
            )
            self.tabview.pack(fill="both", expand=True, pady=(0, 2))
            
            # Lazy loading configuration
            # Format: "Tab Name": ("method_name", is_loaded_bool)
            self._tab_configs = {
                "⚡ Actions": ("_create_actions_tab", False),
                "📁 Groups": ("_create_groups_tab", False),
                "⚙️ Settings": ("_create_settings_tab", False),
                "🎛️ Modifiers": ("_create_modifiers_tab", False),
                "🧪 Playground": ("_create_playground_tab", False)
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
            style.theme_use('clam')
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
        if not hasattr(self, 'editor_widgets') or not self.editor_widgets:
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
        if not hasattr(self, 'prompt_type_frame'):
            return
            
        is_text_edit = self.current_tool == "text_edit_tool"
        is_snip = self.current_tool == "snip_tool"
        is_audio = self.current_tool == "audio_tool"
        
        # prompt_type: Text Edit only
        if is_text_edit:
            self.prompt_type_frame.pack(fill="x", pady=8)
        else:
            self.prompt_type_frame.pack_forget()
        
        # compare_prompts: Snip only
        if hasattr(self, 'compare_prompts_frame'):
            if is_snip:
                self.compare_prompts_frame.pack(fill="x", pady=10)
            else:
                self.compare_prompts_frame.pack_forget()
        
        # Update checkbox label based on tool (per user requirement)
        if hasattr(self, 'editor_widgets') and "show_chat" in self.editor_widgets:
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

    def _create_actions_tab(self, frame):
        """Create the Actions editing tab."""
        # Container with left/right panes
        container = ctk.CTkFrame(frame, fg_color="transparent") if self.use_ctk else tk.Frame(frame, bg=self.colors.bg)
        container.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Left panel: action list (fixed width)
        left_panel = ctk.CTkFrame(container, fg_color="transparent", width=260) if self.use_ctk else tk.Frame(container, bg=self.colors.bg, width=260)
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
                text_color_disabled=self.colors.surface2
            )
            self.tool_switcher.set("Text Edit Tool")
            self.tool_switcher.pack(fill="x", pady=(0, 10))
        
        # List container - using ScrollableButtonList
        if self.use_ctk:
            self.action_listbox = ScrollableButtonList(
                left_panel, self.colors, command=self._on_action_select,
                corner_radius=8, fg_color=self.colors.input_bg
            )
        else:
            self.action_listbox = ScrollableButtonList(
                left_panel, self.colors, command=self._on_action_select,
                bg=self.colors.input_bg
            )
        self.action_listbox.pack(fill="both", expand=True)
        
        # Populate action list moved to end
        
        # Action buttons
        btn_frame = ctk.CTkFrame(left_panel, fg_color="transparent") if self.use_ctk else tk.Frame(left_panel, bg=self.colors.bg)
        btn_frame.pack(fill="x", pady=(12, 0))
        
        # Buttons using shared helper
        create_emoji_button(btn_frame, "Add", "➕", self.colors, "success", 70, 34, self._add_action).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "", "📋", self.colors, "secondary", 40, 34, self._duplicate_action).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "", "🗑️", self.colors, "danger", 40, 34, self._delete_action).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "⬆", "", self.colors, "secondary", 40, 34, self._move_action_up).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "⬇", "", self.colors, "secondary", 40, 34, self._move_action_down).pack(side="left", padx=3)
        
        # Right panel: action editor
        right_panel = ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=self.colors.bg)
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
        row_frame = ctk.CTkFrame(editor_scroll, fg_color="transparent") if self.use_ctk else tk.Frame(editor_scroll, bg=self.colors.bg)
        row_frame.pack(fill="x", pady=8)
        
        if self.use_ctk:
            ctk.CTkLabel(row_frame, text="Name:", font=get_ctk_font(13), width=120, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.editor_widgets["name"] = ctk.CTkLabel(
                row_frame, text="(select an action)", font=get_ctk_font(13, "bold"),
                **get_ctk_label_colors(self.colors)
            )
        else:
            tk.Label(row_frame, text="Name:", font=("Segoe UI", 10), width=12, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.editor_widgets["name"] = tk.Label(row_frame, text="(select an action)",
                                                   font=("Segoe UI", 10, "bold"),
                                                   bg=self.colors.bg, fg=self.colors.fg)
        self.editor_widgets["name"].pack(side="left", padx=(10, 0))
        
        # Icon field
        row_frame = ctk.CTkFrame(editor_scroll, fg_color="transparent") if self.use_ctk else tk.Frame(editor_scroll, bg=self.colors.bg)
        row_frame.pack(fill="x", pady=8)
        
        if self.use_ctk:
            ctk.CTkLabel(row_frame, text="Icon:", font=get_ctk_font(13), width=120, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.editor_widgets["icon_var"] = tk.StringVar(master=self.root)
            self.editor_widgets["icon_entry"] = ctk.CTkEntry(
                row_frame, textvariable=self.editor_widgets["icon_var"],
                font=get_ctk_font(16), width=70, height=34, **get_ctk_entry_colors(self.colors)
            )
            self.editor_widgets["icon_entry"].pack(side="left", padx=(12, 8))
            ctk.CTkButton(
                row_frame, text="Pick...", font=get_ctk_font(13),
                width=80, height=34, **get_ctk_button_colors(self.colors, "secondary"),
                command=self._pick_icon
            ).pack(side="left")
        else:
            tk.Label(row_frame, text="Icon:", font=("Segoe UI", 10), width=12, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.editor_widgets["icon_var"] = tk.StringVar(master=self.root)
            self.editor_widgets["icon_entry"] = tk.Entry(
                row_frame, textvariable=self.editor_widgets["icon_var"],
                font=("Segoe UI", 12), width=5, bg=self.colors.input_bg, fg=self.colors.fg
            )
            self.editor_widgets["icon_entry"].pack(side="left", padx=(10, 5))
            tk.Button(row_frame, text="Pick...", font=("Segoe UI", 9),
                     bg=self.colors.surface1, fg=self.colors.fg,
                     command=self._pick_icon).pack(side="left")
        
        # Prompt type dropdown (Text Edit Tool only)
        self.prompt_type_frame = ctk.CTkFrame(editor_scroll, fg_color="transparent") if self.use_ctk else tk.Frame(editor_scroll, bg=self.colors.bg)
        self.prompt_type_frame.pack(fill="x", pady=8)
        
        if self.use_ctk:
            ctk.CTkLabel(self.prompt_type_frame, text="Type:", font=get_ctk_font(13), width=120, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.editor_widgets["prompt_type_var"] = tk.StringVar(master=self.root, value="edit")
            self.editor_widgets["prompt_type"] = ctk.CTkComboBox(
                self.prompt_type_frame, variable=self.editor_widgets["prompt_type_var"],
                values=["edit", "general"], width=180, height=34, state="readonly",
                font=get_ctk_font(13), **get_ctk_combobox_colors(self.colors)
            )
            self.editor_widgets["prompt_type"].pack(side="left", padx=(12, 0))
        else:
            from tkinter import ttk
            tk.Label(self.prompt_type_frame, text="Type:", font=("Segoe UI", 10), width=12, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.editor_widgets["prompt_type_var"] = tk.StringVar(master=self.root, value="edit")
            self.editor_widgets["prompt_type"] = ttk.Combobox(
                self.prompt_type_frame, textvariable=self.editor_widgets["prompt_type_var"],
                values=["edit", "general"], state="readonly", width=15
            )
            self.editor_widgets["prompt_type"].pack(side="left", padx=(10, 0))
        
        # System prompt (multiline)
        row_frame = ctk.CTkFrame(editor_scroll, fg_color="transparent") if self.use_ctk else tk.Frame(editor_scroll, bg=self.colors.bg)
        row_frame.pack(fill="x", pady=8)
        
        if self.use_ctk:
            ctk.CTkLabel(row_frame, text="System Prompt:", font=get_ctk_font(13), anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(anchor="w")
            self.editor_widgets["system_prompt"] = ctk.CTkTextbox(
                row_frame, height=140, font=get_ctk_font(12),
                **get_ctk_textbox_colors(self.colors)
            )
            self.editor_widgets["system_prompt"].pack(fill="x", pady=(8, 0))
        else:
            tk.Label(row_frame, text="System Prompt:", font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w")
            self.editor_widgets["system_prompt"] = tk.Text(
                row_frame, font=("Consolas", 10), height=6,
                bg=self.colors.input_bg, fg=self.colors.fg, wrap="word"
            )
            self.editor_widgets["system_prompt"].pack(fill="x", pady=(5, 0))
        
        # Task field
        row_frame = ctk.CTkFrame(editor_scroll, fg_color="transparent") if self.use_ctk else tk.Frame(editor_scroll, bg=self.colors.bg)
        row_frame.pack(fill="x", pady=8)
        
        if self.use_ctk:
            ctk.CTkLabel(row_frame, text="Task:", font=get_ctk_font(13), width=120, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.editor_widgets["task_var"] = tk.StringVar()
            self.editor_widgets["task"] = ctk.CTkEntry(
                row_frame, textvariable=self.editor_widgets["task_var"],
                font=get_ctk_font(13), height=34, **get_ctk_entry_colors(self.colors)
            )
            self.editor_widgets["task"].pack(side="left", fill="x", expand=True, padx=(12, 0))
        else:
            tk.Label(row_frame, text="Task:", font=("Segoe UI", 10), width=12, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.editor_widgets["task_var"] = tk.StringVar()
            self.editor_widgets["task"] = tk.Entry(
                row_frame, textvariable=self.editor_widgets["task_var"],
                font=("Segoe UI", 10), bg=self.colors.input_bg, fg=self.colors.fg
            )
            self.editor_widgets["task"].pack(side="left", fill="x", expand=True, padx=(10, 0))
        
        # Show in chat checkbox (label varies by tool)
        self.show_chat_frame = ctk.CTkFrame(editor_scroll, fg_color="transparent") if self.use_ctk else tk.Frame(editor_scroll, bg=self.colors.bg)
        self.show_chat_frame.pack(fill="x", pady=10)
        
        self.editor_widgets["show_chat_var"] = tk.BooleanVar()
        if self.use_ctk:
            self.editor_widgets["show_chat"] = ctk.CTkCheckBox(
                self.show_chat_frame, text="Show response in chat window instead of typing/replacing text",
                variable=self.editor_widgets["show_chat_var"],
                font=get_ctk_font(13), text_color=self.colors.fg,
                fg_color=self.colors.accent
            )
        else:
            self.editor_widgets["show_chat"] = tk.Checkbutton(
                self.show_chat_frame, text="Show response in chat window instead of typing/replacing text",
                variable=self.editor_widgets["show_chat_var"],
                font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg,
                selectcolor=self.colors.input_bg
            )
        self.editor_widgets["show_chat"].pack(anchor="w")
        
        # Compare prompts checkbox (Snip Tool only)
        self.compare_prompts_frame = ctk.CTkFrame(editor_scroll, fg_color="transparent") if self.use_ctk else tk.Frame(editor_scroll, bg=self.colors.bg)
        # Initially hidden - shown only for snip_tool
        
        self.editor_widgets["compare_prompts_var"] = tk.BooleanVar()
        if self.use_ctk:
            self.editor_widgets["compare_prompts"] = ctk.CTkCheckBox(
                self.compare_prompts_frame, text="Compare mode (expects 2 images)",
                variable=self.editor_widgets["compare_prompts_var"],
                font=get_ctk_font(13), text_color=self.colors.fg,
                fg_color=self.colors.accent
            )
        else:
            self.editor_widgets["compare_prompts"] = tk.Checkbutton(
                self.compare_prompts_frame, text="Compare mode (expects 2 images)",
                variable=self.editor_widgets["compare_prompts_var"],
                font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg,
                selectcolor=self.colors.input_bg
            )
        self.editor_widgets["compare_prompts"].pack(anchor="w")
        
        # Save action button
        btn_frame = ctk.CTkFrame(editor_scroll, fg_color="transparent") if self.use_ctk else tk.Frame(editor_scroll, bg=self.colors.bg)
        btn_frame.pack(fill="x", pady=(18, 0))
        
        create_emoji_button(
            btn_frame, "Save Action", "💾", self.colors, "success", 150, 40, self._save_current_action
        ).pack(side="left")

        if self.use_ctk:
            self.editor_widgets["save_status"] = ctk.CTkLabel(
                btn_frame, text="", font=get_ctk_font(12),
                text_color=self.colors.accent_green
            )
        else:
            self.editor_widgets["save_status"] = tk.Label(
                btn_frame, text="", font=("Segoe UI", 9),
                bg=self.colors.bg, fg=self.colors.accent_green
            )
        self.editor_widgets["save_status"].pack(side="left", padx=15)
        
        # Populate action list after widgets are created
        self._refresh_action_list()
    
    def _create_settings_tab(self, frame):
        """Create the Settings tab for _settings object."""
        if self.use_ctk:
            scroll_container = ctk.CTkScrollableFrame(frame, fg_color="transparent")
            scroll_frame = scroll_container
        else:
            scroll_container = TkScrollableFrame(frame, bg_color=self.colors.bg)
            scroll_frame = scroll_container.scrollable_frame
        scroll_container.pack(fill="both", expand=True, padx=15, pady=15)
        
        self.settings_widgets = {}
        
        # --- Helper for creating settings rows ---
        def add_setting_row(section_key, key, label, multiline=False, override_val=None):
            row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
            row.pack(fill="x", pady=8)
            
            if self.use_ctk:
                ctk.CTkLabel(row, text=f"{label}:", font=get_ctk_font(12),
                            **get_ctk_label_colors(self.colors)).pack(anchor="w")
            else:
                tk.Label(row, text=f"{label}:", font=("Segoe UI", 10),
                        bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w")
            
            # Get value
            if section_key == "global":
                val = self.options_data.get("_global_settings", {}).get(key, "")
            else:
                val = self.options_data.get(section_key, {}).get("_settings", {}).get(key, "")
            
            if override_val is not None:
                val = override_val

            widget_key = f"{section_key}:{key}"

            if multiline:
                if self.use_ctk:
                    widget = ctk.CTkTextbox(row, height=100, font=get_ctk_font(12),
                                           **get_ctk_textbox_colors(self.colors))
                else:
                    widget = tk.Text(row, height=4, font=("Consolas", 9),
                                    bg=self.colors.input_bg, fg=self.colors.fg, wrap="word")
                widget.pack(fill="x", pady=(2, 0))
                
                if self.use_ctk:
                    widget.insert("0.0", str(val))
                else:
                    widget.insert("1.0", str(val))
                self.settings_widgets[widget_key] = ("text", widget)
            else:
                var = tk.StringVar(master=scroll_frame, value=str(val))
                if self.use_ctk:
                    widget = ctk.CTkEntry(row, textvariable=var, font=get_ctk_font(12), height=34,
                                         **get_ctk_entry_colors(self.colors))
                else:
                    widget = tk.Entry(row, textvariable=var, font=("Segoe UI", 10),
                                     bg=self.colors.input_bg, fg=self.colors.fg)
                widget.pack(fill="x", pady=(2, 0))
                self.settings_widgets[widget_key] = ("entry", var)

        # =====================================================================
        # Global Settings
        # =====================================================================
        create_section_header(scroll_frame, "Global Settings", self.colors, "🌍")
        
        add_setting_row("global", "chat_window_system_instruction", "Chat Window System Instruction", True)

        # =====================================================================
        # Text Edit Tool Settings
        # =====================================================================
        if self.use_ctk: ctk.CTkFrame(scroll_frame, height=20, fg_color="transparent").pack()
        create_section_header(scroll_frame, "Text Edit Tool", self.colors, "✏️")
        
        tet_fields = [
            ("chat_system_instruction", "Direct Chat System Instruction", True),
            ("base_output_rules_edit", "Base Output Rules (Edit)", True),
            ("base_output_rules_general", "Base Output Rules (General)", True),
            ("text_delimiter", "Text Delimiter", False),
            ("text_delimiter_close", "Text Delimiter Close", False),
            ("custom_task_template", "Custom Task Template", False),
            ("ask_task_template", "Ask Task Template", False),
        ]
        for k, l, m in tet_fields:
            add_setting_row("text_edit_tool", k, l, m)
            
        # Popup settings for Text Edit
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=(8, 0))
        if self.use_ctk:
            ctk.CTkLabel(row, text="Popup Layout:", font=get_ctk_font(12, "bold"),
                        **get_ctk_label_colors(self.colors)).pack(anchor="w")
        else:
            tk.Label(row, text="Popup Layout:", font=("Segoe UI", 9, "bold"),
                    bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w")

        # Items per page
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=4)
        if self.use_ctk:
             ctk.CTkLabel(row, text="Items per page:", font=get_ctk_font(12),
                        **get_ctk_label_colors(self.colors)).pack(side="left")
        else:
             tk.Label(row, text="Items per page:", font=("Segoe UI", 10),
                     bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
        
        tet_val = self.options_data.get("text_edit_tool", {}).get("_settings", {}).get("popup_items_per_page", 6)
        tet_items_var = tk.IntVar(master=scroll_frame, value=tet_val)
        if self.use_ctk:
             tet_items_entry = ctk.CTkEntry(row, textvariable=tet_items_var, width=60, font=get_ctk_font(12),
                        **get_ctk_entry_colors(self.colors))
             tet_items_entry.pack(side="left", padx=10)
             ctk.CTkLabel(row, text="(only if groups disabled)", font=get_ctk_font(11),
                        **get_ctk_label_colors(self.colors, muted=True)).pack(side="left")
        else:
             tet_items_entry = tk.Entry(row, textvariable=tet_items_var, width=5)
             tet_items_entry.pack(side="left", padx=10)
             tk.Label(row, text="(only if groups disabled)", font=("Segoe UI", 8),
                     bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left")
        self.settings_widgets["text_edit_tool:popup_items_per_page"] = ("int", tet_items_var)

        # Use groups
        tet_grp_val = self.options_data.get("text_edit_tool", {}).get("_settings", {}).get("popup_use_groups", True)
        tet_grp_var = tk.BooleanVar(master=scroll_frame, value=tet_grp_val)
        
        def update_tet_items_state(*args):
            state = "disabled" if tet_grp_var.get() else "normal"
            tet_items_entry.configure(state=state)
            
        tet_grp_var.trace_add("write", update_tet_items_state)
        # Initial state
        update_tet_items_state()

        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=4)
        if self.use_ctk:
            ctk.CTkCheckBox(row, text="Use Groups", variable=tet_grp_var, font=get_ctk_font(12),
                           text_color=self.colors.fg, fg_color=self.colors.accent).pack(anchor="w")
        else:
            tk.Checkbutton(row, text="Use Groups", variable=tet_grp_var).pack(anchor="w")
        self.settings_widgets["text_edit_tool:popup_use_groups"] = ("bool", tet_grp_var)


        # =====================================================================
        # Snip Tool Settings
        # =====================================================================
        if self.use_ctk: ctk.CTkFrame(scroll_frame, height=20, fg_color="transparent").pack()
        create_section_header(scroll_frame, "Snip Tool", self.colors, "✂️")

        add_setting_row("snip_tool", "custom_task_template", "Custom Task Template", False)
        
        # Allow Text Edit Actions
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        allow_val = self.options_data.get("snip_tool", {}).get("_settings", {}).get("allow_text_edit_actions", True)
        allow_var = tk.BooleanVar(master=scroll_frame, value=allow_val)
        if self.use_ctk:
            ctk.CTkSwitch(row, text="Allow Text Edit Actions (show in Snip popup)", variable=allow_var,
                         font=get_ctk_font(12), fg_color=self.colors.surface2, progress_color=self.colors.accent,
                         text_color=self.colors.fg).pack(anchor="w")
        else:
            tk.Checkbutton(row, text="Allow Text Edit Actions", variable=allow_var).pack(anchor="w")
        self.settings_widgets["snip_tool:allow_text_edit_actions"] = ("bool", allow_var)
        
        # Popup settings for Snip
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=(8, 0))
        if self.use_ctk:
            ctk.CTkLabel(row, text="Popup Layout:", font=get_ctk_font(12, "bold"),
                        **get_ctk_label_colors(self.colors)).pack(anchor="w")
        else:
            tk.Label(row, text="Popup Layout:", font=("Segoe UI", 9, "bold"),
                    bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w")

        # Items per page
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=4)
        if self.use_ctk:
             ctk.CTkLabel(row, text="Items per page:", font=get_ctk_font(12),
                        **get_ctk_label_colors(self.colors)).pack(side="left")
        else:
             tk.Label(row, text="Items per page:", font=("Segoe UI", 10),
                     bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
        
        snip_val = self.options_data.get("snip_tool", {}).get("_settings", {}).get("popup_items_per_page", 6)
        snip_items_var = tk.IntVar(master=scroll_frame, value=snip_val)
        if self.use_ctk:
             snip_items_entry = ctk.CTkEntry(row, textvariable=snip_items_var, width=60, font=get_ctk_font(12),
                        **get_ctk_entry_colors(self.colors))
             snip_items_entry.pack(side="left", padx=10)
             ctk.CTkLabel(row, text="(only if groups disabled)", font=get_ctk_font(11),
                        **get_ctk_label_colors(self.colors, muted=True)).pack(side="left")
        else:
             snip_items_entry = tk.Entry(row, textvariable=snip_items_var, width=5)
             snip_items_entry.pack(side="left", padx=10)
             tk.Label(row, text="(only if groups disabled)", font=("Segoe UI", 8),
                     bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left")
        self.settings_widgets["snip_tool:popup_items_per_page"] = ("int", snip_items_var)

        # Use groups
        snip_grp_val = self.options_data.get("snip_tool", {}).get("_settings", {}).get("popup_use_groups", True)
        snip_grp_var = tk.BooleanVar(master=scroll_frame, value=snip_grp_val)
        
        def update_snip_items_state(*args):
            state = "disabled" if snip_grp_var.get() else "normal"
            snip_items_entry.configure(state=state)
            
        snip_grp_var.trace_add("write", update_snip_items_state)
        # Initial state
        update_snip_items_state()

        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=4)
        if self.use_ctk:
            ctk.CTkCheckBox(row, text="Use Groups", variable=snip_grp_var, font=get_ctk_font(12),
                           text_color=self.colors.fg, fg_color=self.colors.accent).pack(anchor="w")
        else:
            tk.Checkbutton(row, text="Use Groups", variable=snip_grp_var).pack(anchor="w")
        self.settings_widgets["snip_tool:popup_use_groups"] = ("bool", snip_grp_var)

        # =====================================================================
        # Audio Tool Settings
        # =====================================================================
        if self.use_ctk: ctk.CTkFrame(scroll_frame, height=20, fg_color="transparent").pack()
        create_section_header(scroll_frame, "Audio Tool", self.colors, "🎤")
        
        add_setting_row("audio_tool", "custom_task_template", "Custom Task Template", False)
        
        # Popup settings for Audio
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=(8, 0))
        if self.use_ctk:
            ctk.CTkLabel(row, text="Popup Layout:", font=get_ctk_font(12, "bold"),
                        **get_ctk_label_colors(self.colors)).pack(anchor="w")
        else:
            tk.Label(row, text="Popup Layout:", font=("Segoe UI", 9, "bold"),
                    bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w")

        # Items per page
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=4)
        if self.use_ctk:
             ctk.CTkLabel(row, text="Items per page:", font=get_ctk_font(12),
                        **get_ctk_label_colors(self.colors)).pack(side="left")
        else:
             tk.Label(row, text="Items per page:", font=("Segoe UI", 10),
                     bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
        
        audio_val = self.options_data.get("audio_tool", {}).get("_settings", {}).get("items_per_page", 6)
        audio_items_var = tk.IntVar(master=scroll_frame, value=audio_val)
        if self.use_ctk:
             audio_items_entry = ctk.CTkEntry(row, textvariable=audio_items_var, width=60, font=get_ctk_font(12),
                        **get_ctk_entry_colors(self.colors))
             audio_items_entry.pack(side="left", padx=10)
             ctk.CTkLabel(row, text="(only if groups disabled)", font=get_ctk_font(11),
                        **get_ctk_label_colors(self.colors, muted=True)).pack(side="left")
        else:
             audio_items_entry = tk.Entry(row, textvariable=audio_items_var, width=5)
             audio_items_entry.pack(side="left", padx=10)
             tk.Label(row, text="(only if groups disabled)", font=("Segoe UI", 8),
                     bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left")
        self.settings_widgets["audio_tool:items_per_page"] = ("int", audio_items_var)

        # Use groups (audio_tool is a window, not popup, so uses "use_groups")
        audio_grp_val = self.options_data.get("audio_tool", {}).get("_settings", {}).get("use_groups", True)
        audio_grp_var = tk.BooleanVar(master=scroll_frame, value=audio_grp_val)
        
        def update_audio_items_state(*args):
            state = "disabled" if audio_grp_var.get() else "normal"
            audio_items_entry.configure(state=state)
            
        audio_grp_var.trace_add("write", update_audio_items_state)
        # Initial state
        update_audio_items_state()

        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=4)
        if self.use_ctk:
            ctk.CTkCheckBox(row, text="Use Groups", variable=audio_grp_var, font=get_ctk_font(12),
                           text_color=self.colors.fg, fg_color=self.colors.accent).pack(anchor="w")
        else:
            tk.Checkbutton(row, text="Use Groups", variable=audio_grp_var).pack(anchor="w")
        self.settings_widgets["audio_tool:use_groups"] = ("bool", audio_grp_var)

        # =====================================================================
        # TTS Tool Settings
        # =====================================================================
        if self.use_ctk: ctk.CTkFrame(scroll_frame, height=20, fg_color="transparent").pack()
        create_section_header(scroll_frame, "TTS Tool", self.colors, "🔊")
        
        add_setting_row("tts_tool", "director_system_prompt", "Director System Prompt", True)
        add_setting_row("tts_tool", "director_task_template", "Director Task Template", True)
    
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
            # Use index as ID since key might change or be duplicate (though shouldn't)
            # Actually better to use key for lookup, but index for update?
            # Existing code used listbox index. Let's use index as ID string "0", "1"...
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
        
        # Save button
        create_emoji_button(
            right_panel, "Save Modifier", "💾", self.colors, "success", 160, 40, self._save_current_modifier
        ).pack(anchor="w", pady=(18, 0))
    
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
        left_panel = ctk.CTkFrame(container, fg_color="transparent", width=260) if self.use_ctk else tk.Frame(container, bg=self.colors.bg, width=260)
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
                text_color_disabled=self.colors.surface2
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
                left_panel, self.colors, command=self._on_group_select,
                corner_radius=8, fg_color=self.colors.input_bg
            )
        else:
            self.group_listbox = ScrollableButtonList(
                left_panel, self.colors, command=self._on_group_select,
                bg=self.colors.input_bg
            )
        self.group_listbox.pack(fill="both", expand=True)
        
        # Populate groups
        self._refresh_group_list()
        
        # Buttons
        btn_frame = ctk.CTkFrame(left_panel, fg_color="transparent") if self.use_ctk else tk.Frame(left_panel, bg=self.colors.bg)
        btn_frame.pack(fill="x", pady=(12, 0))
        
        create_emoji_button(btn_frame, "Add", "➕", self.colors, "success", 70, 34, self._add_group).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "", "🗑️", self.colors, "danger", 40, 34, self._delete_group).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "⬆", "", self.colors, "secondary", 40, 34, self._move_group_up).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "⬇", "", self.colors, "secondary", 40, 34, self._move_group_down).pack(side="left", padx=3)
        
        # Right panel: group editor
        right_panel = ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=self.colors.bg)
        right_panel.pack(side="left", fill="both", expand=True)
        
        create_section_header(right_panel, "Edit Group", self.colors, "✏️")
        
        self.group_widgets = {}
        
        # Name field
        row = ctk.CTkFrame(right_panel, fg_color="transparent") if self.use_ctk else tk.Frame(right_panel, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        if self.use_ctk:
            ctk.CTkLabel(row, text="Name:", font=get_ctk_font(13), width=100, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.group_widgets["name_var"] = tk.StringVar(master=self.root)
            ctk.CTkEntry(row, textvariable=self.group_widgets["name_var"],
                        font=get_ctk_font(13), width=240, height=34,
                        **get_ctk_entry_colors(self.colors)).pack(side="left", padx=(12, 0))
        else:
            tk.Label(row, text="Name:", font=("Segoe UI", 10), width=10, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.group_widgets["name_var"] = tk.StringVar()
            tk.Entry(row, textvariable=self.group_widgets["name_var"],
                    font=("Segoe UI", 10), width=25,
                    bg=self.colors.input_bg, fg=self.colors.fg).pack(side="left", padx=(10, 0))
        
        # Enabled checkbox
        row = ctk.CTkFrame(right_panel, fg_color="transparent") if self.use_ctk else tk.Frame(right_panel, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        self.group_widgets["enabled_var"] = tk.BooleanVar(value=True)
        if self.use_ctk:
            self.group_widgets["enabled_checkbox"] = ctk.CTkCheckBox(
                row, text="Enabled (show this group in the corresponding tool)",
                variable=self.group_widgets["enabled_var"],
                font=get_ctk_font(13), text_color=self.colors.fg,
                fg_color=self.colors.accent
            )
        else:
            self.group_widgets["enabled_checkbox"] = tk.Checkbutton(
                row, text="Enabled (show this group in the corresponding tool)",
                variable=self.group_widgets["enabled_var"],
                font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg,
                selectcolor=self.colors.input_bg
            )
        self.group_widgets["enabled_checkbox"].pack(anchor="w")
        
        # Items (one per line)
        row = ctk.CTkFrame(right_panel, fg_color="transparent") if self.use_ctk else tk.Frame(right_panel, bg=self.colors.bg)
        row.pack(fill="both", expand=True, pady=8)
        
        if self.use_ctk:
            ctk.CTkLabel(row, text="Items (one action name per line):", font=get_ctk_font(13),
                        **get_ctk_label_colors(self.colors)).pack(anchor="w")
            self.group_widgets["items"] = ctk.CTkTextbox(
                row, font=get_ctk_font(12),
                **get_ctk_textbox_colors(self.colors)
            )
        else:
            tk.Label(row, text="Items (one action name per line):", font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w")
            self.group_widgets["items"] = tk.Text(
                row, font=("Segoe UI", 10),
                bg=self.colors.input_bg, fg=self.colors.fg, wrap="word"
            )
        self.group_widgets["items"].pack(fill="both", expand=True, pady=(2, 0))
        
        # Save button
        create_emoji_button(
            right_panel, "Save Group", "💾", self.colors, "success", 150, 40, self._save_current_group
        ).pack(anchor="w", pady=(18, 0))
    
    def _create_playground_tab(self, frame):
        """Create the Playground tab for testing prompts."""
        container = ctk.CTkFrame(frame, fg_color="transparent") if self.use_ctk else tk.Frame(frame, bg=self.colors.bg)
        container.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Left panel: Configuration
        left_panel = ctk.CTkFrame(container, fg_color="transparent", width=450) if self.use_ctk else tk.Frame(container, bg=self.colors.bg, width=450)
        left_panel.pack(side="left", fill="y", padx=(0, 15))
        left_panel.pack_propagate(False)
        
        if self.use_ctk:
            scroll_container = ctk.CTkScrollableFrame(left_panel, fg_color="transparent")
            scroll_left = scroll_container
        else:
            scroll_container = TkScrollableFrame(left_panel, bg_color=self.colors.bg)
            scroll_left = scroll_container.scrollable_frame
        scroll_container.pack(fill="both", expand=True)
        
        # Mode selector
        create_section_header(scroll_left, "Mode", self.colors, "🎯")
        
        self.playground_mode_var = tk.StringVar(master=self.root, value="action_text")
        mode_frame = ctk.CTkFrame(scroll_left, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_left, bg=self.colors.bg)
        mode_frame.pack(anchor="w", pady=(0, 15))
        
        if self.use_ctk:
            ctk.CTkRadioButton(mode_frame, text="Text Action",
                              variable=self.playground_mode_var, value="action_text",
                              font=get_ctk_font(13), text_color=self.colors.fg,
                              fg_color=self.colors.accent,
                              command=self._on_playground_mode_change).pack(side="left", padx=(0, 15))
            ctk.CTkRadioButton(mode_frame, text="Snip Action",
                              variable=self.playground_mode_var, value="action_snip",
                              font=get_ctk_font(13), text_color=self.colors.fg,
                              fg_color=self.colors.accent,
                              command=self._on_playground_mode_change).pack(side="left", padx=(0, 15))
            ctk.CTkRadioButton(mode_frame, text="Audio Action",
                              variable=self.playground_mode_var, value="action_audio",
                              font=get_ctk_font(13), text_color=self.colors.fg,
                              fg_color=self.colors.accent,
                              command=self._on_playground_mode_change).pack(side="left")
        else:
            tk.Radiobutton(mode_frame, text="Text Action",
                          variable=self.playground_mode_var, value="action_text",
                          font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg,
                          command=self._on_playground_mode_change).pack(side="left", padx=(0, 15))
            tk.Radiobutton(mode_frame, text="Snip Action",
                          variable=self.playground_mode_var, value="action_snip",
                          font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg,
                          command=self._on_playground_mode_change).pack(side="left", padx=(0, 15))
            tk.Radiobutton(mode_frame, text="Audio Action",
                          variable=self.playground_mode_var, value="action_audio",
                          font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg,
                          command=self._on_playground_mode_change).pack(side="left")
        
        # Action config frame
        self.action_config_frame = ctk.CTkFrame(scroll_left, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_left, bg=self.colors.bg)
        self.action_config_frame.pack(fill="x", pady=(0, 10))
        
        if self.use_ctk:
            ctk.CTkLabel(self.action_config_frame, text="Select Action:", font=get_ctk_font(13),
                        **get_ctk_label_colors(self.colors)).pack(anchor="w", pady=(0, 8))
        else:
            tk.Label(self.action_config_frame, text="Select Action:", font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w", pady=(0, 5))
        
        self.playground_action_var = tk.StringVar()
        # Populated dynamically
        
        if self.use_ctk:
            self.playground_action_combo = ctk.CTkComboBox(
                self.action_config_frame, variable=self.playground_action_var,
                values=[], width=340, height=34, state="readonly", font=get_ctk_font(13),
                **get_ctk_combobox_colors(self.colors),
                command=lambda x: self._on_playground_action_change()
            )
        else:
            from tkinter import ttk
            self.playground_action_combo = ttk.Combobox(
                self.action_config_frame, textvariable=self.playground_action_var,
                values=[], state="readonly", width=35
            )
            self.playground_action_combo.bind('<<ComboboxSelected>>', self._on_playground_action_change)
        self.playground_action_combo.pack(anchor="w", pady=(0, 10))
        
        # Custom input (for custom actions)
        self.custom_input_frame = ctk.CTkFrame(self.action_config_frame, fg_color="transparent") if self.use_ctk else tk.Frame(self.action_config_frame, bg=self.colors.bg)
        # Initially hidden
        
        if self.use_ctk:
            ctk.CTkLabel(self.custom_input_frame, text="Custom Prompt:", font=get_ctk_font(12),
                        **get_ctk_label_colors(self.colors)).pack(anchor="w", pady=(0, 2))
            self.playground_custom_var = tk.StringVar()
            self.playground_custom_entry = ctk.CTkEntry(
                self.custom_input_frame, textvariable=self.playground_custom_var,
                font=get_ctk_font(12), height=32, **get_ctk_entry_colors(self.colors)
            )
            self.playground_custom_entry.pack(fill="x")
            self.playground_custom_entry.bind('<KeyRelease>', lambda e: self._update_playground_preview())
        else:
            tk.Label(self.custom_input_frame, text="Custom Prompt:", font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w", pady=(0, 2))
            self.playground_custom_var = tk.StringVar()
            self.playground_custom_entry = tk.Entry(
                self.custom_input_frame, textvariable=self.playground_custom_var,
                font=("Segoe UI", 10), bg=self.colors.input_bg, fg=self.colors.fg
            )
            self.playground_custom_entry.pack(fill="x")
            self.playground_custom_entry.bind('<KeyRelease>', lambda e: self._update_playground_preview())

        # Modifiers section
        if self.use_ctk:
            # Header with emoji image
            kwargs = {
                "text": " Modifiers:",
                "font": get_ctk_font(13),
                **get_ctk_label_colors(self.colors)
            }
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                img = renderer.get_ctk_image("🎛️", size=18)
                if img:
                    kwargs["image"] = img
                    kwargs["compound"] = "left"
            
            ctk.CTkLabel(self.action_config_frame, **kwargs).pack(anchor="w", pady=(8, 8))
            
            self.playground_mod_scroll = ctk.CTkScrollableFrame(
                self.action_config_frame, height=120, fg_color="transparent"
            )
            mod_scroll_target = self.playground_mod_scroll
        else:
            tk.Label(self.action_config_frame, text="🎛️ Modifiers:", font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w", pady=(8, 5))
            self.playground_mod_scroll = TkScrollableFrame(self.action_config_frame, bg_color=self.colors.bg)
            self.playground_mod_scroll.canvas.configure(height=120)
            mod_scroll_target = self.playground_mod_scroll.scrollable_frame
            
        self.playground_mod_scroll.pack(fill="x")
        
        # Populate modifier checkboxes
        self.playground_modifier_vars = {}
        settings = self.options_data.get("_global_settings", {})
        modifiers = settings.get("modifiers", [])
        
        for mod in modifiers:
            key = mod.get("key")
            label = mod.get("label", key)
            if key:
                var = tk.BooleanVar()
                self.playground_modifier_vars[key] = var
                
                if self.use_ctk:
                    ctk.CTkCheckBox(
                        mod_scroll_target, text=label, variable=var,
                        font=get_ctk_font(12), text_color=self.colors.fg,
                        fg_color=self.colors.accent,
                        command=self._update_playground_preview
                    ).pack(anchor="w", pady=3)
                else:
                    tk.Checkbutton(
                        mod_scroll_target, text=label, variable=var,
                        font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.fg,
                        selectcolor=self.colors.input_bg,
                        command=self._update_playground_preview
                    ).pack(anchor="w")

        # Snip Image Frame (inside action_config_frame, shown only for Snip mode)
        self.snip_image_frame = ctk.CTkFrame(self.action_config_frame, fg_color="transparent") if self.use_ctk else tk.Frame(self.action_config_frame, bg=self.colors.bg)
        # Initially hidden - shown only for action_snip mode
        
        if self.use_ctk:
            snip_img_header = None
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                snip_img_header = renderer.get_ctk_image("🖼️", size=18)
            ctk.CTkLabel(self.snip_image_frame, text=" Image for Snip Test:", image=snip_img_header, compound="left",
                        font=get_ctk_font(13), **get_ctk_label_colors(self.colors)).pack(anchor="w", pady=(8, 8))
        else:
            tk.Label(self.snip_image_frame, text="🖼️ Image for Snip Test:", font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w", pady=(5, 5))
        
        # Image container
        if self.use_ctk:
            self.image_container_frame = ctk.CTkFrame(
                self.snip_image_frame, fg_color=self.colors.surface0,
                corner_radius=6, border_width=1, border_color=self.colors.border
            )
        else:
            self.image_container_frame = tk.Frame(
                self.snip_image_frame, bg=self.colors.surface0,
                highlightbackground=self.colors.border, highlightthickness=1
            )
        self.image_container_frame.pack(fill="x", pady=(0, 10))
        
        self.playground_camera_icon = None
        if self.use_ctk:
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                self.playground_camera_icon = renderer.get_ctk_image("📷", size=48)

            self.image_drop_zone = ctk.CTkLabel(
                self.image_container_frame, text=" No image selected",
                image=self.playground_camera_icon, compound="top",
                font=get_ctk_font(13), text_color=self.colors.blockquote
            )
        else:
            self.image_drop_zone = tk.Label(
                self.image_container_frame, text="📷 No image selected",
                font=("Segoe UI", 10), bg=self.colors.surface0, fg=self.colors.blockquote
            )
        self.image_drop_zone.pack(fill="both", expand=True, padx=10, pady=20)
        
        # Image buttons
        btn_row = ctk.CTkFrame(self.snip_image_frame, fg_color="transparent") if self.use_ctk else tk.Frame(self.snip_image_frame, bg=self.colors.bg)
        btn_row.pack(fill="x", pady=(0, 10))
        
        create_emoji_button(btn_row, "Select", "📁", self.colors, "secondary", 90, 34, self._select_playground_image).pack(side="left", padx=3)
        create_emoji_button(btn_row, "Snip", "✂️", self.colors, "primary", 90, 34, self._snip_playground_image).pack(side="left", padx=3)
        create_emoji_button(btn_row, "Paste", "📋", self.colors, "secondary", 90, 34, self._paste_playground_image).pack(side="left", padx=3)
        create_emoji_button(btn_row, "Clear", "🗑️", self.colors, "danger", 80, 34, self._clear_playground_image).pack(side="left", padx=3)
        
        # Audio Recording Frame (inside action_config_frame, shown only for Audio mode)
        self.audio_record_frame = ctk.CTkFrame(self.action_config_frame, fg_color="transparent") if self.use_ctk else tk.Frame(self.action_config_frame, bg=self.colors.bg)
        # Initially hidden - shown only for action_audio mode
        
        if self.use_ctk:
            audio_header_img = None
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                audio_header_img = renderer.get_ctk_image("🎙️", size=18)
            ctk.CTkLabel(self.audio_record_frame, text=" Audio Recording:", image=audio_header_img, compound="left",
                        font=get_ctk_font(13), **get_ctk_label_colors(self.colors)).pack(anchor="w", pady=(8, 8))
        else:
            tk.Label(self.audio_record_frame, text="🎙️ Audio Recording:", font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w", pady=(5, 5))
        
        # Device selection row
        device_row = ctk.CTkFrame(self.audio_record_frame, fg_color="transparent") if self.use_ctk else tk.Frame(self.audio_record_frame, bg=self.colors.bg)
        device_row.pack(fill="x", pady=(0, 8))
        
        if self.use_ctk:
            ctk.CTkLabel(device_row, text="Device:", font=get_ctk_font(12), width=60,
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.playground_audio_device_var = tk.StringVar()
            self.playground_audio_device_combo = ctk.CTkComboBox(
                device_row, variable=self.playground_audio_device_var,
                values=["(Loading...)"], width=280, height=32, state="readonly",
                font=get_ctk_font(12), **get_ctk_combobox_colors(self.colors)
            )
            self.playground_audio_device_combo.pack(side="left", padx=(8, 8), fill="x", expand=True)
            
            # Refresh button
            refresh_img = None
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                refresh_img = renderer.get_ctk_image("🔄", size=16)
            ctk.CTkButton(device_row, text="", image=refresh_img, width=32, height=32,
                         **get_ctk_button_colors(self.colors, "secondary"),
                         command=self._refresh_audio_devices).pack(side="left")
        else:
            tk.Label(device_row, text="Device:", font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.playground_audio_device_var = tk.StringVar()
            from tkinter import ttk
            self.playground_audio_device_combo = ttk.Combobox(
                device_row, textvariable=self.playground_audio_device_var,
                values=["(Loading...)"], state="readonly", width=35
            )
            self.playground_audio_device_combo.pack(side="left", padx=(8, 8), fill="x", expand=True)
            tk.Button(device_row, text="🔄", command=self._refresh_audio_devices,
                     bg=self.colors.surface1, fg=self.colors.fg).pack(side="left")
        
        # Recording controls row
        record_row = ctk.CTkFrame(self.audio_record_frame, fg_color="transparent") if self.use_ctk else tk.Frame(self.audio_record_frame, bg=self.colors.bg)
        record_row.pack(fill="x", pady=(0, 8))
        
        self.playground_record_btn = create_emoji_button(record_row, "Record", "🔴", self.colors, "primary", 100, 36, self._toggle_playground_recording)
        self.playground_record_btn.pack(side="left", padx=(0, 8))
        
        # Duration label
        if self.use_ctk:
            self.playground_audio_duration = ctk.CTkLabel(record_row, text="00:00", font=get_ctk_font(14, "bold"),
                                                          text_color=self.colors.fg)
        else:
            self.playground_audio_duration = tk.Label(record_row, text="00:00", font=("Segoe UI", 12, "bold"),
                                                      bg=self.colors.bg, fg=self.colors.fg)
        self.playground_audio_duration.pack(side="left", padx=(0, 15))
        
        # Clear button
        self.playground_audio_clear_btn = create_emoji_button(record_row, "Clear", "🗑️", self.colors, "danger", 80, 36, self._clear_playground_audio)
        self.playground_audio_clear_btn.pack(side="left")
        
        # Audio status label
        if self.use_ctk:
            self.playground_audio_status = ctk.CTkLabel(self.audio_record_frame, text="No audio recorded",
                                                        font=get_ctk_font(12), text_color=self.colors.blockquote)
        else:
            self.playground_audio_status = tk.Label(self.audio_record_frame, text="No audio recorded",
                                                    font=("Segoe UI", 10), bg=self.colors.bg, fg=self.colors.blockquote)
        self.playground_audio_status.pack(anchor="w", pady=(0, 5))
        
        # Initialize audio state
        self.playground_audio_data = None
        self.playground_audio_mime = None
        self.playground_is_recording = False
        self.playground_recorder = None
        self.playground_record_start = None
        self.playground_audio_devices = []
        
        # Sample text container (for hiding/showing)
        self.sample_text_container = ctk.CTkFrame(scroll_left, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_left, bg=self.colors.bg)
        self.sample_text_container.pack(fill="x")
        
        if self.use_ctk:
            sample_img = None
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                sample_img = renderer.get_ctk_image("📄", size=18)

            ctk.CTkLabel(self.sample_text_container, text=" Sample Text:", image=sample_img, compound="left",
                        font=get_ctk_font(13), **get_ctk_label_colors(self.colors)).pack(anchor="w", pady=(12, 8))
            self.playground_sample_text = ctk.CTkTextbox(
                self.sample_text_container, height=120, font=get_ctk_font(12),
                **get_ctk_textbox_colors(self.colors)
            )
        else:
            tk.Label(self.sample_text_container, text="📄 Sample Text:", font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.fg).pack(anchor="w", pady=(10, 5))
            self.playground_sample_text = tk.Text(
                self.sample_text_container, height=5, font=("Segoe UI", 10),
                bg=self.colors.input_bg, fg=self.colors.fg, wrap="word"
            )
        self.playground_sample_text.pack(fill="x", pady=(0, 10))
        
        # Bind sample text changes
        if self.use_ctk:
            self.playground_sample_text.insert("0.0", "The quick brown fox jumps over the lazy dog.")
            self.playground_sample_text.bind('<KeyRelease>', lambda e: self._update_playground_preview())
        else:
            self.playground_sample_text.insert("1.0", "The quick brown fox jumps over the lazy dog.")
            self.playground_sample_text.bind('<KeyRelease>', lambda e: self._update_playground_preview())


    
        # API Settings section (below sample text)
        create_section_header(scroll_left, "API Settings", self.colors, "⚙️")
            
        api_frame = ctk.CTkFrame(scroll_left, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_left, bg=self.colors.bg)
        api_frame.pack(fill="x", pady=(0, 10))
        
        # Provider & Model
        if self.use_ctk:
            ctk.CTkLabel(api_frame, text="Provider:", font=get_ctk_font(12), width=80, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.playground_provider_var = tk.StringVar(value="google")
            ctk.CTkComboBox(
                api_frame, variable=self.playground_provider_var,
                values=["google", "openrouter", "custom"],
                width=130, height=32, state="readonly", font=get_ctk_font(12),
                **get_ctk_combobox_colors(self.colors)
            ).pack(side="left", padx=(8, 15))
            
            ctk.CTkLabel(api_frame, text="Model:", font=get_ctk_font(12), width=60, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.playground_model_var = tk.StringVar()
            ctk.CTkEntry(
                api_frame, textvariable=self.playground_model_var,
                font=get_ctk_font(12), height=32, **get_ctk_entry_colors(self.colors)
            ).pack(side="left", padx=(8, 0), fill="x", expand=True)
        else:
            tk.Label(api_frame, text="Provider:", font=("Segoe UI", 9),
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.playground_provider_var = tk.StringVar(value="google")
            ttk.Combobox(
                api_frame, textvariable=self.playground_provider_var,
                values=["google", "openrouter", "custom"],
                state="readonly", width=12
            ).pack(side="left", padx=(5, 10))
            
            tk.Label(api_frame, text="Model:", font=("Segoe UI", 9),
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.playground_model_var = tk.StringVar()
            tk.Entry(
                api_frame, textvariable=self.playground_model_var,
                font=("Segoe UI", 9), bg=self.colors.input_bg, fg=self.colors.fg, width=15
            ).pack(side="left", padx=(5, 0), fill="x", expand=True)

        # Load defaults
        try:
            from ...config import load_config
            config, _, _, _ = load_config()
            default_provider = config.get("default_provider", "google")
            self.playground_provider_var.set(default_provider)
            self.playground_model_var.set(config.get(f"{default_provider}_model", ""))
        except:
            pass

        # Test button
        btn_frame = ctk.CTkFrame(scroll_left, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_left, bg=self.colors.bg)
        btn_frame.pack(fill="x", pady=(10, 0))
        
        if self.use_ctk:
            test_text = "🧪 Test with API"
            test_img = None
            
            # Initialize status icons cache
            self.status_icons = {}
            
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                test_img = renderer.get_ctk_image("🧪", size=20)
                if test_img:
                    test_text = "Test with API"
                
                # Pre-cache status icons to prevent GC/TclError
                self.status_icons["loading"] = renderer.get_ctk_image("⏳", size=16)
                self.status_icons["success"] = renderer.get_ctk_image("✅", size=16)

            ctk.CTkButton(btn_frame, text=test_text, image=test_img,
                         compound="left" if test_img else None,
                         font=get_ctk_font(14),
                         width=160, height=42, **get_ctk_button_colors(self.colors, "primary"),
                         command=self._test_playground_with_api).pack(side="left", padx=(0, 15))
            self.playground_test_status = ctk.CTkLabel(btn_frame, text="", font=get_ctk_font(12),
                                                       text_color=self.colors.fg)
        else:
            tk.Button(btn_frame, text="🧪 Test with API", font=("Segoe UI", 10),
                     bg=self.colors.accent, fg="#ffffff",
                     command=self._test_playground_with_api).pack(side="left", padx=(0, 10))
            self.playground_test_status = tk.Label(btn_frame, text="", font=("Segoe UI", 9),
                                                   bg=self.colors.bg, fg=self.colors.fg)
        self.playground_test_status.pack(side="left")
        
        # Right panel: Preview
        right_panel = ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=self.colors.bg)
        right_panel.pack(side="left", fill="both", expand=True)
        
        # System prompt preview
        sys_header = ctk.CTkFrame(right_panel, fg_color="transparent") if self.use_ctk else tk.Frame(right_panel, bg=self.colors.bg)
        sys_header.pack(fill="x", pady=(0, 5))
        
        if self.use_ctk:
            # Header with emoji image
            kwargs = {
                "text": " System Prompt Preview",
                "font": get_ctk_font(14, "bold"),
                "text_color": self.colors.accent
            }
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                img = renderer.get_ctk_image("📝", size=20)
                if img:
                    kwargs["image"] = img
                    kwargs["compound"] = "left"
                    
            ctk.CTkLabel(sys_header, **kwargs).pack(side="left")
            ctk.CTkButton(sys_header, text="Copy", font=get_ctk_font(12), width=80, height=30,
                         **get_ctk_button_colors(self.colors, "secondary"),
                         command=lambda: self._copy_preview("system")).pack(side="right")
            self.playground_system_preview = ctk.CTkTextbox(
                right_panel, font=get_ctk_font(12),
                state="disabled", **get_ctk_textbox_colors(self.colors)
            )
        else:
            tk.Label(sys_header, text="📝 System Prompt Preview", font=("Segoe UI", 11, "bold"),
                    bg=self.colors.bg, fg=self.colors.accent).pack(side="left")
            tk.Button(sys_header, text="📋 Copy", font=("Segoe UI", 8),
                     command=lambda: self._copy_preview("system")).pack(side="right")
            self.playground_system_preview = tk.Text(
                right_panel, font=("Consolas", 10),
                bg=self.colors.surface0, fg=self.colors.fg, wrap="word", state="disabled"
            )
        self.playground_system_preview.pack(fill="both", expand=True, pady=(0, 10))
        
        # User message preview
        user_header = ctk.CTkFrame(right_panel, fg_color="transparent") if self.use_ctk else tk.Frame(right_panel, bg=self.colors.bg)
        user_header.pack(fill="x", pady=(0, 5))
        
        if self.use_ctk:
             # Header with emoji image
            kwargs = {
                "text": " User Message Preview",
                "font": get_ctk_font(14, "bold"),
                "text_color": self.colors.accent
            }
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                img = renderer.get_ctk_image("💬", size=20)
                if img:
                    kwargs["image"] = img
                    kwargs["compound"] = "left"

            ctk.CTkLabel(user_header, **kwargs).pack(side="left")
            ctk.CTkButton(user_header, text="Copy", font=get_ctk_font(12), width=80, height=30,
                         **get_ctk_button_colors(self.colors, "secondary"),
                         command=lambda: self._copy_preview("user")).pack(side="right")
            self.playground_user_preview = ctk.CTkTextbox(
                right_panel, font=get_ctk_font(12),
                state="disabled", **get_ctk_textbox_colors(self.colors)
            )
        else:
            tk.Label(user_header, text="💬 User Message Preview", font=("Segoe UI", 11, "bold"),
                    bg=self.colors.bg, fg=self.colors.accent).pack(side="left")
            tk.Button(user_header, text="📋 Copy", font=("Segoe UI", 8),
                     command=lambda: self._copy_preview("user")).pack(side="right")
            self.playground_user_preview = tk.Text(
                right_panel, font=("Consolas", 10),
                bg=self.colors.surface0, fg=self.colors.fg, wrap="word", state="disabled"
            )
        self.playground_user_preview.pack(fill="both", expand=True)

        # Metadata Footer
        meta_frame = ctk.CTkFrame(right_panel, fg_color="transparent") if self.use_ctk else tk.Frame(right_panel, bg=self.colors.bg)
        meta_frame.pack(fill="x", pady=(10, 0))
        
        if self.use_ctk:
            meta_img = None
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                meta_img = renderer.get_ctk_image("📊", size=18)

            self.playground_meta_label = ctk.CTkLabel(
                meta_frame,
                text=" Tokens: ~0 | Type: edit | Mode: Replace",
                image=meta_img,
                compound="left",
                font=get_ctk_font(12),
                text_color=self.colors.blockquote
            )
        else:
            self.playground_meta_label = tk.Label(
                meta_frame,
                text="📊 Tokens: ~0 | Type: edit | Mode: Replace",
                font=("Segoe UI", 9),
                bg=self.colors.bg, fg=self.colors.blockquote
            )
        self.playground_meta_label.pack(anchor="w")
        
        # Initial preview update and population
        self._populate_playground_actions("action_text")
        self.root.after(100, self._update_playground_preview)
    
    def _populate_playground_actions(self, mode):
        """Populate the action combo box based on selected mode."""
        if mode == "action_text":
            tool_key = "text_edit_tool"
        elif mode == "action_snip":
            tool_key = "snip_tool"
        else:  # action_audio
            tool_key = "audio_tool"
        tool_data = self.options_data.get(tool_key, {})
        
        # Get actions (exclude _settings)
        actions = [k for k in sorted(tool_data.keys()) if k != "_settings"]
        
        if self.use_ctk:
            self.playground_action_combo.configure(values=actions)
            if actions:
                self.playground_action_combo.set(actions[0])
                self.playground_action_var.set(actions[0])
            else:
                self.playground_action_combo.set("")
                self.playground_action_var.set("")
        else:
            self.playground_action_combo['values'] = actions
            if actions:
                self.playground_action_combo.current(0)
            else:
                self.playground_action_var.set("")
                
        # Trigger preview update
        self._on_playground_action_change()

    def _on_playground_mode_change(self):
        """Handle mode switch between text, snip, and audio actions."""
        mode = self.playground_mode_var.get()
        
        # Always show action config frame (endpoint mode is removed)
        self.action_config_frame.pack(fill="x", pady=(0, 10))
        self._populate_playground_actions(mode)
        
        # Show/Hide mode-specific containers
        if mode == "action_text":
            self.sample_text_container.pack(fill="x", pady=(15, 0))
            self.snip_image_frame.pack_forget()
            self.audio_record_frame.pack_forget()
        elif mode == "action_snip":
            self.sample_text_container.pack_forget()
            self.snip_image_frame.pack(fill="x", pady=(8, 0))
            self.audio_record_frame.pack_forget()
        elif mode == "action_audio":
            self.sample_text_container.pack_forget()
            self.snip_image_frame.pack_forget()
            self.audio_record_frame.pack(fill="x", pady=(8, 0))
            # Initialize audio devices on first switch to audio mode
            self._refresh_audio_devices()
            
        self._update_playground_preview()

    def _upload_image(self):
        """Open file dialog to upload an image."""
        file_path = filedialog.askopenfilename(
            title="Select Image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")]
        )
        if file_path:
            self._set_playground_image(file_path)

    def _paste_image(self):
        """Paste image from clipboard."""
        try:
            from PIL import Image, ImageGrab
            image = ImageGrab.grabclipboard()
            if isinstance(image, Image.Image):
                # Save to temporary buffer to get bytes
                import io
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                buf.seek(0)
                # We can store raw bytes or base64
                b64_data = base64.b64encode(buf.getvalue()).decode('utf-8')
                
                self.playground_image_base64 = b64_data
                self.playground_image_mime = "image/png"
                self.playground_image_name = "Pasted Image"
                
                self._update_image_preview_label()
            else:
                messagebox.showinfo("Paste Image", "No image found in clipboard.")
        except ImportError:
            messagebox.showerror("Error", "Pillow (PIL) is required for image pasting.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to paste image: {e}")

    def _set_playground_image(self, file_path):
        """Set the playground image from a file path."""
        try:
            with open(file_path, "rb") as f:
                data = f.read()
                
            self.playground_image_base64 = base64.b64encode(data).decode('utf-8')
            
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.jpg', '.jpeg']:
                self.playground_image_mime = "image/jpeg"
            elif ext == '.png':
                self.playground_image_mime = "image/png"
            elif ext == '.webp':
                self.playground_image_mime = "image/webp"
            else:
                self.playground_image_mime = "application/octet-stream"
                
            self.playground_image_name = os.path.basename(file_path)
            self._update_image_preview_label()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image: {e}")

    def _update_image_preview_label(self):
        """Update the image preview label text."""
        if hasattr(self, 'image_preview_label'):
            if self.playground_image_name:
                text = f"Selected: {self.playground_image_name}"
                if self.use_ctk:
                    self.image_preview_label.configure(text=text, text_color=self.colors.accent)
                else:
                    self.image_preview_label.configure(text=text, fg=self.colors.accent)
            else:
                if self.use_ctk:
                    self.image_preview_label.configure(text="No image selected", text_color=self.colors.surface2)
                else:
                    self.image_preview_label.configure(text="No image selected", fg=self.colors.surface2)
    
    def _on_playground_action_change(self, event=None):
        """Handle action selection change."""
        action_name = self.playground_action_var.get()
        if action_name in ("_Custom", "_Ask"):
            self.custom_input_frame.pack(fill="x", pady=(5, 0))
        else:
            self.custom_input_frame.pack_forget()
        self._update_playground_preview()
    
    def _populate_endpoint_list(self):
        """Populate the endpoint list from loaded options."""
        try:
            endpoints_data = self.options_data.get("endpoints", {})
            endpoints = sorted([k for k in endpoints_data.keys() if k != "_settings"])
            
            if self.use_ctk:
                self.playground_endpoint_combo.configure(values=endpoints)
            else:
                self.playground_endpoint_combo['values'] = endpoints
            
            if endpoints:
                if self.use_ctk:
                    self.playground_endpoint_combo.set(endpoints[0])
                else:
                    self.playground_endpoint_combo.current(0)
                self.playground_endpoint_var.set(endpoints[0])
        except Exception as e:
            print(f"Error populating endpoints: {e}")
    
    def _update_playground_preview(self, event=None):
        """
        Update the live preview based on current action configuration.
        Matches logic in text_edit_tool.py _process_option.
        """
        mode = self.playground_mode_var.get()
        action_name = self.playground_action_var.get()
        if not action_name:
            return
            
        action_data = self.options_data.get(action_name, {})
        # Note: action_data might be in sub-dict if not properly flattened, but _populate uses keys from tool dict
        # So self.options_data[tool][action_name] is the correct way?
        # self.options_data IS nested now.
        # But wait, self.options_data.get(action_name, {}) implies flat structure or top-level.
        # _populate_playground_actions used tool_data = self.options_data.get(tool_key, {})
        # So we must fetch from the correct tool!
        
        if mode == "action_text":
            tool_key = "text_edit_tool"
        elif mode == "action_snip":
            tool_key = "snip_tool"
        else:  # action_audio
            tool_key = "audio_tool"
        tool_data = self.options_data.get(tool_key, {})
        action_data = tool_data.get(action_name, {})
        
        # Determine global vs tool settings
        # _settings is usually at tool level too
        tool_settings = tool_data.get("_settings", {})
        global_settings = self.options_data.get("_global_settings", {})
        
        # --- 1. System Prompt Construction ---
        # Logic: Starts with action's system prompt, then appends modifier injections.
        # Global chat instructions are NOT used for option requests within text_edit_tool.
        
        system_parts = []
        
        # Get base system prompt from action
        # Note: We check current editor content if it's the current action, else from data
        if self.current_action == action_name:
             # Use live editor value
            if self.use_ctk:
                sys_prompt = self.editor_widgets["system_prompt"].get("0.0", "end").strip()
            else:
                sys_prompt = self.editor_widgets["system_prompt"].get("1.0", "end").strip()
        else:
            sys_prompt = action_data.get("system_prompt", "")
            
        if sys_prompt:
            system_parts.append(sys_prompt)
        
        # Add modifier injections (always appended)
        modifier_injections = []
        for key, var in self.playground_modifier_vars.items():
            if var.get():
                for mod in global_settings.get("modifiers", []):
                    if mod.get("key") == key:
                        injection = mod.get("injection", "")
                        if injection:
                            modifier_injections.append(injection)
        
        if modifier_injections:
            system_parts.append("\n".join(modifier_injections))
        
        full_system = "\n\n".join(system_parts)
        
        # --- 2. User Message Construction ---
        # Logic: Task + Output Rules + Delimiter + Text + Close Delimiter
        
        user_parts = []
        
        # Get task
        # Check Custom/Ask vs Standard
        custom_input = self.playground_custom_var.get()
        task = ""
        
        if action_name == "_Custom" and custom_input:
            template = tool_settings.get("custom_task_template", "Apply the following change to the text: {custom_input}")
            task = template.format(custom_input=custom_input)
        elif action_name == "_Ask" and custom_input:
            template = tool_settings.get("ask_task_template", "Answer the following question about the text: {custom_input}")
            task = template.format(custom_input=custom_input)
        else:
            if self.current_action == action_name:
                task = self.editor_widgets["task_var"].get()
            else:
                task = action_data.get("task", "")
                
            # Handle {input} placeholder for other actions if they use it
            if "{input}" in task and custom_input:
                task = task.replace("{input}", custom_input)
        
        if task:
            user_parts.append(task)
            
        # Add output rules based on type
        if self.current_action == action_name:
             prompt_type = self.editor_widgets["prompt_type_var"].get()
        else:
             prompt_type = action_data.get("prompt_type", "edit")
             
        if prompt_type == "general":
            output_rules = tool_settings.get("base_output_rules_general", "")
        else:
            output_rules = tool_settings.get("base_output_rules_edit", "")
            
        if output_rules:
            user_parts.append(output_rules)
            
        # Add text with delimiters
        text_delimiter = tool_settings.get("text_delimiter", "\n\n<text_to_process>\n")
        text_delimiter_close = tool_settings.get("text_delimiter_close", "\n</text_to_process>")
        
        if self.use_ctk:
            sample_text = self.playground_sample_text.get("0.0", "end").strip()
        else:
            sample_text = self.playground_sample_text.get("1.0", "end").strip()
        
        user_message = "\n\n".join(user_parts)
        if sample_text and mode == "action_text":
            user_message += text_delimiter + sample_text + text_delimiter_close
        
        self._set_preview_text(self.playground_system_preview, full_system, "system")
        self._set_preview_text(self.playground_user_preview, user_message, "user")
        
        # Update metadata
        total_chars = len(full_system) + len(user_message)
        token_estimate = total_chars // 4
        
        # Determine show_chat status based on tool type
        if self.current_action == action_name:
            show_chat = self.editor_widgets["show_chat_var"].get()
        else:
            # Use correct field name based on tool
            if mode == "action_text":
                show_chat = action_data.get("show_chat_window_instead_of_replace", False)
            else:  # snip_tool or audio_tool
                show_chat = action_data.get("show_chat_window", True)

        # Determine response mode label based on tool type
        if show_chat:
            response_mode = "Chat Window"
        else:
            if mode == "action_text":
                response_mode = "Replace"
            elif mode == "action_snip":
                response_mode = "Copy"
            else:  # action_audio
                response_mode = "Result Panel"
        
        # Build metadata text - Type is only for TextEditTool
        if mode == "action_text":
            meta_text = f"📊 Tokens: ~{token_estimate} | Type: {prompt_type} | Mode: {response_mode}"
        else:
            meta_text = f"📊 Tokens: ~{token_estimate} | Mode: {response_mode}"
        
        if self.use_ctk:
            self.playground_meta_label.configure(text=meta_text)
        else:
            self.playground_meta_label.configure(text=meta_text)
    
    def _update_endpoint_preview(self):
        """Update endpoint mode preview."""
        endpoint_name = self.playground_endpoint_var.get()
        if not endpoint_name:
            return
        
        try:
            endpoints_data = self.options_data.get("endpoints", {})
            prompt_template = endpoints_data.get(endpoint_name, "")
            # Handle if it's a dict (new structure) or string (old structure)
            if isinstance(prompt_template, dict):
                 prompt_template = prompt_template.get("task", "") or prompt_template.get("prompt", "")
        except:
            prompt_template = "(Could not load endpoint)"
        
        lang = self.playground_lang_var.get() or "English"
        prompt = prompt_template.replace("{lang}", lang)
        
        self._set_preview_text(self.playground_system_preview,
                              "(Endpoints use direct prompts without system message)", "system")
        self._set_preview_text(self.playground_user_preview, prompt, "user")
        
        token_estimate = len(prompt) // 4
        image_info = f" | 🖼️ {self.playground_image_name}" if self.playground_image_base64 else " | ⚠️ No image"
        
        if self.use_ctk:
            self.playground_meta_label.configure(
                text=f"📊 Tokens: ~{token_estimate} | Endpoint: {endpoint_name}{image_info}"
            )
        else:
            self.playground_meta_label.configure(
                text=f"📊 Tokens: ~{token_estimate} | Endpoint: {endpoint_name}{image_info}"
            )
    
    def _set_preview_text(self, widget, text, preview_type):
        """Helper to set preview text."""
        if self.use_ctk:
            widget.configure(state="normal")
            widget.delete("0.0", "end")
            widget.insert("0.0", text)
            widget.configure(state="disabled")
        else:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
            widget.configure(state="disabled")
    
    def _copy_preview(self, preview_type):
        """Copy preview content to clipboard."""
        widget = self.playground_system_preview if preview_type == "system" else self.playground_user_preview
        if self.use_ctk:
            content = widget.get("0.0", "end").strip()
        else:
            content = widget.get("1.0", "end").strip()
        try:
            pyperclip.copy(content)
            if self.use_ctk:
                ok_img = self.status_icons.get("success") if hasattr(self, "status_icons") else None
                self.playground_test_status.configure(text=" Copied!", image=ok_img, compound="left", text_color=self.colors.accent_green)
            else:
                self.playground_test_status.configure(text="✅ Copied!", fg=self.colors.accent_green)
            self.root.after(2000, lambda: self._clear_test_status())
        except Exception as e:
            if self.use_ctk:
                self.playground_test_status.configure(text=f"❌ Copy failed: {e}", text_color=self.colors.accent_red)
            else:
                self.playground_test_status.configure(text=f"❌ Copy failed: {e}", fg=self.colors.accent_red)
    
    # --- Image Handling ---
    
    def _select_playground_image(self):
        """Select an image file for endpoint testing."""
        path = filedialog.askopenfilename(
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp")]
        )
        if path:
            self._load_playground_image(path)
    
    def _paste_playground_image(self):
        """Paste image from clipboard."""
        try:
            from PIL import ImageGrab, Image
            
            img = ImageGrab.grabclipboard()
            if img:
                if img.mode == 'RGBA':
                    bg = Image.new('RGB', img.size, (255, 255, 255))
                    bg.paste(img, mask=img.split()[3])
                    img = bg
                
                from io import BytesIO
                buffered = BytesIO()
                img.save(buffered, format="JPEG")
                img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                
                self.playground_image_base64 = img_str
                self.playground_image_mime = "image/jpeg"
                self.playground_image_name = "Pasted Image"
                
                self._show_image_preview(img)
                self._update_playground_preview()
            else:
                messagebox.showinfo("Paste", "No image in clipboard", parent=self.root)
        except Exception as e:
            messagebox.showerror("Paste Error", str(e), parent=self.root)
    
    def _load_playground_image(self, filepath):
        """Load image from file."""
        try:
            from PIL import Image
            from io import BytesIO
            
            img = Image.open(filepath)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            buffered = BytesIO()
            img.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            self.playground_image_base64 = img_str
            self.playground_image_mime = "image/jpeg"
            self.playground_image_name = os.path.basename(filepath)
            
            self._show_image_preview(img)
            self._update_playground_preview()
        except ImportError:
            with open(filepath, "rb") as f:
                img_bytes = f.read()
                self.playground_image_base64 = base64.b64encode(img_bytes).decode("utf-8")
                self.playground_image_mime = "image/jpeg"
                self.playground_image_name = os.path.basename(filepath)
                self._show_image_preview_text_only(os.path.basename(filepath), f"{len(img_bytes)//1024} KB")
                self._update_playground_preview()
        except Exception as e:
            messagebox.showerror("Image Error", f"Failed to load image: {e}", parent=self.root)
    
    def _show_image_preview(self, pil_image):
        """Show thumbnail preview of image."""
        try:
            if self.use_ctk:
                ctk_img = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(100, 100))
                self.image_drop_zone.configure(image=ctk_img, text="")
                self.image_drop_zone._image = ctk_img  # Keep reference
            else:
                from PIL import ImageTk
                pil_image.thumbnail((100, 100))
                tk_img = ImageTk.PhotoImage(pil_image)
                self.image_drop_zone.configure(image=tk_img, text="")
                self.image_drop_zone.image = tk_img
        except Exception:
            self.image_drop_zone.configure(text=f"📷 {self.playground_image_name}")
    
    def _show_image_preview_text_only(self, filename, size):
        """Fallback preview."""
        self.image_drop_zone.configure(text=f"📷 {filename}\n({size})")
    
    def _clear_playground_image(self):
        """Clear the selected image."""
        self.playground_image_base64 = None
        self.playground_image_mime = None
        self.playground_image_name = None
        if self.use_ctk:
            # Restore camera icon
            self.image_drop_zone.configure(image=self.playground_camera_icon, text=" No image selected")
        else:
            self.image_drop_zone.configure(image='', text="📷 No image selected")
            if hasattr(self.image_drop_zone, 'image'):
                self.image_drop_zone.image = None
        self._update_playground_preview()
    
    # --- Audio Recording Methods ---
    
    def _refresh_audio_devices(self):
        """Refresh the list of available audio input devices."""
        try:
            from ...audio import list_input_devices, get_default_input_device
            
            devices = list_input_devices()
            self.playground_audio_devices = devices
            
            device_names = [d.get_display_name() for d in devices]
            
            if self.use_ctk:
                self.playground_audio_device_combo.configure(values=device_names if device_names else ["(No devices found)"])
            else:
                self.playground_audio_device_combo['values'] = device_names if device_names else ["(No devices found)"]
            
            # Try to set default device
            if devices:
                try:
                    default = get_default_input_device()
                    if default:
                        default_name = default.get_display_name()
                        if default_name in device_names:
                            self.playground_audio_device_var.set(default_name)
                        else:
                            self.playground_audio_device_var.set(device_names[0])
                    else:
                        self.playground_audio_device_var.set(device_names[0])
                except Exception:
                    self.playground_audio_device_var.set(device_names[0])
            else:
                self.playground_audio_device_var.set("(No devices found)")
                
        except ImportError:
            if self.use_ctk:
                self.playground_audio_device_combo.configure(values=["(Audio module not available)"])
            else:
                self.playground_audio_device_combo['values'] = ["(Audio module not available)"]
            self.playground_audio_device_var.set("(Audio module not available)")
        except Exception as e:
            print(f"[PromptEditor] Error loading audio devices: {e}")
            if self.use_ctk:
                self.playground_audio_device_combo.configure(values=[f"(Error: {str(e)[:30]})"])
            else:
                self.playground_audio_device_combo['values'] = [f"(Error: {str(e)[:30]})"]
    
    def _toggle_playground_recording(self):
        """Toggle audio recording on/off."""
        if self.playground_is_recording:
            self._stop_playground_recording()
        else:
            self._start_playground_recording()
    
    def _start_playground_recording(self):
        """Start audio recording."""
        try:
            from ...audio import AudioRecorder, list_input_devices
            
            # Find selected device
            selected_name = self.playground_audio_device_var.get()
            device = None
            for d in self.playground_audio_devices:
                if d.get_display_name() == selected_name:
                    device = d
                    break
            
            if not device:
                messagebox.showerror("Recording Error", "Please select an audio device.", parent=self.root)
                return
            
            # Create recorder with device
            self.playground_recorder = AudioRecorder(device)
            
            # Start stream and recording (Unified API)
            self.playground_recorder.start_stream()
            self.playground_recorder.start_recording_unified()
            
            self.playground_is_recording = True
            self.playground_record_start = time.time()
            
            # Update UI
            if self.use_ctk:
                self.playground_record_btn.configure(text="⏹️ Stop")
                self.playground_audio_status.configure(text="Recording...", text_color=self.colors.accent_red)
            else:
                self.playground_record_btn.configure(text="⏹️ Stop")
                self.playground_audio_status.configure(text="Recording...", fg=self.colors.accent_red)
            
            # Start duration update
            self._update_playground_recording_duration()
            
        except ImportError as e:
            messagebox.showerror("Recording Error", f"Audio module not available: {e}", parent=self.root)
        except Exception as e:
            messagebox.showerror("Recording Error", f"Failed to start recording: {e}", parent=self.root)
    
    def _stop_playground_recording(self):
        """Stop audio recording and save data."""
        if not self.playground_recorder:
            return
        
        try:
            # Stop recording (Unified API)
            audio_data = self.playground_recorder.stop_recording_unified()
            self.playground_recorder.stop_stream()
            
            self.playground_is_recording = False
            if audio_data:
                self.playground_audio_data = audio_data
                self.playground_audio_mime = "audio/wav"
                
                # Calculate duration
                duration = time.time() - self.playground_record_start if self.playground_record_start else 0
                size_kb = len(audio_data) // 1024
                
                # Update UI
                status_text = f"Recorded: {self._format_playground_duration(duration)} ({size_kb} KB)"
                if self.use_ctk:
                    self.playground_record_btn.configure(text="🔴 Record")
                    self.playground_audio_status.configure(text=status_text, text_color=self.colors.accent_green)
                else:
                    self.playground_record_btn.configure(text="🔴 Record")
                    self.playground_audio_status.configure(text=status_text, fg=self.colors.accent_green)
            else:
                if self.use_ctk:
                    self.playground_record_btn.configure(text="🔴 Record")
                    self.playground_audio_status.configure(text="Recording failed - no audio data", text_color=self.colors.accent_red)
                else:
                    self.playground_record_btn.configure(text="🔴 Record")
                    self.playground_audio_status.configure(text="Recording failed - no audio data", fg=self.colors.accent_red)
                    
        except Exception as e:
            print(f"[PromptEditor] Error stopping recording: {e}")
            if self.use_ctk:
                self.playground_record_btn.configure(text="🔴 Record")
                self.playground_audio_status.configure(text=f"Error: {str(e)[:40]}", text_color=self.colors.accent_red)
            else:
                self.playground_record_btn.configure(text="🔴 Record")
                self.playground_audio_status.configure(text=f"Error: {str(e)[:40]}", fg=self.colors.accent_red)
        finally:
            if self.playground_recorder:
                try:
                    self.playground_recorder.cleanup()
                except:
                    pass
            self.playground_recorder = None
    
    def _update_playground_recording_duration(self):
        """Update the recording duration display."""
        if not self.playground_is_recording:
            return
        
        duration = time.time() - self.playground_record_start if self.playground_record_start else 0
        duration_text = self._format_playground_duration(duration)
        
        if self.use_ctk:
            self.playground_audio_duration.configure(text=duration_text)
        else:
            self.playground_audio_duration.configure(text=duration_text)
        
        # Schedule next update
        if self.playground_is_recording and self.root:
            self.root.after(100, self._update_playground_recording_duration)
    
    def _format_playground_duration(self, seconds: float) -> str:
        """Format duration in MM:SS format."""
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"
    
    def _clear_playground_audio(self):
        """Clear recorded audio data."""
        # Stop recording if in progress
        if self.playground_is_recording:
            self._stop_playground_recording()
        
        self.playground_audio_data = None
        self.playground_audio_mime = None
        
        if self.use_ctk:
            self.playground_audio_duration.configure(text="00:00")
            self.playground_audio_status.configure(text="No audio recorded", text_color=self.colors.blockquote)
        else:
            self.playground_audio_duration.configure(text="00:00")
            self.playground_audio_status.configure(text="No audio recorded", fg=self.colors.blockquote)
    
    def _prepare_audio_request(self) -> Dict:
        """Prepare params for audio action request."""
        if not self.playground_audio_data:
            return {"error": "No audio recorded. Please record audio first."}
        
        if self.use_ctk:
            system_prompt = self.playground_system_preview.get("0.0", "end").strip()
            user_message = self.playground_user_preview.get("0.0", "end").strip()
        else:
            system_prompt = self.playground_system_preview.get("1.0", "end").strip()
            user_message = self.playground_user_preview.get("1.0", "end").strip()
        
        # Convert raw audio bytes to base64 string for the API
        audio_b64 = base64.b64encode(self.playground_audio_data).decode('utf-8')
        
        from ...messages import build_audio_message
        messages = build_audio_message(
            audio_b64=audio_b64,
            mime_type=self.playground_audio_mime or "audio/wav",
            task=user_message,
            system_prompt=system_prompt
        )
        
        return self._get_request_config(messages)
    
    # --- API Testing ---
    
    def _test_playground_with_api(self):
        """Send the current prompt to the API for testing (Streaming)."""
        # Ensure preview is up to date with any edits
        self._update_playground_preview()
        
        mode = self.playground_mode_var.get()
        
        # Snip mode: Use existing image (don't auto-snip)
        if mode == "action_snip":
            if not self.playground_image_base64:
                messagebox.showinfo("Image Required", "Please select or snip an image before testing.", parent=self.root)
                return
            # Proceed directly to test with existing image
            self._continue_snip_test()
            return
        
        # Audio mode: Check for recorded audio
        if mode == "action_audio" and not self.playground_audio_data:
            messagebox.showinfo("Audio Required", "Please record audio before testing.", parent=self.root)
            return

        if self.use_ctk:
            try:
                status_img = self.status_icons.get("loading") if hasattr(self, "status_icons") else None
                self.playground_test_status.configure(text=" Sending request...", image=status_img, compound="left", text_color=self.colors.fg)
            except Exception:
                 # Last resort fallback if cached image also fails (shouldn't happen but safe)
                 try:
                    self.playground_test_status.configure(text="⏳ Sending request...", image=None, compound="left", text_color=self.colors.fg)
                 except:
                    pass
        else:
            self.playground_test_status.configure(text="⏳ Sending request...", fg=self.colors.fg)
        self.root.update()
        
        params = {}
        
        try:
            if mode == "action_audio":
                params = self._prepare_audio_request()
            else:  # action_text
                params = self._prepare_text_request()
            
            if params.get("error"):
                raise ValueError(params["error"])
                
            self._run_streaming_test(params)
            
        except Exception as e:
            if self.use_ctk:
                self.playground_test_status.configure(text=f"❌ Error: {e}", text_color=self.colors.accent_red)
            else:
                self.playground_test_status.configure(text=f"❌ Error: {e}", fg=self.colors.accent_red)

    def _perform_snip_test(self):
        """Trigger screen snipping for Playground test."""
        # Hide window to allow capture
        self.root.iconify()
        
        # We need GUICoordinator to trigger overlay
        try:
            from ..core import GUICoordinator
            GUICoordinator.get_instance().request_snip_overlay(
                on_capture=self._on_playground_snip_captured,
                on_cancel=self._on_playground_snip_cancelled
            )
        except Exception as e:
            self.root.deiconify()
            messagebox.showerror("Error", f"Failed to start snip: {e}")

    def _on_playground_snip_cancelled(self):
        """Handle snip cancellation."""
        self.root.deiconify()
        if self.use_ctk:
            self.playground_test_status.configure(text="❌ Snipping cancelled", image=None, text_color=self.colors.surface2)
        else:
            self.playground_test_status.configure(text="❌ Snipping cancelled", fg=self.colors.surface2)
    
    def _snip_playground_image(self):
        """Capture screen snip and store as playground image (without testing)."""
        # Hide window to allow capture
        self.root.iconify()
        
        try:
            from ..core import GUICoordinator
            GUICoordinator.get_instance().request_snip_overlay(
                on_capture=self._on_playground_snip_image_captured,
                on_cancel=self._on_playground_snip_image_cancelled
            )
        except Exception as e:
            self.root.deiconify()
            messagebox.showerror("Error", f"Failed to start snip: {e}", parent=self.root)
    
    def _on_playground_snip_image_cancelled(self):
        """Handle snip image capture cancellation."""
        self.root.deiconify()
        if self.use_ctk:
            self.playground_test_status.configure(text="Snip cancelled", image=None, text_color=self.colors.surface2)
        else:
            self.playground_test_status.configure(text="Snip cancelled", fg=self.colors.surface2)
    
    def _on_playground_snip_image_captured(self, result):
        """Handle captured snip for image selection (not auto-test)."""
        # Restore window
        self.root.deiconify()
        
        # Store capture data
        self.playground_image_base64 = result.image_base64
        self.playground_image_mime = result.mime_type
        self.playground_image_name = f"Snip_{int(time.time())}.png"
        
        # Show preview
        try:
            from PIL import Image
            from io import BytesIO
            img_data = base64.b64decode(result.image_base64)
            pil_image = Image.open(BytesIO(img_data))
            self._show_image_preview(pil_image)
        except Exception:
            # Fallback to text preview
            self._show_image_preview_text_only(self.playground_image_name, "Captured")
        
        # Update preview
        self._update_playground_preview()
        
        # Update status
        if self.use_ctk:
            self.playground_test_status.configure(text="✅ Image captured", image=None, text_color=self.colors.accent_green)
        else:
            self.playground_test_status.configure(text="✅ Image captured", fg=self.colors.accent_green)
        self.root.after(2000, self._clear_test_status)

    def _on_playground_snip_captured(self, result):
        """Handle captured snip for Playground."""
        # Restore window
        self.root.deiconify()
        
        # Store capture data
        self.playground_image_base64 = result.image_base64
        self.playground_image_mime = result.mime_type
        self.playground_image_name = f"Snip_{int(time.time())}.png"
        
        # Proceed with test
        self._continue_snip_test()

    def _continue_snip_test(self):
        """Continue with API test after snip capture."""
        try:
            if self.use_ctk:
                self.playground_test_status.configure(text="⏳ Sending request...", image=None, text_color=self.colors.fg)
            else:
                self.playground_test_status.configure(text="⏳ Sending request...", fg=self.colors.fg)
            self.root.update()
        except Exception as e:
            print(f"Warning: Failed to update status label: {e}")
        
        try:
            params = self._prepare_snip_request()
            if params.get("error"):
                raise ValueError(params["error"])
                
            self._run_streaming_test(params)
            
        except Exception as e:
            if self.use_ctk:
                self.playground_test_status.configure(text=f"❌ Error: {e}", text_color=self.colors.accent_red)
            else:
                self.playground_test_status.configure(text=f"❌ Error: {e}", fg=self.colors.accent_red)
    
    def _prepare_endpoint_request(self) -> Dict:
        """Prepare params for endpoint request."""
        # Endpoints use the user preview as the prompt template (already resolved with lang)
        # If image is present, treat as multimodal
        
        if self.use_ctk:
            prompt = self.playground_user_preview.get("0.0", "end").strip()
        else:
            prompt = self.playground_user_preview.get("1.0", "end").strip()
            
        from ...messages import build_text_message, build_image_message
        
        # Endpoints typically don't use a system prompt in this context (playground sets it to note)
        system_prompt = "You are a helpful AI assistant."
        
        if self.playground_image_base64:
            messages = build_image_message(
                image_b64=self.playground_image_base64,
                mime_type=self.playground_image_mime,
                task=prompt,
                system_prompt=system_prompt
            )
            # Remove system prompt if it was just the default placeholder
            if messages[0]["role"] == "system" and messages[0]["content"] == system_prompt:
                messages.pop(0)
        else:
            # Text-only endpoint
            messages = [{"role": "user", "content": prompt}]
        
        return self._get_request_config(messages)

    def _prepare_snip_request(self) -> Dict:
        """Prepare params for snip action request (multimodal)."""
        if not self.playground_image_base64:
            return {"error": "No image selected. Snip actions require an image."}
            
        if self.use_ctk:
            system_prompt = self.playground_system_preview.get("0.0", "end").strip()
            user_message = self.playground_user_preview.get("0.0", "end").strip()
        else:
            system_prompt = self.playground_system_preview.get("1.0", "end").strip()
            user_message = self.playground_user_preview.get("1.0", "end").strip()
            
        from ...messages import build_image_message
        messages = build_image_message(
            image_b64=self.playground_image_base64,
            mime_type=self.playground_image_mime,
            task=user_message,
            system_prompt=system_prompt
        )
        
        return self._get_request_config(messages)
    
    def _prepare_text_request(self) -> Dict:
        """Prepare params for text action request."""
        if self.use_ctk:
            system_prompt = self.playground_system_preview.get("0.0", "end").strip()
            user_message = self.playground_user_preview.get("0.0", "end").strip()
        else:
            system_prompt = self.playground_system_preview.get("1.0", "end").strip()
            user_message = self.playground_user_preview.get("1.0", "end").strip()
        
        from ...messages import build_text_message
        messages = build_text_message(user_message, system_prompt)
        
        return self._get_request_config(messages)
        
    def _get_request_config(self, messages) -> Dict:
        """Helper to get common request config."""
        from ...config import load_config
        from ...key_manager import KeyManager

        config, ai_params_loaded, endpoints, loaded_keys = load_config()
        
        key_managers = {}
        for provider in ["custom", "openrouter", "google"]:
            key_managers[provider] = KeyManager(loaded_keys.get(provider, []), provider)
            
        ai_params = {k: v for k, v in ai_params_loaded.items() if v is not None}
        provider = self.playground_provider_var.get()
        model = self.playground_model_var.get()
        
        # Ensure max_tokens is set for image endpoints
        if self.playground_mode_var.get() == "endpoint":
             ai_params["max_tokens"] = 1024
             
        return {
            "messages": messages,
            "provider": provider,
            "model": model,
            "config": config,
            "ai_params": ai_params,
            "key_managers": key_managers
        }
    
    def _run_streaming_test(self, params):
        """Run the streaming test in a background thread."""
        dialog = TestResultDialog(self.root, self.colors)
        
        # Define thread target
        def _target():
            try:
                from ...api_client import call_api_stream_unified

                # Check for thinking support in config to show proper UI
                thinking_enabled = params["config"].get("thinking_enabled", False)
                if thinking_enabled:
                    # Provide visual cue that thinking might happen
                    pass
                
                def stream_callback(type_, content):
                    if type_ == "text":
                        dialog.append_text(content)
                    elif type_ == "thinking":
                        dialog.append_thinking(content)
                    elif type_ == "error":
                        dialog.append_error(content)
                    # We can ignore usage/tool_calls for the basic preview
                
                # Execute unified streaming call
                text, reasoning, usage, error = call_api_stream_unified(
                    provider_type=params["provider"],
                    messages=params["messages"],
                    model=params["model"],
                    config=params["config"],
                    ai_params=params["ai_params"],
                    key_managers=params["key_managers"],
                    callback=stream_callback,
                    thinking_enabled=thinking_enabled,
                    thinking_output=params["config"].get("thinking_output", "reasoning_content")
                )
                
                if error:
                    dialog.append_error(error)
                
                # Mark done
                if dialog.thinking_started:
                    dialog.end_thinking()
                    
                # Update main window status
                self.queue.put(self._update_status_success)
                
            except Exception as e:
                dialog.append_error(str(e))
                self.queue.put(lambda: self._update_status_error(str(e)))
        
        # Start thread
        threading.Thread(target=_target, daemon=True).start()
        
    def _update_status_success(self):
        """Update test button status to success."""
        renderer = get_emoji_renderer() if HAVE_EMOJI else None
        if self.use_ctk:
            ok_img = renderer.get_ctk_image("✅", size=16) if renderer else None
            self.playground_test_status.configure(text=" Success!", image=ok_img, compound="left", text_color=self.colors.accent_green)
        else:
            self.playground_test_status.configure(text="✅ Success!", fg=self.colors.accent_green)
        self.root.after(3000, lambda: self._clear_test_status())
        
    def _update_status_error(self, error):
        """Update test button status to error."""
        if self.use_ctk:
             self.playground_test_status.configure(text=f"❌ Error: {error[:30]}...", text_color=self.colors.accent_red)
        else:
             self.playground_test_status.configure(text=f"❌ Error: {error[:30]}...", fg=self.colors.accent_red)
    
    def _clear_test_status(self):
        """Clear the test status label."""
        try:
            if self.use_ctk:
                self.playground_test_status.configure(text="", image=None)
            else:
                self.playground_test_status.configure(text="")
        except Exception:
            pass
    
    # Event handlers
    
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
            self.editor_widgets["show_chat_var"].set(
                action_data.get("show_chat_window_instead_of_replace", False)
            )
        else:  # snip_tool or audio_tool
            self.editor_widgets["prompt_type_var"].set("edit")  # Not used but keep default
            self.editor_widgets["show_chat_var"].set(
                action_data.get("show_chat_window", True)
            )
            if self.current_tool == "snip_tool" and "compare_prompts_var" in self.editor_widgets:
                self.editor_widgets["compare_prompts_var"].set(
                    action_data.get("compare_prompts", False)
                )
        
        # Update field visibility
        self._update_editor_visibility()
    
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
    
    def _pick_icon(self):
        """Open emoji picker for icon selection."""
        def on_select(emoji):
            self.editor_widgets["icon_var"].set(emoji)
        
        EmojiPicker(self.root, on_select, self.colors)
    
    def _add_action(self):
        """Add a new action."""
        name = ask_themed_string(self.root, "New Action", "Enter action name:", self.colors)
        tool_data = self.options_data.setdefault(self.current_tool, {})
        
        if name and name not in tool_data:
            tool_data[name] = {
                "icon": "⚡",
                "prompt_type": "edit",
                "system_prompt": "",
                "task": "",
                "show_chat_window_instead_of_replace": False
            }
            self.action_listbox.add_item(name, name, "⚡")
            self.action_listbox.select(name)
            # Scroll to end not automatically supported but new item is at bottom
    
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
        
        import copy
        tool_data[new_name] = copy.deepcopy(tool_data[self.current_action])
        
        icon = tool_data[new_name].get("icon", "")
        self.action_listbox.add_item(new_name, new_name, icon)
    
    def _delete_action(self):
        """Delete selected action."""
        if not self.current_action:
            return
        
        if messagebox.askyesno("Delete Action", f"Delete action '{self.current_action}'?", parent=self.root):
            tool_data = self.options_data.get(self.current_tool, {})
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
            display_keys[idx], display_keys[idx-1] = display_keys[idx-1], display_keys[idx]
            
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
            display_keys[idx], display_keys[idx+1] = display_keys[idx+1], display_keys[idx]
            
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
            "icon": self.editor_widgets["icon_var"].get(),
            "system_prompt": system_prompt,
            "task": self.editor_widgets["task_var"].get(),
        }
        
        # Tool-specific fields
        if self.current_tool == "text_edit_tool":
            action_dict["prompt_type"] = self.editor_widgets["prompt_type_var"].get()
            action_dict["show_chat_window_instead_of_replace"] = self.editor_widgets["show_chat_var"].get()
        elif self.current_tool == "snip_tool":
            action_dict["show_chat_window"] = self.editor_widgets["show_chat_var"].get()
            if "compare_prompts_var" in self.editor_widgets:
                action_dict["compare_prompts"] = self.editor_widgets["compare_prompts_var"].get()
        else:  # audio_tool
            action_dict["show_chat_window"] = self.editor_widgets["show_chat_var"].get()
        
        tool_data = self.options_data.setdefault(self.current_tool, {})
        tool_data[self.current_action] = action_dict
        
        # Refresh UI list to update icons
        self._refresh_action_list()
        
        if self.use_ctk:
            self.editor_widgets["save_status"].configure(
                text=f"✅ Saved '{self.current_action}'",
                text_color=self.colors.accent_green
            )
        else:
            self.editor_widgets["save_status"].configure(
                text=f"✅ Saved '{self.current_action}'",
                fg=self.colors.accent_green
            )
    
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
            
            modifiers[index] = {
                "key": self.modifier_widgets["key_var"].get(),
                "icon": self.modifier_widgets["icon_var"].get(),
                "label": self.modifier_widgets["label_var"].get(),
                "tooltip": self.modifier_widgets["tooltip_var"].get(),
                "injection": injection,
                "forces_chat_window": self.modifier_widgets["forces_chat_var"].get()
            }
            
            # Rebuild list to update display
            self.modifier_listbox.clear()
            for i, mod in enumerate(modifiers):
                self.modifier_listbox.add_item(str(i), mod.get('label', mod.get('key', '')), mod.get('icon', ''))
            self.modifier_listbox.select(str(index))
    
    def _add_group(self):
        """Add a new group."""
        name = ask_themed_string(self.root, "New Group", "Enter group name:", self.colors)
        if name:
            tool_data = self.options_data.setdefault(self.current_tool, {})
            settings = tool_data.setdefault("_settings", {})
            groups = settings.setdefault("popup_groups", [])
            groups.append({
                "name": name,
                "items": []
            })
            idx = len(groups) - 1
            self.group_listbox.add_item(str(idx), name, None)
    
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
                del groups[index]
                self._refresh_group_list()
    
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
            groups[index], groups[index-1] = groups[index-1], groups[index]
            
            self._refresh_group_list()
            self.group_listbox.select(str(index-1))

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
            groups[index], groups[index+1] = groups[index+1], groups[index]
            
            self._refresh_group_list()
            self.group_listbox.select(str(index+1))

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
            
            groups[index] = {
                "name": self.group_widgets["name_var"].get(),
                "enabled": self.group_widgets["enabled_var"].get(),
                "items": items
            }
            
            self._refresh_group_list()
            self.group_listbox.select(str(index))
    
    def _create_button_bar(self, parent):
        """Create the bottom button bar."""
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        # Pack with side="bottom" to ensure button bar is visible at all window sizes
        # This works because _create_button_bar is called BEFORE _create_main_content
        btn_frame.pack(fill="x", side="bottom", pady=(5, 0))
        
        create_emoji_button(
            btn_frame, "Save All", "💾", self.colors, "success", 140, 42, self._save_all
        ).pack(side="left", padx=6)
        
        create_emoji_button(
            btn_frame, "Cancel", "✖️", self.colors, "secondary", 120, 42, self._close
        ).pack(side="left", padx=6)
        
        create_emoji_button(
            btn_frame, "Reset to Defaults", "🔄", self.colors, "danger", 160, 42, self._reset_to_defaults
        ).pack(side="right", padx=6)
        
        if self.use_ctk:
             self.status_label = ctk.CTkLabel(
                btn_frame, text="", font=get_ctk_font(13),
                text_color=self.colors.accent_green
            )
        else:
            self.status_label = tk.Label(btn_frame, text="", font=("Segoe UI", 10),
                                        bg=self.colors.bg, fg=self.colors.accent_green)
        self.status_label.pack(side="left", padx=20)
    
    def _save_all(self):
        """Save all options to file."""
        # Save settings from widgets
        if hasattr(self, 'settings_widgets'):
            for widget_key, (widget_type, widget) in self.settings_widgets.items():
                if ":" in widget_key:
                    section, key = widget_key.split(":", 1)
                else:
                    # Fallback for legacy keys if any (shouldn't happen with new create_settings_tab)
                    section, key = "text_edit_tool", widget_key

                # Get the value
                val = None
                if widget_type == "entry":
                    val = widget.get()
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
                    
                    target[key] = val
        
        # Save to file
        if save_options(self.options_data):
            if self.use_ctk:
                self.status_label.configure(text="✅ All options saved!", text_color=self.colors.accent_green)
            else:
                self.status_label.configure(text="✅ All options saved!", fg=self.colors.accent_green)
            
            # Reload prompts via the save_options call (which calls reload_prompts)
            # but also print confirmation
            print("[PromptEditor] Prompt configuration hot-reloaded")
            
            # Close after brief delay
            self.root.after(1000, self._close)
        else:
            if self.use_ctk:
                self.status_label.configure(text="❌ Failed to save", text_color=self.colors.accent_red)
            else:
                self.status_label.configure(text="❌ Failed to save", fg=self.colors.accent_red)
    
    def _reset_to_defaults(self):
        """Reset all prompts configuration to defaults in-memory. Requires Save All to persist."""
        if not messagebox.askyesno(
            "Reset to Defaults",
            "This will reset ALL prompts, actions, modifiers, and settings to their default values.\n\n"
            "You will need to click 'Save All' to apply the changes to prompts.json.\n\n"
            "Are you sure you want to continue?",
            parent=self.root
        ):
            return
        
        try:
            from ..prompts import get_prompts_config
            
            # Get fresh defaults WITHOUT saving to file
            config = get_prompts_config()
            self.options_data = config._get_defaults()
            
            # Clear current selection
            self.current_action = None
            
            # Reset all loaded tabs so they rebuild with new data
            if self.use_ctk and hasattr(self, '_tab_configs'):
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
                if hasattr(self, 'settings_widgets'):
                    self.settings_widgets = {}
                if hasattr(self, 'modifier_listbox'):
                    self.modifier_listbox = None
                if hasattr(self, 'modifier_widgets'):
                    self.modifier_widgets = {}
                if hasattr(self, 'group_listbox'):
                    self.group_listbox = None
                if hasattr(self, 'group_widgets'):
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
                self.status_label.configure(text="🔄 Reset to defaults. Click Save All to apply.", text_color=self.colors.accent_yellow)
            else:
                self.status_label.configure(text="🔄 Reset to defaults. Click Save All to apply.", fg=self.colors.accent_yellow)
            
            print("[PromptEditor] Configuration reset to defaults in editor. Click Save All to apply.")
            
        except Exception as e:
            if self.use_ctk:
                self.status_label.configure(text=f"❌ Reset failed: {e}", text_color=self.colors.accent_red)
            else:
                self.status_label.configure(text=f"❌ Reset failed: {e}", fg=self.colors.accent_red)
            messagebox.showerror("Reset Failed", f"Failed to reset configuration: {e}", parent=self.root)
    
    def _close(self):
        """Close the prompt editor window."""
        self._destroyed = True
        unregister_window(self.window_tag)
        try:
            if self.root:
                self.root.destroy()
        except tk.TclError:
            pass
        self.root = None


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