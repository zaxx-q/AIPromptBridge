#!/usr/bin/env python3
"""
Tools Package Entry Point - Allows running tools via 'python -m src.tools'

Direct sub-commands (skip the interactive menu):
    python -m src.tools merge <export_dir>   Merge chunked transcript responses
"""

import os
import sys

# Ensure we can import from project root
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def _run_merge_command(export_dir: str) -> int:
    """Run the export-merge tool without full app initialization (no API keys needed)."""
    from src.console import print_error
    from src.tools.file_processor import merge_export_responses

    result = merge_export_responses(export_dir, interactive=True)
    if not result:
        print_error("Merge produced no output")
        return 1
    return 0


def main():
    # Check for direct sub-commands first
    if len(sys.argv) > 1:
        sub = sys.argv[1].lower()

        if sub == "merge":
            if len(sys.argv) < 3:
                print("Usage: python -m src.tools merge <export_dir>")
                sys.exit(1)

            sys.exit(_run_merge_command(sys.argv[2]))

        # Unknown sub-command — show available commands
        print(f"Unknown command: {sub}")
        print("Available: merge <export_dir>")
        sys.exit(1)

    # Initialize globals for the tool to function (mirroring main.py logic)
    from src import web_server
    from src.config import load_config
    from src.key_store import KeyStore
    from src.tools.file_processor import show_tools_menu

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
