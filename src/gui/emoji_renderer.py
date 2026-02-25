#!/usr/bin/env python3
"""
Emoji Renderer for Tkinter and CustomTkinter widgets

Replaces emoji characters with inline PNG images from the Twemoji asset set.
This is necessary because Windows Tkinter doesn't natively render color emojis
in Text widgets - they appear as monochrome outlines.

Supports two rendering modes:
1. tk.Text widgets: Uses image_create() to embed PhotoImage objects
2. CTkButton/CTkLabel: Uses CTkImage with compound="left" layout

The assets should be placed in assets/emojis/72x72/ with filenames matching
the Unicode codepoints in lowercase hex (e.g., 1f600.png for 😀).

For multi-codepoint emojis (like flags 🇺🇸), filenames use hyphens:
1f1fa-1f1f8.png
"""

import os
import re
import sys
import zipfile
import io
import tempfile
import shutil
import threading

# Safe atexit registration that ignores errors during interpreter shutdown
def _safe_atexit_register(func):
    """Register an atexit handler, ignoring errors if interpreter is shutting down."""
    import sys
    # Check if interpreter is already shutting down (Python 3.13+)
    is_finalizing = getattr(sys, 'is_finalizing', None)
    if is_finalizing is not None and is_finalizing():
        return
    try:
        import atexit
        atexit.register(func)
    except Exception:
        pass  # Interpreter may be shutting down
try:
    import emoji
    HAVE_EMOJI_LIB = True
except ImportError:
    HAVE_EMOJI_LIB = False
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any
import tkinter as tk

# Try to import PIL for image handling
try:
    from PIL import Image, ImageTk
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

from .platform import HAVE_CTK, ctk, CTkImage


def get_assets_path() -> Tuple[Path, bool]:
    """
    Get the path to the emoji assets (zip or directory).
    
    Returns:
        Tuple[Path, bool]: (path, is_zip)
    """
    # Potential paths to check
    paths = []
    
    # 1. Relative to this file (development)
    module_dir = Path(__file__).parent.parent.parent
    assets_base = module_dir / "assets"
    paths.append(assets_base / "emojis.zip")
    paths.append(assets_base / "emojis" / "72x72")
    
    # 2. Relative to sys.executable (frozen executable)
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        assets_base = exe_dir / "assets"
        paths.append(assets_base / "emojis.zip")
        paths.append(assets_base / "emojis" / "72x72")
    
    # 3. Current working directory (if different from above)
    # This is important when launching from search/Run dialog where CWD might be arbitrary
    cwd = Path.cwd()
    if cwd != module_dir and (not getattr(sys, 'frozen', False) or cwd != Path(sys.executable).parent):
        cwd_base = cwd / "assets"
        paths.append(cwd_base / "emojis.zip")
        paths.append(cwd_base / "emojis" / "72x72")
    
    for path in paths:
        if path.exists():
            return path, path.suffix == '.zip'
    
    # Default fallback
    return Path("assets/emojis.zip"), True


# Regex patterns for fallback emoji detection (if emoji lib not available)
# This covers most common emoji ranges including:
# - Basic emoticons (U+1F600-U+1F64F)
# - Misc symbols (U+2600-U+26FF)
# - Dingbats (U+2700-U+27BF)
# - Transport and map symbols (U+1F680-U+1F6FF)
# - Supplemental symbols (U+1F900-U+1F9FF)
# - Regional indicators for flags (U+1F1E0-U+1F1FF)
# - Various other emoji blocks
FALLBACK_EMOJI_PATTERN = re.compile(
    r'[\U0001F600-\U0001F64F]'  # Emoticons
    r'|[\U0001F300-\U0001F5FF]'  # Misc Symbols and Pictographs
    r'|[\U0001F680-\U0001F6FF]'  # Transport and Map
    r'|[\U0001F700-\U0001F77F]'  # Alchemical Symbols
    r'|[\U0001F780-\U0001F7FF]'  # Geometric Shapes Extended
    r'|[\U0001F800-\U0001F8FF]'  # Supplemental Arrows-C
    r'|[\U0001F900-\U0001F9FF]'  # Supplemental Symbols and Pictographs
    r'|[\U0001FA00-\U0001FA6F]'  # Chess Symbols
    r'|[\U0001FA70-\U0001FAFF]'  # Symbols and Pictographs Extended-A
    r'|[\U00002702-\U000027B0]'  # Dingbats
    r'|[\U0001F1E0-\U0001F1FF]'  # Regional indicators (flags)
    r'|[\U00002600-\U000026FF]'  # Misc symbols
    r'|[\U00002300-\U000023FF]'  # Misc Technical
    r'|[\U0000231A-\U0000231B]'  # Watch, Hourglass
    r'|[\U00002B50]'              # Star
    r'|[\U00003030]'              # Wavy dash
    r'|[\U0000303D]'              # Part alternation mark
    r'|[\U00002934-\U00002935]'  # Arrows
    r'|[\U000025AA-\U000025AB]'  # Squares
    r'|[\U000025B6]'              # Play button
    r'|[\U000025C0]'              # Reverse button
    r'|[\U000025FB-\U000025FE]'  # Squares
    r'|[\U00002B05-\U00002B07]'  # Arrows
    r'|[\U00002B1B-\U00002B1C]'  # Squares
    r'|[\U00002B55]'              # Circle
)

# Pattern for flag emoji sequences (regional indicator pairs) - Fallback
FALLBACK_FLAG_PATTERN = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')

VARIATION_SELECTOR = '\ufe0f'


class EmojiRenderer:
    """
    Renders emojis as inline images in Tkinter and CustomTkinter widgets.
    
    Usage for tk.Text:
        renderer = EmojiRenderer()
        renderer.insert_text_with_emojis(text_widget, "Hello 😀 World!", tags=("normal",))
    
    Usage for CTkButton/CTkLabel:
        renderer = EmojiRenderer()
        content = renderer.prepare_widget_content("📋 Sessions", size=18)
        button = CTkButton(parent, text=content["text"], image=content["image"], compound=content["compound"])
    """
    
    DEFAULT_SIZE = 18  # Default emoji size in pixels
    CTK_DEFAULT_SIZE = 18  # Default size for CTkImage buttons
    
    def __init__(self, size: int = None):
        """
        Initialize the emoji renderer.
        
        Args:
            size: Size to render emojis at in pixels (default: 18)
        """
        self.assets_path, self.is_zip = get_assets_path()
        self.size = size or self.DEFAULT_SIZE
        
        # Temp dir for generated icons - Eager initialization
        # We create this immediately so we can exclude it from background cleanup logic
        self._temp_icon_dir = tempfile.mkdtemp(prefix="aipromptbridge_icons_")
        _safe_atexit_register(self.cleanup)
        
        # Clean up stale directories in background to avoid startup delay
        # This is safe because we've already created (and know the path of) our current dir
        threading.Thread(target=self._clean_stale_dirs, daemon=True).start()
        
        # ZIP file handling
        self.zip_file: Optional[zipfile.ZipFile] = None
        self.zip_data: Optional[bytes] = None
        
        if self.is_zip and self.assets_path.exists():
            try:
                # Read entire ZIP into RAM
                with open(self.assets_path, "rb") as f:
                    self.zip_data = f.read()
                self.zip_file = zipfile.ZipFile(io.BytesIO(self.zip_data))
            except Exception as e:
                print(f"[Error] Failed to load emoji zip: {e}")
        
        # Cache for PhotoImage (tk.Text widgets)
        self._cache: Dict[Tuple[str, int], ImageTk.PhotoImage] = {}
        
        # Cache for CTkImage (CTkButton/CTkLabel widgets)
        # We DO NOT cache CTkImage objects because they are bound to the Tk instance
        # they were created in. If multiple threads/windows create their own roots,
        # sharing CTkImage objects causes "pyimage doesn't exist" errors.
        # We only cache the underlying PIL images.
        
        # Track missing files to avoid repeated lookups
        self._missing_cache: set = set()
        
        # Check if PIL is available
        if not HAVE_PIL:
            print("[Warning] PIL not available - emoji rendering disabled")
    
    def _get_temp_icon_dir(self) -> str:
        """Get the temporary directory for icon files."""
        # Already initialized in __init__
        if self._temp_icon_dir is None or not os.path.exists(self._temp_icon_dir):
            # Re-create if missing (e.g. if user deleted it manually while app running)
            self._temp_icon_dir = tempfile.mkdtemp(prefix="aipromptbridge_icons_")
            # atexit registration is idempotent or harmless if duplicated
            
        return self._temp_icon_dir
    
    def cleanup(self):
        """Clean up the temporary icon directory."""
        if self._temp_icon_dir and os.path.exists(self._temp_icon_dir):
            try:
                shutil.rmtree(self._temp_icon_dir, ignore_errors=True)
                self._temp_icon_dir = None
            except Exception:
                pass

    def _clean_stale_dirs(self):
        """Clean up old temporary directories from previous runs."""
        try:
            temp_base = tempfile.gettempdir()
            prefix = "aipromptbridge_icons_"
            
            for item in os.listdir(temp_base):
                if item.startswith(prefix):
                    full_path = os.path.join(temp_base, item)
                    # Don't delete the current one if it exists (though it shouldn't yet)
                    if full_path == self._temp_icon_dir:
                        continue
                        
                    if os.path.isdir(full_path):
                        try:
                            # Attempt to remove - will fail silently if in use/locked
                            shutil.rmtree(full_path, ignore_errors=True)
                        except Exception:
                            pass
        except Exception:
            pass

    def get_emoji_icon_path(self, emoji_char: str, size: int = 16) -> Optional[str]:
        """
        Get path to a temporary .ico file for the emoji.
        Generates it if it doesn't exist.
        
        Args:
            emoji_char: The emoji character(s)
            size: Base size in pixels to include (default: 16)
            
        Returns:
            Path to .ico file if successful, None otherwise
        """
        if not HAVE_PIL:
            return None
            
        try:
            filename = self.get_codepoint_filename(emoji_char)
            temp_dir = self._get_temp_icon_dir()
            # Use fixed name to include multiple sizes
            icon_path = os.path.join(temp_dir, f"{filename}_multi.ico")
            
            if os.path.exists(icon_path):
                return icon_path
                
            # Load and generate
            pil_img = self._load_pil_image(emoji_char)
            if pil_img:
                # Resize to standard menu icon size (16x16)
                # Using a single size is safer for basic GDI menus to avoid scaling issues
                img = pil_img.resize((16, 16), Image.Resampling.LANCZOS)
                
                # Convert to RGBA for compositing
                rgba = img.convert("RGBA")
                
                # FLATTEN TRANSPARENCY
                # Composite the emoji against the menu background color so
                # Windows GDI menus don't show black/white boxes behind the icon.
                
                # Determine background color based on system theme
                bg_color = (240, 240, 240, 255)  # Standard Windows Light Menu Gray
                try:
                    from .themes import is_dark_mode
                    if is_dark_mode():
                        bg_color = (43, 43, 43, 255)  # Windows 11 Dark Menu (#2b2b2b)
                except ImportError:
                    pass
                except Exception:
                    pass
                
                # Alpha composite onto solid background
                bg = Image.new('RGBA', (16, 16), bg_color)
                combined = Image.alpha_composite(bg, rgba)
                
                # Convert to RGB (no alpha) to prevent GDI from
                # misinterpreting residual alpha channel data in the ICO
                combined_rgb = combined.convert("RGB")
                
                # Save as ICO — fully opaque, no transparency artifacts
                combined_rgb.save(icon_path, format="ICO", sizes=[(16, 16)])
                return icon_path
                
        except Exception as e:
            print(f"[Error] Failed to generate emoji icon: {e}")
            
        return None

    def get_codepoint_filename(self, char_or_seq: str, strip_vs16: bool = True) -> str:
        """
        Convert an emoji character or sequence to its Twemoji filename.
        
        Single emojis: 😀 -> "1f600"
        Flag pairs: 🇺🇸 -> "1f1fa-1f1f8"
        ZWJ sequences: 👨‍👩‍👧 -> "1f468-200d-1f469-200d-1f467"
        
        Args:
            char_or_seq: The emoji character(s)
            strip_vs16: Whether to strip Variation Selector 16 (0xFE0F)
            
        Returns:
            The filename without extension (e.g., "1f600")
        """
        # Convert each codepoint to hex and join with hyphens
        codepoints = []
        for char in char_or_seq:
            cp = ord(char)
            # Skip variation selector if requested
            if strip_vs16 and cp == 0xfe0f:
                continue
            codepoints.append(f"{cp:x}")
        
        return "-".join(codepoints)
    
    def _load_pil_image(self, emoji: str) -> Optional[Image.Image]:
        """
        Load PIL Image for an emoji from assets.
        
        Args:
            emoji: The emoji character(s)
            
        Returns:
            PIL Image if found, None otherwise
        """
        if not HAVE_PIL:
            return None
        
        # Try both with and without VS16
        # Some twemoji files include fe0f (e.g. 1f3f3-fe0f-200d-1f308.png)
        # Others don't (e.g. 1f600.png)
        # We try strict first (keeping the sequence as provided or with fe0f), then loose
        
        filenames_to_try = []
        
        # 1. Exact match (preserve fe0f if present)
        filenames_to_try.append(self.get_codepoint_filename(emoji, strip_vs16=False))
        
        # 2. Stripped match (remove fe0f)
        filenames_to_try.append(self.get_codepoint_filename(emoji, strip_vs16=True))
        
        # Avoid duplicates
        filenames_to_try = list(dict.fromkeys(filenames_to_try))
        
        # Check if we already know ALL variants are missing
        if all(f in self._missing_cache for f in filenames_to_try):
            return None
        
        # Try to load the image
        for filename in filenames_to_try:
            if filename in self._missing_cache:
                continue
                
            try:
                name_variants = [f"{filename}.png", f"{filename.lower()}.png"]
                
                if self.is_zip and self.zip_file:
                    # Look in ZIP
                    found_name = None
                    for name in name_variants:
                        if name in self.zip_file.namelist():
                            found_name = name
                            break
                    
                    if found_name:
                        with self.zip_file.open(found_name) as f:
                            # Must read into memory because Image.open is lazy
                            # and the zip file handle will close when we exit the block
                            img_data = f.read()
                            return Image.open(io.BytesIO(img_data)).convert("RGBA")
                
                elif not self.is_zip and self.assets_path.exists():
                    # Look in directory
                    for name in name_variants:
                        image_path = self.assets_path / name
                        if image_path.exists():
                            return Image.open(image_path).convert("RGBA")
            
            except Exception:
                pass
            
            # If we got here, this filename failed
            self._missing_cache.add(filename)
            
        return None
    
    @staticmethod
    def _hex_to_rgba(hex_color: str) -> Tuple[int, int, int, int]:
        """Convert a hex color string like '#1e3e2e' to an RGBA tuple."""
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return (r, g, b, 255)
    
    def get_emoji_image(self, emoji: str, size: Optional[int] = None,
                        bg_color: Optional[str] = None) -> Optional[ImageTk.PhotoImage]:
        """
        Load and cache an emoji image as PhotoImage (for tk.Text widgets).
        
        Args:
            emoji: The emoji character(s)
            size: Size in pixels (uses default if not specified)
            bg_color: Optional hex background color (e.g. '#1e3e2e') to composite
                      the emoji against, so transparency blends with tag backgrounds.
            
        Returns:
            PhotoImage if found, None otherwise
        """
        if not HAVE_PIL:
            return None
        
        size = size or self.size
        # Special handling for simple keycaps 1..9 which might come as single digits
        # but files are named 31-20e3.png
        # This normalization is usually handled by get_codepoint_filename but
        # keycaps often have the invisible 20E3
        
        filename = self.get_codepoint_filename(emoji)
        cache_key = (filename, size, bg_color)
        
        # Check cache
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Load PIL image
        pil_image = self._load_pil_image(emoji)
        if pil_image is None:
            return None
        
        try:
            # Resize
            pil_image = pil_image.resize((size, size), Image.Resampling.LANCZOS)
            
            # Composite against background color if provided
            # tk.Text embedded images composite against the widget's bg, not the tag's
            # background. This flattens transparency against the correct tag bg color.
            if bg_color:
                bg = Image.new('RGBA', (size, size), self._hex_to_rgba(bg_color))
                pil_image = Image.alpha_composite(bg, pil_image)
            
            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(pil_image)
            
            # Cache it (IMPORTANT: must keep reference to prevent garbage collection)
            self._cache[cache_key] = photo
            
            return photo
            
        except Exception:
            return None
    
    def get_ctk_image(self, emoji: str, size: Optional[int] = None) -> Optional[Any]:
        """
        Load an emoji as CTkImage (for CTkButton/CTkLabel widgets).
        
        Note: We do NOT cache CTkImage objects here because they are thread/root sensitive.
        We only cache the underlying PIL images.
        
        Args:
            emoji: The emoji character(s)
            size: Size in pixels (uses CTK_DEFAULT_SIZE if not specified)
            
        Returns:
            CTkImage if found and CTk available, None otherwise
        """
        if not HAVE_PIL or not HAVE_CTK:
            return None
        
        size = size or self.CTK_DEFAULT_SIZE
        
        # Load PIL image (this IS cached internally)
        pil_image = self._load_pil_image(emoji)
        if pil_image is None:
            return None
        
        try:
            # Create fresh CTkImage every time to ensure it binds to the current Tk root
            # This prevents "pyimage doesn't exist" errors in multi-threaded/multi-window apps
            return CTkImage(
                light_image=pil_image,
                dark_image=pil_image,
                size=(size, size)
            )
            
        except Exception:
            return None
    
    def extract_leading_emoji(self, text: str) -> Tuple[Optional[str], str]:
        """
        Extract a leading emoji from text.
        
        Args:
            text: Text that may start with an emoji
            
        Returns:
            Tuple of (emoji_string, remaining_text) or (None, original_text)
            
        Examples:
            "📋 Sessions" -> ("📋", "Sessions")
            "Hello" -> (None, "Hello")
            "🇺🇸 USA" -> ("🇺🇸", "USA")
        """
        text = text.strip()
        if not text:
            return None, text
        
        if HAVE_EMOJI_LIB:
            # Use emoji library to find first token
            try:
                # analyze() returns a generator of Token objects in order
                # We just check the first token
                first_token = next(emoji.analyze(text, join_emoji=True), None)
                if first_token and first_token.chars:
                    # Check if the token is at the start of the string
                    if text.startswith(first_token.chars):
                        emoji_char = first_token.chars
                        remaining = text[len(emoji_char):].lstrip()
                        return emoji_char, remaining
            except Exception:
                pass
        
        # Fallback to simple regex checks if library unavailable or failed
        
        # Check for flag emoji first (two regional indicators)
        if len(text) >= 2:
            match = FALLBACK_FLAG_PATTERN.match(text)
            if match:
                emoji_char = match.group()
                remaining = text[len(emoji_char):].lstrip()
                return emoji_char, remaining
        
        # Check single emoji at start
        match = FALLBACK_EMOJI_PATTERN.match(text)
        if match:
            emoji_char = match.group()
            remaining = text[len(emoji_char):].lstrip()
            return emoji_char, remaining
        
        return None, text
    
    def prepare_widget_content(
        self,
        text: str,
        size: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Prepare content for CTkButton/CTkLabel with emoji support.
        
        Extracts leading emoji and returns kwargs for widget creation.
        
        Args:
            text: Text that may contain a leading emoji (e.g., "📋 Sessions")
            size: Emoji size in pixels (default: 18)
            
        Returns:
            Dict with keys:
                - "text": str - The text without the emoji
                - "image": CTkImage|None - The emoji image if found
                - "compound": str|None - "left" if image present, else None
                
        Usage:
            content = renderer.prepare_widget_content("📋 Sessions")
            button = CTkButton(parent, **content, ...)
        """
        size = size or self.CTK_DEFAULT_SIZE
        
        # Extract leading emoji
        emoji_char, remaining_text = self.extract_leading_emoji(text)
        
        if emoji_char:
            # Try to get CTkImage for the emoji
            ctk_img = self.get_ctk_image(emoji_char, size)
            
            if ctk_img:
                return {
                    "text": remaining_text,
                    "image": ctk_img,
                    "compound": "left"
                }
        
        # No emoji or couldn't load image - return original text
        return {
            "text": text,
            "image": None,
            "compound": None
        }
    
    def find_emojis(self, text: str) -> List[Tuple[int, int, str]]:
        """
        Find all emoji positions in text.
        
        Args:
            text: The text to search
            
        Returns:
            List of (start, end, emoji_string) tuples
        """
        results = []
        
        if HAVE_EMOJI_LIB:
            try:
                # Use emoji.emoji_list which gives positions directly
                # It handles ZWJ groups, flags, modifiers correctly
                for match in emoji.emoji_list(text):
                    start = match['match_start']
                    end = match['match_end']
                    char = match['emoji']
                    results.append((start, end, char))
                return results
            except Exception:
                pass
        
        # Fallback to simple regex if library unavailable
        
        # First, find flag sequences (two regional indicators)
        for match in FALLBACK_FLAG_PATTERN.finditer(text):
            results.append((match.start(), match.end(), match.group()))
        
        # Then find individual emojis
        for match in FALLBACK_EMOJI_PATTERN.finditer(text):
            start, end = match.start(), match.end()
            
            # Skip if this position is already covered by a flag
            if any(r[0] <= start < r[1] for r in results):
                continue
            
            results.append((start, end, match.group()))
        
        # Sort by position
        results.sort(key=lambda x: x[0])
        
        return results
    
    def insert_text_with_emojis(
        self, 
        text_widget: tk.Text, 
        text: str, 
        tags: Optional[Tuple[str, ...]] = None,
        at_end: bool = True
    ):
        """
        Insert text into a Text widget, replacing emojis with images.
        
        Args:
            text_widget: The tk.Text widget
            text: Text to insert
            tags: Tags to apply to non-emoji text
            at_end: If True, insert at end; otherwise at current cursor
        """
        if not HAVE_PIL:
            # Fallback: just insert text normally
            if at_end:
                text_widget.insert(tk.END, text, tags)
            else:
                text_widget.insert(tk.INSERT, text, tags)
            return
        
        # Find emojis
        emojis = self.find_emojis(text)
        
        if not emojis:
            # No emojis, just insert text
            if at_end:
                text_widget.insert(tk.END, text, tags)
            else:
                text_widget.insert(tk.INSERT, text, tags)
            return
        
        # Detect tag background color for emoji compositing
        # tk.Text embedded images don't inherit tag backgrounds, so we must
        # flatten emoji transparency against the correct bg color.
        bg_color = None
        if tags:
            for tag in tags:
                try:
                    tag_bg = text_widget.tag_cget(tag, "background")
                    if tag_bg:
                        bg_color = tag_bg
                        break
                except Exception:
                    pass
        
        # Insert text segments and emojis
        pos = tk.END if at_end else tk.INSERT
        last_end = 0
        
        for start, end, emoji_char in emojis:
            # Insert text before this emoji
            if start > last_end:
                text_widget.insert(pos, text[last_end:start], tags)
            
            # Try to get emoji image (with bg_color for proper blending)
            img = self.get_emoji_image(emoji_char, bg_color=bg_color)
            
            if img:
                # Record position before insertion so we can tag the image
                img_idx = text_widget.index("end-1c") if at_end else text_widget.index(tk.INSERT)
                # Insert the image
                text_widget.image_create(pos, image=img)
                # Tag the image position so it inherits tag backgrounds
                # (without this, the image cell shows the widget's base bg color)
                if tags:
                    for tag in tags:
                        text_widget.tag_add(tag, img_idx)
            else:
                # Fallback: insert the emoji character as text
                text_widget.insert(pos, emoji_char, tags)
            
            last_end = end
        
        # Insert remaining text after last emoji
        if last_end < len(text):
            text_widget.insert(pos, text[last_end:], tags)
    
    def clear_cache(self):
        """Clear all image caches."""
        self._cache.clear()
        self._missing_cache.clear()
    
    def preload_common_emojis(self):
        """Preload commonly used emojis into cache."""
        common_emojis = [
            "😀", "😃", "😄", "😁", "😆", "😅", "🤣", "😂",
            "🙂", "🙃", "😉", "😊", "😇", "🥰", "😍", "🤩",
            "😘", "😗", "☺", "😚", "😙", "🥲", "😋", "😛",
            "✅", "❌", "⚠️", "❓", "❗", "💡", "🔥", "🔥", "⭐",
            "📋", "📂", "📡", "🤖", "🌊", "💭", "🔑", "🚀",
            "🖥️", "⚙️", "✏️", "🔲", "📟", "🔄", "🗑️", "💬",
            "👍", "👎", "👏", "🙌", "🤝", "🙏", "✍️", "💪",
        ]
        
        for emoji_char in common_emojis:
            self.get_emoji_image(emoji_char)


# Global renderer instance
_global_renderer: Optional[EmojiRenderer] = None


def get_emoji_renderer() -> EmojiRenderer:
    """Get the global emoji renderer instance."""
    global _global_renderer
    if _global_renderer is None:
        _global_renderer = EmojiRenderer()
    return _global_renderer


def insert_with_emojis(
    text_widget: tk.Text,
    text: str,
    tags: Optional[Tuple[str, ...]] = None
):
    """
    Convenience function to insert text with emoji rendering (for tk.Text).
    
    Args:
        text_widget: The tk.Text widget
        text: Text to insert (may contain emojis)
        tags: Tags to apply to non-emoji text
    """
    renderer = get_emoji_renderer()
    renderer.insert_text_with_emojis(text_widget, text, tags)


def get_ctk_emoji_image(emoji_char: str, size: int = 18) -> Optional[Any]:
    """
    Convenience function to get a CTkImage for an emoji.
    
    Args:
        emoji_char: Single emoji character (e.g., "📋")
        size: Size in pixels (default: 18)
        
    Returns:
        CTkImage if available, None otherwise
    """
    renderer = get_emoji_renderer()
    return renderer.get_ctk_image(emoji_char, size)


def prepare_emoji_content(text: str, size: int = 18) -> Dict[str, Any]:
    """
    Convenience function to prepare CTkButton/CTkLabel content with emoji.
    
    Args:
        text: Text with optional leading emoji (e.g., "📋 Sessions")
        size: Emoji size in pixels (default: 18)
        
    Returns:
        Dict with "text", "image", and "compound" keys
        
    Usage:
        content = prepare_emoji_content("📋 Sessions")
        btn = CTkButton(parent, text=content["text"],
                       image=content["image"], compound=content["compound"])
    """
    renderer = get_emoji_renderer()
    return renderer.prepare_widget_content(text, size)