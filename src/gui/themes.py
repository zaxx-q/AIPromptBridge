#!/usr/bin/env python3
"""
# Theme System for AIPromptBridge GUI
#
# Provides a centralized theme registry with multiple color schemes.
# Each theme has dark and light variants.
#
# Themes available:
# - catppuccin: Warm pastel colors (Mocha/Latte)
# - dracula: Dark purple-based theme (Classic/Pro)
# - nord: Arctic blue palette (Polar Night/Snow Storm)
# - gruvbox: Retro earthy colors (Dark/Light)
# - minimal: Clean, minimal design (Dark/Light)
# - highcontrast: Maximum readability (Dark/Light)

CustomTkinter Integration:
- get_ctk_button_colors(): Get button styling kwargs
- get_ctk_frame_colors(): Get frame styling kwargs
- get_ctk_entry_colors(): Get entry styling kwargs
- get_ctk_font(): Get appropriate CTkFont
- sync_ctk_appearance(): Sync appearance mode with config
"""

import sys
from dataclasses import dataclass, field
from typing import Dict, Optional

try:
    import darkdetect

    HAVE_DARKDETECT = True
except ImportError:
    HAVE_DARKDETECT = False

# Import CustomTkinter with fallback
from .platform import HAVE_CTK, ctk


@dataclass
class ThemeColors:
    """
    Complete color definition for a theme.

    This dataclass provides both the standard naming (bg, fg, accent)
    and legacy popup-style naming (base, text, blue) via properties
    for backward compatibility.
    """

    # Base colors
    bg: str  # Primary background
    fg: str  # Primary text
    text_bg: str  # Text area background
    input_bg: str  # Input field background
    border: str  # Border color

    # Accent colors
    accent: str  # Primary accent (blue-ish)
    accent_green: str  # Success/positive
    accent_yellow: str  # Warning/attention
    accent_red: str  # Error/danger

    # Chat-specific
    user_bg: str  # User message background
    user_accent: str  # User label color
    assistant_bg: str  # Assistant message background
    assistant_accent: str  # Assistant label color

    # Code/Markdown
    code_bg: str  # Code block background
    header1: str  # H1 color
    header2: str  # H2 color
    header3: str  # H3 color
    bullet: str  # Bullet point color
    blockquote: str  # Blockquote/muted text

    # Popup-specific (elevated surfaces)
    surface0: str  # Elevated surface level 0
    surface1: str  # Elevated surface level 1 (hover)
    surface2: str  # Elevated surface level 2 (borders)
    overlay0: str  # Muted overlay text
    lavender: str  # Secondary accent (purple-ish)
    peach: str  # Tertiary accent (orange-ish)

    # Legacy popup-style property aliases
    @property
    def base(self) -> str:
        """Alias for bg (legacy popup compatibility)."""
        return self.bg

    @property
    def mantle(self) -> str:
        """Alias for code_bg (legacy popup compatibility)."""
        return self.code_bg

    @property
    def text(self) -> str:
        """Alias for fg (legacy popup compatibility)."""
        return self.fg

    @property
    def subtext0(self) -> str:
        """Alias for blockquote (legacy popup compatibility)."""
        return self.blockquote

    @property
    def blue(self) -> str:
        """Alias for accent (legacy popup compatibility)."""
        return self.accent

    @property
    def green(self) -> str:
        """Alias for accent_green (legacy popup compatibility)."""
        return self.accent_green

    @property
    def red(self) -> str:
        """Alias for accent_red (legacy popup compatibility)."""
        return self.accent_red

    @property
    def accent_fg(self) -> str:
        """Text color for use on accent-colored backgrounds.

        Uses the theme's bg color, matching the official Catppuccin pattern
        where button text_color is the base background. This provides
        high contrast for both dark themes (dark text on pastel accents)
        and light themes (light text on saturated accents).
        """
        return self.bg


# =============================================================================
# Theme Definitions
# =============================================================================

# Catppuccin Mocha (Dark)
CATPPUCCIN_DARK = ThemeColors(
    bg="#1e1e2e",
    fg="#cdd6f4",
    text_bg="#313244",
    input_bg="#45475a",
    border="#585b70",
    accent="#89b4fa",
    accent_green="#a6e3a1",
    accent_yellow="#f9e2af",
    accent_red="#f38ba8",
    user_bg="#1e3a5f",
    user_accent="#89b4fa",
    assistant_bg="#1e3e2e",
    assistant_accent="#a6e3a1",
    code_bg="#11111b",
    header1="#f9e2af",
    header2="#89b4fa",
    header3="#94e2d5",
    bullet="#f5c2e7",
    blockquote="#a6adc8",  # Improved readability (was #6c7086)
    surface0="#313244",
    surface1="#45475a",
    surface2="#585b70",
    overlay0="#a6adc8",  # Improved readability (was #6c7086)
    lavender="#b4befe",
    peach="#fab387",
)

# Catppuccin Latte (Light)
CATPPUCCIN_LIGHT = ThemeColors(
    bg="#eff1f5",
    fg="#4c4f69",
    text_bg="#ffffff",
    input_bg="#ffffff",
    border="#ccd0da",
    accent="#1e66f5",
    accent_green="#40a02b",
    accent_yellow="#df8e1d",
    accent_red="#d20f39",
    user_bg="#dce0e8",
    user_accent="#1e66f5",
    assistant_bg="#e6f3e6",
    assistant_accent="#40a02b",
    code_bg="#e6e9ef",
    header1="#df8e1d",
    header2="#1e66f5",
    header3="#179299",
    bullet="#ea76cb",
    blockquote="#8c8fa1",
    surface0="#ccd0da",
    surface1="#bcc0cc",
    surface2="#acb0be",
    overlay0="#9ca0b0",
    lavender="#7287fd",
    peach="#fe640b",
)

# Dracula Classic (Dark)
DRACULA_DARK = ThemeColors(
    bg="#282a36",
    fg="#f8f8f2",
    text_bg="#21222c",
    input_bg="#44475a",
    border="#6272a4",
    accent="#bd93f9",
    accent_green="#50fa7b",
    accent_yellow="#f1fa8c",
    accent_red="#ff5555",
    user_bg="#2d3548",
    user_accent="#bd93f9",
    assistant_bg="#283e2f",
    assistant_accent="#50fa7b",
    code_bg="#1e1f29",
    header1="#f1fa8c",
    header2="#bd93f9",
    header3="#8be9fd",
    bullet="#ff79c6",
    blockquote="#b0b5c4",  # Improved readability (was #6272a4)
    surface0="#44475a",
    surface1="#4d5066",
    surface2="#6272a4",
    overlay0="#b0b5c4",  # Improved readability (was #6272a4)
    lavender="#bd93f9",
    peach="#ffb86c",
)

# Dracula Pro Light
DRACULA_LIGHT = ThemeColors(
    bg="#f8f8f2",
    fg="#282a36",
    text_bg="#ffffff",
    input_bg="#ffffff",
    border="#d1d5db",
    accent="#7c3aed",
    accent_green="#22863a",
    accent_yellow="#b08800",
    accent_red="#dc2626",
    user_bg="#ede9fe",
    user_accent="#7c3aed",
    assistant_bg="#d1fae5",
    assistant_accent="#22863a",
    code_bg="#f3f4f6",
    header1="#b08800",
    header2="#7c3aed",
    header3="#0284c7",
    bullet="#ec4899",
    blockquote="#6b7280",
    surface0="#e5e7eb",
    surface1="#d1d5db",
    surface2="#9ca3af",
    overlay0="#6b7280",
    lavender="#8b5cf6",
    peach="#f97316",
)

# Nord Polar Night (Dark)
NORD_DARK = ThemeColors(
    bg="#2e3440",
    fg="#eceff4",
    text_bg="#3b4252",
    input_bg="#434c5e",
    border="#4c566a",
    accent="#88c0d0",
    accent_green="#a3be8c",
    accent_yellow="#ebcb8b",
    accent_red="#bf616a",
    user_bg="#3b4252",
    user_accent="#88c0d0",
    assistant_bg="#3b4a3d",
    assistant_accent="#a3be8c",
    code_bg="#2e3440",
    header1="#ebcb8b",
    header2="#88c0d0",
    header3="#81a1c1",
    bullet="#b48ead",
    blockquote="#9aa5b8",  # Improved readability (was #4c566a)
    surface0="#3b4252",
    surface1="#434c5e",
    surface2="#4c566a",
    overlay0="#9aa5b8",  # Improved readability (was #4c566a)
    lavender="#b48ead",
    peach="#d08770",
)

# Nord Snow Storm (Light)
NORD_LIGHT = ThemeColors(
    bg="#eceff4",
    fg="#2e3440",
    text_bg="#ffffff",
    input_bg="#ffffff",
    border="#d8dee9",
    accent="#5e81ac",
    accent_green="#8fbcbb",
    accent_yellow="#ebcb8b",
    accent_red="#bf616a",
    user_bg="#e5e9f0",
    user_accent="#5e81ac",
    assistant_bg="#e6f0ea",
    assistant_accent="#8fbcbb",
    code_bg="#e5e9f0",
    header1="#ebcb8b",
    header2="#5e81ac",
    header3="#81a1c1",
    bullet="#b48ead",
    blockquote="#4c566a",
    surface0="#e5e9f0",
    surface1="#d8dee9",
    surface2="#c8ced8",
    overlay0="#4c566a",
    lavender="#b48ead",
    peach="#d08770",
)

# Gruvbox Dark
GRUVBOX_DARK = ThemeColors(
    bg="#282828",
    fg="#ebdbb2",
    text_bg="#3c3836",
    input_bg="#504945",
    border="#665c54",
    accent="#83a598",
    accent_green="#b8bb26",
    accent_yellow="#fabd2f",
    accent_red="#fb4934",
    user_bg="#3c3836",
    user_accent="#83a598",
    assistant_bg="#3c4137",
    assistant_accent="#b8bb26",
    code_bg="#1d2021",
    header1="#fabd2f",
    header2="#83a598",
    header3="#8ec07c",
    bullet="#d3869b",
    blockquote="#bdae93",  # Improved readability (was #928374)
    surface0="#3c3836",
    surface1="#504945",
    surface2="#665c54",
    overlay0="#bdae93",  # Improved readability (was #928374)
    lavender="#d3869b",
    peach="#fe8019",
)

# Gruvbox Light
GRUVBOX_LIGHT = ThemeColors(
    bg="#fbf1c7",
    fg="#3c3836",
    text_bg="#ffffff",
    input_bg="#ffffff",
    border="#d5c4a1",
    accent="#076678",
    accent_green="#79740e",
    accent_yellow="#b57614",
    accent_red="#9d0006",
    user_bg="#ebdbb2",
    user_accent="#076678",
    assistant_bg="#e6eed8",
    assistant_accent="#79740e",
    code_bg="#ebdbb2",
    header1="#b57614",
    header2="#076678",
    header3="#427b58",
    bullet="#8f3f71",
    blockquote="#928374",
    surface0="#ebdbb2",
    surface1="#d5c4a1",
    surface2="#bdae93",
    overlay0="#928374",
    lavender="#8f3f71",
    peach="#af3a03",
)


# Minimal Dark
MINIMAL_DARK = ThemeColors(
    bg="#1a1a1a",
    fg="#e0e0e0",
    text_bg="#222222",
    input_bg="#2a2a2a",
    border="#404040",
    accent="#5a8ff0",
    accent_green="#43a047",
    accent_yellow="#ffb74d",
    accent_red="#f44336",
    user_bg="#252530",
    user_accent="#5a8ff0",
    assistant_bg="#253025",
    assistant_accent="#43a047",
    code_bg="#161616",
    header1="#ffb74d",
    header2="#5a8ff0",
    header3="#4dd0e1",
    bullet="#ba68c8",
    blockquote="#b3b3b3",  # Improved readability (was #808080)
    surface0="#252525",
    surface1="#303030",
    surface2="#404040",
    overlay0="#b3b3b3",  # Improved readability (was #808080)
    lavender="#9575cd",
    peach="#ff8a65",
)

# Minimal Light
MINIMAL_LIGHT = ThemeColors(
    bg="#ffffff",
    fg="#333333",
    text_bg="#ffffff",
    input_bg="#f5f5f5",
    border="#e0e0e0",
    accent="#2196f3",
    accent_green="#4caf50",
    accent_yellow="#ff9800",
    accent_red="#f44336",
    user_bg="#f5f5f5",
    user_accent="#2196f3",
    assistant_bg="#e8f5e9",
    assistant_accent="#4caf50",
    code_bg="#fafafa",
    header1="#ff9800",
    header2="#2196f3",
    header3="#00bcd4",
    bullet="#9c27b0",
    blockquote="#9e9e9e",
    surface0="#f5f5f5",
    surface1="#eeeeee",
    surface2="#e0e0e0",
    overlay0="#9e9e9e",
    lavender="#7e57c2",
    peach="#ff7043",
)

# High Contrast Dark
HIGHCONTRAST_DARK = ThemeColors(
    bg="#000000",
    fg="#ffffff",
    text_bg="#0a0a0a",
    input_bg="#141414",
    border="#ffffff",
    accent="#00ffff",
    accent_green="#00ff00",
    accent_yellow="#ffff00",
    accent_red="#ff0000",
    user_bg="#001a1a",
    user_accent="#00ffff",
    assistant_bg="#001a00",
    assistant_accent="#00ff00",
    code_bg="#0a0a0a",
    header1="#ffff00",
    header2="#00ffff",
    header3="#00cccc",
    bullet="#ff00ff",
    blockquote="#999999",
    surface0="#141414",
    surface1="#1f1f1f",
    surface2="#333333",
    overlay0="#999999",
    lavender="#ff00ff",
    peach="#ff8800",
)

# High Contrast Light
HIGHCONTRAST_LIGHT = ThemeColors(
    bg="#ffffff",
    fg="#000000",
    text_bg="#ffffff",
    input_bg="#f0f0f0",
    border="#000000",
    accent="#0000ff",
    accent_green="#006600",
    accent_yellow="#996600",
    accent_red="#cc0000",
    user_bg="#e6e6ff",
    user_accent="#0000ff",
    assistant_bg="#e6ffe6",
    assistant_accent="#006600",
    code_bg="#f5f5f5",
    header1="#996600",
    header2="#0000ff",
    header3="#006699",
    bullet="#990099",
    blockquote="#666666",
    surface0="#f0f0f0",
    surface1="#e0e0e0",
    surface2="#cccccc",
    overlay0="#666666",
    lavender="#6600cc",
    peach="#cc6600",
)


# =============================================================================
# Theme Registry
# =============================================================================


class ThemeRegistry:
    """
    Central registry for all available themes.

    Usage:
        # Get current theme based on config and system
        colors = ThemeRegistry.get_current()

        # Get specific theme
        colors = ThemeRegistry.get_theme("dracula", "dark")

        # List available themes
        themes = ThemeRegistry.list_themes()
    """

    from typing import ClassVar

    _themes: ClassVar[Dict[str, tuple]] = {
        "catppuccin": (CATPPUCCIN_DARK, CATPPUCCIN_LIGHT),
        "dracula": (DRACULA_DARK, DRACULA_LIGHT),
        "nord": (NORD_DARK, NORD_LIGHT),
        "gruvbox": (GRUVBOX_DARK, GRUVBOX_LIGHT),
        "minimal": (MINIMAL_DARK, MINIMAL_LIGHT),
        "highcontrast": (HIGHCONTRAST_DARK, HIGHCONTRAST_LIGHT),
    }

    # Default theme
    DEFAULT_THEME = "dracula"
    DEFAULT_MODE = "auto"

    @classmethod
    def list_themes(cls) -> list:
        """Get list of available theme names."""
        return list(cls._themes.keys())

    @classmethod
    def get_theme(cls, name: str, mode: str) -> ThemeColors:
        """
        Get specific theme colors.

        Args:
            name: Theme name (catppuccin, dracula, nord, etc.)
            mode: 'dark' or 'light'

        Returns:
            ThemeColors for the specified theme and mode
        """
        if name not in cls._themes:
            name = cls.DEFAULT_THEME

        dark_theme, light_theme = cls._themes[name]

        if mode == "light":
            return light_theme
        return dark_theme

    @classmethod
    def is_dark_mode(cls) -> bool:
        """Check if system is in dark mode."""
        if HAVE_DARKDETECT:
            try:
                return darkdetect.isDark()
            except Exception:
                pass
        return True  # Default to dark if can't detect

    @classmethod
    def get_current(cls, config: Optional[Dict] = None) -> ThemeColors:
        """
        Get current theme colors based on config and system settings.

        Args:
            config: Optional config dict with 'ui_theme' and 'ui_theme_mode' keys.
                   If not provided, reads from web_server.CONFIG.

        Returns:
            ThemeColors for the current theme and mode
        """
        # Get config if not provided
        if config is None:
            try:
                from .. import web_server

                config = web_server.CONFIG
            except (ImportError, AttributeError):
                config = {}

        # Get theme name (default: catppuccin)
        theme_name = config.get("ui_theme", cls.DEFAULT_THEME)
        if theme_name not in cls._themes:
            theme_name = cls.DEFAULT_THEME

        # Get mode (auto, dark, light)
        theme_mode = config.get("ui_theme_mode", cls.DEFAULT_MODE)

        if theme_mode == "auto":
            # Use system detection
            is_dark = cls.is_dark_mode()
        elif theme_mode == "light":
            is_dark = False
        else:  # "dark" or fallback
            is_dark = True

        return cls.get_theme(theme_name, "dark" if is_dark else "light")

    @classmethod
    def get_current_as_dict(cls, config: Optional[Dict] = None) -> Dict[str, str]:
        """
        Get current theme colors as a dictionary.

        This provides backward compatibility with code expecting a dict
        from the old get_color_scheme() function.

        Returns:
            Dict mapping color names to hex values
        """
        colors = cls.get_current(config)
        return {
            "bg": colors.bg,
            "fg": colors.fg,
            "text_bg": colors.text_bg,
            "input_bg": colors.input_bg,
            "button_bg": colors.surface0,
            "border": colors.border,
            "accent": colors.accent,
            "accent_fg": colors.accent_fg,
            "accent_green": colors.accent_green,
            "accent_yellow": colors.accent_yellow,
            "accent_red": colors.accent_red,
            "user_bg": colors.user_bg,
            "user_accent": colors.user_accent,
            "assistant_bg": colors.assistant_bg,
            "assistant_accent": colors.assistant_accent,
            "code_bg": colors.code_bg,
            "header1": colors.header1,
            "header2": colors.header2,
            "header3": colors.header3,
            "bullet": colors.bullet,
            "blockquote": colors.blockquote,
            # Popup-specific (added for compatibility)
            "surface0": colors.surface0,
            "surface1": colors.surface1,
            "surface2": colors.surface2,
            "overlay0": colors.overlay0,
            "lavender": colors.lavender,
            "peach": colors.peach,
        }


# =============================================================================
# Convenience Functions
# =============================================================================


def get_colors() -> ThemeColors:
    """
    Get current theme colors.

    This is a convenience function for use in popup windows and other
    GUI components that need access to the current theme.

    Returns:
        ThemeColors dataclass with all color values
    """
    return ThemeRegistry.get_current()


def get_color_scheme() -> Dict[str, str]:
    """
    Get current theme colors as a dictionary.

    This maintains backward compatibility with existing code that uses
    the dict-based color scheme from utils.py.

    Returns:
        Dict mapping color names to hex values
    """
    return ThemeRegistry.get_current_as_dict()


def is_dark_mode() -> bool:
    """
    Check if system is in dark mode.

    Returns:
        True if system is in dark mode, False otherwise
    """
    return ThemeRegistry.is_dark_mode()


def list_themes() -> list:
    """
    Get list of available theme names.

    Returns:
        List of theme name strings
    """
    return ThemeRegistry.list_themes()


# =============================================================================
# CustomTkinter Integration Functions
# =============================================================================


def get_ctk_font(size: int = 12, weight: str = "normal", family: str | None = None):
    """
    Get a font specification with appropriate defaults for the platform.

    Args:
        size: Font size in points
        weight: "normal" or "bold"
        family: Font family (auto-detected if None)

    Returns:
        Tuple font specification (family, size, weight) - works with both
        standard tkinter and CustomTkinter widgets, and is thread-safe.

    Note:
        We return a tuple instead of CTkFont because CTkFont cannot be
        created from non-main threads (causes RuntimeError). Tuple fonts
        work perfectly with CTk widgets.
    """
    if family is None:
        if sys.platform == "win32":
            family = "Segoe UI"
        elif sys.platform == "darwin":
            family = "SF Pro Text"
        else:
            family = "DejaVu Sans"

    # Always return tuple - works with both tk and CTk, and is thread-safe
    return (family, size, weight)


def _adjust_hex_color(hex_color: str, factor: float) -> str:
    """Adjust brightness of a hex color by a factor. factor < 1.0 darkens, > 1.0 lightens."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return f"#{hex_color}"
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        r = max(0, min(255, int(r * factor)))
        g = max(0, min(255, int(g * factor)))
        b = max(0, min(255, int(b * factor)))

        return f"#{r:02x}{g:02x}{b:02x}"
    except ValueError:
        return f"#{hex_color}"


def get_ctk_button_colors(colors: ThemeColors, variant: str = "primary") -> dict:
    """
    Get CTkButton color kwargs based on theme and variant.

    Args:
        colors: ThemeColors instance
        variant: "primary", "secondary", "success", "danger", or "ghost"

    Returns:
        Dict of CTkButton color kwargs
    """
    if variant == "primary":
        return {
            "fg_color": colors.accent,
            "hover_color": colors.lavender,
            "text_color": colors.accent_fg,
            "border_width": 0,
        }
    elif variant == "success":
        return {
            "fg_color": colors.accent_green,
            "hover_color": _adjust_hex_color(colors.accent_green, 0.85),
            "text_color": colors.accent_fg,
            "border_width": 0,
        }
    elif variant == "warning":
        return {
            "fg_color": colors.accent_yellow,
            "hover_color": colors.peach,
            "text_color": colors.accent_fg,
            "border_width": 0,
        }
    elif variant == "danger":
        return {
            "fg_color": colors.accent_red,
            "hover_color": _adjust_hex_color(colors.accent_red, 0.85),
            "text_color": colors.accent_fg,
            "border_width": 0,
        }
    elif variant == "ghost":
        return {
            "fg_color": "transparent",
            "hover_color": colors.surface1,
            "text_color": colors.fg,
            "border_width": 0,
        }
    else:  # secondary
        return {
            "fg_color": colors.surface0,
            "hover_color": colors.surface1,
            "text_color": colors.fg,
            "border_width": 0,
        }


def get_ctk_frame_colors(colors: ThemeColors, elevated: bool = False) -> dict:
    """
    Get CTkFrame color kwargs based on theme.

    Args:
        colors: ThemeColors instance
        elevated: If True, use slightly elevated surface color

    Returns:
        Dict of CTkFrame color kwargs
    """
    return {
        "fg_color": colors.surface0 if elevated else colors.bg,
        "border_color": colors.border,
    }


def get_ctk_entry_colors(colors: ThemeColors) -> dict:
    """
    Get CTkEntry color kwargs based on theme.

    Note: For CTkTextbox, use get_ctk_textbox_colors() instead.
    CTkTextbox does NOT support placeholder_text_color.

    Args:
        colors: ThemeColors instance

    Returns:
        Dict of CTkEntry color kwargs
    """
    return {
        "fg_color": colors.input_bg,
        "text_color": colors.fg,
        "border_color": colors.border,
        "placeholder_text_color": colors.overlay0,
    }


def get_ctk_textbox_colors(colors: ThemeColors) -> dict:
    """
    Get CTkTextbox color kwargs based on theme.

    Note: CTkTextbox does NOT support placeholder text.
    Use CTkEntry for single-line input with placeholder.

    Args:
        colors: ThemeColors instance

    Returns:
        Dict of CTkTextbox color kwargs
    """
    return {
        "fg_color": colors.input_bg,
        "text_color": colors.fg,
        "border_color": colors.border,
    }


def get_ctk_scrollbar_colors(colors: ThemeColors) -> dict:
    """
    Get CTkScrollbar color kwargs based on theme.

    Args:
        colors: ThemeColors instance

    Returns:
        Dict of CTkScrollbar color kwargs
    """
    return {
        "fg_color": colors.surface0,
        "button_color": colors.surface2,
        "button_hover_color": colors.overlay0,
    }


def get_ctk_segmented_colors(colors: ThemeColors) -> dict:
    """
    Get CTkSegmentedButton color kwargs based on theme.

    Args:
        colors: ThemeColors instance

    Returns:
        Dict of CTkSegmentedButton color kwargs
    """
    return {
        "fg_color": colors.surface0,
        "selected_color": colors.accent,
        "selected_hover_color": colors.lavender,
        "unselected_color": colors.surface0,
        "unselected_hover_color": colors.surface1,
        "text_color": colors.fg,
        "text_color_disabled": colors.overlay0,
    }


def get_ctk_combobox_colors(colors: ThemeColors) -> dict:
    """
    Get CTkComboBox color kwargs based on theme.

    Args:
        colors: ThemeColors instance

    Returns:
        Dict of CTkComboBox color kwargs
    """
    return {
        "fg_color": colors.input_bg,
        "text_color": colors.fg,
        "border_color": colors.border,
        "button_color": colors.surface2,
        "button_hover_color": colors.overlay0,
        "dropdown_fg_color": colors.surface0,
        "dropdown_hover_color": colors.surface1,
        "dropdown_text_color": colors.fg,
    }


def get_ctk_label_colors(colors: ThemeColors, muted: bool = False) -> dict:
    """
    Get CTkLabel color kwargs based on theme.

    Args:
        colors: ThemeColors instance
        muted: If True, use muted text color

    Returns:
        Dict of CTkLabel color kwargs
    """
    return {
        "text_color": colors.overlay0 if muted else colors.fg,
    }


def sync_ctk_appearance(config: Optional[Dict] = None):
    """
    Sync CustomTkinter appearance mode with config.

    Args:
        config: Optional config dict. If None, reads from web_server.CONFIG
    """
    if not HAVE_CTK:
        return

    if config is None:
        try:
            from .. import web_server

            config = web_server.CONFIG
        except (ImportError, AttributeError):
            config = {}

    mode = config.get("ui_theme_mode", "auto")

    if mode == "auto":
        ctk.set_appearance_mode("system")
    elif mode == "light":
        ctk.set_appearance_mode("light")
    else:
        ctk.set_appearance_mode("dark")


def apply_hover_effect(widget, colors: ThemeColors, normal_color: str | None = None, hover_color: str | None = None):
    """
    Apply hover effect to a CTk widget.

    For widgets that don't have built-in hover (like CTkLabel used as button),
    this adds Enter/Leave bindings to change colors.

    Args:
        widget: CTk widget to apply hover to
        colors: ThemeColors instance
        normal_color: Color when not hovered (default: surface0)
        hover_color: Color when hovered (default: surface1)
    """
    if normal_color is None:
        normal_color = colors.surface0
    if hover_color is None:
        hover_color = colors.surface1

    def on_enter(e):
        try:
            widget.configure(fg_color=hover_color)
        except Exception:
            pass

    def on_leave(e):
        try:
            widget.configure(fg_color=normal_color)
        except Exception:
            pass

    widget.bind("<Enter>", on_enter, add="+")
    widget.bind("<Leave>", on_leave, add="+")


# =============================================================================
# Legacy Compatibility Classes
# =============================================================================


class CatppuccinMocha:
    """
    Legacy compatibility class for popup windows.

    DEPRECATED: Use get_colors() or ThemeRegistry.get_current() instead.
    This class exists only for backward compatibility.
    """

    _colors = CATPPUCCIN_DARK

    base = _colors.bg
    mantle = _colors.code_bg
    surface0 = _colors.surface0
    surface1 = _colors.surface1
    surface2 = _colors.surface2
    overlay0 = _colors.overlay0
    text = _colors.fg
    subtext0 = _colors.blockquote
    blue = _colors.accent
    lavender = _colors.lavender
    green = _colors.accent_green
    peach = _colors.peach
    red = _colors.accent_red


class CatppuccinLatte:
    """
    Legacy compatibility class for popup windows.

    DEPRECATED: Use get_colors() or ThemeRegistry.get_current() instead.
    This class exists only for backward compatibility.
    """

    _colors = CATPPUCCIN_LIGHT

    base = _colors.bg
    mantle = _colors.code_bg
    surface0 = _colors.surface0
    surface1 = _colors.surface1
    surface2 = _colors.surface2
    overlay0 = _colors.overlay0
    text = _colors.fg
    subtext0 = _colors.blockquote
    blue = _colors.accent
    lavender = _colors.lavender
    green = _colors.accent_green
    peach = _colors.peach
    red = _colors.accent_red
