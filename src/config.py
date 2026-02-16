#!/usr/bin/env python3
"""
Configuration loading and management
"""

import os
import re
from pathlib import Path

# Configuration file paths
CONFIG_FILE = "config.ini"
SESSIONS_FILE = "chat_sessions.json"

# Import endpoint prompts from unified prompts module
# This avoids circular imports by using a late import pattern
def _get_default_endpoints():
    """Get default endpoints from prompts module."""
    from src.gui.prompts import DEFAULT_ENDPOINTS
    return dict(DEFAULT_ENDPOINTS)

# Default configuration
DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 5000,
    "default_provider": "google",
    # Custom URL: If it contains "google" or "googleapis.com",
    # Google-specific behavior is automatically applied
    "custom_url": "https://api.openai.com/v1/chat/completions",
    "custom_model": "gpt-5.2",
    "openrouter_model": "openai/gpt-oss-120b:free",
    "google_model": "gemma-3-27b-it",
    "gemini_endpoint": None,
    "max_retries": 3,
    "retry_delay": 5,
    "request_timeout": 120,
    "max_sessions": 200,
    # Show AI response in chat window: yes or no
    # This controls whether responses appear in a GUI window or are typed directly.
    # For API endpoints: overridden by ?show=yes/no URL parameter
    # For TextEditTool: overridden by show_chat_window_instead_of_replace per-action setting,
    #                   which is further overridden by popup radio button selection
    "show_ai_response_in_chat_window": False,
    # Session Auto-Save Setting:
    # controls when sessions are persisted to disk.
    # - "on_followup" (default): Save only when user sends a follow-up message in chat window.
    # - "always_window": Save whenever a new chat window is opened.
    # - "on_attachment": Save whenever a window is opened AND has attachments.
    "auto_save_session": "on_attachment",
    # Streaming and thinking settings
    "streaming_enabled": True,
    "thinking_enabled": False,
    "thinking_output": "reasoning_content",  # filter, raw, or reasoning_content
    # Thinking configuration
    # - reasoning_effort: For OpenAI-compatible APIs ("low", "medium", "high")
    # - thinking_budget: For Gemini 2.5 models (integer tokens, -1 = auto/unlimited)
    # - thinking_level: For Gemini 3.x models ("low", "high")
    "reasoning_effort": "high",
    "thinking_budget": -1,
    "thinking_level": "high",
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
    "screen_snip_hotkey": "ctrl+shift+x",
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
    "audio_tool_hotkey": "ctrl+shift+a",
    "audio_default_device": "default",
    "audio_default_loopback": True,
    # Level meter display style
    # - canvas: Custom canvas with grid lines and color gradient (default)
    # - progressbar: Smooth, simple progress bar
    "audio_level_meter_style": "canvas",
    # TTS (Text-to-Speech) settings
    "tts_enabled": True,
    "tts_default_voice": "Kore",
    "tts_default_model": "gemini-2.5-flash-preview-tts",
    "tts_director_enabled": True,
    "tts_director_auto_mode": False,
    # Model override for AI Director (empty = use default provider model)
    "tts_director_model": "",
    # Directory for saved TTS audio files
    "tts_save_directory": "tts_output",
    # Chat window system prompt behavior
    # true = Use the originating action's system prompt for follow-up messages
    # false = Always use chat_window_system_instruction from prompts.json
    "chat_use_origin_system_prompt": True,
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
    """Load configuration from .ini file"""
    config = dict(DEFAULT_CONFIG)
    ai_params = {}
    endpoints = _get_default_endpoints()
    keys = {"custom": [], "openrouter": [], "google": []}
    
    if not Path(filepath).exists():
        print(f"[Warning] Config file '{filepath}' not found. Using defaults.")
        return config, ai_params, endpoints, keys
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        current_section = None
        multiline_key = None
        multiline_value = []
        seen_config_keys = set()
        
        for line in lines:
            raw_line = line.rstrip('\n\r')
            stripped = raw_line.strip()
            
            if not stripped or stripped.startswith('#'):
                continue
            
            if stripped.startswith('[') and stripped.endswith(']'):
                # Legacy endpoint section handling removed
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
                        print(f"[Warning] Unknown key '{key}' in [config] section (ignored). "
                              f"AI parameters belong in [ai_params].")
            
            elif current_section == 'ai_params':
                if '=' in stripped:
                    key, value = stripped.split('=', 1)
                    key = key.strip().lower()
                    value = parse_config_value(value)
                    if value is not None:
                        ai_params[key] = value
            
            # Legacy [endpoints] section parsing removed - prompts now in prompts.json
            
            elif current_section in keys:
                if stripped and not stripped.startswith('#'):
                    # Strip inline comments (format: key   # name or key # name)
                    # Use regex to handle variable whitespace before #
                    # The comment is for display purposes only; we only store the key
                    match = re.search(r'\s+#', stripped)
                    if match:
                        key_part = stripped[:match.start()].strip()
                    else:
                        key_part = stripped.strip()
                    if key_part:
                        keys[current_section].append(key_part)
        
        # Legacy multiline handling removed
        
        # Load from environment variables if not in config
        if not keys["google"] and os.getenv("GEMINI_API_KEY"):
            keys["google"].append(os.getenv("GEMINI_API_KEY"))
        if not keys["openrouter"] and os.getenv("OPENROUTER_API_KEY"):
            keys["openrouter"].append(os.getenv("OPENROUTER_API_KEY"))
        if not keys["custom"] and os.getenv("CUSTOM_API_KEY"):
            keys["custom"].append(os.getenv("CUSTOM_API_KEY"))
        
    except Exception as e:
        print(f"[Error] Failed to load config: {e}")
    
    return config, ai_params, endpoints, keys


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

# Default API provider: custom, openrouter, or google
default_provider = google

# ============================================================
# RESPONSE DISPLAY SETTINGS
# ============================================================
# Show AI response in a chat window (yes) or type directly (no)
#
# Override hierarchy (highest to lowest priority):
#   1. ?show=yes/no URL parameter (API endpoints only)
#   2. Popup radio button selection (TextEditTool, if not "Default")
#   3. show_chat_window_instead_of_replace per-action setting (TextEditTool)
#   4. This global setting (show_ai_response_in_chat_window)
show_ai_response_in_chat_window = false

# Session Auto-Save Setting:
# controls when sessions are persisted to disk.
# - "on_followup" (default): Save only when user sends a follow-up message in chat window.
# - "always_window": Save whenever a new chat window is opened.
# - "on_attachment": Save whenever a window is opened AND has attachments.
auto_save_session = on_attachment

# Custom API configuration
custom_url = https://api.openai.com/v1/chat/completions
custom_model = gpt-5.2
#
# NOTE: If custom_url contains "google" or "googleapis.com", the system will
# automatically apply Google-specific settings (safety_settings, thinking_config).
# Example for Google's OpenAI-compatible endpoint:
# custom_url = https://generativelanguage.googleapis.com/v1beta/openai
# custom_model = gemini-2.5-flash

# OpenRouter model (see https://openrouter.ai/models for options)
openrouter_model = openai/gpt-oss-120b:free

# Google Gemini model
google_model = gemma-3-27b-it

# Custom Gemini Endpoint (optional)
# Override the default Google AI Studio endpoint
# gemini_endpoint = https://generativelanguage.googleapis.com/v1beta

# Retry settings
max_retries = 3
retry_delay = 5
request_timeout = 120

# Session management
max_sessions = 200

# ============================================================
# STREAMING AND THINKING SETTINGS
# ============================================================
# Enable streaming responses (default: true)
streaming_enabled = true

# Enable extended thinking/reasoning mode (default: false)
thinking_enabled = false

# How to handle thinking output: filter, raw, or reasoning_content
# - filter: Hide thinking content
# - raw: Include thinking in main response
# - reasoning_content: Separate field (for collapsible display)
thinking_output = reasoning_content

# Thinking configuration (for different providers)
# - reasoning_effort: OpenAI-compatible APIs (low, medium, high)
# - thinking_budget: Gemini 2.5 models (integer tokens, -1 = auto/unlimited)
# - thinking_level: Gemini 3.x models (low, high)
reasoning_effort = high
thinking_budget = -1
thinking_level = high

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

# Hotkey combination (e.g., ctrl+shift+x)
screen_snip_hotkey = ctrl+shift+x

# ============================================================
# AUDIO TOOL - Audio recording and analysis with AI
# ============================================================
# Enable/disable Audio Tool feature
audio_tool_enabled = true

# Hotkey combination (e.g., ctrl+shift+a)
audio_tool_hotkey = ctrl+shift+a

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
# TTS (TEXT-TO-SPEECH) - Gemini-powered speech synthesis
# ============================================================
# Enable/disable TTS feature
tts_enabled = true

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
# tts_director_model =

# Directory for saved TTS audio files (relative to app root)
tts_save_directory = tts_output

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

# ============================================================
# AI PARAMETERS (Optional)
# ============================================================
# These parameters are passed directly to the AI model.
# Only set values you want to override; unset = model defaults.
# Unknown keys in [config] are ignored to prevent stale values
# from being sent to the model.

[ai_params]
# temperature = 1
# max_tokens = 16384
# top_p = 0.95

# ============================================================
# API KEYS - Add your keys below (one per line)
# You can add multiple keys for automatic rotation on rate limits
# ============================================================

[custom]
# Your custom/OpenAI API keys here (one per line)
# sk-xxxxxxxxxxxxxxxxxxxxx
# sk-yyyyyyyyyyyyyyyyyyyyy

[openrouter]
# Your OpenRouter API keys here (one per line)
# sk-or-v1-xxxxxxxxxxxxxxxxxxxxx

[google]
# Your Google Gemini API keys here (one per line)
# Get keys at: https://aistudio.google.com/app/apikey
# AIzaSyXXXXXXXXXXXXXXXXXXXXXXX
'''
