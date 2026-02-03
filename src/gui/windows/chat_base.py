#!/usr/bin/env python3
"""
Base classes for chat windows and session browsers.

Provides:
- ChatWindowBase: Unified base class for StandaloneChatWindow and AttachedChatWindow
- BrowserWindowBase: Unified base class for browser windows

These base classes eliminate code duplication by providing shared UI creation,
message handling, and event processing methods.
"""

import threading
import tkinter as tk
from abc import ABC, abstractmethod
from typing import Optional, Dict, List

from ..platform import HAVE_CTK, ctk
from ...utils import strip_markdown
from ...session_manager import add_session
from ..core import get_next_window_id, register_window, unregister_window
from ..utils import copy_to_clipboard, render_markdown, get_color_scheme, setup_text_tags
from ..custom_widgets import ScrollableComboBox
from ..emoji_renderer import prepare_emoji_content
from ..themes import (
    ThemeColors, get_colors, get_ctk_font,
    get_ctk_button_colors, get_ctk_frame_colors,
    get_ctk_entry_colors, get_ctk_textbox_colors, get_ctk_scrollbar_colors,
    get_ctk_combobox_colors, sync_ctk_appearance
)
from .utils import set_window_icon


class ChatWindowBase(ABC):
    """
    Base class for chat windows with unified UI creation and message handling.
    
    Subclasses must implement:
    - _create_root() -> creates the root window (CTk/Tk vs CTkToplevel/Toplevel)
    - _get_window_tag() -> return unique window tag for registration
    - _run_on_gui_thread(func) -> thread-safe callback execution (optional)
    """
    
    def __init__(self, session, initial_response: Optional[str] = None):
        self.session = session
        self.initial_response = initial_response
        
        # Window identity
        self.window_id = get_next_window_id()
        
        # Display state
        self.wrapped = True
        self.markdown = True
        self.auto_scroll = True
        self.last_response = initial_response or ""
        self.is_loading = False
        self._destroyed = False
        
        # Streaming state
        self.streaming_text = ""
        self.streaming_thinking = ""
        self.is_streaming = False
        self.thinking_collapsed_states: Dict[int, bool] = {}
        self.last_usage = None
        
        # Model selection
        self.available_models: List[Dict] = []
        from ... import web_server
        provider = web_server.CONFIG.get("default_provider", "google")
        self.selected_model = web_server.CONFIG.get(f"{provider}_model", "")
        
        # Theme
        self.theme = get_colors()
        self.colors = get_color_scheme()
        
        # UI element references (initialized in _build_ui)
        self._init_ui_refs()
    
    def _init_ui_refs(self):
        """Initialize UI element references to None."""
        self.root = None
        self.status_label = None
        self.wrap_btn = None
        self.md_btn = None
        self.scroll_btn = None
        self.send_btn = None
        self.regen_btn = None
        self.input_text = None
        self.chat_text = None
        self.model_dropdown = None
        self.h_scrollbar = None
        self.v_scrollbar = None
        # Placeholder state
        self._placeholder = "Type your follow-up message here... (Enter to send, Shift+Enter for newline)"
        self._has_placeholder = True
        # Attachment state
        self.attach_btn = None
        self.attachments_frame = None
        self.pending_attachments = []  # List of {"path": str, "thumbnail": PhotoImage, "mime_type": str}
        self._attachment_thumbnails = []  # Keep references to prevent garbage collection
    
    @abstractmethod
    def _get_window_tag(self) -> str:
        """Return unique window tag for registration."""
        pass
    
    def _safe_after(self, delay: int, func):
        """Schedule callback safely. Override for attached windows."""
        if self._destroyed:
            return
        try:
            if self.root and self.root.winfo_exists():
                self.root.after(delay, func)
        except Exception:
            pass
    
    # =========================================================================
    # UI Building
    # =========================================================================
    
    def _configure_window(self):
        """Configure window properties (title, size, position)."""
        self.root.title(f"Chat - {self.session.title or self.session.session_id}")
        self.root.geometry("750x620")
        self.root.minsize(500, 400)
        
        # Offset windows so they don't stack exactly
        offset = (self.window_id % 5) * 30
        self.root.geometry(f"+{80 + offset}+{80 + offset}")
    
    def _build_ui(self):
        """Build complete window UI."""
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)
        
        self._create_info_label()
        self._create_toolbar()
        self._create_chat_area()
        self._create_input_area()
        self._create_action_buttons()
        
        register_window(self._get_window_tag())
        self.root.protocol("WM_DELETE_WINDOW", self._close)
    
    def _create_info_label(self):
        """Create session info label."""
        from ... import web_server
        current_provider = web_server.CONFIG.get("default_provider", "google")
        info_text = f"Session: {self.session.session_id} | Endpoint: /{self.session.endpoint} | Provider: {current_provider}"
        
        if HAVE_CTK:
            ctk.CTkLabel(
                self.root,
                text=info_text,
                font=get_ctk_font(size=11),
                text_color=self.theme.blockquote
            ).grid(row=0, column=0, sticky="w", padx=15, pady=(10, 5))
        else:
            tk.Label(
                self.root, text=info_text, font=("Segoe UI", 9),
                bg=self.colors["bg"], fg=self.colors["blockquote"]
            ).grid(row=0, column=0, sticky=tk.W, padx=15, pady=(10, 5))
    
    def _create_toolbar(self):
        """Create the toolbar with toggle buttons and model dropdown."""
        if HAVE_CTK:
            btn_frame = ctk.CTkFrame(self.root, fg_color="transparent")
            btn_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=5)
            
            ctk.CTkLabel(
                btn_frame,
                text="Conversation:",
                font=get_ctk_font(size=12, weight="bold"),
                text_color=self.theme.accent
            ).pack(side="left", padx=(0, 10))
            
            btn_colors = get_ctk_button_colors(self.theme, "secondary")
            
            self.wrap_btn = ctk.CTkButton(
                btn_frame,
                text="Wrap: ON",
                font=get_ctk_font(size=11),
                width=85,
                height=28,
                corner_radius=6,
                command=self._toggle_wrap,
                **btn_colors
            )
            self.wrap_btn.pack(side="left", padx=2)
            
            self.md_btn = ctk.CTkButton(
                btn_frame,
                text="Markdown",
                font=get_ctk_font(size=11),
                width=85,
                height=28,
                corner_radius=6,
                command=self._toggle_markdown,
                **btn_colors
            )
            self.md_btn.pack(side="left", padx=2)
            
            self.scroll_btn = ctk.CTkButton(
                btn_frame,
                text="Autoscroll: ON",
                font=get_ctk_font(size=11),
                width=100,
                height=28,
                corner_radius=6,
                command=self._toggle_autoscroll,
                **btn_colors
            )
            self.scroll_btn.pack(side="left", padx=2)
            
            ctk.CTkLabel(
                btn_frame,
                text="Model:",
                font=get_ctk_font(size=11),
                text_color=self.theme.fg
            ).pack(side="left", padx=(15, 5))
            
            self.model_dropdown = ScrollableComboBox(
                btn_frame,
                colors=self.theme,
                values=["(loading...)"],
                width=220,
                height=28,
                command=self._on_model_select
            )
            self.model_dropdown.pack(side="left", padx=5)
            self.model_dropdown.set(self.selected_model or "(default)")
        else:
            from tkinter import ttk
            btn_frame = tk.Frame(self.root, bg=self.colors["bg"])
            btn_frame.grid(row=1, column=0, sticky=tk.EW, padx=15, pady=5)
            
            tk.Label(
                btn_frame, text="Conversation:", font=("Segoe UI", 10, "bold"),
                bg=self.colors["bg"], fg=self.colors["accent"]
            ).pack(side=tk.LEFT, padx=(0, 10))
            
            self.wrap_btn = tk.Button(
                btn_frame, text="Wrap: ON", font=("Segoe UI", 9),
                bg=self.colors["button_bg"], fg=self.colors["fg"],
                relief=tk.FLAT, padx=8, pady=4,
                command=self._toggle_wrap, cursor="hand2"
            )
            self.wrap_btn.pack(side=tk.LEFT, padx=2)
            
            self.md_btn = tk.Button(
                btn_frame, text="Markdown", font=("Segoe UI", 9),
                bg=self.colors["button_bg"], fg=self.colors["fg"],
                relief=tk.FLAT, padx=8, pady=4,
                command=self._toggle_markdown, cursor="hand2"
            )
            self.md_btn.pack(side=tk.LEFT, padx=2)
            
            self.scroll_btn = tk.Button(
                btn_frame, text="Autoscroll: ON", font=("Segoe UI", 9),
                bg=self.colors["button_bg"], fg=self.colors["fg"],
                relief=tk.FLAT, padx=8, pady=4,
                command=self._toggle_autoscroll, cursor="hand2"
            )
            self.scroll_btn.pack(side=tk.LEFT, padx=2)
            
            tk.Label(
                btn_frame, text="Model:", font=("Segoe UI", 9),
                bg=self.colors["bg"], fg=self.colors["fg"]
            ).pack(side=tk.LEFT, padx=(15, 5))
            
            self.model_dropdown = ttk.Combobox(
                btn_frame, values=["(loading...)"], width=30, state="readonly"
            )
            self.model_dropdown.pack(side=tk.LEFT, padx=5)
            self.model_dropdown.set(self.selected_model or "(default)")
            self.model_dropdown.bind("<<ComboboxSelected>>", lambda e: self._on_model_select(self.model_dropdown.get()))
        
        # Schedule model loading
        self._schedule_model_loading()
    
    def _schedule_model_loading(self):
        """Schedule model loading - override in subclass if needed."""
        threading.Thread(target=self._load_models, daemon=True).start()
    
    def _create_chat_area(self):
        """Create the chat display area (hybrid: CTkFrame + tk.Text for markdown)."""
        if HAVE_CTK:
            chat_frame = ctk.CTkFrame(
                self.root,
                corner_radius=10,
                fg_color=self.theme.text_bg,
                border_color=self.theme.border,
                border_width=1
            )
            chat_frame.grid(row=2, column=0, sticky="nsew", padx=15, pady=5)
            chat_frame.columnconfigure(0, weight=1)
            chat_frame.rowconfigure(0, weight=1)
            
            self.chat_text = tk.Text(
                chat_frame,
                wrap=tk.WORD,
                font=("Segoe UI", 11),
                bg=self.theme.text_bg,
                fg=self.theme.fg,
                insertbackground=self.theme.fg,
                relief=tk.FLAT,
                highlightthickness=0,
                padx=12,
                pady=12,
                borderwidth=0
            )
            self.chat_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
            
            scrollbar_colors = get_ctk_scrollbar_colors(self.theme)
            self.v_scrollbar = ctk.CTkScrollbar(
                chat_frame,
                command=self.chat_text.yview,
                corner_radius=4,
                width=14,
                **scrollbar_colors
            )
            self.v_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=8)
            self.chat_text.configure(yscrollcommand=self.v_scrollbar.set)
            
            self.h_scrollbar = ctk.CTkScrollbar(
                chat_frame,
                orientation="horizontal",
                command=self.chat_text.xview,
                corner_radius=4,
                height=14,
                **scrollbar_colors
            )
            self.h_scrollbar.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
            self.h_scrollbar.grid_remove()
            self.chat_text.configure(xscrollcommand=self.h_scrollbar.set)
        else:
            from tkinter import ttk
            chat_frame = tk.Frame(
                self.root, bg=self.colors["text_bg"],
                highlightbackground=self.colors["border"],
                highlightthickness=1
            )
            chat_frame.grid(row=2, column=0, sticky=tk.NSEW, padx=15, pady=5)
            chat_frame.columnconfigure(0, weight=1)
            chat_frame.rowconfigure(0, weight=1)
            
            self.chat_text = tk.Text(
                chat_frame,
                wrap=tk.WORD,
                font=("Segoe UI", 11),
                bg=self.colors["text_bg"],
                fg=self.colors["fg"],
                insertbackground=self.colors["fg"],
                relief=tk.FLAT,
                highlightthickness=0,
                padx=12,
                pady=12,
                borderwidth=0
            )
            self.chat_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
            
            self.v_scrollbar = ttk.Scrollbar(chat_frame, orient=tk.VERTICAL, command=self.chat_text.yview)
            self.v_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=8)
            self.chat_text.configure(yscrollcommand=self.v_scrollbar.set)
            
            self.h_scrollbar = ttk.Scrollbar(chat_frame, orient=tk.HORIZONTAL, command=self.chat_text.xview)
            self.h_scrollbar.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
            self.h_scrollbar.grid_remove()
            self.chat_text.configure(xscrollcommand=self.h_scrollbar.set)
        
        # Setup text tags for markdown
        setup_text_tags(self.chat_text, self.colors)
        self.chat_text.tag_bind("thinking_header", "<Button-1>", self._on_thinking_click)
    
    def _create_input_area(self):
        """Create the message input area with attachment button."""
        placeholder = self._placeholder
        
        if HAVE_CTK:
            # Header with attachment count
            header_frame = ctk.CTkFrame(self.root, fg_color="transparent")
            header_frame.grid(row=3, column=0, sticky="ew", padx=15, pady=(10, 5))
            
            ctk.CTkLabel(
                header_frame,
                text="Your message:",
                font=get_ctk_font(size=12, weight="bold"),
                text_color=self.theme.accent
            ).pack(side="left")
            
            # Pending attachments indicator (initially hidden)
            self._attachments_label = ctk.CTkLabel(
                header_frame,
                text="",
                font=get_ctk_font(size=11),
                text_color=self.theme.accent_yellow
            )
            self._attachments_label.pack(side="left", padx=(10, 0))
            
            input_frame = ctk.CTkFrame(self.root, fg_color="transparent")
            input_frame.grid(row=4, column=0, sticky="ew", padx=15, pady=5)
            input_frame.columnconfigure(0, weight=1)
            
            textbox_colors = get_ctk_textbox_colors(self.theme)
            self.input_text = ctk.CTkTextbox(
                input_frame,
                height=75,
                font=get_ctk_font(size=12),
                corner_radius=8,
                border_width=1,
                wrap="word",
                **textbox_colors
            )
            self.input_text.grid(row=0, column=0, sticky="ew", padx=(0, 5))
            
            # Attachment button (📎)
            attach_colors = get_ctk_button_colors(self.theme, "secondary")
            self.attach_btn = ctk.CTkButton(
                input_frame,
                text="📎",
                font=get_ctk_font(size=16),
                width=40,
                height=40,
                corner_radius=8,
                command=self._on_attach_click,
                **attach_colors
            )
            self.attach_btn.grid(row=0, column=1, sticky="n", pady=5)
            
            # Pending attachments preview frame (below input)
            self.attachments_frame = ctk.CTkFrame(self.root, fg_color="transparent", height=0)
            self.attachments_frame.grid(row=5, column=0, sticky="ew", padx=15)
            self.attachments_frame.grid_remove()  # Initially hidden
            
            self.input_text.insert("0.0", placeholder)
            self.input_text.configure(text_color=self.theme.overlay0)
            
            def on_focus_in(event):
                content = self.input_text.get("0.0", "end-1c")
                if content == placeholder:
                    self.input_text.delete("0.0", "end")
                    self.input_text.configure(text_color=self.theme.fg)
                    self._has_placeholder = False
            
            def on_focus_out(event):
                content = self.input_text.get("0.0", "end-1c").strip()
                if not content:
                    self.input_text.insert("0.0", placeholder)
                    self.input_text.configure(text_color=self.theme.overlay0)
                    self._has_placeholder = True
            
            def on_key_return(event):
                if event.state & 0x1:  # Shift held
                    return None
                else:
                    self._send()
                    return "break"
            
            def on_ctrl_backspace(event):
                try:
                    import re
                    cursor_pos = self.input_text.index(tk.INSERT)
                    line, col = map(int, cursor_pos.split('.'))
                    if col == 0:
                        return None
                    line_start = f"{line}.0"
                    text_before = self.input_text.get(line_start, cursor_pos)
                    match = re.search(r'(\s*\S+\s*)$', text_before)
                    if match:
                        delete_start = f"{line}.{col - len(match.group(0))}"
                        self.input_text.delete(delete_start, cursor_pos)
                    return "break"
                except Exception:
                    return None
            
            self.input_text.bind('<FocusIn>', on_focus_in)
            self.input_text.bind('<FocusOut>', on_focus_out)
            self.input_text.bind('<Return>', on_key_return)
            self.input_text.bind('<Control-BackSpace>', on_ctrl_backspace)
        else:
            # Header with attachment count
            header_frame = tk.Frame(self.root, bg=self.colors["bg"])
            header_frame.grid(row=3, column=0, sticky=tk.W, padx=15, pady=(10, 5))
            
            tk.Label(
                header_frame, text="Your message:", font=("Segoe UI", 10, "bold"),
                bg=self.colors["bg"], fg=self.colors["accent"]
            ).pack(side=tk.LEFT)
            
            # Pending attachments indicator
            self._attachments_label = tk.Label(
                header_frame, text="", font=("Segoe UI", 9),
                bg=self.colors["bg"], fg=self.colors["accent"]
            )
            self._attachments_label.pack(side=tk.LEFT, padx=(10, 0))
            
            input_frame = tk.Frame(self.root, bg=self.colors["bg"])
            input_frame.grid(row=4, column=0, sticky=tk.EW, padx=15, pady=5)
            input_frame.columnconfigure(0, weight=1)
            
            self.input_text = tk.Text(
                input_frame,
                height=4,
                font=("Segoe UI", 11),
                bg=self.colors["input_bg"],
                fg=self.colors["fg"],
                insertbackground=self.colors["fg"],
                relief=tk.FLAT,
                highlightbackground=self.colors["border"],
                highlightthickness=1,
                padx=8,
                pady=8,
                wrap=tk.WORD
            )
            self.input_text.grid(row=0, column=0, sticky="ew", padx=(0, 5))
            
            # Attachment button
            self.attach_btn = tk.Button(
                input_frame, text="📎", font=("Segoe UI", 14),
                bg=self.colors["button_bg"], fg=self.colors["fg"],
                relief=tk.FLAT, width=3, height=2,
                command=self._on_attach_click, cursor="hand2"
            )
            self.attach_btn.grid(row=0, column=1, sticky="n", pady=5)
            
            # Pending attachments preview frame
            self.attachments_frame = tk.Frame(self.root, bg=self.colors["bg"])
            self.attachments_frame.grid(row=5, column=0, sticky=tk.EW, padx=15)
            self.attachments_frame.grid_remove()  # Initially hidden
            
            self.input_text.insert("1.0", placeholder)
            self.input_text.configure(fg=self.colors["blockquote"])
            
            def on_focus_in(event):
                content = self.input_text.get("1.0", "end-1c")
                if content == placeholder:
                    self.input_text.delete("1.0", tk.END)
                    self.input_text.configure(fg=self.colors["fg"])
                    self._has_placeholder = False
            
            def on_focus_out(event):
                content = self.input_text.get("1.0", "end-1c").strip()
                if not content:
                    self.input_text.insert("1.0", placeholder)
                    self.input_text.configure(fg=self.colors["blockquote"])
                    self._has_placeholder = True
            
            def on_key_return(event):
                if event.state & 0x1:
                    return None
                else:
                    self._send()
                    return "break"
            
            self.input_text.bind('<FocusIn>', on_focus_in)
            self.input_text.bind('<FocusOut>', on_focus_out)
            self.input_text.bind('<Return>', on_key_return)
    
    def _create_action_buttons(self):
        """Create the action button row."""
        if HAVE_CTK:
            btn_row = ctk.CTkFrame(self.root, fg_color="transparent")
            btn_row.grid(row=6, column=0, sticky="ew", padx=15, pady=(5, 15))
            
            send_colors = get_ctk_button_colors(self.theme, "success")
            send_content = prepare_emoji_content("📤 Send", size=16)
            self.send_btn = ctk.CTkButton(
                btn_row,
                **send_content,
                font=get_ctk_font(size=12, weight="bold"),
                width=80,
                height=32,
                corner_radius=8,
                command=self._send,
                **send_colors
            )
            self.send_btn.pack(side="left", padx=2)
            
            # Regenerate button (warning/yellow color)
            regen_colors = get_ctk_button_colors(self.theme, "warning")
            regen_content = prepare_emoji_content("🔄 Regen", size=16)
            self.regen_btn = ctk.CTkButton(
                btn_row,
                **regen_content,
                font=get_ctk_font(size=12),
                width=85,
                height=32,
                corner_radius=8,
                command=self._regenerate,
                **regen_colors
            )
            self.regen_btn.pack(side="left", padx=2)
            
            sec_colors = get_ctk_button_colors(self.theme, "secondary")
            
            ctk.CTkButton(
                btn_row,
                text="Copy All",
                font=get_ctk_font(size=12),
                width=85,
                height=32,
                corner_radius=8,
                command=self._copy_all,
                **sec_colors
            ).pack(side="left", padx=2)
            
            ctk.CTkButton(
                btn_row,
                text="Copy Last",
                font=get_ctk_font(size=12),
                width=85,
                height=32,
                corner_radius=8,
                command=self._copy_last,
                **sec_colors
            ).pack(side="left", padx=2)
            
            ctk.CTkButton(
                btn_row,
                text="Close",
                font=get_ctk_font(size=12),
                width=70,
                height=32,
                corner_radius=8,
                command=self._close,
                **sec_colors
            ).pack(side="left", padx=2)
            
            self.status_label = ctk.CTkLabel(
                btn_row,
                text="",
                font=get_ctk_font(size=11),
                text_color=self.theme.accent_green
            )
            self.status_label.pack(side="left", padx=15)
        else:
            btn_row = tk.Frame(self.root, bg=self.colors["bg"])
            btn_row.grid(row=6, column=0, sticky=tk.EW, padx=15, pady=(5, 15))
            
            self.send_btn = tk.Button(
                btn_row, text="Send", font=("Segoe UI", 10, "bold"),
                bg=self.colors["accent"], fg="#ffffff",
                relief=tk.FLAT, padx=12, pady=6,
                command=self._send, cursor="hand2"
            )
            self.send_btn.pack(side=tk.LEFT, padx=2)
            
            # Regenerate button (warning/yellow color)
            self.regen_btn = tk.Button(
                btn_row, text="🔄 Regen", font=("Segoe UI", 10),
                bg=self.colors.get("accent_yellow", "#f9e2af"),
                fg=self.colors["bg"],
                relief=tk.FLAT, padx=10, pady=6,
                command=self._regenerate, cursor="hand2"
            )
            self.regen_btn.pack(side=tk.LEFT, padx=2)
            
            for text, cmd in [("Copy All", self._copy_all), ("Copy Last", self._copy_last), ("Close", self._close)]:
                btn = tk.Button(
                    btn_row, text=text, font=("Segoe UI", 10),
                    bg=self.colors["button_bg"], fg=self.colors["fg"],
                    relief=tk.FLAT, padx=10, pady=6,
                    command=cmd, cursor="hand2"
                )
                btn.pack(side=tk.LEFT, padx=2)
            
            self.status_label = tk.Label(
                btn_row, text="", font=("Segoe UI", 9),
                bg=self.colors["bg"], fg=self.colors["accent"]
            )
            self.status_label.pack(side=tk.LEFT, padx=15)
    
    # =========================================================================
    # Chat Display
    # =========================================================================
    
    def _update_chat_display(self, scroll_to_bottom: bool = False, preserve_scroll: bool = False):
        """Update the chat display with card-style message layout and inline images."""
        if self._destroyed or not self.chat_text:
            return
        
        saved_scroll = None
        if preserve_scroll:
            saved_scroll = self.chat_text.yview()
        
        # Clear previous thumbnail references to allow garbage collection
        if hasattr(self, '_chat_thumbnails'):
            self._chat_thumbnails.clear()
        else:
            self._chat_thumbnails = []
        
        self.chat_text.configure(state=tk.NORMAL)
        self.chat_text.delete("1.0", tk.END)
        
        # Update button labels
        if self.wrap_btn:
            if HAVE_CTK:
                self.wrap_btn.configure(text=f"Wrap: {'ON' if self.wrapped else 'OFF'}")
            else:
                self.wrap_btn.configure(text=f"Wrap: {'ON' if self.wrapped else 'OFF'}")
        if self.md_btn:
            if HAVE_CTK:
                self.md_btn.configure(text="Markdown" if self.markdown else "Raw Text")
            else:
                self.md_btn.configure(text="Markdown" if self.markdown else "Raw Text")
        if self.scroll_btn:
            if HAVE_CTK:
                self.scroll_btn.configure(text=f"Autoscroll: {'ON' if self.auto_scroll else 'OFF'}")
            else:
                self.scroll_btn.configure(text=f"Autoscroll: {'ON' if self.auto_scroll else 'OFF'}")
        
        # Render messages with card-style layout
        for i, msg in enumerate(self.session.messages):
            role = msg["role"]
            content = msg["content"]
            thinking = msg.get("thinking", "")
            
            # Add gap between messages (not before first)
            if i > 0:
                self.chat_text.insert(tk.END, "\n", "card_gap")
            
            # Determine styling based on role
            if role == "user":
                accent_tag = "user_accent_bar"
                label_tag = "user_label"
                message_tag = "user_message"
                label_text = "You"
            else:
                accent_tag = "assistant_accent_bar"
                label_tag = "assistant_label"
                message_tag = "assistant_message"
                label_text = "Assistant"
            
            # Insert accent bar + label (first line of card only)
            self.chat_text.insert(tk.END, "▌ ", (accent_tag, message_tag))
            self.chat_text.insert(tk.END, f"{label_text}\n", (label_tag, message_tag))
            
            # Render session-level image for first user message (snip tool captures)
            if i == 0 and role == "user" and self.session.image_base64:
                self._render_session_image(message_tag)
            
            # Render per-message attachments
            msg_attachments = msg.get("attachments", [])
            if msg_attachments and role == "user":
                self._render_message_attachments(msg_attachments, message_tag)
            
            # Thinking section (if assistant and has thinking)
            if role == "assistant" and thinking:
                is_collapsed = self.thinking_collapsed_states.get(i, True)
                
                # Create per-message thinking header tag
                thinking_tag = f"thinking_header_{i}"
                self.chat_text.tag_configure(thinking_tag,
                    font=("Segoe UI", 10, "bold"),
                    foreground=self.theme.accent_yellow,
                    spacing1=2, spacing3=2)
                
                # Bind click event for this specific message
                self.chat_text.tag_bind(thinking_tag, "<Button-1>",
                    lambda e, idx=i: self._toggle_thinking(idx))
                self.chat_text.tag_bind(thinking_tag, "<Enter>",
                    lambda e: self.chat_text.config(cursor="hand2"))
                self.chat_text.tag_bind(thinking_tag, "<Leave>",
                    lambda e: self.chat_text.config(cursor=""))
                
                # Insert thinking header
                thinking_header = "▶ Thinking..." if is_collapsed else "▼ Thinking:"
                self.chat_text.insert(tk.END, f"  {thinking_header}\n", (thinking_tag, message_tag))
                
                # Show thinking content if expanded
                if not is_collapsed:
                    if self.markdown:
                        render_markdown(thinking, self.chat_text, self.colors,
                                      wrap=self.wrapped, as_role="thinking",
                                      block_tag=message_tag, enable_emojis=True,
                                      line_prefix="    ")
                    else:
                        for t_line in thinking.split('\n'):
                            self.chat_text.insert(tk.END, "    " + t_line + "\n", ("thinking_content", message_tag))
            
            # Render content
            if self.markdown:
                render_markdown(content, self.chat_text, self.colors,
                              wrap=self.wrapped, as_role=role,
                              block_tag=message_tag, enable_emojis=True,
                              line_prefix="  ")
            else:
                self.chat_text.configure(wrap=tk.WORD if self.wrapped else tk.NONE)
                for c_idx, c_line in enumerate(content.split('\n')):
                    self.chat_text.insert(tk.END, "  " + c_line, ("normal", message_tag))
                    if c_idx < len(content.split('\n')) - 1:
                        self.chat_text.insert(tk.END, "\n", (message_tag,))
            
            # End of card - add trailing newline
            self.chat_text.insert(tk.END, "\n", (message_tag,))
        
        self.chat_text.configure(state=tk.DISABLED)
        
        if scroll_to_bottom and self.auto_scroll:
            self.chat_text.see(tk.END)
        elif preserve_scroll and saved_scroll:
            self.chat_text.yview_moveto(saved_scroll[0])
    
    def _update_streaming_display(self):
        """Update display during streaming with card-style layout."""
        if not self.is_streaming or self._destroyed:
            return
        
        self.chat_text.configure(state=tk.NORMAL)
        
        # Find and remove the streaming message
        try:
            gap_pos = self.chat_text.search("▌ Assistant", "end", backwards=True)
            if gap_pos:
                line_num = int(gap_pos.split('.')[0])
                if line_num > 1:
                    self.chat_text.delete(f"{line_num - 1}.0", tk.END)
        except:
            pass
        
        # Add gap before streaming message
        self.chat_text.insert(tk.END, "\n", "card_gap")
        
        accent_tag = "assistant_accent_bar"
        message_tag = "assistant_message"
        
        # Insert assistant label
        self.chat_text.insert(tk.END, "▌ ", (accent_tag, message_tag))
        self.chat_text.insert(tk.END, "Assistant\n", ("assistant_label", message_tag))
        
        # Streaming message index for thinking toggle
        streaming_idx = len(self.session.messages)
        is_collapsed = self.thinking_collapsed_states.get(streaming_idx, True)
        
        if self.streaming_thinking:
            thinking_header = "▶ Thinking..." if is_collapsed else "▼ Thinking:"
            self.chat_text.insert(tk.END, f"  {thinking_header}\n", ("thinking_header", message_tag))
            if not is_collapsed:
                for t_line in self.streaming_thinking.split('\n'):
                    self.chat_text.insert(tk.END, "    " + t_line + "\n", ("thinking_content", message_tag))
        
        # Streaming content
        if self.streaming_text:
            for c_idx, c_line in enumerate(self.streaming_text.split('\n')):
                self.chat_text.insert(tk.END, "  " + c_line, ("normal", message_tag))
                if c_idx < len(self.streaming_text.split('\n')) - 1:
                    self.chat_text.insert(tk.END, "\n", (message_tag,))
        else:
            self.chat_text.insert(tk.END, "  ...", ("normal", message_tag))
        
        self.chat_text.insert(tk.END, "\n", (message_tag,))
        
        self.chat_text.configure(state=tk.DISABLED)
        
        if self.auto_scroll:
            self.chat_text.see(tk.END)
    
    # =========================================================================
    # Toggle Methods
    # =========================================================================
    
    def _toggle_wrap(self):
        self.wrapped = not self.wrapped
        if self.h_scrollbar:
            if self.wrapped:
                self.h_scrollbar.grid_remove()
            else:
                self.h_scrollbar.grid()
        self._update_chat_display(preserve_scroll=True)
        self._update_status(f"Wrap: {'ON' if self.wrapped else 'OFF'}")
    
    def _toggle_markdown(self):
        self.markdown = not self.markdown
        self._update_chat_display(preserve_scroll=True)
        self._update_status(f"Mode: {'Markdown' if self.markdown else 'Raw Text'}")
    
    def _toggle_autoscroll(self):
        self.auto_scroll = not self.auto_scroll
        if self.scroll_btn:
            if HAVE_CTK:
                self.scroll_btn.configure(text=f"Autoscroll: {'ON' if self.auto_scroll else 'OFF'}")
            else:
                self.scroll_btn.configure(text=f"Autoscroll: {'ON' if self.auto_scroll else 'OFF'}")
        self._update_status(f"Autoscroll: {'ON' if self.auto_scroll else 'OFF'}")
    
    def _toggle_thinking(self, message_index: int):
        """Toggle thinking section visibility for a specific message."""
        current = self.thinking_collapsed_states.get(message_index, True)
        self.thinking_collapsed_states[message_index] = not current
        self._update_chat_display(preserve_scroll=True)
        state = "collapsed" if self.thinking_collapsed_states[message_index] else "expanded"
        self._update_status(f"Thinking: {state}")
    
    def _on_thinking_click(self, event):
        """Legacy handler - toggles all thinking sections."""
        all_collapsed = all(self.thinking_collapsed_states.get(i, True)
                          for i, msg in enumerate(self.session.messages)
                          if msg.get("thinking"))
        for i, msg in enumerate(self.session.messages):
            if msg.get("thinking"):
                self.thinking_collapsed_states[i] = not all_collapsed
        self._update_chat_display(preserve_scroll=True)
        self._update_status(f"Thinking: {'collapsed' if all_collapsed else 'expanded'}")
    
    # =========================================================================
    # Status & Models
    # =========================================================================
    
    def _update_status(self, text: str, color: str = None):
        """Update status label."""
        if not self.status_label:
            return
        if HAVE_CTK:
            self.status_label.configure(text=text)
            if color:
                self.status_label.configure(text_color=color)
        else:
            self.status_label.configure(text=text)
            if color:
                self.status_label.configure(fg=color)
    
    def _load_models(self):
        """Load available models in background."""
        if self._destroyed:
            return
        try:
            from ...api_client import fetch_models
            from ... import web_server
            
            models, error = fetch_models(web_server.CONFIG, web_server.KEY_MANAGERS)
            
            if models and not error and not self._destroyed:
                self.available_models = models
                model_ids = [m['id'] for m in models]
                
                def update_dropdown():
                    if self._destroyed:
                        return
                    try:
                        provider = web_server.CONFIG.get("default_provider", "google")
                        current = web_server.CONFIG.get(f"{provider}_model", "")
                        if HAVE_CTK:
                            self.model_dropdown.configure(values=model_ids)
                            if current and current in model_ids:
                                self.model_dropdown.set(current)
                            elif model_ids:
                                self.model_dropdown.set(current if current else model_ids[0])
                            else:
                                self.model_dropdown.set("(no models)")
                    except Exception:
                        pass
                
                self._safe_after(0, update_dropdown)
        except Exception as e:
            print(f"[ChatWindowBase] Error loading models: {e}")
    
    def _on_model_select(self, selected: str):
        """Handle model selection."""
        from ...config import save_config_value
        from ... import web_server
        
        if selected and selected not in ("(loading...)", "(no models)", "(default)"):
            self.selected_model = selected
            provider = web_server.CONFIG.get("default_provider", "google")
            config_key = f"{provider}_model"
            if save_config_value(config_key, selected):
                web_server.CONFIG[config_key] = selected
                self._update_status(f"✅ Model: {selected}", self.theme.accent_green)
            else:
                self._update_status(f"Model: {selected} (not saved)")
    
    # =========================================================================
    # Clipboard
    # =========================================================================
    
    def _get_conversation_text(self) -> str:
        """Build conversation text for clipboard."""
        parts = []
        for msg in self.session.messages:
            role = "You" if msg["role"] == "user" else "Assistant"
            parts.append(f"[{role}]\n{msg['content']}\n")
        return "\n".join(parts)
    
    def _copy_all(self):
        text = self._get_conversation_text()
        if copy_to_clipboard(text, self.root):
            self._update_status("✅ Copied all!", self.theme.accent_green)
        else:
            self._update_status("✗ Failed to copy", self.theme.accent_red)
    
    def _copy_last(self):
        text = self.last_response
        if copy_to_clipboard(text, self.root):
            self._update_status("✅ Copied last response!", self.theme.accent_green)
        else:
            self._update_status("✗ Failed to copy", self.theme.accent_red)
    
    # =========================================================================
    # Regenerate Response
    # =========================================================================
    
    def _regenerate(self):
        """Regenerate the last response or generate response for last user message."""
        if self.is_loading or self._destroyed:
            return
        
        if not self.session.messages:
            self._update_status("No messages to regenerate")
            return
        
        last_msg = self.session.messages[-1]
        
        if last_msg["role"] == "assistant":
            # Delete last assistant message and regenerate
            self.session.messages.pop()
            self._update_chat_display(scroll_to_bottom=True)
            self._update_status("Regenerating response...")
        else:
            # Last message is user - just generate response
            self._update_status("Generating response...")
        
        # Trigger regeneration
        self._regenerate_response()
    
    def _regenerate_response(self):
        """Internal method to regenerate without adding new user message."""
        if self._destroyed:
            return
        
        # Disable input
        self.is_loading = True
        if HAVE_CTK:
            self.send_btn.configure(state="disabled")
            if hasattr(self, 'regen_btn') and self.regen_btn:
                self.regen_btn.configure(state="disabled")
            self.input_text.configure(state="disabled")
            if self.attach_btn:
                self.attach_btn.configure(state="disabled")
        else:
            self.send_btn.configure(state=tk.DISABLED)
            if hasattr(self, 'regen_btn') and self.regen_btn:
                self.regen_btn.configure(state=tk.DISABLED)
            self.input_text.configure(state=tk.DISABLED)
            if self.attach_btn:
                self.attach_btn.configure(state=tk.DISABLED)
        
        # Reset streaming state
        self.streaming_text = ""
        self.streaming_thinking = ""
        self.is_streaming = False
        self.last_usage = None
        
        def process_regeneration():
            from ... import web_server
            from ...request_pipeline import RequestPipeline, RequestContext, RequestOrigin, StreamCallback
            
            streaming_enabled = web_server.CONFIG.get("streaming_enabled", True)
            current_provider = web_server.CONFIG.get("default_provider", "google")
            current_model = self.selected_model or web_server.CONFIG.get(f"{current_provider}_model", "")
            
            ctx = RequestContext(
                origin=RequestOrigin.CHAT_WINDOW,
                provider=current_provider,
                model=current_model,
                streaming=streaming_enabled,
                thinking_enabled=web_server.CONFIG.get("thinking_enabled", False),
                session_id=str(self.session.session_id)
            )
            
            def on_text(content):
                if self._destroyed:
                    return
                self.streaming_text += content
                self._safe_after(0, self._update_streaming_display)
            
            def on_thinking(content):
                if self._destroyed:
                    return
                self.streaming_thinking += content
                self._safe_after(0, self._update_streaming_display)
            
            def on_usage(content):
                self.last_usage = content
            
            def on_error(content):
                if self._destroyed:
                    return
                self._safe_after(0, lambda: self._update_status(f"Error: {content}", self.theme.accent_red))
            
            callbacks = StreamCallback(
                on_text=on_text,
                on_thinking=on_thinking,
                on_usage=on_usage,
                on_error=on_error
            )
            
            self.is_streaming = True
            self._safe_after(0, lambda: self._update_status("Streaming..." if streaming_enabled else "Processing..."))
            
            if streaming_enabled and current_provider in ("custom", "google", "openrouter"):
                ctx = RequestPipeline.execute_streaming(
                    ctx, self.session, web_server.CONFIG, web_server.AI_PARAMS,
                    web_server.KEY_MANAGERS, callbacks
                )
            else:
                self.is_streaming = False
                messages = self.session.get_conversation_for_api(include_image=True)
                ctx = RequestPipeline.execute_simple(
                    ctx, messages, web_server.CONFIG, web_server.AI_PARAMS,
                    web_server.KEY_MANAGERS
                )
            
            self.is_streaming = False
            self.last_usage = {
                "prompt_tokens": ctx.input_tokens,
                "completion_tokens": ctx.output_tokens,
                "total_tokens": ctx.total_tokens,
                "estimated": ctx.estimated
            }
            
            if self._destroyed:
                return
            
            def handle_response():
                if self._destroyed:
                    return
                
                if ctx.error:
                    self._update_status(f"Error: {ctx.error}", self.theme.accent_red)
                else:
                    self.session.add_message("assistant", ctx.response_text)
                    thinking_content = self.streaming_thinking or ctx.reasoning_text
                    if thinking_content and len(self.session.messages) > 0:
                        self.session.messages[-1]["thinking"] = thinking_content
                    
                    self.last_response = ctx.response_text
                    self._update_chat_display(scroll_to_bottom=True)
                    
                    usage_str = ""
                    if self.last_usage:
                        usage_str = f" | {self.last_usage.get('total_tokens', 0)} tokens"
                    
                    self._update_status(f"✅ Regenerated{usage_str}", self.theme.accent_green)
                    add_session(self.session, web_server.CONFIG.get("max_sessions", 50))
                
                self.is_loading = False
                if HAVE_CTK:
                    self.send_btn.configure(state="normal")
                    if hasattr(self, 'regen_btn') and self.regen_btn:
                        self.regen_btn.configure(state="normal")
                    self.input_text.configure(state="normal")
                    if self.attach_btn:
                        self.attach_btn.configure(state="normal")
                else:
                    self.send_btn.configure(state=tk.NORMAL)
                    if hasattr(self, 'regen_btn') and self.regen_btn:
                        self.regen_btn.configure(state=tk.NORMAL)
                    self.input_text.configure(state=tk.NORMAL)
                    if self.attach_btn:
                        self.attach_btn.configure(state=tk.NORMAL)
                
                self.streaming_text = ""
                self.streaming_thinking = ""
            
            self._safe_after(0, handle_response)
        
        threading.Thread(target=process_regeneration, daemon=True).start()
    
    # =========================================================================
    # Attachment Handling
    # =========================================================================
    
    def _on_attach_click(self):
        """Open file selector for attachments."""
        from tkinter import filedialog
        
        filetypes = [
            ("Images", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
            ("All supported", "*.png *.jpg *.jpeg *.gif *.webp *.bmp *.pdf"),
            ("All files", "*.*")
        ]
        
        files = filedialog.askopenfilenames(
            title="Select file(s) to attach",
            filetypes=filetypes,
            parent=self.root
        )
        
        if files:
            for file_path in files:
                self._add_pending_attachment(file_path)
    
    def _add_pending_attachment(self, file_path: str):
        """Add file to pending attachments with thumbnail preview."""
        import os
        from pathlib import Path
        
        path = Path(file_path)
        if not path.exists():
            self._update_status(f"File not found: {path.name}")
            return
        
        # Check if already added
        for attach in self.pending_attachments:
            if attach.get("source_path") == file_path:
                self._update_status(f"Already attached: {path.name}")
                return
        
        # Determine MIME type
        ext = path.suffix.lower().lstrip(".")
        mime_map = {
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
            "pdf": "application/pdf"
        }
        mime_type = mime_map.get(ext, "application/octet-stream")
        
        # Create thumbnail for preview (if it's an image)
        thumbnail = None
        if mime_type.startswith("image/"):
            try:
                from PIL import Image, ImageTk
                
                with Image.open(file_path) as img:
                    # Create thumbnail (max 48x48)
                    img.thumbnail((48, 48), Image.Resampling.LANCZOS)
                    thumbnail = ImageTk.PhotoImage(img)
                    self._attachment_thumbnails.append(thumbnail)  # Keep reference
            except Exception as e:
                print(f"[ChatWindow] Failed to create thumbnail: {e}")
        
        # Add to pending list
        attach_info = {
            "source_path": file_path,
            "filename": path.name,
            "mime_type": mime_type,
            "thumbnail": thumbnail
        }
        self.pending_attachments.append(attach_info)
        
        # Update UI
        self._update_attachments_display()
        self._update_status(f"Attached: {path.name}")
    
    def _remove_pending_attachment(self, index: int):
        """Remove attachment from pending list."""
        if 0 <= index < len(self.pending_attachments):
            removed = self.pending_attachments.pop(index)
            self._update_attachments_display()
            self._update_status(f"Removed: {removed.get('filename', 'attachment')}")
    
    def _clear_pending_attachments(self):
        """Clear all pending attachments after sending."""
        self.pending_attachments.clear()
        self._attachment_thumbnails.clear()
        self._update_attachments_display()
    
    def _render_message_attachments(self, attachments: List[Dict], message_tag: str):
        """Render attachment thumbnails inline in chat for a message."""
        if not attachments:
            return
        
        try:
            from PIL import Image, ImageTk
            from ...attachment_manager import AttachmentManager
        except ImportError:
            return
        
        for attach in attachments:
            file_path = attach.get("path", "")
            if not file_path:
                continue
            
            # Check if it's an image
            mime_type = attach.get("mime_type", "")
            if not mime_type.startswith("image/"):
                # Show file icon for non-images
                self.chat_text.insert(tk.END, "  📎 ", (message_tag,))
                self.chat_text.insert(tk.END, f"{attach.get('filename', 'attachment')}\n", ("normal", message_tag))
                continue
            
            try:
                # Load and create thumbnail
                b64, mime = AttachmentManager.load_image(file_path)
                if not b64:
                    continue
                
                import base64
                import io
                
                image_data = base64.b64decode(b64)
                with io.BytesIO(image_data) as buffer:
                    img = Image.open(buffer)
                    # Create thumbnail (max 150x150 for chat display)
                    img.thumbnail((150, 150), Image.Resampling.LANCZOS)
                    thumbnail = ImageTk.PhotoImage(img)
                
                # Store reference to prevent garbage collection
                if not hasattr(self, '_chat_thumbnails'):
                    self._chat_thumbnails = []
                self._chat_thumbnails.append(thumbnail)
                
                # Create unique tag for this image
                img_tag = f"img_{id(thumbnail)}"
                
                # Insert indentation
                self.chat_text.insert(tk.END, "  ", (message_tag,))
                
                # Insert image
                self.chat_text.image_create(tk.END, image=thumbnail)
                
                # Add image tag for click handling
                current_pos = self.chat_text.index(tk.INSERT)
                line = int(current_pos.split('.')[0])
                img_start = f"{line}.2"  # After the indentation
                img_end = f"{line}.3"
                self.chat_text.tag_add(img_tag, img_start, img_end)
                
                # Bind click events
                self.chat_text.tag_bind(img_tag, "<Button-1>",
                    lambda e, path=file_path: self._on_image_left_click(e, path))
                self.chat_text.tag_bind(img_tag, "<Button-3>",
                    lambda e, path=file_path: self._on_image_right_click(e, path))
                self.chat_text.tag_bind(img_tag, "<Enter>",
                    lambda e: self.chat_text.config(cursor="hand2"))
                self.chat_text.tag_bind(img_tag, "<Leave>",
                    lambda e: self.chat_text.config(cursor=""))
                
                # Add newline after image
                self.chat_text.insert(tk.END, "\n", (message_tag,))
                
            except Exception as e:
                print(f"[ChatWindow] Failed to render attachment: {e}")
                self.chat_text.insert(tk.END, f"  📎 {attach.get('filename', 'image')}\n", ("normal", message_tag))
    
    def _render_session_image(self, message_tag: str):
        """Render the session-level image (for snip tool captures)."""
        if not self.session.image_base64:
            return
        
        try:
            from PIL import Image, ImageTk
            import base64
            import io
            
            image_data = base64.b64decode(self.session.image_base64)
            with io.BytesIO(image_data) as buffer:
                img = Image.open(buffer)
                # Create thumbnail (max 200x200 for first message image)
                img.thumbnail((200, 200), Image.Resampling.LANCZOS)
                thumbnail = ImageTk.PhotoImage(img)
            
            # Store reference
            if not hasattr(self, '_chat_thumbnails'):
                self._chat_thumbnails = []
            self._chat_thumbnails.append(thumbnail)
            
            # Insert indentation
            self.chat_text.insert(tk.END, "  ", (message_tag,))
            
            # Insert image
            self.chat_text.image_create(tk.END, image=thumbnail)
            
            # Create tag for click handling
            img_tag = f"session_img_{id(thumbnail)}"
            current_pos = self.chat_text.index(tk.INSERT)
            line = int(current_pos.split('.')[0])
            img_start = f"{line}.2"
            img_end = f"{line}.3"
            self.chat_text.tag_add(img_tag, img_start, img_end)
            
            # Bind click events (use session attachments path if available)
            attach_path = ""
            if self.session.attachments:
                attach_path = self.session.attachments[0].get("path", "")
            
            if attach_path:
                self.chat_text.tag_bind(img_tag, "<Button-1>",
                    lambda e, path=attach_path: self._on_image_left_click(e, path))
                self.chat_text.tag_bind(img_tag, "<Button-3>",
                    lambda e, path=attach_path: self._on_image_right_click(e, path))
            
            self.chat_text.tag_bind(img_tag, "<Enter>",
                lambda e: self.chat_text.config(cursor="hand2"))
            self.chat_text.tag_bind(img_tag, "<Leave>",
                lambda e: self.chat_text.config(cursor=""))
            
            self.chat_text.insert(tk.END, "\n", (message_tag,))
            
        except Exception as e:
            print(f"[ChatWindow] Failed to render session image: {e}")
    
    def _on_image_left_click(self, event, file_path: str):
        """Show enlarged image in a modal window on left click."""
        try:
            from PIL import Image, ImageTk
            from ...attachment_manager import AttachmentManager
            import base64
            import io
            
            # Load full image
            b64, mime = AttachmentManager.load_image(file_path)
            if not b64:
                return
            
            image_data = base64.b64decode(b64)
            with io.BytesIO(image_data) as buffer:
                img = Image.open(buffer)
                orig_width, orig_height = img.size
                
                # Scale to fit screen (max 80% of screen size)
                if self.root:
                    screen_w = self.root.winfo_screenwidth()
                    screen_h = self.root.winfo_screenheight()
                    max_w = int(screen_w * 0.8)
                    max_h = int(screen_h * 0.8)
                    
                    if orig_width > max_w or orig_height > max_h:
                        img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                
                photo = ImageTk.PhotoImage(img)
            
            # Create modal window
            if HAVE_CTK:
                modal = ctk.CTkToplevel(self.root)
                modal.configure(fg_color=self.theme.bg)
            else:
                modal = tk.Toplevel(self.root)
                modal.configure(bg=self.colors["bg"])
            
            modal.title("Image Preview")
            modal.transient(self.root)
            
            # Center on screen
            modal.update_idletasks()
            w = photo.width() + 20
            h = photo.height() + 60
            x = (self.root.winfo_screenwidth() - w) // 2
            y = (self.root.winfo_screenheight() - h) // 2
            modal.geometry(f"{w}x{h}+{x}+{y}")
            
            # Display image
            img_label = tk.Label(modal, image=photo, bg=self.theme.bg if HAVE_CTK else self.colors["bg"])
            img_label.image = photo  # Keep reference
            img_label.pack(padx=10, pady=10)
            
            # Close button
            if HAVE_CTK:
                close_btn = ctk.CTkButton(
                    modal, text="Close", command=modal.destroy,
                    **get_ctk_button_colors(self.theme, "secondary")
                )
                close_btn.pack(pady=(0, 10))
            else:
                close_btn = tk.Button(
                    modal, text="Close", command=modal.destroy,
                    bg=self.colors["button_bg"], fg=self.colors["fg"]
                )
                close_btn.pack(pady=(0, 10))
            
            # Close on click or Escape
            modal.bind("<Button-1>", lambda e: modal.destroy() if e.widget == modal else None)
            modal.bind("<Escape>", lambda e: modal.destroy())
            
            modal.focus_set()
            
        except Exception as e:
            print(f"[ChatWindow] Failed to show image preview: {e}")
    
    def _on_image_right_click(self, event, file_path: str):
        """Open image in system default viewer on right click."""
        import os
        import subprocess
        import sys
        
        if not os.path.exists(file_path):
            self._update_status("Image file not found")
            return
        
        try:
            if sys.platform == "win32":
                os.startfile(file_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", file_path])
            else:
                subprocess.run(["xdg-open", file_path])
            self._update_status("Opened in external viewer")
        except Exception as e:
            print(f"[ChatWindow] Failed to open image: {e}")
            self._update_status("Failed to open image")
    
    def _update_attachments_display(self):
        """Update the attachments preview frame."""
        if not self.attachments_frame:
            return
        
        # Clear existing preview
        for widget in self.attachments_frame.winfo_children():
            widget.destroy()
        
        if not self.pending_attachments:
            self.attachments_frame.grid_remove()
            if hasattr(self, '_attachments_label') and self._attachments_label:
                if HAVE_CTK:
                    self._attachments_label.configure(text="")
                else:
                    self._attachments_label.configure(text="")
            return
        
        # Show frame
        self.attachments_frame.grid()
        
        # Update header label
        count = len(self.pending_attachments)
        label_text = f"📎 {count} file{'s' if count > 1 else ''} attached"
        if hasattr(self, '_attachments_label') and self._attachments_label:
            if HAVE_CTK:
                self._attachments_label.configure(text=label_text)
            else:
                self._attachments_label.configure(text=label_text)
        
        # Create preview items
        if HAVE_CTK:
            for i, attach in enumerate(self.pending_attachments):
                item_frame = ctk.CTkFrame(self.attachments_frame, fg_color=self.theme.surface0, corner_radius=6)
                item_frame.pack(side="left", padx=2, pady=2)
                
                # Thumbnail or icon
                if attach.get("thumbnail"):
                    # Use tk.Label for image (CTkLabel doesn't handle PhotoImage well with transparency)
                    thumb_label = tk.Label(item_frame, image=attach["thumbnail"], bg=self.theme.surface0)
                    thumb_label.pack(side="left", padx=4, pady=4)
                else:
                    ctk.CTkLabel(
                        item_frame, text="📄", font=get_ctk_font(size=20)
                    ).pack(side="left", padx=4, pady=4)
                
                # Filename (truncated)
                name = attach.get("filename", "file")[:20]
                if len(attach.get("filename", "")) > 20:
                    name += "..."
                ctk.CTkLabel(
                    item_frame, text=name, font=get_ctk_font(size=10),
                    text_color=self.theme.fg
                ).pack(side="left", padx=2)
                
                # Remove button
                remove_btn = ctk.CTkButton(
                    item_frame, text="×", width=20, height=20,
                    font=get_ctk_font(size=12), corner_radius=4,
                    fg_color="transparent", hover_color=self.theme.accent_red,
                    command=lambda idx=i: self._remove_pending_attachment(idx)
                )
                remove_btn.pack(side="left", padx=2)
        else:
            for i, attach in enumerate(self.pending_attachments):
                item_frame = tk.Frame(self.attachments_frame, bg=self.colors["surface0"])
                item_frame.pack(side=tk.LEFT, padx=2, pady=2)
                
                # Thumbnail or icon
                if attach.get("thumbnail"):
                    thumb_label = tk.Label(item_frame, image=attach["thumbnail"], bg=self.colors["surface0"])
                    thumb_label.pack(side=tk.LEFT, padx=4, pady=4)
                else:
                    tk.Label(
                        item_frame, text="📄", font=("Segoe UI", 16),
                        bg=self.colors["surface0"], fg=self.colors["fg"]
                    ).pack(side=tk.LEFT, padx=4, pady=4)
                
                # Filename
                name = attach.get("filename", "file")[:20]
                if len(attach.get("filename", "")) > 20:
                    name += "..."
                tk.Label(
                    item_frame, text=name, font=("Segoe UI", 9),
                    bg=self.colors["surface0"], fg=self.colors["fg"]
                ).pack(side=tk.LEFT, padx=2)
                
                # Remove button
                remove_btn = tk.Button(
                    item_frame, text="×", font=("Segoe UI", 10),
                    bg=self.colors["surface0"], fg=self.colors["fg"],
                    relief=tk.FLAT, cursor="hand2",
                    command=lambda idx=i: self._remove_pending_attachment(idx)
                )
                remove_btn.pack(side=tk.LEFT, padx=2)
    
    # =========================================================================
    # Send Message
    # =========================================================================
    
    def _send(self):
        """Send a message with streaming support and attachment handling."""
        if self.is_loading or self._destroyed:
            return
        
        if HAVE_CTK:
            user_input = self.input_text.get("0.0", "end-1c").strip()
        else:
            user_input = self.input_text.get("1.0", tk.END).strip()
        
        placeholder = self._placeholder
        
        if not user_input or user_input == placeholder:
            self._update_status("Please enter a message")
            return
        
        # Capture pending attachments before clearing
        attachments_to_send = list(self.pending_attachments)
        
        # Disable input
        self.is_loading = True
        if HAVE_CTK:
            self.send_btn.configure(state="disabled")
            self.input_text.configure(state="disabled")
            if self.attach_btn:
                self.attach_btn.configure(state="disabled")
        else:
            self.send_btn.configure(state=tk.DISABLED)
            self.input_text.configure(state=tk.DISABLED)
            if self.attach_btn:
                self.attach_btn.configure(state=tk.DISABLED)
        self._update_status("Sending...")
        
        # Clear pending attachments from UI
        self._clear_pending_attachments()
        
        # Reset streaming state
        self.streaming_text = ""
        self.streaming_thinking = ""
        self.is_streaming = False
        self.last_usage = None
        
        def process_message():
            from ... import web_server
            from ...request_pipeline import RequestPipeline, RequestContext, RequestOrigin, StreamCallback
            from ...attachment_manager import AttachmentManager
            
            # Process attachments: save to storage and build attachment list
            message_attachments = []
            message_index = len(self.session.messages)
            
            for attach in attachments_to_send:
                source_path = attach.get("source_path")
                if source_path:
                    # Save file to session attachments
                    saved_path = AttachmentManager.save_file(
                        session_id=self.session.session_id,
                        file_path=source_path,
                        message_index=message_index
                    )
                    if saved_path:
                        message_attachments.append({
                            "path": saved_path,
                            "mime_type": attach.get("mime_type", "application/octet-stream"),
                            "filename": attach.get("filename", "attachment")
                        })
            
            # Add message with attachments
            self.session.add_message("user", user_input, attachments=message_attachments)
            
            # Update display and clear input
            def update_ui():
                self._update_chat_display(scroll_to_bottom=True)
                if HAVE_CTK:
                    self.input_text.configure(state="normal")
                    self.input_text.delete("0.0", "end")
                else:
                    self.input_text.configure(state=tk.NORMAL)
                    self.input_text.delete("1.0", tk.END)
            self._safe_after(0, update_ui)
            
            streaming_enabled = web_server.CONFIG.get("streaming_enabled", True)
            current_provider = web_server.CONFIG.get("default_provider", "google")
            current_model = self.selected_model or web_server.CONFIG.get(f"{current_provider}_model", "")
            
            ctx = RequestContext(
                origin=RequestOrigin.CHAT_WINDOW,
                provider=current_provider,
                model=current_model,
                streaming=streaming_enabled,
                thinking_enabled=web_server.CONFIG.get("thinking_enabled", False),
                session_id=str(self.session.session_id)
            )
            
            def on_text(content):
                if self._destroyed:
                    return
                self.streaming_text += content
                self._safe_after(0, self._update_streaming_display)
            
            def on_thinking(content):
                if self._destroyed:
                    return
                self.streaming_thinking += content
                self._safe_after(0, self._update_streaming_display)
            
            def on_usage(content):
                self.last_usage = content
            
            def on_error(content):
                if self._destroyed:
                    return
                self._safe_after(0, lambda: self._update_status(f"Error: {content}", self.theme.accent_red))
            
            callbacks = StreamCallback(
                on_text=on_text,
                on_thinking=on_thinking,
                on_usage=on_usage,
                on_error=on_error
            )
            
            self.is_streaming = True
            self._safe_after(0, lambda: self._update_status("Streaming..." if streaming_enabled else "Processing..."))
            
            if streaming_enabled and current_provider in ("custom", "google", "openrouter"):
                ctx = RequestPipeline.execute_streaming(
                    ctx, self.session, web_server.CONFIG, web_server.AI_PARAMS,
                    web_server.KEY_MANAGERS, callbacks
                )
            else:
                self.is_streaming = False
                messages = self.session.get_conversation_for_api(include_image=True)
                ctx = RequestPipeline.execute_simple(
                    ctx, messages, web_server.CONFIG, web_server.AI_PARAMS,
                    web_server.KEY_MANAGERS
                )
            
            self.is_streaming = False
            self.last_usage = {
                "prompt_tokens": ctx.input_tokens,
                "completion_tokens": ctx.output_tokens,
                "total_tokens": ctx.total_tokens,
                "estimated": ctx.estimated
            }
            
            if self._destroyed:
                return
            
            def handle_response():
                if self._destroyed:
                    return
                
                if ctx.error:
                    self._update_status(f"Error: {ctx.error}", self.theme.accent_red)
                    self.session.messages.pop()
                else:
                    self.session.add_message("assistant", ctx.response_text)
                    thinking_content = self.streaming_thinking or ctx.reasoning_text
                    if thinking_content and len(self.session.messages) > 0:
                        self.session.messages[-1]["thinking"] = thinking_content
                    
                    self.last_response = ctx.response_text
                    self._update_chat_display(scroll_to_bottom=True)
                    
                    usage_str = ""
                    if self.last_usage:
                        usage_str = f" | {self.last_usage.get('total_tokens', 0)} tokens"
                    
                    self._update_status(f"✅ Response received{usage_str}", self.theme.accent_green)
                    add_session(self.session, web_server.CONFIG.get("max_sessions", 50))
                
                self.is_loading = False
                if HAVE_CTK:
                    self.send_btn.configure(state="normal")
                    self.input_text.configure(state="normal")
                    if self.attach_btn:
                        self.attach_btn.configure(state="normal")
                else:
                    self.send_btn.configure(state=tk.NORMAL)
                    self.input_text.configure(state=tk.NORMAL)
                    if self.attach_btn:
                        self.attach_btn.configure(state=tk.NORMAL)
                
                self.streaming_text = ""
                self.streaming_thinking = ""
            
            self._safe_after(0, handle_response)
        
        threading.Thread(target=process_message, daemon=True).start()
    
    # =========================================================================
    # Focus & Close
    # =========================================================================
    
    def _focus_window(self):
        """Focus the window reliably."""
        if self._destroyed or not self.root:
            return
        try:
            self.root.lift()
            self.root.focus_force()
            self.root.attributes('-topmost', True)
            self.root.after(100, lambda: self.root.attributes('-topmost', False) if self.root and not self._destroyed else None)
        except tk.TclError:
            pass
    
    def _close(self):
        """Close window and cleanup."""
        self._destroyed = True
        self.is_streaming = False
        unregister_window(self._get_window_tag())
        
        try:
            if self.root:
                self.root.destroy()
        except tk.TclError:
            pass
        self.root = None


class BrowserWindowBase(ABC):
    """
    Base class for session browser windows.
    
    Subclasses must implement:
    - _create_root() -> creates the root window
    - _get_window_tag() -> return unique window tag
    """
    
    def __init__(self):
        self.window_id = get_next_window_id()
        
        self.selected_session_id = None
        self.selected_item = None
        
        # Theme
        self.theme = get_colors()
        self.colors = get_color_scheme()
        
        # Sorting state
        self.sort_column = "Updated"
        self.sort_descending = True
        
        self._destroyed = False
        self.session_items: List = []
        
        # UI refs
        self.root = None
        self.list_header = None
        self.session_list = None
        self.status_label = None
    
    @abstractmethod
    def _get_window_tag(self) -> str:
        """Return unique window tag for registration."""
        pass
    
    def _safe_after(self, delay: int, func):
        """Schedule callback safely."""
        if self._destroyed:
            return
        try:
            if self.root and self.root.winfo_exists():
                self.root.after(delay, func)
        except Exception:
            pass
    
    def _sort_by_column(self, column: str):
        """Sort by column."""
        if self.sort_column == column:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = column
            self.sort_descending = True
        
        if self.list_header:
            self.list_header.update_sort_indicators(self.sort_column, self.sort_descending)
        
        self._refresh()
    
    def _refresh(self):
        """Refresh the session list."""
        if self._destroyed:
            return
        
        from ...session_manager import list_sessions
        from .session_browser import SessionListItem
        
        # Clear existing items
        for item in self.session_items:
            item.destroy()
        self.session_items.clear()
        self.selected_item = None
        self.selected_session_id = None
        
        sessions = list_sessions()
        
        # Sort
        reverse = self.sort_descending
        if self.sort_column == "ID":
            sessions.sort(key=lambda s: s['id'] if isinstance(s['id'], int) else 0, reverse=reverse)
        elif self.sort_column == "Title":
            sessions.sort(key=lambda s: (s['title'] or '').lower(), reverse=reverse)
        elif self.sort_column == "Endpoint":
            sessions.sort(key=lambda s: s['endpoint'], reverse=reverse)
        elif self.sort_column == "Messages":
            sessions.sort(key=lambda s: s['messages'], reverse=reverse)
        elif self.sort_column == "Updated":
            sessions.sort(key=lambda s: s['updated'] or '', reverse=reverse)
        
        # Create items
        for session in sessions:
            item = SessionListItem(
                self.session_list,
                session,
                self.theme,
                on_click=self._on_select,
                on_double_click=self._on_double_click
            )
            item.pack(fill="x", pady=1)
            self.session_items.append(item)
        
        self._update_status(f"{len(sessions)} session(s) found")
    
    def _on_select(self, session_data: Dict):
        """Handle session selection."""
        if self.selected_item:
            self.selected_item.set_selected(False)
        
        self.selected_session_id = session_data.get('id')
        for item in self.session_items:
            if item.session_data.get('id') == self.selected_session_id:
                item.set_selected(True)
                self.selected_item = item
                break
        
        self._update_status(f"Selected: {self.selected_session_id}")
    
    def _on_double_click(self, session_data: Dict):
        """Handle double click to open session."""
        self._on_select(session_data)
        self._open_session()
    
    def _update_status(self, text: str):
        """Update status label."""
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.configure(text=text)
    
    @abstractmethod
    def _new_session(self):
        """Create a new session - implemented by subclass."""
        pass
    
    @abstractmethod
    def _open_session(self):
        """Open selected session - implemented by subclass."""
        pass
    
    def _delete_session(self):
        """Delete selected session."""
        if not self.selected_session_id:
            self._update_status("No session selected")
            return
        
        from ...session_manager import delete_session, save_sessions
        
        sid = self.selected_session_id
        if delete_session(sid):
            save_sessions()
            self.selected_session_id = None
            self.selected_item = None
            self._refresh()
            self._update_status(f"Deleted session {sid}")
        else:
            self._update_status("Failed to delete session")
    
    def _close(self):
        """Close window."""
        self._destroyed = True
        unregister_window(self._get_window_tag())
        try:
            if self.root:
                self.root.destroy()
        except tk.TclError:
            pass
        self.root = None
