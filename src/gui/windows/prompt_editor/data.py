#!/usr/bin/env python3
"""
Data utilities for the Prompt Editor.

Handles loading/saving prompts.json and defines shared constants.
"""

import json
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

from ...prompts import PROMPTS_FILE, reload_prompts

# =============================================================================
# Constants
# =============================================================================

OPTIONS_FILE = PROMPTS_FILE

# Action keys a tool's popup never renders as a button, even when a group lists them.
# ("Custom" collides with the pseudo-action the Text Edit popup adds itself.)
_POPUP_RESERVED_ACTIONS: Dict[str, frozenset] = {"text_edit_tool": frozenset({"Custom"})}

# =============================================================================
# Popup group helpers
# =============================================================================


def group_action_status(tool: str, tool_data: Dict, name: str) -> str:
    """
    Classify an action name referenced by a popup group.

    Mirrors the filtering the popups apply when they render a group:
      "ok"      - the action exists and the popup will show it
      "hidden"  - the action exists but is marked _hidden, so the popup skips it
      "missing" - no such action (deleted, or a typo), so the popup skips it
    """
    action = tool_data.get(name) if isinstance(name, str) else None
    if not isinstance(action, dict) or name.startswith("_") or name in _POPUP_RESERVED_ACTIONS.get(tool, ()):
        return "missing"
    return "hidden" if action.get("_hidden", False) else "ok"


def get_group_action_choices(tool: str, tool_data: Dict) -> List[Tuple[str, str]]:
    """
    Return (name, icon) for every action that can be added to a popup group.

    Order matches the Actions tab. Hidden actions are left out because the popups
    would not show them anyway.
    """
    return [
        (name, action.get("icon") or "")
        for name, action in tool_data.items()
        if group_action_status(tool, tool_data, name) == "ok"
    ]


# =============================================================================
# JSON I/O
# =============================================================================


def load_options(filepath: str = PROMPTS_FILE) -> Dict:
    """
    Load and parse options JSON.
    Uses centralized PromptsConfig which handles defaults if file is missing.
    """
    from ...prompts import get_prompts_config

    try:
        # Simply get the config from PromptsConfig which handles loading/defaults
        return get_prompts_config()._config
    except Exception as e:
        print(f"[PromptEditor] Error loading options: {e}")
        return {}


def save_options(data: Dict, filepath: str = OPTIONS_FILE) -> bool:
    """
    Save options with proper formatting.
    Creates a backup before saving.

    Returns:
        True if save was successful
    """
    try:
        # Create backup
        if Path(filepath).exists():
            backup_path = filepath + ".bak"
            shutil.copy2(filepath, backup_path)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Reload prompts in the main app
        reload_prompts()

        return True
    except Exception as e:
        print(f"[PromptEditor] Error saving options: {e}")
        return False
