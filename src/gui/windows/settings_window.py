#!/usr/bin/env python3
"""
Settings Window for AIPromptBridge

Provides a GUI for editing config.ini without opening the file directly.
Features:
- Tabbed interface for different config sections
- Theme selector with live preview
- Validation for fields like ports, hotkeys
- Save/Cancel with backup creation

CustomTkinter Migration: Uses CTk widgets for modern UI.
"""

import os
import sys
import re
import time
import shutil
import threading
import queue
import tkinter as tk
from tkinter import messagebox
from typing import Dict, Optional, List, Callable, Any
from pathlib import Path

# Import CustomTkinter with fallback
from ..platform import HAVE_CTK, ctk
_CTK_AVAILABLE = HAVE_CTK


def _can_use_ctk() -> bool:
    """
    Check if CustomTkinter can be safely used.
    """
    return _CTK_AVAILABLE

from ..themes import (
    ThemeRegistry, ThemeColors, get_colors, list_themes, sync_ctk_appearance,
    get_ctk_button_colors, get_ctk_frame_colors, get_ctk_entry_colors,
    get_ctk_textbox_colors, get_ctk_combobox_colors, get_ctk_label_colors,
    get_ctk_font
)
from ..core import get_next_window_id, register_window, unregister_window
from ..custom_widgets import ScrollableButtonList, ScrollableComboBox, upgrade_tabview_with_icons, create_section_header, create_emoji_button
from .utils import set_window_icon

# Import emoji renderer for CTkImage support (Windows color emoji fix)
try:
    from ..emoji_renderer import get_emoji_renderer, HAVE_PIL
    HAVE_EMOJI = HAVE_PIL and _CTK_AVAILABLE
except ImportError:
    HAVE_EMOJI = False
    get_emoji_renderer = None


# =============================================================================
# Config Parser/Writer
# =============================================================================

class ConfigData:
    """
    Structured representation of config.ini data.
    Preserves comments and structure for round-trip editing.
    """
    
    def __init__(self):
        self.config: Dict[str, Any] = {}       # [config] section values
        self.endpoints: Dict[str, str] = {}    # [endpoints] section
        # API key sections - now stores dicts with "key" and "name" fields
        # Format: [{"key": "sk-xxx", "name": "My Key"}, ...]
        self.keys: Dict[str, List[Dict[str, str]]] = {
            "custom": [],
            "openrouter": [],
            "google": []
        }
        self.raw_lines: List[str] = []         # Original lines for preservation
        self.comments: Dict[str, str] = {}     # Comments associated with keys


def parse_config_full(filepath: str = "config.ini") -> ConfigData:
    """
    Parse entire config file preserving structure and comments.
    
    Returns:
        ConfigData with all sections parsed
    """
    data = ConfigData()
    
    if not Path(filepath).exists():
        return data
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        data.raw_lines = lines
        current_section = None
        multiline_key = None
        multiline_value = []
        last_comment = ""
        
        for line in lines:
            raw_line = line.rstrip('\n\r')
            stripped = raw_line.strip()
            
            # Track comments
            if stripped.startswith('#'):
                last_comment = stripped
                continue
            
            if not stripped:
                last_comment = ""
                continue
            
            # Section header
            if stripped.startswith('[') and stripped.endswith(']'):
                if multiline_key and current_section == 'endpoints':
                    data.endpoints[multiline_key] = ' '.join(multiline_value)
                    multiline_key = None
                    multiline_value = []
                current_section = stripped[1:-1].lower()
                continue
            
            # Parse based on section
            if current_section == 'config':
                if '=' in stripped:
                    key, value = stripped.split('=', 1)
                    key = key.strip().lower()
                    value = _parse_value(value.strip())
                    data.config[key] = value
                    if last_comment:
                        data.comments[key] = last_comment
                    last_comment = ""
            
            elif current_section == 'endpoints':
                if '=' in stripped:
                    if multiline_key:
                        data.endpoints[multiline_key] = ' '.join(multiline_value)
                    endpoint_name, prompt = stripped.split('=', 1)
                    endpoint_name = endpoint_name.strip().lower()
                    prompt = prompt.strip()
                    # Remove quotes if present
                    if (prompt.startswith('"') and prompt.endswith('"')) or \
                       (prompt.startswith("'") and prompt.endswith("'")):
                        prompt = prompt[1:-1]
                    if prompt.endswith('\\'):
                        multiline_key = endpoint_name
                        multiline_value = [prompt[:-1].strip()]
                    else:
                        data.endpoints[endpoint_name] = prompt
                        multiline_key = None
                        multiline_value = []
                elif multiline_key:
                    if stripped.endswith('\\'):
                        multiline_value.append(stripped[:-1].strip())
                    else:
                        multiline_value.append(stripped)
                        data.endpoints[multiline_key] = ' '.join(multiline_value)
                        multiline_key = None
                        multiline_value = []
            
            elif current_section in data.keys:
                if stripped and not stripped.startswith('#'):
                    # Parse key with optional inline comment for name
                    # Format: sk-xxxxx   # My Key Name (uses any whitespace before #)
                    # Use regex to handle variable whitespace
                    match = re.search(r'\s+#\s*', stripped)
                    if match:
                        key_part = stripped[:match.start()].strip()
                        comment = stripped[match.end():].strip()
                        data.keys[current_section].append({
                            "key": key_part,
                            "name": comment
                        })
                    else:
                        data.keys[current_section].append({
                            "key": stripped.strip(),
                            "name": ""
                        })
        
        # Flush any remaining multiline
        if multiline_key and current_section == 'endpoints':
            data.endpoints[multiline_key] = ' '.join(multiline_value)
        
    except Exception as e:
        print(f"[SettingsWindow] Error parsing config: {e}")
    
    return data


def _parse_value(value_str: str) -> Any:
    """Parse a configuration value from string to appropriate type."""
    value_str = value_str.strip()
    if value_str.lower() in ['none', 'null', '']:
        return None
    if value_str.lower() in ['true', 'yes', 'on', '1']:
        return True
    if value_str.lower() in ['false', 'no', 'off', '0']:
        return False
    try:
        if '.' not in value_str:
            return int(value_str)
        return float(value_str)
    except ValueError:
        pass
    # Remove quotes
    if (value_str.startswith('"') and value_str.endswith('"')) or \
       (value_str.startswith("'") and value_str.endswith("'")):
        return value_str[1:-1]
    return value_str


def _value_to_str(value: Any) -> str:
    """Convert a value to config file string format."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def save_config_full(data: ConfigData, filepath: str = "config.ini") -> bool:
    """
    Save full config preserving comments and structure.
    Creates a backup before saving.
    
    Returns:
        True if save was successful
    """
    try:
        # Create backup
        if Path(filepath).exists():
            backup_path = filepath + ".bak"
            shutil.copy2(filepath, backup_path)
        
        # Rebuild the file
        lines = []
        current_section = None
        written_keys = set()
        written_endpoints = set()
        written_api_keys = {"custom": set(), "openrouter": set(), "google": set()}
        
        for line in data.raw_lines:
            raw_line = line.rstrip('\n\r')
            stripped = raw_line.strip()
            
            # Section header
            if stripped.startswith('[') and stripped.endswith(']'):
                current_section = stripped[1:-1].lower()
                lines.append(raw_line + '\n')
                continue
            
            # Comment or empty - preserve as-is
            if not stripped or stripped.startswith('#'):
                lines.append(raw_line + '\n')
                continue
            
            # Handle based on section
            if current_section == 'config' and '=' in stripped:
                key = stripped.split('=', 1)[0].strip().lower()
                if key in data.config:
                    value = _value_to_str(data.config[key])
                    lines.append(f"{key} = {value}\n")
                    written_keys.add(key)
                else:
                    lines.append(raw_line + '\n')
            
            elif current_section == 'endpoints' and '=' in stripped:
                # Skip multiline continuations (handled with main key)
                if not stripped.startswith(' ') and not stripped.startswith('\t'):
                    endpoint_name = stripped.split('=', 1)[0].strip().lower()
                    if endpoint_name in data.endpoints and endpoint_name not in written_endpoints:
                        prompt = data.endpoints[endpoint_name]
                        lines.append(f"{endpoint_name} = {prompt}\n")
                        written_endpoints.add(endpoint_name)
                    elif endpoint_name not in written_endpoints:
                        lines.append(raw_line + '\n')
                # Skip continuation lines (they were merged)
            
            elif current_section in data.keys:
                # Rewrite API keys section
                if stripped and not stripped.startswith('#'):
                    # Skip old keys, we'll write new ones at the end
                    continue
                lines.append(raw_line + '\n')
            
            else:
                lines.append(raw_line + '\n')
        
        # Add new config keys not in original file
        config_section_end = _find_section_end(lines, 'config')
        new_config_lines = []
        for key, value in data.config.items():
            if key not in written_keys:
                new_config_lines.append(f"{key} = {_value_to_str(value)}\n")
        if new_config_lines and config_section_end > 0:
            lines = lines[:config_section_end] + new_config_lines + lines[config_section_end:]
        
        # Add API keys at end of their sections
        for section in ['custom', 'openrouter', 'google']:
            section_end = _find_section_end(lines, section)
            if section_end > 0:
                key_lines = []
                for key_data in data.keys[section]:
                    if isinstance(key_data, dict):
                        key_str = key_data.get("key", "")
                        name = key_data.get("name", "")
                        if key_str:  # Only write non-empty keys
                            if name:
                                key_lines.append(f'{key_str}   # {name}\n')
                            else:
                                key_lines.append(f'{key_str}\n')
                    else:
                        # Backward compat: plain string
                        if key_data:
                            key_lines.append(f'{key_data}\n')
                lines = lines[:section_end] + key_lines + lines[section_end:]
        
        # Write file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        
        return True
    
    except Exception as e:
        print(f"[SettingsWindow] Error saving config: {e}")
        return False


def _find_section_end(lines: List[str], section: str) -> int:
    """Find the line index where a section ends (next section or EOF)."""
    in_section = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            if in_section:
                return i
            if stripped[1:-1].lower() == section:
                in_section = True
    return len(lines) if in_section else -1


# =============================================================================
# Custom Toggle Switch (CTk version)
# =============================================================================

class ToggleSwitch(tk.Canvas):
    """Custom toggle switch widget for non-CTk mode."""
    
    def __init__(self, parent, variable: tk.BooleanVar, colors: ThemeColors, 
                 command: Optional[Callable] = None, **kwargs):
        self.width = kwargs.pop('width', 50)
        self.height = kwargs.pop('height', 24)
        super().__init__(parent, width=self.width, height=self.height, 
                        highlightthickness=0, **kwargs)
        
        self.variable = variable
        self.colors = colors
        self.command = command
        
        self.configure(bg=colors.bg)
        self.bind('<Button-1>', self._toggle)
        self.variable.trace_add('write', lambda *args: self._draw())
        self._draw()
    
    def _draw(self):
        """Draw the toggle switch."""
        self.delete('all')
        
        is_on = self.variable.get()
        
        # Track
        track_color = self.colors.accent_green if is_on else self.colors.surface1
        self.create_oval(2, 2, self.height - 2, self.height - 2, 
                        fill=track_color, outline=track_color)
        self.create_oval(self.width - self.height + 2, 2, 
                        self.width - 2, self.height - 2,
                        fill=track_color, outline=track_color)
        self.create_rectangle(self.height // 2, 2, 
                             self.width - self.height // 2, self.height - 2,
                             fill=track_color, outline=track_color)
        
        # Knob
        knob_x = self.width - self.height // 2 - 4 if is_on else self.height // 2 + 4
        self.create_oval(knob_x - 8, 4, knob_x + 8, self.height - 4,
                        fill='#ffffff', outline='#ffffff')
    
    def _toggle(self, event=None):
        """Toggle the switch."""
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()


# =============================================================================
# Settings Window (CTk version)
# =============================================================================

class SettingsWindow:
    """
    Standalone settings window using CustomTkinter.
    """
    
    def __init__(self, master=None):
        self.window_id = get_next_window_id()
        self.window_tag = f"settings_{self.window_id}"
        
        self.master = master
        self.colors = get_colors()
        self.root = None  # type: ignore
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
        
        # Determine if we can use CTk (must be in main thread)
        self.use_ctk = _can_use_ctk()
    
    def show(self, initial_tab: str = None):
        """
        Create and show the settings window.
        
        Args:
            initial_tab: Name of the tab to select initially (e.g. "API Keys")
        """
        # Sync CTk appearance mode only if we can use CTk
        if self.use_ctk:
            sync_ctk_appearance()
        
        # Load current config
        self.config_data = parse_config_full()
        self.original_config = dict(self.config_data.config)
        
        # Load from web_server if available (in-memory values)
        try:
            from ... import web_server
            for key, value in web_server.CONFIG.items():
                self.config_data.config[key] = value
        except (ImportError, AttributeError):
            pass
        
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
        
        self.root.title("AIPromptBridge Settings")
        self.root.geometry("1000x700")
        self.root.minsize(900, 600)
        
        # Set icon
        set_window_icon(self.root)
        
        # Position window
        offset = (self.window_id % 3) * 30
        self.root.geometry(f"+{100 + offset}+{100 + offset}")
        
        # Main container
        main_container = ctk.CTkFrame(self.root, fg_color=self.colors.bg) if self.use_ctk else tk.Frame(self.root, bg=self.colors.bg)
        main_container.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Title bar
        self._create_title_bar(main_container)
        
        # Notebook (tabs)
        self._create_notebook(main_container)
        
        # Select initial tab if specified
        if initial_tab and self.use_ctk:
            try:
                # Try exact match first
                self.tabview.set(initial_tab)
            except ValueError:
                # Try to find a matching tab (ignoring emoji prefix)
                # Tab names are like "🔑 API Keys"
                found = False
                # List of known tabs with emojis
                known_tabs = ["⚙️ General", "🌐 Provider", "⚡ Streaming",
                             "🔧 Tools", "🔑 API Keys", "🔗 Endpoints", "🎨 Theme"]
                
                for tab_name in known_tabs:
                    # Check for suffix match or containment
                    if initial_tab in tab_name:
                        try:
                            self.tabview.set(tab_name)
                            found = True
                            break
                        except ValueError:
                            pass
                
                if not found:
                    print(f"[Settings] Could not find initial tab '{initial_tab}'")
        
        # Button bar
        self._create_button_bar(main_container)
        
        # Register and bind
        register_window(self.window_tag)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind('<Escape>', lambda e: self._close())
        
        # Focus
        self.root.lift()
        self.root.focus_force()
        
        # Handle protocol for errors
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
            # Benign error during shutdown
            return
        # Print real errors
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
                    
                    # Process any pending callbacks from background threads
                    self._process_callback_queue()
                    
                    time.sleep(0.01)
                except tk.TclError:
                    break
        except Exception:
            pass
        finally:
            # Ensure proper cleanup when loop exits
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
    
    def _schedule_callback(self, callback: Callable):
        """
        Schedule a callback to run on the GUI thread.
        Works both when attached to master and when standalone.
        """
        if self._destroyed:
            return
        
        if self.master:
            # When attached to a master, use GUICoordinator to run on GUI thread
            # (calling self.root.after() from a background thread would fail)
            try:
                from ..core import GUICoordinator

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
            # When standalone, use the queue (processed in _run_event_loop)
            self._callback_queue.put(callback)
    
    def _create_title_bar(self, parent):
        """Create the title bar."""
        title_frame = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        title_frame.pack(fill="x", pady=(0, 10))
        
        if self.use_ctk:
            # Title with emoji image support
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
                    
            ctk.CTkLabel(
                title_frame,
                **title_label_kwargs
            ).pack(side="left")
            
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
        """Create the tabbed notebook."""
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
                corner_radius=8
            )
            self.tabview.pack(fill="both", expand=True, pady=(0, 2))
            
            # Create tabs
            self.tabview.add("⚙️ General")
            self.tabview.add("🌐 Provider")
            self.tabview.add("⚡ Streaming")
            self.tabview.add("🔧 Tools")
            self.tabview.add("🔑 API Keys")
            self.tabview.add("🔗 Endpoints")
            self.tabview.add("🎨 Theme")
            
            # Upgrade tabs with images and larger font
            upgrade_tabview_with_icons(self.tabview)
            
            self._create_general_tab(self.tabview.tab("⚙️ General"))
            self._create_provider_tab(self.tabview.tab("🌐 Provider"))
            self._create_streaming_tab(self.tabview.tab("⚡ Streaming"))
            self._create_tools_tab(self.tabview.tab("🔧 Tools"))
            self._create_keys_tab(self.tabview.tab("🔑 API Keys"))
            self._create_endpoints_tab(self.tabview.tab("🔗 Endpoints"))
            self._create_theme_tab(self.tabview.tab("🎨 Theme"))
        else:
            from tkinter import ttk
            style = ttk.Style(self.root)
            style.theme_use('clam')
            self.tabview = ttk.Notebook(parent)
            self.tabview.pack(fill="both", expand=True, pady=(0, 2))
            
            tabs = ["General", "Provider", "Streaming", "Tools", "API Keys", "Endpoints", "Theme"]
            frames = {}
            for tab_name in tabs:
                frame = tk.Frame(self.tabview, bg=self.colors.bg)
                self.tabview.add(frame, text=tab_name)
                frames[tab_name] = frame
            
            self._create_general_tab(frames["General"])
            self._create_provider_tab(frames["Provider"])
            self._create_streaming_tab(frames["Streaming"])
            self._create_tools_tab(frames["Tools"])
            self._create_keys_tab(frames["API Keys"])
            self._create_endpoints_tab(frames["Endpoints"])
            self._create_theme_tab(frames["Theme"])
    
    def _create_general_tab(self, frame):
        """Create the General settings tab."""
        if self.use_ctk:
            scroll_frame = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        else:
            scroll_frame = tk.Frame(frame, bg=self.colors.bg)
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Server settings section
        create_section_header(scroll_frame, "🖥️ Server Settings", self.colors)
        
        # Host
        self._add_entry_field(scroll_frame, "host", "Host:",
                             self.config_data.config.get("host", "127.0.0.1"),
                             hint="⚠️ Restart required. IP address to bind.")
        
        # Port
        self._add_entry_field(scroll_frame, "port", "Port:",
                             str(self.config_data.config.get("port", 5000)),
                             hint="⚠️ Restart required. Port for Flask server (1-65535)")
        
        # Behavior section
        create_section_header(scroll_frame, "🧠 Behavior", self.colors, top_padding=20)
        
        # Show AI response in chat window
        self._add_toggle_field(scroll_frame, "show_ai_response_in_chat_window",
                              "Show AI response in chat window",
                              self.config_data.config.get("show_ai_response_in_chat_window", False),
                              hint="For direct chat popup and endpoint requests. Actions/modifiers override this.")
        
        # Session Auto-Save
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        self.vars["auto_save_session"] = tk.StringVar(
            master=self.root, value=self.config_data.config.get("auto_save_session", "on_attachment"))
        
        if self.use_ctk:
            ctk.CTkLabel(row, text="New session auto-creation:", font=get_ctk_font(13), width=180, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.widgets["auto_save_session"] = ctk.CTkComboBox(
                row, variable=self.vars["auto_save_session"],
                values=["on_attachment", "always_window", "on_followup"],
                width=160, height=34, state="readonly", font=get_ctk_font(13),
                **get_ctk_combobox_colors(self.colors)
            )
            self.widgets["auto_save_session"].pack(side="left", padx=(12, 0))
            
            ctk.CTkLabel(row, text="Creation trigger: reply (on_followup), open (always_window), or has files (on_attachment)", font=get_ctk_font(11),
                        **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(15, 0))
        else:
            from tkinter import ttk
            tk.Label(row, text="New session auto-creation:", font=("Segoe UI", 10), width=18, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.widgets["auto_save_session"] = ttk.Combobox(
                row, textvariable=self.vars["auto_save_session"],
                values=["on_attachment", "always_window", "on_followup"],
                state="readonly", width=18
            )
            self.widgets["auto_save_session"].pack(side="left", padx=(10, 0))
            
            tk.Label(row, text="Creation trigger: reply (on_followup), open (always_window), or has files (on_attachment)", font=("Segoe UI", 9),
                    bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))

        # Limits section
        create_section_header(scroll_frame, "🚦 Limits", self.colors, top_padding=20)
        
        # Max sessions
        self._add_spinbox_field(scroll_frame, "max_sessions", "Max sessions:",
                               self.config_data.config.get("max_sessions", 50),
                               1, 1000, hint="Maximum chat sessions to keep")
        
        # Max retries
        self._add_spinbox_field(scroll_frame, "max_retries", "Max retries:",
                               self.config_data.config.get("max_retries", 3),
                               0, 10, hint="Retries before giving up on API calls")
        
        # Retry delay
        self._add_spinbox_field(scroll_frame, "retry_delay", "Retry delay (s):",
                               self.config_data.config.get("retry_delay", 5),
                               1, 60, hint="Seconds to wait between retries")
        
        # Request timeout
        self._add_spinbox_field(scroll_frame, "request_timeout", "Request timeout (s):",
                               self.config_data.config.get("request_timeout", 120),
                               10, 600, hint="Timeout for API requests")

        # Image Storage section
        create_section_header(scroll_frame, "🖼️ Session Images", self.colors, top_padding=20)
        
        # Image Format
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        self.vars["session_image_format"] = tk.StringVar(
            master=self.root, value=self.config_data.config.get("session_image_format", "webp"))
            
        if self.use_ctk:
            ctk.CTkLabel(row, text="Image format:", font=get_ctk_font(13), width=180, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.widgets["session_image_format"] = ctk.CTkComboBox(
                row, variable=self.vars["session_image_format"],
                values=["webp", "png", "jpg", "avif"],
                width=120, height=34, state="readonly", font=get_ctk_font(13),
                **get_ctk_combobox_colors(self.colors)
            )
            self.widgets["session_image_format"].pack(side="left", padx=(12, 0))
            
            ctk.CTkLabel(row, text="Storage format for chat attachments", font=get_ctk_font(11),
                        **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(15, 0))
        else:
            from tkinter import ttk
            tk.Label(row, text="Image format:", font=("Segoe UI", 10), width=18, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.widgets["session_image_format"] = ttk.Combobox(
                row, textvariable=self.vars["session_image_format"],
                values=["webp", "png", "jpg", "avif"],
                state="readonly", width=12
            )
            self.widgets["session_image_format"].pack(side="left", padx=(10, 0))
            
            tk.Label(row, text="Storage format for chat attachments", font=("Segoe UI", 9),
                    bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))

        # Image Quality
        self._add_spinbox_field(scroll_frame, "session_image_quality", "Quality (1-100):",
                               self.config_data.config.get("session_image_quality", 85),
                               1, 100, hint="Compression level for webp/jpg/avif")
    
    def _create_provider_tab(self, frame):
        """Create the Provider settings tab."""
        if self.use_ctk:
            scroll_frame = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        else:
            scroll_frame = tk.Frame(frame, bg=self.colors.bg)
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Default provider
        create_section_header(scroll_frame, "🥇 Default Provider", self.colors)
        
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        current_provider = self.config_data.config.get("default_provider", "google")
        self.vars["default_provider"] = tk.StringVar(master=self.root, value=current_provider)
        
        if self.use_ctk:
            ctk.CTkLabel(row, text="Provider:", font=get_ctk_font(13), width=160, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.widgets["default_provider"] = ctk.CTkComboBox(
                row, variable=self.vars["default_provider"],
                values=["custom", "openrouter", "google"],
                width=220, height=32, state="readonly", font=get_ctk_font(13),
                **get_ctk_combobox_colors(self.colors)
            )
        else:
            from tkinter import ttk
            tk.Label(row, text="Provider:", font=("Segoe UI", 10), width=15, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.widgets["default_provider"] = ttk.Combobox(
                row, textvariable=self.vars["default_provider"],
                values=["custom", "openrouter", "google"],
                state="readonly", width=25
            )
        self.widgets["default_provider"].pack(side="left", padx=(10, 0))
        
        if self.use_ctk:
            ctk.CTkLabel(row, text="Provider for requests (can be overriden by endpoint parameters)", font=get_ctk_font(11),
                        **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(15, 0))
        else:
             tk.Label(row, text="Provider for requests (can be overriden by endpoint parameters)", font=("Segoe UI", 9),
                     bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))
        
        # Custom provider settings
        create_section_header(scroll_frame, "🛠️ Custom Provider", self.colors, top_padding=20)
        
        self._add_entry_field(scroll_frame, "custom_url", "URL:",
                             self.config_data.config.get("custom_url", "") or "",
                             width=400, hint="OpenAI-compatible endpoint URL")
        
        # Model dropdown with refresh button
        self._add_model_dropdown_field(scroll_frame, "custom_model", "Model:",
                                       self.config_data.config.get("custom_model", "") or "",
                                       provider="custom", width=300)
        
        # OpenRouter settings
        create_section_header(scroll_frame, "🚀 OpenRouter", self.colors, top_padding=20)
        
        # Model dropdown with refresh button
        self._add_model_dropdown_field(scroll_frame, "openrouter_model", "Model:",
                                       self.config_data.config.get("openrouter_model", ""),
                                       provider="openrouter", width=300)
        
        # Google settings
        create_section_header(scroll_frame, "💎 Google Gemini", self.colors, top_padding=20)
        
        # Model dropdown with refresh button
        self._add_model_dropdown_field(scroll_frame, "google_model", "Model:",
                                       self.config_data.config.get("google_model", ""),
                                       provider="google", width=300)
    
    def _create_streaming_tab(self, frame):
        """Create the Streaming/Thinking settings tab."""
        if self.use_ctk:
            scroll_frame = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        else:
            scroll_frame = tk.Frame(frame, bg=self.colors.bg)
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Streaming section
        create_section_header(scroll_frame, "🌊 Streaming", self.colors)
        
        self._add_toggle_field(scroll_frame, "streaming_enabled",
                              "Enable streaming responses",
                              self.config_data.config.get("streaming_enabled", True),
                              hint="Type answer word-by-word instead of waiting for full response and then pasting")
        
        # Thinking section
        create_section_header(scroll_frame, "💭 Thinking / Reasoning", self.colors, top_padding=20)
        
        self._add_toggle_field(scroll_frame, "thinking_enabled",
                              "Enable thinking mode",
                              self.config_data.config.get("thinking_enabled", False),
                              hint="Enable sending thinking parameters")
        
        # Thinking output dropdown
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        self.vars["thinking_output"] = tk.StringVar(
            master=self.root, value=self.config_data.config.get("thinking_output", "reasoning_content"))
        
        if self.use_ctk:
            ctk.CTkLabel(row, text="Thinking output:", font=get_ctk_font(13), width=180, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.widgets["thinking_output"] = ctk.CTkComboBox(
                row, variable=self.vars["thinking_output"],
                values=["filter", "raw", "reasoning_content"],
                width=200, height=32, state="readonly", font=get_ctk_font(13),
                **get_ctk_combobox_colors(self.colors)
            )
        else:
            from tkinter import ttk
            tk.Label(row, text="Thinking output:", font=("Segoe UI", 10), width=18, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.widgets["thinking_output"] = ttk.Combobox(
                row, textvariable=self.vars["thinking_output"],
                values=["filter", "raw", "reasoning_content"],
                state="readonly", width=20
            )
        self.widgets["thinking_output"].pack(side="left", padx=(10, 0))
        
        # Explanation for thinking output modes
        explanation = "filter: Hide thinking content | raw: Include thinking in main response | reasoning_content: Separate field (collapsible)"
        if self.use_ctk:
             ctk.CTkLabel(row, text=explanation, font=get_ctk_font(11),
                         **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(15, 0))
        else:
             tk.Label(row, text=explanation, font=("Segoe UI", 9),
                     bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))
        
        # Thinking config section
        create_section_header(scroll_frame, "Thinking Configuration", self.colors, top_padding=20)
        
        # Reasoning effort (OpenAI)
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        self.vars["reasoning_effort"] = tk.StringVar(
            master=self.root, value=self.config_data.config.get("reasoning_effort", "high"))
        
        if self.use_ctk:
            ctk.CTkLabel(row, text="Reasoning effort (OpenAI):", font=get_ctk_font(13), width=200, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.widgets["reasoning_effort"] = ctk.CTkComboBox(
                row, variable=self.vars["reasoning_effort"],
                values=["low", "medium", "high"],
                width=150, height=32, state="readonly", font=get_ctk_font(13),
                **get_ctk_combobox_colors(self.colors)
            )
        else:
            from tkinter import ttk
            tk.Label(row, text="Reasoning effort (OpenAI):", font=("Segoe UI", 10), width=22, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.widgets["reasoning_effort"] = ttk.Combobox(
                row, textvariable=self.vars["reasoning_effort"],
                values=["low", "medium", "high"],
                state="readonly", width=12
            )
        self.widgets["reasoning_effort"].pack(side="left", padx=(10, 0))
        if self.use_ctk:
             ctk.CTkLabel(row, text="Set how much the model will think for reasoning/thinking models", font=get_ctk_font(11),
                         **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(15, 0))
        else:
             tk.Label(row, text="Set how much the model will think for reasoning/thinking models", font=("Segoe UI", 9),
                     bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))
        
        # Thinking budget (Gemini 2.5)
        self._add_spinbox_field(scroll_frame, "thinking_budget", "Thinking budget:",
                               self.config_data.config.get("thinking_budget", -1),
                               -1, 100000, hint="For Gemini 2.5 models. -1 = auto.")
        
        # Thinking level (Gemini 3.x)
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        self.vars["thinking_level"] = tk.StringVar(
            master=self.root, value=self.config_data.config.get("thinking_level", "high"))
        
        if self.use_ctk:
            ctk.CTkLabel(row, text="Thinking level (Gemini 3.x):", font=get_ctk_font(13), width=200, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.widgets["thinking_level"] = ctk.CTkComboBox(
                row, variable=self.vars["thinking_level"],
                values=["low", "high"],
                width=150, height=32, state="readonly", font=get_ctk_font(13),
                **get_ctk_combobox_colors(self.colors)
            )
        else:
            from tkinter import ttk
            tk.Label(row, text="Thinking level:", font=("Segoe UI", 10), width=22, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.widgets["thinking_level"] = ttk.Combobox(
                row, textvariable=self.vars["thinking_level"],
                values=["low", "high"],
                state="readonly", width=12
            )
        self.widgets["thinking_level"].pack(side="left", padx=(10, 0))
        if self.use_ctk:
             ctk.CTkLabel(row, text="For Gemini 3 models", font=get_ctk_font(11),
                         **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(15, 0))
        else:
             tk.Label(row, text="For Gemini 3 models", font=("Segoe UI", 9),
                     bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))
    
    def _create_tools_tab(self, frame):
        """Create the Tools settings tab (TextEditTool + ScreenSnip)."""
        if self.use_ctk:
            scroll_frame = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        else:
            scroll_frame = tk.Frame(frame, bg=self.colors.bg)
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # TextEditTool section
        create_section_header(scroll_frame, "✏️ TextEditTool", self.colors)
        
        self._add_toggle_field(scroll_frame, "text_edit_tool_enabled",
                              "Enable TextEditTool",
                              self.config_data.config.get("text_edit_tool_enabled", True),
                              hint="⚠️ Restart required")
        
        self._add_entry_field(scroll_frame, "text_edit_tool_hotkey", "Activation hotkey:",
                             self.config_data.config.get("text_edit_tool_hotkey", "ctrl+space"),
                             width=200, hint="⚠️ Restart required")
        
        self._add_entry_field(scroll_frame, "text_edit_tool_abort_hotkey", "Abort hotkey:",
                             self.config_data.config.get("text_edit_tool_abort_hotkey", "escape"),
                             width=200, hint="⚠️ Restart required")
        
        # ScreenSnip section
        create_section_header(scroll_frame, "📸 ScreenSnip", self.colors, top_padding=20)
        
        self._add_toggle_field(scroll_frame, "screen_snip_enabled",
                              "Enable ScreenSnip",
                              self.config_data.config.get("screen_snip_enabled", True),
                              hint="⚠️ Restart required")
        
        self._add_entry_field(scroll_frame, "screen_snip_hotkey", "ScreenSnip hotkey:",
                             self.config_data.config.get("screen_snip_hotkey", "ctrl+shift+x"),
                             width=200, hint="⚠️ Restart required")
        
        # Audio Tool section
        create_section_header(scroll_frame, "🎤 Audio Tool", self.colors, top_padding=20)
        
        self._add_toggle_field(scroll_frame, "audio_tool_enabled",
                              "Enable Audio Tool",
                              self.config_data.config.get("audio_tool_enabled", True),
                              hint="⚠️ Restart required")
        
        self._add_entry_field(scroll_frame, "audio_tool_hotkey", "Audio Tool hotkey:",
                             self.config_data.config.get("audio_tool_hotkey", "ctrl+shift+a"),
                             width=200, hint="⚠️ Restart required")
        
        self._add_entry_field(scroll_frame, "audio_default_device", "Default device:",
                             self.config_data.config.get("audio_default_device", "") or "",
                             width=300, hint="Partial name match (blank = system default)")
        
        self._add_toggle_field(scroll_frame, "audio_default_loopback",
                              "Default to loopback (system audio)",
                              self.config_data.config.get("audio_default_loopback", True),
                              hint="Record what you hear instead of microphone")
        
        # Level meter style section
        create_section_header(scroll_frame, "📊 Display", self.colors, top_padding=20)
        
        # Level meter style dropdown
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        self.vars["audio_level_meter_style"] = tk.StringVar(
            master=self.root, value=self.config_data.config.get("audio_level_meter_style", "canvas"))
        
        if self.use_ctk:
            ctk.CTkLabel(row, text="Level meter style:", font=get_ctk_font(13), width=180, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.widgets["audio_level_meter_style"] = ctk.CTkComboBox(
                row, variable=self.vars["audio_level_meter_style"],
                values=["canvas", "progressbar"],
                width=150, height=34, state="readonly", font=get_ctk_font(13),
                **get_ctk_combobox_colors(self.colors)
            )
            self.widgets["audio_level_meter_style"].pack(side="left", padx=(12, 0))
            
            ctk.CTkLabel(row, text="Visual style of recording meter, use canvas for gradient effect, progressbar for simple slider-like style", font=get_ctk_font(11),
                        **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(15, 0))
        else:
            from tkinter import ttk
            tk.Label(row, text="Level meter style:", font=("Segoe UI", 10), width=18, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.widgets["audio_level_meter_style"] = ttk.Combobox(
                row, textvariable=self.vars["audio_level_meter_style"],
                values=["canvas", "progressbar"],
                state="readonly", width=15
            )
            self.widgets["audio_level_meter_style"].pack(side="left", padx=(10, 0))
            
            tk.Label(row, text="Visual style of recording meter, use canvas for gradient effect, progressbar for simple slider-like style", font=("Segoe UI", 9),
                    bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))
        
        # Typing settings section
        create_section_header(scroll_frame, "🖱️ Typing Settings", self.colors, top_padding=20)
        
        self._add_spinbox_field(scroll_frame, "streaming_typing_delay", "Typing delay (ms):",
                               self.config_data.config.get("streaming_typing_delay", 5),
                               1, 100, hint="Delay per character in replace mode")
        
        self._add_toggle_field(scroll_frame, "streaming_typing_uncapped",
                              "Uncapped typing speed",
                              self.config_data.config.get("streaming_typing_uncapped", False),
                              hint="⚠️ No delay between chars. May overwhelm some apps.")
    
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
                text=f"Manage {provider} API keys (keys are masked for security). Add a name after '   # ' in the key field.",
                font=get_ctk_font(12),
                **get_ctk_label_colors(self.colors, muted=True)
            ).pack(anchor="w", pady=(0, 12))
        else:
            tk.Label(container, text=f"Manage {provider} API keys (keys are masked for security)",
                    font=("Segoe UI", 9), bg=self.colors.bg, fg=self.colors.blockquote).pack(anchor="w", pady=(0, 10))
        
        # Key list - Replace tk.Listbox with ScrollableButtonList
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

        # Initialize with config data (already in dict format from parser)
        self.widgets[f"keys_{provider}_data"] = list(self.config_data.keys.get(provider, []))
        refresh_keys_list()
        
        self.widgets[f"keys_{provider}_listbox"] = listbox
        self.widgets[f"keys_{provider}_refresh"] = refresh_keys_list
        
        # Input frame for key + name with labels
        input_frame = ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=self.colors.bg)
        input_frame.pack(fill="x", pady=(10, 0))
        
        # Add key entry with label
        if self.use_ctk:
            # API Key label
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
            
            # Name label
            ctk.CTkLabel(
                input_frame, text="Name:",
                font=get_ctk_font(12),
                **get_ctk_label_colors(self.colors)
            ).pack(side="left", padx=(0, 4))
            
            # Name entry
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
            
            # Clean up placeholder text
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
                    # Re-select the moved item (now at idx-1)
                    listbox.select(str(idx-1))
        
        def move_key_down():
            selected_id = listbox.get_selected()
            if selected_id:
                idx = int(selected_id)
                keys = self.widgets[f"keys_{provider}_data"]
                if idx < len(keys) - 1:
                    keys[idx], keys[idx+1] = keys[idx+1], keys[idx]
                    refresh_keys_list()
                    # Re-select the moved item (now at idx+1)
                    listbox.select(str(idx+1))
        
        create_emoji_button(btn_frame, "Add", "", self.colors, "success", 70, 36, add_key).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "Remove", "", self.colors, "danger", 80, 36, remove_key).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "⬆", "", self.colors, "secondary", 40, 36, move_key_up).pack(side="left", padx=3)
        create_emoji_button(btn_frame, "⬇", "", self.colors, "secondary", 40, 36, move_key_down).pack(side="left", padx=3)
    
    def _upgrade_tabs(self, tabview):
        """Invoke internals to add images to tabs and increase font size."""
        # DEPRECATED: Use custom_widgets.upgrade_tabview_with_icons
        pass

    def _mask_key(self, key_data) -> str:
        """Mask an API key for display, including name if present."""
        # Handle both dict format and legacy string format
        if isinstance(key_data, dict):
            key = key_data.get("key", "")
            name = key_data.get("name", "")
        else:
            key = str(key_data)
            name = ""
        
        if len(key) <= 8:
            masked = "*" * len(key)
        else:
            masked = key[:4] + "..." + key[-4:]
        
        if name:
            return f"{masked} ({name})"
        return masked
    
    def _collect_ui_values_for_provider(self, provider: str) -> dict:
        """
        Collect current UI values needed for model fetching.
        Must be called from the main thread before starting background work.
        
        Args:
            provider: Provider type (custom, openrouter, google)
            
        Returns:
            dict with 'custom_url', 'keys', 'error' keys
        """
        result = {"custom_url": None, "keys": [], "error": None}
        
        # Get custom URL if this is the custom provider
        if provider == "custom":
            custom_url_var = self.vars.get("custom_url")
            if custom_url_var:
                try:
                    result["custom_url"] = custom_url_var.get()
                except tk.TclError:
                    result["error"] = "Could not read custom URL"
                    return result
            else:
                result["error"] = "Custom URL not configured"
                return result
        
        # Get keys from UI (not saved config)
        keys_data = self.widgets.get(f"keys_{provider}_data", [])
        if not keys_data:
            result["error"] = f"No API keys configured for {provider}"
            return result
        
        # Extract actual keys from the dict format
        for kd in keys_data:
            if isinstance(kd, dict):
                key_str = kd.get("key", "")
                if key_str:
                    result["keys"].append(key_str)
            elif kd:
                result["keys"].append(str(kd))
        
        if not result["keys"]:
            result["error"] = f"No valid API keys for {provider}"
        
        return result
    
    def _fetch_models_with_values(self, provider: str, ui_values: dict) -> tuple:
        """
        Fetch models using pre-collected UI values.
        Safe to call from a background thread.
        
        Args:
            provider: Provider type (custom, openrouter, google)
            ui_values: Dict from _collect_ui_values_for_provider
            
        Returns:
            (model_ids: List[str], error: Optional[str])
        """
        if ui_values.get("error"):
            return [], ui_values["error"]
        
        key_strings = ui_values.get("keys", [])
        if not key_strings:
            return [], f"No valid API keys for {provider}"
        
        # Build temporary config
        temp_config = {
            "request_timeout": 30,  # Use shorter timeout for fetching
        }
        
        if provider == "custom" and ui_values.get("custom_url"):
            temp_config["custom_url"] = ui_values["custom_url"]
        
        # Create temporary KeyManager and fetch
        try:
            from ...key_manager import KeyManager
            temp_key_manager = KeyManager(key_strings, provider)

            # Create provider and fetch
            from ...api_client import get_provider_for_type
            provider_instance = get_provider_for_type(provider, temp_key_manager, temp_config)
            models, error = provider_instance.fetch_models()
            
            if error:
                return [], error
            if not models:
                return [], "No models returned"
            
            return [m.get("id", str(m)) for m in models], None
        except Exception as e:
            return [], f"Error fetching models: {e}"
    
    def _refresh_models(self, provider: str, dropdown_widget, status_label):
        """
        Refresh models in background thread, update dropdown when done.
        
        Args:
            provider: Provider type (custom, openrouter, google)
            dropdown_widget: CTkComboBox or ttk.Combobox to update
            status_label: Label widget to show status
        """
        # Collect UI values on main thread BEFORE starting background work
        ui_values = self._collect_ui_values_for_provider(provider)
        
        # Check for immediate errors
        if ui_values.get("error"):
            if self.use_ctk:
                status_label.configure(text=f"❌ {ui_values['error'][:35]}", text_color=self.colors.accent_red)
            else:
                status_label.configure(text=f"Error: {ui_values['error'][:35]}", fg=self.colors.accent_red)
            return
        
        # Show loading state
        if self.use_ctk:
            status_label.configure(text="🔄 Loading...", text_color=self.colors.accent)
        else:
            status_label.configure(text="Loading...", fg=self.colors.accent)
        
        def fetch_thread():
            # Use pre-collected values (safe in background thread)
            models, error = self._fetch_models_with_values(provider, ui_values)
            # Schedule UI update on GUI thread using thread-safe method
            if self.root and not self._destroyed:
                self._schedule_callback(lambda: self._update_model_dropdown(
                    provider, dropdown_widget, status_label, models, error
                ))
        
        threading.Thread(target=fetch_thread, daemon=True).start()
    
    def _update_model_dropdown(self, provider: str, dropdown_widget, status_label,
                               models: List[str], error: Optional[str]):
        """Update model dropdown after fetch completes."""
        if self._destroyed:
            return
        
        if error:
            if self.use_ctk:
                status_label.configure(text=f"❌ {error[:40]}", text_color=self.colors.accent_red)
            else:
                status_label.configure(text=f"Error: {error[:40]}", fg=self.colors.accent_red)
            return
        
        if not models:
            if self.use_ctk:
                status_label.configure(text="⚠️ No models found", text_color=self.colors.accent_yellow)
            else:
                status_label.configure(text="No models found", fg=self.colors.accent_yellow)
            return
        
        # Update dropdown values
        if self.use_ctk:
            dropdown_widget.configure(values=models)
            status_label.configure(text=f"✅ {len(models)} models", text_color=self.colors.accent_green)
        else:
            dropdown_widget.configure(values=models)
            status_label.configure(text=f"{len(models)} models", fg=self.colors.accent_green)
    
    def _add_model_dropdown_field(self, parent, key: str, label: str, value: str,
                                  provider: str, width: int = 300, hint: str = None):
        """
        Add a model dropdown field with refresh button.
        
        Args:
            parent: Parent widget
            key: Config key name (e.g., 'custom_model')
            label: Display label
            value: Current value
            provider: Provider type for fetching models
            width: Dropdown width
            hint: Optional hint text
        """
        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        self.vars[key] = tk.StringVar(master=self.root, value=value or "")
        
        if self.use_ctk:
            ctk.CTkLabel(row, text=label, font=get_ctk_font(13), width=180, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            
            # Create scrollable combobox for handling many models
            dropdown = ScrollableComboBox(
                row, colors=self.colors, variable=self.vars[key],
                values=[value] if value else [],
                width=width, height=34, font_size=13
            )
            dropdown.pack(side="left", padx=(12, 0))
            self.widgets[key] = dropdown
            
            # Refresh button
            refresh_btn = create_emoji_button(
                row, "", "🔄", self.colors, "secondary", 40, 34,
                command=lambda: self._refresh_models(provider, dropdown, status_label)
            )
            refresh_btn.pack(side="left", padx=(8, 0))
            
            # Status label
            status_label = ctk.CTkLabel(row, text="", font=get_ctk_font(11), width=150,
                                       **get_ctk_label_colors(self.colors, muted=True))
            status_label.pack(side="left", padx=(8, 0))
            self.widgets[f"{key}_status"] = status_label
            
            if hint:
                ctk.CTkLabel(row, text=hint, font=get_ctk_font(11),
                            **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(10, 0))
        else:
            from tkinter import ttk
            tk.Label(row, text=label, font=("Segoe UI", 10), width=18, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            
            dropdown = ttk.Combobox(
                row, textvariable=self.vars[key],
                values=[value] if value else [],
                width=width//10
            )
            dropdown.pack(side="left", padx=(10, 0))
            self.widgets[key] = dropdown
            
            # Refresh button
            refresh_btn = tk.Button(
                row, text="🔄", font=("Segoe UI", 9),
                bg=self.colors.surface1, fg=self.colors.fg,
                command=lambda: self._refresh_models(provider, dropdown, status_label)
            )
            refresh_btn.pack(side="left", padx=(6, 0))
            
            # Status label
            status_label = tk.Label(row, text="", font=("Segoe UI", 9),
                                   bg=self.colors.bg, fg=self.colors.blockquote, width=18)
            status_label.pack(side="left", padx=(6, 0))
            self.widgets[f"{key}_status"] = status_label
            
            if hint:
                tk.Label(row, text=hint, font=("Segoe UI", 9),
                        bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(10, 0))
    
    def _create_endpoints_tab(self, frame):
        """Create the Endpoints settings tab with prompts.json support."""
        # Load endpoint prompts from prompts.json
        from ..prompts import PromptsConfig
        self._prompts_config = PromptsConfig.get_instance()
        self._endpoint_prompts = dict(self._prompts_config.get_endpoint_prompts())
        
        if self.use_ctk:
            scroll_frame = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        else:
            scroll_frame = tk.Frame(frame, bg=self.colors.bg)
        scroll_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Flask Endpoints Enable toggle at top
        create_section_header(scroll_frame, "🔧 Flask Endpoints", self.colors)
        
        self._add_toggle_field(scroll_frame, "flask_endpoints_enabled",
                              "Enable Flask API Endpoints",
                              self.config_data.config.get("flask_endpoints_enabled", True),
                              hint="⚠️ Restart required. Enable/disable all Flask API endpoints.")
        
        # Main container for endpoint editor
        container = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        container.pack(fill="both", expand=True, pady=(15, 0))
        
        # Left: endpoint list
        left_panel = ctk.CTkFrame(container, fg_color="transparent", width=240) if self.use_ctk else tk.Frame(container, bg=self.colors.bg, width=240)
        left_panel.pack(side="left", fill="y", padx=(0, 15))
        left_panel.pack_propagate(False)
        
        create_section_header(left_panel, "🔗 Endpoint Prompts", self.colors)
        
        if self.use_ctk:
            ctk.CTkLabel(
                left_panel,
                text="Edit prompts from prompts.json",
                font=get_ctk_font(11),
                **get_ctk_label_colors(self.colors, muted=True)
            ).pack(anchor="w", pady=(0, 8))
        else:
            tk.Label(left_panel, text="Edit prompts from prompts.json",
                    font=("Segoe UI", 9), bg=self.colors.bg,
                    fg=self.colors.blockquote).pack(anchor="w", pady=(0, 8))
        
        # Endpoints List
        if self.use_ctk:
            self.endpoint_listbox = ScrollableButtonList(
                left_panel, self.colors, command=self._on_endpoint_select,
                corner_radius=8, fg_color=self.colors.input_bg
            )
        else:
            self.endpoint_listbox = ScrollableButtonList(left_panel, self.colors, command=self._on_endpoint_select, bg=self.colors.input_bg)
        self.endpoint_listbox.pack(fill="both", expand=True)
        
        # Populate endpoints from prompts.json
        for name in sorted(self._endpoint_prompts.keys()):
            self.endpoint_listbox.add_item(name, name, "🔗")
        
        # Right: prompt editor
        right_panel = ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=self.colors.bg)
        right_panel.pack(side="left", fill="both", expand=True)
        
        if self.use_ctk:
            ctk.CTkLabel(right_panel, text="Prompt", font=get_ctk_font(14, "bold"),
                        text_color=self.colors.accent).pack(anchor="w", pady=(0, 12))
            
            self.endpoint_text = ctk.CTkTextbox(
                right_panel, font=get_ctk_font(12), height=300,
                **get_ctk_textbox_colors(self.colors)
            )
        else:
            tk.Label(right_panel, text="Prompt", font=("Segoe UI", 11, "bold"),
                    bg=self.colors.bg, fg=self.colors.accent).pack(anchor="w", pady=(0, 10))
            
            self.endpoint_text = tk.Text(
                right_panel, font=("Segoe UI", 10), height=15,
                bg=self.colors.input_bg, fg=self.colors.fg, wrap="word"
            )
        self.endpoint_text.pack(fill="both", expand=True, pady=(0, 10))
        
        # Button row
        btn_frame = ctk.CTkFrame(right_panel, fg_color="transparent") if self.use_ctk else tk.Frame(right_panel, bg=self.colors.bg)
        btn_frame.pack(fill="x")
        
        if self.use_ctk:
            ctk.CTkButton(
                btn_frame, text="Save Prompt", font=get_ctk_font(13),
                width=140, height=38, **get_ctk_button_colors(self.colors, "success"),
                command=self._save_endpoint
            ).pack(side="left", padx=4)
            
            self.endpoint_status = ctk.CTkLabel(btn_frame, text="", font=get_ctk_font(12),
                                               text_color=self.colors.accent_green)
        else:
            tk.Button(btn_frame, text="Save Prompt", font=("Segoe UI", 10),
                     bg=self.colors.accent_green, fg="#ffffff",
                     command=self._save_endpoint).pack(side="left", padx=2)
            self.endpoint_status = tk.Label(btn_frame, text="", font=("Segoe UI", 9),
                                           bg=self.colors.bg, fg=self.colors.accent_green)
        self.endpoint_status.pack(side="left", padx=15)
    
    def _on_endpoint_select(self, name):
        """Handle endpoint selection."""
        if name:
            # Load from our local copy of endpoint prompts
            prompt = self._endpoint_prompts.get(name, "")
            if self.use_ctk:
                self.endpoint_text.delete("0.0", "end")
                self.endpoint_text.insert("0.0", prompt)
            else:
                self.endpoint_text.delete("1.0", "end")
                self.endpoint_text.insert("1.0", prompt)
    
    def _save_endpoint(self):
        """Save the currently edited endpoint to prompts.json."""
        name = self.endpoint_listbox.get_selected()
        if name:
            if self.use_ctk:
                prompt = self.endpoint_text.get("0.0", "end").strip()
            else:
                prompt = self.endpoint_text.get("1.0", "end").strip()
            
            # Update local copy
            self._endpoint_prompts[name] = prompt
            
            # Save to prompts.json (only endpoints section)
            if self._save_endpoint_prompts():
                if self.use_ctk:
                    self.endpoint_status.configure(text=f"✅ Saved '{name}'", text_color=self.colors.accent_green)
                else:
                    self.endpoint_status.configure(text=f"✅ Saved '{name}'", fg=self.colors.accent_green)
            else:
                if self.use_ctk:
                    self.endpoint_status.configure(text=f"❌ Failed to save", text_color=self.colors.accent_red)
                else:
                    self.endpoint_status.configure(text=f"❌ Failed to save", fg=self.colors.accent_red)
    
    def _save_endpoint_prompts(self) -> bool:
        """Save endpoint prompts to prompts.json (only endpoints section)."""
        import json
        from pathlib import Path
        
        prompts_file = Path("prompts.json")
        
        try:
            # Load existing prompts.json
            if prompts_file.exists():
                with open(prompts_file, 'r', encoding='utf-8') as f:
                    prompts_data = json.load(f)
            else:
                prompts_data = {}
            
            # Preserve _settings if it exists
            existing_settings = {}
            if "endpoints" in prompts_data and "_settings" in prompts_data["endpoints"]:
                existing_settings = prompts_data["endpoints"]["_settings"]
            
            # Update only the endpoints section
            prompts_data["endpoints"] = {
                "_settings": existing_settings,
                **self._endpoint_prompts
            }
            
            # Create backup
            if prompts_file.exists():
                import shutil
                shutil.copy2(prompts_file, prompts_file.with_suffix('.json.bak'))
            
            # Write back
            with open(prompts_file, 'w', encoding='utf-8') as f:
                json.dump(prompts_data, f, indent=2, ensure_ascii=False)
            
            # Reload PromptsConfig to pick up changes
            self._prompts_config.reload()
            
            # Also update web_server ENDPOINTS if available
            try:
                from ... import web_server
                for endpoint_name, prompt in self._endpoint_prompts.items():
                    web_server.ENDPOINTS[endpoint_name] = prompt
                print(f"[Settings] Reloaded {len(self._endpoint_prompts)} endpoint prompt(s)")
            except (ImportError, AttributeError):
                pass
            
            return True
        except Exception as e:
            print(f"[Settings] Error saving endpoint prompts: {e}")
            return False
    
    def _create_theme_tab(self, frame):
        """Create the Theme settings tab."""
        if self.use_ctk:
            scroll_frame = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        else:
            scroll_frame = tk.Frame(frame, bg=self.colors.bg)
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Theme selection
        create_section_header(scroll_frame, "UI Theme", self.colors)
        
        # Theme dropdown
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        current_theme = self.config_data.config.get("ui_theme", "catppuccin")
        self.vars["ui_theme"] = tk.StringVar(master=self.root, value=current_theme)
        
        if self.use_ctk:
            ctk.CTkLabel(row, text="Theme:", font=get_ctk_font(14), width=120, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.widgets["ui_theme"] = ctk.CTkComboBox(
                row, variable=self.vars["ui_theme"],
                values=list_themes(), width=200, height=34, state="readonly", font=get_ctk_font(13),
                **get_ctk_combobox_colors(self.colors),
                command=lambda x: self._update_theme_preview()
            )
        else:
            from tkinter import ttk
            tk.Label(row, text="Theme:", font=("Segoe UI", 10), width=12, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.widgets["ui_theme"] = ttk.Combobox(
                row, textvariable=self.vars["ui_theme"],
                values=list_themes(), state="readonly", width=20
            )
            self.widgets["ui_theme"].bind('<<ComboboxSelected>>', lambda e: self._update_theme_preview())
        self.widgets["ui_theme"].pack(side="left", padx=(10, 0))
        
        # Mode dropdown
        row = ctk.CTkFrame(scroll_frame, fg_color="transparent") if self.use_ctk else tk.Frame(scroll_frame, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        current_mode = self.config_data.config.get("ui_theme_mode", "auto")
        self.vars["ui_theme_mode"] = tk.StringVar(master=self.root, value=current_mode)
        
        if self.use_ctk:
            ctk.CTkLabel(row, text="Mode:", font=get_ctk_font(14), width=120, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            self.widgets["ui_theme_mode"] = ctk.CTkComboBox(
                row, variable=self.vars["ui_theme_mode"],
                values=["auto", "dark", "light"], width=150, height=34, state="readonly", font=get_ctk_font(13),
                **get_ctk_combobox_colors(self.colors),
                command=lambda x: self._update_theme_preview()
            )
        else:
            from tkinter import ttk
            tk.Label(row, text="Mode:", font=("Segoe UI", 10), width=12, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            self.widgets["ui_theme_mode"] = ttk.Combobox(
                row, textvariable=self.vars["ui_theme_mode"],
                values=["auto", "dark", "light"], state="readonly", width=12
            )
            self.widgets["ui_theme_mode"].bind('<<ComboboxSelected>>', lambda e: self._update_theme_preview())
        self.widgets["ui_theme_mode"].pack(side="left", padx=(10, 0))
        
        # Framework section
        create_section_header(scroll_frame, "🔧 Framework", self.colors, top_padding=20)
        
        self._add_toggle_field(scroll_frame, "ui_force_standard_tk",
                              "Force Standard Tkinter (Disable Modern UI)",
                              self.config_data.config.get("ui_force_standard_tk", False),
                              hint="⚠️ Restart required. Use if CustomTkinter causes performance issues.")
        
        # Preview section
        create_section_header(scroll_frame, "Preview", self.colors, top_padding=20)
        
        # Preview frame
        if self.use_ctk:
            self.preview_frame = ctk.CTkFrame(
                scroll_frame, fg_color=self.colors.surface0,
                corner_radius=10, border_width=1, border_color=self.colors.border
            )
        else:
            self.preview_frame = tk.Frame(scroll_frame, bg=self.colors.surface0,
                                         highlightbackground=self.colors.border, highlightthickness=1)
        self.preview_frame.pack(fill="x", pady=5)
        
        self._update_theme_preview()
    
    def _update_theme_preview(self, event=None):
        """Update the theme preview."""
        if not self.preview_frame:
            return
        
        # Clear preview
        for widget in self.preview_frame.winfo_children():
            widget.destroy()
        
        # Get preview colors
        theme_name = self.vars["ui_theme"].get()
        mode = self.vars["ui_theme_mode"].get()
        
        if mode == "auto":
            is_dark = ThemeRegistry.is_dark_mode()
        else:
            is_dark = mode == "dark"
        
        preview_colors = ThemeRegistry.get_theme(theme_name, "dark" if is_dark else "light")
        
        # Update preview frame background
        if self.use_ctk:
            self.preview_frame.configure(fg_color=preview_colors.bg)
        else:
            self.preview_frame.configure(bg=preview_colors.bg)
        
        # Add sample elements
        inner = ctk.CTkFrame(self.preview_frame, fg_color="transparent") if self.use_ctk else tk.Frame(self.preview_frame, bg=preview_colors.bg)
        inner.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Title
        if self.use_ctk:
            ctk.CTkLabel(
                inner,
                text=f"Theme: {theme_name.title()} ({'Dark' if is_dark else 'Light'})",
                font=get_ctk_font(16, "bold"),
                text_color=preview_colors.fg
            ).pack(anchor="w")
            
            ctk.CTkLabel(
                inner,
                text="This is how text will look in this theme.",
                font=get_ctk_font(13),
                text_color=preview_colors.fg
            ).pack(anchor="w", pady=(8, 0))
            
            ctk.CTkLabel(
                inner,
                text="Muted/secondary text appears like this.",
                font=get_ctk_font(12),
                text_color=preview_colors.blockquote
            ).pack(anchor="w")
        else:
            tk.Label(inner, text=f"Theme: {theme_name.title()} ({'Dark' if is_dark else 'Light'})",
                    font=("Segoe UI", 12, "bold"),
                    bg=preview_colors.bg, fg=preview_colors.fg).pack(anchor="w")
            tk.Label(inner, text="This is how text will look in this theme.",
                    font=("Segoe UI", 10),
                    bg=preview_colors.bg, fg=preview_colors.fg).pack(anchor="w", pady=(5, 0))
            tk.Label(inner, text="Muted/secondary text appears like this.",
                    font=("Segoe UI", 9),
                    bg=preview_colors.bg, fg=preview_colors.blockquote).pack(anchor="w")
        
        # Sample buttons row
        btn_row = ctk.CTkFrame(inner, fg_color="transparent") if self.use_ctk else tk.Frame(inner, bg=preview_colors.bg)
        btn_row.pack(anchor="w", pady=(10, 0))
        
        for label, color in [("Primary", preview_colors.accent),
                            ("Success", preview_colors.accent_green),
                            ("Warning", preview_colors.accent_yellow),
                            ("Danger", preview_colors.accent_red)]:
            fg = "#ffffff" if label != "Warning" else "#000000"
            if self.use_ctk:
                ctk.CTkLabel(
                    btn_row, text=label, font=get_ctk_font(12),
                    fg_color=color, text_color=fg,
                    corner_radius=6, padx=14, pady=5
                ).pack(side="left", padx=4)
            else:
                tk.Label(btn_row, text=label, font=("Segoe UI", 9),
                        bg=color, fg=fg, padx=10, pady=3).pack(side="left", padx=2)
        
        # Sample input
        if self.use_ctk:
            sample_entry = ctk.CTkEntry(
                inner, font=get_ctk_font(12), width=240, height=34,
                fg_color=preview_colors.input_bg,
                text_color=preview_colors.fg,
                border_color=preview_colors.border
            )
            sample_entry.pack(anchor="w", pady=(12, 0))
            sample_entry.insert(0, "Sample input field")
        else:
            sample_entry = tk.Entry(inner, font=("Segoe UI", 10),
                                   bg=preview_colors.input_bg, fg=preview_colors.fg)
            sample_entry.insert(0, "Sample input field")
            sample_entry.pack(anchor="w", pady=(10, 0))
    
    # Helper methods for creating form fields
    
    def _add_entry_field(self, parent, key: str, label: str, value: str,
                        width: int = 240, hint: str = None):
        """Add an entry field to the form."""
        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        self.vars[key] = tk.StringVar(master=self.root, value=value)
        
        if self.use_ctk:
            ctk.CTkLabel(row, text=label, font=get_ctk_font(13), width=180, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            entry = ctk.CTkEntry(
                row, textvariable=self.vars[key],
                font=get_ctk_font(13), width=width, height=34,
                **get_ctk_entry_colors(self.colors)
            )
            entry.pack(side="left", padx=(12, 0))
            self.widgets[key] = entry
            
            if hint:
                ctk.CTkLabel(row, text=hint, font=get_ctk_font(11),
                            **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(15, 0))
        else:
            tk.Label(row, text=label, font=("Segoe UI", 10), width=18, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            entry = tk.Entry(row, textvariable=self.vars[key],
                            font=("Segoe UI", 10), width=width//8,
                            bg=self.colors.input_bg, fg=self.colors.fg)
            entry.pack(side="left", padx=(10, 0), ipady=4)
            self.widgets[key] = entry
            
            if hint:
                tk.Label(row, text=hint, font=("Segoe UI", 9),
                        bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))
    
    def _add_toggle_field(self, parent, key: str, label: str, value: bool, hint: str = None):
        """Add a toggle switch field to the form."""
        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        self.vars[key] = tk.BooleanVar(master=self.root, value=value)
        
        if self.use_ctk:
            self.widgets[key] = ctk.CTkSwitch(
                row, text=label, variable=self.vars[key],
                font=get_ctk_font(13), text_color=self.colors.fg,
                fg_color=self.colors.surface2,
                progress_color=self.colors.accent,
                button_color="#ffffff",
                button_hover_color="#f0f0f0"
            )
            self.widgets[key].pack(side="left")
            
            if hint:
                ctk.CTkLabel(row, text=hint, font=get_ctk_font(11),
                            **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(15, 0))
        else:
            tk.Label(row, text=label, font=("Segoe UI", 10),
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            toggle = ToggleSwitch(row, self.vars[key], self.colors)
            toggle.pack(side="left", padx=(10, 0))
            self.widgets[key] = toggle
            
            if hint:
                tk.Label(row, text=hint, font=("Segoe UI", 9),
                        bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))
    
    def _add_spinbox_field(self, parent, key: str, label: str, value: int,
                          min_val: int, max_val: int, hint: str = None):
        """Add a spinbox field to the form."""
        row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        row.pack(fill="x", pady=8)
        
        # Use StringVar instead of IntVar to avoid TclError when field is cleared
        self.vars[key] = tk.StringVar(master=self.root, value=str(value) if value is not None else "")
        
        # Store metadata for validation and default value restoration
        self.widgets[f"{key}_default"] = value
        self.widgets[f"{key}_min"] = min_val
        self.widgets[f"{key}_max"] = max_val
        
        if self.use_ctk:
            ctk.CTkLabel(row, text=label, font=get_ctk_font(13), width=200, anchor="w",
                        **get_ctk_label_colors(self.colors)).pack(side="left")
            # CTk doesn't have spinbox, use entry
            entry = ctk.CTkEntry(
                row, textvariable=self.vars[key],
                font=get_ctk_font(13), width=100, height=34,
                **get_ctk_entry_colors(self.colors)
            )
            entry.pack(side="left", padx=(12, 0))
            self.widgets[key] = entry
            
            if hint:
                ctk.CTkLabel(row, text=hint, font=get_ctk_font(11),
                            **get_ctk_label_colors(self.colors, muted=True)).pack(side="left", padx=(15, 0))
        else:
            from tkinter import ttk
            tk.Label(row, text=label, font=("Segoe UI", 10), width=22, anchor="w",
                    bg=self.colors.bg, fg=self.colors.fg).pack(side="left")
            spinbox = ttk.Spinbox(row, textvariable=self.vars[key],
                                 from_=min_val, to=max_val, width=10)
            spinbox.pack(side="left", padx=(10, 0))
            self.widgets[key] = spinbox
            
            if hint:
                tk.Label(row, text=hint, font=("Segoe UI", 9),
                        bg=self.colors.bg, fg=self.colors.blockquote).pack(side="left", padx=(15, 0))
    
    def _create_button_bar(self, parent):
        """Create the bottom button bar."""
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        btn_frame.pack(fill="x", pady=(2, 0))
        
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
    
    def _validate(self) -> tuple:
        """
        Validate all fields.
        
        Returns:
            (is_valid, error_message)
        """
        # Validate port
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
        # Validate
        is_valid, error = self._validate()
        if not is_valid:
            messagebox.showerror("Validation Error", error, parent=self.root)
            return
        
        # Collect values from widgets
        for key, var in self.vars.items():
            try:
                value = var.get()
            except tk.TclError:
                # Handle empty fields gracefully (e.g., empty integer fields)
                value = self.widgets.get(f"{key}_default", "")
            
            # Handle spinbox fields (stored as StringVar but need int conversion)
            if f"{key}_default" in self.widgets:
                try:
                    str_val = str(value).strip()
                    if str_val:
                        value = int(str_val)
                    else:
                        value = self.widgets[f"{key}_default"]
                except (ValueError, TypeError):
                    value = self.widgets[f"{key}_default"]
            
            # Handle special cases
            if key == "port":
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    value = 5000  # Default port
            
            self.config_data.config[key] = value
        
        # Collect API keys (now as list of dicts with key and name)
        for provider in ["custom", "openrouter", "google"]:
            data_key = f"keys_{provider}_data"
            if data_key in self.widgets:
                # Filter out empty keys and ensure dict format
                cleaned_keys = []
                for kd in self.widgets[data_key]:
                    if isinstance(kd, dict):
                        if kd.get("key"):
                            cleaned_keys.append(kd)
                    elif kd:  # Backward compat: plain string
                        cleaned_keys.append({"key": str(kd), "name": ""})
                self.config_data.keys[provider] = cleaned_keys
        
        # Save to file
        if save_config_full(self.config_data):
            # Update in-memory config
            try:
                from ... import web_server
                for key, value in self.config_data.config.items():
                    web_server.CONFIG[key] = value
                
                # Hot-reload API keys without restart
                for provider in ["custom", "openrouter", "google"]:
                    if provider in web_server.KEY_MANAGERS:
                        new_keys = self.config_data.keys.get(provider, [])
                        # Extract just the key strings for the KeyManager
                        key_strings = []
                        for kd in new_keys:
                            if isinstance(kd, dict):
                                key_str = kd.get("key", "")
                                if key_str:
                                    key_strings.append(key_str)
                            elif kd:
                                key_strings.append(str(kd))
                        web_server.KEY_MANAGERS[provider].keys = key_strings
                        web_server.KEY_MANAGERS[provider].current_index = 0
                        web_server.KEY_MANAGERS[provider].exhausted_keys.clear()
                        print(f"[Settings] Reloaded {len(key_strings)} {provider} API key(s)")
                
                # Hot-reload endpoints without restart
                for endpoint_name, prompt in self.config_data.endpoints.items():
                    web_server.ENDPOINTS[endpoint_name] = prompt
                print(f"[Settings] Reloaded {len(self.config_data.endpoints)} endpoint(s)")
                
            except (ImportError, AttributeError) as e:
                print(f"[Settings] Note: Could not update in-memory config: {e}")
            
            if self.use_ctk:
                self.status_label.configure(text="✅ Settings saved!", text_color=self.colors.accent_green)
            else:
                self.status_label.configure(text="✅ Settings saved!", fg=self.colors.accent_green)
            
            # Close after brief delay
            self.root.after(1500, self._close)
        else:
            if self.use_ctk:
                self.status_label.configure(text="❌ Failed to save", text_color=self.colors.accent_red)
            else:
                self.status_label.configure(text="❌ Failed to save", fg=self.colors.accent_red)
    
    def _safe_destroy(self):
        """Safely destroy the window and cleanup."""
        try:
            if self.root:
                # Suppress stderr to catch Tcl "invalid command name" errors
                # which are benign during shutdown but annoying in console.
                # Do NOT try to cancel after events as this can cause freezes.
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
                    # Fallback if redirect fails
                    try:
                        self.root.destroy()
                    except:
                        pass
        except Exception:
            pass
        self.root = None
        unregister_window(self.window_tag)

    def _close(self):
        """Close the settings window."""
        self._destroyed = True
        
        # If we have a master, we rely on the master's loop, so we must destroy now.
        # If we are standalone (no master), the manual event loop will see
        # self._destroyed and call _safe_destroy()
        if self.master:
            self._safe_destroy()


class AttachedSettingsWindow:
    """
    Settings window as Toplevel attached to GUICoordinator's root.
    Used for centralized GUI threading.
    """
    
    def __init__(self, parent_root):
        self.parent_root = parent_root
        # Run directly on GUI thread as a child window
        settings = SettingsWindow(master=parent_root)
        settings.show()


def create_attached_settings_window(parent_root):
    """Create a settings window (called on GUI thread)."""
    AttachedSettingsWindow(parent_root)


def show_settings_window():
    """Show settings window - can be called from any thread."""
    def run():
        settings = SettingsWindow()
        settings.show()
    
    threading.Thread(target=run, daemon=True).start()
