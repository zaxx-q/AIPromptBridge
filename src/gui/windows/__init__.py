#!/usr/bin/env python3
"""
Windows package - modular GUI window implementations.

This package provides:
- Chat windows (StandaloneChatWindow, AttachedChatWindow)
- Session browser windows (StandaloneSessionBrowserWindow, AttachedBrowserWindow)
- Settings window (SettingsWindow, show_settings_window)
- Prompt editor window (PromptEditorWindow, show_prompt_editor)
- Audio analyzer window (AudioAnalyzerWindow)
- Utility functions (get_icon_path, set_window_icon)
- Base classes for extension
"""

# Utility functions
from .utils import get_icon_path, set_window_icon

# Base classes (for extension)
from .chat_base import ChatWindowBase
from .session_browser import BrowserWindowBase

# Session list components
from .session_browser import SessionListItem, SessionListHeader

# Chat windows
from .chat_window import (
    StandaloneChatWindow,
    AttachedChatWindow,
    create_attached_chat_window
)

# Session browser windows
from .session_browser import (
    StandaloneSessionBrowserWindow,
    AttachedBrowserWindow,
    create_attached_browser_window
)

# Settings window
from .settings_window import (
    SettingsWindow,
    create_attached_settings_window,
    show_settings_window
)

# Prompt editor window
from .prompt_editor import (
    PromptEditorWindow,
    create_attached_prompt_editor_window,
    show_prompt_editor
)

# Audio analyzer window
from .audio_analyzer import (
    AudioAnalyzerWindow,
    create_audio_analyzer_window
)

# TTS window
from .tts_window import (
    TTSWindow,
    create_tts_window
)

__all__ = [
    # Utils
    'get_icon_path',
    'set_window_icon',
    
    # Base classes
    'ChatWindowBase',
    'BrowserWindowBase',
    
    # List components
    'SessionListItem',
    'SessionListHeader',
    
    # Chat windows
    'StandaloneChatWindow',
    'AttachedChatWindow',
    'create_attached_chat_window',
    
    # Browser windows
    'StandaloneSessionBrowserWindow',
    'AttachedBrowserWindow',
    'create_attached_browser_window',
    
    # Settings window
    'SettingsWindow',
    'create_attached_settings_window',
    'show_settings_window',
    
    # Prompt editor window
    'PromptEditorWindow',
    'create_attached_prompt_editor_window',
    'show_prompt_editor',
    
    # Audio analyzer
    'AudioAnalyzerWindow',
    'create_audio_analyzer_window',
    
    # TTS window
    'TTSWindow',
    'create_tts_window',
]
