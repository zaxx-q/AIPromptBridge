#!/usr/bin/env python3
"""
Data utilities for the Prompt Editor.

Handles loading/saving prompts.json and defines shared constants.
"""

import json
import shutil
from pathlib import Path
from typing import Dict

from ...prompts import PROMPTS_FILE, reload_prompts


# =============================================================================
# Constants
# =============================================================================

OPTIONS_FILE = PROMPTS_FILE



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
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        # Reload prompts in the main app
        reload_prompts()
        
        return True
    except Exception as e:
        print(f"[PromptEditor] Error saving options: {e}")
        return False
