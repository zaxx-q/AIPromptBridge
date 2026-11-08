#!/usr/bin/env python3
"""Tests for PromptsConfig loading, saving, and default preservation."""

import json
import os
import shutil

from src.gui.prompts import (
    DEFAULT_AUDIO_ACTIONS,
    DEFAULT_GLOBAL_SETTINGS,
    DEFAULT_SNIP_ACTIONS,
    DEFAULT_TEXT_EDIT_ACTIONS,
    MINIMAL_AUDIO_ACTIONS,
    MINIMAL_MODIFIERS,
    MINIMAL_SNIP_ACTIONS,
    MINIMAL_TEXT_EDIT_ACTIONS,
    PromptsConfig,
    get_minimal_prompt_preset,
)
from src.tools.config import load_tools_config


class TestPromptsConfig:
    """Test PromptsConfig default tagging and preservation."""

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
            os.remove("prompts_backup_test.json")
        if os.path.exists("tools_config.json"):
            os.remove("tools_config.json")

    def test_defaults_tagged(self):
        config = PromptsConfig()
        actions = config.get_text_edit_actions()
        assert actions.get("Explain", {}).get("_is_default") is True

    def test_user_modification_preserved(self):
        config = PromptsConfig()
        config._config["text_edit_tool"]["Explain"]["_is_default"] = False
        config._config["text_edit_tool"]["Explain"]["system_prompt"] += " Test suffix."
        config._save()

        config2 = PromptsConfig()
        config2.reload()
        actions2 = config2.get_text_edit_actions()
        assert actions2["Explain"]["_is_default"] is False
        assert actions2["Explain"]["system_prompt"].endswith("Test suffix.")

    def test_tools_config_defaults(self):
        if os.path.exists("tools_config.json"):
            os.remove("tools_config.json")
        tools_cfg = load_tools_config()
        ocr = tools_cfg.get("file_processor", {}).get("prompts", {}).get("OCR (Verbatim)", {})
        assert ocr.get("_is_default") is True

    def test_tools_config_user_edit_preserved(self):
        if os.path.exists("tools_config.json"):
            os.remove("tools_config.json")
        tools_cfg = load_tools_config()
        tools_cfg["file_processor"]["prompts"]["OCR (Verbatim)"]["_is_default"] = False
        tools_cfg["file_processor"]["prompts"]["OCR (Verbatim)"]["description"] += " Test desc"
        with open("tools_config.json", "w") as f:
            json.dump(tools_cfg, f)

        tools_cfg_2 = load_tools_config()
        ocr2 = tools_cfg_2["file_processor"]["prompts"]["OCR (Verbatim)"]
        assert ocr2["_is_default"] is False
        assert ocr2["description"].endswith("Test desc")

    def test_minimal_prompt_presets_validity(self):
        """Verify minimal presets are valid and exist in defaults."""
        assert MINIMAL_TEXT_EDIT_ACTIONS.issubset(set(DEFAULT_TEXT_EDIT_ACTIONS.keys()))
        assert MINIMAL_SNIP_ACTIONS.issubset(set(DEFAULT_SNIP_ACTIONS.keys()))
        assert MINIMAL_AUDIO_ACTIONS.issubset(set(DEFAULT_AUDIO_ACTIONS.keys()))

        mod_keys = {m["key"] for m in DEFAULT_GLOBAL_SETTINGS.get("modifiers", [])}
        assert MINIMAL_MODIFIERS.issubset(mod_keys)

        # Essential actions are present
        assert "Explain" in MINIMAL_TEXT_EDIT_ACTIONS
        assert "Summary" in MINIMAL_TEXT_EDIT_ACTIONS
        assert "Proofread" in MINIMAL_TEXT_EDIT_ACTIONS
        assert "Refine" in MINIMAL_TEXT_EDIT_ACTIONS
        assert "Humanize" in MINIMAL_TEXT_EDIT_ACTIONS
        assert "To Markdown" in MINIMAL_TEXT_EDIT_ACTIONS

        assert "Quick Extract" in MINIMAL_SNIP_ACTIONS
        assert "Smart Extract" in MINIMAL_SNIP_ACTIONS
        assert "Summarize" in MINIMAL_SNIP_ACTIONS
        assert "To Markdown" in MINIMAL_SNIP_ACTIONS

        assert "Transcribe" in MINIMAL_AUDIO_ACTIONS
        assert "Summarize" in MINIMAL_AUDIO_ACTIONS
        assert "Extract Key Points" in MINIMAL_AUDIO_ACTIONS

        # Test helper function
        assert get_minimal_prompt_preset("text_edit_tool") == MINIMAL_TEXT_EDIT_ACTIONS
        preset_copy = get_minimal_prompt_preset("text_edit_tool")
        preset_copy.clear()
        assert len(MINIMAL_TEXT_EDIT_ACTIONS) > 0  # ensure copy, not reference

        # Test OnboardingWizard backward compatibility
        from src.gui.windows.onboarding_window import OnboardingWizard

        assert OnboardingWizard.WIZARD_MINIMAL_TEXT_EDIT == MINIMAL_TEXT_EDIT_ACTIONS
        assert OnboardingWizard.WIZARD_MINIMAL_SNIP == MINIMAL_SNIP_ACTIONS
        assert OnboardingWizard.WIZARD_MINIMAL_AUDIO == MINIMAL_AUDIO_ACTIONS
        assert OnboardingWizard.WIZARD_MINIMAL_MODIFIERS == MINIMAL_MODIFIERS
