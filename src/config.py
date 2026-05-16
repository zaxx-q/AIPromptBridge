#!/usr/bin/env python3
"""
Configuration loading and management
"""

import os
import re
import logging
import threading
from pathlib import Path

# Configuration file paths
CONFIG_FILE = "config.ini"
SESSIONS_FILE = "chat_sessions.json"

# Default configuration
DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 5000,
    "max_retries": 3,
    "retry_delay": 5,
    "request_timeout": 120,
    "max_sessions": 200,
    # Show AI response in chat window: yes or no
    # This controls whether responses appear in a GUI window or are typed directly.
    # For API endpoints: overridden by ?show=yes/no URL parameter
    # For TextEditTool: overridden by show_chat_window_instead_of_replace per-action setting,
    # which is further overridden by popup radio button selection
    "show_ai_response_in_chat_window": False,
    # Session Auto-Save Setting:
    # controls when new sessions are automatically created and persisted to disk.
    # Note: A session is ALWAYS saved when receiving an AI response or sending a reply.
    # - "on_followup": Create session only when receiving AI response or sending a reply.
    # - "on_attachment": Create session when chat window has attachments.
    # - "always_window": Create session whenever a new chat window is opened from Tools.
    "auto_save_session": "on_attachment",
    # How to handle thinking output: filter, raw, or reasoning_content
    # This is a display preference, NOT a connection setting.
    # - filter: Hide thinking content
    # - raw: Include thinking in main response
    # - reasoning_content: Separate field (for collapsible display)
    "thinking_output": "reasoning_content",
    # TextEditTool settings
    "text_edit_tool_enabled": True,
    "text_edit_tool_hotkey": "ctrl+space",
    # Hotkey to abort streaming typing (default: escape)
    "text_edit_tool_abort_hotkey": "escape",
    # Delay between characters when streaming to text field (ms)
    # Lower = faster typing. Default: 5
    "streaming_typing_delay": 5,
    # Uncap typing speed - type at maximum speed from server stream
    # WARNING: May cause issues with some applications (input lag, missed characters)
    "streaming_typing_uncapped": False,
    # Screen Snipping Tool settings
    "screen_snip_enabled": True,
    "screen_snip_hotkey": "ctrl+alt+x",
    # Flask endpoints settings
    # Enable/disable Flask API endpoints for external tools like ShareX
    # When disabled, endpoints from prompts.json are not registered
    # Default: False (use built-in screen snipping instead)
    "flask_endpoints_enabled": False,
    # UI Theme settings
    # Available themes: catppuccin, dracula, nord, gruvbox, onedark, minimal, highcontrast
    "ui_theme": "dracula",
    # Theme mode: auto (follows system), dark, light
    "ui_theme_mode": "auto",
    # UI Framework settings
    # Force use of standard Tkinter even if CustomTkinter is available (fallback mode)
    "ui_force_standard_tk": False,
    # Session attachment settings
    # Image format for saving session attachments: png, jpg, webp (default)
    "session_image_format": "webp",
    # Image quality for lossy formats (jpg, webp): 1-100
    "session_image_quality": 85,
    # Audio Tool settings
    "audio_tool_enabled": True,
    "audio_tool_hotkey": "ctrl+alt+a",
    "audio_default_device": "default",
    "audio_default_loopback": True,
    # Level meter display style
    # - canvas: Custom canvas with grid lines and color gradient (default)
    # - progressbar: Smooth, simple progress bar
    "audio_level_meter_style": "canvas",
    # TTS (Text-to-Speech) settings
    # Audio output format for all tools (Audio Analyzer save, TTS save)
    # Options: ogg (Opus, recommended), mp3, wav, flac, m4a (AAC)
    "audio_output_format": "ogg",
    "tts_enabled": True,
    "tts_hotkey": "ctrl+alt+t",
    "tts_default_voice": "Kore",
    "tts_default_model": "gemini-2.5-flash-preview-tts",
    "tts_director_enabled": True,
    "tts_director_auto_mode": False,
    # Model override for AI Director (empty = use default provider model)
    "tts_director_model": "",
    # Directory for saved TTS audio files
    "tts_save_directory": "audio_output",
    # Automatically play generated audio
    "tts_autoplay": True,
    # Force TTS to use official Google endpoint even when gemini_endpoint is set
    "tts_use_official_endpoint": False,
    # Chat window system prompt behavior
    # true = Use the originating action's system prompt for follow-up messages
    # false = Always use chat_window_system_instruction from prompts.json
    "chat_use_origin_system_prompt": True,
    # Chat message background coloring
    # Enable/disable colored backgrounds for user/assistant messages
    "chat_message_bg_enabled": True,
    # Custom background colors (hex, empty = use theme default)
    "chat_user_bg_color": "",
    "chat_assistant_bg_color": "",
    # Profile selector mode
    # true = Show connection profiles in dropdowns (if profiles exist) instead of model list
    # false = Always show model list in dropdowns
    "profile_selector_enabled": True,
    # Update settings
    "update_check_enabled": True,       # Auto-check on startup
}

# API URLs
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def parse_config_value(value_str):
    """Parse a configuration value from string to appropriate type"""
    value_str = value_str.strip()
    if value_str.lower() in ['none', 'null', '']:
        return None
    # Use 'true'/'false' for boolean values in config.
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
    if (value_str.startswith('"') and value_str.endswith('"')) or \
       (value_str.startswith("'") and value_str.endswith("'")):
        return value_str[1:-1]
    return value_str


def load_config(filepath=CONFIG_FILE):
    """Load configuration from .ini file.
    
    Returns:
        config dict. AI parameters are managed by Connection Profiles
        (profiles.json). Endpoints are loaded from prompts.json via PromptsConfig.
        API keys are managed separately by KeyStore (keys.json).
    """
    config = dict(DEFAULT_CONFIG)
    
    if not Path(filepath).exists():
        print(f"[Warning] Config file '{filepath}' not found. Using defaults.")
        return config
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        current_section = None
        seen_config_keys = set()
        
        for line in lines:
            raw_line = line.rstrip('\n\r')
            stripped = raw_line.strip()
            
            if not stripped or stripped.startswith('#'):
                continue
            
            if stripped.startswith('[') and stripped.endswith(']'):
                current_section = stripped[1:-1].lower()
                continue
            
            if current_section == 'config':
                if '=' in stripped:
                    key, value = stripped.split('=', 1)
                    key = key.strip().lower()
                    value = parse_config_value(value)
                    if key in DEFAULT_CONFIG:
                        if key in seen_config_keys:
                            print(f"[Warning] Duplicate config key '{key}' in config.ini (using last value)")
                        seen_config_keys.add(key)
                        config[key] = value
                    else:
                        print(f"[Warning] Unknown key '{key}' in [config] section (ignored).")
            
            # [ai_params], [endpoints], and API key sections ([custom],
            # [openrouter], [google]) are silently ignored here.
            # ai_params: managed by Connection Profiles (profiles.json)
            # endpoints: managed by PromptsConfig (prompts.json)
            # API keys: managed by KeyStore (keys.json)
        
    except Exception as e:
        print(f"[Error] Failed to load config: {e}")
    
    return config


def load_key_names(filepath=CONFIG_FILE):
    """
    Load API key display names from config.ini inline comments.
    
    Parses lines like:
        sk-abc123   # My Key Name
    and returns the name part for each key, in order.
    
    This is separate from load_config() to keep concerns distinct.
    
    Returns:
        Dict[str, List[str]]: Mapping of provider -> list of key names.
        Names are empty strings for keys without inline comments.
    """
    key_names = {"custom": [], "openrouter": [], "google": []}
    
    if not Path(filepath).exists():
        return key_names
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        current_section = None
        
        for line in lines:
            stripped = line.strip()
            
            if not stripped or stripped.startswith('#'):
                continue
            
            if stripped.startswith('[') and stripped.endswith(']'):
                current_section = stripped[1:-1].lower()
                continue
            
            if current_section in key_names:
                if stripped and not stripped.startswith('#'):
                    match = re.search(r'\s+#\s*(.+)$', stripped)
                    if match:
                        name = match.group(1).strip()
                    else:
                        name = ""
                    # Only append if there's an actual key part
                    key_match = re.search(r'\s+#', stripped)
                    if key_match:
                        key_part = stripped[:key_match.start()].strip()
                    else:
                        key_part = stripped.strip()
                    if key_part:
                        key_names[current_section].append(name)
    except Exception as e:
        logging.debug(f"[Config] Failed to load key names: {e}")
    
    return key_names


# ──────────────────────────────────────────────────────────────
# Config change notification (pub/sub)
# ──────────────────────────────────────────────────────────────
_config_listeners = []
_config_listeners_lock = threading.Lock()


def subscribe_config_change(callback):
    """Register a callback for config value changes.
    
    Callback signature: callback(key: str, value: Any)
    Called whenever a config value is saved via save_config_value() or
    explicitly via notify_config_change().
    """
    with _config_listeners_lock:
        if callback not in _config_listeners:
            _config_listeners.append(callback)


def unsubscribe_config_change(callback):
    """Remove a previously registered config change callback."""
    with _config_listeners_lock:
        try:
            _config_listeners.remove(callback)
        except ValueError:
            pass


def notify_config_change(key: str, value=None):
    """Fire all registered config change callbacks.
    
    Safe to call from any thread. Callbacks are invoked synchronously
    on the caller's thread — GUI-bound listeners must marshal to the
    main thread themselves.
    """
    with _config_listeners_lock:
        listeners = list(_config_listeners)
    for cb in listeners:
        try:
            cb(key, value)
        except Exception:
            pass  # Never let a listener crash the caller


def save_config_value(key: str, value, filepath=CONFIG_FILE):
    """Update a single config value in the config file"""
    try:
        if not Path(filepath).exists():
            return False
        
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Convert value to string
        if isinstance(value, bool):
            value_str = "true" if value else "false"
        elif value is None:
            value_str = "none"
        else:
            value_str = str(value)
        
        # Find and update the key in [config] section
        in_config_section = False
        found = False
        new_lines = []
        
        for line in lines:
            stripped = line.strip()
            
            # Track section
            if stripped.startswith('[') and stripped.endswith(']'):
                in_config_section = stripped.lower() == '[config]'
            
            # Update key if in config section
            if in_config_section and stripped.startswith(f"{key} =") or stripped.startswith(f"{key}="):
                new_lines.append(f"{key} = {value_str}\n")
                found = True
            else:
                new_lines.append(line)
        
        # If not found, add it to [config] section
        if not found:
            final_lines = []
            added = False
            for line in new_lines:
                final_lines.append(line)
                if not added and line.strip().lower() == '[config]':
                    final_lines.append(f"{key} = {value_str}\n")
                    added = True
            new_lines = final_lines
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        
        notify_config_change(key, value)
        return True
    except Exception as e:
        print(f"[Error] Failed to save config: {e}")
        return False


def generate_example_config():
    """Generate example configuration file content"""
    return '''# ============================================================
# AIPromptBridge - AI Desktop Tools & Integration Bridge
# ============================================================

[config]
# Server settings
host = 127.0.0.1
port = 5000

# ============================================================
# RESPONSE DISPLAY SETTINGS
# ============================================================
# Show AI response in a chat window (yes) or type directly (no)
#
# Override hierarchy (highest to lowest priority):
# 1. ?show=yes/no URL parameter (API endpoints only)
# 2. Popup radio button selection (TextEditTool, if not "Default")
# 3. show_chat_window_instead_of_replace per-action setting (TextEditTool)
# 4. This global setting (show_ai_response_in_chat_window)
show_ai_response_in_chat_window = false

# Session Auto-Save Setting:
# controls when new sessions are automatically created and persisted to disk.
# Note: A session is ALWAYS saved when receiving an AI response or sending a reply.
# - "on_followup": Create session only when user sends a reply.
# - "on_attachment": Create session when replying OR when attaching files to a new window.
# - "always_window": Create session whenever a new chat window is opened.
auto_save_session = on_attachment

# Retry settings
max_retries = 3
retry_delay = 5
# request_timeout is also set here as a fallback; active profile overrides it.
request_timeout = 120

# Session management
max_sessions = 200

# ============================================================
# THINKING OUTPUT DISPLAY
# ============================================================
# How to handle thinking output: filter, raw, or reasoning_content
# - filter: Hide thinking content
# - raw: Include thinking in main response
# - reasoning_content: Separate field (for collapsible display)
# This is a display preference and does NOT change when switching profiles.
thinking_output = reasoning_content

# ============================================================
# TEXT EDIT TOOL - Hotkey-triggered text processing with AI
# ============================================================
# Enable/disable TextEditTool
text_edit_tool_enabled = true

# Hotkey combination (e.g., ctrl+space, ctrl+alt+w)
text_edit_tool_hotkey = ctrl+space

# Hotkey to abort streaming typing (default: escape)
# Press this key to stop mid-stream typing
text_edit_tool_abort_hotkey = escape

# Delay between characters when streaming to text field (milliseconds)
# Lower = faster typing. Default: 5
streaming_typing_delay = 5

# Uncap typing speed - type at maximum speed from server stream
# WARNING: Setting to true may cause issues with some applications
# (input lag, missed characters, application freezing). Use with caution!
streaming_typing_uncapped = false

# ============================================================
# SCREEN SNIPPING TOOL - Capture screen regions for AI analysis
# ============================================================
# Enable/disable screen snipping feature
screen_snip_enabled = true

# Hotkey combination (e.g., ctrl+alt+x)
screen_snip_hotkey = ctrl+alt+x

# ============================================================
# AUDIO TOOL - Audio recording and analysis with AI
# ============================================================
# Enable/disable Audio Tool feature
audio_tool_enabled = true

# Hotkey combination (e.g., ctrl+alt+a)
audio_tool_hotkey = ctrl+alt+a

# Default input device ("default" = system default)
# Partial names allowed for matching (e.g., "High Definition" matches "Speakers (2- High Definition Audio Device)")
# Matching is case-insensitive
audio_default_device = default

# Default to loopback (system audio) instead of microphone?
# true = Record what you hear (system audio)
# false = Record microphone input
audio_default_loopback = true

# Level meter display style
# - canvas: Custom canvas with grid lines and color gradient (default)
# - progressbar: Smooth, simple progress bar
audio_level_meter_style = canvas

# ============================================================
# AUDIO OUTPUT FORMAT (shared across tools)
# ============================================================
# Format for saved audio files (Audio Analyzer, TTS)
# Options: ogg (Opus, recommended), mp3, wav, flac, m4a (AAC)
audio_output_format = ogg

# ============================================================
# TTS (TEXT-TO-SPEECH) - Gemini-powered speech synthesis
# ============================================================
# Enable/disable TTS feature
tts_enabled = true

# Hotkey combination (e.g., ctrl+alt+t)
tts_hotkey = ctrl+alt+t

# Default voice (see Voice Reference in docs for all 30 options)
tts_default_voice = Kore

# Default TTS model
# Options: gemini-2.5-flash-preview-tts, gemini-2.5-pro-preview-tts
tts_default_model = gemini-2.5-flash-preview-tts

# Enable AI Director (auto-generates style instructions for expressive speech)
tts_director_enabled = true

# Auto mode: automatically run director before generating audio
# false = manual (click Generate Style first, review, then Generate Audio)
# true = auto (Generate Audio runs director automatically)
tts_director_auto_mode = false

# Model override for AI Director (leave empty to use default provider model)
tts_director_model =

# Directory for saved TTS audio files (relative to app root)
tts_save_directory = audio_output

# Automatically play generated audio
# true = play immediately after generation
# false = wait for user to press play
tts_autoplay = true

# Force TTS to use the official Google endpoint
# When true, TTS always uses https://generativelanguage.googleapis.com/v1beta
# regardless of gemini_endpoint setting (useful when using a proxy that
# doesn't support TTS models)
tts_use_official_endpoint = false

# ============================================================
# FLASK API ENDPOINTS (Optional)
# ============================================================
# Enable Flask endpoints for external tools like ShareX
# When disabled (default), use built-in screen snipping instead
# Set to true if you need to integrate with external tools
# Endpoint prompts are defined in prompts.json (endpoints section)
flask_endpoints_enabled = false

# ============================================================
# UI THEME SETTINGS
# ============================================================
# Available themes: catppuccin, dracula, nord, gruvbox, onedark, minimal, highcontrast
ui_theme = dracula

# Theme mode: auto (follows system dark/light), dark, light
ui_theme_mode = auto

# UI Framework settings
# Force use of standard Tkinter even if CustomTkinter is available (fallback mode)
# Useful for debugging or low-resource environments
ui_force_standard_tk = false

# ============================================================
# SESSION ATTACHMENT SETTINGS
# ============================================================
# Image format for saving session attachments
# Options: png, jpg, webp (default)
session_image_format = webp

# Image quality for lossy formats (1-100)
# Higher = better quality but larger file size
session_image_quality = 85

# ============================================================
# CHAT WINDOW BEHAVIOR
# ============================================================
# Chat window system prompt behavior
# true = Use the originating action's system prompt for follow-up messages
# false = Always use chat_window_system_instruction from prompts.json
chat_use_origin_system_prompt = true

# Chat message background coloring
# Enable/disable colored backgrounds for user/assistant messages in the chat window
# false = transparent (no background tinting)
chat_message_bg_enabled = true

# Custom background colors for chat messages (hex color, empty = use theme default)
# Examples: #1e3a5f (blue-ish for user), #1e3e2e (green-ish for assistant)
# Leave empty to use the current theme's default colors
chat_user_bg_color =
chat_assistant_bg_color =

# Profile selector mode
# When enabled and connection profiles are defined in prompts.json,
# model dropdowns (Chat Window, Audio Analyzer) show profile names
# instead of the full model list.
# true = use profile dropdown (if profiles exist)
# false = always show model list
profile_selector_enabled = true

# ============================================================
# UPDATE SETTINGS
# ============================================================
# Automatically check for updates on startup
update_check_enabled = true

# ============================================================
# AI PARAMETERS — Now in Connection Profiles (profiles.json)
# ============================================================
# temperature, max_tokens, and other AI parameters are now managed
# per-profile via the Connection Profile Manager.

# ============================================================
# API KEYS — Now in keys.json (managed by KeyStore)
# ============================================================
# API keys have moved to keys.json for better security.
# Run the app once to auto-migrate existing keys from config.ini.
# Use Settings > API Keys to manage key pools.
'''

