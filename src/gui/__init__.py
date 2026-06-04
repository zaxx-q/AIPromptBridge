# GUI package for CustomTkinter interface
# Uses CustomTkinter for modern UI with fallback to standard Tkinter

# Check for CustomTkinter availability
from .core import (
    HAVE_GUI,
    GUICoordinator,
    get_gui_status,
    show_chat_gui,
    show_prompt_editor,
    show_session_browser,
    show_settings_window,
)
from .platform import HAVE_CTK, ctk
from .popups import TypingIndicator, create_typing_indicator, dismiss_typing_indicator
from .prompts import PromptsConfig, get_prompts_config, reload_prompts
from .snip_tool import SnipToolApp
from .text_edit_tool import TextEditToolApp
from .themes import (
    ThemeColors,
    ThemeRegistry,
    get_color_scheme,
    get_colors,
    get_ctk_button_colors,
    get_ctk_entry_colors,
    get_ctk_frame_colors,
    get_ctk_scrollbar_colors,
    get_ctk_textbox_colors,
    list_themes,
    sync_ctk_appearance,
)
from .utils import copy_to_clipboard, get_tk_text_for_ctk_frame, render_markdown, setup_text_tags

# Emoji rendering support (Windows color emoji fix)
try:
    from .emoji_renderer import HAVE_CTK as HAVE_CTK_EMOJI
    from .emoji_renderer import (
        HAVE_PIL,
        EmojiRenderer,
        get_ctk_emoji_image,
        get_emoji_renderer,
        insert_with_emojis,
        prepare_emoji_content,
    )

    HAVE_EMOJI_RENDERER = HAVE_PIL
except ImportError:
    HAVE_EMOJI_RENDERER = False
    EmojiRenderer = None
    get_emoji_renderer = None
    insert_with_emojis = None
    get_ctk_emoji_image = None
    prepare_emoji_content = None
    HAVE_CTK_EMOJI = False

__all__ = [
    "HAVE_CTK",
    "HAVE_EMOJI_RENDERER",
    "HAVE_GUI",
    # Emoji rendering
    "EmojiRenderer",
    "GUICoordinator",
    # Prompts configuration
    "PromptsConfig",
    "SnipToolApp",
    # Core exports
    "TextEditToolApp",
    "ThemeColors",
    # Theme system
    "ThemeRegistry",
    "TypingIndicator",
    # Utilities
    "copy_to_clipboard",
    # Popups
    "create_typing_indicator",
    "dismiss_typing_indicator",
    "get_color_scheme",
    "get_colors",
    "get_ctk_button_colors",
    "get_ctk_emoji_image",
    "get_ctk_entry_colors",
    "get_ctk_frame_colors",
    "get_ctk_scrollbar_colors",
    "get_ctk_textbox_colors",
    "get_emoji_renderer",
    "get_gui_status",
    "get_prompts_config",
    "get_tk_text_for_ctk_frame",
    "insert_with_emojis",
    "list_themes",
    "prepare_emoji_content",
    "reload_prompts",
    "render_markdown",
    "setup_text_tags",
    "show_chat_gui",
    "show_prompt_editor",
    "show_session_browser",
    "show_settings_window",
    "sync_ctk_appearance",
]
