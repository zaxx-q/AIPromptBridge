#!/usr/bin/env python3
"""
Settings Window Package for AIPromptBridge.

Modular settings window split into:
- config_io.py: ConfigData, parse/save config.ini (pure data, no GUI)
- widgets.py: ToggleSwitch, FormFieldsMixin (uniform layout helpers)
- core.py: SettingsWindow class composing all tab mixins
- tab_general.py: General tab (startup/autostart, behavior, updates, server)
- tab_provider.py: Connection tab (connection profile, key pools, request settings)
- tab_tools.py: Tools tab (TextEditTool, ScreenSnip, Audio Tool, Typing)
- tab_tts.py: TTS tab (text-to-speech, director, export)
- tab_keys.py: API Keys tab (key management per provider)
- tab_theme.py: Theme tab (theme, mode, chat colors, preview)

Public API:
- SettingsWindow: Main settings window class
- AttachedSettingsWindow: Settings as child of GUICoordinator root
- create_attached_settings_window: Factory for attached settings
- show_settings_window: Thread-safe shortcut to show settings
"""

from .core import (
    AttachedSettingsWindow,
    SettingsWindow,
    create_attached_settings_window,
    show_settings_window,
)

__all__ = [
    "AttachedSettingsWindow",
    "SettingsWindow",
    "create_attached_settings_window",
    "show_settings_window",
]
