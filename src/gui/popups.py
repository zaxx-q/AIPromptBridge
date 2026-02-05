#!/usr/bin/env python3
"""
Popup windows for TextEditTool - input and prompt selection

Threading Note:
    Popups are shown from hotkey threads and create their own Tk roots.
    To avoid conflicts with other Tk instances (like session browser),
    we use a polling update loop instead of blocking mainloop().

Design:
    Modern themed color scheme with CustomTkinter widgets:
    - Segmented toggle for response mode selection
    - Carousel-based action buttons with pagination
    - Icon support for action buttons
    - Multiple theme support via ThemeRegistry
"""

import logging
import math
import sys
import time
import tkinter as tk
from typing import Callable, Optional, Dict, List, Tuple

# Windows-specific imports for transparent windows
if sys.platform == "win32":
    try:
        import ctypes
        from ctypes import wintypes
        HAVE_WIN32 = True
    except ImportError:
        HAVE_WIN32 = False
else:
    HAVE_WIN32 = False

# Import CustomTkinter with fallback
from .platform import HAVE_CTK, ctk

# Import theme system
from .themes import (
    ThemeRegistry, ThemeColors,
    get_colors as _get_theme_colors,
    is_dark_mode, get_ctk_font,
    get_ctk_button_colors, get_ctk_frame_colors,
    get_ctk_entry_colors, sync_ctk_appearance,
    # Legacy compatibility classes (deprecated but kept for transition)
    CatppuccinMocha, CatppuccinLatte
)

from .utils import hide_from_taskbar
from .custom_widgets import create_emoji_button

# Import emoji renderer for CTkImage support (Windows color emoji fix)
try:
    from .emoji_renderer import get_emoji_renderer, HAVE_PIL
    HAVE_EMOJI = HAVE_PIL and HAVE_CTK
except ImportError:
    HAVE_EMOJI = False
    get_emoji_renderer = None


def get_colors() -> ThemeColors:
    """
    Get the current theme colors.
    
    Returns ThemeColors dataclass based on current config and system theme.
    This function provides the same interface as before but now uses
    the centralized theme registry.
    """
    return _get_theme_colors()


# Transparency color for Windows (must be a color not used in UI)
TRANSPARENCY_COLOR = "#010101"  # Near-black that won't appear in themes


def setup_transparent_popup(window, colors: ThemeColors):
    """
    Set up a popup window with transparency for rounded corners.
    
    On Windows, uses -transparentcolor attribute for the corners.
    Sets the root background to the transparency color.
    
    Args:
        window: The Tk/CTk window
        colors: Theme colors for reference
    """
    if sys.platform == "win32":
        try:
            # Set the transparency color - this color will be see-through
            window.attributes('-transparentcolor', TRANSPARENCY_COLOR)
            # Configure root bg to transparency color (corners will be transparent)
            if HAVE_CTK:
                window.configure(fg_color=TRANSPARENCY_COLOR)
            else:
                window.configure(bg=TRANSPARENCY_COLOR)
        except tk.TclError:
            # Fallback if transparency not supported
            if HAVE_CTK:
                window.configure(fg_color=colors.base)
            else:
                window.configure(bg=colors.base)
    else:
        # On other platforms, just set the background
        if HAVE_CTK:
            window.configure(fg_color=colors.base)
        else:
            window.configure(bg=colors.base)


# =============================================================================
# Custom UI Components (CustomTkinter-based)
# =============================================================================

class SegmentedToggle:
    """
    A segmented control for selecting between options.
    Similar to iOS/macOS segmented controls.
    Uses CTkSegmentedButton when available.
    """
    
    def __init__(
        self,
        parent,
        options: List[Tuple[str, str]],  # [(display_text, value), ...]
        default_value: str = None,
        on_change: Optional[Callable[[str], None]] = None
    ):
        self.parent = parent
        self.options = options
        self.on_change = on_change
        self.current_value = default_value or options[0][1]
        
        self.colors = get_colors()
        self.frame = None
        self.segments: List = []
        
        self._create_widget()
    
    def _create_widget(self):
        """Create the segmented toggle widget."""
        if HAVE_CTK:
            # Use CTkSegmentedButton for modern look
            values = [text for text, _ in self.options]
            self.value_map = {text: value for text, value in self.options}
            self.reverse_map = {value: text for text, value in self.options}
            
            self.frame = ctk.CTkSegmentedButton(
                self.parent,
                values=values,
                command=self._on_ctk_select,
                font=get_ctk_font(size=11),
                corner_radius=6,
                fg_color=self.colors.surface0,
                selected_color=self.colors.blue,
                selected_hover_color=self.colors.lavender,
                unselected_color=self.colors.surface0,
                unselected_hover_color=self.colors.surface1,
                text_color=self.colors.fg,
                text_color_disabled=self.colors.overlay0
            )
            
            # Set initial value
            initial_text = self.reverse_map.get(self.current_value, values[0])
            self.frame.set(initial_text)
        else:
            # Fallback to tk.Frame with labels
            self.frame = tk.Frame(
                self.parent,
                bg=self.colors.surface0,
                highlightbackground=self.colors.surface2,
                highlightthickness=1
            )
            
            for i, (display_text, value) in enumerate(self.options):
                is_selected = value == self.current_value
                
                segment = tk.Label(
                    self.frame,
                    text=display_text,
                    font=("Arial", 9),
                    bg=self.colors.blue if is_selected else self.colors.surface0,
                    fg="#ffffff" if is_selected else self.colors.text,
                    padx=12,
                    pady=4,
                    cursor="hand2"
                )
                segment.pack(side=tk.LEFT)
                segment.bind('<Button-1>', lambda e, v=value: self._on_click(v))
                segment.bind('<Enter>', lambda e, seg=segment, v=value: self._on_hover(seg, v, True))
                segment.bind('<Leave>', lambda e, seg=segment, v=value: self._on_hover(seg, v, False))
                
                self.segments.append(segment)
    
    def _on_ctk_select(self, selected_text: str):
        """Handle CTk segmented button selection."""
        value = self.value_map.get(selected_text, "default")
        if value != self.current_value:
            self.current_value = value
            if self.on_change:
                self.on_change(value)
    
    def _on_click(self, value: str):
        """Handle segment click (tk fallback)."""
        if value != self.current_value:
            self.current_value = value
            self._update_segments()
            if self.on_change:
                self.on_change(value)
    
    def _on_hover(self, segment, value: str, entering: bool):
        """Handle hover effect (tk fallback)."""
        if value == self.current_value:
            return
        
        if entering:
            segment.config(bg=self.colors.surface1)
        else:
            segment.config(bg=self.colors.surface0)
    
    def _update_segments(self):
        """Update segment appearance (tk fallback)."""
        for segment, (_, value) in zip(self.segments, self.options):
            is_selected = value == self.current_value
            segment.config(
                bg=self.colors.blue if is_selected else self.colors.surface0,
                fg="#ffffff" if is_selected else self.colors.text
            )
    
    def get(self) -> str:
        """Get current value."""
        return self.current_value
    
    def pack(self, **kwargs):
        """Pack the widget."""
        self.frame.pack(**kwargs)


class Tooltip:
    """
    A tooltip that appears after hovering over a widget for a specified delay.
    Uses add='+' to not override existing event bindings.
    """
    
    DELAY_MS = 500
    
    def __init__(self, widget, text: str, delay_ms: int = None):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms or self.DELAY_MS
        self.tooltip_window: Optional[tk.Toplevel] = None
        self.after_id: Optional[str] = None
        self.colors = get_colors()
        
        self.widget.bind('<Enter>', self._on_enter, add='+')
        self.widget.bind('<Leave>', self._on_leave, add='+')
        self.widget.bind('<Button-1>', self._on_leave, add='+')
    
    def _on_enter(self, event):
        """Schedule tooltip display."""
        self._cancel_scheduled()
        self.after_id = self.widget.after(self.delay_ms, self._show_tooltip)
    
    def _on_leave(self, event=None):
        """Cancel scheduled tooltip or hide if visible."""
        self._cancel_scheduled()
        self._hide_tooltip()
    
    def _cancel_scheduled(self):
        """Cancel any scheduled tooltip display."""
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
    
    def _show_tooltip(self):
        """Display the tooltip."""
        if not self.text:
            return
        
        self.after_id = None
        
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        
        # Get the root window for the toplevel
        root = self.widget.winfo_toplevel()
        self.tooltip_window = tk.Toplevel(root)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_attributes('-topmost', True)
        
        # Apply transparency for rounded corners on Windows
        if sys.platform == "win32":
            try:
                self.tooltip_window.attributes('-transparentcolor', TRANSPARENCY_COLOR)
                self.tooltip_window.configure(bg=TRANSPARENCY_COLOR)
            except tk.TclError:
                pass
        
        if HAVE_CTK:
            frame = ctk.CTkFrame(
                self.tooltip_window,
                fg_color=self.colors.surface0,
                border_color=self.colors.surface2,
                border_width=1,
                corner_radius=6
            )
            frame.pack()
            
            label = ctk.CTkLabel(
                frame,
                text=self.text,
                font=get_ctk_font(size=10),
                text_color=self.colors.text,
                wraplength=300,
                justify="left"
            )
            label.pack(padx=10, pady=6)
        else:
            frame = tk.Frame(
                self.tooltip_window,
                bg=self.colors.surface0,
                highlightbackground=self.colors.surface2,
                highlightthickness=1
            )
            frame.pack()
            
            label = tk.Label(
                frame,
                text=self.text,
                font=("Arial", 9),
                bg=self.colors.surface0,
                fg=self.colors.text,
                padx=8,
                pady=4,
                wraplength=300,
                justify=tk.LEFT
            )
            label.pack()
        
        self.tooltip_window.wm_geometry(f"+{x}+{y}")
    
    def _hide_tooltip(self):
        """Hide the tooltip."""
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


class ModifierBar:
    """
    A horizontally scrollable bar of toggle buttons for modifiers.
    Supports mouse wheel scrolling for horizontal navigation.
    """
    
    def __init__(
        self,
        parent,
        modifiers: List[Dict],
        on_change: Optional[Callable[[List[str]], None]] = None
    ):
        self.parent = parent
        self.modifiers = modifiers
        self.on_change = on_change
        
        self.colors = get_colors()
        self.active_modifiers: set = set()
        self.buttons: Dict[str, object] = {}
        self.tooltips: List[Tooltip] = []
        
        self._create_widget()
    
    def _create_widget(self):
        """Create the scrollable modifier bar."""
        if HAVE_CTK:
            self.frame = ctk.CTkFrame(self.parent, fg_color="transparent")
            
            # Container with border
            self.container = ctk.CTkFrame(
                self.frame,
                fg_color=self.colors.mantle,
                corner_radius=8,
                height=52,
                border_color=self.colors.surface2,
                border_width=1
            )
            self.container.pack(fill="x", pady=(0, 8))
            self.container.pack_propagate(False)
            
            # Scrollable frame for buttons
            self.scroll_frame = ctk.CTkScrollableFrame(
                self.container,
                fg_color="transparent",
                orientation="horizontal",
                height=48
            )
            self.scroll_frame.pack(fill="both", expand=True, padx=4)
            
            # Bind events to various elements to catch all hover zones
            # Bind to container (bg)
            self.container.bind("<MouseWheel>", self._on_mousewheel_ctk)
            self.container.bind("<Button-4>", self._on_mousewheel_ctk)
            self.container.bind("<Button-5>", self._on_mousewheel_ctk)
            
            # Bind to scroll frame widget itself
            self.scroll_frame.bind("<MouseWheel>", self._on_mousewheel_ctk)
            self.scroll_frame.bind("<Button-4>", self._on_mousewheel_ctk)
            self.scroll_frame.bind("<Button-5>", self._on_mousewheel_ctk)
            
            # Bind events to the scroll frame's internal canvas
            if hasattr(self.scroll_frame, "_parent_canvas"):
                self.scroll_frame._parent_canvas.bind("<MouseWheel>", self._on_mousewheel_ctk, add="+")
                self.scroll_frame._parent_canvas.bind("<Button-4>", self._on_mousewheel_ctk, add="+")
                self.scroll_frame._parent_canvas.bind("<Button-5>", self._on_mousewheel_ctk, add="+")

            # Create modifier buttons
            for mod in self.modifiers:
                self._create_modifier_button_ctk(mod)
        else:
            # Fallback to tk
            self.frame = tk.Frame(self.parent, bg=self.colors.base)
            
            self.container = tk.Frame(
                self.frame,
                bg=self.colors.mantle,
                height=40,
                highlightbackground=self.colors.surface2,
                highlightthickness=1
            )
            self.container.pack(fill=tk.X, pady=(0, 8))
            self.container.pack_propagate(False)
            
            self.canvas = tk.Canvas(
                self.container,
                bg=self.colors.mantle,
                height=38,
                highlightthickness=0,
                bd=0
            )
            self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            self.inner_frame = tk.Frame(self.canvas, bg=self.colors.mantle)
            self.canvas_window = self.canvas.create_window((0, 0), window=self.inner_frame, anchor=tk.NW)
            
            for mod in self.modifiers:
                self._create_modifier_button_tk(mod)
            
            self.inner_frame.bind('<Configure>', self._on_inner_configure)
            self.canvas.bind('<Configure>', self._on_canvas_configure)
            
            # Bind mousewheel to all components
            self.canvas.bind('<MouseWheel>', self._on_mousewheel)
            self.canvas.bind('<Button-4>', self._on_mousewheel)
            self.canvas.bind('<Button-5>', self._on_mousewheel)
            self.inner_frame.bind('<MouseWheel>', self._on_mousewheel)
            self.inner_frame.bind('<Button-4>', self._on_mousewheel)
            self.inner_frame.bind('<Button-5>', self._on_mousewheel)
    
    def _on_mousewheel_ctk(self, event):
        """Handle mouse wheel for horizontal scrolling in CTk."""
        if not hasattr(self.scroll_frame, "_parent_canvas"):
            return
            
        if event.num == 4: # Linux scroll up/left
            delta = -1
        elif event.num == 5: # Linux scroll down/right
            delta = 1
        else: # Windows/Mac
            # Depending on platform, delta might be 120 (windows) or smaller (mac)
            # Normalizing to direction roughly
            delta = -1 if event.delta > 0 else 1
            
        # Increase scroll speed by using a multiplier (e.g. 50 units)
        self.scroll_frame._parent_canvas.xview_scroll(delta * 50, "units")
        return "break"

    def _create_modifier_button_ctk(self, mod: Dict):
        """Create a CTk modifier button."""
        key = mod.get("key", "")
        icon = mod.get("icon", "")
        label = mod.get("label", key)
        tooltip_text = mod.get("tooltip", "")
        
        btn = create_emoji_button(
            self.scroll_frame,
            text=label,
            icon=icon,
            colors=self.colors,
            variant="secondary",
            width=80,
            height=32,
            font_size=10,
            command=lambda k=key: self._toggle_modifier(k)
        )
        # Use surface1 for better contrast against surface0 containers
        btn.configure(
            fg_color=self.colors.surface1,
            hover_color=self.colors.surface2,
            text_color=self.colors.text
        )
        btn.pack(side="left", padx=3, pady=2)
        
        # Bind scrolling to button
        btn.bind("<MouseWheel>", self._on_mousewheel_ctk)
        btn.bind("<Button-4>", self._on_mousewheel_ctk)
        btn.bind("<Button-5>", self._on_mousewheel_ctk)
        
        self.buttons[key] = btn
        
        if tooltip_text:
            tooltip = Tooltip(btn, tooltip_text)
            self.tooltips.append(tooltip)
    
    def _create_modifier_button_tk(self, mod: Dict):
        """Create a tk modifier button (fallback)."""
        key = mod.get("key", "")
        icon = mod.get("icon", "")
        label = mod.get("label", key)
        tooltip_text = mod.get("tooltip", "")
        
        btn = tk.Label(
            self.inner_frame,
            text=f"{icon} {label}",
            font=("Arial", 9),
            bg=self.colors.surface1,
            fg=self.colors.text,
            padx=10,
            pady=8,
            cursor="hand2"
        )
        btn.pack(side=tk.LEFT, padx=2, pady=4)
        
        btn.bind('<Button-1>', lambda e, k=key: self._toggle_modifier(k))
        btn.bind('<Enter>', lambda e, b=btn, k=key: self._on_hover_tk(b, k, True))
        btn.bind('<Leave>', lambda e, b=btn, k=key: self._on_hover_tk(b, k, False))
        
        # Enable scrolling while hovering over buttons
        btn.bind('<MouseWheel>', self._on_mousewheel)
        btn.bind('<Button-4>', self._on_mousewheel)
        btn.bind('<Button-5>', self._on_mousewheel)
        
        self.buttons[key] = btn
        
        if tooltip_text:
            tooltip = Tooltip(btn, tooltip_text)
            self.tooltips.append(tooltip)
    
    def _toggle_modifier(self, key: str):
        """Toggle a modifier on/off."""
        if key in self.active_modifiers:
            self.active_modifiers.remove(key)
        else:
            self.active_modifiers.add(key)
        
        self._update_button_states()
        
        if self.on_change:
            self.on_change(list(self.active_modifiers))
    
    def _update_button_states(self):
        """Update button appearance based on active state."""
        for key, btn in self.buttons.items():
            is_active = key in self.active_modifiers
            
            if HAVE_CTK:
                btn.configure(
                    fg_color=self.colors.blue if is_active else self.colors.surface0,
                    text_color="#ffffff" if is_active else self.colors.text
                )
            else:
                btn.config(
                    bg=self.colors.blue if is_active else self.colors.surface0,
                    fg="#ffffff" if is_active else self.colors.text
                )
    
    def _on_hover_tk(self, btn, key: str, entering: bool):
        """Handle hover effect (tk fallback)."""
        is_active = key in self.active_modifiers
        if is_active:
            return
        
        if entering:
            btn.config(bg=self.colors.surface2)
        else:
            btn.config(bg=self.colors.surface1)
    
    def _on_inner_configure(self, event):
        """Update scroll region (tk fallback)."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    
    def _on_canvas_configure(self, event):
        """Update inner frame height (tk fallback)."""
        self.canvas.itemconfig(self.canvas_window, height=event.height)
    
    def _on_mousewheel(self, event):
        """Handle mouse wheel (tk fallback)."""
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        
        self.canvas.xview_scroll(delta * 2, "units")
        return "break"
    
    def get_active_modifiers(self) -> List[str]:
        """Get list of active modifier keys."""
        return list(self.active_modifiers)
    
    def pack(self, **kwargs):
        """Pack the widget."""
        self.frame.pack(**kwargs)


class GroupedButtonList:
    """
    A list of buttons organized by groups with inline headers.
    Each group displays all its items together without pagination.
    """
    
    def __init__(
        self,
        parent,
        groups: List[Dict],
        on_click: Callable[[str], None],
        on_group_changed: Optional[Callable[[], None]] = None
    ):
        self.parent = parent
        self.groups = groups
        self.on_click = on_click
        self.on_group_changed = on_group_changed
        
        self.colors = get_colors()
        self.current_group_idx = 0
        self.total_groups = len(groups)
        
        self.buttons_frame = None
        self.nav_frame = None
        self.dot_labels: List = []
        self.tooltips: List[Tooltip] = []
        
        self._create_widget()
    
    def _create_widget(self):
        """Create the grouped button list widget."""
        if HAVE_CTK:
            self.frame = ctk.CTkFrame(self.parent, fg_color="transparent")
            
            # Content with navigation
            self.content_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
            self.content_frame.pack(fill="both", expand=True)
            
            # Navigation arrows
            if self.total_groups > 1:
                self.left_arrow = ctk.CTkButton(
                    self.content_frame,
                    text="◀",
                    width=15,
                    height=40,
                    corner_radius=6,
                    fg_color="transparent",
                    hover_color=self.colors.surface1,
                    text_color=self.colors.overlay0,
                    command=self._prev_group
                )
                self.left_arrow.pack(side="left", fill="y", padx=(0, 4))
            
            self.buttons_container = ctk.CTkFrame(self.content_frame, fg_color="transparent")
            self.buttons_container.pack(side="left", fill="both", expand=True)
            
            if self.total_groups > 1:
                self.right_arrow = ctk.CTkButton(
                    self.content_frame,
                    text="▶",
                    width=15,
                    height=40,
                    corner_radius=6,
                    fg_color="transparent",
                    hover_color=self.colors.surface1,
                    text_color=self.colors.overlay0,
                    command=self._next_group
                )
                self.right_arrow.pack(side="right", fill="y", padx=(4, 0))
            
            # Dots
            if self.total_groups > 1:
                self.nav_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
                self.nav_frame.pack(pady=(8, 0))
                
                for i in range(self.total_groups):
                    dot = ctk.CTkLabel(
                        self.nav_frame,
                        text="●" if i == 0 else "○",
                        font=get_ctk_font(size=10),
                        text_color=self.colors.blue if i == 0 else self.colors.overlay0,
                        cursor="hand2"
                    )
                    dot.pack(side="left", padx=2)
                    dot.bind('<Button-1>', lambda e, idx=i: self._go_to_group(idx))
                    self.dot_labels.append(dot)
        else:
            # Fallback to tk
            self.frame = tk.Frame(self.parent, bg=self.colors.base)
            self.content_frame = tk.Frame(self.frame, bg=self.colors.base)
            self.content_frame.pack(fill=tk.BOTH, expand=True)
            
            if self.total_groups > 1:
                self.left_arrow = tk.Label(
                    self.content_frame, text="◀", font=("Arial", 12),
                    bg=self.colors.base, fg=self.colors.overlay0,
                    padx=8, cursor="hand2"
                )
                self.left_arrow.pack(side=tk.LEFT, fill=tk.Y)
                self.left_arrow.bind('<Button-1>', lambda e: self._prev_group())
            
            self.buttons_container = tk.Frame(self.content_frame, bg=self.colors.base)
            self.buttons_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            if self.total_groups > 1:
                self.right_arrow = tk.Label(
                    self.content_frame, text="▶", font=("Arial", 12),
                    bg=self.colors.base, fg=self.colors.overlay0,
                    padx=8, cursor="hand2"
                )
                self.right_arrow.pack(side=tk.RIGHT, fill=tk.Y)
                self.right_arrow.bind('<Button-1>', lambda e: self._next_group())
            
            # Dots (only if multiple groups)
            if self.total_groups > 1:
                self.nav_frame = tk.Frame(self.frame, bg=self.colors.base)
                self.nav_frame.pack(pady=(8, 0))
                
                for i in range(self.total_groups):
                    dot = tk.Label(
                        self.nav_frame,
                        text="●" if i == 0 else "○",
                        font=("Arial", 8),
                        bg=self.colors.base,
                        fg=self.colors.blue if i == 0 else self.colors.overlay0,
                        padx=2,
                        cursor="hand2"
                    )
                    dot.pack(side=tk.LEFT)
                    dot.bind('<Button-1>', lambda e, idx=i: self._go_to_group(idx))
                    self.dot_labels.append(dot)
        
        self._render_group()
    
    def _render_group(self):
        """Render the current group."""
        # Clear existing
        for widget in self.buttons_container.winfo_children():
            widget.destroy()
        self.tooltips.clear()
        
        if not self.groups:
            return
        
        current_group = self.groups[self.current_group_idx]
        group_name = current_group.get("name", "")
        items = current_group.get("items", [])
        
        if HAVE_CTK:
            # Header
            if group_name:
                header = ctk.CTkLabel(
                    self.buttons_container,
                    text=f"── {group_name} ──",
                    font=get_ctk_font(size=10, weight="bold"),
                    text_color=self.colors.overlay0
                )
                header.pack(pady=(0, 6))
            
            # Buttons
            for item in items:
                key = item[0]
                display_text = item[1]
                icon = item[2] if len(item) > 2 else ""
                tooltip_text = item[3] if len(item) > 3 else None
                
                btn = create_emoji_button(
                    self.buttons_container,
                    text=display_text,
                    icon=icon,
                    colors=self.colors,
                    variant="secondary",
                    height=38,
                    font_size=11,
                    anchor="w",
                    command=lambda k=key: self.on_click(k)
                )
                # Override colors
                btn.configure(
                    fg_color=self.colors.surface1,
                    hover_color=self.colors.surface2,
                    text_color=self.colors.text
                )
                btn.pack(fill="x", pady=1)
                
                if tooltip_text:
                    tooltip = Tooltip(btn, tooltip_text)
                    self.tooltips.append(tooltip)
        else:
            # Fallback to tk
            if group_name:
                header = tk.Label(
                    self.buttons_container,
                    text=f"── {group_name} ──",
                    font=("Arial", 9, "bold"),
                    bg=self.colors.base,
                    fg=self.colors.overlay0
                )
                header.pack(pady=(0, 4))
            
            for item in items:
                key = item[0]
                display_text = item[1]
                icon = item[2] if len(item) > 2 else ""
                tooltip_text = item[3] if len(item) > 3 else None
                
                row = tk.Frame(self.buttons_container, bg=self.colors.surface1, cursor="hand2")
                row.pack(fill=tk.X, pady=1)
                
                icon_lbl = tk.Label(row, text=icon, bg=self.colors.surface1, fg=self.colors.text, width=3, pady=8)
                icon_lbl.pack(side=tk.LEFT, padx=(8, 0))
                
                text_lbl = tk.Label(row, text=display_text, bg=self.colors.surface1, fg=self.colors.text, anchor=tk.W, pady=8)
                text_lbl.pack(side=tk.LEFT, padx=(4, 8), fill=tk.X, expand=True)
                
                def on_enter(e, widgets=[row, icon_lbl, text_lbl]):
                    for w in widgets: w.configure(bg=self.colors.surface2)
                
                def on_leave(e, widgets=[row, icon_lbl, text_lbl]):
                    for w in widgets: w.configure(bg=self.colors.surface1)

                for widget in (row, icon_lbl, text_lbl):
                    widget.bind('<Button-1>', lambda e, k=key: self.on_click(k))
                    widget.bind('<Enter>', on_enter)
                    widget.bind('<Leave>', on_leave)
                
                if tooltip_text:
                    tooltip = Tooltip(text_lbl, tooltip_text)
                    self.tooltips.append(tooltip)
        
        self._update_dots()
    
    def _update_dots(self):
        """Update dot indicators."""
        for i, dot in enumerate(self.dot_labels):
            if HAVE_CTK:
                dot.configure(
                    text="●" if i == self.current_group_idx else "○",
                    text_color=self.colors.blue if i == self.current_group_idx else self.colors.overlay0
                )
            else:
                dot.config(
                    text="●" if i == self.current_group_idx else "○",
                    fg=self.colors.blue if i == self.current_group_idx else self.colors.overlay0
                )
    
    def _next_group(self):
        """Go to next group."""
        self.current_group_idx = (self.current_group_idx + 1) % self.total_groups
        self._render_group()
        if self.on_group_changed:
            self.on_group_changed()
    
    def _prev_group(self):
        """Go to previous group."""
        self.current_group_idx = (self.current_group_idx - 1) % self.total_groups
        self._render_group()
        if self.on_group_changed:
            self.on_group_changed()
    
    def _go_to_group(self, idx: int):
        """Go to specific group."""
        if 0 <= idx < self.total_groups:
            self.current_group_idx = idx
            self._render_group()
            if self.on_group_changed:
                self.on_group_changed()
    
    def pack(self, **kwargs):
        """Pack the widget."""
        self.frame.pack(**kwargs)


class CarouselButtonList:
    """
    A carousel-style list of buttons with pagination.
    Shows a configurable number of items per page with navigation arrows.
    """
    
    DEFAULT_ITEMS_PER_PAGE = 4
    
    def __init__(
        self,
        parent,
        items: List[Tuple[str, str, Optional[str], Optional[str]]],
        on_click: Callable[[str], None],
        items_per_page: int = None
    ):
        self.parent = parent
        self.items = items
        self.on_click = on_click
        self.items_per_page = items_per_page or self.DEFAULT_ITEMS_PER_PAGE
        
        self.colors = get_colors()
        self.current_page = 0
        self.total_pages = max(1, math.ceil(len(items) / self.items_per_page))
        
        self.buttons_frame = None
        self.nav_frame = None
        self.dot_labels: List = []
        self.tooltips: List[Tooltip] = []
        
        self._create_widget()
    
    def _create_widget(self):
        """Create the carousel widget."""
        if HAVE_CTK:
            self.frame = ctk.CTkFrame(self.parent, fg_color="transparent")
            
            self.content_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
            self.content_frame.pack(fill="both", expand=True)
            
            # Arrows
            if self.total_pages > 1:
                self.left_arrow = ctk.CTkButton(
                    self.content_frame,
                    text="◀",
                    width=15,
                    height=40,
                    corner_radius=6,
                    fg_color="transparent",
                    hover_color=self.colors.surface1,
                    text_color=self.colors.overlay0,
                    command=self._prev_page
                )
                self.left_arrow.pack(side="left", fill="y", padx=(0, 2))  # Reduced padding
            
            self.buttons_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
            self.buttons_frame.pack(side="left", fill="both", expand=True)
            
            if self.total_pages > 1:
                self.right_arrow = ctk.CTkButton(
                    self.content_frame,
                    text="▶",
                    width=15,
                    height=40,
                    corner_radius=6,
                    fg_color="transparent",
                    hover_color=self.colors.surface1,
                    text_color=self.colors.overlay0,
                    command=self._next_page
                )
                self.right_arrow.pack(side="right", fill="y", padx=(2, 0))  # Reduced padding
            
            # Dots
            if self.total_pages > 1:
                self.nav_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
                self.nav_frame.pack(pady=(8, 0))
                
                for i in range(self.total_pages):
                    dot = ctk.CTkLabel(
                        self.nav_frame,
                        text="●" if i == 0 else "○",
                        font=get_ctk_font(size=10),
                        text_color=self.colors.blue if i == 0 else self.colors.overlay0,
                        cursor="hand2"
                    )
                    dot.pack(side="left", padx=2)
                    dot.bind('<Button-1>', lambda e, page=i: self._go_to_page(page))
                    self.dot_labels.append(dot)
        else:
            # Fallback
            self.frame = tk.Frame(self.parent, bg=self.colors.base)
            self.content_frame = tk.Frame(self.frame, bg=self.colors.base)
            self.content_frame.pack(fill=tk.BOTH, expand=True)
            
            if self.total_pages > 1:
                self.left_arrow = tk.Label(
                    self.content_frame, text="◀", font=("Arial", 12),
                    bg=self.colors.base, fg=self.colors.overlay0, padx=8, cursor="hand2"
                )
                self.left_arrow.pack(side=tk.LEFT, fill=tk.Y)
                self.left_arrow.bind('<Button-1>', lambda e: self._prev_page())
            
            self.buttons_frame = tk.Frame(self.content_frame, bg=self.colors.base)
            self.buttons_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            if self.total_pages > 1:
                self.right_arrow = tk.Label(
                    self.content_frame, text="▶", font=("Arial", 12),
                    bg=self.colors.base, fg=self.colors.overlay0, padx=8, cursor="hand2"
                )
                self.right_arrow.pack(side=tk.RIGHT, fill=tk.Y)
                self.right_arrow.bind('<Button-1>', lambda e: self._next_page())
            
            if self.total_pages > 1:
                self.nav_frame = tk.Frame(self.frame, bg=self.colors.base)
                self.nav_frame.pack(pady=(8, 0))
                
                for i in range(self.total_pages):
                    dot = tk.Label(
                        self.nav_frame, text="●" if i == 0 else "○", font=("Arial", 8),
                        bg=self.colors.base, fg=self.colors.blue if i == 0 else self.colors.overlay0,
                        padx=2, cursor="hand2"
                    )
                    dot.pack(side=tk.LEFT)
                    dot.bind('<Button-1>', lambda e, page=i: self._go_to_page(page))
                    self.dot_labels.append(dot)
        
        self._render_page()
    
    def _render_page(self):
        """Render the current page."""
        for widget in self.buttons_frame.winfo_children():
            widget.destroy()
        self.tooltips.clear()
        
        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_items = self.items[start_idx:end_idx]
        
        for item in page_items:
            key = item[0]
            display_text = item[1]
            icon = item[2] if len(item) > 2 else ""
            tooltip_text = item[3] if len(item) > 3 else None
            
            if HAVE_CTK:
                btn = create_emoji_button(
                    self.buttons_frame,
                    text=display_text,
                    icon=icon,
                    colors=self.colors,
                    variant="secondary",
                    height=38,
                    font_size=11,
                    anchor="w",
                    command=lambda k=key: self.on_click(k)
                )
                # Override colors
                btn.configure(
                    fg_color=self.colors.surface1,
                    hover_color=self.colors.surface2,
                    text_color=self.colors.text
                )
                btn.pack(fill="x", pady=1)
                
                if tooltip_text:
                    tooltip = Tooltip(btn, tooltip_text)
                    self.tooltips.append(tooltip)
            else:
                row = tk.Frame(self.buttons_frame, bg=self.colors.surface1, cursor="hand2")
                row.pack(fill=tk.X, pady=1)
                
                icon_lbl = tk.Label(row, text=icon, bg=self.colors.surface1, fg=self.colors.text, width=3, pady=10)
                icon_lbl.pack(side=tk.LEFT, padx=(8, 0))
                
                text_lbl = tk.Label(row, text=display_text, bg=self.colors.surface1, fg=self.colors.text, anchor=tk.W, pady=10)
                text_lbl.pack(side=tk.LEFT, padx=(4, 8))
                
                def on_enter(e, widgets=[row, icon_lbl, text_lbl]):
                    for w in widgets: w.configure(bg=self.colors.surface2)
                
                def on_leave(e, widgets=[row, icon_lbl, text_lbl]):
                    for w in widgets: w.configure(bg=self.colors.surface1)

                for widget in (row, icon_lbl, text_lbl):
                    widget.bind('<Button-1>', lambda e, k=key: self.on_click(k))
                    widget.bind('<Enter>', on_enter)
                    widget.bind('<Leave>', on_leave)
                
                if tooltip_text:
                    tooltip = Tooltip(text_lbl, tooltip_text)
                    self.tooltips.append(tooltip)
        
        self._update_dots()
    
    def _update_dots(self):
        """Update dot indicators."""
        for i, dot in enumerate(self.dot_labels):
            if HAVE_CTK:
                dot.configure(
                    text="●" if i == self.current_page else "○",
                    text_color=self.colors.blue if i == self.current_page else self.colors.overlay0
                )
            else:
                dot.config(
                    text="●" if i == self.current_page else "○",
                    fg=self.colors.blue if i == self.current_page else self.colors.overlay0
                )
    
    def _next_page(self):
        self.current_page = (self.current_page + 1) % self.total_pages
        self._render_page()
    
    def _prev_page(self):
        self.current_page = (self.current_page - 1) % self.total_pages
        self._render_page()
    
    def _go_to_page(self, page: int):
        if 0 <= page < self.total_pages:
            self.current_page = page
            self._render_page()
    
    def pack(self, **kwargs):
        self.frame.pack(**kwargs)


# =============================================================================
# Base Popup Class
# =============================================================================

class BasePopup:
    """Base class for popup windows"""
    
    def __init__(self):
        self.root = None
        self.dark_mode = is_dark_mode()
        self.colors = get_colors()
        self._setup_colors()
    
    def _setup_colors(self):
        """Setup color scheme (legacy compatibility)."""
        c = self.colors
        self.bg_color = c.base
        self.fg_color = c.text
        self.button_bg = c.surface0
        self.button_hover = c.surface1
        self.input_bg = c.surface0
        self.border_color = c.surface2
        self.accent_color = c.blue
    
    def _close(self):
        """Close the popup window."""
        if self.root:
            self.root.destroy()
            self.root = None
    
    def is_open(self) -> bool:
        """Check if the popup is currently open."""
        return self.root is not None and self.root.winfo_exists()


class InputPopup(BasePopup):
    """
    Simple input popup for when no text is selected.
    Uses CTk for modern look when available.
    """
    
    def __init__(
        self,
        on_submit: Callable[[str, str], None],
        on_close: Optional[Callable[[], None]] = None
    ):
        super().__init__()
        self.on_submit = on_submit
        self.on_close_callback = on_close
        self.input_var = None
        self.response_toggle = None
    
    def show(self, x: Optional[int] = None, y: Optional[int] = None):
        """Show the input popup."""
        if HAVE_CTK:
            sync_ctk_appearance()
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()
        
        self.root.withdraw()
        self.root.title("AI Chat")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        
        # Set up transparent corners on Windows
        setup_transparent_popup(self.root, self.colors)
        
        # Hide from taskbar
        hide_from_taskbar(self.root)
        
        if HAVE_CTK:
            main_frame = ctk.CTkFrame(
                self.root,
                corner_radius=10,
                fg_color=self.colors.base,
                border_color=self.colors.surface2,
                border_width=1
            )
            main_frame.pack(fill="both", expand=True, padx=1, pady=1)
            
            content_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
            content_frame.pack(fill="both", expand=True, padx=8, pady=8)
            
            # Close button
            top_bar = ctk.CTkFrame(content_frame, fg_color="transparent")
            top_bar.pack(fill="x", pady=(0, 8))
            
            close_btn = ctk.CTkButton(
                top_bar,
                text="×",
                width=24,
                height=24,
                corner_radius=6,
                fg_color="transparent",
                hover_color=self.colors.red,
                text_color=self.colors.overlay0,
                font=get_ctk_font(size=14, weight="bold"),
                command=self._close
            )
            close_btn.pack(side="right")
            
            # Response toggle
            toggle_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
            toggle_frame.pack(fill="x", pady=(0, 8))
            
            self.response_toggle = SegmentedToggle(
                toggle_frame,
                options=[("Default", "default"), ("Replace", "replace"), ("Show", "show")],
                default_value="default"
            )
            self.response_toggle.pack(anchor="center")
            
            # Input area
            input_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
            input_frame.pack(fill="x")
            
            self.input_entry = ctk.CTkEntry(
                input_frame,
                placeholder_text="Ask your AI...",
                font=get_ctk_font(size=12),
                height=40,
                corner_radius=8,
                fg_color=self.colors.surface0,
                border_color=self.colors.surface2,
                text_color=self.colors.text,
                placeholder_text_color=self.colors.overlay0,
                width=280
            )
            self.input_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
            self.input_entry.bind('<Return>', lambda e: self._submit())
            
            send_btn = ctk.CTkButton(
                input_frame,
                text="➤",
                width=44,
                height=40,
                corner_radius=8,
                fg_color=self.colors.blue,
                hover_color=self.colors.lavender,
                text_color="#ffffff",
                font=get_ctk_font(size=14),
                command=self._submit
            )
            send_btn.pack(side="right")
        else:
            # Fallback to tk
            self.root.configure(bg=self.bg_color)
            main_frame = tk.Frame(self.root, bg=self.bg_color, highlightbackground=self.border_color, highlightthickness=1)
            main_frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
            
            content_frame = tk.Frame(main_frame, bg=self.bg_color)
            content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # Close button
            top_bar = tk.Frame(content_frame, bg=self.bg_color)
            top_bar.pack(fill=tk.X, pady=(0, 5))
            
            close_btn = tk.Button(
                top_bar,
                text="×",
                font=("Arial", 14, "bold"),
                bg=self.bg_color,
                fg=self.fg_color,
                activebackground=self.button_hover,
                relief=tk.FLAT,
                bd=0,
                command=self._close
            )
            close_btn.pack(side=tk.RIGHT)
            
            # Response mode toggle
            toggle_frame = tk.Frame(content_frame, bg=self.bg_color)
            toggle_frame.pack(fill=tk.X, pady=(0, 8))
            
            self.response_toggle = SegmentedToggle(
                toggle_frame,
                options=[("Default", "default"), ("Replace", "replace"), ("Show", "show")],
                default_value="default"
            )
            self.response_toggle.pack(anchor=tk.CENTER)
            
            # Input area
            input_frame = tk.Frame(content_frame, bg=self.bg_color)
            input_frame.pack(fill=tk.X)
            
            self.input_var = tk.StringVar()
            placeholder = "Ask your AI..."
            
            self.input_entry = tk.Entry(
                input_frame,
                textvariable=self.input_var,
                font=("Arial", 11),
                bg=self.input_bg,
                fg=self.fg_color,
                insertbackground=self.fg_color,
                relief=tk.FLAT,
                highlightbackground=self.border_color,
                highlightthickness=1,
                width=40
            )
            self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5), ipady=8)
            self.input_entry.insert(0, placeholder)
            self.input_entry.config(fg='gray')
            
            def on_focus_in(event):
                if self.input_entry.get() == placeholder:
                    self.input_entry.delete(0, tk.END)
                    self.input_entry.config(fg=self.fg_color)
            
            def on_focus_out(event):
                if not self.input_entry.get():
                    self.input_entry.insert(0, placeholder)
                    self.input_entry.config(fg='gray')
            
            self.input_entry.bind('<FocusIn>', on_focus_in)
            self.input_entry.bind('<FocusOut>', on_focus_out)
            self.input_entry.bind('<Return>', lambda e: self._submit())
            
            # Send button
            send_btn = tk.Button(
                input_frame,
                text="➤",
                font=("Arial", 12),
                bg=self.accent_color,
                fg="#ffffff",
                activebackground="#1976D2",
                relief=tk.FLAT,
                bd=0,
                padx=10,
                pady=5,
                command=self._submit
            )
            send_btn.pack(side=tk.RIGHT)
        
        # Position window and force rendering before showing
        self._position_window(x, y)
        self.root.update_idletasks()
        self.root.deiconify()
        self.root.bind('<Escape>', lambda e: self._close())
        self.root.lift()
        self.root.focus_force()
        self.input_entry.focus_set()
        
        self._run_event_loop()
    
    def _position_window(self, x, y):
        """Position the window."""
        self.root.update_idletasks()
        
        if x is None or y is None:
            x = self.root.winfo_pointerx()
            y = self.root.winfo_pointery() + 20
        
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = self.root.winfo_reqwidth()
        window_height = self.root.winfo_reqheight()
        
        if x + window_width > screen_width:
            x = screen_width - window_width - 10
        if y + window_height > screen_height:
            y = y - window_height - 30
        
        self.root.geometry(f"+{x}+{y}")
    
    def _run_event_loop(self):
        """Run event loop without blocking."""
        try:
            while self.root is not None:
                try:
                    if not self.root.winfo_exists():
                        break
                    self.root.update()
                    time.sleep(0.01)
                except tk.TclError:
                    break
        except Exception:
            pass
    
    def _submit(self):
        """Handle submit."""
        if HAVE_CTK:
            text = self.input_entry.get().strip()
        else:
            text = self.input_var.get().strip() if self.input_var else ""
        
        if text and text != "Ask your AI...":
            response_mode = self.response_toggle.get() if self.response_toggle else "default"
            self._close()
            self.on_submit(text, response_mode)
    
    def _close(self):
        super()._close()
        if self.on_close_callback:
            self.on_close_callback()


class PromptSelectionPopup(BasePopup):
    """
    Popup with prompt selection buttons for when text is selected.
    """
    
    def __init__(
        self,
        options: Dict,
        on_option_selected: Callable[[str, str, Optional[str]], None],
        on_close: Optional[Callable[[], None]] = None
    ):
        super().__init__()
        self.options = options
        self.on_option_selected = on_option_selected
        self.on_close_callback = on_close
        self.selected_text = ""
        self.response_toggle = None
    
    def show(self, selected_text: str, x: Optional[int] = None, y: Optional[int] = None):
        """Show the popup window."""
        self.selected_text = selected_text
        
        if HAVE_CTK:
            sync_ctk_appearance()
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()
        
        self.root.withdraw()
        self.root.title("Text Edit Tool")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        
        # Set up transparent corners on Windows
        setup_transparent_popup(self.root, self.colors)
        
        # Hide from taskbar
        hide_from_taskbar(self.root)
        
        if HAVE_CTK:
            main_frame = ctk.CTkFrame(
                self.root,
                corner_radius=10,
                fg_color=self.colors.base,
                border_color=self.colors.surface2,
                border_width=1
            )
            main_frame.pack(fill="both", expand=True, padx=1, pady=1)
            
            content_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
            content_frame.pack(fill="both", expand=True, padx=8, pady=8)
            
            # Close button
            top_bar = ctk.CTkFrame(content_frame, fg_color="transparent")
            top_bar.pack(fill="x", pady=(0, 8))
            
            close_btn = ctk.CTkButton(
                top_bar,
                text="×",
                width=24,
                height=24,
                corner_radius=6,
                fg_color="transparent",
                hover_color=self.colors.red,
                text_color=self.colors.overlay0,
                font=get_ctk_font(size=14, weight="bold"),
                command=self._close
            )
            close_btn.pack(side="right")
            
            # Response toggle
            toggle_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
            toggle_frame.pack(fill="x", pady=(0, 8))
            
            self.response_toggle = SegmentedToggle(
                toggle_frame,
                options=[("Default", "default"), ("Replace", "replace"), ("Show", "show")],
                default_value="default"
            )
            self.response_toggle.pack(anchor="center")
            
            # Input area
            input_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
            input_frame.pack(fill="x", pady=(0, 8))
            
            self.input_entry = ctk.CTkEntry(
                input_frame,
                placeholder_text="Explain your changes...",
                font=get_ctk_font(size=12),
                height=40,
                corner_radius=8,
                fg_color=self.colors.surface0,
                border_color=self.colors.surface2,
                text_color=self.colors.text,
                placeholder_text_color=self.colors.overlay0
            )
            self.input_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
            self.input_entry.bind('<Return>', lambda e: self._on_custom_submit())
            
            send_btn = ctk.CTkButton(
                input_frame,
                text="➤",
                width=44,
                height=40,
                corner_radius=8,
                fg_color=self.colors.blue,
                hover_color=self.colors.lavender,
                text_color="#ffffff",
                font=get_ctk_font(size=14),
                command=self._on_custom_submit
            )
            send_btn.pack(side="right")
            
            # Option buttons
            self._create_option_buttons_ctk(content_frame)
        else:
            # Fallback to tk
            self.root.configure(bg=self.bg_color)
            main_frame = tk.Frame(
                self.root,
                bg=self.bg_color,
                highlightbackground=self.border_color,
                highlightthickness=1
            )
            main_frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
            
            content_frame = tk.Frame(main_frame, bg=self.bg_color)
            content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # Close button
            top_bar = tk.Frame(content_frame, bg=self.bg_color)
            top_bar.pack(fill=tk.X, pady=(0, 5))
            
            close_btn = tk.Button(
                top_bar,
                text="×",
                font=("Arial", 14, "bold"),
                bg=self.bg_color,
                fg=self.fg_color,
                activebackground=self.button_hover,
                relief=tk.FLAT,
                bd=0,
                command=self._close
            )
            close_btn.pack(side=tk.RIGHT)
            
            # Response mode toggle
            toggle_frame = tk.Frame(content_frame, bg=self.bg_color)
            toggle_frame.pack(fill=tk.X, pady=(0, 8))
            
            self.response_toggle = SegmentedToggle(
                toggle_frame,
                options=[("Default", "default"), ("Replace", "replace"), ("Show", "show")],
                default_value="default"
            )
            self.response_toggle.pack(anchor=tk.CENTER)
            
            # Input area
            input_frame = tk.Frame(content_frame, bg=self.bg_color)
            input_frame.pack(fill=tk.X, pady=(0, 10))
            
            self.input_var = tk.StringVar()
            placeholder = "Explain your changes.."
            
            self.input_entry = tk.Entry(
                input_frame,
                textvariable=self.input_var,
                font=("Arial", 11),
                bg=self.input_bg,
                fg=self.fg_color,
                insertbackground=self.fg_color,
                relief=tk.FLAT,
                highlightbackground=self.border_color,
                highlightthickness=1
            )
            self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5), ipady=8)
            self.input_entry.insert(0, placeholder)
            self.input_entry.config(fg='gray')
            
            def on_focus_in(event):
                if self.input_entry.get() == placeholder:
                    self.input_entry.delete(0, tk.END)
                    self.input_entry.config(fg=self.fg_color)
            
            def on_focus_out(event):
                if not self.input_entry.get():
                    self.input_entry.insert(0, placeholder)
                    self.input_entry.config(fg='gray')
            
            self.input_entry.bind('<FocusIn>', on_focus_in)
            self.input_entry.bind('<FocusOut>', on_focus_out)
            self.input_entry.bind('<Return>', lambda e: self._on_custom_submit())
            
            # Send button
            send_btn = tk.Button(
                input_frame,
                text="➤",
                font=("Arial", 12),
                bg=self.accent_color,
                fg="#ffffff",
                activebackground="#1976D2",
                relief=tk.FLAT,
                bd=0,
                padx=10,
                pady=5,
                command=self._on_custom_submit
            )
            send_btn.pack(side=tk.RIGHT)
            
            # Option buttons
            self._create_option_buttons_tk(content_frame)
        
        # Position window and force rendering before showing
        self._position_window(x, y)
        self.root.update_idletasks()
        self.root.deiconify()
        self.root.bind('<Escape>', lambda e: self._close())
        self.root.lift()
        self.root.focus_force()
        self.input_entry.focus_set()
        
        self._run_event_loop()
    
    def _create_option_buttons_ctk(self, parent):
        """Create option buttons with CTk."""
        buttons_frame = ctk.CTkFrame(parent, fg_color="transparent")
        buttons_frame.pack(fill="both", expand=True)
        
        for key, option in self.options.items():
            if key == "Custom" or key.startswith("_"):
                continue
            
            icon = option.get("icon", "")
            
            btn = create_emoji_button(
                buttons_frame,
                text=key,
                icon=icon,
                colors=self.colors,
                variant="secondary",
                height=36,
                font_size=11,
                anchor="w",
                command=lambda k=key: self._on_option_click(k)
            )
            # Override colors to match design
            btn.configure(
                fg_color=self.colors.surface0,
                text_color=self.colors.text
            )
            btn.pack(fill="x", pady=1)
    
    def _position_window(self, x, y):
        """Position the window."""
        self.root.update_idletasks()
        
        if x is None or y is None:
            x = self.root.winfo_pointerx()
            y = self.root.winfo_pointery() + 20
        
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = self.root.winfo_reqwidth()
        window_height = self.root.winfo_reqheight()
        
        if x + window_width > screen_width:
            x = screen_width - window_width - 10
        if y + window_height > screen_height:
            y = y - window_height - 30
        
        self.root.geometry(f"+{x}+{y}")
    
    def _run_event_loop(self):
        """Run event loop."""
        try:
            while self.root is not None:
                try:
                    if not self.root.winfo_exists():
                        break
                    self.root.update()
                    time.sleep(0.01)
                except tk.TclError:
                    break
        except Exception:
            pass
    
    def _create_option_buttons_tk(self, parent):
        """Create option buttons for tk fallback."""
        buttons_frame = tk.Frame(parent, bg=self.bg_color)
        buttons_frame.pack(fill=tk.BOTH, expand=True)
        
        row = 0
        col = 0
        
        for key, option in self.options.items():
            if key == "Custom" or key.startswith("_"):
                continue
            
            btn = tk.Button(
                buttons_frame,
                text=key,
                font=("Arial", 10),
                bg=self.button_bg,
                fg=self.fg_color,
                activebackground=self.button_hover,
                relief=tk.FLAT,
                bd=0,
                padx=15,
                pady=8,
                width=12,
                anchor=tk.W,
                command=lambda k=key: self._on_option_click(k)
            )
            btn.grid(row=row, column=col, padx=3, pady=3, sticky=tk.EW)
            
            btn.bind('<Enter>', lambda e, b=btn: b.config(bg=self.button_hover))
            btn.bind('<Leave>', lambda e, b=btn: b.config(bg=self.button_bg))
            
            col += 1
            if col > 1:
                col = 0
                row += 1
        
        buttons_frame.columnconfigure(0, weight=1)
        buttons_frame.columnconfigure(1, weight=1)
    
    def _on_option_click(self, option_key: str):
        """Handle option button click."""
        response_mode = self.response_toggle.get() if self.response_toggle else "default"
        self._close()
        self.on_option_selected(option_key, self.selected_text, None, response_mode)
    
    def _on_custom_submit(self):
        """Handle custom input submission."""
        if HAVE_CTK:
            custom_text = self.input_entry.get().strip()
        else:
            custom_text = self.input_var.get().strip() if self.input_var else ""
        
        if not custom_text or custom_text == "Explain your changes..":
            return
        
        response_mode = self.response_toggle.get() if self.response_toggle else "default"
        self._close()
        self.on_option_selected("_Custom", self.selected_text, custom_text, response_mode)
    
    def _close(self):
        super()._close()
        if self.on_close_callback:
            self.on_close_callback()


# =============================================================================
# Attached Popups for GUICoordinator (CTkToplevel versions)
# =============================================================================

class AttachedInputPopup:
    """
    Input popup as CTkToplevel attached to coordinator's root.
    Modern CustomTkinter-styled with segmented toggle.
    """
    
    PLACEHOLDER = "Ask AI anything..."
    
    def __init__(
        self,
        parent_root,
        on_submit: Callable[[str, str], None],
        on_close: Optional[Callable[[], None]] = None,
        x: Optional[int] = None,
        y: Optional[int] = None
    ):
        self.parent_root = parent_root
        self.on_submit = on_submit
        self.on_close_callback = on_close
        self.x = x
        self.y = y
        
        self.colors = get_colors()
        self.root = None
        self.response_toggle = None
        
        self._create_window()
    
    def _create_window(self):
        """Create the styled input popup window."""
        if HAVE_CTK:
            self.root = ctk.CTkToplevel(self.parent_root)
        else:
            self.root = tk.Toplevel(self.parent_root)
        
        # Hide window while building UI (prevents flickering)
        self.root.withdraw()
        
        self.root.title("AI Chat")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        
        # Set up transparent corners on Windows
        setup_transparent_popup(self.root, self.colors)
        
        # Hide from taskbar
        hide_from_taskbar(self.root)
        
        if HAVE_CTK:
            main_frame = ctk.CTkFrame(
                self.root,
                corner_radius=10,
                fg_color=self.colors.base,
                border_color=self.colors.surface2,
                border_width=1
            )
            main_frame.pack(fill="both", expand=True, padx=1, pady=1)
            
            content_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
            content_frame.pack(fill="both", expand=True, padx=8, pady=8)
            
            # Close button
            top_bar = ctk.CTkFrame(content_frame, fg_color="transparent")
            top_bar.pack(fill="x", pady=(0, 8))
            
            close_btn = ctk.CTkButton(
                top_bar,
                text="×",
                width=24,
                height=24,
                corner_radius=6,
                fg_color="transparent",
                hover_color=self.colors.red,
                text_color=self.colors.overlay0,
                font=get_ctk_font(size=14, weight="bold"),
                command=self._close
            )
            close_btn.pack(side="right")
            
            # Response toggle
            toggle_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
            toggle_frame.pack(fill="x", pady=(0, 8))
            
            self.response_toggle = SegmentedToggle(
                toggle_frame,
                options=[("Default", "default"), ("Replace", "replace"), ("Show", "show")],
                default_value="default"
            )
            self.response_toggle.pack(anchor="center")
            
            # Input area
            input_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
            input_frame.pack(fill="x")
            
            self.input_entry = ctk.CTkEntry(
                input_frame,
                placeholder_text=self.PLACEHOLDER,
                font=get_ctk_font(size=12),
                height=42,
                corner_radius=8,
                fg_color=self.colors.surface0,
                border_color=self.colors.surface2,
                text_color=self.colors.text,
                placeholder_text_color=self.colors.overlay0,
                width=280
            )
            self.input_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
            self.input_entry.bind('<Return>', lambda e: self._submit())
            
            send_btn = ctk.CTkButton(
                input_frame,
                text="➤",
                width=46,
                height=42,
                corner_radius=8,
                fg_color=self.colors.blue,
                hover_color=self.colors.lavender,
                text_color="#ffffff",
                font=get_ctk_font(size=14),
                command=self._submit
            )
            send_btn.pack(side="right")
        else:
            # Fallback to tk
            self.root.configure(bg=self.colors.base)
            
            main_frame = tk.Frame(
                self.root,
                bg=self.colors.base,
                highlightbackground=self.colors.surface2,
                highlightthickness=1
            )
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            content_frame = tk.Frame(main_frame, bg=self.colors.base)
            content_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
            
            # Top bar with close button
            top_bar = tk.Frame(content_frame, bg=self.colors.base)
            top_bar.pack(fill=tk.X, pady=(0, 8))
            
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
            
            # Response mode toggle
            toggle_frame = tk.Frame(content_frame, bg=self.colors.base)
            toggle_frame.pack(fill=tk.X, pady=(0, 12))
            
            self.response_toggle = SegmentedToggle(
                toggle_frame,
                options=[("Default", "default"), ("Replace", "replace"), ("Show", "show")],
                default_value="default"
            )
            self.response_toggle.pack(anchor=tk.CENTER)
            
            # Input area with modern styling
            input_frame = tk.Frame(content_frame, bg=self.colors.base)
            input_frame.pack(fill=tk.X)
            
            # Input container with border
            input_container = tk.Frame(
                input_frame,
                bg=self.colors.surface0,
                highlightbackground=self.colors.surface2,
                highlightthickness=1
            )
            input_container.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
            
            self.input_var = tk.StringVar(master=self.root)
            
            self.input_entry = tk.Entry(
                input_container,
                textvariable=self.input_var,
                font=("Arial", 11),
                bg=self.colors.surface0,
                fg=self.colors.text,
                insertbackground=self.colors.text,
                relief=tk.FLAT,
                bd=0,
                width=35
            )
            self.input_entry.pack(fill=tk.X, padx=10, pady=10)
            self.input_entry.insert(0, self.PLACEHOLDER)
            self.input_entry.config(fg=self.colors.overlay0)
            
            self.input_entry.bind('<FocusIn>', self._on_focus_in)
            self.input_entry.bind('<FocusOut>', self._on_focus_out)
            self.input_entry.bind('<Return>', lambda e: self._submit())
            
            # Send button
            send_btn = tk.Label(
                input_frame,
                text="➤",
                font=("Arial", 14),
                bg=self.colors.blue,
                fg="#ffffff",
                padx=14,
                pady=8,
                cursor="hand2"
            )
            send_btn.pack(side=tk.RIGHT)
            send_btn.bind('<Button-1>', lambda e: self._submit())
            send_btn.bind('<Enter>', lambda e: send_btn.config(bg=self.colors.lavender))
            send_btn.bind('<Leave>', lambda e: send_btn.config(bg=self.colors.blue))
        
        # Force Tk to process all pending drawing commands before showing
        self._position_window()
        self.root.update_idletasks()
        # Use delayed deiconify to let CTk finish internal rendering
        self.root.after(10, self._show_and_focus)
    
    def _show_and_focus(self):
        """Show window after CTk has finished rendering (prevents flickering)."""
        if not self.root:
            return
        try:
            self.root.deiconify()
            self.root.bind('<Escape>', lambda e: self._close())
            self.root.lift()
            self.root.focus_force()
            self.input_entry.focus_set()
        except tk.TclError:
            pass
    
    def _position_window(self):
        """Position the window near the cursor."""
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
        
        if x + window_width > screen_width:
            x = screen_width - window_width - 10
        if y + window_height > screen_height:
            y = y - window_height - 30
        
        self.root.geometry(f"+{x}+{y}")
    
    def _on_focus_in(self, event):
        """Handle input focus in."""
        if self.input_entry.get() == self.PLACEHOLDER:
            self.input_entry.delete(0, tk.END)
            self.input_entry.config(fg=self.colors.text)
    
    def _on_focus_out(self, event):
        """Handle input focus out."""
        if not self.input_entry.get():
            self.input_entry.insert(0, self.PLACEHOLDER)
            self.input_entry.config(fg=self.colors.overlay0)
    
    def _submit(self):
        """Handle form submission."""
        text = self.input_entry.get().strip()
        if text and text != self.PLACEHOLDER:
            response_mode = self.response_toggle.get() if self.response_toggle else "default"
            self._close()
            self.on_submit(text, response_mode)
    
    def _close(self):
        """Close the popup."""
        if self.root:
            try:
                self.root.destroy()
            except tk.TclError:
                pass
            self.root = None
        if self.on_close_callback:
            self.on_close_callback()


class AttachedPromptPopup:
    """
    Prompt selection popup as CTkToplevel attached to coordinator's root.
    Modern CustomTkinter-styled with segmented toggle and action buttons.
    """
    
    PLACEHOLDER_EDIT = "Explain your changes..."
    PLACEHOLDER_ASK = "Ask about this text..."
    
    def __init__(
        self,
        parent_root,
        options: Dict,
        on_option_selected: Callable[[str, str, Optional[str], str, List[str]], None],
        on_close: Optional[Callable[[], None]],
        selected_text: str,
        x: Optional[int] = None,
        y: Optional[int] = None
    ):
        self.parent_root = parent_root
        self.options = options
        self.on_option_selected = on_option_selected
        self.on_close_callback = on_close
        self.selected_text = selected_text
        self.x = x
        self.y = y
        
        self.colors = get_colors()
        self.root = None
        self.response_toggle = None
        self.modifier_bar = None
        self.active_modifiers: List[str] = []
        
        self._create_window()
    
    def _create_window(self):
        """Create the styled prompt popup window."""
        if HAVE_CTK:
            self.root = ctk.CTkToplevel(self.parent_root)
        else:
            self.root = tk.Toplevel(self.parent_root)
        
        # Hide window while building UI (prevents flickering)
        self.root.withdraw()
        
        self.root.title("Text Edit Tool")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        
        # Set up transparent corners on Windows
        setup_transparent_popup(self.root, self.colors)
        
        # Hide from taskbar
        hide_from_taskbar(self.root)
        
        if HAVE_CTK:
            main_frame = ctk.CTkFrame(
                self.root,
                corner_radius=10,
                fg_color=self.colors.base,
                border_color=self.colors.surface2,
                border_width=1
            )
            main_frame.pack(fill="both", expand=True, padx=1, pady=1)
            
            content_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
            content_frame.pack(fill="both", expand=True, padx=8, pady=8)
            
            # Close button
            top_bar = ctk.CTkFrame(content_frame, fg_color="transparent")
            top_bar.pack(fill="x", pady=(0, 8))
            
            close_btn = ctk.CTkButton(
                top_bar,
                text="×",
                width=24,
                height=24,
                corner_radius=6,
                fg_color="transparent",
                hover_color=self.colors.red,
                text_color=self.colors.overlay0,
                font=get_ctk_font(size=14, weight="bold"),
                command=self._close
            )
            close_btn.pack(side="right")
            
            # Response toggle
            toggle_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
            toggle_frame.pack(fill="x", pady=(0, 8))
            
            self.response_toggle = SegmentedToggle(
                toggle_frame,
                options=[("Default", "default"), ("Replace", "replace"), ("Show", "show")],
                default_value="default"
            )
            self.response_toggle.pack(anchor="center")
            
            # Modifier bar - get from global settings
            from .prompts import get_prompts_config
            modifiers = get_prompts_config().get_modifiers()
            if modifiers:
                self.modifier_bar = ModifierBar(
                    content_frame,
                    modifiers=modifiers,
                    on_change=self._on_modifiers_changed
                )
                self.modifier_bar.pack(fill="x")
            
            # Edit input
            edit_frame = ctk.CTkFrame(
                content_frame,
                fg_color=self.colors.surface0,
                corner_radius=8,
                border_color=self.colors.surface2,
                border_width=1
            )
            edit_frame.pack(fill="x", pady=(0, 6))
            
            self.edit_input = ctk.CTkEntry(
                edit_frame,
                placeholder_text=self.PLACEHOLDER_EDIT,
                font=get_ctk_font(size=12),
                height=40,
                corner_radius=0,
                fg_color="transparent",
                border_width=0,
                text_color=self.colors.text,
                placeholder_text_color=self.colors.overlay0
            )
            # Create a fixed-size container for the button to prevent scaling issues
            edit_btn_container = ctk.CTkFrame(
                edit_frame,
                width=40,
                height=40,
                fg_color="transparent"
            )
            edit_btn_container.pack(side="right")
            edit_btn_container.pack_propagate(False)

            # Create Edit button using helper
            edit_btn = create_emoji_button(
                edit_btn_container,
                text="",
                icon="✏️",
                colors=self.colors,
                variant="primary",
                width=40,
                height=40,
                font_size=14,
                command=self._on_custom_submit
            )
            # Ensure proper styling
            edit_btn.configure(corner_radius=8)
            edit_btn.pack(fill="both", expand=True)
            
            self.edit_input = ctk.CTkEntry(
                edit_frame,
                placeholder_text=self.PLACEHOLDER_EDIT,
                font=get_ctk_font(size=12),
                height=40,
                corner_radius=0,
                fg_color="transparent",
                border_width=0,
                text_color=self.colors.text,
                placeholder_text_color=self.colors.overlay0
            )
            self.edit_input.pack(side="left", fill="x", expand=True, padx=(10, 0))
            self.edit_input.bind('<Return>', lambda e: self._on_custom_submit())
            Tooltip(edit_btn, "Edit text with custom instructions")
            
            # Ask input
            ask_frame = ctk.CTkFrame(
                content_frame,
                fg_color=self.colors.surface0,
                corner_radius=8,
                border_color=self.colors.surface2,
                border_width=1
            )
            ask_frame.pack(fill="x", pady=(0, 8))
            
            self.ask_input = ctk.CTkEntry(
                ask_frame,
                placeholder_text=self.PLACEHOLDER_ASK,
                font=get_ctk_font(size=12),
                height=40,
                corner_radius=0,
                fg_color="transparent",
                border_width=0,
                text_color=self.colors.text,
                placeholder_text_color=self.colors.overlay0
            )
            # Create a fixed-size container for the button to prevent scaling issues
            ask_btn_container = ctk.CTkFrame(
                ask_frame,
                width=40,
                height=40,
                fg_color="transparent"
            )
            ask_btn_container.pack(side="right")
            ask_btn_container.pack_propagate(False)

            # Create Ask button using helper
            ask_btn = create_emoji_button(
                ask_btn_container,
                text="",
                icon="❓",
                colors=self.colors,
                variant="success",
                width=40,
                height=40,
                font_size=14,
                command=self._on_ask_submit
            )
            # Ensure proper styling
            ask_btn.configure(corner_radius=8)
            ask_btn.pack(fill="both", expand=True)

            self.ask_input = ctk.CTkEntry(
                ask_frame,
                placeholder_text=self.PLACEHOLDER_ASK,
                font=get_ctk_font(size=12),
                height=40,
                corner_radius=0,
                fg_color="transparent",
                border_width=0,
                text_color=self.colors.text,
                placeholder_text_color=self.colors.overlay0
            )
            self.ask_input.pack(side="left", fill="x", expand=True, padx=(10, 0))
            self.ask_input.bind('<Return>', lambda e: self._on_ask_submit())
            Tooltip(ask_btn, "Ask a question about the text")
            
            # Action buttons
            self._create_carousel(content_frame)
        else:
            # Fallback to tk
            self.root.configure(bg=self.colors.base)
            
            main_frame = tk.Frame(
                self.root,
                bg=self.colors.base,
                highlightbackground=self.colors.surface2,
                highlightthickness=1
            )
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            content_frame = tk.Frame(main_frame, bg=self.colors.base)
            content_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
            
            # Top bar with close button
            top_bar = tk.Frame(content_frame, bg=self.colors.base)
            top_bar.pack(fill=tk.X, pady=(0, 8))
            
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
            
            # Response mode toggle
            toggle_frame = tk.Frame(content_frame, bg=self.colors.base)
            toggle_frame.pack(fill=tk.X, pady=(0, 12))
            
            self.response_toggle = SegmentedToggle(
                toggle_frame,
                options=[("Default", "default"), ("Replace", "replace"), ("Show", "show")],
                default_value="default"
            )
            self.response_toggle.pack(anchor=tk.CENTER)
            
            # Modifier bar - get from global settings
            from .prompts import get_prompts_config
            modifiers = get_prompts_config().get_modifiers()
            if modifiers:
                self.modifier_bar = ModifierBar(
                    content_frame,
                    modifiers=modifiers,
                    on_change=self._on_modifiers_changed
                )
                self.modifier_bar.pack(fill=tk.X)
            
            # Edit input area
            edit_container = tk.Frame(
                content_frame,
                bg=self.colors.surface0,
                highlightbackground=self.colors.surface2,
                highlightthickness=1
            )
            edit_container.pack(fill=tk.X, pady=(0, 8))
            
            # Edit send button
            edit_send_btn = tk.Label(
                edit_container,
                text="      ✏️",
                font=("Arial", 12),
                bg=self.colors.blue,
                fg="#ffffff",
                width=4,
                pady=8,
                cursor="hand2"
            )
            edit_send_btn.pack(side=tk.RIGHT, fill=tk.Y)
            edit_send_btn.bind('<Button-1>', lambda e: self._on_custom_submit())
            edit_send_btn.bind('<Enter>', lambda e: edit_send_btn.config(bg=self.colors.lavender))
            edit_send_btn.bind('<Leave>', lambda e: edit_send_btn.config(bg=self.colors.blue))
            Tooltip(edit_send_btn, "Edit text with custom instructions")
            
            self.edit_input_var = tk.StringVar(master=self.root)
            
            self.edit_input = tk.Entry(
                edit_container,
                textvariable=self.edit_input_var,
                font=("Arial", 11),
                bg=self.colors.surface0,
                fg=self.colors.text,
                insertbackground=self.colors.text,
                relief=tk.FLAT,
                bd=0
            )
            self.edit_input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
            self.edit_input.insert(0, self.PLACEHOLDER_EDIT)
            self.edit_input.config(fg=self.colors.overlay0)
            
            self.edit_input.bind('<FocusIn>', lambda e: self._on_edit_focus_in())
            self.edit_input.bind('<FocusOut>', lambda e: self._on_edit_focus_out())
            self.edit_input.bind('<Return>', lambda e: self._on_custom_submit())
            
            # Ask input area
            ask_container = tk.Frame(
                content_frame,
                bg=self.colors.surface0,
                highlightbackground=self.colors.surface2,
                highlightthickness=1
            )
            ask_container.pack(fill=tk.X, pady=(0, 12))
            
            # Ask send button
            ask_send_btn = tk.Label(
                ask_container,
                text="❓",
                font=("Arial", 12),
                bg=self.colors.green,
                fg="#ffffff",
                width=4,
                pady=8,
                cursor="hand2"
            )
            ask_send_btn.pack(side=tk.RIGHT, fill=tk.Y)
            ask_send_btn.bind('<Button-1>', lambda e: self._on_ask_submit())
            ask_send_btn.bind('<Enter>', lambda e: ask_send_btn.config(bg=self.colors.peach))
            ask_send_btn.bind('<Leave>', lambda e: ask_send_btn.config(bg=self.colors.green))
            Tooltip(ask_send_btn, "Ask a question about the text")
            
            self.ask_input_var = tk.StringVar(master=self.root)
            
            self.ask_input = tk.Entry(
                ask_container,
                textvariable=self.ask_input_var,
                font=("Arial", 11),
                bg=self.colors.surface0,
                fg=self.colors.text,
                insertbackground=self.colors.text,
                relief=tk.FLAT,
                bd=0
            )
            self.ask_input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
            self.ask_input.insert(0, self.PLACEHOLDER_ASK)
            self.ask_input.config(fg=self.colors.overlay0)
            
            self.ask_input.bind('<FocusIn>', lambda e: self._on_ask_focus_in())
            self.ask_input.bind('<FocusOut>', lambda e: self._on_ask_focus_out())
            self.ask_input.bind('<Return>', lambda e: self._on_ask_submit())
            
            # Action buttons carousel
            self._create_carousel_tk(content_frame)
        
        # Force Tk to process all pending drawing commands before showing
        self._position_window()
        self.root.update_idletasks()
        # Use delayed deiconify to let CTk finish internal rendering
        self.root.after(10, self._show_and_focus)
    
    def _show_and_focus(self):
        """Show window after CTk has finished rendering (prevents flickering)."""
        if not self.root:
            return
        try:
            self.root.deiconify()
            self.root.bind('<Escape>', lambda e: self._close())
            self.root.lift()
            self.root.focus_force()
            if HAVE_CTK:
                self.edit_input.focus_set()
        except tk.TclError:
            pass
    
    def _create_carousel(self, parent):
        """Create the carousel with action buttons."""
        settings = self.options.get("_settings", {})
        use_groups = settings.get("popup_use_groups", False)
        
        if use_groups:
            popup_groups = settings.get("popup_groups", [])
            if popup_groups:
                groups = []
                for group_def in popup_groups:
                    group_name = group_def.get("name", "")
                    item_keys = group_def.get("items", [])
                    
                    items = []
                    for key in item_keys:
                        option = self.options.get(key)
                        if option and key != "Custom" and not key.startswith("_"):
                            icon = option.get("icon", None)
                            tooltip = option.get("task", None)
                            items.append((key, key, icon, tooltip))
                    
                    if items:
                        groups.append({"name": group_name, "items": items})
                
                if groups:
                    self.grouped_list = GroupedButtonList(
                        parent,
                        groups=groups,
                        on_click=self._on_option_click,
                        on_group_changed=self._reposition_window
                    )
                    self.grouped_list.pack(fill="x")
                    return
        
        # Flat carousel
        items_per_page = settings.get("popup_items_per_page", CarouselButtonList.DEFAULT_ITEMS_PER_PAGE)
        items = []
        for key, option in self.options.items():
            if key == "Custom" or key.startswith("_"):
                continue
            icon = option.get("icon", None)
            tooltip = option.get("task", None)
            items.append((key, key, icon, tooltip))
        
        if items:
            carousel = CarouselButtonList(
                parent,
                items=items,
                on_click=self._on_option_click,
                items_per_page=items_per_page
            )
            carousel.pack(fill="x")
    
    def _create_carousel_tk(self, parent):
        """Create the carousel with action buttons (tk fallback)."""
        settings = self.options.get("_settings", {})
        use_groups = settings.get("popup_use_groups", False)
        
        if use_groups:
            popup_groups = settings.get("popup_groups", [])
            if popup_groups:
                groups = []
                for group_def in popup_groups:
                    group_name = group_def.get("name", "")
                    item_keys = group_def.get("items", [])
                    
                    items = []
                    for key in item_keys:
                        option = self.options.get(key)
                        if option and key != "Custom" and not key.startswith("_"):
                            icon = option.get("icon", None)
                            tooltip = option.get("task", None)
                            items.append((key, key, icon, tooltip))
                    
                    if items:
                        groups.append({"name": group_name, "items": items})
                
                if groups:
                    self.grouped_list = GroupedButtonList(
                        parent,
                        groups=groups,
                        on_click=self._on_option_click,
                        on_group_changed=self._reposition_window
                    )
                    self.grouped_list.pack(fill=tk.X)
                    return
        
        # Flat carousel
        items_per_page = settings.get("popup_items_per_page", CarouselButtonList.DEFAULT_ITEMS_PER_PAGE)
        items = []
        for key, option in self.options.items():
            if key == "Custom" or key.startswith("_"):
                continue
            icon = option.get("icon", None)
            tooltip = option.get("task", None)
            items.append((key, key, icon, tooltip))
        
        if items:
            carousel = CarouselButtonList(
                parent,
                items=items,
                on_click=self._on_option_click,
                items_per_page=items_per_page
            )
            carousel.pack(fill=tk.X)
    
    def _on_edit_focus_in(self):
        """Handle edit input focus in (tk fallback)."""
        if self.edit_input.get() == self.PLACEHOLDER_EDIT:
            self.edit_input.delete(0, tk.END)
            self.edit_input.config(fg=self.colors.text)
    
    def _on_edit_focus_out(self):
        """Handle edit input focus out (tk fallback)."""
        if not self.edit_input.get():
            self.edit_input.insert(0, self.PLACEHOLDER_EDIT)
            self.edit_input.config(fg=self.colors.overlay0)
    
    def _on_ask_focus_in(self):
        """Handle ask input focus in (tk fallback)."""
        if self.ask_input.get() == self.PLACEHOLDER_ASK:
            self.ask_input.delete(0, tk.END)
            self.ask_input.config(fg=self.colors.text)
    
    def _on_ask_focus_out(self):
        """Handle ask input focus out (tk fallback)."""
        if not self.ask_input.get():
            self.ask_input.insert(0, self.PLACEHOLDER_ASK)
            self.ask_input.config(fg=self.colors.overlay0)
    
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
    
    def _on_modifiers_changed(self, active_modifiers: List[str]):
        """Handle modifier toggle changes."""
        self.active_modifiers = active_modifiers
    
    def _on_option_click(self, option_key: str):
        """Handle action button click."""
        response_mode = self._get_effective_response_mode(option_key)
        self._close()
        self.on_option_selected(option_key, self.selected_text, None, response_mode, self.active_modifiers)
    
    def _on_custom_submit(self):
        """Handle custom edit submission."""
        if HAVE_CTK:
            custom_text = self.edit_input.get().strip()
        else:
            custom_text = self.edit_input_var.get().strip() if hasattr(self, 'edit_input_var') and self.edit_input_var else ""
        
        if not custom_text or custom_text == self.PLACEHOLDER_EDIT:
            return
        
        response_mode = self._get_effective_response_mode("_Custom")
        self._close()
        self.on_option_selected("_Custom", self.selected_text, custom_text, response_mode, self.active_modifiers)
    
    def _on_ask_submit(self):
        """Handle ask submission."""
        if HAVE_CTK:
            ask_text = self.ask_input.get().strip()
        else:
            ask_text = self.ask_input_var.get().strip() if hasattr(self, 'ask_input_var') and self.ask_input_var else ""
        
        if not ask_text or ask_text == self.PLACEHOLDER_ASK:
            return
        
        response_mode = self._get_effective_response_mode("_Ask")
        self._close()
        self.on_option_selected("_Ask", self.selected_text, ask_text, response_mode, self.active_modifiers)
    
    def _get_effective_response_mode(self, option_key: str) -> str:
        """Get effective response mode, considering modifiers."""
        user_mode = self.response_toggle.get() if self.response_toggle else "default"
        
        if self.active_modifiers:
            # Get modifiers from global settings
            from .prompts import get_prompts_config
            modifiers = get_prompts_config().get_modifiers()
            for mod in modifiers:
                if mod.get("key") in self.active_modifiers:
                    if mod.get("forces_chat_window", False):
                        if user_mode != "replace":
                            return "show"
        
        return user_mode
    
    def _close(self):
        """Close the popup."""
        if self.root:
            try:
                self.root.destroy()
            except tk.TclError:
                pass
            self.root = None
        if self.on_close_callback:
            self.on_close_callback()


def create_attached_input_popup(
    parent_root,
    on_submit: Callable[[str, str], None],
    on_close: Optional[Callable[[], None]],
    x: Optional[int] = None,
    y: Optional[int] = None
):
    """Create an input popup as Toplevel attached to parent root."""
    AttachedInputPopup(parent_root, on_submit, on_close, x, y)


def create_attached_prompt_popup(
    parent_root,
    options: Dict,
    on_option_selected: Callable[[str, str, Optional[str], str, List[str]], None],
    on_close: Optional[Callable[[], None]],
    selected_text: str,
    x: Optional[int] = None,
    y: Optional[int] = None
):
    """Create a prompt selection popup as Toplevel attached to parent root."""
    AttachedPromptPopup(parent_root, options, on_option_selected, on_close, selected_text, x, y)


# =============================================================================
# Typing Indicator - Floating tooltip during streaming
# =============================================================================

class TypingIndicator:
    """
    A small floating indicator that shows during streaming typing.
    Displays near the mouse cursor and shows abort hotkey.
    Uses CustomTkinter for modern appearance.
    """
    
    OFFSET_X = 20
    OFFSET_Y = 20
    
    def __init__(
        self,
        parent_root,
        abort_hotkey: str = "Escape",
        on_dismiss: Optional[Callable[[], None]] = None
    ):
        self.parent_root = parent_root
        self.abort_hotkey = abort_hotkey
        self.on_dismiss = on_dismiss
        
        self.colors = get_colors()
        self.root = None
        self.is_visible = False
        
        self._create_window()
    
    def _create_window(self):
        """Create the indicator window."""
        if HAVE_CTK:
            self.root = ctk.CTkToplevel(self.parent_root)
        else:
            self.root = tk.Toplevel(self.parent_root)
        
        # Hide window while building UI (prevents flickering)
        self.root.withdraw()
        
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        
        try:
            self.root.attributes('-alpha', 0.95)
        except tk.TclError:
            pass
        
        # Set up transparent corners on Windows
        setup_transparent_popup(self.root, self.colors)
        
        # Hide from taskbar
        hide_from_taskbar(self.root)
        
        if HAVE_CTK:
            main_frame = ctk.CTkFrame(
                self.root,
                corner_radius=8,
                fg_color=self.colors.surface0,
                border_color=self.colors.blue,
                border_width=2
            )
            main_frame.pack(fill="both", expand=True)
            
            content_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
            content_frame.pack(padx=10, pady=8)
            
            # Try to use emoji image for typing indicator
            typing_emoji_img = None
            typing_text = "✍️ Typing..."
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                typing_emoji_img = renderer.get_ctk_image("✍️", size=16)
                if typing_emoji_img:
                    typing_text = "Typing..."  # Remove emoji from text
            
            # Build typing label kwargs - only include image/compound if we have an image
            typing_label_kwargs = {
                "text": typing_text,
                "font": get_ctk_font(size=11, weight="bold"),
                "text_color": self.colors.text
            }
            if typing_emoji_img:
                typing_label_kwargs["image"] = typing_emoji_img
                typing_label_kwargs["compound"] = "left"
            
            typing_label = ctk.CTkLabel(content_frame, **typing_label_kwargs)
            typing_label.pack(side="left")
            
            hotkey_display = self.abort_hotkey.title() if self.abort_hotkey else "Escape"
            abort_label = ctk.CTkLabel(
                content_frame,
                text=f" [{hotkey_display} to abort]",
                font=get_ctk_font(size=10),
                text_color=self.colors.overlay0
            )
            abort_label.pack(side="left")
        else:
            # Fallback
            main_frame = tk.Frame(
                self.root,
                bg=self.colors.surface0,
                highlightbackground=self.colors.blue,
                highlightthickness=2
            )
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            content_frame = tk.Frame(main_frame, bg=self.colors.surface0)
            content_frame.pack(padx=8, pady=6)
            
            tk.Label(
                content_frame,
                text="✍️ Typing...",
                font=("Arial", 10, "bold"),
                bg=self.colors.surface0,
                fg=self.colors.text
            ).pack(side=tk.LEFT)
            
            hotkey_display = self.abort_hotkey.title() if self.abort_hotkey else "Escape"
            tk.Label(
                content_frame,
                text=f" [{hotkey_display} to abort]",
                font=("Arial", 9),
                bg=self.colors.surface0,
                fg=self.colors.overlay0
            ).pack(side=tk.LEFT)
        
        # Force Tk to process all pending drawing commands before showing
        self.root.update_idletasks()
        # Use delayed deiconify for smoother appearance
        self.root.after(10, self._show_indicator)
    
    def _show_indicator(self):
        """Show indicator after CTk has finished rendering."""
        if not self.root:
            return
        try:
            self.root.deiconify()
            self.is_visible = True
            self._update_position()
        except tk.TclError:
            pass
    
    def _update_position(self):
        """Set window position near cursor."""
        if not self.root or not self.is_visible:
            return
        
        try:
            x = self.root.winfo_pointerx() + self.OFFSET_X
            y = self.root.winfo_pointery() + self.OFFSET_Y
            
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            
            self.root.update_idletasks()
            window_width = self.root.winfo_width()
            window_height = self.root.winfo_height()
            
            if x + window_width > screen_width:
                x = self.root.winfo_pointerx() - window_width - 10
            if y + window_height > screen_height:
                y = self.root.winfo_pointery() - window_height - 10
            
            self.root.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
    
    def dismiss(self):
        """Dismiss the indicator."""
        self.is_visible = False
        
        if self.root:
            try:
                self.root.withdraw()  # Immediate visual feedback
                self.root.destroy()
            except tk.TclError:
                pass
            self.root = None
        
        if self.on_dismiss:
            try:
                self.on_dismiss()
            except Exception:
                pass


# Global reference
_current_typing_indicator: Optional[TypingIndicator] = None


def create_typing_indicator(
    parent_root,
    abort_hotkey: str = "Escape",
    on_dismiss: Optional[Callable[[], None]] = None
) -> TypingIndicator:
    """Create and show a typing indicator."""
    global _current_typing_indicator
    
    if _current_typing_indicator:
        _current_typing_indicator.dismiss()
    
    _current_typing_indicator = TypingIndicator(parent_root, abort_hotkey, on_dismiss)
    return _current_typing_indicator


def dismiss_typing_indicator():
    """Dismiss the current typing indicator if any."""
    global _current_typing_indicator
    
    if _current_typing_indicator:
        _current_typing_indicator.dismiss()
        _current_typing_indicator = None


# =============================================================================
# Error Popup - Display API errors to user
# =============================================================================

class ErrorPopup:
    """
    Error dialog popup for displaying API failures.
    Matches the theme and style of other popups.
    """
    
    def __init__(
        self,
        parent_root,
        title: str,
        message: str,
        details: Optional[str] = None,
        on_close: Optional[Callable[[], None]] = None
    ):
        self.parent_root = parent_root
        self.title = title
        self.message = message
        self.details = details
        self.on_close_callback = on_close
        
        self.colors = get_colors()
        self.root = None
        
        self._create_window()
    
    def _create_window(self):
        """Create the error popup window."""
        if HAVE_CTK:
            self.root = ctk.CTkToplevel(self.parent_root)
        else:
            self.root = tk.Toplevel(self.parent_root)
        
        self.root.withdraw()
        self.root.title("Error")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        
        setup_transparent_popup(self.root, self.colors)
        hide_from_taskbar(self.root)
        
        if HAVE_CTK:
            main_frame = ctk.CTkFrame(
                self.root,
                corner_radius=10,
                fg_color=self.colors.base,
                border_color=self.colors.red,
                border_width=2
            )
            main_frame.pack(fill="both", expand=True, padx=1, pady=1)
            
            content_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
            content_frame.pack(fill="both", expand=True, padx=12, pady=12)
            
            # Header with error icon
            header_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
            header_frame.pack(fill="x", pady=(0, 8))
            
            # Try to use emoji image
            error_icon_text = "❌ Error"
            header_label_created = False
            
            if HAVE_EMOJI:
                try:
                    renderer = get_emoji_renderer()
                    error_img = renderer.get_ctk_image("❌", size=20)
                    if error_img:
                        ctk.CTkLabel(
                            header_frame,
                            text=" Error",
                            image=error_img,
                            compound="left",
                            font=get_ctk_font(size=14, weight="bold"),
                            text_color=self.colors.red
                        ).pack(side="left")
                        header_label_created = True
                except Exception:
                    pass
            
            if not header_label_created:
                ctk.CTkLabel(
                    header_frame,
                    text=error_icon_text,
                    font=get_ctk_font(size=14, weight="bold"),
                    text_color=self.colors.red
                ).pack(side="left")
            
            # Close button
            close_btn = ctk.CTkButton(
                header_frame,
                text="×",
                width=24,
                height=24,
                corner_radius=6,
                fg_color="transparent",
                hover_color=self.colors.red,
                text_color=self.colors.overlay0,
                font=get_ctk_font(size=14, weight="bold"),
                command=self._close
            )
            close_btn.pack(side="right")
            
            # Title
            if self.title:
                ctk.CTkLabel(
                    content_frame,
                    text=self.title,
                    font=get_ctk_font(size=13, weight="bold"),
                    text_color=self.colors.text,
                    wraplength=350
                ).pack(anchor="w", pady=(0, 4))
            
            # Message
            ctk.CTkLabel(
                content_frame,
                text=self.message,
                font=get_ctk_font(size=12),
                text_color=self.colors.text,
                wraplength=350,
                justify="left"
            ).pack(anchor="w", pady=(0, 8))
            
            # Details (scrollable)
            if self.details:
                details_frame = ctk.CTkFrame(
                    content_frame,
                    fg_color=self.colors.surface0,
                    corner_radius=6
                )
                details_frame.pack(fill="x", pady=(0, 8))
                
                details_text = ctk.CTkTextbox(
                    details_frame,
                    height=100,
                    font=get_ctk_font(size=10),
                    fg_color=self.colors.surface0,
                    text_color=self.colors.overlay0,
                    wrap="word"
                )
                details_text.pack(fill="x", padx=8, pady=8)
                details_text.insert("0.0", self.details)
                details_text.configure(state="disabled")
            
            # Buttons
            btn_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
            btn_frame.pack(fill="x")
            
            # Copy to clipboard button (if details)
            if self.details:
                copy_btn = create_emoji_button(
                    btn_frame,
                    text="Copy",
                    icon="📋",
                    colors=self.colors,
                    hover_color=self.colors.accent_green,
                    variant="secondary",
                    width=80,
                    height=32,
                    font_size=11,
                    command=self._copy_to_clipboard
                )
                # Override to match surface0 background of details area
                copy_btn.configure(fg_color=self.colors.surface0)
                copy_btn.pack(side="left", padx=(0, 8))
            
            # OK button
            ok_btn = ctk.CTkButton(
                btn_frame,
                text="OK",
                width=80,
                height=32,
                corner_radius=6,
                fg_color=self.colors.blue,
                hover_color=self.colors.accent_green,
                text_color="#ffffff",
                font=get_ctk_font(size=11),
                command=self._close
            )
            ok_btn.pack(side="right")
        
        else:
            # Fallback tk implementation
            self.root.configure(bg=self.colors.base)
            
            main_frame = tk.Frame(
                self.root,
                bg=self.colors.base,
                highlightbackground=self.colors.red,
                highlightthickness=2
            )
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            content_frame = tk.Frame(main_frame, bg=self.colors.base)
            content_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
            
            # Header
            header_frame = tk.Frame(content_frame, bg=self.colors.base)
            header_frame.pack(fill=tk.X, pady=(0, 8))
            
            tk.Label(
                header_frame,
                text="❌ Error",
                font=("Arial", 12, "bold"),
                bg=self.colors.base,
                fg=self.colors.red
            ).pack(side=tk.LEFT)
            
            close_btn = tk.Label(
                header_frame,
                text="×",
                font=("Arial", 14, "bold"),
                bg=self.colors.base,
                fg=self.colors.overlay0,
                cursor="hand2"
            )
            close_btn.pack(side=tk.RIGHT)
            close_btn.bind('<Button-1>', lambda e: self._close())
            
            # Title
            if self.title:
                tk.Label(
                    content_frame,
                    text=self.title,
                    font=("Arial", 11, "bold"),
                    bg=self.colors.base,
                    fg=self.colors.text,
                    wraplength=350,
                    anchor="w",
                    justify=tk.LEFT
                ).pack(anchor="w", pady=(0, 4))
            
            # Message
            tk.Label(
                content_frame,
                text=self.message,
                font=("Arial", 10),
                bg=self.colors.base,
                fg=self.colors.text,
                wraplength=350,
                anchor="w",
                justify=tk.LEFT
            ).pack(anchor="w", pady=(0, 8))
            
            # Details
            if self.details:
                details_frame = tk.Frame(
                    content_frame,
                    bg=self.colors.surface0,
                    highlightbackground=self.colors.surface2,
                    highlightthickness=1
                )
                details_frame.pack(fill=tk.X, pady=(0, 8))
                
                details_text = tk.Text(
                    details_frame,
                    height=5,
                    font=("Arial", 9),
                    bg=self.colors.surface0,
                    fg=self.colors.overlay0,
                    wrap=tk.WORD,
                    relief=tk.FLAT,
                    bd=0
                )
                details_text.pack(fill=tk.X, padx=8, pady=8)
                details_text.insert("1.0", self.details)
                details_text.configure(state=tk.DISABLED)
            
            # Buttons
            btn_frame = tk.Frame(content_frame, bg=self.colors.base)
            btn_frame.pack(fill=tk.X)
            
            if self.details:
                copy_btn = tk.Label(
                    btn_frame,
                    text="📋 Copy",
                    font=("Arial", 10),
                    bg=self.colors.surface0,
                    fg=self.colors.text,
                    padx=12,
                    pady=6,
                    cursor="hand2"
                )
                copy_btn.pack(side=tk.LEFT, padx=(0, 8))
                copy_btn.bind('<Button-1>', lambda e: self._copy_to_clipboard())
            
            ok_btn = tk.Label(
                btn_frame,
                text="OK",
                font=("Arial", 10),
                bg=self.colors.blue,
                fg="#ffffff",
                padx=16,
                pady=6,
                cursor="hand2"
            )
            ok_btn.pack(side=tk.RIGHT)
            ok_btn.bind('<Button-1>', lambda e: self._close())
        
        self._position_window()
        self.root.update_idletasks()
        self.root.after(10, self._show_and_focus)
    
    def _show_and_focus(self):
        if not self.root:
            return
        try:
            self.root.deiconify()
            self.root.bind('<Escape>', lambda e: self._close())
            self.root.bind('<Return>', lambda e: self._close())
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass
    
    def _position_window(self):
        """Position window at center of screen."""
        self.root.update_idletasks()
        
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = max(400, self.root.winfo_reqwidth())
        window_height = self.root.winfo_reqheight()
        
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
    
    def _copy_to_clipboard(self):
        """Copy error details to clipboard."""
        import pyperclip
        text = f"{self.title}\n\n{self.message}"
        if self.details:
            text += f"\n\nDetails:\n{self.details}"
        try:
            pyperclip.copy(text)
        except Exception:
            pass
    
    def _close(self):
        if self.root:
            try:
                self.root.destroy()
            except tk.TclError:
                pass
            self.root = None
        if self.on_close_callback:
            self.on_close_callback()


def create_error_popup(
    parent_root,
    title: str,
    message: str,
    details: Optional[str] = None,
    on_close: Optional[Callable[[], None]] = None
):
    """Create and show an error popup."""
    ErrorPopup(parent_root, title, message, details, on_close)


def show_error_popup(title: str, message: str, details: Optional[str] = None):
    """
    Show an error popup via GUICoordinator - thread-safe.
    
    This can be called from any thread and will show the error popup
    on the main GUI thread.
    
    Args:
        title: Error title (e.g., "API Request Failed")
        message: User-friendly message describing the error
        details: Optional detailed error information (technical details)
    """
    from .core import GUICoordinator
    coordinator = GUICoordinator.get_instance()
    coordinator.ensure_running()
    coordinator._request_queue.put({
        'type': 'error_popup',
        'title': title,
        'message': message,
        'details': details
    })


# =============================================================================
# Toast Notification - Temporary bottom-right message
# =============================================================================

class ToastNotification:
    """
    A toast notification that appears at the bottom-right corner.
    Shows a preview of copied content and auto-dismisses.
    Matches the theme and style of other popups.
    """
    
    PREVIEW_MAX_CHARS = 150
    DEFAULT_TIMEOUT_MS = 4000
    MARGIN_X = 20
    MARGIN_Y = 20
    
    def __init__(
        self,
        parent_root,
        title: str,
        message: str,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        on_dismiss: Optional[Callable[[], None]] = None
    ):
        self.parent_root = parent_root
        self.title = title
        self.message = message
        self.timeout_ms = timeout_ms
        self.on_dismiss = on_dismiss
        
        self.colors = get_colors()
        self.root = None
        
        # Animation state
        self.target_x = 0
        self.target_y = 0
        self.timeout_job = None
        self.fade_job = None
        self.hover_job = None
        
        self._create_window()
    
    def _create_window(self):
        """Create the toast window."""
        if HAVE_CTK:
            self.root = ctk.CTkToplevel(self.parent_root)
        else:
            self.root = tk.Toplevel(self.parent_root)
        
        # Hide window while building
        self.root.withdraw()
        
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        
        # Start transparent for fade-in
        try:
            self.root.attributes('-alpha', 0.0)
        except tk.TclError:
            pass
        
        # Set up transparent corners on Windows
        setup_transparent_popup(self.root, self.colors)
        
        # Hide from taskbar
        hide_from_taskbar(self.root)
        
        if HAVE_CTK:
            self._build_ctk_ui()
        else:
            self._build_tk_ui()
        
        # Position and show with animation
        self._position_window()
        self.root.update_idletasks()
        self.root.after(10, self._show)
    
    def _build_ctk_ui(self):
        """Build CustomTkinter UI."""
        main_frame = ctk.CTkFrame(
            self.root,
            corner_radius=10,
            fg_color=self.colors.surface0,
            border_color=self.colors.green,  # Green border for success
            border_width=2
        )
        main_frame.pack(fill="both", expand=True, padx=1, pady=1)
        
        # Bind verify hover to main elements to be responsive
        def on_click(e): self.dismiss()
        main_frame.bind("<Button-1>", on_click)
        
        content = ctk.CTkFrame(main_frame, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=12, pady=10)
        content.bind("<Button-1>", on_click)
        
        # Header
        header = ctk.CTkFrame(content, fg_color="transparent")
        header.pack(fill="x", pady=(0, 4))
        header.bind("<Button-1>", on_click)
        
        # Icon and Title
        icon_frame = ctk.CTkFrame(header, fg_color="transparent")
        icon_frame.pack(side="left")
        icon_frame.bind("<Button-1>", on_click)
        
        # Try to use emoji image
        icon_text = "📋 " + self.title
        label_kwargs = {
            "text": icon_text,
            "font": get_ctk_font(size=12, weight="bold"),
            "text_color": self.colors.text
        }
        
        if HAVE_EMOJI:
            try:
                renderer = get_emoji_renderer()
                # Use checkmark or clipboard based on content
                icon_char = "✅"
                icon_img = renderer.get_ctk_image(icon_char, size=16)
                if icon_img:
                    label_kwargs["text"] = " " + self.title
                    label_kwargs["image"] = icon_img
                    label_kwargs["compound"] = "left"
            except Exception:
                pass
        
        title_lbl = ctk.CTkLabel(icon_frame, **label_kwargs)
        title_lbl.pack(side="left")
        title_lbl.bind("<Button-1>", on_click)
        
        # Message preview
        preview_text = self.message
        if len(preview_text) > self.PREVIEW_MAX_CHARS:
            preview_text = preview_text[:self.PREVIEW_MAX_CHARS] + "..."
            
        msg_lbl = ctk.CTkLabel(
            content,
            text=preview_text,
            font=get_ctk_font(size=11),
            text_color=self.colors.overlay0,
            wraplength=300,
            justify="left"
        )
        msg_lbl.pack(anchor="w")
        msg_lbl.bind("<Button-1>", on_click)
        
        # Footer text (click to dismiss)
        footer = ctk.CTkLabel(
            content,
            text="Click to dismiss",
            font=get_ctk_font(size=9),
            text_color=self.colors.surface2
        )
        footer.pack(anchor="e", pady=(4, 0))
        footer.bind("<Button-1>", on_click)

    def _build_tk_ui(self):
        """Build standard Tkinter UI."""
        self.root.configure(bg=self.colors.base)
        
        main_frame = tk.Frame(
            self.root,
            bg=self.colors.surface0,
            highlightbackground=self.colors.green,
            highlightthickness=2
        )
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.bind("<Button-1>", lambda e: self.dismiss())
        
        content = tk.Frame(main_frame, bg=self.colors.surface0)
        content.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        content.bind("<Button-1>", lambda e: self.dismiss())
        
        # Header
        header = tk.Frame(content, bg=self.colors.surface0)
        header.pack(fill=tk.X, pady=(0, 4))
        header.bind("<Button-1>", lambda e: self.dismiss())
        
        tk.Label(
            header,
            text="✅ " + self.title,
            font=("Arial", 11, "bold"),
            bg=self.colors.surface0,
            fg=self.colors.text
        ).pack(side=tk.LEFT)
        
        # Message preview
        preview_text = self.message
        if len(preview_text) > self.PREVIEW_MAX_CHARS:
            preview_text = preview_text[:self.PREVIEW_MAX_CHARS] + "..."
            
        msg_lbl = tk.Label(
            content,
            text=preview_text,
            font=("Arial", 10),
            bg=self.colors.surface0,
            fg=self.colors.overlay0,
            wraplength=300,
            justify=tk.LEFT
        )
        msg_lbl.pack(anchor="w")
        msg_lbl.bind("<Button-1>", lambda e: self.dismiss())

    def _position_window(self):
        """Calculate target position at bottom right of screen."""
        self.root.update_idletasks()
        
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = self.root.winfo_reqwidth()
        window_height = self.root.winfo_reqheight()
        
        # Position with margin from bottom-right corner
        self.target_x = screen_width - window_width - self.MARGIN_X
        # Target Y is the final resting position
        self.target_y = screen_height - window_height - self.MARGIN_Y - 40 # Account for taskbar
        
        # Start from bottom of screen (off-screen)
        self.start_rise_y = screen_height
        
        self.root.geometry(f"+{self.target_x}+{self.start_rise_y}")
    
    def _show(self):
        """Show the window and start entry animation."""
        if not self.root:
            return
        
        try:
            self.root.deiconify()
            self.root.lift()
            
            # Start entry animation (rise + fade in)
            self._animate_entry()
            
            # Start hover monitor
            self._start_hover_monitor()
            
        except tk.TclError:
            pass
    
    def _animate_entry(self, step=0):
        """Animate window entering (rise up from bottom)."""
        if not self.root: return
        
        total_steps = 15
        progress = (step + 1) / total_steps
        if progress > 1.0: progress = 1.0
        
        try:
            # Fade in (Alpha 0 -> 1)
            self.root.attributes('-alpha', progress)
            
            # Rise up (from bottom screen to target)
            # Use sinusoidal easing for smooth pop-up
            ease = math.sin(progress * math.pi / 2)
            
            dist = self.start_rise_y - self.target_y
            current_y = int(self.start_rise_y - (dist * ease))
            self.root.geometry(f"+{self.target_x}+{current_y}")
            
            if progress < 1.0:
                self.root.after(16, lambda: self._animate_entry(step + 1))
            else:
                self._start_gradual_fade()
        except tk.TclError:
            pass

    def _start_gradual_fade(self):
        """Start fading out continuously over timeout duration."""
        if self.fade_job:
            self.root.after_cancel(self.fade_job)
            self.fade_job = None
            
        # Update every 50ms
        interval = 50
        total_steps = int(self.timeout_ms / interval)
        if total_steps < 1: total_steps = 1
        
        self._run_fade_step(total_steps, total_steps)
        
    def _run_fade_step(self, remaining_steps, total_steps):
        """Run single step of fade out."""
        if not self.root: return
        
        try:
            alpha = remaining_steps / total_steps
            self.root.attributes('-alpha', alpha)
            
            if remaining_steps > 0:
                self.fade_job = self.root.after(50, lambda: self._run_fade_step(remaining_steps - 1, total_steps))
            else:
                self.dismiss()
        except tk.TclError:
            pass

    def _start_hover_monitor(self):
        """Start checking for mouse hover position."""
        if not self.root: return
        self._check_hover()
        self.hover_job = self.root.after(100, self._start_hover_monitor)
        
    def _check_hover(self):
        """Check if mouse is over window and manage state."""
        if not self.root: return
        
        try:
            x, y = self.root.winfo_pointerxy()
            wx = self.root.winfo_rootx()
            wy = self.root.winfo_rooty()
            ww = self.root.winfo_width()
            wh = self.root.winfo_height()
            
            # Check collision
            is_hovering = (wx <= x <= wx + ww) and (wy <= y <= wy + wh)
            
            if is_hovering:
                # Cancel fade out, restore full opacity
                if self.fade_job:
                    self.root.after_cancel(self.fade_job)
                    self.fade_job = None
                    self.root.attributes('-alpha', 1.0)
                elif self.root.attributes('-alpha') < 1.0:
                    self.root.attributes('-alpha', 1.0)
            else:
                # If not hovering and no fade job, start fading
                if self.fade_job is None:
                    self._start_gradual_fade()
                    
        except Exception:
            pass

    def dismiss(self):
        """Dismiss the toast immediately."""
        # Cancel all jobs
        if self.timeout_job: self.root.after_cancel(self.timeout_job)
        if self.fade_job: self.root.after_cancel(self.fade_job)
        if self.hover_job: self.root.after_cancel(self.hover_job)
        
        self.timeout_job = None
        self.fade_job = None
        self.hover_job = None
            
        if self.root:
            try:
                self.root.destroy()
            except tk.TclError:
                pass
            self.root = None
        
        if self.on_dismiss:
            try:
                self.on_dismiss()
            except Exception:
                pass


def create_toast_notification(
    parent_root,
    title: str,
    message: str,
    timeout_ms: int = 4000
):
    """Create and show a toast notification."""
    ToastNotification(parent_root, title, message, timeout_ms)
