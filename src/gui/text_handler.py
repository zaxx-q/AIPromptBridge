#!/usr/bin/env python3
"""
Text selection and clipboard handler
"""

import logging
import time

# Soft import: Linux can run without pyperclip when using the platform clipboard service.
try:
    import pyperclip
except ImportError:  # pragma: no cover - optional on minimal Linux envs
    pyperclip = None  # type: ignore[assignment]

from pynput import keyboard as pykeyboard

from ..platform import is_linux, is_windows
from ..platform.clipboard import copy_text as platform_copy_text
from ..platform.clipboard import get_selected_text_wayland
from ..platform.clipboard import paste_text as platform_paste_text
from ..platform.input import (
    copy_via_clipboard_shortcut,
    paste_via_clipboard_shortcut,
)

# --- Win32 SendInput structures (module-level to avoid repeated class definitions) ---
# Defined only for type/layout use on Windows; never touch windll on non-Windows.
_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_VK_CONTROL = 0x11
_VK_C = 0x43
_VK_V = 0x56
_WM_COPY = 0x0301

if is_windows():
    import ctypes

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
else:
    # Stubs so attribute references in Windows-only methods are never evaluated on Linux.
    ctypes = None  # type: ignore[assignment]
    _GUITHREADINFO = None  # type: ignore[assignment,misc]
    _INPUT = None  # type: ignore[assignment,misc]
    _PUL = None  # type: ignore[assignment]

    def _make_key_event(vk: int, up: bool = False):  # type: ignore[misc]
        raise RuntimeError("Win32 key events are only available on Windows")


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
    def _send_copy_keystroke() -> bool:
        """
        Send a copy command (Ctrl+C / WM_COPY).

        **Windows:** two parallel strategies (no delays):

        1. **WM_COPY** window message → tells the focused control to copy
           its selection directly, completely bypassing keyboard state.
        2. **SendInput** bare-C keystroke → leverages the Ctrl key that is
           *already physically held* from the hotkey combo.  Instead of
           fighting the hardware (releasing Ctrl then re-pressing it, which
           the physical keyboard overrides), we embrace it: just inject 'C'
           and the OS naturally combines it with the physical Ctrl state.

        Both fire instantly.  Whichever the target app responds to first
        triggers the clipboard change detected by get_selected_text().

        **Linux:** ``wlrctl`` virtual-keyboard Ctrl+C (optional hybrid capture).

        Returns:
            True if the platform reported a successful inject (best-effort).
        """
        if is_linux():
            ok = copy_via_clipboard_shortcut()
            if not ok:
                logging.debug("_send_copy_keystroke: wlrctl Ctrl+C failed or unavailable")
            return ok

        if not is_windows():
            logging.debug("_send_copy_keystroke skipped (unsupported platform)")
            return False

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
        return sent == n

    @staticmethod
    def _send_paste_keystroke() -> bool:
        """
        Send a Ctrl+V paste command.

        **Windows:** Win32 SendInput with virtual key codes (avoids Caps Lock /
        layout issues that can make pynput send the wrong character).

        **Linux:** ``wlrctl`` virtual-keyboard Ctrl+V.

        Returns:
            True if the platform reported a successful inject (best-effort).
        """
        if is_linux():
            ok = paste_via_clipboard_shortcut()
            if not ok:
                logging.debug("_send_paste_keystroke: wlrctl Ctrl+V failed or unavailable")
            return ok

        if not is_windows():
            logging.debug("_send_paste_keystroke skipped (unsupported platform)")
            return False

        user32 = ctypes.windll.user32

        # Check if Ctrl is already physically held
        ctrl_held = bool(user32.GetAsyncKeyState(_VK_CONTROL) & 0x8000)

        if ctrl_held:
            # Ctrl already held → just press/release V
            events = [
                _make_key_event(_VK_V),
                _make_key_event(_VK_V, up=True),
            ]
        else:
            # No Ctrl held → send full Ctrl+V sequence
            events = [
                _make_key_event(_VK_CONTROL),
                _make_key_event(_VK_V),
                _make_key_event(_VK_V, up=True),
                _make_key_event(_VK_CONTROL, up=True),
            ]

        n = len(events)
        arr = (_INPUT * n)(*events)
        sent = user32.SendInput(n, arr, ctypes.sizeof(_INPUT))

        if sent != n:
            logging.warning(f"SendInput paste: only {sent}/{n} events were injected")

        logging.debug(f"SendInput paste: ctrl_held={ctrl_held}, {sent}/{n} events sent")
        return sent == n

    def get_selected_text(self, sleep_duration: float = 0.01, max_wait: float = 0.4) -> str:
        """
        Get the currently selected text from any application.

        **Linux/Wayland:** reads primary selection first (mouse highlight), then
        falls back to a read-only clipboard paste. Does **not** inject Ctrl+C
        (hybrid primary→Ctrl+C capture is optional/later; paste inject uses wlrctl).

        **Windows:** uses clipboard sequence number + SendInput Ctrl+C, then
        restores the previous clipboard content.

        Args:
            sleep_duration: Short delay before Ctrl+C for stability (Windows; default: 0.01s)
            max_wait: Maximum time to wait for clipboard content (Windows; default: 0.4s)

        Returns:
            The selected text, or empty string if none
        """
        if is_linux():
            # Prefer primary selection; optional read-only clipboard fallback.
            # No SendInput / clipboard pollution.
            try:
                return get_selected_text_wayland()
            except Exception as e:
                logging.error(f"Linux selection capture failed: {e}")
                return ""

        # ── Windows path (unchanged strategy) ────────────────────────────
        if pyperclip is None:
            logging.error("pyperclip is required for selection capture on Windows")
            return ""

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
        Get selected text with a smart retry for slow applications.

        **Linux:** single primary-selection read (no Ctrl+C retry needed).

        **Windows:**
        Fast path (attempt 1): default timing — works for most apps, returns in <100ms
        typically (exits as soon as clipboard changes). Max wait 0.4s.

        Slow-app path (attempt 2): if the first attempt captured nothing, retries with
        a longer timeout (1.2s) and re-sends the copy keystroke after 0.4s. This
        handles Electron apps (Obsidian), JavaFX apps (XMind), and similar programs
        that process Ctrl+C asynchronously.

        Returns:
            The selected text, or empty string if none
        """
        if is_linux():
            return self.get_selected_text()

        # Fast path — works for most apps
        selected_text = self.get_selected_text()
        if selected_text:
            return selected_text

        # Slow-app retry
        logging.warning("No text captured on first attempt, retrying with slow-app strategy")
        return self._get_selected_text_slow_app()

    def _get_selected_text_slow_app(self) -> str:
        """
        Retry strategy for slow applications (Electron/JavaFX). Windows-only.

        - Waits 80ms before sending (gives Electron's event loop time to settle)
        - Polls for up to 1.2s with 20ms intervals
        - Re-sends the copy keystroke once after 0.4s if clipboard hasn't changed
        - Total added latency for normal apps: 0 (this only runs if fast path failed)

        Returns:
            The selected text, or empty string if none
        """
        if not is_windows() or pyperclip is None:
            return ""

        user32 = ctypes.windll.user32

        try:
            clipboard_backup = pyperclip.paste()
        except Exception:
            clipboard_backup = ""

        try:
            start_sequence = user32.GetClipboardSequenceNumber()
        except Exception:
            return ""

        # Longer pre-send delay — Electron needs time after focus change
        time.sleep(0.08)

        # Send copy keystroke
        try:
            self.is_copying = True
            self.last_copy_time = time.time()
            self._send_copy_keystroke()
        except Exception as e:
            logging.error(f"Slow-app copy failed: {e}")
            self.is_copying = False
            return ""

        # Poll for clipboard change with longer timeout and mid-wait re-send
        start_time = time.time()
        selected_text = ""
        clipboard_changed = False
        resent = False

        while (time.time() - start_time) < 1.2:
            try:
                current_sequence = user32.GetClipboardSequenceNumber()
                if current_sequence != start_sequence:
                    selected_text = pyperclip.paste()
                    clipboard_changed = True
                    break
            except Exception:
                pass

            # After 0.4s with no result, re-send the copy keystroke once
            # This handles apps that may have missed or delayed the first send
            if not resent and (time.time() - start_time) > 0.4:
                resent = True
                logging.debug("Re-sending copy keystroke for slow app")
                try:
                    self._send_copy_keystroke()
                except Exception:
                    pass

            time.sleep(0.02)  # 20ms polling interval

        self.is_copying = False

        # Restore clipboard if we captured text (we overwrote user's clipboard)
        if clipboard_changed:
            try:
                time.sleep(0.05)
                pyperclip.copy(clipboard_backup)
            except Exception as e:
                logging.error(f"Failed to restore clipboard after slow-app capture: {e}")

        if selected_text:
            logging.debug(f"Slow-app strategy captured {len(selected_text)} chars (resent={resent})")

        return selected_text

    def replace_selected_text(self, new_text: str) -> bool:
        """
        Replace the currently selected text with new text.

        **Windows:** clipboard + SendInput Ctrl+V, then restore clipboard.
        **Linux:** platform clipboard (wl-copy) + wlrctl Ctrl+V, then restore
        clipboard best-effort. Returns True only when paste injection succeeds.

        Args:
            new_text: The text to paste

        Returns:
            True if successful, False otherwise
        """
        if not new_text:
            return False

        if is_linux():
            cleaned = new_text.rstrip("\n")
            # Backup current clipboard (best-effort; may be empty)
            try:
                clipboard_backup = platform_paste_text(primary=False)
            except Exception:
                clipboard_backup = ""

            try:
                if not platform_copy_text(cleaned):
                    logging.warning(
                        "Linux replace_selected_text: failed to set clipboard "
                        "(wl-clipboard missing or error)"
                    )
                    return False

                # Brief settle for compositor clipboard sync
                time.sleep(0.08)
                if not self._send_paste_keystroke():
                    logging.warning(
                        "Linux replace_selected_text: clipboard set but paste key "
                        "injection failed (is wlrctl installed and the target focused?)"
                    )
                    # Still try to restore clipboard
                    try:
                        if clipboard_backup is not None:
                            platform_copy_text(clipboard_backup)
                    except Exception:
                        pass
                    return False

                time.sleep(0.1)

                # Restore previous clipboard best-effort
                try:
                    if clipboard_backup is not None:
                        platform_copy_text(clipboard_backup)
                except Exception as e:
                    logging.debug(f"Linux replace: clipboard restore failed: {e}")

                logging.debug("Linux text replaced successfully via clipboard + wlrctl")
                return True
            except Exception as e:
                logging.error(f"Linux replace_selected_text failed: {e}")
                try:
                    if clipboard_backup is not None:
                        platform_copy_text(clipboard_backup)
                except Exception:
                    pass
                return False

        if pyperclip is None:
            logging.error("pyperclip is required for replace_selected_text on Windows")
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

            # Paste using SendInput with VK codes
            # (avoids Caps Lock / keyboard layout issues with pynput)
            time.sleep(0.1)
            self._send_paste_keystroke()

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
        if is_linux():
            if not platform_copy_text(""):
                logging.error("Error clearing clipboard via wl-copy")
            return
        try:
            if pyperclip is None:
                raise RuntimeError("pyperclip not available")
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
        if is_linux():
            return platform_copy_text(text if text is not None else "")
        try:
            if pyperclip is None:
                raise RuntimeError("pyperclip not available")
            pyperclip.copy(text)
            return True
        except Exception as e:
            logging.error(f"Failed to copy to clipboard: {e}")
            return False
