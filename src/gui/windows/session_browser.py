#!/usr/bin/env python3
"""
Session browser components and windows.

Provides:
- SessionListItem: A single session row in the browser list
- SessionListHeader: Column headers with click-to-sort
- StandaloneSessionBrowserWindow: Creates own CTk root
- AttachedBrowserWindow: Uses CTkToplevel, attached to GUICoordinator
- create_attached_browser_window(): Factory function
"""

import threading
import time
import tkinter as tk
from typing import Optional, Dict, List

from ..platform import HAVE_CTK, ctk
from ...session_manager import add_session, get_session, ChatSession
from ..core import register_window
from ..custom_widgets import create_emoji_button
from ..themes import ThemeColors, get_colors, get_ctk_font, sync_ctk_appearance
from ..emoji_renderer import get_emoji_renderer, HAVE_PIL
from .chat_base import BrowserWindowBase
from .utils import set_window_icon


# =============================================================================
# Session List Components (lightweight tk-based for performance)
# =============================================================================

class SessionListItem(tk.Frame):
    """
    A single session row in the session browser list.
    Uses lightweight tk widgets with grid layout for proper alignment.
    """
    
    def __init__(self, parent, session_data: Dict, colors: ThemeColors,
                 on_click, on_double_click, **kwargs):
        # Remove CTk-specific kwargs if present
        kwargs.pop('fg_color', None)
        kwargs.pop('corner_radius', None)
        
        super().__init__(
            parent,
            bg=colors.surface0,
            height=36,
            **kwargs
        )
        self.session_data = session_data
        self.colors = colors
        self.on_click_callback = on_click
        self.on_double_click_callback = on_double_click
        self.selected = False
        self._emoji_images = []  # Keep references to prevent GC
        
        # Use grid layout for column alignment (pixel-perfect)
        # MUST match SessionListHeader grid config
        self.grid_columnconfigure(0, minsize=60)   # ID
        self.grid_columnconfigure(1, weight=1)     # Title
        self.grid_columnconfigure(2, minsize=100)  # Origin
        self.grid_columnconfigure(3, minsize=70)   # Msgs
        self.grid_columnconfigure(4, minsize=140)  # Updated
        
        self.pack_propagate(False)
        self.grid_propagate(False)
        
        # Data preparation
        sid = str(session_data.get('id', ''))
        title = session_data.get('title', '') or 'Untitled'
        # Truncate very long titles for display
        if len(title) > 60:
            title = title[:60] + '...'
            
        endpoint = session_data.get('origin', '')
        msgs = str(session_data.get('messages', 0))
        updated = session_data.get('updated', '')
        if updated:
            updated = updated[:16].replace('T', ' ')
        
        font = ("Segoe UI", 10)
        self.cells = []

        # Helper to create cells
        def create_cell(text, col, anchor="w", sticky="w", with_emoji=False):
            emoji_img = None
            display_text = text

            # Try to extract leading emoji for title column
            if with_emoji and HAVE_PIL:
                try:
                    renderer = get_emoji_renderer()
                    emoji_char, remaining = renderer.extract_leading_emoji(text)
                    if emoji_char:
                        emoji_img = renderer.get_emoji_image(emoji_char, size=16)
                        if emoji_img:
                            self._emoji_images.append(emoji_img)  # Prevent GC
                            display_text = remaining
                except Exception:
                    pass

            lbl = tk.Label(
                self,
                text=display_text,
                font=font,
                bg=colors.surface0,
                fg=colors.fg,
                anchor=anchor,
                padx=5,
                pady=8,
                cursor="hand2"
            )

            if emoji_img:
                lbl.configure(image=emoji_img, compound="left")

            lbl.grid(row=0, column=col, sticky=sticky, padx=(10 if col==0 else 0, 0))
            self.cells.append(lbl)

            # Event binding
            lbl.bind("<Button-1>", lambda e: self._on_click())
            lbl.bind("<Double-1>", lambda e: self._on_double_click())
            lbl.bind("<Enter>", lambda e: self._on_hover(True))
            lbl.bind("<Leave>", lambda e: self._on_hover(False))

        # Create columns
        create_cell(sid, 0, "w", "ew")
        create_cell(title, 1, "w", "ew", with_emoji=True)  # Title with emoji support
        create_cell(endpoint, 2, "w", "ew")
        create_cell(msgs, 3, "center", "ew")
        create_cell(updated, 4, "w", "ew")

        # Bind events to the frame itself too
        self.bind("<Button-1>", lambda e: self._on_click())
        self.bind("<Double-1>", lambda e: self._on_double_click())
        self.bind("<Enter>", lambda e: self._on_hover(True))
        self.bind("<Leave>", lambda e: self._on_hover(False))

    def _on_click(self):
        """Handle single click."""
        if self.on_click_callback:
            self.on_click_callback(self.session_data)
    
    def _on_double_click(self):
        """Handle double click."""
        if self.on_double_click_callback:
            self.on_double_click_callback(self.session_data)
    
    def _on_hover(self, entering: bool):
        """Handle hover effect."""
        if self.selected:
            return
        
        color = self.colors.surface1 if entering else self.colors.surface0
        self.configure(bg=color)
        for cell in self.cells:
            cell.configure(bg=color)
    
    def set_selected(self, selected: bool):
        """Set selection state."""
        self.selected = selected
        
        if selected:
            bg = self.colors.accent
            fg = "#ffffff"
        else:
            bg = self.colors.surface0
            fg = self.colors.fg
        
        self.configure(bg=bg)
        for cell in self.cells:
            cell.configure(bg=bg, fg=fg)


class SessionListHeader(tk.Frame):
    """
    Column headers for session list with click-to-sort functionality.
    Uses grid layout with fixed columns for alignment.
    """
    
    def __init__(self, parent, colors: ThemeColors, on_sort, current_sort, descending, **kwargs):
        # Remove CTk-specific kwargs
        kwargs.pop('fg_color', None)
        kwargs.pop('corner_radius', None)
        
        super().__init__(
            parent,
            bg=colors.surface1,
            height=30,
            **kwargs
        )
        self.colors = colors
        self.on_sort = on_sort
        self.current_sort = current_sort
        self.descending = descending
        
        # Grid config (Must match SessionListItem)
        self.grid_columnconfigure(0, minsize=60)   # ID
        self.grid_columnconfigure(1, weight=1)     # Title
        self.grid_columnconfigure(2, minsize=100)  # Origin
        self.grid_columnconfigure(3, minsize=70)   # Msgs
        self.grid_columnconfigure(4, minsize=140)  # Updated
        
        self.pack_propagate(False)
        self.grid_propagate(False)
        
        self.cells = {}
        self._create_headers()
        
    def _create_headers(self):
        font = ("Segoe UI", 10, "bold")
        
        def create_header(text, col, sort_key, anchor="w", sticky="w"):
            # Determine indicator
            indicator = ""
            actual_sort_key = "Messages" if sort_key == "Msgs" else sort_key
            
            if self.current_sort == actual_sort_key:
                indicator = " ▼" if self.descending else " ▲"
            
            lbl = tk.Label(
                self,
                text=text + indicator,
                font=font,
                bg=self.colors.surface1,
                fg=self.colors.fg,
                anchor=anchor,
                padx=5,
                pady=6,
                cursor="hand2"
            )
            lbl.grid(row=0, column=col, sticky=sticky, padx=(10 if col==0 else 0, 0))
            
            lbl.bind("<Button-1>", lambda e: self.on_sort(actual_sort_key) if self.on_sort else None)
            self.cells[actual_sort_key] = lbl
        
        create_header("ID", 0, "ID", "w", "ew")
        create_header("Title", 1, "Title", "w", "ew")
        create_header("Origin", 2, "Origin", "w", "ew")
        create_header("Msgs", 3, "Msgs", "center", "ew")
        create_header("Updated", 4, "Updated", "w", "ew")

    def update_sort_indicators(self, current_sort: str, descending: bool):
        """Update sort indicators on headers."""
        self.current_sort = current_sort
        self.descending = descending
        
        display_map = {
            "ID": "ID",
            "Title": "Title",
            "Origin": "Origin",
            "Messages": "Msgs",
            "Updated": "Updated"
        }
        
        for key, lbl in self.cells.items():
            base_text = display_map.get(key, key)
            if key == current_sort:
                indicator = " ▼" if descending else " ▲"
            else:
                indicator = ""
            lbl.configure(text=base_text + indicator)


# =============================================================================
# Standalone Session Browser Window
# =============================================================================

class StandaloneSessionBrowserWindow(BrowserWindowBase):
    """
    Standalone session browser window that creates its own CTk root.
    Uses CTkScrollableFrame with custom SessionListItem widgets.
    """
    
    def __init__(self):
        super().__init__()
        self.window_tag = f"standalone_browser_{self.window_id}"
    
    def _get_window_tag(self) -> str:
        return self.window_tag
    
    def show(self):
        """Create and show the window."""
        from ..utils import get_color_scheme
        
        if HAVE_CTK:
            sync_ctk_appearance()
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()
            self.root.configure(bg=self.colors["bg"])
        
        # Hide window while building UI
        self.root.withdraw()
        
        self.root.title("Session Browser")
        self.root.geometry("880x520")
        self.root.minsize(600, 350)
        
        offset = (self.window_id % 3) * 30
        self.root.geometry(f"+{50 + offset}+{50 + offset}")
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        
        # Title with emoji image support
        self._create_title()
        
        # Session list container
        self._create_session_list()
        
        # Action buttons
        self._create_action_buttons()
        
        # Register and bind
        register_window(self.window_tag)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        
        # Load sessions
        self._refresh()
        
        # Force Tk to process all pending drawing commands before showing
        self.root.update_idletasks()
        
        # Show window after UI is fully rendered
        self.root.deiconify()
        
        # Set window icon AFTER deiconify
        set_window_icon(self.root)
        
        # Focus
        self.root.lift()
        self.root.focus_force()
        
        # Run event loop
        self._run_event_loop()
    
    def _create_title(self):
        """Create title label."""
        if HAVE_CTK:
            title_emoji_img = None
            title_text = "📋 Saved Chat Sessions"
            
            try:
                from ..emoji_renderer import get_emoji_renderer, HAVE_PIL
                if HAVE_PIL:
                    renderer = get_emoji_renderer()
                    title_emoji_img = renderer.get_ctk_image("📋", size=22)
                    if title_emoji_img:
                        title_text = " Saved Chat Sessions"
            except ImportError:
                pass
            
            title_label_kwargs = {
                "text": title_text,
                "font": get_ctk_font(size=16, weight="bold"),
                "text_color": self.theme.accent
            }
            if title_emoji_img:
                title_label_kwargs["image"] = title_emoji_img
                title_label_kwargs["compound"] = "left"
            
            ctk.CTkLabel(self.root, **title_label_kwargs).grid(row=0, column=0, sticky="w", padx=15, pady=(15, 10))
        else:
            tk.Label(
                self.root, text="📋 Saved Chat Sessions",
                font=("Segoe UI", 14, "bold"),
                bg=self.colors["bg"], fg=self.colors["accent"]
            ).grid(row=0, column=0, sticky=tk.W, padx=15, pady=(15, 10))
    
    def _create_session_list(self):
        """Create the scrollable session list."""
        if HAVE_CTK:
            list_container = ctk.CTkFrame(
                self.root,
                corner_radius=10,
                fg_color=self.theme.text_bg,
                border_color=self.theme.border,
                border_width=1
            )
            list_container.grid(row=1, column=0, sticky="nsew", padx=15, pady=5)
            list_container.columnconfigure(0, weight=1)
            list_container.rowconfigure(1, weight=1)
            
            self.list_header = SessionListHeader(
                list_container,
                self.theme,
                on_sort=self._sort_by_column,
                current_sort=self.sort_column,
                descending=self.sort_descending
            )
            self.list_header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
            
            self.session_list = ctk.CTkScrollableFrame(
                list_container,
                corner_radius=0,
                fg_color="transparent"
            )
            self.session_list.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
            self.session_list.columnconfigure(0, weight=1)
        else:
            from tkinter import ttk
            list_container = tk.Frame(
                self.root, bg=self.colors["text_bg"],
                highlightbackground=self.colors["border"],
                highlightthickness=1
            )
            list_container.grid(row=1, column=0, sticky=tk.NSEW, padx=15, pady=5)
            list_container.columnconfigure(0, weight=1)
            list_container.rowconfigure(1, weight=1)
            
            self.list_header = SessionListHeader(
                list_container,
                self.theme,
                on_sort=self._sort_by_column,
                current_sort=self.sort_column,
                descending=self.sort_descending
            )
            self.list_header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
            
            # Scrollable canvas
            canvas_frame = tk.Frame(list_container, bg=self.colors["text_bg"])
            canvas_frame.grid(row=1, column=0, sticky=tk.NSEW, padx=8, pady=(0, 8))
            canvas_frame.columnconfigure(0, weight=1)
            canvas_frame.rowconfigure(0, weight=1)
            
            self._list_canvas = tk.Canvas(
                canvas_frame, bg=self.colors["text_bg"],
                highlightthickness=0, bd=0
            )
            self._list_canvas.grid(row=0, column=0, sticky=tk.NSEW)
            
            scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self._list_canvas.yview)
            scrollbar.grid(row=0, column=1, sticky=tk.NS)
            self._list_canvas.configure(yscrollcommand=scrollbar.set)
            
            self.session_list = tk.Frame(self._list_canvas, bg=self.colors["text_bg"])
            self._canvas_window = self._list_canvas.create_window((0, 0), window=self.session_list, anchor=tk.NW)
            
            def on_frame_configure(event):
                self._list_canvas.configure(scrollregion=self._list_canvas.bbox("all"))
            
            def on_canvas_configure(event):
                self._list_canvas.itemconfig(self._canvas_window, width=event.width)
            
            self.session_list.bind('<Configure>', on_frame_configure)
            self._list_canvas.bind('<Configure>', on_canvas_configure)
            
            # Mouse wheel scrolling
            def on_mousewheel(event):
                if not self.root or not self.root.winfo_exists():
                    return
                try:
                    x, y = self.root.winfo_pointerxy()
                    widget = self.root.winfo_containing(x, y)
                    if widget and (str(widget) == str(self._list_canvas) or str(widget).startswith(str(self._list_canvas) + ".")):
                        self._list_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                except Exception:
                    pass

            def _bind_mousewheel(event):
                self._list_canvas.bind_all("<MouseWheel>", on_mousewheel)
            
            self.root.bind("<Enter>", _bind_mousewheel, add="+")
            self.list_header.bind("<Enter>", _bind_mousewheel, add="+")
            self._list_canvas.bind("<Enter>", _bind_mousewheel, add="+")
            self._list_canvas.bind_all("<MouseWheel>", on_mousewheel)
    
    def _create_action_buttons(self):
        """Create the action button row."""
        if HAVE_CTK:
            btn_frame = ctk.CTkFrame(self.root, fg_color="transparent")
            btn_frame.grid(row=2, column=0, sticky="ew", padx=15, pady=(10, 15))
            
            create_emoji_button(
                btn_frame, "New Session", "➕", self.theme, "success", 120, 32, self._new_session
            ).pack(side="left", padx=2)
            
            create_emoji_button(
                btn_frame, "Open Chat", "💬", self.theme, "primary", 110, 32, self._open_session
            ).pack(side="left", padx=2)
            
            create_emoji_button(
                btn_frame, "Delete", "🗑️", self.theme, "danger", 90, 32, self._delete_session
            ).pack(side="left", padx=2)
            
            create_emoji_button(
                btn_frame, "Refresh", "🔄", self.theme, "secondary", 90, 32, self._refresh
            ).pack(side="left", padx=2)
            
            create_emoji_button(
                btn_frame, "Close", "", self.theme, "secondary", 70, 32, self._close
            ).pack(side="left", padx=2)
            
            self.status_label = ctk.CTkLabel(
                btn_frame,
                text="Click on a session to select it",
                font=get_ctk_font(size=11),
                text_color=self.theme.overlay0
            )
            self.status_label.pack(side="left", padx=15)
        else:
            btn_frame = tk.Frame(self.root, bg=self.colors["bg"])
            btn_frame.grid(row=2, column=0, sticky=tk.EW, padx=15, pady=(10, 15))
            
            for text, cmd, bg_color in [
                ("➕ New Session", self._new_session, self.colors["accent"]),
                ("💬 Open Chat", self._open_session, self.colors["button_bg"]),
                ("🗑️ Delete", self._delete_session, self.colors["button_bg"]),
                ("🔄 Refresh", self._refresh, self.colors["button_bg"]),
                ("Close", self._close, self.colors["button_bg"])
            ]:
                btn = tk.Button(
                    btn_frame, text=text, font=("Segoe UI", 9),
                    bg=bg_color, fg="#ffffff" if bg_color == self.colors["accent"] else self.colors["fg"],
                    relief=tk.FLAT, padx=10, pady=6,
                    command=cmd, cursor="hand2"
                )
                btn.pack(side=tk.LEFT, padx=2)
            
            self.status_label = tk.Label(
                btn_frame, text="Click on a session to select it",
                font=("Segoe UI", 9),
                bg=self.colors["bg"], fg=self.colors["blockquote"]
            )
            self.status_label.pack(side=tk.LEFT, padx=15)
    
    def _run_event_loop(self):
        """Run event loop."""
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
    
    def _new_session(self):
        """Create a new session."""
        from ..prompts import get_prompts_config
        from .chat_window import StandaloneChatWindow
        
        session = ChatSession(origin="chat")
        session.system_instruction = get_prompts_config().get_chat_window_system_instruction()
        add_session(session)
        
        def open_chat():
            chat = StandaloneChatWindow(session)
            chat.show()
        threading.Thread(target=open_chat, daemon=True).start()
        
        self._refresh()
        self._update_status(f"Created new session {session.session_id}")
    
    def _open_session(self):
        """Open selected session."""
        if not self.selected_session_id:
            self._update_status("No session selected")
            return
        
        from ..prompts import get_prompts_config
        from .chat_window import StandaloneChatWindow
        
        session = get_session(self.selected_session_id)
        if session:
            # Resolve system instruction from origin when config enabled
            prompts = get_prompts_config()
            from ... import web_server
            use_origin = web_server.CONFIG.get("chat_use_origin_system_prompt", True)
            if use_origin:
                resolved = prompts.get_system_prompt_for_origin(session.origin)
                session.system_instruction = resolved or prompts.get_chat_window_system_instruction()
            else:
                session.system_instruction = prompts.get_chat_window_system_instruction()
            
            def open_chat():
                chat = StandaloneChatWindow(session)
                chat.show()
            threading.Thread(target=open_chat, daemon=True).start()
            self._update_status(f"Opened session {self.selected_session_id}")
        else:
            self._update_status("Session not found")


# =============================================================================
# Attached Session Browser Window
# =============================================================================

class AttachedBrowserWindow(BrowserWindowBase):
    """
    Session browser as CTkToplevel attached to coordinator's root.
    """
    
    def __init__(self, parent_root):
        self.parent_root = parent_root
        super().__init__()
        self.window_tag = f"attached_browser_{self.window_id}"
        self._create_window()
    
    def _get_window_tag(self) -> str:
        return self.window_tag
    
    def _create_window(self):
        """Create browser window."""
        from ..utils import get_color_scheme
        
        if HAVE_CTK:
            self.root = ctk.CTkToplevel(self.parent_root)
        else:
            self.root = tk.Toplevel(self.parent_root)
            self.root.configure(bg=self.colors["bg"])
        
        # Hide window while building UI
        self.root.withdraw()
        
        self.root.title("Session Browser")
        self.root.geometry("880x520")
        self.root.minsize(600, 350)
        
        offset = (self.window_id % 3) * 30
        self.root.geometry(f"+{50 + offset}+{50 + offset}")
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        
        # Build UI
        self._create_title()
        self._create_session_list()
        self._create_action_buttons()
        
        register_window(self.window_tag)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        
        self._refresh()
        
        # Force Tk to process all pending drawing commands before showing
        self.root.update_idletasks()
        
        # Show window after UI is fully rendered
        self.root.deiconify()
        
        # Set window icon AFTER deiconify
        set_window_icon(self.root)
        
        self.root.lift()
        self.root.focus_force()
    
    def _create_title(self):
        """Create title label."""
        if HAVE_CTK:
            title_emoji_img = None
            title_text = "📋 Saved Chat Sessions"
            
            try:
                from ..emoji_renderer import get_emoji_renderer, HAVE_PIL
                if HAVE_PIL:
                    renderer = get_emoji_renderer()
                    title_emoji_img = renderer.get_ctk_image("📋", size=22)
                    if title_emoji_img:
                        title_text = " Saved Chat Sessions"
            except ImportError:
                pass
            
            title_label_kwargs = {
                "text": title_text,
                "font": get_ctk_font(size=16, weight="bold"),
                "text_color": self.theme.accent
            }
            if title_emoji_img:
                title_label_kwargs["image"] = title_emoji_img
                title_label_kwargs["compound"] = "left"
            
            ctk.CTkLabel(self.root, **title_label_kwargs).grid(row=0, column=0, sticky="w", padx=15, pady=(15, 10))
        else:
            tk.Label(
                self.root, text="📋 Saved Chat Sessions",
                font=("Segoe UI", 14, "bold"),
                bg=self.colors["bg"], fg=self.colors["accent"]
            ).grid(row=0, column=0, sticky=tk.W, padx=15, pady=(15, 10))
    
    def _create_session_list(self):
        """Create the scrollable session list."""
        if HAVE_CTK:
            list_container = ctk.CTkFrame(
                self.root, corner_radius=10, fg_color=self.theme.text_bg,
                border_color=self.theme.border, border_width=1
            )
            list_container.grid(row=1, column=0, sticky="nsew", padx=15, pady=5)
            list_container.columnconfigure(0, weight=1)
            list_container.rowconfigure(1, weight=1)
            
            self.list_header = SessionListHeader(
                list_container, self.theme,
                on_sort=self._sort_by_column,
                current_sort=self.sort_column,
                descending=self.sort_descending
            )
            self.list_header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
            
            self.session_list = ctk.CTkScrollableFrame(
                list_container, corner_radius=0, fg_color="transparent"
            )
            self.session_list.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
            self.session_list.columnconfigure(0, weight=1)
        else:
            from tkinter import ttk
            list_container = tk.Frame(
                self.root, bg=self.colors["text_bg"],
                highlightbackground=self.colors["border"],
                highlightthickness=1
            )
            list_container.grid(row=1, column=0, sticky=tk.NSEW, padx=15, pady=5)
            list_container.columnconfigure(0, weight=1)
            list_container.rowconfigure(1, weight=1)
            
            self.list_header = SessionListHeader(
                list_container, self.theme,
                on_sort=self._sort_by_column,
                current_sort=self.sort_column,
                descending=self.sort_descending
            )
            self.list_header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
            
            canvas_frame = tk.Frame(list_container, bg=self.colors["text_bg"])
            canvas_frame.grid(row=1, column=0, sticky=tk.NSEW, padx=8, pady=(0, 8))
            canvas_frame.columnconfigure(0, weight=1)
            canvas_frame.rowconfigure(0, weight=1)
            
            self._list_canvas = tk.Canvas(
                canvas_frame, bg=self.colors["text_bg"],
                highlightthickness=0, bd=0
            )
            self._list_canvas.grid(row=0, column=0, sticky=tk.NSEW)
            
            scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self._list_canvas.yview)
            scrollbar.grid(row=0, column=1, sticky=tk.NS)
            self._list_canvas.configure(yscrollcommand=scrollbar.set)
            
            self.session_list = tk.Frame(self._list_canvas, bg=self.colors["text_bg"])
            self._canvas_window = self._list_canvas.create_window((0, 0), window=self.session_list, anchor=tk.NW)
            
            def on_frame_configure(event):
                self._list_canvas.configure(scrollregion=self._list_canvas.bbox("all"))
            
            def on_canvas_configure(event):
                self._list_canvas.itemconfig(self._canvas_window, width=event.width)
            
            self.session_list.bind('<Configure>', on_frame_configure)
            self._list_canvas.bind('<Configure>', on_canvas_configure)
            
            def on_mousewheel(event):
                if not self.root or not self.root.winfo_exists():
                    return
                try:
                    x, y = self.root.winfo_pointerxy()
                    widget = self.root.winfo_containing(x, y)
                    if widget and (str(widget) == str(self._list_canvas) or str(widget).startswith(str(self._list_canvas) + ".")):
                        self._list_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                except Exception:
                    pass

            def _bind_mousewheel(event):
                self._list_canvas.bind_all("<MouseWheel>", on_mousewheel)
            
            self.root.bind("<Enter>", _bind_mousewheel, add="+")
            self.list_header.bind("<Enter>", _bind_mousewheel, add="+")
            self._list_canvas.bind("<Enter>", _bind_mousewheel, add="+")
            self._list_canvas.bind_all("<MouseWheel>", on_mousewheel)
    
    def _create_action_buttons(self):
        """Create action buttons."""
        if HAVE_CTK:
            btn_frame = ctk.CTkFrame(self.root, fg_color="transparent")
            btn_frame.grid(row=2, column=0, sticky="ew", padx=15, pady=(10, 15))
            
            create_emoji_button(
                btn_frame, "New Session", "➕", self.theme, "success", 120, 32, self._new_session
            ).pack(side="left", padx=2)
            
            create_emoji_button(
                btn_frame, "Open Chat", "💬", self.theme, "primary", 110, 32, self._open_session
            ).pack(side="left", padx=2)
            
            create_emoji_button(
                btn_frame, "Delete", "🗑️", self.theme, "danger", 90, 32, self._delete_session
            ).pack(side="left", padx=2)
            
            create_emoji_button(
                btn_frame, "Refresh", "🔄", self.theme, "secondary", 90, 32, self._refresh
            ).pack(side="left", padx=2)
            
            create_emoji_button(
                btn_frame, "Close", "", self.theme, "secondary", 70, 32, self._close
            ).pack(side="left", padx=2)
            
            self.status_label = ctk.CTkLabel(
                btn_frame, text="Click on a session to select it",
                font=get_ctk_font(size=11), text_color=self.theme.overlay0
            )
            self.status_label.pack(side="left", padx=15)
        else:
            btn_frame = tk.Frame(self.root, bg=self.colors["bg"])
            btn_frame.grid(row=2, column=0, sticky=tk.EW, padx=15, pady=(10, 15))
            
            for text, cmd, bg_color in [
                ("➕ New Session", self._new_session, self.colors["accent"]),
                ("💬 Open Chat", self._open_session, self.colors["button_bg"]),
                ("🗑️ Delete", self._delete_session, self.colors["button_bg"]),
                ("🔄 Refresh", self._refresh, self.colors["button_bg"]),
                ("Close", self._close, self.colors["button_bg"])
            ]:
                btn = tk.Button(
                    btn_frame, text=text, font=("Segoe UI", 9),
                    bg=bg_color, fg="#ffffff" if bg_color == self.colors["accent"] else self.colors["fg"],
                    relief=tk.FLAT, padx=10, pady=6,
                    command=cmd, cursor="hand2"
                )
                btn.pack(side=tk.LEFT, padx=2)
            
            self.status_label = tk.Label(
                btn_frame, text="Click on a session to select it",
                font=("Segoe UI", 9),
                bg=self.colors["bg"], fg=self.colors["blockquote"]
            )
            self.status_label.pack(side=tk.LEFT, padx=15)
    
    def _new_session(self):
        """Create a new session."""
        from ..core import GUICoordinator
        from ..prompts import get_prompts_config
        
        session = ChatSession(origin="chat")
        session.system_instruction = get_prompts_config().get_chat_window_system_instruction()
        add_session(session)
        GUICoordinator.get_instance().request_chat_window(session)
        self._refresh()
        self._update_status(f"Created new session {session.session_id}")
    
    def _open_session(self):
        """Open selected session."""
        if not self.selected_session_id:
            self._update_status("No session selected")
            return
        
        from ..core import GUICoordinator
        from ..prompts import get_prompts_config
        
        session = get_session(self.selected_session_id)
        if session:
            # Resolve system instruction from origin when config enabled
            prompts = get_prompts_config()
            from ... import web_server
            use_origin = web_server.CONFIG.get("chat_use_origin_system_prompt", True)
            if use_origin:
                resolved = prompts.get_system_prompt_for_origin(session.origin)
                session.system_instruction = resolved or prompts.get_chat_window_system_instruction()
            else:
                session.system_instruction = prompts.get_chat_window_system_instruction()
            GUICoordinator.get_instance().request_chat_window(session)
            self._update_status(f"Opened session {self.selected_session_id}")
        else:
            self._update_status("Session not found")


def create_attached_browser_window(parent_root):
    """Create a session browser window as Toplevel attached to parent root."""
    AttachedBrowserWindow(parent_root)
