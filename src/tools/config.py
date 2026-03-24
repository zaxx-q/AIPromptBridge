#!/usr/bin/env python3
"""
Tools Configuration Loader

Loads and manages tools_config.json configuration.
Creates the config file on-demand when user first interacts with tools.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List

from .defaults import DEFAULT_TOOLS_CONFIG

TOOLS_CONFIG_FILE = "tools_config.json"


def get_default_config() -> Dict[str, Any]:
    """
    Get default tools configuration.
    
    Returns:
        Default configuration dictionary from defaults.py
    """
    return DEFAULT_TOOLS_CONFIG.copy()


def ensure_tools_config(filepath: str = TOOLS_CONFIG_FILE) -> Path:
    """
    Ensure tools_config.json exists, creating it from defaults if needed.
    
    This should be called when user first interacts with tools,
    NOT at application startup.
    
    Args:
        filepath: Path to tools_config.json
    
    Returns:
        Path to the config file
    """
    path = Path(filepath)
    
    if not path.exists():
        print(f"[Info] Creating default tools config: {filepath}")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_TOOLS_CONFIG, f, indent=2, ensure_ascii=False)
            print(f"[Success] Created {filepath}")
        except IOError as e:
            print(f"[Error] Failed to create tools config: {e}")
    
    return path


def _merge_with_defaults(user_config: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    """Merge user tools config with defaults, preserving customizations and updating defaults."""
    default_config = get_default_config()
    changed = False

    # Initialize missing top-level keys
    for k in ["_settings", "file_processor"]:
        if k not in user_config:
            user_config[k] = default_config.get(k, {}).copy()
            changed = True

    # Overlay _settings
    for k, v in default_config.get("_settings", {}).items():
        if k not in user_config["_settings"]:
            user_config["_settings"][k] = v
            changed = True

    # Initialize file_processor sub-keys if missing
    for k in ["output_modes", "file_type_mappings"]:
        if k not in user_config["file_processor"]:
            user_config["file_processor"][k] = default_config["file_processor"].get(k, {}).copy()
            changed = True

    # Overlay output_modes
    for k, v in default_config["file_processor"].get("output_modes", {}).items():
        if k not in user_config["file_processor"]["output_modes"]:
            user_config["file_processor"]["output_modes"][k] = v.copy()
            changed = True

    # Overlay file_type_mappings
    for k, v in default_config["file_processor"].get("file_type_mappings", {}).items():
        if k not in user_config["file_processor"]["file_type_mappings"]:
            user_config["file_processor"]["file_type_mappings"][k] = v.copy()
            changed = True

    # Access deleted defaults from settings
    deleted_defaults = user_config.get("_settings", {}).get("deleted_defaults", [])

    # Merge prompts with _is_default tagging
    if "prompts" not in user_config["file_processor"]:
        user_config["file_processor"]["prompts"] = {}
        for name, action in default_config["file_processor"]["prompts"].items():
            if name not in deleted_defaults:
                user_config["file_processor"]["prompts"][name] = action.copy()
                user_config["file_processor"]["prompts"][name]["_is_default"] = True
        changed = True
    else:
        user_prompts = user_config["file_processor"]["prompts"]
        default_prompts = default_config["file_processor"]["prompts"]
        
        # Helper to compare ignoring _is_default
        def compare_prompt(u_act, d_act):
            u_copy = u_act.copy()
            d_copy = d_act.copy()
            u_copy.pop("_is_default", None)
            d_copy.pop("_is_default", None)
            return u_copy == d_copy

        # Tag untagged actions
        for name, u_action in user_prompts.items():
            if not isinstance(u_action, dict): continue
            if "_is_default" not in u_action:
                d_action = default_prompts.get(name)
                if d_action and compare_prompt(u_action, d_action):
                    u_action["_is_default"] = True
                else:
                    u_action["_is_default"] = False
                changed = True

        # Add missing or update default
        for name, d_action in default_prompts.items():
            if name in deleted_defaults:
                continue # Skip re-adding defaults the user explicitly deleted
                
            if name not in user_prompts:
                user_prompts[name] = d_action.copy()
                user_prompts[name]["_is_default"] = True
                changed = True
            elif isinstance(user_prompts[name], dict) and user_prompts[name].get("_is_default", False):
                d_action_tagged = d_action.copy()
                d_action_tagged["_is_default"] = True
                if user_prompts[name] != d_action_tagged:
                    user_prompts[name] = d_action_tagged
                    changed = True

    return user_config, changed

def load_tools_config(filepath: str = TOOLS_CONFIG_FILE, create_if_missing: bool = True) -> Dict[str, Any]:
    """
    Load tools configuration from JSON file.
    
    Args:
        filepath: Path to tools_config.json
        create_if_missing: If True, create the file from defaults when missing
    
    Returns:
        Configuration dictionary
    """
    path = Path(filepath)
    
    if not path.exists():
        if create_if_missing:
            ensure_tools_config(filepath)
        else:
            return get_default_config()
    
    # Re-check after potential creation
    if not path.exists():
        return get_default_config()
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
            merged_config, changed = _merge_with_defaults(user_config)
            if changed:
                with open(path, "w", encoding="utf-8") as fw:
                    json.dump(merged_config, fw, indent=2, ensure_ascii=False)
            return merged_config
    except (json.JSONDecodeError, IOError) as e:
        print(f"[Error] Failed to load tools config: {e}")
        return get_default_config()


def get_file_processor_prompts(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Get file processor prompts from config.
    
    Args:
        config: Tools configuration dictionary
    
    Returns:
        Dictionary of prompt name -> prompt config
    """
    return config.get("file_processor", {}).get("prompts", {})


def get_prompt_by_key(config: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific prompt configuration.
    
    Args:
        config: Tools configuration dictionary
        key: Prompt key name
    
    Returns:
        Prompt configuration or None
    """
    prompts = get_file_processor_prompts(config)
    return prompts.get(key)


def get_setting(config: Dict[str, Any], key: str, default: Any = None) -> Any:
    """
    Get a setting from _settings section.
    
    Args:
        config: Tools configuration dictionary
        key: Setting key
        default: Default value if not found
    
    Returns:
        Setting value
    """
    return config.get("_settings", {}).get(key, default)


def get_file_type_mappings(config: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Get file type mappings from config.
    
    Args:
        config: Tools configuration dictionary
    
    Returns:
        Dictionary of file type -> list of extensions
    """
    return config.get("file_processor", {}).get("file_type_mappings", {})


def resolve_endpoint_prompt(prompt_text: str, endpoints: Dict[str, str]) -> str:
    """
    Resolve @endpoint:name references in prompt text.
    
    Args:
        prompt_text: Prompt text that may contain @endpoint:name
        endpoints: Dictionary of endpoint name -> prompt
    
    Returns:
        Resolved prompt text
    """
    if prompt_text.startswith("@endpoint:"):
        endpoint_name = prompt_text[10:].strip()  # Remove "@endpoint:"
        if endpoint_name in endpoints:
            return endpoints[endpoint_name]
        else:
            print(f"[Warning] Endpoint '{endpoint_name}' not found")
            return prompt_text
    return prompt_text


def list_available_prompts(
    config: Dict[str, Any],
    endpoints: Dict[str, str] = None,
    filter_input_type: str = None
) -> List[Dict[str, Any]]:
    """
    List all available prompts for file processor.
    
    Args:
        config: Tools configuration dictionary
        endpoints: Optional endpoints dict to include endpoint prompts
        filter_input_type: Optional filter by input type (image, text, code)
    
    Returns:
        List of prompt info dicts with keys: key, icon, description, input_types
    """
    result = []
    prompts = get_file_processor_prompts(config)
    
    # Add tool prompts
    for key, prompt_config in prompts.items():
        if key.startswith("_"):
            continue  # Skip internal prompts
        
        input_types = prompt_config.get("input_types", ["image", "text", "code"])
        
        # Apply filter if specified
        if filter_input_type and filter_input_type not in input_types:
            continue
        
        result.append({
            "key": key,
            "icon": prompt_config.get("icon", "📄"),
            "description": prompt_config.get("description", ""),
            "input_types": input_types,
            "source": "tool"
        })
    
    # Add endpoint prompts if provided
    if endpoints:
        for name, prompt in endpoints.items():
            result.append({
                "key": f"@endpoint:{name}",
                "icon": "📡",
                "description": f"Endpoint: {prompt[:50]}..." if len(prompt) > 50 else f"Endpoint: {prompt}",
                "input_types": ["image"],  # Endpoints are typically for images
                "source": "endpoint"
            })
    
    return result