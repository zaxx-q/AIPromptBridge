#!/usr/bin/env python3
"""
API Key Management with rotation and exhaustion tracking
"""

import threading


class KeyManager:
    """Manages API keys with rotation on failures"""

    def __init__(self, keys, provider_name, key_names=None):
        self.keys = [k for k in keys if k]
        self.current_index = 0
        self.exhausted_keys = set()
        self.provider_name = provider_name
        self.lock = threading.Lock()
        # Optional display names for keys (parallel list, same length as self.keys)
        # Used by profile resolver to select keys by name
        self.key_names = key_names or [""] * len(self.keys)

    def get_current_key(self):
        """Get the current active API key"""
        with self.lock:
            if not self.keys:
                return None
            if self.current_index >= len(self.keys):
                self.current_index = 0
            return self.keys[self.current_index]

    def rotate_key(self, reason=""):
        """Rotate to next available key"""
        with self.lock:
            if not self.keys:
                return None
            if len(self.keys) <= 1:
                return self.keys[0]
            self.exhausted_keys.add(self.current_index)
            for i in range(len(self.keys)):
                next_index = (self.current_index + 1 + i) % len(self.keys)
                if next_index not in self.exhausted_keys:
                    self.current_index = next_index
                    print(f"    → Switched to {self.provider_name} key #{self.current_index + 1} {reason}")
                    return self.keys[self.current_index]
            print(f"    → All {self.provider_name} keys exhausted, resetting...")
            self.exhausted_keys.clear()
            self.current_index = 0
            return self.keys[0] if self.keys else None

    def get_key_label(self):
        """Get a friendly display label for the current key (name if set, else index)"""
        with self.lock:
            if not self.keys:
                return "None"
            if self.current_index >= len(self.keys):
                self.current_index = 0
            if self.current_index < len(self.key_names) and self.key_names[self.current_index]:
                return self.key_names[self.current_index]
            return f"#{self.current_index + 1}"

    def get_key_count(self):
        """Get total number of keys"""
        return len(self.keys)

    def get_key_number(self):
        """Get current key number (1-indexed)"""
        return self.current_index + 1

    def has_keys(self):
        """Check if any keys are available"""
        return len(self.keys) > 0

    def has_more_keys(self):
        """Check if there are more keys to try"""
        return len(self.exhausted_keys) < len(self.keys)

    def reset_exhausted(self):
        """Reset exhausted keys tracking"""
        with self.lock:
            self.exhausted_keys.clear()

    def get_key_by_name(self, name: str):
        """
        Get an API key by its display name.

        Args:
            name: The display name to search for (from config.ini inline comment).

        Returns:
            The API key string if found, None otherwise.
        """
        if not name or not self.key_names:
            return None
        name_lower = name.lower().strip()
        for i, kn in enumerate(self.key_names):
            if kn and kn.lower().strip() == name_lower:
                return self.keys[i]
        return None
