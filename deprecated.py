#!/usr/bin/env python3
"""
Universal ShareX Middleman Server with GUI Support (Dear PyGui)
Supports OpenRouter, Google Gemini, and custom OpenAI-compatible APIs
with smart key rotation, auto-retry, configurable endpoints, and GUI display.
"""

import base64
import json
import os
import queue
import re
import sys
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, abort, jsonify, request

# GUI support with Dear PyGui
try:
    import dearpygui.dearpygui as dpg

    HAVE_GUI = True
except ImportError:
    print("[Warning] Dear PyGui not installed. GUI features disabled.")
    print("         Install with: pip install dearpygui")
    HAVE_GUI = False
    dpg = None

# Optional: Load .env file
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# ============================================================================
# CONFIGURATION DEFAULTS
# ============================================================================

CONFIG_FILE = "config.ini"
SESSIONS_FILE = "chat_sessions.json"

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 5000,
    "default_provider": "google",
    "custom_url": None,
    "custom_model": None,
    "openrouter_model": "google/gemini-2.5-flash-preview",
    "google_model": "gemini-2.0-flash",
    "max_retries": 3,
    "retry_delay": 5,
    "request_timeout": 120,
    "max_sessions": 50,
    "default_show": "no",
}

DEFAULT_ENDPOINTS = {
    "ocr": "Extract the text from this image. Preserve the original formatting, including line breaks, spacing, and layout, as accurately as possible. Return only the extracted text.",
    "translate": "Translate all text in this image to English. Preserve the original formatting as much as possible. Return only the translated text.",
    "summarize": "Summarize the content shown in this image concisely. Focus on the main points.",
    "describe": "Describe this image in detail, including all visible elements, text, and context.",
    "code": "Extract any code from this image. Preserve exact formatting, indentation, and syntax. Return only the code.",
}

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Global state
CONFIG = {}
AI_PARAMS = {}
ENDPOINTS = {}
KEY_MANAGERS = {}
CHAT_SESSIONS = OrderedDict()
SESSION_LOCK = threading.Lock()

# GUI state - Improved for on-demand creation
GUI_QUEUE = queue.Queue()
GUI_THREAD = None
GUI_LOCK = threading.Lock()
GUI_RUNNING = False
GUI_CONTEXT_CREATED = False
GUI_SHUTDOWN_REQUESTED = False
OPEN_WINDOWS = set()
OPEN_WINDOWS_LOCK = threading.Lock()
WINDOW_COUNTER = 0
WINDOW_COUNTER_LOCK = threading.Lock()

# Default font reference
DEFAULT_FONT = None
FONTS = {
    "regular": None,
    "bold": None,
    "italic": None,
    "bold_italic": None,
    "header1": None,
    "header2": None,
    "code": None,
}


# ============================================================================
# SESSION MANAGEMENT
# ============================================================================


class ChatSession:
    """Represents a chat session with history"""

    def __init__(self, session_id=None, endpoint=None, provider=None, model=None, image_base64=None, mime_type=None):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.endpoint = endpoint or "chat"
        self.provider = provider or CONFIG.get("default_provider", "google")
        self.model = model  # Optional model override
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.image_base64 = image_base64
        self.mime_type = mime_type or "image/png"
        self.messages = []
        self.title = None

    def add_message(self, role, content):
        self.messages.append({"role": role, "content": content, "timestamp": datetime.now().isoformat()})
        self.updated_at = datetime.now().isoformat()
        if not self.title and role == "user":
            self.title = content[:50] + ("..." if len(content) > 50 else "")

    def get_conversation_for_api(self, include_image=True):
        messages = []
        for i, msg in enumerate(self.messages):
            if msg["role"] == "user":
                content = []
                if i == 0 and include_image and self.image_base64:
                    data_url = f"data:{self.mime_type};base64,{self.image_base64}"
                    content.append({"type": "image_url", "image_url": {"url": data_url}})
                content.append({"type": "text", "text": msg["content"]})
                messages.append({"role": "user", "content": content})
            else:
                messages.append({"role": "assistant", "content": msg["content"]})
        return messages

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "endpoint": self.endpoint,
            "provider": self.provider,
            "model": self.model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "title": self.title,
            "messages": self.messages,
            "has_image": bool(self.image_base64),
            "mime_type": self.mime_type,
        }

    @classmethod
    def from_dict(cls, data):
        session = cls()
        session.session_id = data.get("session_id", str(uuid.uuid4())[:8])
        session.endpoint = data.get("endpoint", "chat")
        session.provider = data.get("provider", "google")
        session.model = data.get("model")
        session.created_at = data.get("created_at", datetime.now().isoformat())
        session.updated_at = data.get("updated_at", session.created_at)
        session.title = data.get("title")
        session.messages = data.get("messages", [])
        session.mime_type = data.get("mime_type", "image/png")
        session.image_base64 = None
        return session


def save_sessions():
    with SESSION_LOCK:
        try:
            data = {sid: session.to_dict() for sid, session in CHAT_SESSIONS.items()}
            with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Warning] Failed to save sessions: {e}")


def load_sessions():
    global CHAT_SESSIONS
    try:
        if Path(SESSIONS_FILE).exists():
            with open(SESSIONS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            with SESSION_LOCK:
                for sid, session_data in data.items():
                    CHAT_SESSIONS[sid] = ChatSession.from_dict(session_data)
            print(f"  ✓ Loaded {len(CHAT_SESSIONS)} saved session(s)")
    except Exception as e:
        print(f"[Warning] Failed to load sessions: {e}")


def add_session(session):
    with SESSION_LOCK:
        max_sessions = CONFIG.get("max_sessions", 50)
        while len(CHAT_SESSIONS) >= max_sessions:
            oldest_id = next(iter(CHAT_SESSIONS))
            del CHAT_SESSIONS[oldest_id]
        CHAT_SESSIONS[session.session_id] = session
    threading.Thread(target=save_sessions, daemon=True).start()


def get_session(session_id):
    with SESSION_LOCK:
        return CHAT_SESSIONS.get(session_id)


def list_sessions():
    with SESSION_LOCK:
        sessions = []
        for sid, session in reversed(list(CHAT_SESSIONS.items())):
            sessions.append(
                {
                    "id": sid,
                    "title": session.title or "(No title)",
                    "endpoint": session.endpoint,
                    "provider": session.provider,
                    "messages": len(session.messages),
                    "updated": session.updated_at,
                    "created": session.created_at,
                }
            )
        return sessions


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def parse_config_value(value_str):
    value_str = value_str.strip()
    if value_str.lower() in ["none", "null", ""]:
        return None
    if value_str.lower() in ["true", "yes", "on", "1"]:
        return True
    if value_str.lower() in ["false", "no", "off", "0"]:
        return False
    try:
        if "." not in value_str:
            return int(value_str)
        return float(value_str)
    except ValueError:
        pass
    if (value_str.startswith('"') and value_str.endswith('"')) or (
        value_str.startswith("'") and value_str.endswith("'")
    ):
        return value_str[1:-1]
    return value_str


def load_config(filepath=CONFIG_FILE):
    config = dict(DEFAULT_CONFIG)
    ai_params = {}
    endpoints = dict(DEFAULT_ENDPOINTS)
    keys = {"custom": [], "openrouter": [], "google": []}

    if not Path(filepath).exists():
        print(f"[Warning] Config file '{filepath}' not found. Using defaults.")
        return config, ai_params, endpoints, keys

    try:
        with open(filepath, encoding="utf-8") as f:
            lines = f.readlines()

        current_section = None
        multiline_key = None
        multiline_value = []

        for line in lines:
            raw_line = line.rstrip("\n\r")
            stripped = raw_line.strip()

            if not stripped or stripped.startswith("#"):
                continue

            if stripped.startswith("[") and stripped.endswith("]"):
                if multiline_key and current_section == "endpoints":
                    endpoints[multiline_key] = " ".join(multiline_value)
                    multiline_key = None
                    multiline_value = []
                current_section = stripped[1:-1].lower()
                continue

            if current_section == "config":
                if "=" in stripped:
                    key, value = stripped.split("=", 1)
                    key = key.strip().lower()
                    value = parse_config_value(value)
                    if key in DEFAULT_CONFIG:
                        config[key] = value
                    elif value is not None:
                        ai_params[key] = value

            elif current_section == "endpoints":
                if "=" in stripped:
                    if multiline_key:
                        endpoints[multiline_key] = " ".join(multiline_value)
                    endpoint_name, prompt = stripped.split("=", 1)
                    endpoint_name = endpoint_name.strip().lower()
                    prompt = prompt.strip()
                    if (prompt.startswith('"') and prompt.endswith('"')) or (
                        prompt.startswith("'") and prompt.endswith("'")
                    ):
                        prompt = prompt[1:-1]
                    if prompt.endswith("\\"):
                        multiline_key = endpoint_name
                        multiline_value = [prompt[:-1].strip()]
                    else:
                        endpoints[endpoint_name] = prompt
                        multiline_key = None
                        multiline_value = []
                elif multiline_key:
                    if stripped.endswith("\\"):
                        multiline_value.append(stripped[:-1].strip())
                    else:
                        multiline_value.append(stripped)
                        endpoints[multiline_key] = " ".join(multiline_value)
                        multiline_key = None
                        multiline_value = []

            elif current_section in keys:
                if stripped and not stripped.startswith("#"):
                    keys[current_section].append(stripped)

        if multiline_key and current_section == "endpoints":
            endpoints[multiline_key] = " ".join(multiline_value)

        if not keys["google"] and os.getenv("GEMINI_API_KEY"):
            keys["google"].append(os.getenv("GEMINI_API_KEY"))
        if not keys["openrouter"] and os.getenv("OPENROUTER_API_KEY"):
            keys["openrouter"].append(os.getenv("OPENROUTER_API_KEY"))
        if not keys["custom"] and os.getenv("CUSTOM_API_KEY"):
            keys["custom"].append(os.getenv("CUSTOM_API_KEY"))

    except Exception as e:
        print(f"[Error] Failed to load config: {e}")

    return config, ai_params, endpoints, keys


def get_next_window_id():
    global WINDOW_COUNTER
    with WINDOW_COUNTER_LOCK:
        WINDOW_COUNTER += 1
        return WINDOW_COUNTER


# ============================================================================
# KEY MANAGER
# ============================================================================


class KeyManager:
    def __init__(self, keys, provider_name):
        self.keys = [k for k in keys if k]
        self.current_index = 0
        self.exhausted_keys = set()
        self.provider_name = provider_name
        self.lock = threading.Lock()

    def get_current_key(self):
        with self.lock:
            if not self.keys:
                return None
            if self.current_index >= len(self.keys):
                self.current_index = 0
            return self.keys[self.current_index]

    def rotate_key(self, reason=""):
        with self.lock:
            if not self.keys:
                return None
            self.exhausted_keys.add(self.current_index)
            for i in range(len(self.keys)):
                next_index = (self.current_index + 1 + i) % len(self.keys)
                if next_index not in self.exhausted_keys:
                    self.current_index = next_index
                    print(f"    → Switched to {self.provider_name} key #{self.current_index + 1} {reason}")
                    return self.keys[self.current_index]
            print(f"    → All {self.provider_name} keys exhausted, resetting...")
            self.exhausted_keys.clear()
            self.current_index = 0
            return self.keys[0] if self.keys else None

    def get_key_count(self):
        return len(self.keys)

    def get_key_number(self):
        return self.current_index + 1

    def has_keys(self):
        return len(self.keys) > 0

    def has_more_keys(self):
        return len(self.exhausted_keys) < len(self.keys)

    def reset_exhausted(self):
        with self.lock:
            self.exhausted_keys.clear()


# ============================================================================
# ERROR DETECTION
# ============================================================================


def is_rate_limit_error(error_msg, status_code=None):
    if status_code == 429:
        return True
    error_str = str(error_msg).lower()
    patterns = [
        "too many requests",
        "rate limit",
        "rate_limit",
        "quota exceeded",
        "429",
        "throttl",
        "resource exhausted",
        "resource_exhausted",
    ]
    return any(p in error_str for p in patterns)


def is_insufficient_credits_error(error_msg, response_json=None):
    error_str = str(error_msg).lower()
    patterns = [
        "insufficient credits",
        "insufficient funds",
        "not enough credits",
        "credit balance",
        "out of credits",
        "no credits",
        "payment required",
        "billing",
        "exceeded your current quota",
    ]
    if any(p in error_str for p in patterns):
        return True
    if response_json and isinstance(response_json, dict):
        try:
            msg = str(response_json.get("error", {}).get("message", "")).lower()
            if any(p in msg for p in patterns):
                return True
        except:
            pass
    return False


def is_invalid_key_error(error_msg, status_code=None):
    if status_code in [401, 403]:
        return True
    error_str = str(error_msg).lower()
    patterns = [
        "invalid api key",
        "invalid key",
        "api key invalid",
        "unauthorized",
        "authentication",
        "forbidden",
        "not authorized",
    ]
    return any(p in error_str for p in patterns)


# ============================================================================
# API CALLERS
# ============================================================================


def call_openrouter_api(key_manager, model, messages, ai_params, timeout):
    current_key = key_manager.get_current_key()
    if not current_key:
        return None, "No API key available"
    headers = {
        "Authorization": f"Bearer {current_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
    }
    payload = {"model": model, "messages": messages}
    for param, value in ai_params.items():
        if value is not None:
            payload[param] = value
    response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)
    return response, None


def call_google_api(key_manager, model, messages, ai_params, timeout):
    current_key = key_manager.get_current_key()
    if not current_key:
        return None, "No API key available"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": current_key, "Content-Type": "application/json"}

    contents = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        parts = []
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append({"text": content})
        elif isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    parts.append({"text": item.get("text", "")})
                elif item.get("type") == "image_url":
                    url_data = item.get("image_url", {}).get("url", "")
                    if url_data.startswith("data:"):
                        match = re.match(r"data:([^;]+);base64,(.+)", url_data)
                        if match:
                            mime_type, b64_data = match.groups()
                            parts.append({"inline_data": {"mime_type": mime_type, "data": b64_data}})
        contents.append({"role": role, "parts": parts})

    payload = {"contents": contents, "generationConfig": {}}
    for param, value in ai_params.items():
        if value is not None:
            payload["generationConfig"][param] = value
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    return response, None


def call_custom_api(key_manager, url, model, messages, ai_params, timeout):
    current_key = key_manager.get_current_key()
    if not current_key:
        return None, "No API key available"
    headers = {"Authorization": f"Bearer {current_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages}
    for param, value in ai_params.items():
        if value is not None:
            payload[param] = value
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    return response, None


def extract_text_from_response(response_json, provider):
    try:
        if provider in ["openrouter", "custom"]:
            choices = response_json.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                content = message.get("content", "")
                if content:
                    return content
        elif provider == "google":
            candidates = response_json.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    return parts[0].get("text", "")
        return None
    except Exception as e:
        print(f"    [Error] Failed to extract text: {e}")
        return None


# ============================================================================
# MAIN API CALLER WITH RETRY LOGIC
# ============================================================================


def call_api_with_retry(provider, messages, model_override=None):
    global CONFIG, AI_PARAMS, KEY_MANAGERS

    max_retries = CONFIG.get("max_retries", 3)
    retry_delay = CONFIG.get("retry_delay", 5)
    timeout = CONFIG.get("request_timeout", 120)

    key_manager = KEY_MANAGERS.get(provider)
    if not key_manager or not key_manager.has_keys():
        return None, f"No API keys configured for provider: {provider}"

    max_attempts = max_retries * max(1, key_manager.get_key_count())

    # Determine the model to use
    if model_override:
        model = model_override
    elif provider == "openrouter":
        model = CONFIG.get("openrouter_model", "google/gemini-2.5-flash-preview")
    elif provider == "google":
        model = CONFIG.get("google_model", "gemini-2.0-flash")
    elif provider == "custom":
        model = CONFIG.get("custom_model")
    else:
        model = None

    for attempt in range(max_attempts):
        try:
            key_num = key_manager.get_key_number()
            print(f"    Calling {provider} API (key #{key_num}, attempt {attempt + 1}/{max_attempts})")
            print(f"    Model: {model}")

            response = None
            error = None

            if provider == "openrouter":
                response, error = call_openrouter_api(key_manager, model, messages, AI_PARAMS, timeout)
            elif provider == "google":
                response, error = call_google_api(key_manager, model, messages, AI_PARAMS, timeout)
            elif provider == "custom":
                url = CONFIG.get("custom_url")
                if not url or not model:
                    return None, "Custom API URL or model not configured"
                response, error = call_custom_api(key_manager, url, model, messages, AI_PARAMS, timeout)
            else:
                return None, f"Unknown provider: {provider}"

            if error:
                print(f"    [Error] {error}")
                continue

            if response is None:
                continue

            resp_json = None
            try:
                resp_json = response.json()
            except:
                pass

            if is_invalid_key_error(response.text, response.status_code):
                print(f"    [Error] Invalid API key #{key_num}")
                new_key = key_manager.rotate_key("(invalid key)")
                if not new_key or not key_manager.has_more_keys():
                    return None, "All API keys are invalid"
                continue

            if is_insufficient_credits_error(response.text, resp_json):
                print(f"    [Warning] Insufficient credits on key #{key_num}")
                new_key = key_manager.rotate_key("(insufficient credits)")
                if not new_key or not key_manager.has_more_keys():
                    return None, "All API keys have insufficient credits"
                continue

            if response.status_code != 200:
                if is_rate_limit_error(response.text, response.status_code):
                    print(f"    [Warning] Rate limited on key #{key_num}")
                    new_key = key_manager.rotate_key("(rate limited)")
                    if new_key and key_manager.has_more_keys():
                        time.sleep(min(retry_delay, 2))
                        continue
                    else:
                        print(f"    All keys rate limited, waiting {retry_delay * 2}s...")
                        time.sleep(retry_delay * 2)
                        key_manager.reset_exhausted()
                        continue
                print(f"    [Error] API error {response.status_code}: {response.text[:300]}")
                if attempt < max_attempts - 1:
                    time.sleep(retry_delay)
                continue

            text = extract_text_from_response(resp_json, provider)
            if text:
                return text, None
            else:
                print("    [Warning] No text in response, retrying...")
                if attempt < max_attempts - 1:
                    time.sleep(retry_delay)
                continue

        except requests.exceptions.Timeout:
            print(f"    [Error] Request timeout after {timeout}s")
            if attempt < max_attempts - 1:
                time.sleep(retry_delay)
        except requests.exceptions.RequestException as e:
            print(f"    [Error] Request failed: {e}")
            if is_rate_limit_error(str(e)):
                key_manager.rotate_key("(rate limit exception)")
            if attempt < max_attempts - 1:
                time.sleep(retry_delay)
        except Exception as e:
            print(f"    [Error] Unexpected: {e}")
            if attempt < max_attempts - 1:
                time.sleep(retry_delay)

    return None, f"All {max_attempts} attempts failed"


def call_api_simple(provider, prompt, image_base64, mime_type, model_override=None):
    data_url = f"data:{mime_type};base64,{image_base64}"
    messages = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": data_url}}, {"type": "text", "text": prompt}],
        }
    ]
    return call_api_with_retry(provider, messages, model_override)


def call_api_chat(session):
    messages = session.get_conversation_for_api(include_image=True)
    return call_api_with_retry(session.provider, messages, session.model)


# ============================================================================
# MARKDOWN UTILITIES
# ============================================================================


def strip_markdown(text):
    """Convert markdown to plain text by stripping formatting"""
    if not text:
        return text

    result = text

    # Remove code blocks (``` ... ```)
    result = re.sub(r"```[\s\S]*?```", lambda m: m.group(0).replace("```", "").strip(), result)

    # Remove inline code (`code`)
    result = re.sub(r"`([^`]+)`", r"\1", result)

    # Remove bold (**text** or __text__)
    result = re.sub(r"\*\*([^*]+)\*\*", r"\1", result)
    result = re.sub(r"__([^_]+)__", r"\1", result)

    # Remove italic (*text* or _text_)
    result = re.sub(r"\*([^*]+)\*", r"\1", result)
    result = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", result)

    # Remove strikethrough (~~text~~)
    result = re.sub(r"~~([^~]+)~~", r"\1", result)

    # Remove headers (# Header)
    result = re.sub(r"^#{1,6}\s+", "", result, flags=re.MULTILINE)

    # Remove blockquotes (> text)
    result = re.sub(r"^>\s+", "", result, flags=re.MULTILINE)

    # Remove horizontal rules
    result = re.sub(r"^[-*_]{3,}\s*$", "", result, flags=re.MULTILINE)

    # Remove link formatting [text](url) -> text
    result = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", result)

    # Remove image formatting ![alt](url) -> alt
    result = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", result)

    # Remove list markers
    result = re.sub(r"^[\s]*[-*+]\s+", "• ", result, flags=re.MULTILINE)
    result = re.sub(r"^[\s]*\d+\.\s+", "", result, flags=re.MULTILINE)

    return result


def render_markdown(text, parent, wrap_width=-1):
    """Render markdown text to DPG items"""
    lines = text.split("\n")
    in_code_block = False
    code_block_lines = []
    code_lang = ""

    # Helper to flush code block
    def flush_code_block():
        nonlocal code_block_lines, code_lang
        if code_block_lines:
            code_text = "\n".join(code_block_lines)
            # Estimate height: lines * 18 pixels + padding
            height = max(60, len(code_block_lines) * 18 + 20)
            dpg.add_input_text(
                default_value=code_text, multiline=True, readonly=True, width=-1, height=height, parent=parent
            )
            code_block_lines = []
            code_lang = ""

    for line in lines:
        stripped_line = line.strip()

        # Code Block Detection
        if stripped_line.startswith("```"):
            if in_code_block:
                # End of code block
                flush_code_block()
                in_code_block = False
            else:
                # Start of code block
                in_code_block = True
                code_lang = stripped_line[3:].strip()
            continue

        if in_code_block:
            code_block_lines.append(line)
            continue

        # Headers
        if stripped_line.startswith("#"):
            level = len(stripped_line.split(" ")[0])
            content = stripped_line.lstrip("#").strip()
            if level == 1:
                item = dpg.add_text(content, parent=parent, wrap=wrap_width, color=(255, 200, 100))
                if FONTS.get("header1"):
                    dpg.bind_item_font(item, FONTS.get("header1"))
            elif level == 2:
                item = dpg.add_text(content, parent=parent, wrap=wrap_width, color=(200, 200, 255))
                if FONTS.get("header2"):
                    dpg.bind_item_font(item, FONTS.get("header2"))
            else:
                item = dpg.add_text(content, parent=parent, wrap=wrap_width, color=(180, 220, 255))
                if FONTS.get("bold"):
                    dpg.bind_item_font(item, FONTS.get("bold"))
            continue

        # Bullet Points
        if stripped_line.startswith("- ") or stripped_line.startswith("* "):
            content = stripped_line[2:].strip()
            # Clean up bold markers for cleaner bullet display
            content = content.replace("**", "").replace("__", "")
            dpg.add_text(content, parent=parent, wrap=wrap_width, bullet=True)
            continue

        # Bold Line (whole line)
        if stripped_line.startswith("**") and stripped_line.endswith("**") and len(stripped_line) > 4:
            content = stripped_line[2:-2]
            item = dpg.add_text(content, parent=parent, wrap=wrap_width)
            if FONTS.get("bold"):
                dpg.bind_item_font(item, FONTS.get("bold"))
            continue

        # Italic Line (whole line)
        if (stripped_line.startswith("*") and stripped_line.endswith("*") and len(stripped_line) > 2) or (
            stripped_line.startswith("_") and stripped_line.endswith("_") and len(stripped_line) > 2
        ):
            content = stripped_line[1:-1]
            item = dpg.add_text(content, parent=parent, wrap=wrap_width)
            if FONTS.get("italic"):
                dpg.bind_item_font(item, FONTS.get("italic"))
            continue

        # Regular Text (with simple inline stripping for display)
        # Note: We don't support true inline bold/italic yet, so we strip markers for cleaner look
        # but keep the text.

        # Check if empty line (spacer)
        if not stripped_line:
            dpg.add_spacer(height=5, parent=parent)
            continue

        dpg.add_text(line, parent=parent, wrap=wrap_width)

    # Flush any remaining code block
    if in_code_block:
        flush_code_block()


# ============================================================================
# DEAR PYGUI GUI FUNCTIONS - ON-DEMAND CREATION
# ============================================================================


def copy_to_clipboard(text):
    """Cross-platform clipboard copy"""
    try:
        if sys.platform == "win32":
            import subprocess

            process = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            process.communicate(text.encode("utf-16le"))
        elif sys.platform == "darwin":
            import subprocess

            process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            process.communicate(text.encode("utf-8"))
        else:
            try:
                import subprocess

                process = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
                process.communicate(text.encode("utf-8"))
            except:
                process = subprocess.Popen(["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE)
                process.communicate(text.encode("utf-8"))
        return True
    except Exception as e:
        print(f"[Clipboard Error] {e}")
        return False


def register_window(window_tag):
    """Register a window as open"""
    with OPEN_WINDOWS_LOCK:
        OPEN_WINDOWS.add(window_tag)


def unregister_window(window_tag):
    """Unregister a window when closed"""
    with OPEN_WINDOWS_LOCK:
        OPEN_WINDOWS.discard(window_tag)


def has_open_windows():
    """Check if any windows are open"""
    with OPEN_WINDOWS_LOCK:
        return len(OPEN_WINDOWS) > 0


def init_dearpygui():
    """Initialize Dear PyGui context and viewport"""
    global GUI_CONTEXT_CREATED, DEFAULT_FONT, FONTS

    if GUI_CONTEXT_CREATED:
        return True

    try:
        dpg.create_context()
        dpg.create_viewport(title="ShareX Middleman", width=900, height=700, decorated=True)

        # Create a font registry with a larger default font and styles
        with dpg.font_registry():
            # Try to load Consolas family (Windows)
            base_path = Path("C:/Windows/Fonts")
            if (base_path / "consola.ttf").exists():
                try:
                    FONTS["regular"] = dpg.add_font(str(base_path / "consola.ttf"), 16)
                    FONTS["bold"] = dpg.add_font(str(base_path / "consolab.ttf"), 16)
                    FONTS["italic"] = dpg.add_font(str(base_path / "consolai.ttf"), 16)
                    FONTS["bold_italic"] = dpg.add_font(str(base_path / "consolaz.ttf"), 16)
                    FONTS["header1"] = dpg.add_font(str(base_path / "consolab.ttf"), 26)
                    FONTS["header2"] = dpg.add_font(str(base_path / "consolab.ttf"), 20)
                    FONTS["code"] = dpg.add_font(str(base_path / "consola.ttf"), 14)
                    DEFAULT_FONT = FONTS["regular"]
                except Exception as e:
                    print(f"[GUI Warning] Failed to load Consolas fonts: {e}")

            # Fallback if Consolas failed or not on Windows
            if not DEFAULT_FONT:
                font_paths = [
                    "C:/Windows/Fonts/segoeui.ttf",  # Windows Segoe UI
                    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",  # Linux
                    "/System/Library/Fonts/SFNSMono.ttf",  # macOS
                    "/System/Library/Fonts/Menlo.ttc",  # macOS fallback
                ]

                for font_path in font_paths:
                    if Path(font_path).exists():
                        try:
                            DEFAULT_FONT = dpg.add_font(font_path, 16)
                            FONTS["regular"] = DEFAULT_FONT
                            # Create larger variants for headers if possible (re-adding same font with different size)
                            FONTS["header1"] = dpg.add_font(font_path, 26)
                            FONTS["header2"] = dpg.add_font(font_path, 20)
                            break
                        except:
                            continue

            if DEFAULT_FONT:
                dpg.bind_font(DEFAULT_FONT)

        # Set theme
        with dpg.theme() as global_theme, dpg.theme_component(dpg.mvAll):
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 6)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 6)
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (30, 30, 40))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (45, 45, 60))
            dpg.add_theme_color(dpg.mvThemeCol_Button, (70, 100, 150))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (90, 120, 170))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (60, 90, 140))

        dpg.bind_theme(global_theme)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        GUI_CONTEXT_CREATED = True
        return True
    except Exception as e:
        print(f"[GUI Error] Failed to initialize Dear PyGui: {e}")
        return False


def shutdown_dearpygui():
    """Shutdown Dear PyGui context"""
    global GUI_CONTEXT_CREATED, GUI_RUNNING, DEFAULT_FONT

    try:
        if GUI_CONTEXT_CREATED:
            dpg.destroy_context()
            GUI_CONTEXT_CREATED = False
            DEFAULT_FONT = None
            with OPEN_WINDOWS_LOCK:
                OPEN_WINDOWS.clear()
    except Exception as e:
        print(f"[GUI Error] Failed to shutdown Dear PyGui: {e}")

    GUI_RUNNING = False


def gui_main_loop():
    """Main GUI loop running in separate thread - runs only when windows are open"""
    global GUI_RUNNING, GUI_SHUTDOWN_REQUESTED

    if not init_dearpygui():
        print("[GUI Error] Failed to start GUI")
        GUI_RUNNING = False
        return

    GUI_RUNNING = True
    GUI_SHUTDOWN_REQUESTED = False
    last_window_check = time.time()

    print("[GUI] Started")

    while dpg.is_dearpygui_running() and not GUI_SHUTDOWN_REQUESTED:
        # Process any queued GUI requests
        try:
            while not GUI_QUEUE.empty():
                task = GUI_QUEUE.get_nowait()
                task_type = task.get("type")

                if task_type == "result":
                    create_result_window(task["text"], task.get("endpoint"), task.get("title"))
                elif task_type == "chat":
                    create_chat_window(task["session"], task.get("initial_response"))
                elif task_type == "browser":
                    create_session_browser_window()

                GUI_QUEUE.task_done()
        except:
            pass

        dpg.render_dearpygui_frame()

        # Check if all windows are closed (every 0.5 seconds)
        current_time = time.time()
        if current_time - last_window_check > 0.5:
            last_window_check = current_time
            if not has_open_windows():
                print("[GUI] All windows closed, stopping...")
                break

    shutdown_dearpygui()
    print("[GUI] Stopped")


def ensure_gui_running():
    """Ensure GUI thread is running, start if needed"""
    global GUI_THREAD, GUI_RUNNING, GUI_SHUTDOWN_REQUESTED

    if not HAVE_GUI:
        return False

    with GUI_LOCK:
        if GUI_RUNNING and GUI_THREAD and GUI_THREAD.is_alive():
            return True

        # Start new GUI thread
        GUI_SHUTDOWN_REQUESTED = False
        GUI_THREAD = threading.Thread(target=gui_main_loop, daemon=True)
        GUI_THREAD.start()

        # Wait for GUI to initialize
        for _ in range(50):  # Wait up to 5 seconds
            if GUI_RUNNING and GUI_CONTEXT_CREATED:
                return True
            time.sleep(0.1)

        return GUI_RUNNING


def create_result_window(text, endpoint=None, title=None):
    """Create a result display window"""
    window_id = get_next_window_id()
    window_tag = f"result_window_{window_id}"
    content_group_tag = f"result_content_{window_id}"
    status_tag = f"result_status_{window_id}"
    wrap_btn_tag = f"wrap_btn_{window_id}"
    mode_btn_tag = f"mode_btn_{window_id}"
    scroll_area_tag = f"scroll_area_{window_id}"

    title = title or f"Response - /{endpoint}" if endpoint else "AI Response"

    # State for toggles
    state = {
        "wrapped": True,
        "mode": "rich",  # 'rich' (markdown) or 'text' (selectable)
        "original_text": text,
    }

    def get_display_text():
        """Get text based on current display mode"""
        if state["mode"] == "rich":
            return state["original_text"]
        else:
            return strip_markdown(state["original_text"])

    def update_display():
        """Update the text display"""
        # Clear existing content
        dpg.delete_item(content_group_tag, children_only=True)

        # Update buttons
        dpg.configure_item(wrap_btn_tag, label=f"Wrap: {'ON' if state['wrapped'] else 'OFF'}")
        dpg.configure_item(mode_btn_tag, label=f"Mode: {'Rich' if state['mode'] == 'rich' else 'Text'}")

        # Configure parent scrollbar
        if state["wrapped"]:
            dpg.configure_item(scroll_area_tag, horizontal_scrollbar=False)
        else:
            dpg.configure_item(scroll_area_tag, horizontal_scrollbar=True)

        # Add content based on mode
        if state["mode"] == "text":
            # Use InputText for selection (monochrome)
            width = -1 if state["wrapped"] else 3000
            dpg.add_input_text(
                default_value=get_display_text(),
                parent=content_group_tag,
                multiline=True,
                readonly=True,
                width=width,
                height=-1,
            )
        else:
            # Use Text for rich display (colored potential, clean wrapping)
            wrap_width = 0 if state["wrapped"] else -1
            render_markdown(state["original_text"], parent=content_group_tag, wrap_width=wrap_width)

    def toggle_wrap():
        state["wrapped"] = not state["wrapped"]
        update_display()
        dpg.set_value(status_tag, f"Wrap: {'ON' if state['wrapped'] else 'OFF'}")

    def toggle_mode():
        state["mode"] = "text" if state["mode"] == "rich" else "rich"
        update_display()
        dpg.set_value(status_tag, f"Mode: {state['mode'].title()}")

    def copy_callback():
        if copy_to_clipboard(get_display_text()):
            dpg.set_value(status_tag, "✓ Copied to clipboard!")
        else:
            dpg.set_value(status_tag, "✗ Failed to copy")

    def close_callback():
        unregister_window(window_tag)
        dpg.delete_item(window_tag)

    register_window(window_tag)

    with dpg.window(
        label=title,
        tag=window_tag,
        width=700,
        height=500,
        pos=[100 + (window_id % 5) * 30, 100 + (window_id % 5) * 30],
        on_close=close_callback,
    ):
        if endpoint:
            dpg.add_text(f"Endpoint: /{endpoint}")
            dpg.add_separator()

        # Toggle buttons row
        with dpg.group(horizontal=True):
            dpg.add_text("Response:", color=(150, 200, 255))
            dpg.add_spacer(width=20)
            dpg.add_button(label="Wrap: ON", tag=wrap_btn_tag, callback=toggle_wrap, width=100)
            dpg.add_button(label="Mode: Rich", tag=mode_btn_tag, callback=toggle_mode, width=100)

        # Scrollable area for text
        with dpg.child_window(tag=scroll_area_tag, border=False, width=-1, height=-60, horizontal_scrollbar=False):
            dpg.add_group(tag=content_group_tag)

        # Initial display
        update_display()

        dpg.add_separator()

        with dpg.group(horizontal=True):
            dpg.add_button(label="Copy to Clipboard", callback=copy_callback)
            dpg.add_button(label="Close", callback=close_callback)
            dpg.add_text("", tag=status_tag, color=(100, 255, 100))


def create_chat_window(session, initial_response=None):
    """Create a chat window for interactive conversation"""
    window_id = get_next_window_id()
    window_tag = f"chat_window_{window_id}"
    chat_log_group = f"chat_log_{window_id}"
    input_tag = f"chat_input_{window_id}"
    status_tag = f"chat_status_{window_id}"
    send_btn_tag = f"send_btn_{window_id}"
    wrap_btn_tag = f"wrap_btn_{window_id}"
    md_btn_tag = f"md_btn_{window_id}"
    select_btn_tag = f"select_btn_{window_id}"
    scroll_area_tag = f"scroll_area_{window_id}"

    # State for toggles
    state = {"wrapped": True, "markdown": True, "selectable": False, "last_response": initial_response or ""}

    def get_conversation_text():
        """Build conversation text based on current display mode (for clipboard)"""
        parts = []
        for msg in session.messages:
            role = "You" if msg["role"] == "user" else "Assistant"
            content = msg["content"]
            if state["mode"] == "text":
                content = strip_markdown(content)
            parts.append(f"[{role}]\n{content}\n")
        return "\n".join(parts)

    def update_chat_display():
        # Clear existing messages
        dpg.delete_item(chat_log_group, children_only=True)

        # Update buttons
        dpg.configure_item(wrap_btn_tag, label=f"Wrap: {'ON' if state['wrapped'] else 'OFF'}")
        dpg.configure_item(md_btn_tag, label=f"{'Markdown' if state['markdown'] else 'Plain Text'}")
        dpg.configure_item(select_btn_tag, label=f"Select: {'ON' if state['selectable'] else 'OFF'}")

        # Handle wrapping
        wrap_width = 0 if state["wrapped"] else -1

        if state["wrapped"]:
            dpg.configure_item(scroll_area_tag, horizontal_scrollbar=False)
        else:
            dpg.configure_item(scroll_area_tag, horizontal_scrollbar=True)

        if state["selectable"]:
            # Selectable mode: One big text box (monochrome)
            width = -1 if state["wrapped"] else 3000
            dpg.add_input_text(
                default_value=get_conversation_text(),
                parent=chat_log_group,
                multiline=True,
                readonly=True,
                width=width,
                height=-1,
            )
        else:
            # Rich mode: Colored text blocks
            for i, msg in enumerate(session.messages):
                role = msg["role"]
                content = msg["content"]
                if not state["markdown"]:
                    content = strip_markdown(content)

                if role == "user":
                    dpg.add_text("You:", color=(100, 200, 255), parent=chat_log_group)
                else:
                    dpg.add_text("Assistant:", color=(150, 255, 150), parent=chat_log_group)

                if state["markdown"]:
                    render_markdown(content, parent=chat_log_group, wrap_width=wrap_width)
                else:
                    dpg.add_text(content, parent=chat_log_group, wrap=wrap_width, bullet=True)

                dpg.add_separator(parent=chat_log_group)

        # Scroll to bottom (simple hack: set scroll y to max)
        # Note: DPG scroll setting is sometimes tricky, usually requires next frame
        # dpg.set_y_scroll(scroll_area_tag, dpg.get_y_scroll_max(scroll_area_tag))

    def toggle_wrap():
        state["wrapped"] = not state["wrapped"]
        update_chat_display()
        dpg.set_value(status_tag, f"Wrap: {'ON' if state['wrapped'] else 'OFF'}")

    def toggle_markdown():
        state["markdown"] = not state["markdown"]
        update_chat_display()
        dpg.set_value(status_tag, f"Mode: {'Markdown' if state['markdown'] else 'Plain Text'}")

    def toggle_selectable():
        state["selectable"] = not state["selectable"]
        update_chat_display()
        dpg.set_value(status_tag, f"Selectable: {'ON' if state['selectable'] else 'OFF'}")

    def send_callback():
        user_input = dpg.get_value(input_tag).strip()
        if not user_input:
            dpg.set_value(status_tag, "Please enter a message")
            return

        # Disable input during processing
        dpg.configure_item(send_btn_tag, enabled=False)
        dpg.set_value(status_tag, "Sending...")

        def process_message():
            session.add_message("user", user_input)
            update_chat_display()
            dpg.set_value(input_tag, "")

            response_text, error = call_api_chat(session)

            if error:
                dpg.set_value(status_tag, f"Error: {error}")
                session.messages.pop()  # Remove failed user message
            else:
                session.add_message("assistant", response_text)
                state["last_response"] = response_text
                update_chat_display()
                dpg.set_value(status_tag, "✓ Response received")
                add_session(session)

            dpg.configure_item(send_btn_tag, enabled=True)

        threading.Thread(target=process_message, daemon=True).start()

    def copy_all_callback():
        all_text = get_conversation_text()
        if copy_to_clipboard(all_text):
            dpg.set_value(status_tag, "✓ Copied all!")
        else:
            dpg.set_value(status_tag, "✗ Failed to copy")

    def copy_last_callback():
        text = state["last_response"]
        if not state["markdown"]:
            text = strip_markdown(text)
        if copy_to_clipboard(text):
            dpg.set_value(status_tag, "✓ Copied last response!")
        else:
            dpg.set_value(status_tag, "✗ Failed to copy")

    def close_callback():
        unregister_window(window_tag)
        dpg.delete_item(window_tag)

    register_window(window_tag)

    title = f"Chat - {session.title or session.session_id}"

    with dpg.window(
        label=title,
        tag=window_tag,
        width=750,
        height=600,
        pos=[80 + (window_id % 5) * 30, 80 + (window_id % 5) * 30],
        on_close=close_callback,
    ):
        dpg.add_text(
            f"Session: {session.session_id} | Endpoint: /{session.endpoint} | Provider: {session.provider}",
            color=(150, 150, 200),
        )
        dpg.add_separator()

        # Toggle buttons row
        with dpg.group(horizontal=True):
            dpg.add_text("Conversation:", color=(150, 200, 255))
            dpg.add_spacer(width=20)
            dpg.add_button(label="Wrap: ON", tag=wrap_btn_tag, callback=toggle_wrap, width=100)
            dpg.add_button(label="Markdown", tag=md_btn_tag, callback=toggle_markdown, width=100)
            dpg.add_button(label="Select: OFF", tag=select_btn_tag, callback=toggle_selectable, width=100)

        # Scrollable area for chat log
        with dpg.child_window(tag=scroll_area_tag, border=False, width=-1, height=-150, horizontal_scrollbar=False):
            dpg.add_group(tag=chat_log_group)

        # Initial display
        update_chat_display()

        dpg.add_separator()
        dpg.add_text("Your message:", color=(150, 200, 255))
        dpg.add_input_text(
            tag=input_tag, multiline=True, width=-1, height=60, hint="Type your follow-up message here..."
        )

        with dpg.group(horizontal=True):
            dpg.add_button(label="Send", tag=send_btn_tag, callback=send_callback)
            dpg.add_button(label="Copy All", callback=copy_all_callback)
            dpg.add_button(label="Copy Last", callback=copy_last_callback)
            dpg.add_button(label="Close", callback=close_callback)

        dpg.add_text("", tag=status_tag, color=(100, 255, 100))


def create_session_browser_window():
    """Create a session browser window"""
    window_id = get_next_window_id()
    window_tag = f"browser_window_{window_id}"
    table_tag = f"session_table_{window_id}"
    status_tag = f"browser_status_{window_id}"

    sessions = list_sessions()
    selected_session = {"id": None}

    def refresh_table():
        nonlocal sessions
        sessions = list_sessions()

        # Clear existing rows
        for child in dpg.get_item_children(table_tag, 1):
            dpg.delete_item(child)

        # Add rows
        for s in sessions:
            sid = s["id"]
            with dpg.table_row(parent=table_tag):

                def make_callback(session_id):
                    return lambda *args: select_session(session_id)

                dpg.add_selectable(label=sid, callback=make_callback(sid))
                dpg.add_text(s["title"][:35] + ("..." if len(s["title"]) > 35 else ""))
                dpg.add_text(s["endpoint"])
                dpg.add_text(s["provider"])
                dpg.add_text(str(s["messages"]))
                updated = s["updated"][:16].replace("T", " ") if s["updated"] else ""
                dpg.add_text(updated)

    def select_session(session_id):
        selected_session["id"] = session_id
        dpg.set_value(status_tag, f"Selected: {session_id}")

    def open_callback():
        if selected_session["id"]:
            session = get_session(selected_session["id"])
            if session:
                create_chat_window(session)
                dpg.set_value(status_tag, f"Opened session {selected_session['id']}")
        else:
            dpg.set_value(status_tag, "No session selected")

    def delete_callback():
        if selected_session["id"]:
            sid = selected_session["id"]
            with SESSION_LOCK:
                if sid in CHAT_SESSIONS:
                    del CHAT_SESSIONS[sid]
            save_sessions()
            selected_session["id"] = None
            refresh_table()
            dpg.set_value(status_tag, f"Deleted session {sid}")
        else:
            dpg.set_value(status_tag, "No session selected")

    def close_callback():
        unregister_window(window_tag)
        dpg.delete_item(window_tag)

    register_window(window_tag)

    with dpg.window(
        label="Session Browser",
        tag=window_tag,
        width=850,
        height=500,
        pos=[50 + (window_id % 3) * 30, 50 + (window_id % 3) * 30],
        on_close=close_callback,
    ):
        dpg.add_text("Saved Chat Sessions", color=(200, 200, 255))
        dpg.add_separator()

        with dpg.table(
            tag=table_tag,
            header_row=True,
            borders_innerH=True,
            borders_outerH=True,
            borders_innerV=True,
            borders_outerV=True,
            scrollY=True,
            height=-60,
        ):
            dpg.add_table_column(label="ID", width_fixed=True, init_width_or_weight=70)
            dpg.add_table_column(label="Title", width_stretch=True)
            dpg.add_table_column(label="Endpoint", width_fixed=True, init_width_or_weight=80)
            dpg.add_table_column(label="Provider", width_fixed=True, init_width_or_weight=80)
            dpg.add_table_column(label="Msgs", width_fixed=True, init_width_or_weight=50)
            dpg.add_table_column(label="Updated", width_fixed=True, init_width_or_weight=130)

            for s in sessions:
                sid = s["id"]
                with dpg.table_row():

                    def make_callback(session_id):
                        return lambda *args: select_session(session_id)

                    dpg.add_selectable(label=sid, callback=make_callback(sid))
                    dpg.add_text(s["title"][:35] + ("..." if len(s["title"]) > 35 else ""))
                    dpg.add_text(s["endpoint"])
                    dpg.add_text(s["provider"])
                    dpg.add_text(str(s["messages"]))
                    updated = s["updated"][:16].replace("T", " ") if s["updated"] else ""
                    dpg.add_text(updated)

        dpg.add_separator()

        with dpg.group(horizontal=True):
            dpg.add_button(label="Open Chat", callback=open_callback)
            dpg.add_button(label="Delete", callback=delete_callback)
            dpg.add_button(label="Refresh", callback=refresh_table)
            dpg.add_button(label="Close", callback=close_callback)

        dpg.add_text("Click on a session ID to select it", tag=status_tag, color=(150, 150, 150))


def show_result_gui(text, title="AI Response", endpoint=None):
    """Queue a result GUI window to be created"""
    if not HAVE_GUI:
        print("[Warning] GUI not available.")
        return False

    if not ensure_gui_running():
        print("[Warning] Failed to start GUI.")
        return False

    GUI_QUEUE.put({"type": "result", "text": text, "title": title, "endpoint": endpoint})
    return True


def show_chat_gui(session, initial_response=None):
    """Queue a chat GUI window to be created"""
    if not HAVE_GUI:
        print("[Warning] GUI not available.")
        return False

    if not ensure_gui_running():
        print("[Warning] Failed to start GUI.")
        return False

    GUI_QUEUE.put({"type": "chat", "session": session, "initial_response": initial_response})
    return True


def show_session_browser():
    """Queue a session browser window to be created"""
    if not HAVE_GUI:
        print("[Warning] GUI not available.")
        return False

    if not ensure_gui_running():
        print("[Warning] Failed to start GUI.")
        return False

    GUI_QUEUE.put({"type": "browser"})
    return True


# ============================================================================
# FLASK APPLICATION
# ============================================================================

app = Flask(__name__)


def create_endpoint_handler(endpoint_name, prompt_template):
    def handler():
        start_time = time.time()

        image_bytes = None
        mime_type = "image/png"

        if "image" in request.files:
            image_file = request.files["image"]
            image_bytes = image_file.read()
            mime_type = image_file.mimetype or "image/png"
        elif request.content_type and "image" in request.content_type:
            image_bytes = request.get_data()
            mime_type = request.content_type.split(";")[0]
        elif request.data:
            image_bytes = request.data

        if not image_bytes:
            abort(400, description="No image found in request.")

        base64_image = base64.b64encode(image_bytes).decode("utf-8")

        # Parse provider override
        provider = CONFIG.get("default_provider", "google")
        if request.args.get("provider"):
            provider = request.args.get("provider").lower()
        elif request.headers.get("X-API-Provider"):
            provider = request.headers.get("X-API-Provider").lower()

        # Parse prompt override
        prompt = prompt_template
        if request.args.get("prompt"):
            prompt = request.args.get("prompt")
        elif request.headers.get("X-Custom-Prompt"):
            prompt = request.headers.get("X-Custom-Prompt")

        # Parse model override
        model_override = None
        if request.args.get("model"):
            model_override = request.args.get("model")
        elif request.headers.get("X-API-Model"):
            model_override = request.headers.get("X-API-Model")

        # Determine the effective model for logging
        if model_override:
            effective_model = model_override
        elif provider == "openrouter":
            effective_model = CONFIG.get("openrouter_model", "google/gemini-2.5-flash-preview")
        elif provider == "google":
            effective_model = CONFIG.get("google_model", "gemini-2.0-flash")
        elif provider == "custom":
            effective_model = CONFIG.get("custom_model", "not configured")
        else:
            effective_model = "unknown"

        show_mode = request.args.get("show", CONFIG.get("default_show", "no")).lower()

        # Enhanced request logging
        print(f"\n{'=' * 60}")
        print(f"[{endpoint_name.upper()}] New request")
        print(f"  Provider: {provider}")
        print(f"  Model: {effective_model}{' (override)' if model_override else ' (default)'}")
        print(f"  Image: {len(image_bytes) / 1024:.1f} KB ({mime_type})")
        print(f"  Show mode: {show_mode}")
        print(f"  Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")

        result, error = call_api_simple(provider, prompt, base64_image, mime_type, model_override)
        elapsed = time.time() - start_time

        if error:
            print(f"  [FAILED] {error} ({elapsed:.1f}s)")
            print(f"{'=' * 60}\n")

            if show_mode in ("gui", "chatgui") and HAVE_GUI:
                show_result_gui(f"Error: {error}", title="Error", endpoint=endpoint_name)

            return jsonify({"error": error, "elapsed": elapsed}), 500

        print(f"  [SUCCESS] {len(result)} chars ({elapsed:.1f}s)")
        print(f"{'=' * 60}\n")

        if show_mode == "gui" and HAVE_GUI:
            show_result_gui(result, title=f"Response - /{endpoint_name}", endpoint=endpoint_name)

        elif show_mode == "chatgui" and HAVE_GUI:
            session = ChatSession(
                endpoint=endpoint_name,
                provider=provider,
                model=model_override,
                image_base64=base64_image,
                mime_type=mime_type,
            )
            session.add_message("user", prompt)
            session.add_message("assistant", result)
            add_session(session)
            show_chat_gui(session, initial_response=result)

        if request.headers.get("Accept") == "application/json":
            return jsonify({"text": result, "elapsed": elapsed})

        return result, 200, {"Content-Type": "text/plain; charset=utf-8"}

    handler.__name__ = f"handle_{endpoint_name}"
    return handler


@app.route("/")
def index():
    available_providers = [p for p, km in KEY_MANAGERS.items() if km.has_keys()]
    return jsonify(
        {
            "service": "Universal ShareX Middleman",
            "status": "running",
            "gui_available": HAVE_GUI,
            "gui_running": GUI_RUNNING,
            "default_provider": CONFIG.get("default_provider", "google"),
            "available_providers": available_providers,
            "endpoints": {
                f"/{name}": prompt[:100] + "..." if len(prompt) > 100 else prompt for name, prompt in ENDPOINTS.items()
            },
            "show_modes": {
                "no": "Return text only (default)",
                "gui": "Show result in a GUI window",
                "chatgui": "Show result in a chat GUI with input for follow-up",
            },
            "sessions": len(CHAT_SESSIONS),
        }
    )


@app.route("/health")
def health():
    return jsonify(
        {
            "status": "healthy",
            "gui_available": HAVE_GUI,
            "gui_running": GUI_RUNNING,
            "providers": {p: km.get_key_count() for p, km in KEY_MANAGERS.items() if km.has_keys()},
            "endpoints_count": len(ENDPOINTS),
            "sessions_count": len(CHAT_SESSIONS),
        }
    )


@app.route("/sessions")
def sessions_api():
    return jsonify({"sessions": list_sessions()})


@app.route("/sessions/<session_id>")
def get_session_api(session_id):
    session = get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(session.to_dict())


@app.route("/gui/browser")
def open_browser_api():
    """Open the session browser via HTTP request"""
    if show_session_browser():
        return jsonify({"status": "ok", "message": "Session browser opened"})
    else:
        return jsonify({"status": "error", "message": "GUI not available"}), 503


@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": str(e.description)}), 400


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


# ============================================================================
# TERMINAL SESSION MANAGER
# ============================================================================


def terminal_session_manager():
    print("\n" + "─" * 60)
    print("TERMINAL COMMANDS (press key anytime):")
    print("  [L] List sessions       [O] Open session browser (GUI)")
    print("  [S] Show session        [D] Delete session")
    print("  [C] Clear all sessions  [H] Help")
    print("  [G] Toggle GUI status")
    print("─" * 60 + "\n")

    def get_input_nonblocking():
        if sys.platform == "win32":
            import msvcrt

            if msvcrt.kbhit():
                return msvcrt.getch().decode("utf-8", errors="ignore").lower()
            return None
        else:
            import select
            import termios
            import tty

            old_settings = None
            try:
                old_settings = termios.tcgetattr(sys.stdin)
                tty.setcbreak(sys.stdin.fileno())
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    return sys.stdin.read(1).lower()
            except:
                pass
            finally:
                if old_settings:
                    try:
                        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                    except:
                        pass
            return None

    while True:
        try:
            key = get_input_nonblocking()

            if key == "l":
                sessions = list_sessions()
                print(f"\n{'─' * 60}")
                print(f"SAVED SESSIONS ({len(sessions)} total):")
                print(f"{'─' * 60}")
                if not sessions:
                    print("  (No sessions)")
                else:
                    for i, s in enumerate(sessions[:10]):
                        print(f"  [{s['id']}] {s['title'][:40]} ({s['messages']} msgs, {s['provider']})")
                    if len(sessions) > 10:
                        print(f"  ... and {len(sessions) - 10} more")
                print(f"{'─' * 60}\n")

            elif key == "o":
                if HAVE_GUI:
                    print("\n[Opening session browser...]\n")
                    show_session_browser()
                else:
                    print("\n[GUI not available]\n")

            elif key == "g":
                print(f"\n{'─' * 60}")
                print("GUI STATUS:")
                print(f"  Available: {HAVE_GUI}")
                print(f"  Running: {GUI_RUNNING}")
                print(f"  Context Created: {GUI_CONTEXT_CREATED}")
                print(f"  Open Windows: {len(OPEN_WINDOWS)}")
                if OPEN_WINDOWS:
                    for w in list(OPEN_WINDOWS):
                        print(f"    - {w}")
                print(f"{'─' * 60}\n")

            elif key == "s":
                print("\nEnter session ID: ", end="", flush=True)
                try:
                    session_id = input().strip()
                    session = get_session(session_id)
                    if session:
                        print(f"\n{'─' * 60}")
                        print(f"SESSION: {session.session_id}")
                        print(f"Title: {session.title}")
                        print(f"Endpoint: {session.endpoint} | Provider: {session.provider}")
                        print(f"Created: {session.created_at}")
                        print(f"{'─' * 60}")
                        for msg in session.messages:
                            role = "USER" if msg["role"] == "user" else "ASSISTANT"
                            print(f"\n[{role}]")
                            print(msg["content"][:500] + ("..." if len(msg["content"]) > 500 else ""))
                        print(f"{'─' * 60}\n")

                        if HAVE_GUI:
                            open_gui = input("Open in chat GUI? [y/N]: ").strip().lower()
                            if open_gui == "y":
                                show_chat_gui(session)
                    else:
                        print(f"Session '{session_id}' not found.\n")
                except:
                    pass

            elif key == "d":
                print("\nEnter session ID to delete: ", end="", flush=True)
                try:
                    session_id = input().strip()
                    if session_id in CHAT_SESSIONS:
                        confirm = input(f"Delete session {session_id}? [y/N]: ").strip().lower()
                        if confirm == "y":
                            with SESSION_LOCK:
                                del CHAT_SESSIONS[session_id]
                            save_sessions()
                            print(f"Session {session_id} deleted.\n")
                    else:
                        print(f"Session '{session_id}' not found.\n")
                except:
                    pass

            elif key == "c":
                try:
                    confirm = input("\nClear ALL sessions? This cannot be undone. [y/N]: ").strip().lower()
                    if confirm == "y":
                        with SESSION_LOCK:
                            CHAT_SESSIONS.clear()
                        save_sessions()
                        print("All sessions cleared.\n")
                except:
                    pass

            elif key == "h":
                print("\n" + "─" * 60)
                print("TERMINAL COMMANDS:")
                print("  [L] List sessions       - Show recent saved sessions")
                print("  [O] Open browser        - Open session browser GUI")
                print("  [S] Show session        - Display a session by ID")
                print("  [D] Delete session      - Delete a session by ID")
                print("  [C] Clear all           - Delete all sessions")
                print("  [G] GUI status          - Show GUI state information")
                print("  [H] Help                - Show this help")
                print("─" * 60 + "\n")

            time.sleep(0.1)

        except Exception as e:
            print(f"[Terminal Error] {e}")
            time.sleep(1)


# ============================================================================
# INITIALIZATION
# ============================================================================


def initialize():
    global CONFIG, AI_PARAMS, ENDPOINTS, KEY_MANAGERS

    print("=" * 60)
    print("Universal ShareX Middleman Server (Dear PyGui - On Demand)")
    print("=" * 60)

    print(f"\nLoading configuration from '{CONFIG_FILE}'...")
    config, ai_params, endpoints, keys = load_config()

    CONFIG = config
    AI_PARAMS = ai_params
    ENDPOINTS = endpoints

    for provider in ["custom", "openrouter", "google"]:
        KEY_MANAGERS[provider] = KeyManager(keys[provider], provider)
        count = len(keys[provider])
        if count > 0:
            print(f"  ✓ {provider}: {count} API key(s) loaded")
        else:
            print(f"  ✗ {provider}: No API keys")

    print("\nLoading saved sessions...")
    load_sessions()

    print("\nServer Configuration:")
    print(f"  Host: {CONFIG.get('host', '127.0.0.1')}")
    print(f"  Port: {CONFIG.get('port', 5000)}")
    print(f"  Default Provider: {CONFIG.get('default_provider', 'google')}")
    print(f"  Default Show Mode: {CONFIG.get('default_show', 'no')}")
    print(f"  GUI Available: {HAVE_GUI}")
    print("  GUI Mode: On-demand (starts when needed)")
    print(f"  Max Sessions: {CONFIG.get('max_sessions', 50)}")

    if AI_PARAMS:
        print("\nAI Parameters:")
        for k, v in AI_PARAMS.items():
            print(f"  {k}: {v}")

    print(f"\nRegistering {len(ENDPOINTS)} endpoint(s):")
    for endpoint_name, prompt in ENDPOINTS.items():
        handler = create_endpoint_handler(endpoint_name, prompt)
        app.add_url_rule(f"/{endpoint_name}", endpoint_name, handler, methods=["POST"])
        prompt_preview = prompt[:60] + "..." if len(prompt) > 60 else prompt
        print(f"  /{endpoint_name}")
        print(f"      → {prompt_preview}")

    print("\n" + "=" * 60)


def generate_example_config():
    return """# ============================================================
# Universal ShareX Middleman Server Configuration
# ============================================================

[config]
# Server settings
host = 127.0.0.1
port = 5000

# Default API provider: custom, openrouter, or google
default_provider = google

# Default show mode: no, gui, or chatgui
default_show = no

# Custom API configuration
# custom_url = https://api.openai.com/v1/chat/completions
# custom_model = gpt-4o

# OpenRouter model (see https://openrouter.ai/models for options)
openrouter_model = google/gemini-2.5-flash-preview

# Google Gemini model
google_model = gemini-2.0-flash

# Retry settings
max_retries = 3
retry_delay = 5
request_timeout = 120

# Session management
max_sessions = 50

# AI Parameters (optional)
# temperature = 0.7
# max_tokens = 4096
# top_p = 1.0

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

# ============================================================
# ENDPOINTS - Define your custom endpoints and prompts
# Format: endpoint_name = prompt text
# Access via: POST http://host:port/endpoint_name
# ============================================================

[endpoints]
ocr = Extract the text from this image. Preserve the original formatting, including line breaks, spacing, and layout, as accurately as possible. Return only the extracted text.

translate = Translate all text in this image to English. Preserve the original formatting as much as possible. Return only the translated text.

translate_ja = Translate all Japanese text in this image to English. Maintain the original structure and formatting. Return only the translation.

translate_zh = Translate all Chinese text in this image to English. Maintain the original structure and formatting. Return only the translation.

translate_ko = Translate all Korean text in this image to English. Maintain the original structure and formatting. Return only the translation.

summarize = Summarize the content shown in this image concisely. Focus on the main points and key information.

describe = Describe this image in detail, including all visible elements, text, colors, and context.

code = Extract any code from this image. Preserve exact formatting, indentation, and syntax. Return only the code without any explanation.

explain = Analyze and explain what is shown in this image. Provide context and insights.

explain_code = Extract and explain any code shown in this image. First show the code, then explain what it does.

latex = Convert any mathematical equations or formulas in this image to LaTeX format. Return only the LaTeX code.

markdown = Convert the content of this image to Markdown format. Preserve the structure, headings, lists, and formatting.

proofread = Extract the text from this image and proofread it. Fix any spelling, grammar, or punctuation errors. Return the corrected text.

caption = Generate a short, descriptive caption for this image suitable for social media or alt text.

analyze = Analyze this image and provide insights about its content, context, and any notable elements.

extract_data = Extract any structured data (tables, lists, key-value pairs) from this image and format it clearly.

handwriting = Transcribe any handwritten text in this image as accurately as possible.
"""


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    # Create example config if needed
    if not Path(CONFIG_FILE).exists():
        print(f"Config file '{CONFIG_FILE}' not found.")
        print("Creating example configuration file...")
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(generate_example_config())
        print(f"✓ Created '{CONFIG_FILE}'")
        print("\nPlease edit the config file to add your API keys, then restart.")
        exit(0)

    # Initialize
    initialize()

    # Check for API keys
    has_any_keys = any(km.has_keys() for km in KEY_MANAGERS.values())
    if not has_any_keys:
        print("\n⚠️  WARNING: No API keys configured!")
        print("Please add your API keys to config.ini\n")

    # NOTE: GUI is NOT started at startup - it will be started on-demand
    # when a GUI window is requested (via ?show=gui, ?show=chatgui, or pressing 'O')
    if HAVE_GUI:
        print("✓ GUI available (will start on-demand when needed)")
    else:
        print("✗ GUI not available (Dear PyGui not installed)")

    # Start terminal session manager
    terminal_thread = threading.Thread(target=terminal_session_manager, daemon=True)
    terminal_thread.start()

    # Start server
    host = CONFIG.get("host", "127.0.0.1")
    port = int(CONFIG.get("port", 5000))

    print(f"\n🚀 Starting server at http://{host}:{port}")
    print(f"   Endpoints: {', '.join('/' + e for e in ENDPOINTS)}")
    print("\n   Show modes:")
    print("     ?show=no      - Return text only (default)")
    print("     ?show=gui     - Display result in GUI window (starts GUI on first use)")
    print("     ?show=chatgui - Display result in chat GUI with follow-up input")
    print("\nPress Ctrl+C to stop\n")

    app.run(host=host, port=port, debug=False, threaded=True)
