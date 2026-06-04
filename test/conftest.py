"""
Pytest configuration and shared fixtures for AIPromptBridge tests.

This file is automatically loaded by pytest before test collection.
It ensures the project root is on sys.path so `from src.xxx import ...` works.
"""

import sys
from pathlib import Path

# Add project root to sys.path so tests can import src modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
