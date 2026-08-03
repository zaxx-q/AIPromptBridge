#!/usr/bin/env python3
"""
GUI utility functions for clipboard and markdown rendering

Uses tk.Text for markdown rendering (tag support not available in CTkTextbox).
This is the hybrid approach: CTk for windows/widgets, tk.Text for rich text display.

Emoji Support:
    On Windows, Tkinter doesn't natively render color emojis. This module
    integrates with emoji_renderer.py to replace emoji characters with
    inline PNG images from the Twemoji asset set.
"""

import re
import sys
import tkinter as tk
import webbrowser
from tkinter import font as tkfont
from typing import Dict, List, Optional, Tuple, Union

# Windows-specific imports and constants
_user32 = None
_GWL_EXSTYLE = -20
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_TOOLWINDOW = 0x00000080

if sys.platform == "win32":
    try:
        import ctypes
        from ctypes import wintypes

        _user32 = ctypes.windll.user32
    except ImportError:
        pass

# Import CustomTkinter with fallback
from .platform import HAVE_CTK, ctk

# Import theme system
from .themes import ThemeColors, ThemeRegistry, get_ctk_font, get_tk_font, scaled_tk_size
from .themes import get_color_scheme as _get_color_scheme
from .themes import is_dark_mode as _is_dark_mode

# Import emoji renderer
try:
    from .emoji_renderer import HAVE_PIL, EmojiRenderer, get_emoji_renderer

    HAVE_EMOJI_RENDERER = HAVE_PIL
except ImportError:
    HAVE_EMOJI_RENDERER = False
    get_emoji_renderer = None

# Import LaTeX renderer
from .latex_renderer import extract_latex_blocks, latex_to_unicode

# Sentinel markers for pre-processed inline LaTeX.
# _preprocess_inline_latex() wraps converted Unicode with these so that
# downstream insertion can still apply the latex_inline styling tag.
_LATEX_SENTINEL_START = "\x02"  # STX control char – safe for tk.Text
_LATEX_SENTINEL_END = "\x03"  # ETX control char

# Miscellaneous Technical glyphs such as ⎨ / ⎬ used by display math.  Segoe
# UI Symbol is available on Windows; DejaVu Sans carries the same characters
# on Linux and is the dependable cross-desktop fallback.
_SYMBOL_FONT_FAMILY = "Segoe UI Symbol" if sys.platform == "win32" else "DejaVu Sans"


def is_dark_mode() -> bool:
    """
    Check if system is in dark mode.

    This wraps the theme registry's dark mode detection,
    which respects the ui_theme_mode config setting.
    """
    return _is_dark_mode()


def get_color_scheme() -> Dict[str, str]:
    """
    Get color scheme based on current theme and mode.

    This uses the centralized ThemeRegistry which reads from config
    to determine the active theme and mode.

    Returns:
        Dict mapping color names to hex values
    """
    return _get_color_scheme()


def copy_to_clipboard(text: str, root=None) -> bool:
    """
    Cross-platform clipboard copy.

    **Linux/Wayland:** prefers ``wl-copy`` via the platform clipboard service
    (works without X11). Optional Tk clipboard is tried only as a last resort.

    **Windows/macOS:** Tk root clipboard when available, else OS clipboard tools.
    """
    # Linux: prefer wl-copy so Wayland sessions work without X11/xclip.
    if sys.platform.startswith("linux"):
        try:
            from ..platform.clipboard import copy_text as platform_copy_text
            from ..platform.clipboard import is_wl_clipboard_available

            if is_wl_clipboard_available() and platform_copy_text(text if text is not None else ""):
                return True
        except Exception as e:
            print(f"[Clipboard Error] wl-copy path failed: {e}")

        # Optional Tk fallback (may be empty/X11-only on pure Wayland)
        if root:
            try:
                root.clipboard_clear()
                root.clipboard_append(text)
                root.update()
                return True
            except Exception as e:
                print(f"[Clipboard Error] Tk fallback failed: {e}")
                return False
        return False

    try:
        if root:
            # Both tk.Tk and ctk.CTk have clipboard methods
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()  # Required for clipboard to persist
            return True

        # Fallback to subprocess method
        if sys.platform == "win32":
            import subprocess

            process = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            process.communicate(text.encode("utf-16le"))
        elif sys.platform == "darwin":
            import subprocess

            process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            process.communicate(text.encode("utf-8"))
        else:
            try:
                import subprocess

                process = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
                process.communicate(text.encode("utf-8"))
            except Exception:
                process = subprocess.Popen(["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE)
                process.communicate(text.encode("utf-8"))
        return True
    except Exception as e:
        print(f"[Clipboard Error] {e}")
        return False


def _handle_link_click(event):
    """Handle click on a link tag."""
    widget = event.widget
    try:
        # Get index of click
        index = widget.index(f"@{event.x},{event.y}")
        # Get tags at index
        tags = widget.tag_names(index)
        for tag in tags:
            if tag.startswith("url_"):
                url = tag[4:]
                webbrowser.open(url)
                return "break"
    except Exception as e:
        print(f"Error opening link: {e}")


def setup_text_tags(text_widget: tk.Text, colors: Union[Dict[str, str], ThemeColors]):
    """
    Configure text tags for markdown styling with card-based message layout.

    Uses tk.Text tags which provide rich text formatting.
    This is why we keep tk.Text for chat display instead of CTkTextbox.

    Args:
        text_widget: A tk.Text widget (not CTkTextbox)
        colors: Color scheme dict or ThemeColors dataclass
    """
    # Read chat message background config
    try:
        from .. import web_server

        _config = web_server.CONFIG
    except (ImportError, AttributeError):
        _config = {}

    chat_bg_enabled = _config.get("chat_message_bg_enabled", True)
    custom_user_bg = _config.get("chat_user_bg_color", "")
    custom_assistant_bg = _config.get("chat_assistant_bg_color", "")

    # Convert ThemeColors to dict if needed
    if hasattr(colors, "__dataclass_fields__"):
        color_dict = {
            "bg": colors.bg,
            "text_bg": colors.text_bg,
            "header1": colors.accent,
            "header2": colors.accent,
            "header3": colors.accent,
            "fg": colors.fg,
            "code_bg": colors.surface0,
            "accent": colors.accent,
            "bullet": colors.accent,
            "blockquote": colors.blockquote,
            "user_accent": colors.user_accent,
            "assistant_accent": colors.assistant_accent,
            "user_bg": colors.user_bg,
            "assistant_bg": colors.assistant_bg,
            "border": colors.border,
            "accent_yellow": colors.accent_yellow,
            "overlay0": colors.overlay0,
            "surface1": colors.surface1,
            "select_bg": colors.accent,
            "select_fg": colors.bg,
        }
        colors = color_dict

    # Apply chat message background overrides from config
    if not chat_bg_enabled:
        # Disable backgrounds entirely — use the chat area's text_bg (transparent look)
        text_bg = colors.get("text_bg", colors.get("bg", ""))
        if text_bg:
            colors["user_bg"] = text_bg
            colors["assistant_bg"] = text_bg
    else:
        # Apply custom colors if specified (non-empty hex strings)
        if custom_user_bg and custom_user_bg.startswith("#"):
            colors["user_bg"] = custom_user_bg
        if custom_assistant_bg and custom_assistant_bg.startswith("#"):
            colors["assistant_bg"] = custom_assistant_bg

    # Configure text selection colors
    select_bg = colors.get("select_bg", colors.get("accent", "#89b4fa"))
    select_fg = colors.get("select_fg", colors.get("bg", "#1e1e2e"))
    text_widget.configure(selectbackground=select_bg, selectforeground=select_fg)

    # Get available fonts with Segoe UI Emoji fallback for Windows
    try:
        if sys.platform == "win32":
            mono_font = "Consolas"
            base_font = "Segoe UI"
        else:
            mono_font = "DejaVu Sans Mono"
            base_font = "DejaVu Sans"
    except Exception:
        mono_font = "TkFixedFont"
        base_font = "TkDefaultFont"

    # DPI-scale font sizes for raw tk.Text tag configuration.
    # CTk handles its own scaling; raw tk widgets need manual adjustment.
    _s = scaled_tk_size

    # Headers
    text_widget.tag_configure(
        "h1", font=(base_font, _s(16), "bold"), foreground=colors["header1"], spacing1=6, spacing3=4
    )

    text_widget.tag_configure(
        "h2", font=(base_font, _s(14), "bold"), foreground=colors["header2"], spacing1=5, spacing3=3
    )

    text_widget.tag_configure(
        "h3", font=(base_font, _s(12), "bold"), foreground=colors["header3"], spacing1=4, spacing3=2
    )

    text_widget.tag_configure("h4", font=(base_font, _s(11), "bold"), foreground=colors["fg"], spacing1=3, spacing3=2)

    # Header + italic combinations
    text_widget.tag_configure(
        "h1_italic", font=(base_font, _s(16), "bold italic"), foreground=colors["header1"], spacing1=6, spacing3=4
    )

    text_widget.tag_configure(
        "h2_italic", font=(base_font, _s(14), "bold italic"), foreground=colors["header2"], spacing1=5, spacing3=3
    )

    text_widget.tag_configure(
        "h3_italic", font=(base_font, _s(12), "bold italic"), foreground=colors["header3"], spacing1=4, spacing3=2
    )

    text_widget.tag_configure(
        "h4_italic", font=(base_font, _s(11), "bold italic"), foreground=colors["fg"], spacing1=3, spacing3=2
    )

    # Inline formatting
    text_widget.tag_configure("bold", font=(base_font, _s(11), "bold"))
    text_widget.tag_configure("italic", font=(base_font, _s(11), "italic"))
    text_widget.tag_configure("bold_italic", font=(base_font, _s(11), "bold italic"))
    text_widget.tag_configure("strikethrough", font=(base_font, _s(11)), overstrike=True)

    # Code
    text_widget.tag_configure(
        "code", font=(mono_font, _s(10)), background=colors["code_bg"], foreground=colors["accent"]
    )

    text_widget.tag_configure(
        "codeblock",
        font=(mono_font, _s(10)),
        background=colors["code_bg"],
        lmargin1=12,
        lmargin2=12,
        rmargin=8,
        spacing1=4,
        spacing3=4,
    )

    # Links
    text_widget.tag_configure("link", foreground=colors["accent"], underline=True)
    text_widget.tag_bind("link", "<Enter>", lambda e: text_widget.config(cursor="hand2"))
    text_widget.tag_bind("link", "<Leave>", lambda e: text_widget.config(cursor=""))
    text_widget.tag_bind("link", "<Button-1>", _handle_link_click)

    # Lists
    text_widget.tag_configure("bullet", lmargin1=16, lmargin2=28, foreground=colors["fg"])

    text_widget.tag_configure("bullet_marker", foreground=colors["bullet"])

    text_widget.tag_configure("numbered", lmargin1=16, lmargin2=28, foreground=colors["fg"])

    # Blockquote
    text_widget.tag_configure(
        "blockquote", lmargin1=16, lmargin2=20, foreground=colors["blockquote"], font=(base_font, _s(11), "italic")
    )

    # =================================================================
    # Card-style message blocks with accent bars
    # =================================================================

    # User message card - left accent bar color
    text_widget.tag_configure("user_accent_bar", foreground=colors["user_accent"], font=(base_font, _s(11)))

    # User message label
    text_widget.tag_configure(
        "user_label", font=(base_font, _s(11), "bold"), foreground=colors["user_accent"], spacing1=0, spacing3=2
    )

    # User message content (colored background)
    text_widget.tag_configure(
        "user_message", background=colors["user_bg"], lmargin1=0, lmargin2=0, rmargin=8, spacing1=0, spacing3=0
    )

    # Assistant message card - left accent bar color
    text_widget.tag_configure("assistant_accent_bar", foreground=colors["assistant_accent"], font=(base_font, _s(11)))

    # Assistant message label
    text_widget.tag_configure(
        "assistant_label",
        font=(base_font, _s(11), "bold"),
        foreground=colors["assistant_accent"],
        spacing1=0,
        spacing3=2,
    )

    # Assistant message content (colored background)
    text_widget.tag_configure(
        "assistant_message",
        background=colors["assistant_bg"],
        lmargin1=0,
        lmargin2=0,
        rmargin=8,
        spacing1=0,
        spacing3=0,
    )

    # Card gap (transparent space between messages)
    text_widget.tag_configure(
        "card_gap", spacing1=4, spacing3=4, font=(base_font, _s(4))
    )  # Small font for minimal height

    # Normal text
    text_widget.tag_configure("normal", font=(base_font, _s(11)), foreground=colors["fg"])

    # Separator (only used within cards, not between them)
    text_widget.tag_configure("separator", foreground=colors.get("surface1", colors["border"]), spacing1=4, spacing3=4)

    # =================================================================
    # Thinking/Reasoning display - improved styling
    # =================================================================

    # Thinking header - clickable, yellow accent
    text_widget.tag_configure(
        "thinking_header", font=(base_font, _s(10), "bold"), foreground=colors["accent_yellow"], spacing1=4, spacing3=2
    )

    # Add cursor change on hover for thinking header
    text_widget.tag_bind("thinking_header", "<Enter>", lambda e: text_widget.config(cursor="hand2"))
    text_widget.tag_bind("thinking_header", "<Leave>", lambda e: text_widget.config(cursor=""))

    # Thinking content - improved contrast (use overlay0 instead of blockquote)
    text_widget.tag_configure(
        "thinking_content",
        font=(base_font, _s(10)),
        foreground=colors.get("overlay0", colors["blockquote"]),
        lmargin1=12,
        lmargin2=12,
        spacing1=2,
        spacing3=2,
    )

    # Thinking message role (for markdown-rendered thinking)
    text_widget.tag_configure("thinking_message", lmargin1=12, lmargin2=12, rmargin=8, spacing1=1, spacing3=2)

    # Thinking block background - visually distinct from answer area,
    # mirrors assistant_message layout but with darker background
    text_widget.tag_configure(
        "thinking_block_layout", background=colors["code_bg"], lmargin1=0, lmargin2=0, rmargin=8, spacing1=0, spacing3=0
    )

    # Separator between thinking and answer
    text_widget.tag_configure(
        "thinking_end_sep",
        foreground=colors.get("surface2", colors.get("overlay0", "#9399b2")),
        font=(base_font, _s(7)),
        spacing1=6,
        spacing3=4,
    )

    # =================================================================
    # Message action icons (edit, rerun, more)
    # =================================================================

    # Muted by default — accent highlight on hover is handled per-instance
    text_widget.tag_configure(
        "action_icon", font=(base_font, _s(10)), foreground=colors.get("surface1", colors.get("overlay0", "#585b70"))
    )

    # Hover-highlighted variant
    text_widget.tag_configure("action_icon_hover", font=(base_font, _s(10)), foreground=colors.get("accent", "#89b4fa"))

    # =================================================================
    # LaTeX math display
    # =================================================================

    # Inline math ($...$) - italic with accent color
    text_widget.tag_configure(
        "latex_inline", font=(base_font, _s(11), "italic"), foreground=colors.get("accent_yellow", colors["accent"])
    )

    # Display math ($$...$$) - left-aligned block with code font for alignment
    text_widget.tag_configure(
        "latex_block",
        font=(mono_font, _s(11)),
        foreground=colors.get("accent_yellow", colors["accent"]),
        background=colors["code_bg"],
        justify="left",
        lmargin1=24,
        lmargin2=24,
        rmargin=24,
        spacing1=4,
        spacing3=4,
    )

    # Bold/italic variants for display math wrapped in markdown formatting
    # e.g. **$$...$$** → latex_block_bold
    text_widget.tag_configure(
        "latex_block_bold",
        font=(mono_font, _s(11), "bold"),
        foreground=colors.get("accent_yellow", colors["accent"]),
        background=colors["code_bg"],
        justify="left",
        lmargin1=24,
        lmargin2=24,
        rmargin=24,
        spacing1=4,
        spacing3=4,
    )

    text_widget.tag_configure(
        "latex_block_italic",
        font=(mono_font, _s(11), "italic"),
        foreground=colors.get("accent_yellow", colors["accent"]),
        background=colors["code_bg"],
        justify="left",
        lmargin1=24,
        lmargin2=24,
        rmargin=24,
        spacing1=4,
        spacing3=4,
    )

    text_widget.tag_configure(
        "latex_block_bold_italic",
        font=(mono_font, _s(11), "bold italic"),
        foreground=colors.get("accent_yellow", colors["accent"]),
        background=colors["code_bg"],
        justify="left",
        lmargin1=24,
        lmargin2=24,
        rmargin=24,
        spacing1=4,
        spacing3=4,
    )

    # Technical symbols font (center pieces) - used for characters
    # that are missing or look poor in monospaced fonts.
    text_widget.tag_configure(
        "latex_symbols", font=(_SYMBOL_FONT_FAMILY, _s(24)), foreground=colors.get("accent_yellow", colors["accent"])
    )

    # Raise thinking_block_layout above user_message/assistant_message so its background takes priority
    text_widget.tag_raise("thinking_block_layout")

    # Raise "sel" tag priority so text selection always shows over background colors
    text_widget.tag_raise("sel")


def _strip_inline_formatting(text: str) -> Tuple[str, Optional[str]]:
    """
    Remove markdown inline formatting markers and detect the formatting style.

    Returns:
        Tuple of (stripped_text, format_style) where format_style is one of:
        'bold_italic', 'bold', 'italic', or None
    """
    # Check for bold+italic first
    match = re.match(r"^\*\*\*(.+)\*\*\*$", text.strip())
    if match:
        return match.group(1), "bold_italic"

    match = re.match(r"^___(.+)___$", text.strip())
    if match:
        return match.group(1), "bold_italic"

    # Check for bold
    match = re.match(r"^\*\*(.+)\*\*$", text.strip())
    if match:
        return match.group(1), "bold"

    match = re.match(r"^__(.+)__$", text.strip())
    if match:
        return match.group(1), "bold"

    # Check for italic
    match = re.match(r"^\*([^\*]+)\*$", text.strip())
    if match:
        return match.group(1), "italic"

    match = re.match(r"^_([^_]+)_$", text.strip())
    if match:
        return match.group(1), "italic"

    # No formatting or mixed - strip all markers
    result = text
    result = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", result)
    result = re.sub(r"\*\*(.+?)\*\*", r"\1", result)
    result = re.sub(r"__(.+?)__", r"\1", result)
    result = re.sub(r"\*([^\*]+)\*", r"\1", result)
    result = re.sub(r"`([^`]+)`", r"\1", result)
    return result, None


def _strip_formatting_simple(text: str) -> str:
    """Strip inline formatting markers without detecting style (for tables)."""
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"\*([^\*]+)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text


def _extract_tables(text: str) -> Tuple[str, List[Tuple[int, List[List[str]]]]]:
    """
    Extract markdown tables from text and replace with placeholders.

    Returns:
        Tuple of (modified_text, list of (placeholder_line_index, table_data))
    """
    lines = text.split("\n")
    result_lines = []
    tables = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check if this looks like a table row (starts and ends with |)
        if stripped.startswith("|") and stripped.endswith("|"):
            table_rows = []
            table_start = len(result_lines)

            # Collect all consecutive table rows
            while i < len(lines):
                row_line = lines[i].strip()
                if not (row_line.startswith("|") and row_line.endswith("|")):
                    break

                # Parse cells (split by | and strip)
                cells = [c.strip() for c in row_line.split("|")[1:-1]]

                # Skip separator rows (containing only dashes/colons)
                if cells and all(re.match(r"^:?-+:?$", c) for c in cells):
                    i += 1
                    continue

                table_rows.append(cells)
                i += 1

            if table_rows:
                # Add placeholder and store table data
                placeholder = f"__TABLE_PLACEHOLDER_{len(tables)}__"
                result_lines.append(placeholder)
                tables.append((table_start, table_rows))
            continue

        result_lines.append(line)
        i += 1

    return "\n".join(result_lines), tables


def _extract_latex_display_blocks(text: str) -> Tuple[str, List[str]]:
    """
    Extract $$...$$ display math blocks from text and replace with placeholders.

    Returns:
        Tuple of (modified_text, list of latex_content_strings)
    """
    blocks = []

    def replace_block(match):
        content = match.group(1).strip()
        idx = len(blocks)
        blocks.append(content)
        return f"__LATEX_DISPLAY_{idx}__"

    # Match $$...$$ (may span multiple lines)
    modified = re.sub(r"\$\$(.+?)\$\$", replace_block, text, flags=re.DOTALL)
    return modified, blocks


def _preprocess_inline_latex(text: str) -> str:
    """
    Pre-convert ``$...$`` inline LaTeX to Unicode wrapped in sentinel markers.

    This **must** run BEFORE the markdown inline-formatting regex so that
    bold / italic / strikethrough patterns don't swallow raw LaTeX
    delimiters.  Sentinel markers (``\\x02 … \\x03``) let downstream
    insertion helpers apply the ``latex_inline`` styling tag to the
    converted segments while the surrounding text keeps its own tag.
    """

    def _replace(m):
        inner = m.group(1)
        # Skip currency-like patterns ($100, $3.50, $1,000) but NOT single
        # digits which are common in LaTeX math ($9$, $3$, $n$).
        if re.match(r"^\d{2,}[\d,]*\.?\d*$|^\d[\d,]*\.\d+$|^\d[\d,]+$", inner):
            return m.group(0)
        try:
            converted = latex_to_unicode(inner)
        except Exception:
            converted = inner
        return f"{_LATEX_SENTINEL_START}{converted}{_LATEX_SENTINEL_END}"

    return re.sub(
        r"(?<!\$)\$(?!\$)(\S(?:[^$]*?\S)?)\$(?!\$)",
        _replace,
        text,
    )


def _render_table(
    text_widget: tk.Text,
    table_data: List[List[str]],
    colors: Dict[str, str],
    role_tag: Optional[str] = None,
    block_tag: Optional[str] = None,
    line_prefix: str = "",
):
    """Render a markdown table to the text widget with proper box-drawing borders."""
    if not table_data:
        return

    def build_tags(*primary_tags):
        result = list(primary_tags)
        if role_tag:
            result.append(role_tag)
        if block_tag:
            result.append(block_tag)
        return tuple(result) if result else ("normal",)

    # Calculate column widths
    num_cols = max(len(row) for row in table_data)
    col_widths = [0] * num_cols

    for row in table_data:
        for j, cell in enumerate(row):
            if j < num_cols:
                col_widths[j] = max(col_widths[j], len(_strip_formatting_simple(cell)))

    # Ensure minimum column width
    col_widths = [max(w, 3) for w in col_widths]

    # Box-drawing characters
    # ┌─┬─┐  top border
    # │ │ │  row with data
    # ├─┼─┤  separator (after header)
    # │ │ │  row with data
    # └─┴─┘  bottom border

    # Build top border: ┌───┬───┬───┐
    top_parts = ["─" * (w + 2) for w in col_widths]
    top_border = "┌" + "┬".join(top_parts) + "┐"

    # Build header separator: ├───┼───┼───┤
    mid_parts = ["─" * (w + 2) for w in col_widths]
    mid_border = "├" + "┼".join(mid_parts) + "┤"

    # Build bottom border: └───┴───┴───┘
    bottom_parts = ["─" * (w + 2) for w in col_widths]
    bottom_border = "└" + "┴".join(bottom_parts) + "┘"

    # Insert top border
    text_widget.insert(tk.END, line_prefix, build_tags("normal"))
    text_widget.insert(tk.END, top_border + "\n", build_tags("codeblock"))

    # Render each row
    for row_idx, row in enumerate(table_data):
        # Pad row to have correct number of columns
        while len(row) < num_cols:
            row.append("")

        # Build row: │ cell1 │ cell2 │ cell3 │
        row_parts = []
        for col_idx, cell in enumerate(row):
            cell_text = _strip_formatting_simple(cell)
            padded = cell_text.ljust(col_widths[col_idx])
            row_parts.append(f" {padded} ")

        row_text = "│" + "│".join(row_parts) + "│"

        text_widget.insert(tk.END, line_prefix, build_tags("normal"))
        text_widget.insert(tk.END, row_text + "\n", build_tags("codeblock"))

        # Add separator after header row
        if row_idx == 0:
            text_widget.insert(tk.END, line_prefix, build_tags("normal"))
            text_widget.insert(tk.END, mid_border + "\n", build_tags("codeblock"))

    # Insert bottom border
    text_widget.insert(tk.END, line_prefix, build_tags("normal"))
    text_widget.insert(tk.END, bottom_border + "\n", build_tags("codeblock"))


def _apply_hanging_indent(text_widget: tk.Text, prefix_text: str, font_obj):
    """
    Apply a hanging indent to the current paragraph so wrapped lines
    align with the start of the content text (past the bullet/number marker).

    Args:
        text_widget: The tk.Text widget
        prefix_text: The full prefix string before content (e.g. "    • ")
        font_obj: A tkfont.Font instance for pixel measurement
    """
    # Calculate pixel width of the prefix
    if font_obj:
        try:
            lmargin2 = font_obj.measure(prefix_text)
        except Exception:
            lmargin2 = len(prefix_text) * 7  # fallback estimate
    else:
        lmargin2 = len(prefix_text) * 7

    # Get current line number
    current_pos = text_widget.index("end-1c")
    line_num = current_pos.split(".")[0]

    # Create/configure a tag keyed by the computed margin (reuse across same-width lines)
    tag_name = f"_hanging_{lmargin2}"
    text_widget.tag_configure(tag_name, lmargin2=lmargin2)

    # Apply to the entire current paragraph
    text_widget.tag_add(tag_name, f"{line_num}.0", f"{line_num}.end")
    # Raise priority so it overrides message block tags (user_message/assistant_message)
    # which set lmargin2=0
    text_widget.tag_raise(tag_name)


def render_markdown(
    text: str,
    text_widget: tk.Text,
    colors: Dict[str, str],
    wrap: bool = True,
    as_role: Optional[str] = None,
    enable_emojis: bool = True,
    block_tag: Optional[str] = None,
    line_prefix: str = "",
):
    """
    Render markdown text to a Tkinter Text widget with formatting.

    Args:
        text: The markdown text to render
        text_widget: The Tkinter Text widget to render into
        colors: Color scheme dictionary
        wrap: Whether to enable word wrapping
        as_role: Optional role ('user', 'assistant', or 'thinking') for message styling
        enable_emojis: Whether to render emojis as images (Windows only)
        block_tag: Optional additional tag to apply to all content (for card backgrounds)
        line_prefix: Optional string to prepend to each line (preserves indentation)
    """
    # Setup tags if not already done
    setup_text_tags(text_widget, colors)

    # Configure wrap mode
    text_widget.configure(wrap=tk.WORD if wrap else tk.NONE)

    # Pre-process: Extract and render tables first
    text, table_blocks = _extract_tables(text)

    # Pre-process: Extract $$...$$ display math blocks (may span lines)
    text, latex_display_blocks = _extract_latex_display_blocks(text)

    lines = text.split("\n")
    in_code_block = False
    code_block_lines = []

    # Create a font object for measuring prefix widths (hanging indent)
    try:
        widget_font = text_widget.cget("font")
        _font_obj = tkfont.Font(font=widget_font)
    except Exception:
        try:
            family, size = get_tk_font(11)[:2]
            _font_obj = tkfont.Font(family=family, size=size)
        except Exception:
            _font_obj = None

    # Apply role-based styling
    role_tag = None
    if as_role == "user":
        role_tag = "user_message"
    elif as_role == "assistant":
        role_tag = "assistant_message"
    elif as_role == "thinking":
        role_tag = "thinking_message"

    def build_tags(*primary_tags):
        """Build tag tuple including role_tag and block_tag if present."""
        result = list(primary_tags)
        if role_tag:
            result.append(role_tag)
        if block_tag:
            result.append(block_tag)
        return tuple(result) if result else None

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Code block handling
        if stripped.startswith("```"):
            if in_code_block:
                # End code block - render accumulated lines
                if code_block_lines:
                    # Add newline before code block if there's preceding content
                    if text_widget.index(tk.END) != "1.0":
                        text_widget.insert(tk.END, "\n", build_tags("normal"))
                    # Apply indentation to code block lines
                    code_lines_prefixed = [line_prefix + l for l in code_block_lines]
                    code_text = "\n".join(code_lines_prefixed)
                    tags = build_tags("codeblock")
                    # Don't render emojis in code blocks
                    text_widget.insert(tk.END, code_text + "\n", tags)
                code_block_lines = []
                in_code_block = False
            else:
                # Start code block (ignore language identifier)
                in_code_block = True
            continue

        if in_code_block:
            code_block_lines.append(line)
            continue

        # Add newline between lines (except first)
        if text_widget.index(tk.END) != "1.0" and i > 0:
            newline_tags = build_tags("normal")
            text_widget.insert(tk.END, "\n", newline_tags)

        # Empty line - minimal spacing
        if not stripped:
            continue

        # Check for table placeholder
        table_match = re.match(r"^__TABLE_PLACEHOLDER_(\d+)__$", stripped)
        if table_match:
            table_idx = int(table_match.group(1))
            if table_idx < len(table_blocks):
                _, table_data = table_blocks[table_idx]
                _render_table(text_widget, table_data, colors, role_tag, block_tag, line_prefix)
            continue

        # Check for LaTeX display block placeholder (optionally wrapped in bold/italic markers)
        # Matches: __LATEX_DISPLAY_0__, **__LATEX_DISPLAY_0__**, *__LATEX_DISPLAY_0__*,
        #          ***__LATEX_DISPLAY_0__***, ___...___, __...__
        latex_match = re.match(r"^(\*{1,3}|_{1,3})?__LATEX_DISPLAY_(\d+)__(\*{1,3}|_{1,3})?$", stripped)
        if latex_match:
            latex_idx = int(latex_match.group(2))
            if latex_idx < len(latex_display_blocks):
                latex_content = latex_display_blocks[latex_idx]
                try:
                    converted = latex_to_unicode(latex_content)
                except Exception:
                    converted = latex_content

                # Determine formatting from surrounding markers
                open_marker = latex_match.group(1) or ""
                marker_len = len(open_marker)
                if marker_len == 3:
                    latex_tag = "latex_block_bold_italic"
                elif marker_len == 2:
                    latex_tag = "latex_block_bold"
                elif marker_len == 1:
                    latex_tag = "latex_block_italic"
                else:
                    latex_tag = "latex_block"

                # Need to handle each line separately to apply prefix correctly
                converted_lines = converted.split("\n")
                for idx, line_str in enumerate(converted_lines):
                    if idx > 0:
                        text_widget.insert(tk.END, "\n", build_tags("normal"))

                    if line_prefix:
                        text_widget.insert(tk.END, line_prefix, build_tags("normal"))

                    tags = build_tags(latex_tag)

                    # Technical characters that need Segoe UI Symbol
                    symbol_chars = "⎨⎬"

                    for char in line_str:
                        if char in symbol_chars:
                            char_tags = tuple([*list(tags), "latex_symbols"])
                            _insert_with_emojis(text_widget, char, char_tags, False)
                        else:
                            _insert_with_emojis(text_widget, char, tags, False)
            continue

        # Insert prefix for this line
        if line_prefix:
            prefix_tags = build_tags("normal")
            text_widget.insert(tk.END, line_prefix, prefix_tags)

        # Headers
        if stripped.startswith("#"):
            level = 0
            for char in stripped:
                if char == "#":
                    level += 1
                else:
                    break

            if level <= 6 and len(stripped) > level and stripped[level] == " ":
                header_text = _preprocess_inline_latex(stripped[level + 1 :])
                content, format_style = _strip_inline_formatting(header_text)
                base_tag = f"h{min(level, 4)}"

                # Use italic header tag if italic formatting detected
                if format_style in ("italic", "bold_italic"):
                    tag = f"{base_tag}_italic"
                else:
                    tag = base_tag

                tags = build_tags(tag)
                _insert_with_latex_segments(text_widget, content, tags, enable_emojis)
                continue

        # Blockquote
        if stripped.startswith(">"):
            content = _preprocess_inline_latex(stripped[1:].strip())
            tags = build_tags("blockquote")
            _insert_with_latex_segments(text_widget, "│ " + content, tags, enable_emojis)
            continue

        # Bullet points
        if stripped.startswith("- ") or stripped.startswith("* "):
            content = stripped[2:]
            # Calculate indentation from original line
            indent_len = len(line) - len(line.lstrip())
            indent_str = " " * indent_len

            # Build the prefix string for hanging indent measurement
            bullet_prefix = f"{line_prefix}{indent_str}  • "

            # Insert bullet marker with indentation
            tags = build_tags("bullet_marker")
            text_widget.insert(tk.END, f"{indent_str}  • ", tags)
            # Insert content with inline formatting
            _render_inline(content, text_widget, colors, role_tag, enable_emojis, block_tag)
            # Apply hanging indent so wrapped lines align with content start
            _apply_hanging_indent(text_widget, bullet_prefix, _font_obj)
            continue

        # Numbered list
        match = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if match:
            num, content = match.groups()
            # Calculate indentation from original line
            indent_len = len(line) - len(line.lstrip())
            indent_str = " " * indent_len

            # Build the prefix string for hanging indent measurement
            num_prefix = f"{line_prefix}{indent_str}  {num}. "

            tags = build_tags("numbered")
            text_widget.insert(tk.END, f"{indent_str}  {num}. ", tags)
            _render_inline(content, text_widget, colors, role_tag, enable_emojis, block_tag)
            # Apply hanging indent so wrapped lines align with content start
            _apply_hanging_indent(text_widget, num_prefix, _font_obj)
            continue

        # Horizontal rule
        if re.match(r"^[-*_]{3,}$", stripped):
            tags = build_tags("separator")
            text_widget.insert(tk.END, "─" * 40, tags)
            continue

        # Regular paragraph with inline formatting
        _render_inline(line, text_widget, colors, role_tag, enable_emojis, block_tag)

    # Flush any remaining code block
    if in_code_block and code_block_lines:
        code_lines_prefixed = [line_prefix + l for l in code_block_lines]
        code_text = "\n".join(code_lines_prefixed)
        tags = build_tags("codeblock")
        # Don't render emojis in code blocks
        text_widget.insert(tk.END, code_text + "\n", tags)


def _insert_with_emojis(
    text_widget: tk.Text, text: str, tags: Optional[Tuple[str, ...]] = None, enable_emojis: bool = True
):
    """
    Insert text into a Text widget, optionally rendering emojis as images.

    On Windows, this replaces emoji characters with inline PNG images
    for proper color emoji display. On other platforms or if the emoji
    renderer is not available, falls back to plain text insertion.

    Args:
        text_widget: The tk.Text widget
        text: Text to insert
        tags: Tags to apply to the text
        enable_emojis: Whether to render emojis as images (default True)
    """
    # Special handling for links (don't render emojis inside link URLs)
    link_url = None
    if tags:
        for tag in tags:
            if tag.startswith("url_"):
                link_url = tag[4:]
                break

    # Only use emoji rendering on Windows and if available
    use_emoji_renderer = (
        enable_emojis
        and HAVE_EMOJI_RENDERER
        and sys.platform == "win32"
        and get_emoji_renderer is not None
        and not link_url  # Check if this is a link URL segment
    )

    if use_emoji_renderer:
        try:
            renderer = get_emoji_renderer()
            renderer.insert_text_with_emojis(text_widget, text, tags)
        except Exception:
            # Fallback on any error
            text_widget.insert(tk.END, text, tags)
    else:
        text_widget.insert(tk.END, text, tags)

    # Bind click event if it's a link
    if link_url:
        # We need to bind to the specific tag that contains the URL info
        # But tk.Text bindings are per-tag.
        # We can't bind to "url_..." because it's dynamic.
        # Instead, we rely on the 'link' tag we added, and this helper doesn't do the binding.
        # The binding needs to be generic on the 'link' tag in setup_text_tags,
        # but that can't access the URL unless we inspect the tags at the click position.

        # Binding is already done in setup_text_tags for 'link' tag class?
        # No, we need a way to open the specific URL.

        def open_specific_url(event=None, u=link_url):
            webbrowser.open(u)

        # Create a unique tag for this specific link instance to bind the click
        # This is a bit heavy but reliable.
        # Alternatively, use the global 'link' tag binding and find the url_ tag at current index.
        pass


def _merge_latex_tags(
    base_tags: Optional[Tuple[str, ...]],
    latex_tag: str,
) -> Tuple[str, ...]:
    """Replace the primary formatting tag with *latex_tag*, keeping structural tags.

    ``build_tags()`` always puts the formatting tag first (e.g. ``"bold"``),
    followed by role_tag and block_tag.  We swap the first element so that
    LaTeX segments receive ``latex_inline`` styling while structural tags
    (``user_message``, ``assistant_message``, …) are preserved.
    """
    if not base_tags:
        return (latex_tag,)
    return (latex_tag, *base_tags[1:])


def _insert_with_latex_segments(
    text_widget: tk.Text,
    text: str,
    base_tags: Optional[Tuple[str, ...]] = None,
    enable_emojis: bool = True,
):
    """Insert *text*, applying ``latex_inline`` to sentinel-wrapped segments.

    Sentinel markers (``\\x02 … \\x03``) are placed by
    :func:`_preprocess_inline_latex`.  Segments **outside** sentinels use
    *base_tags*; sentinel-wrapped segments use ``latex_inline`` plus any
    structural tags inherited from *base_tags*.

    When no sentinels are present the function falls through to
    :func:`_insert_with_emojis` with zero overhead.
    """
    if _LATEX_SENTINEL_START not in text:
        # Fast path – no LaTeX segments at all
        _insert_with_emojis(text_widget, text, base_tags, enable_emojis)
        return

    # Split while keeping sentinel-wrapped groups as separate elements
    parts = re.split(
        f"({re.escape(_LATEX_SENTINEL_START)}[^{re.escape(_LATEX_SENTINEL_END)}]+{re.escape(_LATEX_SENTINEL_END)})",
        text,
    )

    for part in parts:
        if not part:
            continue
        if part.startswith(_LATEX_SENTINEL_START) and part.endswith(_LATEX_SENTINEL_END):
            latex_content = part[1:-1]
            latex_tags = _merge_latex_tags(base_tags, "latex_inline")
            _insert_with_emojis(text_widget, latex_content, latex_tags, enable_emojis)
        else:
            _insert_with_emojis(text_widget, part, base_tags, enable_emojis)


def _render_inline(
    text: str,
    text_widget: tk.Text,
    colors: Dict[str, str],
    role_tag: Optional[str] = None,
    enable_emojis: bool = True,
    block_tag: Optional[str] = None,
):
    """Render inline markdown formatting (bold, italic, code) with emoji support."""

    # Pre-convert $...$ inline LaTeX to Unicode (sentinel-wrapped) BEFORE
    # the markdown formatting regex runs, so bold/italic don't swallow
    # raw LaTeX delimiters.  Standalone sentinels are then caught by the
    # combined regex below and tagged as latex_inline.
    text = _preprocess_inline_latex(text)

    def build_tags(*primary_tags):
        """Build tag tuple including role_tag and block_tag if present."""
        result = list(primary_tags)
        if role_tag:
            result.append(role_tag)
        if block_tag:
            result.append(block_tag)
        return tuple(result) if result else ("normal",)

    # Pattern for inline elements
    # Order matters: check bold+italic first, then bold, then italic, then code, then strikethrough, then links
    patterns = [
        (r"\*\*\*(.+?)\*\*\*", "bold_italic"),  # ***text***
        (r"___(.+?)___", "bold_italic"),  # ___text___
        (r"\*\*(.+?)\*\*", "bold"),  # **text**
        (r"__(.+?)__", "bold"),  # __text__
        (r"\*(.+?)\*", "italic"),  # *text*
        (r"_(.+?)_", "italic"),  # _text_ (word boundary aware)
        (r"`([^`]+)`", "code"),  # `code`
        (r"~~(.+?)~~", "strikethrough"),  # ~~text~~
        (r"\[([^\]]+)\]\(([^)]+)\)", "link"),  # [text](url)
    ]

    # Build a combined pattern to find all matches in order.
    # Inline LaTeX has already been pre-processed into sentinel-wrapped
    # Unicode by _preprocess_inline_latex(), so we match \x02…\x03 here.
    combined = (
        r"(\*\*\*.+?\*\*\*|___.+?___|"
        r"\*\*.+?\*\*|__.+?__|"
        r"\*[^\*]+\*|(?<![a-zA-Z])_[^_]+_(?![a-zA-Z])|"
        r"`[^`]+`|~~.+?~~|"
        r"\[[^\]]+\]\([^)]+\)|"
        r"\x02[^\x03]+\x03)"
    )

    pos = 0
    for match in re.finditer(combined, text):
        # Insert any text before this match
        if match.start() > pos:
            plain_text = text[pos : match.start()]
            tags = build_tags("normal")
            _insert_with_latex_segments(text_widget, plain_text, tags, enable_emojis)

        matched_text = match.group(0)
        content = None
        tag = "normal"

        # Determine which pattern matched
        if matched_text.startswith("***") and matched_text.endswith("***"):
            content = matched_text[3:-3]
            tag = "bold_italic"
        elif matched_text.startswith("___") and matched_text.endswith("___"):
            content = matched_text[3:-3]
            tag = "bold_italic"
        elif matched_text.startswith("**") and matched_text.endswith("**"):
            content = matched_text[2:-2]
            tag = "bold"
        elif matched_text.startswith("__") and matched_text.endswith("__"):
            content = matched_text[2:-2]
            tag = "bold"
        elif matched_text.startswith("`") and matched_text.endswith("`"):
            content = matched_text[1:-1]
            tag = "code"
        elif matched_text.startswith("~~") and matched_text.endswith("~~"):
            content = matched_text[2:-2]
            tag = "strikethrough"
        elif matched_text.startswith("[") and matched_text.endswith(")"):
            # Parse link [text](url)
            match_link = re.match(r"\[([^\]]+)\]\(([^)]+)\)", matched_text)
            if match_link:
                content = match_link.group(1)
                url = match_link.group(2)
                tag = "link"
                # We need to bind a unique tag for this URL
                # Since we can't easily modify the 'tags' tuple later in _insert_with_emojis to add a unique callback,
                # we'll handle insertion directly here for links?
                # No, _insert_with_emojis expects content.

                # We will add a dynamic tag "url_{url}"
                # But tkinter tags with spaces or odd chars might be an issue? URL encoded?
                # Let's just use the url if safe, or a safe hash?
                # Tkinter tags are strings.

                # We'll allow spaces in tags? yes.
                url_tag = f"url_{url}"
                extra_tag = url_tag
        elif matched_text.startswith(_LATEX_SENTINEL_START) and matched_text.endswith(_LATEX_SENTINEL_END):
            # Pre-processed inline LaTeX (sentinel-wrapped by _preprocess_inline_latex)
            content = matched_text[1:-1]
            tag = "latex_inline"
        elif matched_text.startswith("*") and matched_text.endswith("*"):
            content = matched_text[1:-1]
            tag = "italic"
        elif matched_text.startswith("_") and matched_text.endswith("_"):
            content = matched_text[1:-1]
            tag = "italic"

        if content:
            if tag == "link" and "extra_tag" in locals():
                tags = build_tags(tag, extra_tag)
                # Cleanup local variable for next iteration
                del extra_tag
            else:
                tags = build_tags(tag)
            _insert_with_latex_segments(text_widget, content, tags, enable_emojis)

        pos = match.end()

    # Insert any remaining text
    if pos < len(text):
        remaining = text[pos:]
        tags = build_tags("normal")
        _insert_with_latex_segments(text_widget, remaining, tags, enable_emojis)


def markdown_to_html(text: str) -> str:
    """
    Convert markdown text to basic HTML for clipboard (CF_HTML).

    Handles: headers, bold, italic, code, code blocks, bullet lists,
    numbered lists, blockquotes, links, horizontal rules, paragraphs.
    """
    import html as html_module

    lines = text.split("\n")
    result = []
    in_code_block = False
    code_block_lines = []
    code_lang = ""
    in_list = False  # Track if we're inside a <ul> or <ol>
    list_type = None  # "ul" or "ol"
    in_table = False
    table_rows = []

    def process_inline(line_text: str) -> str:
        """Process inline markdown formatting."""
        # Escape HTML entities first
        t = html_module.escape(line_text)
        # Bold+italic (***text*** or ___text___)
        t = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", t)
        t = re.sub(r"___(.+?)___", r"<strong><em>\1</em></strong>", t)
        # Bold (**text** or __text__)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"__(.+?)__", r"<strong>\1</strong>", t)
        # Italic (*text* or _text_)
        t = re.sub(r"\*([^\*]+)\*", r"<em>\1</em>", t)
        t = re.sub(r"(?<![a-zA-Z])_([^_]+)_(?![a-zA-Z])", r"<em>\1</em>", t)
        # Strikethrough
        t = re.sub(r"~~(.+?)~~", r"<s>\1</s>", t)
        # Inline code
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        # Links [text](url)
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
        return t

    def close_list():
        nonlocal in_list, list_type
        if in_list:
            result.append(f"</{list_type}>")
            in_list = False
            list_type = None

    def close_table():
        nonlocal in_table, table_rows
        if not in_table:
            return

        html_rows = []
        has_separator = False
        header_row_index = -1

        for i, row in enumerate(table_rows):
            clean_row = row.strip()
            if re.match(r"^\|(?:\s*:?-+:?\s*\|)+$", clean_row):
                has_separator = True
                header_row_index = i - 1
                break

        html_rows.append(
            '<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; margin: 10px 0;">'
        )

        thead_written = False
        tbody_open = False

        for i, row in enumerate(table_rows):
            clean_row = row.strip()
            if has_separator and re.match(r"^\|(?:\s*:?-+:?\s*\|)+$", clean_row):
                continue

            cols = [c.strip() for c in clean_row.split("|")[1:-1]]
            is_header = has_separator and i == header_row_index

            row_html = []
            row_html.append("  <tr>")
            for col in cols:
                processed_val = process_inline(col)
                if is_header:
                    row_html.append(f"    <th>{processed_val}</th>")
                else:
                    row_html.append(f"    <td>{processed_val}</td>")
            row_html.append("  </tr>")

            if is_header:
                html_rows.append("<thead>")
                html_rows.extend(row_html)
                html_rows.append("</thead>")
                thead_written = True
            else:
                if not tbody_open:
                    if thead_written:
                        html_rows.append("<tbody>")
                    tbody_open = True
                html_rows.extend(row_html)

        if tbody_open:
            html_rows.append("</tbody>")

        html_rows.append("</table>")
        result.append("\n".join(html_rows))

        in_table = False
        table_rows = []

    for line in lines:
        stripped = line.strip()

        # Code block toggle
        if stripped.startswith("```"):
            close_table()
            if in_code_block:
                # End code block
                code_text = html_module.escape("\n".join(code_block_lines))
                result.append(f"<pre><code>{code_text}</code></pre>")
                code_block_lines = []
                in_code_block = False
            else:
                close_list()
                in_code_block = True
                code_lang = stripped[3:].strip()
            continue

        if in_code_block:
            code_block_lines.append(line)
            continue

        # Table row match
        if stripped.startswith("|") and stripped.endswith("|"):
            close_list()
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(stripped)
            continue

        # Empty line
        if not stripped:
            close_table()
            close_list()
            continue

        # Headers
        header_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if header_match:
            close_table()
            close_list()
            level = len(header_match.group(1))
            content = process_inline(header_match.group(2))
            result.append(f"<h{level}>{content}</h{level}>")
            continue

        # Horizontal rule
        if re.match(r"^[-*_]{3,}$", stripped):
            close_table()
            close_list()
            result.append("<hr>")
            continue

        # Blockquote
        if stripped.startswith("> "):
            close_table()
            close_list()
            content = process_inline(stripped[2:])
            result.append(f"<blockquote>{content}</blockquote>")
            continue

        # Bullet list
        bullet_match = re.match(r"^[-*+]\s+(.+)$", stripped)
        if bullet_match:
            close_table()
            if not in_list or list_type != "ul":
                close_list()
                result.append("<ul>")
                in_list = True
                list_type = "ul"
            content = process_inline(bullet_match.group(1))
            result.append(f"<li>{content}</li>")
            continue

        # Numbered list
        num_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if num_match:
            close_table()
            if not in_list or list_type != "ol":
                close_list()
                result.append("<ol>")
                in_list = True
                list_type = "ol"
            content = process_inline(num_match.group(1))
            result.append(f"<li>{content}</li>")
            continue

        # Regular paragraph
        close_table()
        close_list()
        content = process_inline(stripped)
        result.append(f"<p>{content}</p>")

    # Close any remaining open table
    close_table()

    # Close any remaining open list
    close_list()

    # Close any unclosed code block
    if in_code_block and code_block_lines:
        import html as html_module

        code_text = html_module.escape("\n".join(code_block_lines))
        result.append(f"<pre><code>{code_text}</code></pre>")

    return "\n".join(result)


def copy_as_html_to_clipboard(markdown_text: str, root=None) -> bool:
    """
    Convert markdown to HTML and copy to clipboard as CF_HTML format.

    This uses the Windows CF_HTML clipboard format which applications
    like Microsoft Word recognize for rich text paste.

    Falls back to plain HTML text copy on non-Windows or on failure.

    Args:
        markdown_text: Raw markdown text to convert and copy
        root: Optional Tk root for fallback clipboard

    Returns:
        True if successful
    """
    html_body = markdown_to_html(markdown_text)

    if sys.platform != "win32":
        if sys.platform.startswith("linux"):
            # Linux/Wayland: offer text/html via wl-copy for rich paste targets.
            # Plain-text-only targets should use "Copy as Markdown" instead.
            from ..platform.clipboard import copy_rich_text

            full_html = f"<html><body>{html_body}</body></html>"
            if copy_rich_text(full_html, markdown_text):
                return True
            # wl-copy is unavailable or rejected the rich offer: preserve the
            # existing plain-markdown fallback rather than failing the action.
            return copy_to_clipboard(markdown_text, root)
        return copy_to_clipboard(html_body, root)

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        # Configure ctypes argtypes and restypes for 64-bit compatibility
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p

        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p

        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.restype = ctypes.c_bool

        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.restype = ctypes.c_void_p

        user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
        user32.RegisterClipboardFormatW.restype = ctypes.c_uint

        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_bool

        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = ctypes.c_bool

        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = ctypes.c_bool

        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p

        # Build CF_HTML payload with required header
        # The header contains byte offsets that must be precise
        html_template = (
            "Version:0.9\r\n"
            "StartHTML:{start_html:010d}\r\n"
            "EndHTML:{end_html:010d}\r\n"
            "StartFragment:{start_frag:010d}\r\n"
            "EndFragment:{end_frag:010d}\r\n"
            "<html><body>\r\n"
            "<!--StartFragment-->"
            "{fragment}"
            "<!--EndFragment-->\r\n"
            "</body></html>"
        )

        # Calculate header length first (with placeholder zeros)
        dummy = html_template.format(start_html=0, end_html=0, start_frag=0, end_frag=0, fragment="")
        header_len = len(dummy.split("<!--StartFragment-->")[0].encode("utf-8"))
        # Actually we need to compute offsets on the final encoded string

        prefix = "<html><body>\r\n<!--StartFragment-->"
        suffix = "<!--EndFragment-->\r\n</body></html>"

        # Build with placeholder header to measure
        header_placeholder = (
            "Version:0.9\r\n"
            "StartHTML:0000000000\r\n"
            "EndHTML:0000000000\r\n"
            "StartFragment:0000000000\r\n"
            "EndFragment:0000000000\r\n"
        )

        header_bytes = header_placeholder.encode("utf-8")
        prefix_bytes = prefix.encode("utf-8")
        fragment_bytes = html_body.encode("utf-8")
        suffix_bytes = suffix.encode("utf-8")

        start_html = len(header_bytes)
        start_frag = start_html + len(prefix_bytes)
        end_frag = start_frag + len(fragment_bytes)
        end_html = end_frag + len(suffix_bytes)

        header = (
            "Version:0.9\r\n"
            f"StartHTML:{start_html:010d}\r\n"
            f"EndHTML:{end_html:010d}\r\n"
            f"StartFragment:{start_frag:010d}\r\n"
            f"EndFragment:{end_frag:010d}\r\n"
        )

        cf_html_data = header.encode("utf-8") + prefix_bytes + fragment_bytes + suffix_bytes

        # Use Win32 API to set clipboard
        CF_HTML = user32.RegisterClipboardFormatW("HTML Format")

        GMEM_MOVEABLE = 0x0002

        if not user32.OpenClipboard(0):
            print("[CF_HTML Error] Failed to open clipboard.")
            return copy_to_clipboard(html_body, root)

        try:
            user32.EmptyClipboard()

            # Allocate global memory
            size = len(cf_html_data) + 1  # +1 for null terminator
            h_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
            if not h_global:
                print("[CF_HTML Error] GlobalAlloc failed.")
                return False

            # Lock and copy data
            p_global = kernel32.GlobalLock(h_global)
            if not p_global:
                print("[CF_HTML Error] GlobalLock failed.")
                kernel32.GlobalFree(h_global)
                return False

            ctypes.memmove(p_global, cf_html_data, len(cf_html_data))
            # Null terminate
            ctypes.memset(p_global + len(cf_html_data), 0, 1)
            kernel32.GlobalUnlock(h_global)

            # Set clipboard data
            result = user32.SetClipboardData(CF_HTML, h_global)

            # Also set plain text (CF_UNICODETEXT = 13) so Ctrl+V works everywhere
            plain_text = markdown_text
            text_bytes = plain_text.encode("utf-16-le") + b"\x00\x00"
            h_text = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(text_bytes))
            if h_text:
                p_text = kernel32.GlobalLock(h_text)
                if p_text:
                    ctypes.memmove(p_text, text_bytes, len(text_bytes))
                    kernel32.GlobalUnlock(h_text)
                    user32.SetClipboardData(13, h_text)  # 13 = CF_UNICODETEXT

            return bool(result)

        finally:
            user32.CloseClipboard()

    except Exception as e:
        print(f"[CF_HTML Error] {e}")
        # Fallback: copy HTML as plain text
        return copy_to_clipboard(html_body, root)


def copy_as_plaintext(markdown_text: str, root=None) -> bool:
    """Copy markdown text as plain text (stripped of formatting) to clipboard."""
    from ..utils import strip_markdown

    plain = strip_markdown(markdown_text)
    return copy_to_clipboard(plain, root)


def hide_from_taskbar(window):
    """
    Remove the window from the taskbar on Windows.
    Uses GWL_EXSTYLE to set WS_EX_TOOLWINDOW and remove WS_EX_APPWINDOW.

    Args:
        window: The Tkinter or CTk window instance
    """
    if sys.platform == "win32" and _user32:
        try:
            # Get the window handle (HWND)
            # For Tkinter/CTkToplevel, we need the wrapper's parent sometimes
            # But winfo_id() usually returns the HWND of the inner window
            # CTk creates a frame inside a toplevel, so we might need the parent
            try:
                hwnd = window.winfo_id()
                # Check if we need to get parent (for some CTk setups)
                parent_hwnd = _user32.GetParent(hwnd)
                if parent_hwnd != 0:
                    hwnd = parent_hwnd
            except Exception:
                hwnd = window.winfo_id()

            # Modify the style
            style = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            style = style & ~_WS_EX_APPWINDOW
            style = style | _WS_EX_TOOLWINDOW
            _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style)
        except Exception as e:
            print(f"Error hiding from taskbar: {e}")


def get_tk_text_for_ctk_frame(parent_frame, colors: Union[Dict[str, str], ThemeColors], **kwargs) -> tk.Text:
    """
    Create a tk.Text widget properly styled to look good inside a CTkFrame.

    This helper creates a tk.Text with theme-appropriate colors and styling
    that visually integrates with CustomTkinter frames.

    Args:
        parent_frame: A CTkFrame or tk.Frame to place the text widget in
        colors: Color scheme dict or ThemeColors dataclass
        **kwargs: Additional arguments passed to tk.Text

    Returns:
        Configured tk.Text widget
    """
    # Get color values
    if hasattr(colors, "__dataclass_fields__"):
        bg = colors.text_bg
        fg = colors.fg
        insert_bg = colors.fg
        select_bg = colors.accent
    else:
        bg = colors.get("text_bg", "#1e1e2e")
        fg = colors.get("fg", "#cdd6f4")
        insert_bg = fg
        select_bg = colors.get("accent", "#89b4fa")

    # Default font
    if sys.platform == "win32":
        font = get_tk_font(11)
    else:
        font = ("DejaVu Sans", 11)

    # Merge with provided kwargs
    text_kwargs = {
        "wrap": tk.WORD,
        "font": font,
        "bg": bg,
        "fg": fg,
        "insertbackground": insert_bg,
        "selectbackground": select_bg,
        "relief": tk.FLAT,
        "highlightthickness": 0,
        "borderwidth": 0,
        "padx": 12,
        "pady": 12,
    }
    text_kwargs.update(kwargs)

    return tk.Text(parent_frame, **text_kwargs)
