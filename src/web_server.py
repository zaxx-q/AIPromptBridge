#!/usr/bin/env python3
"""
Flask web server for AIPromptBridge
"""

import logging
import time

from flask import Flask, jsonify, request

from .api_client import call_api_chat, call_api_simple, fetch_models
from .config import CONFIG_FILE
from .session_manager import ChatSession, add_session, get_session, list_sessions

# GUI is optional (e.g. Linux hosts without tkinter) — soft import
try:
    from .gui.core import HAVE_GUI, get_gui_status, show_chat_gui, show_session_browser
except ImportError:
    HAVE_GUI = False

    def get_gui_status():
        return {"available": False, "running": False, "error": "GUI dependencies not available"}

    def show_chat_gui(*_args, **_kwargs):
        raise RuntimeError("GUI not available")

    def show_session_browser(*_args, **_kwargs):
        raise RuntimeError("GUI not available")


# Global state - will be initialized by main.py
CONFIG = {}
AI_PARAMS = {}
KEY_MANAGERS = {}

# Connection profile state — the single source of truth for connection settings
ACTIVE_PROFILE = None  # Current ConnectionProfile object
SESSION_OVERRIDES = {}  # In-memory session overrides from terminal toggles

# Cached models list
CACHED_MODELS = None
FILE_PROCESSOR_JOB_SERVICE = None

app = Flask(__name__)


def _get_file_processor_service():
    """Construct the non-Flask job service only after app state is initialized."""
    global FILE_PROCESSOR_JOB_SERVICE
    if FILE_PROCESSOR_JOB_SERVICE is None:
        from .tools.file_processor_service import FileProcessorJobService

        FILE_PROCESSOR_JOB_SERVICE = FileProcessorJobService(CONFIG, AI_PARAMS, KEY_MANAGERS)
    return FILE_PROCESSOR_JOB_SERVICE


@app.get("/file-processor/capabilities")
def file_processor_capabilities():
    return jsonify(_get_file_processor_service().capabilities())


@app.post("/file-processor/jobs")
def create_file_processor_job():
    from .tools.file_processor_service import JobBusyError, JobSemanticError, JobValidationError

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a JSON object"}), 400
    try:
        result = _get_file_processor_service().run(payload)
        return jsonify(result.to_api_dict()), 200 if result.success else 422
    except JobBusyError as exc:
        return jsonify({"error": str(exc), "active_job_id": exc.job_id}), 409
    except JobSemanticError as exc:
        return jsonify({"error": str(exc), "fields": exc.errors}), 422
    except JobValidationError as exc:
        return jsonify({"error": str(exc), "fields": exc.errors}), 400
    except Exception:
        logging.exception("File Processor job failed unexpectedly")
        return jsonify({"error": "Internal server error"}), 500


@app.get("/file-processor/jobs/<job_id>")
def get_file_processor_job(job_id):
    value = _get_file_processor_service().get(job_id)
    return (jsonify(value), 200) if value else (jsonify({"error": "Job not found"}), 404)


@app.post("/file-processor/jobs/<job_id>/resume")
def resume_file_processor_job(job_id):
    from .tools.file_processor_service import JobBusyError, JobSemanticError, JobValidationError

    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a JSON object"}), 400
    try:
        result = _get_file_processor_service().resume(job_id, payload)
        return jsonify(result.to_api_dict()), 200 if result.success else 422
    except FileNotFoundError:
        return jsonify({"error": "Job not found"}), 404
    except JobBusyError as exc:
        return jsonify({"error": str(exc), "active_job_id": exc.job_id}), 409
    except JobSemanticError as exc:
        return jsonify({"error": str(exc), "fields": exc.errors}), 422
    except JobValidationError as exc:
        return jsonify({"error": str(exc), "fields": exc.errors}), 400
    except Exception:
        logging.exception("File Processor resume failed unexpectedly")
        return jsonify({"error": "Internal server error"}), 500


@app.delete("/file-processor/jobs/<job_id>")
def delete_file_processor_job(job_id):
    from .tools.file_processor_service import JobBusyError

    try:
        if not _get_file_processor_service().delete(job_id):
            return jsonify({"error": "Job not found"}), 404
    except JobBusyError as exc:
        return jsonify({"error": str(exc), "active_job_id": exc.job_id}), 409
    return "", 204


@app.route("/")
def index():
    """Root endpoint with service information"""
    available_providers = [p for p, km in KEY_MANAGERS.items() if km.has_keys()]
    return jsonify(
        {
            "service": "AIPromptBridge",
            "status": "running",
            "gui_available": HAVE_GUI,
            "gui_running": get_gui_status()["running"],
            "default_provider": get_active_setting("provider", "google"),
            "available_providers": available_providers,
            "sessions": len(list_sessions()),
        }
    )


@app.route("/health")
def health():
    """Health check endpoint"""
    gui_status = get_gui_status()
    return jsonify(
        {
            "status": "healthy",
            "gui_available": HAVE_GUI,
            "gui_running": gui_status["running"],
            "providers": {p: km.get_key_count() for p, km in KEY_MANAGERS.items() if km.has_keys()},
            "sessions_count": len(list_sessions()),
        }
    )


@app.route("/models")
def get_models():
    """Fetch available models from upstream API"""
    global CACHED_MODELS

    # Check for force refresh
    force_refresh = request.args.get("refresh", "false").lower() in ("true", "1", "yes")

    if not force_refresh and CACHED_MODELS is not None:
        return jsonify({"object": "list", "data": CACHED_MODELS, "cached": True})

    # Resolve profile to get merged config with connection keys
    from .profile_resolver import resolve_profile

    resolved = resolve_profile(None, CONFIG, AI_PARAMS, KEY_MANAGERS)
    models, error = fetch_models(resolved.config, resolved.key_managers)

    if error:
        return jsonify({"error": error}), 500

    # Cache the models
    CACHED_MODELS = models

    return jsonify({"object": "list", "data": models, "cached": False})


@app.route("/sessions")
def sessions_list():
    """List all chat sessions"""
    return jsonify(list_sessions())


@app.route("/sessions/<session_id>")
def get_session_api(session_id):
    """Get a specific session"""
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
    """Handle 400 errors"""
    return jsonify({"error": str(e.description)}), 400


@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors"""
    return jsonify({"error": "Internal server error"}), 500


def init_web_server(config, ai_params, key_managers):
    """Initialize web server with configuration"""
    global CONFIG, AI_PARAMS, KEY_MANAGERS, ACTIVE_PROFILE, FILE_PROCESSOR_JOB_SERVICE
    CONFIG = config
    AI_PARAMS = ai_params
    KEY_MANAGERS = key_managers
    FILE_PROCESSOR_JOB_SERVICE = None

    # Set active profile from ProfileStore
    from .connection_profiles import ProfileStore

    ACTIVE_PROFILE = ProfileStore.get_instance().get_active_profile()

    return app


def switch_active_profile(profile_name: str) -> bool:
    """
    Switch the active connection profile at runtime.

    Updates ProfileStore, sets ACTIVE_PROFILE, repopulates CONFIG/AI_PARAMS,
    and fires config change notifications so all listeners update.

    Returns True on success, False if profile not found.
    """
    global CONFIG, AI_PARAMS, ACTIVE_PROFILE, SESSION_OVERRIDES

    from .config import notify_config_change
    from .connection_profiles import ProfileStore

    store = ProfileStore.get_instance()
    if not store.set_active_profile(profile_name):
        return False

    ACTIVE_PROFILE = store.get_active_profile()
    SESSION_OVERRIDES.clear()  # Profile switch resets session overrides

    # Profile is the source of truth — no longer populating CONFIG/AI_PARAMS
    # (connection keys are read via ACTIVE_PROFILE / get_active_setting() / resolve_profile())
    #
    # Key overrides (api_key_pool / api_key_name) are handled at request time
    # by resolve_profile() — no need to mutate global KEY_MANAGERS here.

    notify_config_change("_bulk_update", None)
    return True


def get_active_setting(key: str, default=None):
    """Read a connection setting from the active profile, with session override support.

    Checks SESSION_OVERRIDES first (terminal toggles), then ACTIVE_PROFILE,
    then returns the default.

    Supported keys: provider, model, streaming, thinking, thinking_budget,
    thinking_level, reasoning_effort, base_url,
    request_timeout, temperature, max_tokens, api_key_name, api_key_pool
    """
    if key in SESSION_OVERRIDES:
        return SESSION_OVERRIDES[key]
    if ACTIVE_PROFILE:
        mapping = {
            "provider": ACTIVE_PROFILE.provider,
            "model": ACTIVE_PROFILE.model,
            "streaming": ACTIVE_PROFILE.streaming,
            "thinking": ACTIVE_PROFILE.thinking,
            "thinking_budget": ACTIVE_PROFILE.thinking_budget,
            "thinking_level": ACTIVE_PROFILE.thinking_level,
            "reasoning_effort": ACTIVE_PROFILE.reasoning_effort,
            "base_url": ACTIVE_PROFILE.base_url,
            "request_timeout": ACTIVE_PROFILE.request_timeout,
            "temperature": ACTIVE_PROFILE.temperature,
            "max_tokens": ACTIVE_PROFILE.max_tokens,
            "api_key_name": ACTIVE_PROFILE.api_key_name,
            "api_key_pool": ACTIVE_PROFILE.api_key_pool,
        }
        return mapping.get(key, default)
    return default
