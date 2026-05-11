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

from src.config import load_config
from src.key_store import KeyStore
from src import web_server
from src.tools.file_processor import show_tools_menu

def main():
    # Initialize globals for the tool to function (mirroring main.py logic)
    config, ai_params, endpoints = load_config()
    web_server.CONFIG = config
    web_server.AI_PARAMS = ai_params
    web_server.ENDPOINTS = endpoints
    
    # Initialize key managers via KeyStore (pool-based)
    key_store = KeyStore.get_instance()
    key_store.load()
    web_server.KEY_MANAGERS = key_store.build_key_managers()
    
    # Run the menu
    show_tools_menu(endpoints=web_server.ENDPOINTS)

if __name__ == "__main__":
    main()