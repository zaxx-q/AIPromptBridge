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
import webbrowser
import tkinter as tk
from tkinter import font as tkfont
from typing import Optional, Dict, Union, Tuple, List

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
from .themes import (
    ThemeRegistry, ThemeColors,
    get_color_scheme as _get_color_scheme,
    is_dark_mode as _is_dark_mode,
    get_ctk_font
)

# Import emoji renderer
try:
    from .emoji_renderer import get_emoji_renderer, EmojiRenderer, HAVE_PIL
    HAVE_EMOJI_RENDERER = HAVE_PIL
except ImportError:
    HAVE_EMOJI_RENDERER = False
    get_emoji_renderer = None

# Import LaTeX renderer
from .latex_renderer import latex_to_unicode, extract_latex_blocks


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


def copy_to_clipboard(text: str, root = None) -> bool:
    """
    Cross-platform clipboard copy.
    
    Works with both tk.Tk and ctk.CTk root windows.
    """
    try:
        if root:
            # Both tk.Tk and ctk.CTk have clipboard methods
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()  # Required for clipboard to persist
            return True
        
        # Fallback to subprocess method
        if sys.platform == 'win32':
            import subprocess
            process = subprocess.Popen(['clip'], stdin=subprocess.PIPE)
            process.communicate(text.encode('utf-16le'))
        elif sys.platform == 'darwin':
            import subprocess
            process = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
            process.communicate(text.encode('utf-8'))
        else:
            try:
                import subprocess
                process = subprocess.Popen(['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE)
                process.communicate(text.encode('utf-8'))
            except:
                process = subprocess.Popen(['xsel', '--clipboard', '--input'], stdin=subprocess.PIPE)
                process.communicate(text.encode('utf-8'))
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
    # Convert ThemeColors to dict if needed
    if hasattr(colors, '__dataclass_fields__'):
        color_dict = {
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
    
    # Configure text selection colors
    select_bg = colors.get("select_bg", colors.get("accent", "#89b4fa"))
    select_fg = colors.get("select_fg", colors.get("bg", "#1e1e2e"))
    text_widget.configure(selectbackground=select_bg, selectforeground=select_fg)
    
    # Get available fonts with Segoe UI Emoji fallback for Windows
    try:
        if sys.platform == 'win32':
            mono_font = "Consolas"
            base_font = "Segoe UI"
        else:
            mono_font = "DejaVu Sans Mono"
            base_font = "DejaVu Sans"
    except:
        mono_font = "TkFixedFont"
        base_font = "TkDefaultFont"
    
    # Headers
    text_widget.tag_configure("h1",
        font=(base_font, 16, "bold"),
        foreground=colors["header1"],
        spacing1=6, spacing3=4)
    
    text_widget.tag_configure("h2",
        font=(base_font, 14, "bold"),
        foreground=colors["header2"],
        spacing1=5, spacing3=3)
    
    text_widget.tag_configure("h3",
        font=(base_font, 12, "bold"),
        foreground=colors["header3"],
        spacing1=4, spacing3=2)
    
    text_widget.tag_configure("h4",
        font=(base_font, 11, "bold"),
        foreground=colors["fg"],
        spacing1=3, spacing3=2)

    # Header + italic combinations
    text_widget.tag_configure("h1_italic",
        font=(base_font, 16, "bold italic"),
        foreground=colors["header1"],
        spacing1=6, spacing3=4)

    text_widget.tag_configure("h2_italic",
        font=(base_font, 14, "bold italic"),
        foreground=colors["header2"],
        spacing1=5, spacing3=3)

    text_widget.tag_configure("h3_italic",
        font=(base_font, 12, "bold italic"),
        foreground=colors["header3"],
        spacing1=4, spacing3=2)

    text_widget.tag_configure("h4_italic",
        font=(base_font, 11, "bold italic"),
        foreground=colors["fg"],
        spacing1=3, spacing3=2)

    # Inline formatting
    text_widget.tag_configure("bold", font=(base_font, 11, "bold"))
    text_widget.tag_configure("italic", font=(base_font, 11, "italic"))
    text_widget.tag_configure("bold_italic", font=(base_font, 11, "bold italic"))
    text_widget.tag_configure("strikethrough", font=(base_font, 11), overstrike=True)
    
    # Code
    text_widget.tag_configure("code",
        font=(mono_font, 10),
        background=colors["code_bg"],
        foreground=colors["accent"])
    
    text_widget.tag_configure("codeblock",
        font=(mono_font, 10),
        background=colors["code_bg"],
        lmargin1=12, lmargin2=12, rmargin=8,
        spacing1=4, spacing3=4)

    # Links
    text_widget.tag_configure("link",
        foreground=colors["accent"],
        underline=True)
    text_widget.tag_bind("link", "<Enter>", lambda e: text_widget.config(cursor="hand2"))
    text_widget.tag_bind("link", "<Leave>", lambda e: text_widget.config(cursor=""))
    text_widget.tag_bind("link", "<Button-1>", _handle_link_click)
    
    # Lists
    text_widget.tag_configure("bullet",
        lmargin1=16, lmargin2=28,
        foreground=colors["fg"])
    
    text_widget.tag_configure("bullet_marker",
        foreground=colors["bullet"])
    
    text_widget.tag_configure("numbered",
        lmargin1=16, lmargin2=28,
        foreground=colors["fg"])
    
    # Blockquote
    text_widget.tag_configure("blockquote",
        lmargin1=16, lmargin2=20,
        foreground=colors["blockquote"],
        font=(base_font, 11, "italic"))
    
    # =================================================================
    # Card-style message blocks with accent bars
    # =================================================================
    
    # User message card - left accent bar color
    text_widget.tag_configure("user_accent_bar",
        foreground=colors["user_accent"],
        font=(base_font, 11))
    
    # User message label
    text_widget.tag_configure("user_label",
        font=(base_font, 11, "bold"),
        foreground=colors["user_accent"],
        spacing1=0, spacing3=2)
    
    # User message content (colored background)
    text_widget.tag_configure("user_message",
        background=colors["user_bg"],
        lmargin1=0, lmargin2=0, rmargin=8,
        spacing1=0, spacing3=0)
    
    # Assistant message card - left accent bar color
    text_widget.tag_configure("assistant_accent_bar",
        foreground=colors["assistant_accent"],
        font=(base_font, 11))
    
    # Assistant message label
    text_widget.tag_configure("assistant_label",
        font=(base_font, 11, "bold"),
        foreground=colors["assistant_accent"],
        spacing1=0, spacing3=2)
    
    # Assistant message content (colored background)
    text_widget.tag_configure("assistant_message",
        background=colors["assistant_bg"],
        lmargin1=0, lmargin2=0, rmargin=8,
        spacing1=0, spacing3=0)
    
    # Card gap (transparent space between messages)
    text_widget.tag_configure("card_gap",
        spacing1=4, spacing3=4,
        font=(base_font, 4))  # Small font for minimal height
    
    # Normal text
    text_widget.tag_configure("normal",
        font=(base_font, 11),
        foreground=colors["fg"])
    
    # Separator (only used within cards, not between them)
    text_widget.tag_configure("separator",
        foreground=colors.get("surface1", colors["border"]),
        spacing1=4, spacing3=4)
    
    # =================================================================
    # Thinking/Reasoning display - improved styling
    # =================================================================
    
    # Thinking header - clickable, yellow accent
    text_widget.tag_configure("thinking_header",
        font=(base_font, 10, "bold"),
        foreground=colors["accent_yellow"],
        spacing1=4, spacing3=2)
    
    # Add cursor change on hover for thinking header
    text_widget.tag_bind("thinking_header", "<Enter>",
        lambda e: text_widget.config(cursor="hand2"))
    text_widget.tag_bind("thinking_header", "<Leave>",
        lambda e: text_widget.config(cursor=""))
    
    # Thinking content - improved contrast (use overlay0 instead of blockquote)
    text_widget.tag_configure("thinking_content",
        font=(base_font, 10),
        foreground=colors.get("overlay0", colors["blockquote"]),
        lmargin1=12, lmargin2=12,
        spacing1=2, spacing3=2)
    
    # Thinking message role (for markdown-rendered thinking)
    text_widget.tag_configure("thinking_message",
        lmargin1=12, lmargin2=12, rmargin=8,
        spacing1=1, spacing3=2)
    
    # =================================================================
    # Message action icons (edit, rerun, more)
    # =================================================================
    
    # Muted by default — accent highlight on hover is handled per-instance
    text_widget.tag_configure("action_icon",
        font=(base_font, 10),
        foreground=colors.get("surface1", colors.get("overlay0", "#585b70")))
    
    # Hover-highlighted variant
    text_widget.tag_configure("action_icon_hover",
        font=(base_font, 10),
        foreground=colors.get("accent", "#89b4fa"))
    
    # =================================================================
    # LaTeX math display
    # =================================================================
    
    # Inline math ($...$) - italic with accent color
    text_widget.tag_configure("latex_inline",
        font=(base_font, 11, "italic"),
        foreground=colors.get("accent_yellow", colors["accent"]))
    
    # Display math ($$...$$) - left-aligned block with code font for alignment
    text_widget.tag_configure("latex_block",
        font=(mono_font, 11),
        foreground=colors.get("accent_yellow", colors["accent"]),
        background=colors["code_bg"],
        justify="left",
        lmargin1=24, lmargin2=24, rmargin=24,
        spacing1=4, spacing3=4)
    
    # Technical symbols font (center pieces) - used for characters 
    # that are missing or look poor in monospaced fonts.
    text_widget.tag_configure("latex_symbols",
        font=("Segoe UI Symbol", 24),
        foreground=colors.get("accent_yellow", colors["accent"]))
    
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
    match = re.match(r'^\*\*\*(.+)\*\*\*$', text.strip())
    if match:
        return match.group(1), 'bold_italic'

    match = re.match(r'^___(.+)___$', text.strip())
    if match:
        return match.group(1), 'bold_italic'

    # Check for bold
    match = re.match(r'^\*\*(.+)\*\*$', text.strip())
    if match:
        return match.group(1), 'bold'

    match = re.match(r'^__(.+)__$', text.strip())
    if match:
        return match.group(1), 'bold'

    # Check for italic
    match = re.match(r'^\*([^\*]+)\*$', text.strip())
    if match:
        return match.group(1), 'italic'

    match = re.match(r'^_([^_]+)_$', text.strip())
    if match:
        return match.group(1), 'italic'

    # No formatting or mixed - strip all markers
    result = text
    result = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', result)
    result = re.sub(r'\*\*(.+?)\*\*', r'\1', result)
    result = re.sub(r'__(.+?)__', r'\1', result)
    result = re.sub(r'\*([^\*]+)\*', r'\1', result)
    result = re.sub(r'`([^`]+)`', r'\1', result)
    return result, None


def _strip_formatting_simple(text: str) -> str:
    """Strip inline formatting markers without detecting style (for tables)."""
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'\*([^\*]+)\*', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return text


def _extract_tables(text: str) -> Tuple[str, List[Tuple[int, List[List[str]]]]]:
    """
    Extract markdown tables from text and replace with placeholders.

    Returns:
        Tuple of (modified_text, list of (placeholder_line_index, table_data))
    """
    lines = text.split('\n')
    result_lines = []
    tables = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check if this looks like a table row (starts and ends with |)
        if stripped.startswith('|') and stripped.endswith('|'):
            table_rows = []
            table_start = len(result_lines)

            # Collect all consecutive table rows
            while i < len(lines):
                row_line = lines[i].strip()
                if not (row_line.startswith('|') and row_line.endswith('|')):
                    break

                # Parse cells (split by | and strip)
                cells = [c.strip() for c in row_line.split('|')[1:-1]]

                # Skip separator rows (containing only dashes/colons)
                if cells and all(re.match(r'^:?-+:?$', c) for c in cells):
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

    return '\n'.join(result_lines), tables


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
        return f'__LATEX_DISPLAY_{idx}__'
    
    # Match $$...$$ (may span multiple lines)
    modified = re.sub(r'\$\$(.+?)\$\$', replace_block, text, flags=re.DOTALL)
    return modified, blocks


def _render_table(text_widget: tk.Text, table_data: List[List[str]], colors: Dict[str, str],
                  role_tag: Optional[str] = None, block_tag: Optional[str] = None,
                  line_prefix: str = ""):
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
    line_num = current_pos.split('.')[0]

    # Create/configure a tag keyed by the computed margin (reuse across same-width lines)
    tag_name = f"_hanging_{lmargin2}"
    text_widget.tag_configure(tag_name, lmargin2=lmargin2)

    # Apply to the entire current paragraph
    text_widget.tag_add(tag_name, f"{line_num}.0", f"{line_num}.end")
    # Raise priority so it overrides message block tags (user_message/assistant_message)
    # which set lmargin2=0
    text_widget.tag_raise(tag_name)


def render_markdown(text: str, text_widget: tk.Text, colors: Dict[str, str],
                   wrap: bool = True, as_role: Optional[str] = None,
                   enable_emojis: bool = True, block_tag: Optional[str] = None,
                   line_prefix: str = ""):
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

    lines = text.split('\n')
    in_code_block = False
    code_block_lines = []

    # Create a font object for measuring prefix widths (hanging indent)
    try:
        widget_font = text_widget.cget("font")
        _font_obj = tkfont.Font(font=widget_font)
    except Exception:
        try:
            _font_obj = tkfont.Font(family="Segoe UI", size=11)
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
        if stripped.startswith('```'):
            if in_code_block:
                # End code block - render accumulated lines
                if code_block_lines:
                    # Add newline before code block if there's preceding content
                    if text_widget.index(tk.END) != "1.0":
                        text_widget.insert(tk.END, '\n', build_tags("normal"))
                    # Apply indentation to code block lines
                    code_lines_prefixed = [line_prefix + l for l in code_block_lines]
                    code_text = '\n'.join(code_lines_prefixed)
                    tags = build_tags("codeblock")
                    # Don't render emojis in code blocks
                    text_widget.insert(tk.END, code_text + '\n', tags)
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
            text_widget.insert(tk.END, '\n', newline_tags)
        
        # Empty line - minimal spacing
        if not stripped:
            continue

        # Check for table placeholder
        table_match = re.match(r'^__TABLE_PLACEHOLDER_(\d+)__$', stripped)
        if table_match:
            table_idx = int(table_match.group(1))
            if table_idx < len(table_blocks):
                _, table_data = table_blocks[table_idx]
                _render_table(text_widget, table_data, colors, role_tag, block_tag, line_prefix)
            continue
        
        # Check for LaTeX display block placeholder
        latex_match = re.match(r'^__LATEX_DISPLAY_(\d+)__$', stripped)
        if latex_match:
            latex_idx = int(latex_match.group(1))
            if latex_idx < len(latex_display_blocks):
                latex_content = latex_display_blocks[latex_idx]
                try:
                    converted = latex_to_unicode(latex_content)
                except Exception:
                    converted = latex_content
                # Need to handle each line separately to apply prefix correctly
                converted_lines = converted.split('\n')
                for idx, line_str in enumerate(converted_lines):
                    if idx > 0:
                        text_widget.insert(tk.END, '\n', build_tags("normal"))
                    
                    if line_prefix:
                        text_widget.insert(tk.END, line_prefix, build_tags("normal"))
                    
                    tags = build_tags("latex_block")
                    
                    # Technical characters that need Segoe UI Symbol
                    symbol_chars = "⎨⎬"
                    
                    for char in line_str:
                        if char in symbol_chars:
                            char_tags = tuple(list(tags) + ["latex_symbols"])
                            _insert_with_emojis(text_widget, char, char_tags, False)
                        else:
                            _insert_with_emojis(text_widget, char, tags, False)
            continue

        # Insert prefix for this line
        if line_prefix:
            prefix_tags = build_tags("normal")
            text_widget.insert(tk.END, line_prefix, prefix_tags)
        
        # Headers
        if stripped.startswith('#'):
            level = 0
            for char in stripped:
                if char == '#':
                    level += 1
                else:
                    break
            
            if level <= 6 and len(stripped) > level and stripped[level] == ' ':
                header_text = stripped[level+1:]
                content, format_style = _strip_inline_formatting(header_text)
                base_tag = f"h{min(level, 4)}"

                # Use italic header tag if italic formatting detected
                if format_style in ('italic', 'bold_italic'):
                    tag = f"{base_tag}_italic"
                else:
                    tag = base_tag

                tags = build_tags(tag)
                _insert_with_emojis(text_widget, content, tags, enable_emojis)
                continue
        
        # Blockquote
        if stripped.startswith('>'):
            content = stripped[1:].strip()
            tags = build_tags("blockquote")
            _insert_with_emojis(text_widget, "│ " + content, tags, enable_emojis)
            continue
        
        # Bullet points
        if stripped.startswith('- ') or stripped.startswith('* '):
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
        match = re.match(r'^(\d+)\.\s+(.+)$', stripped)
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
        if re.match(r'^[-*_]{3,}$', stripped):
            tags = build_tags("separator")
            text_widget.insert(tk.END, "─" * 40, tags)
            continue
        
        # Regular paragraph with inline formatting
        _render_inline(line, text_widget, colors, role_tag, enable_emojis, block_tag)
    
    # Flush any remaining code block
    if in_code_block and code_block_lines:
        code_lines_prefixed = [line_prefix + l for l in code_block_lines]
        code_text = '\n'.join(code_lines_prefixed)
        tags = build_tags("codeblock")
        # Don't render emojis in code blocks
        text_widget.insert(tk.END, code_text + '\n', tags)


def _insert_with_emojis(
    text_widget: tk.Text,
    text: str,
    tags: Optional[Tuple[str, ...]] = None,
    enable_emojis: bool = True
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
        enable_emojis and
        HAVE_EMOJI_RENDERER and
        sys.platform == 'win32' and
        get_emoji_renderer is not None and
        not link_url # Check if this is a link URL segment
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


def _render_inline(text: str, text_widget: tk.Text, colors: Dict[str, str],
                   role_tag: Optional[str] = None, enable_emojis: bool = True,
                   block_tag: Optional[str] = None):
    """Render inline markdown formatting (bold, italic, code) with emoji support."""
    
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
        (r'\*\*\*(.+?)\*\*\*', 'bold_italic'),  # ***text***
        (r'___(.+?)___', 'bold_italic'),         # ___text___
        (r'\*\*(.+?)\*\*', 'bold'),              # **text**
        (r'__(.+?)__', 'bold'),                  # __text__
        (r'\*(.+?)\*', 'italic'),                # *text*
        (r'_(.+?)_', 'italic'),                  # _text_ (word boundary aware)
        (r'`([^`]+)`', 'code'),                  # `code`
        (r'~~(.+?)~~', 'strikethrough'),         # ~~text~~
        (r'\[([^\]]+)\]\(([^)]+)\)', 'link'),    # [text](url)
    ]
    
    # Build a combined pattern to find all matches in order
    # Note: $...$ inline LaTeX is matched BEFORE bold/italic underscore patterns
    combined = r'(\*\*\*.+?\*\*\*|___.+?___|' \
               r'\*\*.+?\*\*|__.+?__|' \
               r'\*[^\*]+\*|(?<![a-zA-Z])_[^_]+_(?![a-zA-Z])|' \
               r'`[^`]+`|~~.+?~~|' \
               r'\[[^\]]+\]\([^)]+\)|' \
               r'(?<!\$)\$(?!\$)(\S(?:[^$]*?\S)?)\$(?!\$))'
    
    pos = 0
    for match in re.finditer(combined, text):
        # Insert any text before this match
        if match.start() > pos:
            plain_text = text[pos:match.start()]
            tags = build_tags("normal")
            _insert_with_emojis(text_widget, plain_text, tags, enable_emojis)
        
        matched_text = match.group(0)
        content = None
        tag = "normal"
        
        # Determine which pattern matched
        if matched_text.startswith('***') and matched_text.endswith('***'):
            content = matched_text[3:-3]
            tag = "bold_italic"
        elif matched_text.startswith('___') and matched_text.endswith('___'):
            content = matched_text[3:-3]
            tag = "bold_italic"
        elif matched_text.startswith('**') and matched_text.endswith('**'):
            content = matched_text[2:-2]
            tag = "bold"
        elif matched_text.startswith('__') and matched_text.endswith('__'):
            content = matched_text[2:-2]
            tag = "bold"
        elif matched_text.startswith('`') and matched_text.endswith('`'):
            content = matched_text[1:-1]
            tag = "code"
        elif matched_text.startswith('~~') and matched_text.endswith('~~'):
            content = matched_text[2:-2]
            tag = "strikethrough"
        elif matched_text.startswith('[') and matched_text.endswith(')'):
            # Parse link [text](url)
            match_link = re.match(r'\[([^\]]+)\]\(([^)]+)\)', matched_text)
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
        elif matched_text.startswith('$') and matched_text.endswith('$') and not matched_text.startswith('$$'):
            # Inline LaTeX math
            inner = matched_text[1:-1]
            # Skip if it looks like currency ($100)
            if not re.match(r'^\d[\d,]*\.?\d*$', inner):
                try:
                    content = latex_to_unicode(inner)
                except Exception:
                    content = inner
                tag = "latex_inline"
        elif matched_text.startswith('*') and matched_text.endswith('*'):
            content = matched_text[1:-1]
            tag = "italic"
        elif matched_text.startswith('_') and matched_text.endswith('_'):
            content = matched_text[1:-1]
            tag = "italic"
        
        if content:
            if tag == "link" and 'extra_tag' in locals():
                tags = build_tags(tag, extra_tag)
                # Cleanup local variable for next iteration
                del extra_tag
            else:
                tags = build_tags(tag)
            _insert_with_emojis(text_widget, content, tags, enable_emojis)
        
        pos = match.end()
    
    # Insert any remaining text
    if pos < len(text):
        remaining = text[pos:]
        tags = build_tags("normal")
        _insert_with_emojis(text_widget, remaining, tags, enable_emojis)


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
    if hasattr(colors, '__dataclass_fields__'):
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
    if sys.platform == 'win32':
        font = ("Segoe UI", 11)
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
