#!/usr/bin/env python3
"""
Config I/O for Settings Window.

Handles parsing and writing config.ini with full round-trip preservation
of comments and structure. Pure data layer — no GUI dependencies.

Classes:
    ConfigData: Structured representation of config.ini sections.

Functions:
    parse_config_full(): Parse config.ini into ConfigData.
    save_config_full(): Write ConfigData back to config.ini.
"""

import re
import shutil
from typing import Dict, Optional, List, Any
from pathlib import Path


class ConfigData:
    """
    Structured representation of config.ini data.
    Preserves comments and structure for round-trip editing.
    """

    def __init__(self):
        self.config: Dict[str, Any] = {}       # [config] section values
        self.ai_params: Dict[str, Any] = {}    # [ai_params] section values
        self.endpoints: Dict[str, str] = {}    # [endpoints] section
        # API keys are now managed by KeyStore (keys.json), not here.
        self.raw_lines: List[str] = []         # Original lines for preservation
        self.comments: Dict[str, str] = {}     # Comments associated with keys


def parse_config_full(filepath: str = "config.ini") -> ConfigData:
    """
    Parse entire config file preserving structure and comments.

    Returns:
        ConfigData with all sections parsed
    """
    data = ConfigData()

    if not Path(filepath).exists():
        return data

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        data.raw_lines = lines
        current_section = None
        multiline_key = None
        multiline_value = []
        last_comment = ""

        for line in lines:
            raw_line = line.rstrip('\n\r')
            stripped = raw_line.strip()

            # Track comments
            if stripped.startswith('#'):
                last_comment = stripped
                continue

            if not stripped:
                last_comment = ""
                continue

            # Section header
            if stripped.startswith('[') and stripped.endswith(']'):
                if multiline_key and current_section == 'endpoints':
                    data.endpoints[multiline_key] = ' '.join(multiline_value)
                    multiline_key = None
                    multiline_value = []
                current_section = stripped[1:-1].lower()
                continue

            # Parse based on section
            if current_section == 'config':
                if '=' in stripped:
                    key, value = stripped.split('=', 1)
                    key = key.strip().lower()
                    value = _parse_value(value.strip())
                    data.config[key] = value
                    if last_comment:
                        data.comments[key] = last_comment
                    last_comment = ""

            elif current_section == 'ai_params':
                if '=' in stripped:
                    key, value = stripped.split('=', 1)
                    key = key.strip().lower()
                    value = _parse_value(value.strip())
                    data.ai_params[key] = value
                    if last_comment:
                        data.comments[f"ai_params.{key}"] = last_comment
                    last_comment = ""

            elif current_section == 'endpoints':
                if '=' in stripped:
                    if multiline_key:
                        data.endpoints[multiline_key] = ' '.join(multiline_value)
                    endpoint_name, prompt = stripped.split('=', 1)
                    endpoint_name = endpoint_name.strip().lower()
                    prompt = prompt.strip()
                    # Remove quotes if present
                    if (prompt.startswith('"') and prompt.endswith('"')) or \
                       (prompt.startswith("'") and prompt.endswith("'")):
                        prompt = prompt[1:-1]
                    if prompt.endswith('\\'):
                        multiline_key = endpoint_name
                        multiline_value = [prompt[:-1].strip()]
                    else:
                        data.endpoints[endpoint_name] = prompt
                        multiline_key = None
                        multiline_value = []
                elif multiline_key:
                    if stripped.endswith('\\'):
                        multiline_value.append(stripped[:-1].strip())
                    else:
                        multiline_value.append(stripped)
                        data.endpoints[multiline_key] = ' '.join(multiline_value)
                        multiline_key = None
                        multiline_value = []

            elif current_section in ('custom', 'openrouter', 'google'):
                # API key sections — now managed by KeyStore (keys.json).
                # Silently skip so old config.ini files don't cause errors.
                pass

        # Flush any remaining multiline
        if multiline_key and current_section == 'endpoints':
            data.endpoints[multiline_key] = ' '.join(multiline_value)

    except Exception as e:
        print(f"[SettingsWindow] Error parsing config: {e}")

    return data


def _parse_value(value_str: str) -> Any:
    """Parse a configuration value from string to appropriate type."""
    value_str = value_str.strip()
    if value_str.lower() in ['none', 'null', '']:
        return None
    # Note: '1'/'0' intentionally excluded - they should parse as int, not bool.
    if value_str.lower() in ['true', 'yes', 'on']:
        return True
    if value_str.lower() in ['false', 'no', 'off']:
        return False
    try:
        if '.' not in value_str:
            return int(value_str)
        return float(value_str)
    except ValueError:
        pass
    # Remove quotes
    if (value_str.startswith('"') and value_str.endswith('"')) or \
       (value_str.startswith("'") and value_str.endswith("'")):
        return value_str[1:-1]
    return value_str


def _value_to_str(value: Any) -> str:
    """Convert a value to config file string format."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def save_config_full(data: ConfigData, filepath: str = "config.ini") -> bool:
    """
    Save full config preserving comments and structure.
    Creates a backup before saving.

    Returns:
        True if save was successful
    """
    try:
        # Create backup
        if Path(filepath).exists():
            backup_path = filepath + ".bak"
            shutil.copy2(filepath, backup_path)

        # Rebuild the file
        lines = []
        current_section = None
        written_keys = set()
        written_ai_params = set()
        written_endpoints = set()

        for line in data.raw_lines:
            raw_line = line.rstrip('\n\r')
            stripped = raw_line.strip()

            # Section header
            if stripped.startswith('[') and stripped.endswith(']'):
                current_section = stripped[1:-1].lower()
                lines.append(raw_line + '\n')
                continue

            # Comment or empty - preserve as-is
            if not stripped or stripped.startswith('#'):
                lines.append(raw_line + '\n')
                continue

            # Handle based on section
            if current_section == 'config' and '=' in stripped:
                key = stripped.split('=', 1)[0].strip().lower()
                if key in data.config:
                    value = _value_to_str(data.config[key])
                    lines.append(f"{key} = {value}\n")
                    written_keys.add(key)
                else:
                    lines.append(raw_line + '\n')

            elif current_section == 'ai_params' and '=' in stripped:
                key = stripped.split('=', 1)[0].strip().lower()
                if key in data.ai_params:
                    value = _value_to_str(data.ai_params[key])
                    lines.append(f"{key} = {value}\n")
                    written_ai_params.add(key)
                else:
                    continue

            elif current_section == 'endpoints' and '=' in stripped:
                # Skip multiline continuations (handled with main key)
                if not stripped.startswith(' ') and not stripped.startswith('\t'):
                    endpoint_name = stripped.split('=', 1)[0].strip().lower()
                    if endpoint_name in data.endpoints and endpoint_name not in written_endpoints:
                        prompt = data.endpoints[endpoint_name]
                        lines.append(f"{endpoint_name} = {prompt}\n")
                        written_endpoints.add(endpoint_name)
                    elif endpoint_name not in written_endpoints:
                        lines.append(raw_line + '\n')
                # Skip continuation lines (they were merged)

            elif current_section in ('custom', 'openrouter', 'google'):
                # API key sections — skip old key lines, they're in keys.json now.
                if stripped and not stripped.startswith('#'):
                    continue
                lines.append(raw_line + '\n')

            else:
                lines.append(raw_line + '\n')

        # Add new config keys not in original file
        config_section_end = _find_section_end(lines, 'config')
        new_config_lines = []
        for key, value in data.config.items():
            if key not in written_keys:
                # Skip None values to avoid cluttering config with defaults that act as "unset"
                if value is None:
                    continue
                new_config_lines.append(f"{key} = {_value_to_str(value)}\n")
        if new_config_lines and config_section_end > 0:
            lines = lines[:config_section_end] + new_config_lines + lines[config_section_end:]

        # Add new ai_params keys not in original file
        ai_params_section_end = _find_section_end(lines, 'ai_params')
        if ai_params_section_end == -1 and data.ai_params:
            # [ai_params] section doesn't exist yet - create it before API key sections
            insert_pos = len(lines)
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('[') and stripped.endswith(']'):
                    sec = stripped[1:-1].lower()
                    if sec in ('custom', 'openrouter', 'google'):
                        insert_pos = i
                        break
            section_lines = ['\n[ai_params]\n']
            for key, value in data.ai_params.items():
                if value is not None:
                    section_lines.append(f"{key} = {_value_to_str(value)}\n")
            lines = lines[:insert_pos] + section_lines + lines[insert_pos:]
        elif ai_params_section_end > 0:
            new_ai_params_lines = []
            for key, value in data.ai_params.items():
                if key not in written_ai_params:
                    if value is None:
                        continue
                    new_ai_params_lines.append(f"{key} = {_value_to_str(value)}\n")
            if new_ai_params_lines:
                lines = lines[:ai_params_section_end] + new_ai_params_lines + lines[ai_params_section_end:]

        # API keys are no longer written to config.ini — managed by KeyStore (keys.json)

        # Write file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        return True

    except Exception as e:
        print(f"[SettingsWindow] Error saving config: {e}")
        return False


def _find_section_end(lines: List[str], section: str) -> int:
    """Find the line index where a section ends (next section or EOF)."""
    in_section = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            if in_section:
                return i
            if stripped[1:-1].lower() == section:
                in_section = True
    return len(lines) if in_section else -1
