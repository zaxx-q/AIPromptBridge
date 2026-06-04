#!/usr/bin/env python3
"""
Chat window implementations.

Provides:
- StandaloneChatWindow: Creates own CTk root, runs own event loop
- AttachedChatWindow: Uses CTkToplevel, attached to GUICoordinator
- create_attached_chat_window(): Factory function for attached windows
"""

import time
import tkinter as tk
from typing import Optional

from ..platform import HAVE_CTK, ctk
from ..themes import sync_ctk_appearance
from .chat_base import ChatWindowBase
from .utils import set_window_icon


class StandaloneChatWindow(ChatWindowBase):
    """
    Standalone chat window that creates its own CTk root.
    Used when launching from non-GUI contexts (e.g., terminal command).
    """

    def __init__(self, session, initial_response: Optional[str] = None):
        super().__init__(session, initial_response)
        self.window_tag = f"standalone_chat_{self.window_id}"

    def _get_window_tag(self) -> str:
        return self.window_tag

    def show(self):
        """Create and show the window with its own mainloop."""
        # Sync appearance mode
        if HAVE_CTK:
            sync_ctk_appearance()
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()
            self.root.configure(bg=self.colors["bg"])

        # Hide window while building UI (prevents flashing)
        self.root.withdraw()

        self._configure_window()
        self._build_ui()

        # Initial display
        self._update_chat_display(scroll_to_bottom=True)

        # Force Tk to process all pending drawing commands before showing
        self.root.update_idletasks()

        # Show window after UI is fully rendered
        self.root.deiconify()

        # Set window icon AFTER deiconify (CTk overrides icon during setup)
        set_window_icon(self.root)

        # Focus - use after() for reliable focus
        self.root.after(50, lambda: self._focus_window())

        # Run event loop
        self._run_event_loop()

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


class AttachedChatWindow(ChatWindowBase):
    """
    Chat window as CTkToplevel attached to coordinator's root.
    Used for centralized GUI threading.
    """

    def __init__(self, parent_root, session, initial_response: Optional[str] = None):
        self.parent_root = parent_root
        super().__init__(session, initial_response)
        self.window_tag = f"attached_chat_{self.window_id}"
        self._create_window()

    def _get_window_tag(self) -> str:
        return self.window_tag

    def _create_window(self):
        """Create the chat window as CTkToplevel."""
        if HAVE_CTK:
            self.root = ctk.CTkToplevel(self.parent_root)
        else:
            self.root = tk.Toplevel(self.parent_root)
            self.root.configure(bg=self.colors["bg"])

        # Hide window while building UI
        self.root.withdraw()

        self._configure_window()
        self._build_ui()

        self._update_chat_display(scroll_to_bottom=True)

        # Force Tk to process all pending drawing commands before showing
        self.root.update_idletasks()

        # Show window after UI is fully rendered
        self.root.deiconify()

        # Set window icon AFTER deiconify (CTk overrides icon during setup)
        set_window_icon(self.root)

        # Use after() for reliable focus on new window
        self.root.after(100, lambda: self._focus_window())

    def _run_on_gui_thread(self, func):
        """Run callback on GUI thread via coordinator."""
        if self._destroyed:
            return
        from ..core import GUICoordinator

        def safe_wrapper():
            if not self._destroyed:
                try:
                    func()
                except tk.TclError:
                    pass

        GUICoordinator.get_instance().run_on_gui_thread(safe_wrapper)

    def _safe_after(self, delay: int, func):
        """Schedule callback safely via coordinator for delay=0."""
        if self._destroyed:
            return
        if delay == 0:
            self._run_on_gui_thread(func)
        else:
            try:
                if self.root and self.root.winfo_exists():
                    self.root.after(delay, func)
            except Exception:
                pass

    def _focus_window(self):
        """Focus the window reliably."""
        if self._destroyed or not self.root:
            return
        try:
            self.root.lift()
            self.root.focus_force()
            # Temporarily set topmost to grab focus, then remove
            self.root.attributes('-topmost', True)
            self.root.after(150, lambda: self.root.attributes('-topmost', False) if self.root and not self._destroyed else None)
        except tk.TclError:
            pass


def create_attached_chat_window(parent_root, session, initial_response: Optional[str] = None):
    """Create a chat window as Toplevel attached to parent root."""
    AttachedChatWindow(parent_root, session, initial_response)
