#!/usr/bin/env python3
"""
Dialog windows for the Prompt Editor.

Standalone dialog classes that can be used independently:
- EmojiPicker: Simple emoji selection popup
- ThemedInputDialog / ask_themed_string: Themed text input dialog
- TestResultDialog: Streaming API test result viewer
- PresetManagerDialog: Model preset CRUD manager (usable outside prompt editor)
"""

import queue
import tkinter as tk
from tkinter import messagebox
from typing import Callable, Optional

from ...platform import HAVE_CTK, ctk
from ...themes import (
    ThemeColors, get_colors,
    get_ctk_button_colors, get_ctk_frame_colors, get_ctk_entry_colors,
    get_ctk_textbox_colors, get_ctk_combobox_colors, get_ctk_label_colors,
    get_ctk_font
)
from ...custom_widgets import ScrollableButtonList, create_emoji_button, TkScrollableFrame
from ..utils import set_window_icon

from .data import COMMON_EMOJIS

# Import emoji renderer for CTkImage support (Windows color emoji fix)
try:
    from ...emoji_renderer import get_emoji_renderer, HAVE_PIL
    HAVE_EMOJI = HAVE_PIL and HAVE_CTK
except ImportError:
    HAVE_EMOJI = False
    get_emoji_renderer = None


# =============================================================================
# Emoji Picker (CTk version)
# =============================================================================

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
        
        self.withdraw()
        from ..utils import set_dark_titlebar
        set_dark_titlebar(self)
        set_window_icon(self)
        
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
        
        self.deiconify()
    
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
# Model Preset Manager Dialog
# =============================================================================

class PresetManagerDialog(ctk.CTkToplevel if HAVE_CTK else tk.Toplevel):
    """
    Dialog for creating, editing, and deleting model presets.
    
    Can be used standalone (outside of prompt editor) by providing
    a parent window and colors:
    
        from src.gui.windows.prompt_editor.dialogs import PresetManagerDialog
        from src.gui.themes import get_colors
        PresetManagerDialog(parent_window, get_colors())
    """
    
    PRESET_FIELDS = [
        ("provider", "Provider", "combobox", ["google", "openrouter", "custom"]),
        ("model", "Model", "entry", None),
        ("streaming", "Streaming", "checkbox", None),
        ("thinking", "Thinking", "checkbox", None),
        ("thinking_budget", "Thinking Budget", "entry", None),
        ("thinking_level", "Thinking Level", "combobox", ["", "low", "high"]),
        ("reasoning_effort", "Reasoning Effort", "combobox", ["", "low", "medium", "high"]),
        ("temperature", "Temperature", "entry", None),
        ("max_tokens", "Max Tokens", "entry", None),
        ("request_timeout", "Request Timeout", "entry", None),
        ("custom_url", "Custom URL", "entry", None),
        ("gemini_endpoint", "Gemini Endpoint", "entry", None),
        ("api_key_name", "API Key Name", "entry", None),
    ]
    
    def __init__(self, parent, colors: ThemeColors = None, on_close=None):
        super().__init__(parent)
        self.colors = colors or get_colors()
        self.on_close = on_close
        self.use_ctk = HAVE_CTK
        self.field_widgets = {}
        self.current_preset = None
        
        self.title("Manage Model Presets")
        self.geometry("700x620")
        self.minsize(600, 500)
        self.transient(parent)
        self.grab_set()
        
        if self.use_ctk:
            self.configure(fg_color=self.colors.bg)
        else:
            self.configure(bg=self.colors.bg)
        
        self.withdraw()
        from ..utils import set_dark_titlebar
        set_dark_titlebar(self)
        
        set_window_icon(self)
        self._build_ui()
        self._refresh_list()
        
        self.deiconify()
    
    def _build_ui(self):
        """Build the preset manager UI."""
        c = self.colors
        
        # Title
        if self.use_ctk:
            ctk.CTkLabel(self, text="⚙️  Model Presets", font=get_ctk_font(16, "bold"),
                        **get_ctk_label_colors(c)).pack(anchor="w", padx=20, pady=(15, 10))
        else:
            tk.Label(self, text="⚙️  Model Presets", font=("Segoe UI", 14, "bold"),
                    bg=c.bg, fg=c.fg).pack(anchor="w", padx=20, pady=(15, 10))
        
        # Main container: left list + right editor
        container = ctk.CTkFrame(self, fg_color="transparent") if self.use_ctk else tk.Frame(self, bg=c.bg)
        container.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        
        # Left panel: preset list
        left = ctk.CTkFrame(container, fg_color="transparent", width=200) if self.use_ctk else tk.Frame(container, bg=c.bg, width=200)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        
        self.preset_listbox = ScrollableButtonList(
            left, c, command=self._on_preset_select,
            **({"corner_radius": 8, "fg_color": c.input_bg} if self.use_ctk else {"bg": c.input_bg})
        )
        self.preset_listbox.pack(fill="both", expand=True)
        
        # Buttons
        btn_frame = ctk.CTkFrame(left, fg_color="transparent") if self.use_ctk else tk.Frame(left, bg=c.bg)
        btn_frame.pack(fill="x", pady=(8, 0))
        
        create_emoji_button(btn_frame, "New", "➕", c, "success", 70, 30, self._new_preset).pack(side="left", padx=2)
        create_emoji_button(btn_frame, "", "📋", c, "secondary", 35, 30, self._duplicate_preset).pack(side="left", padx=2)
        create_emoji_button(btn_frame, "", "🗑️", c, "danger", 35, 30, self._delete_preset).pack(side="left", padx=2)
        
        # Right panel: editor
        right = ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=c.bg)
        right.pack(side="left", fill="both", expand=True)
        
        # Scrollable editor area
        if self.use_ctk:
            editor = ctk.CTkScrollableFrame(right, fg_color="transparent")
        else:
            editor = TkScrollableFrame(right, bg_color=c.bg)
            editor = editor.scrollable_frame if hasattr(editor, 'scrollable_frame') else editor
        editor.pack(fill="both", expand=True) if not isinstance(editor, tk.Frame) else None
        # For TkScrollableFrame, the parent already handles packing
        try:
            editor.pack(fill="both", expand=True)
        except Exception:
            pass
        
        # Preset name
        row = ctk.CTkFrame(editor, fg_color="transparent") if self.use_ctk else tk.Frame(editor, bg=c.bg)
        row.pack(fill="x", pady=5)
        if self.use_ctk:
            ctk.CTkLabel(row, text="Preset Name:", font=get_ctk_font(13, "bold"), width=130, anchor="w",
                        **get_ctk_label_colors(c)).pack(side="left")
            self.name_var = tk.StringVar()
            self.name_entry = ctk.CTkEntry(row, textvariable=self.name_var, font=get_ctk_font(13),
                                           height=32, **get_ctk_entry_colors(c))
            self.name_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        else:
            tk.Label(row, text="Preset Name:", font=("Segoe UI", 10, "bold"), width=14, anchor="w",
                    bg=c.bg, fg=c.fg).pack(side="left")
            self.name_var = tk.StringVar()
            self.name_entry = tk.Entry(row, textvariable=self.name_var, font=("Segoe UI", 10),
                                       bg=c.input_bg, fg=c.fg)
            self.name_entry.pack(side="left", fill="x", expand=True, padx=(5, 0))
        
        # Separator
        if self.use_ctk:
            ctk.CTkFrame(editor, fg_color=c.surface1, height=1).pack(fill="x", pady=8)
        else:
            tk.Frame(editor, bg=c.surface1, height=1).pack(fill="x", pady=8)
        
        # Field note
        if self.use_ctk:
            ctk.CTkLabel(editor, text="Leave fields empty to use global defaults",
                        font=get_ctk_font(11), text_color=c.surface2).pack(anchor="w", pady=(0, 5))
        else:
            tk.Label(editor, text="Leave fields empty to use global defaults",
                    font=("Segoe UI", 9), bg=c.bg, fg=c.surface2).pack(anchor="w", pady=(0, 5))
        
        # Build fields
        for key, label, field_type, options in self.PRESET_FIELDS:
            row = ctk.CTkFrame(editor, fg_color="transparent") if self.use_ctk else tk.Frame(editor, bg=c.bg)
            row.pack(fill="x", pady=3)
            
            if field_type == "checkbox":
                var = tk.BooleanVar()
                enabled_var = tk.BooleanVar(value=False)  # Whether this override is active
                
                if self.use_ctk:
                    # Enable checkbox
                    enable_cb = ctk.CTkCheckBox(row, text="", variable=enabled_var, width=20,
                                                fg_color=c.accent, checkbox_width=18, checkbox_height=18)
                    enable_cb.pack(side="left", padx=(0, 4))
                    ctk.CTkLabel(row, text=f"{label}:", font=get_ctk_font(12), width=130, anchor="w",
                                **get_ctk_label_colors(c)).pack(side="left")
                    cb = ctk.CTkCheckBox(row, text="Enabled", variable=var,
                                         font=get_ctk_font(12), text_color=c.fg, fg_color=c.accent)
                    cb.pack(side="left", padx=(8, 0))
                else:
                    enable_cb = tk.Checkbutton(row, text="", variable=enabled_var,
                                               bg=c.bg, selectcolor=c.input_bg)
                    enable_cb.pack(side="left", padx=(0, 4))
                    tk.Label(row, text=f"{label}:", font=("Segoe UI", 9), width=14, anchor="w",
                            bg=c.bg, fg=c.fg).pack(side="left")
                    cb = tk.Checkbutton(row, text="Enabled", variable=var,
                                        bg=c.bg, fg=c.fg, selectcolor=c.input_bg)
                    cb.pack(side="left", padx=(5, 0))
                
                self.field_widgets[key] = {"var": var, "enabled_var": enabled_var, "type": "checkbox"}
            
            elif field_type == "combobox":
                var = tk.StringVar()
                if self.use_ctk:
                    ctk.CTkLabel(row, text=f"{label}:", font=get_ctk_font(12), width=150, anchor="w",
                                **get_ctk_label_colors(c)).pack(side="left")
                    combo = ctk.CTkComboBox(row, variable=var, values=options or [],
                                            width=200, height=30, state="readonly",
                                            font=get_ctk_font(12), **get_ctk_combobox_colors(c))
                    combo.pack(side="left", padx=(8, 0))
                else:
                    from tkinter import ttk as ttk_local
                    tk.Label(row, text=f"{label}:", font=("Segoe UI", 9), width=14, anchor="w",
                            bg=c.bg, fg=c.fg).pack(side="left")
                    combo = ttk_local.Combobox(row, textvariable=var, values=options or [],
                                               state="readonly", width=18)
                    combo.pack(side="left", padx=(5, 0))
                
                self.field_widgets[key] = {"var": var, "type": "combobox"}
            
            else:  # entry
                var = tk.StringVar()
                if self.use_ctk:
                    ctk.CTkLabel(row, text=f"{label}:", font=get_ctk_font(12), width=150, anchor="w",
                                **get_ctk_label_colors(c)).pack(side="left")
                    entry = ctk.CTkEntry(row, textvariable=var, font=get_ctk_font(12),
                                         height=30, width=250, **get_ctk_entry_colors(c))
                    entry.pack(side="left", padx=(8, 0))
                else:
                    tk.Label(row, text=f"{label}:", font=("Segoe UI", 9), width=14, anchor="w",
                            bg=c.bg, fg=c.fg).pack(side="left")
                    entry = tk.Entry(row, textvariable=var, font=("Segoe UI", 9),
                                     bg=c.input_bg, fg=c.fg, width=25)
                    entry.pack(side="left", padx=(5, 0))
                
                self.field_widgets[key] = {"var": var, "type": "entry"}
        
        # Save button
        btn_row = ctk.CTkFrame(right, fg_color="transparent") if self.use_ctk else tk.Frame(right, bg=c.bg)
        btn_row.pack(fill="x", pady=(10, 5))
        
        create_emoji_button(btn_row, "Save Preset", "💾", c, "success", 140, 36, self._save_preset).pack(side="left")
        
        if self.use_ctk:
            self.save_status = ctk.CTkLabel(btn_row, text="", font=get_ctk_font(11),
                                            text_color=c.accent_green)
        else:
            self.save_status = tk.Label(btn_row, text="", font=("Segoe UI", 9),
                                        bg=c.bg, fg=c.accent_green)
        self.save_status.pack(side="left", padx=12)
    
    def _refresh_list(self):
        """Refresh the preset list."""
        from ...prompts import get_prompts_config
        self.preset_listbox.clear()
        for name in get_prompts_config().get_preset_names():
            self.preset_listbox.add_item(name, name, "⚙️")
    
    def _on_preset_select(self, name):
        """Load preset into editor."""
        from ...prompts import get_prompts_config
        self.current_preset = name
        preset = get_prompts_config().get_model_preset(name) or {}
        
        self.name_var.set(name)
        
        for key, widget_info in self.field_widgets.items():
            val = preset.get(key)
            if widget_info["type"] == "checkbox":
                if val is not None:
                    widget_info["enabled_var"].set(True)
                    widget_info["var"].set(bool(val))
                else:
                    widget_info["enabled_var"].set(False)
                    widget_info["var"].set(False)
            else:
                widget_info["var"].set(str(val) if val is not None else "")
    
    def _save_preset(self):
        """Save the current preset."""
        from ...prompts import get_prompts_config
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Please enter a preset name.", parent=self)
            return
        
        preset = {}
        for key, widget_info in self.field_widgets.items():
            if widget_info["type"] == "checkbox":
                if widget_info["enabled_var"].get():
                    preset[key] = widget_info["var"].get()
            elif widget_info["type"] in ("entry", "combobox"):
                val = widget_info["var"].get().strip()
                if val:
                    # Try to convert numeric values
                    if key in ("temperature",):
                        try:
                            preset[key] = float(val)
                        except ValueError:
                            preset[key] = val
                    elif key in ("thinking_budget", "max_tokens", "request_timeout"):
                        try:
                            preset[key] = int(val)
                        except ValueError:
                            preset[key] = val
                    else:
                        preset[key] = val
        
        pc = get_prompts_config()
        
        # Handle rename
        if self.current_preset and self.current_preset != name:
            pc.delete_model_preset(self.current_preset)
        
        pc.set_model_preset(name, preset)
        self.current_preset = name
        self._refresh_list()
        self.preset_listbox.select(name)
        
        if self.use_ctk:
            self.save_status.configure(text=f"✅ Saved '{name}'")
        else:
            self.save_status.configure(text=f"✅ Saved '{name}'")
    
    def _new_preset(self):
        """Create a new empty preset."""
        name = ask_themed_string(self, "New Preset", "Enter preset name:", self.colors)
        if name:
            self.current_preset = None
            self.name_var.set(name)
            for widget_info in self.field_widgets.values():
                if widget_info["type"] == "checkbox":
                    widget_info["enabled_var"].set(False)
                    widget_info["var"].set(False)
                else:
                    widget_info["var"].set("")
    
    def _duplicate_preset(self):
        """Duplicate the selected preset and save immediately."""
        if not self.current_preset:
            return
        name = ask_themed_string(self, "Duplicate Preset", "Enter new preset name:", self.colors)
        if name:
            from ...prompts import get_prompts_config
            pc = get_prompts_config()
            source = pc.get_model_preset(self.current_preset) or {}
            pc.set_model_preset(name, dict(source))
            self.current_preset = name
            self.name_var.set(name)
            self._refresh_list()
            self.preset_listbox.select(name)
            if self.use_ctk:
                self.save_status.configure(text=f"✅ Duplicated as '{name}'")
            else:
                self.save_status.configure(text=f"✅ Duplicated as '{name}'")
    
    def _delete_preset(self):
        """Delete the selected preset."""
        if not self.current_preset:
            return
        if messagebox.askyesno("Delete Preset", f"Delete preset '{self.current_preset}'?", parent=self):
            from ...prompts import get_prompts_config
            get_prompts_config().delete_model_preset(self.current_preset)
            self.current_preset = None
            self.name_var.set("")
            for widget_info in self.field_widgets.values():
                if widget_info["type"] == "checkbox":
                    widget_info["enabled_var"].set(False)
                    widget_info["var"].set(False)
                else:
                    widget_info["var"].set("")
            self._refresh_list()
    
    def destroy(self):
        """Override destroy to call on_close callback."""
        if self.on_close:
            self.on_close()
        super().destroy()
