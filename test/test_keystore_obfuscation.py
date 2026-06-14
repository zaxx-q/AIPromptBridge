#!/usr/bin/env python3
"""Tests for KeyStore obfuscation toggles, export, and import features."""

import json
import os

from src.key_store import KeyStore

TEST_KEYS_FILE = "test_keys_temp.json"


class TestKeyStoreObfuscation:
    """Test suite for KeyStore key obfuscation toggles and import/export."""

    def setup_method(self):
        """Clean up test keys file if it exists."""
        if os.path.exists(TEST_KEYS_FILE):
            os.remove(TEST_KEYS_FILE)

    def teardown_method(self):
        """Clean up test keys file."""
        if os.path.exists(TEST_KEYS_FILE):
            os.remove(TEST_KEYS_FILE)

    def test_default_obfuscation(self):
        """Verify that by default, keys are obfuscated on disk and deobfuscated in get_pool."""
        # Setup clean instance
        store = KeyStore()
        store._file_path = TEST_KEYS_FILE
        store._pools = {}
        store._provider_pool_map = {}
        store._obfuscation_disabled = False
        store._ensure_builtin_pools()

        # Add key
        assert store.add_key("google", "test-api-key-12345", "main-key")
        store.save()

        # Verify on-disk representation is obfuscated
        with open(TEST_KEYS_FILE, encoding="utf-8") as f:
            disk_data = json.load(f)

        disk_key = disk_data["pools"]["google"]["keys"][0]["key"]
        assert disk_key.startswith("$OBF$")
        assert disk_key != "test-api-key-12345"

        # Verify in-memory retrieval is deobfuscated
        keys = store.get_pool("google")
        assert len(keys) == 1
        assert keys[0]["key"] == "test-api-key-12345"
        assert keys[0]["name"] == "main-key"

        # Verify load retrieves correctly
        store2 = KeyStore()
        store2.load(TEST_KEYS_FILE)
        keys2 = store2.get_pool("google")
        assert len(keys2) == 1
        assert keys2[0]["key"] == "test-api-key-12345"

    def test_toggle_obfuscation_off_and_on(self):
        """Test disabling key obfuscation (portable mode) and re-enabling it."""
        store = KeyStore()
        store._file_path = TEST_KEYS_FILE
        store._pools = {}
        store._provider_pool_map = {}
        store._obfuscation_disabled = False
        store._ensure_builtin_pools()

        # Add key and save obfuscated
        store.add_key("openai", "sk-12345", "primary")
        store.save()

        # Disable obfuscation
        assert not store.obfuscation_disabled
        store.set_obfuscation_disabled(True)
        assert store.obfuscation_disabled
        store.save()

        # Verify on-disk representation is now plaintext
        with open(TEST_KEYS_FILE, encoding="utf-8") as f:
            disk_data = json.load(f)

        assert disk_data.get("obfuscation_disabled") is True
        disk_key = disk_data["pools"]["openai"]["keys"][0]["key"]
        assert disk_key == "sk-12345"

        # Check deobfuscated retrieval is still correct
        keys = store.get_pool("openai")
        assert keys[0]["key"] == "sk-12345"

        # Load into another instance with disabled obfuscation
        store2 = KeyStore()
        store2.load(TEST_KEYS_FILE)
        assert store2.obfuscation_disabled
        assert store2.get_pool("openai")[0]["key"] == "sk-12345"

        # Re-enable obfuscation
        store2.set_obfuscation_disabled(False)
        assert not store2.obfuscation_disabled
        store2.save()

        # Verify on-disk representation is obfuscated again
        with open(TEST_KEYS_FILE, encoding="utf-8") as f:
            disk_data2 = json.load(f)

        assert "obfuscation_disabled" not in disk_data2
        disk_key2 = disk_data2["pools"]["openai"]["keys"][0]["key"]
        assert disk_key2.startswith("$OBF$")
        assert disk_key2 != "sk-12345"

    def test_export_keys(self):
        """Verify export_keys returns plaintext keys regardless of obfuscation state."""
        store = KeyStore()
        store._file_path = TEST_KEYS_FILE
        store._pools = {}
        store._provider_pool_map = {}
        store._obfuscation_disabled = False
        store._ensure_builtin_pools()

        store.add_key("google", "gemini-key-1", "g1")
        store.add_key("openai", "openai-key-2", "o2")

        # Export (obfuscated in memory)
        export_data = store.export_keys()
        assert export_data["pools"]["google"]["keys"][0]["key"] == "gemini-key-1"
        assert export_data["pools"]["openai"]["keys"][0]["key"] == "openai-key-2"

        # Disable obfuscation and export again
        store.set_obfuscation_disabled(True)
        export_data2 = store.export_keys()
        assert export_data2["pools"]["google"]["keys"][0]["key"] == "gemini-key-1"
        assert export_data2["pools"]["openai"]["keys"][0]["key"] == "openai-key-2"

    def test_import_keys(self):
        """Verify import_keys appends keys and avoids duplicates."""
        store = KeyStore()
        store._file_path = TEST_KEYS_FILE
        store._pools = {}
        store._provider_pool_map = {}
        store._obfuscation_disabled = False
        store._ensure_builtin_pools()

        # Start with one existing key
        store.add_key("google", "existing-key", "old")

        # Create import payload
        import_payload = {
            "pools": {
                "google": {
                    "display_name": "Google",
                    "keys": [
                        {"key": "existing-key", "name": "duplicate-attempt"},
                        {"key": "new-key-1", "name": "fresh-1"},
                        {"key": "new-key-2", "name": "fresh-2"},
                    ],
                },
                "custom-pool": {"display_name": "My Custom Pool", "keys": [{"key": "custom-key-1", "name": "c1"}]},
            },
            "provider_pool_map": {"google": "google", "my-provider": "custom-pool"},
        }

        # Import
        result = store.import_keys(import_payload)
        assert result["google"] == 2  # 2 new keys added (existing-key skipped)
        assert result["custom-pool"] == 1

        # Check google keys
        google_keys = store.get_pool("google")
        assert len(google_keys) == 3
        assert google_keys[0]["key"] == "existing-key"
        assert google_keys[1]["key"] == "new-key-1"
        assert google_keys[2]["key"] == "new-key-2"

        # Check custom pool was created
        assert store.pool_exists("custom-pool")
        custom_keys = store.get_pool("custom-pool")
        assert len(custom_keys) == 1
        assert custom_keys[0]["key"] == "custom-key-1"
        assert store.get_provider_pool_id("my-provider") == "custom-pool"
