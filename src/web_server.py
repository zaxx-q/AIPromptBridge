#!/usr/bin/env python3
"""
Flask web server for AIPromptBridge
"""

import time

from flask import Flask, request, jsonify

from .config import CONFIG_FILE
from .api_client import call_api_simple, call_api_chat, fetch_models
from .session_manager import ChatSession, add_session, get_session, list_sessions
from .gui.core import show_chat_gui, show_session_browser, get_gui_status, HAVE_GUI

# Global state - will be initialized by main.py
CONFIG = {}
AI_PARAMS = {}
KEY_MANAGERS = {}

# Cached models list
CACHED_MODELS = None

app = Flask(__name__)


@app.route('/')
def index():
    """Root endpoint with service information"""
    available_providers = [p for p, km in KEY_MANAGERS.items() if km.has_keys()]
    return jsonify({
        "service": "AIPromptBridge",
        "status": "running",
        "gui_available": HAVE_GUI,
        "gui_running": get_gui_status()["running"],
        "default_provider": CONFIG.get("default_provider", "google"),
        "available_providers": available_providers,
        "sessions": len(list_sessions())
    })


@app.route('/health')
def health():
    """Health check endpoint"""
    gui_status = get_gui_status()
    return jsonify({
        "status": "healthy",
        "gui_available": HAVE_GUI,
        "gui_running": gui_status["running"],
        "providers": {p: km.get_key_count() for p, km in KEY_MANAGERS.items() if km.has_keys()},
        "sessions_count": len(list_sessions())
    })


@app.route('/models')
def get_models():
    """Fetch available models from upstream API"""
    global CACHED_MODELS
    
    # Check for force refresh
    force_refresh = request.args.get('refresh', 'false').lower() in ('true', '1', 'yes')
    
    if not force_refresh and CACHED_MODELS is not None:
        return jsonify({
            "object": "list",
            "data": CACHED_MODELS,
            "cached": True
        })
    
    models, error = fetch_models(CONFIG, KEY_MANAGERS)
    
    if error:
        return jsonify({"error": error}), 500
    
    # Cache the models
    CACHED_MODELS = models
    
    return jsonify({
        "object": "list",
        "data": models,
        "cached": False
    })


@app.route('/sessions')
def sessions_list():
    """List all chat sessions"""
    return jsonify(list_sessions())


@app.route('/sessions/<session_id>')
def get_session_api(session_id):
    """Get a specific session"""
    session = get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(session.to_dict())


@app.route('/gui/browser')
def open_browser_api():
    """Open the session browser via HTTP request"""
    if show_session_browser():
        return jsonify({"status": "ok", "message": "Session browser opened"})
    else:
        return jsonify({"status": "error", "message": "GUI not available"}), 503


@app.errorhandler(400)
def bad_request(e):
    """Handle 400 errors"""
    return jsonify({"error": str(e.description)}), 400


@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors"""
    return jsonify({"error": "Internal server error"}), 500


def init_web_server(config, ai_params, key_managers):
    """Initialize web server with configuration"""
    global CONFIG, AI_PARAMS, KEY_MANAGERS
    CONFIG = config
    AI_PARAMS = ai_params
    KEY_MANAGERS = key_managers

    return app


def switch_active_profile(profile_name: str) -> bool:
    """
    Switch the active connection profile at runtime.

    Updates ProfileStore, repopulates CONFIG/AI_PARAMS, and fires
    config change notifications so all listeners (chat windows, etc.) update.

    Returns True on success, False if profile not found.
    """
    global CONFIG, AI_PARAMS

    from .connection_profiles import ProfileStore
    from .config import notify_config_change

    store = ProfileStore.get_instance()
    if not store.set_active_profile(profile_name):
        return False

    profile = store.get_active_profile()
    profile.populate_config(CONFIG)
    profile.populate_ai_params(AI_PARAMS)

    # Rebuild key managers if profile specifies a key pool/name override
    if profile.api_key_pool or profile.api_key_name:
        from .key_store import KeyStore
        KEY_MANAGERS.update(KeyStore.get_instance().build_key_managers())

    notify_config_change("_bulk_update", None)
    return True
