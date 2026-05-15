#!/usr/bin/env python3
"""
Snip popup window for image analysis.

Displays after a successful screen capture, showing:
- Image thumbnail preview
- Action source selector (Snip actions vs TextEditTool actions)
- Custom question input
- Action buttons organized by groups

Threading Note:
    This must be created on the GUI thread via GUICoordinator.
    Uses CTkToplevel when CustomTkinter is available.
"""

import gc
import io
import logging
import tkinter as tk
from typing import Callable, Optional, Dict, List, Any

from PIL import Image, ImageTk

# Import CustomTkinter with fallback
from .platform import HAVE_CTK, ctk

# Import theme system
from .themes import (
    get_colors, ThemeColors,
    get_ctk_font, get_ctk_button_colors,
    get_ctk_frame_colors, get_ctk_entry_colors,
    sync_ctk_appearance
)

from .utils import hide_from_taskbar
from .custom_widgets import create_emoji_button
from .popups import (
    Tooltip, GroupedButtonList, CarouselButtonList,
    setup_transparent_popup, TRANSPARENCY_COLOR,
    ModifierBar, SegmentedToggle,
    create_profile_dropdown_ctk, create_profile_dropdown_tk,
    get_profile_override_value
)
from .screen_snip import CaptureResult
from .prompts import get_prompts_config
from .emoji_renderer import prepare_emoji_content, get_emoji_renderer


def _neutralize_tk_var(var):
    """
    Prevent a tkinter Variable from calling into Tcl during ``__del__``.

    Must be called **after** the parent window has been destroyed (so that
    CTk widgets can still run ``trace_remove`` on the variable during their
    own ``destroy()``).  Sets ``var._tk = None`` so that ``__del__`` becomes
    a harmless no-op instead of crashing with ``RuntimeError: main thread
    is not in main loop`` when GC runs on a background thread.
    """
    try:
        var._tk = None
    except Exception:
        pass


class AttachedSnipPopup:
    """
    Popup for interacting with captured screenshot.
    """
    
    PLACEHOLDER = "Ask about this image..."
    THUMBNAIL_MAX_SIZE = (120, 120)
    
    def __init__(
        self,
        parent_root: tk.Tk,
        capture_result: CaptureResult,
        prompts_config: Dict[str, Any],
        on_action: Callable[[str, str, Optional[str], List[str], bool, Optional[CaptureResult]], None],
        on_close: Optional[Callable[[], None]] = None,
        on_request_compare_capture: Optional[Callable[[Callable[[CaptureResult], None], Callable[[], None]], None]] = None,
        x: Optional[int] = None,
        y: Optional[int] = None
    ):
        """
        Initialize the snip popup.
        
        Args:
            parent_root: Parent Tk root (from GUICoordinator)
            capture_result: The captured image data
            prompts_config: Combined prompts config with snip_tool and optionally text_edit_tool
            on_action: Callback(source, action_key, custom_input, active_modifiers, compare_mode, compare_capture) when action is selected
                source: "snip", "text_edit", or "file_processor"
                action_key: The action name (e.g., "Describe", "Proofread")
                custom_input: Custom question text (if any)
                active_modifiers: List of active modifier keys
                compare_mode: Whether compare mode is enabled
                compare_capture: Second capture result (if compare mode was used)
            on_close: Callback when popup is closed
            on_request_compare_capture: Callback to request second capture for comparison
                Takes (on_capture, on_cancel) callbacks
            x, y: Position coordinates (optional, defaults to cursor position)
        """
        self.parent_root = parent_root
        self.capture_result = capture_result
        self.prompts_config = prompts_config
        self.on_action = on_action
        self.on_close_callback = on_close
        self.on_request_compare_capture = on_request_compare_capture
        self.x = x
        self.y = y
        
        self.colors = get_colors()
        self.root = None
        
        # Current action source: "snip", "text_edit", or "file_processor"
        self.action_source = "snip"
        
        # Load File Processor prompts (filtered for image type)
        self.file_processor_prompts = self._load_file_processor_prompts()
        
        # Compare mode state
        self.compare_mode_enabled = False
        self.compare_capture: Optional[CaptureResult] = None
        self.compare_checkbox = None
        
        # Pending action (for after compare capture)
        self._pending_action: Optional[tuple] = None
        
        # UI references
        self.source_dropdown = None
        self.input_entry = None
        self.actions_frame = None
        self.carousel = None
        self.modifier_bar = None
        
        # Active modifiers
        self.active_modifiers: List[str] = []
        
        # Connection profile override
        self.profile_var = None
        self.profile_dropdown = None
        
        # Thumbnail
        self.thumbnail_photo = None
        
        self._create_window()
    
    def _load_file_processor_prompts(self) -> Dict[str, Any]:
        """Load and filter file processor prompts for images."""
        try:
            from ..tools.config import load_tools_config, get_file_processor_prompts
            config = load_tools_config(create_if_missing=False)
            prompts = get_file_processor_prompts(config)
            # Filter to image-compatible prompts only
            return {
                key: prompt for key, prompt in prompts.items()
                if "image" in prompt.get("input_types", [])
            }
        except Exception as e:
            logging.debug(f"[SnipPopup] Could not load file processor prompts: {e}")
            return {}
    
    def _create_window(self):
        """Create the popup window."""
        if HAVE_CTK:
            sync_ctk_appearance()
            self.root = ctk.CTkToplevel(self.parent_root)
        else:
            self.root = tk.Toplevel(self.parent_root)
        
        # Hide while building
        self.root.withdraw()
        
        self.root.title("Screen Snip")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        
        # Transparent corners on Windows
        setup_transparent_popup(self.root, self.colors)
        hide_from_taskbar(self.root)
        
        if HAVE_CTK:
            self._build_ctk_ui()
        else:
            self._build_tk_ui()
        
        # Position and show
        self._position_window()
        self.root.update_idletasks()
        self.root.after(10, self._show_and_focus)
    
    def _build_ctk_ui(self):
        """Build CustomTkinter UI."""
        # Main container with rounded corners
        main_frame = ctk.CTkFrame(
            self.root,
            corner_radius=12,
            fg_color=self.colors.base,
            border_color=self.colors.surface2,
            border_width=1
        )
        main_frame.pack(fill="both", expand=True, padx=1, pady=1)
        
        content = ctk.CTkFrame(main_frame, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=12, pady=12)
        
        # Top bar with close button
        top_bar = ctk.CTkFrame(content, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 10))
        
        # Title with proper emoji rendering
        title_content = prepare_emoji_content("📷 Screen Capture", size=16)
        title_label = ctk.CTkLabel(
            top_bar,
            text=title_content["text"],
            image=title_content.get("image"),
            compound=title_content.get("compound") or "left",
            font=get_ctk_font(size=13, weight="bold"),
            text_color=self.colors.text
        )
        title_label.pack(side="left")
        
        # Close button
        close_btn = ctk.CTkButton(
            top_bar,
            text="×",
            width=28,
            height=28,
            corner_radius=6,
            fg_color="transparent",
            hover_color=self.colors.red,
            text_color=self.colors.overlay0,
            font=get_ctk_font(size=16, weight="bold"),
            command=self._close
        )
        close_btn.pack(side="right")
        
        # Image preview and input row
        preview_row = ctk.CTkFrame(content, fg_color="transparent")
        preview_row.pack(fill="x", pady=(0, 10))
        
        # Thumbnail container with resolution text below
        thumb_container = ctk.CTkFrame(preview_row, fg_color="transparent")
        thumb_container.pack(side="left", padx=(0, 12))
        
        # Thumbnail frame
        thumb_frame = ctk.CTkFrame(
            thumb_container,
            fg_color=self.colors.surface0,
            corner_radius=8,
            width=self.THUMBNAIL_MAX_SIZE[0] + 10,
            height=self.THUMBNAIL_MAX_SIZE[1] + 10
        )
        thumb_frame.pack(side="top")
        thumb_frame.pack_propagate(False)
        
        self._create_thumbnail(thumb_frame)
        
        # Resolution text below thumbnail
        info_text = f"{self.capture_result.width} × {self.capture_result.height} px"
        ctk.CTkLabel(
            thumb_container,
            text=info_text,
            font=get_ctk_font(size=10),
            text_color=self.colors.overlay0
        ).pack(side="top", pady=(4, 0))
        
        # Right side: source selector and input
        right_side = ctk.CTkFrame(preview_row, fg_color="transparent")
        right_side.pack(side="left", fill="both", expand=True)
        
        # Source selector
        source_frame = ctk.CTkFrame(right_side, fg_color="transparent")
        source_frame.pack(fill="x", pady=(0, 8))
        
        # Dropdown for action source
        sources = ["Snip Actions"]
        if "text_edit_tool" in self.prompts_config:
            sources.append("Text Edit Actions")
        if self.file_processor_prompts:
            sources.append("File Processor")
        
        self.source_var = tk.StringVar(value=sources[0])
        self.source_dropdown = ctk.CTkOptionMenu(
            source_frame,
            values=sources,
            variable=self.source_var,
            command=self._on_source_changed,
            height=28,
            corner_radius=6,
            fg_color=self.colors.surface0,
            button_color=self.colors.surface1,
            button_hover_color=self.colors.surface2,
            dropdown_fg_color=self.colors.surface0,
            dropdown_hover_color=self.colors.surface1,
            text_color=self.colors.text,
            font=get_ctk_font(size=11)
        )
        self.source_dropdown.pack(side="left", fill="x", expand=True)
        Tooltip(self.source_dropdown, "Select action source category")
        
        # Connection profile dropdown (only if profiles exist)
        self.profile_var, self.profile_dropdown, profile_frame = create_profile_dropdown_ctk(right_side, self.colors)
        if profile_frame:
            profile_frame.pack(fill="x", pady=(0, 8))

        # Response mode toggle
        toggle_frame = ctk.CTkFrame(right_side, fg_color="transparent")
        toggle_frame.pack(fill="x", pady=(0, 8))
        
        self.response_toggle = SegmentedToggle(
            toggle_frame,
            options=[("Default", "default"), ("Copy", "copy"), ("Show", "show"), ("Type", "type")],
            default_value="default",
            tooltips={
                "Default": "Use the action's configured response mode",
                "Copy": "Copy the response to clipboard",
                "Show": "Show the response in a chat window",
                "Type": "Type the response into the active window"
            }
        )
        self.response_toggle.pack(anchor="center")
        
        # Custom input with send button
        input_frame = ctk.CTkFrame(
            right_side,
            fg_color=self.colors.surface0,
            corner_radius=8,
            border_color=self.colors.surface2,
            border_width=1
        )
        input_frame.pack(fill="x")
        
        self.input_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text=self.PLACEHOLDER,
            font=get_ctk_font(size=12),
            height=38,
            corner_radius=0,
            fg_color="transparent",
            border_width=0,
            text_color=self.colors.text,
            placeholder_text_color=self.colors.overlay0
        )
        
        # Send button container
        send_container = ctk.CTkFrame(input_frame, width=38, height=38, fg_color="transparent")
        send_container.pack(side="right")
        send_container.pack_propagate(False)
        
        send_btn = create_emoji_button(
            send_container,
            text="",
            icon="➤",
            colors=self.colors,
            variant="primary",
            width=38,
            height=38,
            font_size=14,
            command=self._on_custom_submit
        )
        send_btn.configure(corner_radius=8)
        send_btn.pack(fill="both", expand=True)
        
        self.input_entry.pack(side="left", fill="x", expand=True, padx=(10, 0))
        self.input_entry.bind('<Return>', lambda e: self._on_custom_submit())
        
        Tooltip(send_btn, "Ask a question about this image")
        
        # Compare Mode checkbox row
        compare_row = ctk.CTkFrame(right_side, fg_color="transparent")
        compare_row.pack(fill="x", pady=(8, 0))
        
        self.compare_var = tk.BooleanVar(value=False)
        self.compare_checkbox = ctk.CTkCheckBox(
            compare_row,
            text="Compare Mode",
            variable=self.compare_var,
            command=self._on_compare_mode_changed,
            font=get_ctk_font(size=11),
            text_color=self.colors.overlay0,
            fg_color=self.colors.blue,
            hover_color=self.colors.lavender,
            border_color=self.colors.surface2,
            checkmark_color=self.colors.base,
            width=20,
            height=20
        )
        self.compare_checkbox.pack(side="left")
        Tooltip(self.compare_checkbox, "Enable to capture a second image for comparison")
        
        # Compare capture indicator (hidden initially)
        self.compare_indicator = ctk.CTkLabel(
            compare_row,
            text="",
            font=get_ctk_font(size=10),
            text_color=self.colors.green
        )
        self.compare_indicator.pack(side="left", padx=(8, 0))
        
        # Modifier bar (get from global settings)
        global_modifiers = get_prompts_config().get_modifiers()
        default_active = get_prompts_config().get_default_modifier_keys_for_tool("snip_tool")
        if global_modifiers:
            self.modifier_bar = ModifierBar(
                content,
                modifiers=global_modifiers,
                on_change=self._on_modifiers_changed,
                default_active=default_active
            )
            self.modifier_bar.pack(fill="x", pady=(0, 8))
        
        # Actions area
        self.actions_frame = ctk.CTkFrame(content, fg_color="transparent")
        self.actions_frame.pack(fill="both", expand=True)
        
        self._create_action_buttons()
    
    def _build_tk_ui(self):
        """Build standard Tkinter UI (fallback)."""
        self.root.configure(bg=self.colors.base)
        
        main_frame = tk.Frame(
            self.root,
            bg=self.colors.base,
            highlightbackground=self.colors.surface2,
            highlightthickness=1
        )
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        content = tk.Frame(main_frame, bg=self.colors.base)
        content.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        
        # Top bar
        top_bar = tk.Frame(content, bg=self.colors.base)
        top_bar.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(
            top_bar,
            text="📷 Screen Capture",
            font=("Arial", 12, "bold"),
            bg=self.colors.base,
            fg=self.colors.text
        ).pack(side=tk.LEFT)
        
        close_btn = tk.Label(
            top_bar,
            text="×",
            font=("Arial", 16, "bold"),
            bg=self.colors.base,
            fg=self.colors.overlay0,
            cursor="hand2"
        )
        close_btn.pack(side=tk.RIGHT)
        close_btn.bind('<Button-1>', lambda e: self._close())
        close_btn.bind('<Enter>', lambda e: close_btn.config(fg=self.colors.red))
        close_btn.bind('<Leave>', lambda e: close_btn.config(fg=self.colors.overlay0))
        
        # Preview row
        preview_row = tk.Frame(content, bg=self.colors.base)
        preview_row.pack(fill=tk.X, pady=(0, 10))
        
        # Thumbnail container with resolution text below
        thumb_container = tk.Frame(preview_row, bg=self.colors.base)
        thumb_container.pack(side=tk.LEFT, padx=(0, 12))
        
        # Thumbnail frame
        thumb_frame = tk.Frame(
            thumb_container,
            bg=self.colors.surface0,
            width=self.THUMBNAIL_MAX_SIZE[0] + 10,
            height=self.THUMBNAIL_MAX_SIZE[1] + 10,
            highlightbackground=self.colors.surface2,
            highlightthickness=1
        )
        thumb_frame.pack(side=tk.TOP)
        thumb_frame.pack_propagate(False)
        
        self._create_thumbnail_tk(thumb_frame)
        
        # Resolution text below thumbnail
        info_text = f"{self.capture_result.width} × {self.capture_result.height} px"
        tk.Label(
            thumb_container,
            text=info_text,
            font=("Arial", 9),
            bg=self.colors.base,
            fg=self.colors.overlay0
        ).pack(side=tk.TOP, pady=(4, 0))
        
        # Right side
        right_side = tk.Frame(preview_row, bg=self.colors.base)
        right_side.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Source selector (simplified for tk)
        source_frame = tk.Frame(right_side, bg=self.colors.base)
        source_frame.pack(fill=tk.X, pady=(0, 8))
        
        # For tk, use a simple label toggle instead of dropdown
        self.source_label = tk.Label(
            source_frame,
            text="[Snip Actions]",
            font=("Arial", 10, "bold"),
            bg=self.colors.surface0,
            fg=self.colors.text,
            padx=10,
            pady=4,
            cursor="hand2"
        )
        self.source_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.source_label.bind('<Button-1>', self._toggle_source_tk)
        Tooltip(self.source_label, "Select action source category")
        
        # Connection profile dropdown (only if profiles exist)
        self.profile_var, self.profile_dropdown, profile_frame = create_profile_dropdown_tk(right_side, self.root, self.colors)
        if profile_frame:
            profile_frame.pack(fill=tk.X, pady=(0, 8))
        
        # Response mode toggle
        toggle_frame = tk.Frame(right_side, bg=self.colors.base)
        toggle_frame.pack(fill=tk.X, pady=(0, 8))
        
        self.response_toggle = SegmentedToggle(
            toggle_frame,
            options=[("Default", "default"), ("Copy", "copy"), ("Show", "show"), ("Type", "type")],
            default_value="default",
            tooltips={
                "Default": "Use the action's configured response mode",
                "Copy": "Copy the response to clipboard",
                "Show": "Show the response in a chat window",
                "Type": "Type the response into the active window"
            }
        )
        self.response_toggle.pack(anchor=tk.CENTER)
        
        # Input
        input_container = tk.Frame(
            right_side,
            bg=self.colors.surface0,
            highlightbackground=self.colors.surface2,
            highlightthickness=1
        )
        input_container.pack(fill=tk.X)
        
        self.input_var = tk.StringVar(master=self.root)
        self.input_entry = tk.Entry(
            input_container,
            textvariable=self.input_var,
            font=("Arial", 11),
            bg=self.colors.surface0,
            fg=self.colors.text,
            insertbackground=self.colors.text,
            relief=tk.FLAT,
            bd=0
        )
        self.input_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.input_entry.insert(0, self.PLACEHOLDER)
        self.input_entry.config(fg=self.colors.overlay0)
        
        self.input_entry.bind('<FocusIn>', self._on_input_focus_in)
        self.input_entry.bind('<FocusOut>', self._on_input_focus_out)
        self.input_entry.bind('<Return>', lambda e: self._on_custom_submit())
        
        # Send button
        send_btn = tk.Label(
            input_container,
            text="➤",
            font=("Arial", 14),
            bg=self.colors.blue,
            fg="#ffffff",
            padx=12,
            pady=8,
            cursor="hand2"
        )
        send_btn.pack(side=tk.RIGHT, fill=tk.Y)
        send_btn.bind('<Button-1>', lambda e: self._on_custom_submit())
        send_btn.bind('<Enter>', lambda e: send_btn.config(bg=self.colors.lavender))
        send_btn.bind('<Leave>', lambda e: send_btn.config(bg=self.colors.blue))
        
        # Compare Mode checkbox row (tk version)
        compare_row = tk.Frame(right_side, bg=self.colors.base)
        compare_row.pack(fill=tk.X, pady=(8, 0))
        
        self.compare_var = tk.BooleanVar(value=False)
        self.compare_checkbox = tk.Checkbutton(
            compare_row,
            text="Compare Mode",
            variable=self.compare_var,
            command=self._on_compare_mode_changed,
            font=("Arial", 10),
            bg=self.colors.base,
            fg=self.colors.overlay0,
            activebackground=self.colors.base,
            activeforeground=self.colors.text,
            selectcolor=self.colors.surface0
        )
        self.compare_checkbox.pack(side=tk.LEFT)
        
        # Compare capture indicator (hidden initially)
        self.compare_indicator = tk.Label(
            compare_row,
            text="",
            font=("Arial", 9),
            bg=self.colors.base,
            fg=self.colors.green
        )
        self.compare_indicator.pack(side=tk.LEFT, padx=(8, 0))
        
        # Modifier bar (get from global settings) - tk version
        global_modifiers = get_prompts_config().get_modifiers()
        default_active = get_prompts_config().get_default_modifier_keys_for_tool("snip_tool")
        if global_modifiers:
            self.modifier_bar = ModifierBar(
                content,
                modifiers=global_modifiers,
                on_change=self._on_modifiers_changed,
                default_active=default_active
            )
            self.modifier_bar.pack(fill=tk.X, pady=(10, 0))
        
        # Actions area
        self.actions_frame = tk.Frame(content, bg=self.colors.base)
        self.actions_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        self._create_action_buttons()
    
    def _create_thumbnail(self, parent):
        """Create clickable thumbnail preview (CTk version)."""
        if not self.capture_result.pil_image:
            # Create placeholder
            ctk.CTkLabel(
                parent,
                text="🖼️",
                font=get_ctk_font(size=32),
                text_color=self.colors.overlay0
            ).pack(expand=True)
            return
        
        try:
            # Create thumbnail
            thumb = self.capture_result.pil_image.copy()
            thumb.thumbnail(self.THUMBNAIL_MAX_SIZE, Image.Resampling.LANCZOS)
            self.thumbnail_photo = ImageTk.PhotoImage(thumb)
            
            # Display in label (use tk.Label for image display with click handler)
            label = tk.Label(
                parent,
                image=self.thumbnail_photo,
                bg=self.colors.surface0,
                cursor="hand2"  # Show clickable cursor
            )
            label.pack(expand=True)
            
            # Bind click to show enlarged image
            label.bind('<Button-1>', self._on_thumbnail_click)
            Tooltip(label, "Click to view full size")
            
        except Exception as e:
            logging.error(f"[SnipPopup] Thumbnail error: {e}")
            ctk.CTkLabel(
                parent,
                text="🖼️",
                font=get_ctk_font(size=32),
                text_color=self.colors.overlay0
            ).pack(expand=True)
    
    def _create_thumbnail_tk(self, parent):
        """Create clickable thumbnail preview (tk version)."""
        if not self.capture_result.pil_image:
            tk.Label(
                parent,
                text="🖼️",
                font=("Arial", 24),
                bg=self.colors.surface0,
                fg=self.colors.overlay0
            ).pack(expand=True)
            return
        
        try:
            thumb = self.capture_result.pil_image.copy()
            thumb.thumbnail(self.THUMBNAIL_MAX_SIZE, Image.Resampling.LANCZOS)
            self.thumbnail_photo = ImageTk.PhotoImage(thumb)
            
            label = tk.Label(
                parent,
                image=self.thumbnail_photo,
                bg=self.colors.surface0,
                cursor="hand2"  # Show clickable cursor
            )
            label.pack(expand=True)
            
            # Bind click to show enlarged image
            label.bind('<Button-1>', self._on_thumbnail_click)
            
        except Exception as e:
            logging.error(f"[SnipPopup] Thumbnail error: {e}")
            tk.Label(
                parent,
                text="🖼️",
                font=("Arial", 24),
                bg=self.colors.surface0,
                fg=self.colors.overlay0
            ).pack(expand=True)
    
    def _on_thumbnail_click(self, event):
        """Show enlarged image in a modal window."""
        if not self.capture_result.pil_image:
            return
        
        try:
            # Get original image
            img = self.capture_result.pil_image.copy()
            orig_width, orig_height = img.size
            
            # Scale to fit screen (max 80% of screen size)
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            max_w = int(screen_w * 0.8)
            max_h = int(screen_h * 0.8)
            
            if orig_width > max_w or orig_height > max_h:
                img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            
            photo = ImageTk.PhotoImage(img)
            
            # Create modal window
            if HAVE_CTK:
                modal = ctk.CTkToplevel(self.root)
                modal.configure(fg_color=self.colors.base)
            else:
                modal = tk.Toplevel(self.root)
                modal.configure(bg=self.colors.base)
            
            modal.title("Image Preview")
            modal.transient(self.root)
            modal.attributes('-topmost', True)
            modal.overrideredirect(True)  # No window decorations for cleaner look
            
            # Center on screen
            modal.update_idletasks()
            w = photo.width() + 20
            h = photo.height() + 60
            x = (screen_w - w) // 2
            y = (screen_h - h) // 2
            modal.geometry(f"{w}x{h}+{x}+{y}")
            
            # Main container
            if HAVE_CTK:
                container = ctk.CTkFrame(modal, fg_color=self.colors.base, corner_radius=12)
                container.pack(fill="both", expand=True, padx=2, pady=2)
            else:
                container = tk.Frame(modal, bg=self.colors.base)
                container.pack(fill=tk.BOTH, expand=True)
            
            # Display image
            img_label = tk.Label(container, image=photo, bg=self.colors.base)
            img_label.image = photo  # Keep reference
            img_label.pack(padx=10, pady=10)
            
            # Resolution info and close button row
            if HAVE_CTK:
                bottom_row = ctk.CTkFrame(container, fg_color="transparent")
                bottom_row.pack(fill="x", padx=10, pady=(0, 10))
                
                ctk.CTkLabel(
                    bottom_row,
                    text=f"{orig_width} × {orig_height} px",
                    font=get_ctk_font(size=11),
                    text_color=self.colors.overlay0
                ).pack(side="left")
                
                close_btn = ctk.CTkButton(
                    bottom_row,
                    text="Close",
                    command=modal.destroy,
                    width=80,
                    height=28,
                    corner_radius=6,
                    **get_ctk_button_colors(self.colors, "secondary")
                )
                close_btn.pack(side="right")
            else:
                bottom_row = tk.Frame(container, bg=self.colors.base)
                bottom_row.pack(fill=tk.X, padx=10, pady=(0, 10))
                
                tk.Label(
                    bottom_row,
                    text=f"{orig_width} × {orig_height} px",
                    font=("Arial", 10),
                    bg=self.colors.base,
                    fg=self.colors.overlay0
                ).pack(side=tk.LEFT)
                
                close_btn = tk.Button(
                    bottom_row,
                    text="Close",
                    command=modal.destroy,
                    bg=self.colors.surface0,
                    fg=self.colors.text,
                    relief=tk.FLAT,
                    padx=10,
                    pady=4
                )
                close_btn.pack(side=tk.RIGHT)
            
            # Close on Escape or click outside
            modal.bind("<Escape>", lambda e: modal.destroy())
            img_label.bind("<Button-1>", lambda e: modal.destroy())
            modal.focus_set()
            modal.grab_set()  # Modal behavior
            
        except Exception as e:
            logging.error(f"[SnipPopup] Failed to show image preview: {e}")
    
    def _create_action_buttons(self):
        """Create action buttons based on current source."""
        # Clear existing
        for widget in self.actions_frame.winfo_children():
            widget.destroy()
        
        # Handle File Processor source separately
        if self.action_source == "file_processor":
            self._create_file_processor_buttons()
            return
        
        # Get actions for current source
        if self.action_source == "snip":
            config = self.prompts_config.get("snip_tool", {})
        else:
            config = self.prompts_config.get("text_edit_tool", {})
        
        settings = config.get("_settings", {})
        use_groups = settings.get("popup_use_groups", True)
        popup_groups = settings.get("popup_groups", [])
        
        # Only use groups if popup_use_groups is True AND groups are defined
        if use_groups and popup_groups:
            groups = []
            for group_def in popup_groups:
                if not group_def.get("enabled", True):
                    continue
                group_name = group_def.get("name", "")
                item_keys = group_def.get("items", [])
                
                items = []
                for key in item_keys:
                    action = config.get(key)
                    if action and not key.startswith("_"):
                        icon = action.get("icon", "")
                        tooltip = action.get("task", "")
                        items.append((key, key, icon, tooltip))
                
                if items:
                    groups.append({"name": group_name, "items": items})
            
            if groups:
                self.carousel = GroupedButtonList(
                    self.actions_frame,
                    groups=groups,
                    on_click=self._on_action_click,
                    on_group_changed=self._reposition_window
                )
                self.carousel.pack(fill="both" if HAVE_CTK else tk.BOTH, expand=True)
                return
        
        # Flat carousel (when popup_use_groups is False or no groups defined)
        items_per_page = settings.get("popup_items_per_page", 6)
        items = []
        
        for key, action in config.items():
            if key.startswith("_"):
                continue
            if not isinstance(action, dict):
                continue
            
            icon = action.get("icon", "")
            tooltip = action.get("task", "")
            items.append((key, key, icon, tooltip))
        
        if items:
            self.carousel = CarouselButtonList(
                self.actions_frame,
                items=items,
                on_click=self._on_action_click,
                items_per_page=items_per_page
            )
            self.carousel.pack(fill="both" if HAVE_CTK else tk.BOTH, expand=True)
    
    def _create_file_processor_buttons(self):
        """Create action buttons for File Processor prompts."""
        items = []
        for key, prompt in self.file_processor_prompts.items():
            if key.startswith("_"):
                continue
            icon = prompt.get("icon", "📄")
            tooltip = prompt.get("description", "")
            items.append((key, key, icon, tooltip))
        
        if items:
            self.carousel = CarouselButtonList(
                self.actions_frame,
                items=items,
                on_click=self._on_action_click,
                items_per_page=6
            )
            self.carousel.pack(fill="both" if HAVE_CTK else tk.BOTH, expand=True)
    
    def _on_source_changed(self, value: str):
        """Handle action source dropdown change."""
        if "Text Edit" in value:
            self.action_source = "text_edit"
        elif "File Processor" in value:
            self.action_source = "file_processor"
        else:
            self.action_source = "snip"
        
        self._create_action_buttons()
        self._reposition_window()
    
    def _toggle_source_tk(self, event):
        """Toggle action source (tk fallback)."""
        # Cycle through available sources
        if self.action_source == "snip":
            if "text_edit_tool" in self.prompts_config:
                self.action_source = "text_edit"
                self.source_label.config(text="[Text Edit Actions]")
            elif self.file_processor_prompts:
                self.action_source = "file_processor"
                self.source_label.config(text="[File Processor]")
        elif self.action_source == "text_edit":
            if self.file_processor_prompts:
                self.action_source = "file_processor"
                self.source_label.config(text="[File Processor]")
            else:
                self.action_source = "snip"
                self.source_label.config(text="[Snip Actions]")
        else:  # file_processor
            self.action_source = "snip"
            self.source_label.config(text="[Snip Actions]")
        
        self._create_action_buttons()
        self._reposition_window()
    
    def _on_modifiers_changed(self, active_modifiers: List[str]):
        """Handle modifier toggle changes."""
        self.active_modifiers = active_modifiers
    
    def _on_compare_mode_changed(self):
        """Handle Compare Mode checkbox toggle."""
        self.compare_mode_enabled = self.compare_var.get()
        
        # If enabling and we have a callback for second capture
        if self.compare_mode_enabled and self.on_request_compare_capture and not self.compare_capture:
            self._initiate_compare_capture()
        elif not self.compare_mode_enabled:
            # Clear compare capture when disabling
            self.compare_capture = None
            self._update_compare_indicator()
    
    def _initiate_compare_capture(self):
        """Initiate second capture for comparison."""
        if not self.on_request_compare_capture:
            return
        
        # Hide popup temporarily
        self.root.withdraw()
        
        # Request second capture
        self.on_request_compare_capture(
            self._on_compare_captured,
            self._on_compare_cancelled
        )
    
    def _on_compare_captured(self, capture_result: CaptureResult):
        """Handle second capture completion."""
        self.compare_capture = capture_result
        self._update_compare_indicator()
        
        # If we have a pending action, execute it directly without re-showing popup
        if self._pending_action:
            source, action_key, custom_input = self._pending_action
            self._pending_action = None
            self._execute_action(source, action_key, custom_input)
        else:
            # No pending action - show popup again for user to select action
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
    
    def _on_compare_cancelled(self):
        """Handle cancellation of second capture."""
        # Uncheck compare mode since capture was cancelled
        self.compare_var.set(False)
        self.compare_mode_enabled = False
        self.compare_capture = None
        self._update_compare_indicator()
        
        # Show popup again
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        
        # Clear pending action
        self._pending_action = None
    
    def _update_compare_indicator(self):
        """Update the compare capture indicator text."""
        if self.compare_capture:
            text = f"✓ 2nd image: {self.compare_capture.width}×{self.compare_capture.height}px"
        else:
            text = ""
        
        if HAVE_CTK and hasattr(self.compare_indicator, 'configure'):
            self.compare_indicator.configure(text=text)
        else:
            self.compare_indicator.config(text=text)
    
    def _on_action_click(self, action_key: str):
        """Handle action button click."""
        # Check if this action has compare_prompts flag
        action_requires_compare = self._action_requires_compare(action_key)
        
        # If action requires compare and we don't have second capture yet, trigger it
        if action_requires_compare and not self.compare_capture and self.on_request_compare_capture:
            self._pending_action = (self.action_source, action_key, None)
            self.compare_var.set(True)
            self.compare_mode_enabled = True
            self._initiate_compare_capture()
            return
        
        self._execute_action(self.action_source, action_key, None)
    
    def _action_requires_compare(self, action_key: str) -> bool:
        """Check if action has compare_prompts: true flag."""
        if self.action_source == "snip":
            config = self.prompts_config.get("snip_tool", {})
            action = config.get(action_key, {})
            return action.get("compare_prompts", False)
        return False
    
    def _execute_action(self, source: str, action_key: str, custom_input: Optional[str]):
        """Execute the action with current state."""
        response_mode = self.response_toggle.get() if hasattr(self, 'response_toggle') and self.response_toggle else "default"
        
        profile_override = get_profile_override_value(self.profile_var)
        self._close()
        # on_action signature: (source, action_key, custom_input, active_modifiers, compare_mode, compare_capture, response_mode, profile_override)
        self.on_action(
            source,
            action_key,
            custom_input,
            self.active_modifiers,
            self.compare_mode_enabled,
            self.compare_capture,
            response_mode,
            profile_override
        )
    
    def _on_custom_submit(self):
        """Handle custom question submission."""
        if HAVE_CTK:
            text = self.input_entry.get().strip()
        else:
            text = self.input_var.get().strip() if hasattr(self, 'input_var') else ""
        
        if not text or text == self.PLACEHOLDER:
            return
        
        # If compare mode enabled and we don't have second capture, trigger it
        if self.compare_mode_enabled and not self.compare_capture and self.on_request_compare_capture:
            self._pending_action = (self.action_source, "_Custom", text)
            self._initiate_compare_capture()
            return
        
        self._execute_action(self.action_source, "_Custom", text)
    
    def _on_input_focus_in(self, event):
        """Handle input focus in (tk fallback)."""
        if self.input_entry.get() == self.PLACEHOLDER:
            self.input_entry.delete(0, tk.END)
            self.input_entry.config(fg=self.colors.text)
    
    def _on_input_focus_out(self, event):
        """Handle input focus out (tk fallback)."""
        if not self.input_entry.get():
            self.input_entry.insert(0, self.PLACEHOLDER)
            self.input_entry.config(fg=self.colors.overlay0)
    
    def _position_window(self):
        """Position the window."""
        self.root.update_idletasks()
        
        x = self.x
        y = self.y
        if x is None or y is None:
            x = self.root.winfo_pointerx()
            y = self.root.winfo_pointery() + 20
        
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = self.root.winfo_reqwidth()
        window_height = self.root.winfo_reqheight()
        
        # Ensure window stays on screen
        if x + window_width > screen_width:
            x = screen_width - window_width - 10
        if y + window_height > screen_height:
            y = screen_height - window_height - 10
        
        x = max(10, x)
        y = max(10, y)
        
        self.root.geometry(f"+{x}+{y}")
    
    def _reposition_window(self):
        """Reposition after content changes."""
        if not self.root:
            return
        
        self.root.update_idletasks()
        
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = self.root.winfo_reqwidth()
        window_height = self.root.winfo_reqheight()
        
        if x + window_width > screen_width:
            x = screen_width - window_width - 10
        if y + window_height > screen_height:
            y = screen_height - window_height - 10
        
        x = max(10, x)
        y = max(10, y)
        
        self.root.geometry(f"+{x}+{y}")
    
    def _show_and_focus(self):
        """Show window after UI is built."""
        if not self.root:
            return
        
        try:
            self.root.deiconify()
            self.root.bind('<Escape>', lambda e: self._close())
            self.root.lift()
            self.root.focus_force()
            
            if HAVE_CTK:
                self.input_entry.focus_set()
        except tk.TclError:
            pass
    
    def _close(self):
        """Close the popup."""
        if self.root:
            try:
                self.root.destroy()
            except tk.TclError:
                pass
            self.root = None

        # Neutralize tkinter Variables AFTER root.destroy() so that CTk
        # widgets can still call trace_remove() during their own destroy().
        # Setting _tk = None makes Variable.__del__ a no-op, preventing
        # "RuntimeError: main thread is not in main loop" when the popup
        # object is later GC'd on a background thread.
        for attr_name in ('source_var', 'compare_var', 'input_var', 'profile_var'):
            var = getattr(self, attr_name, None)
            if isinstance(var, tk.Variable):
                _neutralize_tk_var(var)

        # Release all widget references so that any CTk-internal tk.Variable
        # objects are also GC'd NOW (on the main thread) rather than later on
        # a background thread where their __del__ would crash.
        self.source_dropdown = None
        self.input_entry = None
        self.compare_checkbox = None
        self.compare_indicator = None
        self.carousel = None
        self.modifier_bar = None
        self.response_toggle = None
        self.profile_var = None
        self.profile_dropdown = None
        self.thumbnail_photo = None
        self.source_var = None
        self.compare_var = None
        if hasattr(self, 'input_var'):
            self.input_var = None
        if hasattr(self, 'source_label'):
            self.source_label = None

        # Force immediate collection of any CTk-internal Variables that
        # survive in circular references (CTk widgets <-> callbacks <-> vars).
        # Without this, GC may defer collection to a background thread.
        gc.collect()

        if self.on_close_callback:
            self.on_close_callback()


def create_attached_snip_popup(
    parent_root: tk.Tk,
    capture_result: CaptureResult,
    prompts_config: Dict[str, Any],
    on_action: Callable[[str, str, Optional[str], List[str], bool, Optional[CaptureResult]], None],
    on_close: Optional[Callable[[], None]] = None,
    on_request_compare_capture: Optional[Callable[[Callable[[CaptureResult], None], Callable[[], None]], None]] = None,
    x: Optional[int] = None,
    y: Optional[int] = None
) -> AttachedSnipPopup:
    """
    Create a snip popup attached to the GUI coordinator's root.
    
    Args:
        parent_root: Parent Tk root
        capture_result: Captured image data
        prompts_config: Combined prompts configuration
        on_action: Callback for action selection (source, action_key, custom_input, active_modifiers, compare_mode, compare_capture)
        on_close: Callback when popup closes
        on_request_compare_capture: Callback to request second capture for comparison
        x, y: Position coordinates
        
    Returns:
        The created popup instance
    """
    return AttachedSnipPopup(
        parent_root, capture_result, prompts_config,
        on_action, on_close, on_request_compare_capture, x, y
    )