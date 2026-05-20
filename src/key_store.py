#!/usr/bin/env python3
"""
API Key Store — Pool-based key management with obfuscation.

Keys are stored in a dedicated ``keys.json`` file, grouped into named
"pools".  Each provider type is mapped to a pool via ``provider_pool_map``
so that a provider's key rotation draws from the correct pool.

Obfuscation
-----------
Keys are XOR'd with a machine-derived key and Base64-encoded before being
written to disk.  This is *obfuscation*, not encryption — it prevents
accidental exposure (screen sharing, git commits) but will not resist a
determined attacker with filesystem access.

Migration
---------
On first load (``keys.json`` missing), the store auto-migrates keys from
``config.ini`` using the legacy ``load_config()`` / ``load_key_names()``
helpers.  Environment variable fallbacks (``GEMINI_API_KEY``, etc.) are
included in migration only — once ``keys.json`` exists, env vars are
ignored.
"""

import base64
import hashlib
import json
import os
import platform
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .key_manager import KeyManager

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KEYS_FILE = "keys.json"
_FORMAT_VERSION = 2
_OBF_PREFIX = "$OBF$"

# Built-in provider IDs that always have a pool by default
_BUILTIN_PROVIDERS = (
    "google", "openrouter", "custom", "anthropic", "openai", "xai", "mistral", "cohere"
)

# Salt mixed into the machine key derivation
_SALT = b"AIPromptBridge::key-obfuscation::v1"

# ---------------------------------------------------------------------------
# Obfuscation helpers
# ---------------------------------------------------------------------------

def _get_machine_key() -> bytes:
    """Derive a deterministic key from the machine's hostname + salt."""
    raw = platform.node().encode("utf-8") + _SALT
    return hashlib.sha256(raw).digest()


def obfuscate(plaintext: str) -> str:
    """XOR *plaintext* with a machine-derived key, then Base64-encode.

    Returns a string prefixed with ``$OBF$`` so that already-obfuscated
    values are easy to detect.
    """
    if not plaintext:
        return ""
    machine_key = _get_machine_key()
    xored = bytes(
        b ^ machine_key[i % len(machine_key)]
        for i, b in enumerate(plaintext.encode("utf-8"))
    )
    return _OBF_PREFIX + base64.b64encode(xored).decode("ascii")


def deobfuscate(encoded: str) -> str:
    """Reverse :func:`obfuscate`.

    If *encoded* does not start with ``$OBF$`` it is returned as-is
    (assumed to be a raw/un-obfuscated key, e.g. during migration).
    """
    if not encoded:
        return ""
    if not encoded.startswith(_OBF_PREFIX):
        return encoded  # raw key — pass through
    raw_b64 = encoded[len(_OBF_PREFIX):]
    try:
        xored = base64.b64decode(raw_b64)
    except Exception:
        return encoded  # corrupt — return as-is
    machine_key = _get_machine_key()
    plaintext_bytes = bytes(
        b ^ machine_key[i % len(machine_key)]
        for i, b in enumerate(xored)
    )
    return plaintext_bytes.decode("utf-8", errors="replace")

# ---------------------------------------------------------------------------
# KeyStore
# ---------------------------------------------------------------------------

class KeyStore:
    """Singleton manager for pool-based API key storage.

    Thread-safe.  All mutations must go through the public API; direct
    access to ``_pools`` / ``_provider_pool_map`` from outside is
    discouraged.
    """

    _instance: Optional["KeyStore"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        # Pool ID → pool data:
        #   {"display_name": str, "keys": [{"key": str, "name": str}, ...]}
        # Keys stored *obfuscated* in memory exactly as on disk; deobfuscated
        # only when handed out via get_pool() / build_key_managers().
        self._pools: Dict[str, Dict[str, Any]] = {}

        # Provider type → pool ID
        self._provider_pool_map: Dict[str, str] = {}

        self._file_path = KEYS_FILE
        self._data_lock = threading.Lock()

    # -- Singleton -----------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "KeyStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # -- Load / Save ---------------------------------------------------------

    def load(self, filepath: Optional[str] = None) -> None:
        """Load pools from *filepath* (default ``keys.json``).

        If the file doesn't exist, migrate from ``config.ini`` and create
        it automatically.
        """
        if filepath:
            self._file_path = filepath

        path = Path(self._file_path)
        if not path.exists():
            self._migrate_from_config()
            self.save()
            return

        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            from .console import print_error
            print_error(f"Failed to load {self._file_path}: {exc}")
            self._ensure_builtin_pools()
            return

        with self._data_lock:
            self._pools = data.get("pools", {})
            self._provider_pool_map = data.get("provider_pool_map", {})
            self._ensure_builtin_pools()

    def save(self, filepath: Optional[str] = None) -> bool:
        """Persist current state to disk."""
        target = filepath or self._file_path
        try:
            with self._data_lock:
                data = {
                    "_format": _FORMAT_VERSION,
                    "pools": self._pools,
                    "provider_pool_map": self._provider_pool_map,
                }
            with open(target, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            return True
        except Exception as exc:
            from .console import print_error
            print_error(f"Failed to save {target}: {exc}")
            return False

    # -- Migration -----------------------------------------------------------

    def _migrate_from_config(self) -> None:
        """One-time migration: pull keys from ``config.ini`` + env vars."""
        from .config import CONFIG_FILE
        from .console import print_info

        print_info("Migrating API keys from config.ini → keys.json …")

        # Parse legacy key sections directly from config.ini
        legacy_keys: Dict[str, List[str]] = {p: [] for p in _BUILTIN_PROVIDERS}
        legacy_names: Dict[str, List[str]] = {p: [] for p in _BUILTIN_PROVIDERS}

        config_path = Path(CONFIG_FILE)
        if config_path.exists():
            try:
                import re as _re
                with open(config_path, "r", encoding="utf-8") as fh:
                    current_section = None
                    for line in fh:
                        stripped = line.strip()
                        if stripped.startswith("[") and stripped.endswith("]"):
                            current_section = stripped[1:-1].strip().lower()
                        elif current_section in legacy_keys:
                            if stripped and not stripped.startswith("#"):
                                match = _re.search(r'\s+#\s*', stripped)
                                if match:
                                    key_part = stripped[:match.start()].strip()
                                    name_part = stripped[match.end():].strip()
                                else:
                                    key_part = stripped.strip()
                                    name_part = ""
                                if key_part:
                                    legacy_keys[current_section].append(key_part)
                                    legacy_names[current_section].append(name_part)
            except Exception as exc:
                print_info(f"Could not read config.ini for migration: {exc}")

        # Also check environment variables (one-time only)
        env_map = {
            "google": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
            "openrouter": ["OPENROUTER_API_KEY"],
            "custom": ["CUSTOM_API_KEY"],
            "anthropic": ["ANTHROPIC_API_KEY"],
            "openai": ["OPENAI_API_KEY"],
            "xai": ["XAI_API_KEY"],
            "mistral": ["MISTRAL_API_KEY"],
            "cohere": ["COHERE_API_KEY"],
        }
        for provider, env_vars in env_map.items():
            if not legacy_keys[provider]:
                for env_name in env_vars:
                    val = os.environ.get(env_name, "").strip()
                    if val:
                        legacy_keys[provider].append(val)
                        legacy_names[provider].append(f"env:{env_name}")
                        break

        with self._data_lock:
            for provider in _BUILTIN_PROVIDERS:
                raw_keys = legacy_keys.get(provider, [])
                names = legacy_names.get(provider, [])
                keys_list: List[Dict[str, str]] = []
                for idx, raw_key in enumerate(raw_keys):
                    if raw_key:
                        name = names[idx] if idx < len(names) else ""
                        keys_list.append({
                            "key": obfuscate(raw_key),
                            "name": name,
                        })
                display = provider.capitalize()
                if provider == "openrouter":
                    display = "OpenRouter"
                elif provider == "xai":
                    display = "xAI"
                self._pools[provider] = {
                    "display_name": display,
                    "keys": keys_list,
                }
                self._provider_pool_map[provider] = provider

            self._ensure_builtin_pools()

        key_count = sum(len(p["keys"]) for p in self._pools.values())
        if key_count:
            print_info(
                f"Migrated {key_count} key(s) into keys.json. "
                "You may now remove the [custom]/[openrouter]/[google] "
                "sections from config.ini."
            )
        else:
            print_info("No keys found in config.ini; created empty keys.json.")

    # -- Internal helpers ----------------------------------------------------

    def _ensure_builtin_pools(self) -> None:
        """Guarantee that every built-in provider has a pool entry."""
        for provider in _BUILTIN_PROVIDERS:
            if provider not in self._pools:
                display = provider.capitalize()
                if provider == "openrouter":
                    display = "OpenRouter"
                elif provider == "xai":
                    display = "xAI"
                self._pools[provider] = {"display_name": display, "keys": []}
            if provider not in self._provider_pool_map:
                self._provider_pool_map[provider] = provider

    @staticmethod
    def _slugify(name: str) -> str:
        """Convert a display name to a pool ID slug."""
        slug = name.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-")
        return slug or "pool"

    # -- Pool CRUD -----------------------------------------------------------

    def list_pools(self) -> List[Dict[str, Any]]:
        """Return ``[{id, display_name, key_count}, ...]``."""
        with self._data_lock:
            return [
                {
                    "id": pid,
                    "display_name": pdata.get("display_name", pid),
                    "key_count": len(pdata.get("keys", [])),
                }
                for pid, pdata in self._pools.items()
            ]

    def add_pool(self, display_name: str) -> str:
        """Create a new pool.  Returns the generated pool ID."""
        with self._data_lock:
            slug = self._slugify(display_name)
            # Ensure uniqueness
            base = slug
            counter = 2
            while slug in self._pools:
                slug = f"{base}-{counter}"
                counter += 1
            self._pools[slug] = {"display_name": display_name, "keys": []}
            return slug

    def remove_pool(self, pool_id: str) -> bool:
        """Remove a pool.  Built-in pools cannot be removed."""
        with self._data_lock:
            if pool_id in _BUILTIN_PROVIDERS:
                return False
            if pool_id not in self._pools:
                return False
            # Unmap any providers pointing at this pool
            for prov, mapped in list(self._provider_pool_map.items()):
                if mapped == pool_id:
                    self._provider_pool_map[prov] = prov  # reset to default
            del self._pools[pool_id]
            return True

    def rename_pool(self, pool_id: str, new_display_name: str) -> bool:
        """Rename a pool's display name (ID stays the same)."""
        with self._data_lock:
            if pool_id not in self._pools:
                return False
            self._pools[pool_id]["display_name"] = new_display_name
            return True

    # -- Key CRUD within a pool ----------------------------------------------

    def get_pool(self, pool_id: str) -> List[Dict[str, str]]:
        """Return *deobfuscated* key list for a pool: ``[{key, name}]``."""
        with self._data_lock:
            pool = self._pools.get(pool_id)
            if not pool:
                return []
            return [
                {"key": deobfuscate(kd.get("key", "")), "name": kd.get("name", "")}
                for kd in pool.get("keys", [])
            ]

    def get_pool_for_provider(self, provider: str) -> List[Dict[str, str]]:
        """Shortcut: get deobfuscated keys for the pool mapped to *provider*."""
        with self._data_lock:
            pool_id = self._provider_pool_map.get(provider, provider)
        return self.get_pool(pool_id)

    def add_key(self, pool_id: str, key: str, name: str = "") -> bool:
        """Add a key to a pool (obfuscates automatically)."""
        with self._data_lock:
            pool = self._pools.get(pool_id)
            if pool is None:
                return False
            pool["keys"].append({"key": obfuscate(key), "name": name})
            return True

    def remove_key(self, pool_id: str, index: int) -> bool:
        """Remove a key by index."""
        with self._data_lock:
            pool = self._pools.get(pool_id)
            if pool is None:
                return False
            keys = pool.get("keys", [])
            if 0 <= index < len(keys):
                del keys[index]
                return True
            return False

    def reorder_key(self, pool_id: str, from_idx: int, to_idx: int) -> bool:
        """Move a key from *from_idx* to *to_idx*."""
        with self._data_lock:
            pool = self._pools.get(pool_id)
            if pool is None:
                return False
            keys = pool.get("keys", [])
            if not (0 <= from_idx < len(keys) and 0 <= to_idx < len(keys)):
                return False
            item = keys.pop(from_idx)
            keys.insert(to_idx, item)
            return True

    def set_keys(self, pool_id: str, keys_data: List[Dict[str, str]]) -> bool:
        """Replace all keys in a pool (expects *plaintext* key values).

        Each entry: ``{"key": "<plaintext>", "name": "..."}``
        """
        with self._data_lock:
            pool = self._pools.get(pool_id)
            if pool is None:
                return False
            pool["keys"] = [
                {"key": obfuscate(kd.get("key", "")), "name": kd.get("name", "")}
                for kd in keys_data
                if kd.get("key")
            ]
            return True

    # -- Provider ↔ Pool mapping ---------------------------------------------

    def get_provider_pool_map(self) -> Dict[str, str]:
        """Return a *copy* of the provider → pool mapping."""
        with self._data_lock:
            return dict(self._provider_pool_map)

    def get_provider_pool_id(self, provider: str) -> str:
        """Get the pool ID mapped to a provider."""
        with self._data_lock:
            return self._provider_pool_map.get(provider, provider)

    def set_provider_pool(self, provider: str, pool_id: str) -> bool:
        """Reassign a provider to a different pool."""
        with self._data_lock:
            if pool_id not in self._pools:
                return False
            self._provider_pool_map[provider] = pool_id
            return True

    # -- KeyManager construction ---------------------------------------------

    def build_key_managers(self) -> Dict[str, KeyManager]:
        """Build a ``KeyManager`` per provider using the mapped pools.

        Returns:
            ``{"google": KeyManager(...), "openrouter": ..., "custom": ...}``
        """
        managers: Dict[str, KeyManager] = {}
        with self._data_lock:
            for provider in _BUILTIN_PROVIDERS:
                pool_id = self._provider_pool_map.get(provider, provider)
                pool = self._pools.get(pool_id, {})
                raw_keys: List[str] = []
                key_names: List[str] = []
                for kd in pool.get("keys", []):
                    k = deobfuscate(kd.get("key", ""))
                    if k:
                        raw_keys.append(k)
                        key_names.append(kd.get("name", ""))
                managers[provider] = KeyManager(
                    raw_keys, provider, key_names=key_names
                )
        return managers

    def build_key_manager_for_pool(
        self, pool_id: str, provider_name: str = "pool"
    ) -> Optional[KeyManager]:
        """Build a single ``KeyManager`` for a specific pool.

        Used by profile resolver when ``api_key_pool`` overrides the
        default provider mapping.
        """
        keys_data = self.get_pool(pool_id)
        if not keys_data:
            return None
        raw_keys = [kd["key"] for kd in keys_data if kd["key"]]
        key_names = [kd["name"] for kd in keys_data]
        if not raw_keys:
            return None
        return KeyManager(raw_keys, provider_name, key_names=key_names)

    # -- Utility -------------------------------------------------------------

    def get_all_pool_ids(self) -> List[str]:
        """Return all pool IDs in order."""
        with self._data_lock:
            return list(self._pools.keys())

    def get_pool_display_name(self, pool_id: str) -> str:
        """Get a pool's display name."""
        with self._data_lock:
            pool = self._pools.get(pool_id)
            return pool.get("display_name", pool_id) if pool else pool_id

    def pool_exists(self, pool_id: str) -> bool:
        """Check if a pool exists."""
        with self._data_lock:
            return pool_id in self._pools
