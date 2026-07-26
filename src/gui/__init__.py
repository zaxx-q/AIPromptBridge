# GUI package for CustomTkinter interface
# Uses CustomTkinter for modern UI with fallback to standard Tkinter
#
# Imports are softened so missing tkinter / tool deps on Linux do not hard-crash
# the package (prompts config and other non-GUI consumers stay importable).

# Core GUI coordinator (requires tkinter)
try:
    from .core import (
        HAVE_GUI,
        GUICoordinator,
        get_gui_status,
        show_chat_gui,
        show_prompt_editor,
        show_session_browser,
        show_settings_window,
    )
except ImportError:
    HAVE_GUI = False
    GUICoordinator = None  # type: ignore[assignment,misc]

    def get_gui_status():
        return {"available": False, "running": False, "error": "GUI dependencies not available"}

    def show_chat_gui(*_args, **_kwargs):
        raise RuntimeError("GUI not available")

    def show_prompt_editor(*_args, **_kwargs):
        raise RuntimeError("GUI not available")

    def show_session_browser(*_args, **_kwargs):
        raise RuntimeError("GUI not available")

    def show_settings_window(*_args, **_kwargs):
        raise RuntimeError("GUI not available")


try:
    from .platform import HAVE_CTK, ctk
except ImportError:
    HAVE_CTK = False
    ctk = None

# Popups (optional — needs tk)
try:
    from .popups import TypingIndicator, create_typing_indicator, dismiss_typing_indicator
except ImportError:
    TypingIndicator = None  # type: ignore[assignment,misc]
    create_typing_indicator = None  # type: ignore[assignment]
    dismiss_typing_indicator = None  # type: ignore[assignment]

# Prompts config is pure data — should always load when package deps allow
from .prompts import PromptsConfig, get_prompts_config, reload_prompts

# Tool apps (optional — may lack pynput / audio / etc.)
try:
    from .snip_tool import SnipToolApp
except ImportError:
    SnipToolApp = None  # type: ignore[assignment,misc]

try:
    from .text_edit_tool import TextEditToolApp
except ImportError:
    TextEditToolApp = None  # type: ignore[assignment,misc]

# Themes / utils may need tk for some helpers; soften
try:
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
except ImportError:
    ThemeColors = None  # type: ignore[assignment,misc]
    ThemeRegistry = None  # type: ignore[assignment,misc]
    get_color_scheme = None  # type: ignore[assignment]
    get_colors = None  # type: ignore[assignment]
    get_ctk_button_colors = None  # type: ignore[assignment]
    get_ctk_entry_colors = None  # type: ignore[assignment]
    get_ctk_frame_colors = None  # type: ignore[assignment]
    get_ctk_scrollbar_colors = None  # type: ignore[assignment]
    get_ctk_textbox_colors = None  # type: ignore[assignment]
    list_themes = None  # type: ignore[assignment]
    sync_ctk_appearance = None  # type: ignore[assignment]

try:
    from .utils import copy_to_clipboard, get_tk_text_for_ctk_frame, render_markdown, setup_text_tags
except ImportError:
    copy_to_clipboard = None  # type: ignore[assignment]
    get_tk_text_for_ctk_frame = None  # type: ignore[assignment]
    render_markdown = None  # type: ignore[assignment]
    setup_text_tags = None  # type: ignore[assignment]

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
