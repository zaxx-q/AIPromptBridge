#!/usr/bin/env python3
"""
Script to generate screenshots of the TextEditTool popup in all available themes.
Run with: python test/generate_theme_screenshots.py
"""

import os
import sys
import time

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import customtkinter as ctk
from PIL import ImageGrab

# Mock the configuration
import src.web_server

src.web_server.CONFIG = {
    "text_edit_tool_enabled": True,
    "ui_theme_mode": "dark",  # Default to dark for screenshots
    "ui_force_standard_tk": False
}

from src.gui.popups import AttachedPromptPopup
from src.gui.themes import ThemeRegistry, sync_ctk_appearance

# Dummy options for the popup
MOCK_OPTIONS = {
    "_settings": {
        "popup_items_per_page": 4
    },
    "Proofread": {
        "icon": "✏️",
        "task": "Fix grammar and spelling"
    },
    "Rewrite": {
        "icon": "📝",
        "task": "Rewrite for better clarity"
    },
    "Summarize": {
        "icon": "📋",
        "task": "Create a brief summary"
    },
    "Explain": {
        "icon": "💡",
        "task": "Explain this text"
    },
    "Casual": {
        "icon": "😎",
        "task": "Make it sound casual"
    }
}

OUTPUT_DIR = "docs/images/themes"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def mock_callback(*args):
    pass

def take_screenshot_of_window(window, filename):
    """Capture screenshot of a specific window"""
    # Force update
    window.update()
    window.update_idletasks()
    time.sleep(0.5)  # Wait for render

    # Get window coordinates
    x = window.winfo_rootx()
    y = window.winfo_rooty()
    w = window.winfo_width()
    h = window.winfo_height()

    # Add some padding/margin if needed, or capture exact
    # Note: winfo_rootx/y excludes window manager decorations for some OS,
    # but for overrideredirect=True (which popups are), it should be exact.

    # Capture
    bbox = (x, y, x + w, y + h)
    screenshot = ImageGrab.grab(bbox=bbox)
    screenshot.save(filename)
    print(f"Saved {filename}")

def main():
    print("Starting theme screenshot generator...")

    # Initialize main root (hidden)
    root = ctk.CTk()
    root.withdraw()

    # List of themes to capture
    themes = ThemeRegistry.list_themes()

    # Dummy selected text
    selected_text = "This is some sample text to demonstrate the AI popup interface."

    # Screen position for the popup
    popup_x = 200
    popup_y = 200

    try:
        for theme in themes:
            print(f"Processing theme: {theme}")

            # Update config
            src.web_server.CONFIG["ui_theme"] = theme
            src.web_server.CONFIG["ui_theme_mode"] = "dark" # Capture dark mode

            # Sync appearance
            sync_ctk_appearance(src.web_server.CONFIG)

            # Create popup
            # Note: We need to pass options and callbacks
            popup = AttachedPromptPopup(
                parent_root=root,
                options=MOCK_OPTIONS,
                on_option_selected=mock_callback,
                on_close=mock_callback,
                selected_text=selected_text,
                x=popup_x,
                y=popup_y
            )

            # Wait for window to be ready
            # The popup uses .after(10, ...) to show itself
            root.update()
            time.sleep(0.1)
            popup.root.update()

            # Take screenshot
            filename = os.path.join(OUTPUT_DIR, f"theme_{theme}.png")
            take_screenshot_of_window(popup.root, filename)

            # Cleanup
            popup._close()
            root.update()
            time.sleep(0.1)

            # Also capture Light mode for same theme?
            # User request: "launch TextEditTool popup in all themes"
            # "show as gallery/grid/table style"
            # Maybe just dark mode is enough for now, or both?
            # Let's do Dark mode first as it's usually the primary showcase.

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        root.destroy()
        print("Done.")

if __name__ == "__main__":
    main()
