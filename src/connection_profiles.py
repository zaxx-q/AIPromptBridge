#!/usr/bin/env python3
"""
Connection Profile Manager — data layer.

Manages profiles.json: a self-contained store of connection profiles
(provider, model, streaming, thinking, API params, etc.).

Usage:
    from src.connection_profiles import ProfileStore

    store = ProfileStore.get_instance()
    profile = store.get_active_profile()
    store.set_active_profile("GPT Heavy")
"""

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

PROFILES_FILE = "profiles.json"

# All fields a complete profile must have, with hard-coded defaults
PROFILE_DEFAULTS: Dict[str, Any] = {
    "description": "",
    "provider": "google",
    "model": "gemini-3-flash",
    "streaming": True,
    "thinking": False,
    "thinking_budget": -1,
    "thinking_level": "high",
    "reasoning_effort": "high",
    "temperature": None,
    "max_tokens": None,
    "request_timeout": 120,
    "custom_url": "",
    "gemini_endpoint": "",
    "api_key_name": "",
    "api_key_pool": "",
}

# Fields that map to config.ini keys when populating web_server.CONFIG
PROFILE_TO_CONFIG_MAP = {
    "provider": "default_provider",
    "model": None,  # dynamic: "{provider}_model"
    "streaming": "streaming_enabled",
    "thinking": "thinking_enabled",
    "thinking_budget": "thinking_budget",
    "thinking_level": "thinking_level",
    "reasoning_effort": "reasoning_effort",
    "request_timeout": "request_timeout",
    "custom_url": "custom_url",
    "gemini_endpoint": "gemini_endpoint",
}

# Fields that map to ai_params dict
PROFILE_AI_PARAM_FIELDS = {"temperature", "max_tokens"}

# Safe defaults for connection keys that must exist in CONFIG dict.
CONNECTION_KEY_DEFAULTS: Dict[str, Any] = {
    "default_provider": "google",
    "google_model": "gemini-3-flash-preview",
    "custom_model": "",
    "openrouter_model": "",
    "custom_url": "",
    "gemini_endpoint": "",
    "streaming_enabled": True,
    "thinking_enabled": False,
    "thinking_budget": -1,
    "thinking_level": "high",
    "reasoning_effort": "high",
}

def ensure_config_connection_keys(config: Dict[str, Any]) -> None:
    """Ensure CONFIG dict has all connection keys with safe defaults.

    Called after load_config() and before profile population to guarantee
    that connection keys exist even if config.ini is missing or was created
    without them (post-refactor).
    """
    for config_key, default in CONNECTION_KEY_DEFAULTS.items():
        if config_key not in config:
            config[config_key] = default

@dataclass
class ConnectionProfile:
    """A complete connection profile — every field has a value."""
    description: str = ""
    provider: str = "google"
    model: str = "gemini-3-flash"
    streaming: bool = True
    thinking: bool = False
    thinking_budget: int = -1
    thinking_level: str = "high"
    reasoning_effort: str = "high"
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    request_timeout: int = 120
    custom_url: str = ""
    gemini_endpoint: str = ""
    api_key_name: str = ""
    api_key_pool: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConnectionProfile":
        """Create profile from dict, filling missing fields with defaults."""
        clean = {}
        for k, default in PROFILE_DEFAULTS.items():
            val = data.get(k, default)
            # Type coercion for numeric fields
            if k == "thinking_budget" and val is not None:
                try:
                    val = int(val)
                except (ValueError, TypeError):
                    val = -1
            elif k == "temperature" and val is not None and val != "":
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    val = None
            elif k == "max_tokens" and val is not None and val != "":
                try:
                    val = int(val)
                except (ValueError, TypeError):
                    val = None
            elif k == "request_timeout" and val is not None:
                try:
                    val = int(val)
                except (ValueError, TypeError):
                    val = 120
            clean[k] = val
        return cls(**clean)

    def populate_config(self, config: Dict[str, Any]) -> None:
        """Write profile values into a config dict (web_server.CONFIG style)."""
        config["default_provider"] = self.provider
        config[f"{self.provider}_model"] = self.model
        config["streaming_enabled"] = self.streaming
        config["thinking_enabled"] = self.thinking
        config["thinking_budget"] = self.thinking_budget
        config["thinking_level"] = self.thinking_level
        config["reasoning_effort"] = self.reasoning_effort
        config["request_timeout"] = self.request_timeout
        config["custom_url"] = self.custom_url
        config["gemini_endpoint"] = self.gemini_endpoint

    def populate_ai_params(self, ai_params: Dict[str, Any]) -> None:
        """Write profile AI param values into an ai_params dict."""
        if self.temperature is not None:
            ai_params["temperature"] = self.temperature
        else:
            ai_params.pop("temperature", None)
        if self.max_tokens is not None:
            ai_params["max_tokens"] = self.max_tokens
        else:
            ai_params.pop("max_tokens", None)


class ProfileStore:
    """Singleton store for connection profiles backed by profiles.json."""

    _instance: Optional["ProfileStore"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._profiles: Dict[str, Dict[str, Any]] = {}
        self._active_profile_name: str = "Default"
        self._file_path = Path(PROFILES_FILE)
        self._save_lock = threading.Lock()
        self._load()

    @classmethod
    def get_instance(cls) -> "ProfileStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    # ─── Load / Save ──────────────────────────────────────────────────────

    def _load(self):
        if self._file_path.exists():
            try:
                with open(self._file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._active_profile_name = data.get("active_profile", "Default")
                self._profiles = data.get("profiles", {})
                # Ensure all profiles have all fields
                for name, pdata in self._profiles.items():
                    for k, v in PROFILE_DEFAULTS.items():
                        if k not in pdata:
                            pdata[k] = v
                logging.info(f"[ProfileStore] Loaded {len(self._profiles)} profiles from {self._file_path}")
            except Exception as e:
                logging.error(f"[ProfileStore] Failed to load {self._file_path}: {e}")
                self._create_default()
        else:
            self._create_default()

    def _create_default(self):
        self._active_profile_name = "Default"
        self._profiles = {"Default": dict(PROFILE_DEFAULTS)}
        self._save()
        logging.info("[ProfileStore] Created default profiles.json")

    def _save(self):
        with self._save_lock:
            data = {
                "active_profile": self._active_profile_name,
                "profiles": self._profiles,
            }
            try:
                with open(self._file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logging.error(f"[ProfileStore] Failed to save: {e}")

    def reload(self):
        """Reload from disk."""
        self._load()

    # ─── Active Profile ───────────────────────────────────────────────────

    def get_active_profile_name(self) -> str:
        return self._active_profile_name

    def get_active_profile(self) -> ConnectionProfile:
        data = self._profiles.get(self._active_profile_name)
        if data is None:
            # Fallback: first profile or hard defaults
            if self._profiles:
                first = next(iter(self._profiles))
                self._active_profile_name = first
                data = self._profiles[first]
                self._save()
            else:
                return ConnectionProfile()
        return ConnectionProfile.from_dict(data)

    def set_active_profile(self, name: str) -> bool:
        """Set active profile by name. Returns False if profile doesn't exist."""
        if name not in self._profiles:
            logging.warning(f"[ProfileStore] Profile '{name}' not found")
            return False
        self._active_profile_name = name
        self._save()
        logging.info(f"[ProfileStore] Active profile set to '{name}'")
        return True

    # ─── CRUD ─────────────────────────────────────────────────────────────

    def get_profile(self, name: str) -> Optional[ConnectionProfile]:
        data = self._profiles.get(name)
        if data is None:
            return None
        return ConnectionProfile.from_dict(data)

    def get_profile_dict(self, name: str) -> Optional[Dict[str, Any]]:
        return self._profiles.get(name)

    def set_profile(self, name: str, profile: ConnectionProfile) -> None:
        self._profiles[name] = profile.to_dict()
        self._save()

    def set_profile_from_dict(self, name: str, data: Dict[str, Any]) -> None:
        # Ensure completeness
        complete = dict(PROFILE_DEFAULTS)
        complete.update(data)
        self._profiles[name] = complete
        self._save()

    def delete_profile(self, name: str) -> bool:
        if name not in self._profiles:
            return False
        del self._profiles[name]
        if self._active_profile_name == name:
            self._active_profile_name = next(iter(self._profiles), "Default")
            if not self._profiles:
                self._create_default()
                return True
        self._save()
        return True

    def rename_profile(self, old_name: str, new_name: str) -> bool:
        if old_name not in self._profiles or new_name in self._profiles:
            return False
        self._profiles[new_name] = self._profiles.pop(old_name)
        if self._active_profile_name == old_name:
            self._active_profile_name = new_name
        self._save()
        return True

    def get_profile_names(self) -> List[str]:
        return sorted(self._profiles.keys())

    def profile_exists(self, name: str) -> bool:
        return name in self._profiles

    def get_profile_count(self) -> int:
        return len(self._profiles)
