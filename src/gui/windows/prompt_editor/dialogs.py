#!/usr/bin/env python3
"""
Dialog windows for the Prompt Editor.

Standalone dialog classes that can be used independently:
- TestResultDialog: Streaming API test result viewer
"""

import queue
import tkinter as tk

from ...platform import HAVE_CTK, ctk
from ...themes import (
    get_ctk_button_colors, get_ctk_textbox_colors, get_ctk_font
)
from ..utils import set_window_icon


# Import emoji renderer for CTkImage support (Windows color emoji fix)
try:
    from ...emoji_renderer import get_emoji_renderer, HAVE_PIL
    HAVE_EMOJI = HAVE_PIL and HAVE_CTK
except ImportError:
    HAVE_EMOJI = False
    get_emoji_renderer = None





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

        # Dark titlebar support (must happen before deiconify)
        self.withdraw()
        from ..utils import set_dark_titlebar
        set_dark_titlebar(self)
        set_window_icon(self)
            
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
                bg=colors.accent, fg=colors.accent_fg,
                command=self.destroy
            ).pack()
            
        # State
        self.thinking_started = False
        self._has_content = False  # True once any text/thinking content arrives
        self._completed = False    # True once test is finished
        
        # Start message
        self._safe_insert("Waiting for response...\n\n")
        
        # Start queue polling
        self._check_queue()
        
        self.deiconify()
        
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
        if not self._has_content:
            self._has_content = True
            # Clear the "Waiting for response..." placeholder
            self._safe_clear_and_insert(text)
            return
            
        if self.thinking_started:
            self.end_thinking()
            
        self._safe_insert(text)
        
    def append_thinking(self, text):
        """Append thinking/reasoning text."""
        if not self._has_content:
            self._has_content = True
            # Clear the "Waiting for response..." placeholder
            def _clear_then_insert():
                try:
                    if self.use_ctk:
                        self.output_box.delete("0.0", "end")
                    else:
                        self.output_box.delete("1.0", "end")
                except Exception:
                    pass
            self.queue.put(_clear_then_insert)

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
        if not self._has_content:
            self._has_content = True
            self._safe_clear_and_insert(f"❌ Error: {text}\n", "error")
        else:
            self._safe_insert(f"\n❌ Error: {text}\n", "error")

    def mark_done(self, usage: dict = None):
        """Mark the test as complete with optional usage stats."""
        self._completed = True
        if self.thinking_started:
            self.end_thinking()

        parts = ["\n\n✅ Test complete."]
        if usage:
            prompt = usage.get("prompt_tokens", 0)
            completion = usage.get("completion_tokens", 0)
            total = usage.get("total_tokens", 0)
            est = " (est)" if usage.get("estimated", False) else ""
            parts.append(f"📊 Tokens: {prompt} in | {completion} out | {total} total{est}")

        self._safe_insert("\n".join(parts) + "\n")
        
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

    def _safe_clear_and_insert(self, text, tag=None):
        """Thread-safe: clear output box then insert text."""
        def _update():
            try:
                if self.use_ctk:
                    self.output_box.delete("0.0", "end")
                    self.output_box.insert("end", text)
                    self.output_box.see("end")
                else:
                    self.output_box.delete("1.0", "end")
                    self.output_box.insert("end", text, tag)
                    self.output_box.see("end")
            except Exception:
                pass

        self.queue.put(_update)
