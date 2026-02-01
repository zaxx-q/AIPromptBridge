#!/usr/bin/env python3
"""
Windows package - modular GUI window implementations.

This package provides:
- Chat windows (StandaloneChatWindow, AttachedChatWindow)
- Session browser windows (StandaloneSessionBrowserWindow, AttachedBrowserWindow)
- Utility functions (get_icon_path, set_window_icon)
- List components (SessionListItem, SessionListHeader)

All exports are backward-compatible with the original monolithic windows.py.
"""

# Utility functions
from .utils import get_icon_path, set_window_icon

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

# Base classes (for extension)
from .base import ChatWindowBase, BrowserWindowBase

# Audio analyzer window
from .audio_analyzer import (
    AudioAnalyzerWindow,
    create_audio_analyzer_window
)

__all__ = [
    # Utils
    'get_icon_path',
    'set_window_icon',
    
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
    
    # Audio analyzer
    'AudioAnalyzerWindow',
    'create_audio_analyzer_window',
    
    # Base classes
    'ChatWindowBase',
    'BrowserWindowBase',
]
