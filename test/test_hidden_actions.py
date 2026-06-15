#!/usr/bin/env python3
"""Tests for _hidden action and modifier filtering and management."""

import os
import shutil

from src.gui.prompts import PromptsConfig


class TestHiddenActions:
    """Test hidden actions and modifiers visibility toggles."""

    def setup_method(self):
        """Backup prompts.json if it exists."""
        self._backup = False
        if os.path.exists("prompts.json"):
            shutil.copy("prompts.json", "prompts_backup_test.json")
            os.remove("prompts.json")
            self._backup = True

    def teardown_method(self):
        """Restore prompts.json and clean up."""
        if self._backup:
            shutil.copy("prompts_backup_test.json", "prompts.json")
            if os.path.exists("prompts_backup_test.json"):
                os.remove("prompts_backup_test.json")
        else:
            if os.path.exists("prompts.json"):
                os.remove("prompts.json")

    def test_hidden_action_filtering(self):
        # Reset and load
        config = PromptsConfig()
        config.reset_to_defaults()

        # Hide "Explain" under text_edit_tool
        config.set_action_hidden("text_edit_tool", "Explain", True)
        config._save()

        # Reload configuration
        config2 = PromptsConfig()
        config2.reload()

        # Get actions (include_hidden=False by default)
        actions = config2.get_text_edit_actions()
        assert "Explain" not in actions

        # Get actions (include_hidden=True)
        actions_with_hidden = config2.get_text_edit_actions(include_hidden=True)
        assert "Explain" in actions_with_hidden
        assert actions_with_hidden["Explain"].get("_hidden") is True

        # Unhide
        config2.set_action_hidden("text_edit_tool", "Explain", False)
        config2._save()

        config3 = PromptsConfig()
        config3.reload()
        actions3 = config3.get_text_edit_actions()
        assert "Explain" in actions3
        assert "_hidden" not in actions3.get("Explain", {})

    def test_hidden_modifier_filtering(self):
        # Reset and load
        config = PromptsConfig()
        config.reset_to_defaults()

        # Hide "direct" modifier
        config.set_modifier_hidden("direct", True)
        config._save()

        # Reload
        config2 = PromptsConfig()
        config2.reload()

        # Get modifiers (include_hidden=False by default)
        mods = config2.get_modifiers()
        mod_keys = [m.get("key") for m in mods]
        assert "direct" not in mod_keys

        # Get modifiers (include_hidden=True)
        mods_with_hidden = config2.get_modifiers(include_hidden=True)
        mod_keys_all = [m.get("key") for m in mods_with_hidden]
        assert "direct" in mod_keys_all
        direct_mod = next(m for m in mods_with_hidden if m.get("key") == "direct")
        assert direct_mod.get("_hidden") is True
