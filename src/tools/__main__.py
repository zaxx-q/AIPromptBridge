#!/usr/bin/env python3
"""
Tools Package Entry Point - Allows running tools via 'python -m src.tools'
"""
import os
import sys

# Ensure we can import from project root
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config import load_config, load_key_names
from src.key_manager import KeyManager
from src import web_server
from src.tools.file_processor import show_tools_menu

def main():
    # Initialize globals for the tool to function (mirroring main.py logic)
    config, ai_params, endpoints, keys = load_config()
    web_server.CONFIG = config
    web_server.AI_PARAMS = ai_params
    web_server.ENDPOINTS = endpoints
    
    # Initialize key managers
    key_names = load_key_names()
    for provider in ["custom", "openrouter", "google"]:
        web_server.KEY_MANAGERS[provider] = KeyManager(
            keys[provider], provider, key_names=key_names.get(provider, [])
        )
    
    # Run the menu
    show_tools_menu(endpoints=web_server.ENDPOINTS)

if __name__ == "__main__":
    main()