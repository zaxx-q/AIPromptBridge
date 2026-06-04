#!/usr/bin/env python3
"""
Text selection and clipboard handler
"""

import ctypes
import logging
import time
from typing import Optional

import pyperclip
from pynput import keyboard as pykeyboard

# --- Win32 SendInput structures (module-level to avoid repeated class definitions) ---
_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_VK_CONTROL = 0x11
_VK_C = 0x43
_WM_COPY = 0x0301

_PUL = ctypes.POINTER(ctypes.c_ulong)


# --- Win32 GUITHREADINFO for finding the focused control within a window ---
class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("hwndActive", ctypes.c_void_p),
        ("hwndFocus", ctypes.c_void_p),
        ("hwndCapture", ctypes.c_void_p),
        ("hwndMenuOwner", ctypes.c_void_p),
        ("hwndMoveSize", ctypes.c_void_p),
        ("hwndCaret", ctypes.c_void_p),
        ("rcCaret", ctypes.c_long * 4),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", _PUL),
    ]


class _MOUSEINPUT(ctypes.Structure):
    """Only used to ensure the INPUT union is large enough (MOUSEINPUT > KEYBDINPUT)."""

    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", _PUL),
    ]


class _INPUT_UNION(ctypes.Union):
    from typing import ClassVar, List, Tuple

    _fields_: ClassVar[List[Tuple[str, type]]] = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT_UNION)]


def _make_key_event(vk: int, up: bool = False) -> _INPUT:
    """Create a single keyboard INPUT event."""
    inp = _INPUT()
    inp.type = _INPUT_KEYBOARD
    inp._input.ki.wVk = vk
    inp._input.ki.dwFlags = _KEYEVENTF_KEYUP if up else 0
    return inp


class TextHandler:
    """
    Handles text selection capture and clipboard operations.
    """

    def __init__(self):
        self.keyboard = pykeyboard.Controller()
        self.is_copying = False
        self.last_copy_time = 0.0
        logging.debug("TextHandler initialized")

    @staticmethod
    def _send_copy_keystroke():
        """
        Send a copy command using two parallel strategies (no delays):

        1. **WM_COPY** window message → tells the focused control to copy
           its selection directly, completely bypassing keyboard state.
        2. **SendInput** bare-C keystroke → leverages the Ctrl key that is
           *already physically held* from the hotkey combo.  Instead of
           fighting the hardware (releasing Ctrl then re-pressing it, which
           the physical keyboard overrides), we embrace it: just inject 'C'
           and the OS naturally combines it with the physical Ctrl state.

        Both fire instantly.  Whichever the target app responds to first
        triggers the clipboard change detected by get_selected_text().
        """
        user32 = ctypes.windll.user32

        # ── Strategy 1: WM_COPY window message ──────────────────────────
        try:
            hwnd_fg = user32.GetForegroundWindow()
            if hwnd_fg:
                # Find the focused child control (e.g. Word's editing pane)
                tid = user32.GetWindowThreadProcessId(hwnd_fg, None)
                gti = _GUITHREADINFO()
                gti.cbSize = ctypes.sizeof(_GUITHREADINFO)

                target_hwnd = hwnd_fg
                if user32.GetGUIThreadInfo(tid, ctypes.byref(gti)):
                    if gti.hwndFocus:
                        target_hwnd = gti.hwndFocus

                user32.SendMessageW(target_hwnd, _WM_COPY, 0, 0)
                logging.debug(f"WM_COPY sent to hwnd=0x{target_hwnd:X}")
        except Exception as e:
            logging.debug(f"WM_COPY strategy failed: {e}")

        # ── Strategy 2: SendInput (bare C if Ctrl held, full Ctrl+C otherwise)
        ctrl_held = bool(user32.GetAsyncKeyState(_VK_CONTROL) & 0x8000)

        if ctrl_held:
            # Ctrl already physically held → just press/release C
            events = [
                _make_key_event(_VK_C),
                _make_key_event(_VK_C, up=True),
            ]
        else:
            # No Ctrl held → send full Ctrl+C sequence
            events = [
                _make_key_event(_VK_CONTROL),
                _make_key_event(_VK_C),
                _make_key_event(_VK_C, up=True),
                _make_key_event(_VK_CONTROL, up=True),
            ]

        n = len(events)
        arr = (_INPUT * n)(*events)
        sent = user32.SendInput(n, arr, ctypes.sizeof(_INPUT))

        if sent != n:
            logging.warning(f"SendInput: only {sent}/{n} events were injected")

        logging.debug(f"SendInput copy: ctrl_held={ctrl_held}, {sent}/{n} events sent")

    def get_selected_text(self, sleep_duration: float = 0.01, max_wait: float = 0.4) -> str:
        """
        Get the currently selected text from any application using polling.
        Uses Windows clipboard sequence number to detect changes without modifying clipboard history.

        Args:
            sleep_duration: Short delay before Ctrl+C for stability (default: 0.01s)
            max_wait: Maximum time to wait for clipboard content (default: 0.4s)

        Returns:
            The selected text, or empty string if none
        """
        # Backup the clipboard in case we need to restore it
        # We only restore if we actually successfully copied new text (overwriting the user's clipboard)
        try:
            clipboard_backup = pyperclip.paste()
        except Exception:
            clipboard_backup = ""

        # Get current sequence number to detect changes
        try:
            user32 = ctypes.windll.user32
            start_sequence = user32.GetClipboardSequenceNumber()
        except Exception as e:
            logging.error(f"Failed to get clipboard sequence: {e}")
            return ""

        # Short stability delay before pressing keys
        time.sleep(sleep_duration)

        try:
            self.is_copying = True
            self.last_copy_time = time.time()
            # Use Win32 SendInput instead of pynput to ensure a clean Ctrl+C
            # even when modifier keys are still held from the hotkey combo
            self._send_copy_keystroke()
        except Exception as e:
            logging.error(f"Failed to simulate Ctrl+C: {e}")
            self.is_copying = False
            return ""

        # Poll for clipboard update
        # We check frequently (every 10ms) to return as fast as possible
        start_time = time.time()
        selected_text = ""
        clipboard_changed = False

        while (time.time() - start_time) < max_wait:
            try:
                current_sequence = user32.GetClipboardSequenceNumber()
                if current_sequence != start_sequence:
                    selected_text = pyperclip.paste()
                    clipboard_changed = True
                    break
            except Exception:
                pass
            time.sleep(0.01)  # 10ms poll interval

        # Reset copying flag after operation complete
        self.is_copying = False

        # If we successfully captured text, it means we overwrote the user's clipboard.
        # We should restore the original content to be transparent.
        if clipboard_changed:
            try:
                # Add a tiny delay to ensure the system is ready for another clipboard op
                # (prevent "OpenClipboard Failed" errors)
                time.sleep(0.05)
                pyperclip.copy(clipboard_backup)
            except Exception as e:
                logging.error(f"Failed to restore clipboard: {e}")

        return selected_text

    def get_selected_text_with_retry(self) -> str:
        """
        Get selected text with a retry using longer wait time.

        Returns:
            The selected text, or empty string if none
        """
        # First attempt with default settings (0.5s max wait)
        selected_text = self.get_selected_text()

        # Retry with longer wait if no text captured
        if not selected_text:
            logging.debug("No text captured, retrying with longer wait")
            # Increase stability delay and max wait
            selected_text = self.get_selected_text(sleep_duration=0.1, max_wait=0.8)

        return selected_text

    def replace_selected_text(self, new_text: str) -> bool:
        """
        Replace the currently selected text with new text.

        Args:
            new_text: The text to paste

        Returns:
            True if successful, False otherwise
        """
        if not new_text:
            return False

        # Backup clipboard
        try:
            clipboard_backup = pyperclip.paste()
        except Exception:
            clipboard_backup = ""

        try:
            # Copy new text to clipboard
            cleaned_text = new_text.rstrip("\n")
            pyperclip.copy(cleaned_text)

            # Simulate Ctrl+V
            time.sleep(0.1)
            self.keyboard.press(pykeyboard.Key.ctrl)
            self.keyboard.press("v")
            self.keyboard.release("v")
            self.keyboard.release(pykeyboard.Key.ctrl)

            time.sleep(0.2)

            # Restore clipboard
            pyperclip.copy(clipboard_backup)

            logging.debug("Text replaced successfully")
            return True

        except Exception as e:
            logging.error(f"Failed to replace text: {e}")
            # Try to restore clipboard
            try:
                pyperclip.copy(clipboard_backup)
            except Exception:
                pass
            return False

    @staticmethod
    def clear_clipboard():
        """Clear the system clipboard."""
        try:
            pyperclip.copy("")
        except Exception as e:
            logging.error(f"Error clearing clipboard: {e}")

    @staticmethod
    def copy_to_clipboard(text: str) -> bool:
        """
        Copy text to clipboard.

        Args:
            text: Text to copy

        Returns:
            True if successful
        """
        try:
            pyperclip.copy(text)
            return True
        except Exception as e:
            logging.error(f"Failed to copy to clipboard: {e}")
            return False
