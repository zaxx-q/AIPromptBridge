#!/usr/bin/env python3
"""
Global hotkey listener using pynput
"""

import logging
import threading
import time
from typing import Callable, Optional

from pynput import keyboard as pykeyboard


class HotkeyListener:
    """
    Global hotkey listener with spam detection and pause/resume support.
    """

    def __init__(self, shortcut: str, callback: Callable[[], None]):
        """
        Initialize the hotkey listener.

        Args:
            shortcut: Hotkey string like 'ctrl+space' or 'ctrl+alt+w'
            callback: Function to call when hotkey is triggered
        """
        self.shortcut = shortcut
        self.callback = callback
        self.listener: Optional[pykeyboard.Listener] = None
        self.paused = False
        self.running = False

        # Spam detection
        self.recent_triggers = []
        self.TRIGGER_WINDOW = 1.5  # seconds
        self.MAX_TRIGGERS = 3

        logging.debug(f"HotkeyListener initialized with shortcut: {shortcut}")

    def _parse_shortcut(self, shortcut: str) -> str:
        """
        Parse shortcut string to pynput format.
        e.g., 'ctrl+space' -> '<ctrl>+<space>'
        """
        parts = shortcut.lower().split("+")
        parsed_parts = []

        for part in parts:
            part = part.strip()
            if len(part) <= 1:
                # Single character key
                parsed_parts.append(part)
            else:
                # Modifier or special key
                parsed_parts.append(f"<{part}>")

        return "+".join(parsed_parts)

    def _check_trigger_spam(self) -> bool:
        """
        Check if hotkey is being triggered too frequently.
        Returns True if spam is detected.
        """
        current_time = time.time()

        # Add current trigger
        self.recent_triggers.append(current_time)

        # Remove old triggers outside the window
        self.recent_triggers = [t for t in self.recent_triggers if current_time - t <= self.TRIGGER_WINDOW]

        # Check if we have too many triggers in the window
        return len(self.recent_triggers) >= self.MAX_TRIGGERS

    def _on_activate(self):
        """Called when hotkey is activated."""
        if self.paused:
            logging.debug("Hotkey pressed but listener is paused")
            return

        if self._check_trigger_spam():
            logging.warning("Hotkey spam detected - ignoring trigger")
            return

        logging.debug("Hotkey triggered")

        # Call callback in a separate thread to not block the listener
        threading.Thread(target=self.callback, daemon=True).start()

    def start(self):
        """Start listening for the hotkey."""
        if self.running:
            logging.debug("Hotkey listener already running")
            return

        try:
            parsed_shortcut = self._parse_shortcut(self.shortcut)
            logging.debug(f"Starting hotkey listener for: {parsed_shortcut}")

            # Create the hotkey combination
            hotkey = pykeyboard.HotKey(pykeyboard.HotKey.parse(parsed_shortcut), self._on_activate)

            # Helper function to standardize key event
            def for_canonical(f):
                return lambda k: f(self.listener.canonical(k))

            # Create and start the listener
            self.listener = pykeyboard.Listener(
                on_press=for_canonical(hotkey.press), on_release=for_canonical(hotkey.release)
            )

            self.listener.start()
            self.running = True
            logging.info(f"Hotkey listener started: {self.shortcut}")

        except Exception as e:
            logging.error(f"Failed to start hotkey listener: {e}")
            self.running = False

    def stop(self):
        """Stop the hotkey listener."""
        if self.listener:
            self.listener.stop()
            self.listener = None
        self.running = False
        logging.debug("Hotkey listener stopped")

    def pause(self):
        """Pause the hotkey listener (stops responding to hotkeys)."""
        self.paused = True
        logging.debug("Hotkey listener paused")

    def resume(self):
        """Resume the hotkey listener."""
        self.paused = False
        logging.debug("Hotkey listener resumed")

    def toggle_pause(self):
        """Toggle pause state."""
        if self.paused:
            self.resume()
        else:
            self.pause()
        return self.paused

    def is_running(self) -> bool:
        """Check if listener is running."""
        return self.running

    def is_paused(self) -> bool:
        """Check if listener is paused."""
        return self.paused
