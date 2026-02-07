#!/usr/bin/env python3
"""
Flask web server with API endpoints
"""

import base64
import time

from flask import Flask, request, abort, jsonify

from .config import CONFIG_FILE
from .api_client import call_api_simple, call_api_chat, fetch_models
from .session_manager import ChatSession, add_session, get_session, list_sessions
from .gui.core import show_chat_gui, show_session_browser, get_gui_status, HAVE_GUI

# Global state - will be initialized by main.py
CONFIG = {}
AI_PARAMS = {}
ENDPOINTS = {}
KEY_MANAGERS = {}

# Cached models list
CACHED_MODELS = None

app = Flask(__name__)


def create_endpoint_handler(endpoint_name, prompt_template):
    """Create a handler function for a specific endpoint"""
    def handler():
        start_time = time.time()
        
        image_bytes = None
        mime_type = 'image/png'
        
        if 'image' in request.files:
            image_file = request.files['image']
            image_bytes = image_file.read()
            mime_type = image_file.mimetype or 'image/png'
        elif request.content_type and 'image' in request.content_type:
            image_bytes = request.get_data()
            mime_type = request.content_type.split(';')[0]
        elif request.data:
            image_bytes = request.data
        
        if not image_bytes:
            abort(400, description='No image found in request.')
        
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        # Parse provider override
        provider = CONFIG.get("default_provider", "google")
        if request.args.get('provider'):
            provider = request.args.get('provider').lower()
        elif request.headers.get('X-API-Provider'):
            provider = request.headers.get('X-API-Provider').lower()
        
        # Parse prompt override
        prompt = prompt_template
        if request.args.get('prompt'):
            prompt = request.args.get('prompt')
        elif request.headers.get('X-Custom-Prompt'):
            prompt = request.headers.get('X-Custom-Prompt')
        
        # Parse lang parameter and substitute {lang} placeholder
        lang = request.args.get('lang', 'English')
        if request.headers.get('X-Target-Language'):
            lang = request.headers.get('X-Target-Language')
        prompt = prompt.replace('{lang}', lang)
        
        # Parse model override
        model_override = None
        if request.args.get('model'):
            model_override = request.args.get('model')
        elif request.headers.get('X-API-Model'):
            model_override = request.headers.get('X-API-Model')
        
        # Determine the effective model for logging
        if model_override:
            effective_model = model_override
        elif provider == "openrouter":
            effective_model = CONFIG.get("openrouter_model", "openai/gpt-oss-120b:free")
        elif provider == "google":
            effective_model = CONFIG.get("google_model", "gemini-2.5-flash")
        elif provider == "custom":
            effective_model = CONFIG.get("custom_model", "not configured")
        else:
            effective_model = "unknown"
        
        # Show parameter: yes/true/1 = show chat window, anything else = no
        # Uses show_ai_response_in_chat_window
        default_show = CONFIG.get('show_ai_response_in_chat_window', False)
        show_param = request.args.get('show', default_show)
        if isinstance(show_param, bool):
            show_gui = show_param
        else:
            show_gui = str(show_param).lower() in ('yes', 'true', '1')
        
        # Use unified pipeline
        from .request_pipeline import RequestPipeline, RequestContext, RequestOrigin
        
        # Determine origin based on endpoint name
        try:
            origin_name = f"ENDPOINT_{endpoint_name.upper()}"
            origin = getattr(RequestOrigin, origin_name, RequestOrigin.ENDPOINT_OCR)
        except:
            origin = RequestOrigin.ENDPOINT_OCR
            
        ctx = RequestContext(
            origin=origin,
            provider=provider,
            model=effective_model,
            streaming=False,
            thinking_enabled=False
        )
        
        # Prepare messages for simple API call
        data_url = f"data:{mime_type};base64,{base64_image}"
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": prompt}
            ]
        }]
        
        # Execute via pipeline
        ctx = RequestPipeline.execute_simple(ctx, messages, CONFIG, AI_PARAMS, KEY_MANAGERS)
        
        result = ctx.response_text
        error = ctx.error
        elapsed = ctx.elapsed_time
        
        if error:
            return jsonify({"error": error, "elapsed": elapsed}), 500
        
        # Show chat window if requested
        if show_gui and HAVE_GUI:
            session = ChatSession(
                endpoint=endpoint_name,
                mime_type=mime_type
            )
            
            # Save attachment so it's available in chat history
            from .attachment_manager import AttachmentManager
            attachment_path = AttachmentManager.save_image(
                session_id=session.session_id,
                image_base64=base64_image,
                mime_type=mime_type,
                message_index=0
            )
            
            attachments = []
            if attachment_path:
                attachments.append({
                    "path": attachment_path,
                    "mime_type": mime_type
                })
            
            session.add_message("user", prompt, attachments=attachments)
            session.add_message("assistant", result)
            add_session(session, CONFIG.get("max_sessions", 50))
            show_chat_gui(session, initial_response=result)
        
        if request.headers.get('Accept') == 'application/json':
            return jsonify({"text": result, "elapsed": elapsed})
        
        return result, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    
    handler.__name__ = f"handle_{endpoint_name}"
    return handler


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
        "endpoints": {f"/{name}": prompt[:100] + "..." if len(prompt) > 100 else prompt 
                     for name, prompt in ENDPOINTS.items()},
        "show_parameter": {
            "yes": "Show result in a chat GUI window",
            "no": "Return text only (default)"
        },
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
        "endpoints_count": len(ENDPOINTS),
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


def init_web_server(config, ai_params, endpoints, key_managers):
    """Initialize web server with configuration"""
    global CONFIG, AI_PARAMS, ENDPOINTS, KEY_MANAGERS
    CONFIG = config
    AI_PARAMS = ai_params
    KEY_MANAGERS = key_managers
    
    # Only register endpoints if flask_endpoints_enabled is true
    # Default: False (use built-in screen snipping instead)
    flask_endpoints_enabled = config.get("flask_endpoints_enabled", False)
    
    if flask_endpoints_enabled:
        ENDPOINTS = endpoints
        # Register dynamic endpoints
        for endpoint_name, prompt in endpoints.items():
            handler = create_endpoint_handler(endpoint_name, prompt)
            app.add_url_rule(f'/{endpoint_name}', endpoint_name, handler, methods=['POST'])
    else:
        # No endpoints registered - API available but no custom routes
        ENDPOINTS = {}
    
    return app
