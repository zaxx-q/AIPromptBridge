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

from src import web_server
from src.config import load_config
from src.key_store import KeyStore
from src.tools.file_processor import show_tools_menu


def main():
    # Initialize globals for the tool to function (mirroring main.py logic)
    config = load_config()
    ai_params = {}

    web_server.CONFIG = config
    web_server.AI_PARAMS = ai_params

    # Initialize key managers via KeyStore (pool-based)
    key_store = KeyStore.get_instance()
    key_store.load()
    web_server.KEY_MANAGERS = key_store.build_key_managers()

    # Set ACTIVE_PROFILE from ProfileStore
    from src.connection_profiles import ProfileStore
    web_server.ACTIVE_PROFILE = ProfileStore.get_instance().get_active_profile()

    # Run the menu
    show_tools_menu()

if __name__ == "__main__":
    main()
