#!/usr/bin/env python3
"""
Screen snipping overlay for region capture.

Uses PIL.ImageGrab for screen capture and Tkinter Canvas for selection overlay.
Provides a fullscreen overlay where users can drag to select a region to capture.

Threading Note:
    This must be created on the GUI thread via GUICoordinator.
    Uses Tk Canvas for cross-platform overlay with stipple pattern for semi-transparency.
"""

import io
import base64
import logging
import tkinter as tk
from typing import Callable, Optional
from dataclasses import dataclass

from PIL import ImageGrab, Image, ImageTk

from .themes import get_colors, ThemeColors


@dataclass
class CaptureResult:
    """Result of a screen capture operation."""
    image_base64: str
    mime_type: str = "image/png"
    width: int = 0
    height: int = 0
    pil_image: Optional[Image.Image] = None  # For thumbnail preview


class ScreenSnipOverlay:
    """
    Fullscreen overlay for selecting a screen region.
    
    Flow:
    1. Take snapshot of entire screen with PIL.ImageGrab (for frozen background)
    2. Display as fullscreen overlay with dark tint (stipple pattern)
    3. User drags to select region (selection area shows through tint)
    4. On mouse release, hide overlay and capture just that region fresh
    5. Return base64-encoded PNG via callback
    
    The overlay uses a frozen screenshot as background rather than true
    transparency because:
    - Cross-platform compatibility
    - Prevents visual confusion from moving content behind overlay
    - More reliable than OS-specific transparency APIs
    """
    
    # Minimum selection size in pixels
    MIN_SELECTION_SIZE = 10
    
    def __init__(
        self,
        parent_root: tk.Tk,
        on_capture: Callable[[CaptureResult], None],
        on_cancel: Callable[[], None]
    ):
        """
        Initialize the screen snip overlay.
        
        Args:
            parent_root: Parent Tk root (from GUICoordinator)
            on_capture: Callback with CaptureResult when capture completes
            on_cancel: Callback when user cancels (Escape or too-small selection)
        """
        self.parent_root = parent_root
        self.on_capture = on_capture
        self.on_cancel = on_cancel
        self.colors = get_colors()
        
        # Selection state
        self.start_x = 0
        self.start_y = 0
        self.current_x = 0
        self.current_y = 0
        self.is_selecting = False
        
        # Screen capture
        self.background_image: Optional[Image.Image] = None
        self.tk_background: Optional[ImageTk.PhotoImage] = None
        self.screen_width = 0
        self.screen_height = 0
        
        # Window reference
        self.root: Optional[tk.Toplevel] = None
        self.canvas: Optional[tk.Canvas] = None
        
        self._create_overlay()
    
    def _create_overlay(self):
        """Create the fullscreen overlay window."""
        # Take initial screenshot of entire screen
        # This becomes the frozen background - overlay is shown on top
        try:
            # all_screens=True captures all monitors on Windows
            # include_layered_windows=True captures transparent windows
            self.background_image = ImageGrab.grab(
                all_screens=True,
                include_layered_windows=True
            )
            logging.debug(f"[ScreenSnip] Captured full screen: {self.background_image.size}")
        except Exception as e:
            logging.warning(f"[ScreenSnip] Multi-monitor capture failed: {e}, falling back to primary")
            try:
                self.background_image = ImageGrab.grab()
            except Exception as e2:
                logging.error(f"[ScreenSnip] Screen capture failed: {e2}")
                self.on_cancel()
                return
        
        self.screen_width, self.screen_height = self.background_image.size
        
        # Create fullscreen toplevel window
        # Use standard Toplevel (not CTkToplevel) for canvas support
        self.root = tk.Toplevel(self.parent_root)
        
        # Configure window for fullscreen overlay
        self.root.attributes('-fullscreen', True)
        self.root.attributes('-topmost', True)
        self.root.config(cursor="crosshair")
        self.root.overrideredirect(True)  # No window decorations
        
        # Position at top-left of virtual screen (handles multi-monitor)
        # On Windows, negative coordinates may be used for monitors left of primary
        self.root.geometry(f"{self.screen_width}x{self.screen_height}+0+0")
        
        # Canvas for drawing
        self.canvas = tk.Canvas(
            self.root,
            width=self.screen_width,
            height=self.screen_height,
            highlightthickness=0,
            bd=0,
            bg="black"  # Fallback color
        )
        self.canvas.pack(fill="both", expand=True)
        
        # Display frozen background
        self.tk_background = ImageTk.PhotoImage(self.background_image)
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_background, tags="bg")
        
        # Semi-transparent dark overlay using stipple pattern
        # This creates the "screen dimming" effect
        self.canvas.create_rectangle(
            0, 0, self.screen_width, self.screen_height,
            fill="black",
            stipple="gray50",  # 50% transparent black
            outline="",
            tags="overlay"
        )
        
        # Instructions text at top
        self.canvas.create_text(
            self.screen_width // 2, 30,
            text="Drag to select region • Click anywhere or Press Escape to cancel",
            fill="white",
            font=("Arial", 14, "bold"),
            tags="instructions"
        )
        
        # Mouse bindings
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        
        # Keyboard bindings
        self.root.bind("<Escape>", self._on_escape)
        self.root.bind("<Return>", self._on_enter)  # Confirm with Enter
        
        # Focus handling
        self.root.focus_force()
        self.root.grab_set()  # Modal behavior
        
        logging.debug("[ScreenSnip] Overlay created")
    
    def _on_press(self, event):
        """Handle mouse button press - start selection."""
        self.start_x = event.x
        self.start_y = event.y
        self.current_x = event.x
        self.current_y = event.y
        self.is_selecting = True
        
        # Clear any previous selection graphics
        self.canvas.delete("selection")
        self.canvas.delete("size_label")
        self.canvas.delete("clear_area")
    
    def _on_drag(self, event):
        """Handle mouse drag - update selection rectangle."""
        if not self.is_selecting:
            return
        
        self.current_x = event.x
        self.current_y = event.y
        
        # Normalize coordinates (handle drag in any direction)
        x1 = min(self.start_x, self.current_x)
        y1 = min(self.start_y, self.current_y)
        x2 = max(self.start_x, self.current_x)
        y2 = max(self.start_y, self.current_y)
        
        # Clear previous selection graphics
        self.canvas.delete("selection")
        self.canvas.delete("size_label")
        self.canvas.delete("clear_area")
        
        # Draw "clear" area where selection is (shows original image without tint)
        # This is done by drawing the original image section on top
        if x2 - x1 > 0 and y2 - y1 > 0:
            # Crop the region from background and display it
            try:
                region = self.background_image.crop((x1, y1, x2, y2))
                self._selection_photo = ImageTk.PhotoImage(region)
                self.canvas.create_image(x1, y1, anchor="nw", image=self._selection_photo, tags="clear_area")
            except Exception:
                pass
        
        # Draw selection border with glow effect
        glow_colors = ["#003300", "#006600", "#009900"]
        for i, color in enumerate(glow_colors):
            offset = len(glow_colors) - i
            self.canvas.create_rectangle(
                x1 - offset, y1 - offset, x2 + offset, y2 + offset,
                outline=color, width=1, tags="selection"
            )
        
        # Main selection border (green)
        self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline=self.colors.green, width=2, tags="selection"
        )
        
        # Corner handles
        handle_size = 5
        corners = [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]
        for cx, cy in corners:
            self.canvas.create_rectangle(
                cx - handle_size, cy - handle_size,
                cx + handle_size, cy + handle_size,
                fill=self.colors.green, outline="white", width=1, tags="selection"
            )
        
        # Size label
        width = x2 - x1
        height = y2 - y1
        label_text = f"{width} × {height}"
        
        # Position label above selection, or below if not enough space
        label_y = y1 - 25 if y1 > 40 else y2 + 25
        label_x = (x1 + x2) // 2
        
        # Label background
        self.canvas.create_rectangle(
            label_x - 50, label_y - 12,
            label_x + 50, label_y + 12,
            fill="#2e2e2e", outline="#4f4f4f", tags="size_label"
        )
        
        # Label text
        self.canvas.create_text(
            label_x, label_y,
            text=label_text, fill="white",
            font=("Arial", 11, "bold"), tags="size_label"
        )
    
    def _on_release(self, event):
        """Handle mouse button release - complete selection."""
        if not self.is_selecting:
            return
        
        self.is_selecting = False
        
        # Calculate final coordinates
        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)
        
        width = x2 - x1
        height = y2 - y1
        
        # Check minimum size
        if width < self.MIN_SELECTION_SIZE or height < self.MIN_SELECTION_SIZE:
            logging.debug(f"[ScreenSnip] Selection too small: {width}x{height}")
            self._close()
            self.on_cancel()
            return
        
        # Hide overlay before capturing
        self.root.withdraw()
        
        # Capture immediately from frozen background
        self._finish_capture(x1, y1, x2, y2)
    
    def _finish_capture(self, x1: int, y1: int, x2: int, y2: int):
        """Complete the capture using the frozen background."""
        result = self._capture_region(x1, y1, x2, y2)
        self._close()
        
        if result:
            logging.debug(f"[ScreenSnip] Capture successful: {result.width}x{result.height}")
            self.on_capture(result)
        else:
            logging.error("[ScreenSnip] Capture failed")
            self.on_cancel()
    
    def _capture_region(self, x1: int, y1: int, x2: int, y2: int) -> Optional[CaptureResult]:
        """
        Capture a screen region from the frozen background.
        
        Uses the background image captured when the overlay was created to ensure
        consistency with what the user saw during selection.
        """
        try:
            if not self.background_image:
                logging.error("[ScreenSnip] No background image available for capture")
                return None

            # Crop from frozen background
            img = self.background_image.crop((x1, y1, x2, y2))
            
            # Convert to PNG bytes
            buffer = io.BytesIO()
            img.save(buffer, format="PNG", optimize=True)
            buffer.seek(0)
            
            # Encode to base64
            image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
            
            return CaptureResult(
                image_base64=image_base64,
                mime_type="image/png",
                width=x2 - x1,
                height=y2 - y1,
                pil_image=img  # Keep reference for thumbnail
            )
            
        except Exception as e:
            logging.error(f"[ScreenSnip] Region capture error: {e}")
            return None
    
    def _on_escape(self, event):
        """Cancel capture on Escape key."""
        logging.debug("[ScreenSnip] Cancelled by user")
        self._close()
        self.on_cancel()
    
    def _on_enter(self, event):
        """Confirm current selection on Enter key."""
        if self.is_selecting:
            # Treat as mouse release at current position
            self._on_release(type('Event', (), {'x': self.current_x, 'y': self.current_y})())
    
    def _close(self):
        """Close and cleanup the overlay window."""
        try:
            if self.root:
                self.root.grab_release()
                self.root.destroy()
                self.root = None
        except tk.TclError:
            pass
        
        # Clear image references
        self.background_image = None
        self.tk_background = None
        self._selection_photo = None


# =============================================================================
# Convenience function for direct capture (non-GUI contexts)
# =============================================================================

def capture_screen_region(x1: int, y1: int, x2: int, y2: int) -> Optional[CaptureResult]:
    """
    Capture a screen region without showing overlay.
    
    Useful for programmatic capture when coordinates are already known
    (e.g., from external tools like ShareX).
    
    Args:
        x1, y1: Top-left corner
        x2, y2: Bottom-right corner
        
    Returns:
        CaptureResult or None if capture fails
    """
    try:
        img = ImageGrab.grab(
            bbox=(x1, y1, x2, y2),
            include_layered_windows=True
        )
        
        buffer = io.BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        buffer.seek(0)
        
        image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        
        return CaptureResult(
            image_base64=image_base64,
            mime_type="image/png",
            width=x2 - x1,
            height=y2 - y1,
            pil_image=img
        )
        
    except Exception as e:
        logging.error(f"[ScreenSnip] Direct capture error: {e}")
        return None


def capture_full_screen() -> Optional[CaptureResult]:
    """
    Capture the entire screen (all monitors on Windows).
    
    Returns:
        CaptureResult or None if capture fails
    """
    try:
        img = ImageGrab.grab(
            all_screens=True,
            include_layered_windows=True
        )
        
        buffer = io.BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        buffer.seek(0)
        
        image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        
        return CaptureResult(
            image_base64=image_base64,
            mime_type="image/png",
            width=img.width,
            height=img.height,
            pil_image=img
        )
        
    except Exception as e:
        logging.error(f"[ScreenSnip] Full screen capture error: {e}")
        return None