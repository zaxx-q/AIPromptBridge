#!/usr/bin/env python3
import unittest

import src.web_server as web_server
from src.connection_profiles import ConnectionProfile, ProfileStore
from src.profile_resolver import resolve_profile


class TestProfileResolverOverrides(unittest.TestCase):
    def setUp(self):
        # Backup web_server globals
        self.original_active_profile = web_server.ACTIVE_PROFILE
        self.original_session_overrides = web_server.SESSION_OVERRIDES.copy()

        # Reset ProfileStore singleton for testing
        ProfileStore.reset_instance()
        self.store = ProfileStore.get_instance()

        # Clear profiles for clean state
        self.store._profiles = {}

    def tearDown(self):
        # Restore web_server globals
        web_server.ACTIVE_PROFILE = self.original_active_profile
        web_server.SESSION_OVERRIDES = self.original_session_overrides
        ProfileStore.reset_instance()

    def test_base_url_override_leaks_fixed(self):
        # 1. Create and set an Active Profile that has a custom base_url
        active_profile = ConnectionProfile(
            provider="openai", model="gpt-4o", base_url="https://active.custom.url/v1", temperature=0.7
        )
        self.store._profiles["ActiveProf"] = active_profile.to_dict()
        self.store._active_profile_name = "ActiveProf"
        web_server.ACTIVE_PROFILE = active_profile
        web_server.SESSION_OVERRIDES = {}

        # 2. Create another profile that has an EMPTY base_url (meaning use default provider base_url)
        override_profile = ConnectionProfile(provider="google", model="gemini-1.5-pro", base_url="", temperature=0.2)
        self.store._profiles["OverrideProf"] = override_profile.to_dict()

        # Action dict specifying the override profile
        action = {"connection_profile": "OverrideProf"}

        # Resolve
        resolved = resolve_profile(action, {}, {}, {})

        # Assertions
        # Base URL of the override profile is empty, so it should NOT use the ActiveProf's base_url!
        self.assertNotIn("base_url", resolved.config)
        self.assertEqual(resolved.provider, "google")
        self.assertEqual(resolved.model, "gemini-1.5-pro")
        self.assertEqual(resolved.ai_params.get("temperature"), 0.2)

    def test_active_profile_without_override(self):
        # Set Active Profile
        active_profile = ConnectionProfile(
            provider="openai", model="gpt-4o", base_url="https://active.custom.url/v1", temperature=0.7, max_tokens=150
        )
        web_server.ACTIVE_PROFILE = active_profile
        web_server.SESSION_OVERRIDES = {}

        resolved = resolve_profile(None, {}, {}, {})

        self.assertEqual(resolved.config.get("base_url"), "https://active.custom.url/v1")
        self.assertEqual(resolved.ai_params.get("temperature"), 0.7)
        self.assertEqual(resolved.ai_params.get("max_tokens"), 150)

    def test_disabled_profile_fallback(self):
        # 1. Active profile
        active_profile = ConnectionProfile(
            provider="openai", model="gpt-4o", base_url="https://active.custom.url/v1", temperature=0.7
        )
        self.store._profiles["ActiveProf"] = active_profile.to_dict()
        self.store._active_profile_name = "ActiveProf"
        web_server.ACTIVE_PROFILE = active_profile
        web_server.SESSION_OVERRIDES = {}

        # 2. Disabled profile
        disabled_profile = ConnectionProfile(provider="google", model="gemini-1.5-pro", enabled=False, temperature=0.2)
        self.store._profiles["DisabledProf"] = disabled_profile.to_dict()

        # Action dict specifying the disabled profile
        action = {"connection_profile": "DisabledProf"}

        # Resolve should fall back to active profile because DisabledProf is disabled
        resolved = resolve_profile(action, {}, {}, {})

        self.assertEqual(resolved.provider, "openai")
        self.assertEqual(resolved.model, "gpt-4o")
        self.assertEqual(resolved.ai_params.get("temperature"), 0.7)

    def test_transcription_profile_resolution(self):
        # Create a transcription profile
        transcribe_profile = ConnectionProfile(
            provider="transcription",
            model="gemini-3.5-transcribe",
            transcribe_mode="VERBATIM",
            transcribe_diarization=True,
            transcribe_timestamps=True,
            transcribe_language="es-ES",
            transcribe_vocabulary="Kubernetes, BigQuery",
        )
        self.store._profiles["TranscribeProf"] = transcribe_profile.to_dict()

        # Mock key managers
        from unittest.mock import MagicMock

        google_km = MagicMock()
        key_managers = {"google": google_km}

        action = {"connection_profile": "TranscribeProf"}
        resolved = resolve_profile(action, {}, {}, key_managers)

        self.assertEqual(resolved.provider, "transcription")
        self.assertEqual(resolved.model, "gemini-3.5-transcribe")
        self.assertEqual(resolved.config.get("transcription_model"), "gemini-3.5-transcribe")
        self.assertEqual(resolved.config.get("google_model"), "gemini-3.5-transcribe")
        self.assertIn("transcription", resolved.key_managers)
        self.assertEqual(resolved.key_managers["transcription"], google_km)

        # Test to_transcribe_config helper
        cfg = transcribe_profile.to_transcribe_config()
        self.assertEqual(cfg["model"], "gemini-3.5-transcribe")
        self.assertEqual(cfg["mode"], "VERBATIM")
        self.assertTrue(cfg["diarization"])
        self.assertTrue(cfg["word_timestamp"])
        self.assertEqual(cfg["language_codes"], ["es-ES"])
        self.assertEqual(cfg["custom_vocabulary"], ["Kubernetes", "BigQuery"])

    def test_connection_profile_manager_on_provider_change_transcribe_mode(self):
        import tkinter as tk

        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError:
            self.skipTest("No Tk display available")

        from src.gui.windows.connection_manager import ConnectionProfileManager

        cpm = ConnectionProfileManager(root)
        try:
            # Set provider to transcription
            cpm.field_widgets["provider"]["var"].set("transcription")
            cpm._on_provider_change("transcription")

            # Verify transcribe_mode row is packed (visible)
            mode_row = cpm.field_rows.get("transcribe_mode")
            self.assertTrue(bool(mode_row.winfo_manager()))

            # Trigger _on_provider_change as if passed "SMART" from transcribe_mode combobox
            cpm.field_widgets["transcribe_mode"]["var"].set("SMART")
            cpm._on_provider_change("SMART")

            # transcribe_mode, transcribe_language, transcribe_vocabulary must remain visible
            self.assertTrue(bool(mode_row.winfo_manager()))
            self.assertTrue(bool(cpm.field_rows["transcribe_language"].winfo_manager()))
            self.assertTrue(bool(cpm.field_rows["transcribe_vocabulary"].winfo_manager()))

            # Diarization and timestamps should be hidden in SMART mode
            self.assertFalse(bool(cpm.field_rows["transcribe_diarization"].winfo_manager()))
            self.assertFalse(bool(cpm.field_rows["transcribe_timestamps"].winfo_manager()))

            # Switch back to VERBATIM mode
            cpm.field_widgets["transcribe_mode"]["var"].set("VERBATIM")
            cpm._on_provider_change("VERBATIM")

            # Diarization and timestamps should be visible again
            self.assertTrue(bool(cpm.field_rows["transcribe_diarization"].winfo_manager()))
            self.assertTrue(bool(cpm.field_rows["transcribe_timestamps"].winfo_manager()))
        finally:
            cpm.destroy()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
