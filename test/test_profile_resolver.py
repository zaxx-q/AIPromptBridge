#!/usr/bin/env python3
import unittest
from unittest.mock import MagicMock
from src.connection_profiles import ConnectionProfile, ProfileStore
from src.profile_resolver import resolve_profile, resolve_profile_by_name
import src.web_server as web_server

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
            provider="openai",
            model="gpt-4o",
            base_url="https://active.custom.url/v1",
            temperature=0.7
        )
        self.store._profiles["ActiveProf"] = active_profile.to_dict()
        self.store._active_profile_name = "ActiveProf"
        web_server.ACTIVE_PROFILE = active_profile
        web_server.SESSION_OVERRIDES = {}

        # 2. Create another profile that has an EMPTY base_url (meaning use default provider base_url)
        override_profile = ConnectionProfile(
            provider="google",
            model="gemini-1.5-pro",
            base_url="",
            temperature=0.2
        )
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
            provider="openai",
            model="gpt-4o",
            base_url="https://active.custom.url/v1",
            temperature=0.7,
            max_tokens=150
        )
        web_server.ACTIVE_PROFILE = active_profile
        web_server.SESSION_OVERRIDES = {}

        resolved = resolve_profile(None, {}, {}, {})

        self.assertEqual(resolved.config.get("base_url"), "https://active.custom.url/v1")
        self.assertEqual(resolved.ai_params.get("temperature"), 0.7)
        self.assertEqual(resolved.ai_params.get("max_tokens"), 150)

if __name__ == "__main__":
    unittest.main()
