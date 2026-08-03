#!/usr/bin/env python3
"""
Custom widgets for AIPromptBridge GUI.
Includes ScrollableButtonList for replacing tk.Listbox with rich buttons.
Includes ScrollableComboBox for dropdowns with scrollbar support.
Includes TkScrollableFrame for a fallback scrollable frame for standard Tkinter.
"""

import sys
import tkinter as tk
from typing import Any, Callable, Dict, List, Optional, Union

from .platform import HAVE_CTK, ctk
from .themes import ThemeColors, get_ctk_button_colors, get_ctk_combobox_colors, get_ctk_font, get_tk_font

try:
    from .emoji_renderer import HAVE_PIL, get_emoji_renderer

    HAVE_EMOJI = HAVE_PIL and HAVE_CTK
except ImportError:
    HAVE_EMOJI = False
    get_emoji_renderer = None


class ScrollableButtonList(ctk.CTkScrollableFrame if HAVE_CTK else tk.Frame):
    """
    A scrollable list of buttons acting as a selector.
    Replaces tk.Listbox to allow images/emojis and modern styling.
    """

    def __init__(self, master, colors: ThemeColors, command: Callable[[str], None], **kwargs):
        super().__init__(master, **kwargs)
        self.colors = colors
        self.command = command

        self.buttons: Dict[str, Any] = {}  # id -> button
        self.selected_id: Optional[str] = None
        self.items: List[str] = []  # ordered list of IDs
        self.dimmed: Dict[str, bool] = {}

        # Determine strict inner frame for buttons
        if HAVE_CTK:
            self.inner_frame = self
            self.grid_columnconfigure(0, weight=1)
        else:
            # Setup scrolling for standard Tk
            self.canvas = tk.Canvas(self, bg=colors.bg, highlightthickness=0)
            self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
            self.inner_frame = tk.Frame(self.canvas, bg=colors.bg)

            self.inner_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

            self.canvas_window = self.canvas.create_window((0, 0), window=self.inner_frame, anchor="nw")

            # Allow inner frame to expand to canvas width
            self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))

            self.canvas.configure(yscrollcommand=self.scrollbar.set)

            self.scrollbar.pack(side="right", fill="y")
            self.canvas.pack(side="left", fill="both", expand=True)

            # Mousewheel scrolling
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
            self.inner_frame.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        """Handle mousewheel scrolling for standard Tk."""
        if not HAVE_CTK:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def add_item(
        self, item_id: str, text: str, icon: str | None = None, font_weight: str = "normal", dimmed: bool = False
    ):
        """Add an item to the list."""
        if item_id in self.buttons:
            return

        self.items.append(item_id)
        self.dimmed[item_id] = dimmed

        # Determine image
        img = None
        display_text = text

        if icon:
            # Try to render emoji image
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                img = renderer.get_ctk_image(icon, size=20)

            # If no image (or no renderer), prepend icon to text if not already there
            if not img and icon not in text:
                display_text = f"{icon} {text}"

        # Determine styling
        is_selected = item_id == self.selected_id
        variant = "primary" if is_selected else "secondary"
        color_kwargs = get_ctk_button_colors(self.colors, variant)
        if dimmed and not is_selected:
            color_kwargs["text_color"] = self.colors.blockquote

        if HAVE_CTK:
            btn_kwargs = {
                "text": display_text,
                "anchor": "w",
                "font": get_ctk_font(14, weight=font_weight),
                "height": 38,
                "command": lambda id=item_id: self.select(id),
                **color_kwargs,
            }
            if img:
                btn_kwargs["image"] = img
                btn_kwargs["compound"] = "left"

            btn = ctk.CTkButton(self.inner_frame, **btn_kwargs)
            btn.grid(row=len(self.items) - 1, column=0, sticky="ew", padx=2, pady=2)
            self.buttons[item_id] = btn
        else:
            # Fallback for standard tk
            btn = tk.Button(
                self.inner_frame,
                text=display_text,
                anchor="w",
                command=lambda id=item_id: self.select(id),
                bg=self.colors.accent if is_selected else self.colors.surface0,
                fg=self.colors.accent_fg if is_selected else (self.colors.blockquote if dimmed else self.colors.fg),
                relief="flat",
                padx=10,
                pady=5,
            )
            btn.pack(fill="x", padx=2, pady=1)
            self.buttons[item_id] = btn

    def select(self, item_id: str):
        """Select an item and trigger callback."""
        if item_id not in self.buttons:
            return

        old_id = self.selected_id
        if old_id == item_id:
            return  # Already selected

        self.selected_id = item_id

        # Update colors
        self._update_button_colors(old_id)
        self._update_button_colors(item_id)

        # Trigger callback
        if self.command:
            self.command(item_id)

    def _update_button_colors(self, item_id: Optional[str]):
        """Update styling for a single button."""
        if not item_id or item_id not in self.buttons:
            return

        btn = self.buttons[item_id]
        is_selected = item_id == self.selected_id
        variant = "primary" if is_selected else "secondary"
        dimmed = self.dimmed.get(item_id, False)

        if HAVE_CTK:
            # Configure colors - exclude border_width as it causes flicker sometimes
            colors = get_ctk_button_colors(self.colors, variant)
            text_color = colors["text_color"]
            if dimmed and not is_selected:
                text_color = self.colors.blockquote
            btn.configure(fg_color=colors["fg_color"], text_color=text_color, hover_color=colors["hover_color"])
        else:
            fg_color = self.colors.accent_fg if is_selected else (self.colors.blockquote if dimmed else self.colors.fg)
            btn.configure(
                bg=self.colors.accent if is_selected else self.colors.surface0,
                fg=fg_color,
            )

    def clear(self):
        """Remove all items."""
        for btn in self.buttons.values():
            btn.destroy()
        self.buttons.clear()
        self.items.clear()
        self.dimmed.clear()
        self.selected_id = None

    def get_selected(self) -> Optional[str]:
        """Get ID of currently selected item."""
        return self.selected_id

    def selection_clear(self):
        """Clear selection visuals."""
        old_id = self.selected_id
        self.selected_id = None
        self._update_button_colors(old_id)

    def delete(self, item_id: str):
        """Delete an item."""
        if item_id in self.buttons:
            self.buttons[item_id].destroy()
            del self.buttons[item_id]
            if item_id in self.items:
                self.items.remove(item_id)
            if self.selected_id == item_id:
                self.selected_id = None

    def size(self) -> int:
        return len(self.items)

    def update_item(self, item_id: str, text: str, icon: str | None = None):
        """Update an existing item's text and icon."""
        if item_id not in self.buttons:
            return

        btn = self.buttons[item_id]
        img = None
        display_text = text

        if icon:
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                img = renderer.get_ctk_image(icon, size=20)
            if not img and icon not in text:
                display_text = f"{icon} {text}"

        btn.configure(text=display_text, image=img)


def upgrade_tabview_with_icons(tabview, icon_size: int = 24, font_size: int = 14):
    """
    Upgrade CTkTabview tabs with larger font and emoji images.
    Uses internal hacks to access the segmented button.
    """
    if not HAVE_CTK or not isinstance(tabview, ctk.CTkTabview):
        return

    try:
        if hasattr(tabview, "_segmented_button"):
            # Enlarge font and height (public API)
            tabview._segmented_button.configure(font=get_ctk_font(font_size, "bold"), height=42)

            # Add images (hack via internal dict)
            if HAVE_EMOJI:
                renderer = get_emoji_renderer()
                for value in tabview._segmented_button._value_list:
                    # Split "⚡ Actions" -> "⚡", "Actions"
                    parts = value.split(" ", 1)
                    if len(parts) >= 2:
                        emoji = parts[0]
                        text = " ".join(parts[1:])
                        # Render emoji if valid first char (simple heuristic)
                        if any(ord(c) > 127 for c in emoji):
                            img = renderer.get_ctk_image(emoji, size=icon_size)
                            if img:
                                btn = tabview._segmented_button._buttons_dict.get(value)
                                if btn:
                                    btn.configure(image=img, compound="left", text=f" {text}")
    except Exception as e:
        print(f"Error upgrading tabs: {e}")


def create_section_header(parent, text: str, colors: ThemeColors, emoji: str | None = None, top_padding: int = 0):
    """
    Create a section header with optional emoji support.
    Handles both explicit emoji arg or parsing emoji from start of text.
    """
    if HAVE_CTK:
        # Check for emoji at start if not explicitly provided
        label_text = text
        emoji_char = emoji

        if not emoji_char and " " in text:
            potential_emoji, rest = text.split(" ", 1)
            if any(ord(c) > 127 for c in potential_emoji):
                emoji_char = potential_emoji
                label_text = rest

        kwargs = {
            "text": label_text if emoji_char else text,
            "font": get_ctk_font(15, "bold"),
            "text_color": colors.accent,
        }

        if emoji_char and HAVE_EMOJI:
            renderer = get_emoji_renderer()
            img = renderer.get_ctk_image(emoji_char, size=22)
            if img:
                kwargs["image"] = img
                kwargs["compound"] = "left"
                kwargs["text"] = " " + label_text

        # Use CTkLabel
        lbl = ctk.CTkLabel(parent, **kwargs)
        lbl.pack(anchor="w", pady=(top_padding, 12))
        return lbl
    else:
        # Fallback tk
        full_text = f"{emoji} {text}" if emoji else text
        lbl = tk.Label(parent, text=full_text, font=get_tk_font(11, "bold"), bg=colors.bg, fg=colors.accent)
        lbl.pack(anchor="w", pady=(top_padding, 10))
        return lbl


def create_emoji_button(
    parent,
    text: str,
    icon: str,
    colors: ThemeColors,
    variant: str = "primary",
    width: int = 140,
    height: int = 38,
    command: Callable | None = None,
    font_size: int = 13,
    **kwargs,
):
    """
    Create a styled button with optional emoji icon.
    Handles rendering emoji as image (CTk) or text fallback.
    """
    if HAVE_CTK:
        img = None
        display_text = text

        if icon and HAVE_EMOJI:
            renderer = get_emoji_renderer()
            img = renderer.get_ctk_image(icon, size=20)

        if not img and icon:
            display_text = f"{icon} {text}" if text else icon

        button_kwargs = {
            "text": display_text,
            "font": get_ctk_font(font_size),
            "width": width,
            "height": height,
            "command": command,
            **get_ctk_button_colors(colors, variant),
            **kwargs,
        }

        if img:
            button_kwargs["image"] = img
            button_kwargs["compound"] = "left"

        return ctk.CTkButton(parent, **button_kwargs)
    else:
        # Fallback for standard tk
        full_text = f"{icon} {text}" if (icon and text) else (text or icon)

        # Map variant to colors
        bg_color = colors.accent
        fg_color = colors.accent_fg

        if variant == "success":
            bg_color = colors.accent_green
        elif variant == "danger":
            bg_color = colors.accent_red
        elif variant == "secondary":
            bg_color = colors.surface1
            fg_color = colors.fg

        btn = tk.Button(
            parent, text=full_text, command=command, font=get_tk_font(9), bg=bg_color, fg=fg_color, padx=10, pady=5
        )
        return btn


class SplitButton:
    """
    A unified split button that displays as a single rounded capsule.
    Clicking the main text triggers the default command, while clicking the
    dropdown arrow (on the rightmost 30 pixels) opens the dropdown menu.

    Supports both CustomTkinter and standard Tkinter fallback.
    """

    def __init__(
        self,
        parent,
        text: str,
        colors: ThemeColors,
        command: Callable | None = None,
        menu_items: list[tuple[str, Callable]] | None = None,
        variant: str = "secondary",
        width: int = 85,
        height: int = 32,
        font_size: int = 12,
        corner_radius: int = 8,
        **kwargs,
    ):
        """
        Args:
            parent: Parent widget
            text: Main button text
            colors: ThemeColors instance
            command: Default action when main button is clicked
            menu_items: List of (label, callback) tuples for dropdown menu.
                        Use None as label for a separator: (None, None).
            variant: Button color variant ("primary", "secondary", "success", etc.)
            width: Width of the main button (default width, expanded for arrow and separator)
            height: Button height
            font_size: Font size
            corner_radius: Corner radius (CTk only)
        """
        self.colors = colors
        self.command = command
        self.menu_items = menu_items or []

        combined_width = width + 25

        if HAVE_CTK:
            btn_colors = get_ctk_button_colors(colors, variant)

            self.main_btn = ctk.CTkButton(
                parent,
                text=f"  {text}",
                font=get_ctk_font(size=font_size),
                width=combined_width,
                height=height,
                corner_radius=corner_radius,
                command=self._on_click_wrapper,
                anchor="w",
                **btn_colors,
                **kwargs,
            )

            # Override the _draw method of CTkButton to render our custom line and arrow on its canvas.
            self.original_draw = self.main_btn._draw
            self.main_btn._draw = self._custom_draw
            self.main_btn._draw()
        else:
            # Map variant to colors for Tk fallback
            bg_color = colors.surface0
            fg_color = colors.fg
            if variant == "primary":
                bg_color = colors.accent
                fg_color = colors.accent_fg
            elif variant == "success":
                bg_color = colors.accent_green
                fg_color = colors.accent_fg
            elif variant == "danger":
                bg_color = colors.accent_red
                fg_color = colors.accent_fg

            self.main_btn = tk.Button(
                parent,
                text=f"  {text}  │  ▼",
                font=get_tk_font(10),
                bg=bg_color,
                fg=fg_color,
                relief=tk.FLAT,
                padx=10,
                pady=6,
                command=self._on_click_wrapper,
                cursor="hand2",
            )

        # Build tk.Menu for dropdown
        self._menu = tk.Menu(
            self.main_btn,
            tearoff=0,
            bg=colors.surface0,
            fg=colors.fg,
            activebackground=colors.accent,
            activeforeground=colors.accent_fg,
            relief=tk.FLAT,
            borderwidth=1,
            font=get_tk_font(10),
        )
        for item in self.menu_items:
            label, callback = item
            if label is None:
                self._menu.add_separator()
            else:
                self._menu.add_command(label=label, command=callback)

    def _custom_draw(self, *args, **kwargs):
        """Draw the default CTkButton elements, then overlay the divider column and arrow."""
        if not hasattr(self, "main_btn") or not self.main_btn:
            return

        self.original_draw(*args, **kwargs)

        btn = self.main_btn
        try:
            btn._canvas.delete("custom_split")

            scale = btn._get_widget_scaling()
            w = btn._current_width
            h = btn._current_height
            scaled_w = w * scale
            scaled_h = h * scale

            sep_x = scaled_w - (30 * scale)
            text_color = btn._apply_appearance_mode(btn._text_color)

            # Draw vertical divider line
            btn._canvas.create_line(
                sep_x, 6 * scale, sep_x, (h - 6) * scale, fill=text_color, width=1, tags="custom_split"
            )

            # Draw prominent arrow ▼
            btn._canvas.create_text(
                sep_x + (15 * scale),
                scaled_h / 2,
                text="▼",
                font=get_tk_font(10, "bold"),
                fill=text_color,
                anchor="center",
                tags="custom_split",
            )
        except Exception:
            pass

    def _on_click_wrapper(self):
        """Determine whether click was on the right arrow or the main body."""
        btn = self.main_btn
        try:
            x = btn.winfo_pointerx() - btn.winfo_rootx()
            y = btn.winfo_pointery() - btn.winfo_rooty()
            w = btn.winfo_width()
            h = btn.winfo_height()

            # If click was in the rightmost 30 pixels, trigger dropdown
            # Check boundaries of the widget to ensure it wasn't a keyboard trigger (e.g. Enter/Space)
            if 0 <= x <= w and 0 <= y <= h and x > w - 30:
                self._show_menu()
            else:
                self._on_main_click()
        except Exception:
            # Fallback to main action in case of any issues with pointer querying
            self._on_main_click()

    def _on_main_click(self):
        """Execute the default command."""
        if self.command:
            self.command()

    def _show_menu(self):
        """Show the dropdown menu below the rightmost portion of the button."""
        try:
            # Post menu directly under the right-side arrow index
            x = self.main_btn.winfo_rootx() + self.main_btn.winfo_width() - 110
            y = self.main_btn.winfo_rooty() + self.main_btn.winfo_height()
            self._menu.post(x, y)
        except tk.TclError:
            pass

    # Layout proxy methods forwarding directly to the main button
    def pack(self, **kwargs):
        self.main_btn.pack(**kwargs)

    def grid(self, **kwargs):
        self.main_btn.grid(**kwargs)

    def place(self, **kwargs):
        self.main_btn.place(**kwargs)

    def pack_forget(self):
        self.main_btn.pack_forget()

    def configure(self, **kwargs):
        self.main_btn.configure(**kwargs)

    def destroy(self):
        self.main_btn.destroy()


class ScrollableComboBox:
    """
    A searchable combobox with scrollable dropdown for handling many items.
    Uses CTkEntry for typing and a Toplevel with tk.Text for high-performance dropdown.

    Features:
    - Click arrow or field to open dropdown
    - Type to search/filter OR enter custom value
    - Scrollable dropdown using tk.Text (very fast even with 1000+ items)
    - Press Enter to use typed text as custom value
    - Compatible interface with CTkComboBox
    - Closes when clicking outside or losing focus to other app

    Compatible interface with CTkComboBox:
    - get() / set() for value
    - configure(values=[...]) to update options
    - command callback on selection
    """

    MAX_VISIBLE_ITEMS = 15
    ITEM_HEIGHT = 22  # Line height in text widget
    DEBOUNCE_MS = 100  # Debounce delay for search filtering

    def __init__(
        self,
        master,
        colors: ThemeColors,
        values: List[str] | None = None,
        variable: tk.StringVar | None = None,
        command: Callable[[str], None] | None = None,
        width: int = 220,
        height: int = 32,
        font_size: int = 13,
        state: str = "normal",
        item_tooltip_callback: Callable[[str], str] | None = None,
        **kwargs,
    ):
        self.master = master
        self.colors = colors
        self.values = values or []
        self.variable = variable
        self.command = command
        self.width = width
        self.height = height
        self.font_size = font_size
        self.state = state
        self._item_tooltip_callback = item_tooltip_callback
        self._item_tooltip_window = None
        self._item_tooltip_after_id = None

        self._dropdown_open = False
        self._dropdown_window = None
        self._selected_value = ""
        self._filtered_values = list(self.values)
        self._text_widget = None  # Text widget for dropdown
        self._debounce_id = None  # For debounced search
        self._focus_check_id = None  # For periodic focus checking
        self._focus_out_id = None  # For delayed focus-out value application
        self._hover_line = -1  # Currently hovered line
        self._selection_gen = 0  # Generation counter to invalidate stale focus-out callbacks

        # Main frame to hold entry and arrow button
        if HAVE_CTK:
            self.frame = ctk.CTkFrame(master, fg_color="transparent")
        else:
            self.frame = tk.Frame(master, bg=colors.bg)

        # Create the input widgets
        self._create_widgets()

        # Initialize with variable value if set
        if variable and variable.get():
            self._selected_value = variable.get()
            self._update_entry_text()

        # Apply initial state
        if self.state != "normal":
            self.configure(state=self.state)

    def _create_widgets(self):
        """Create the entry field and arrow button."""
        if HAVE_CTK:
            combo_colors = get_ctk_combobox_colors(self.colors)

            # Container frame with border
            self._container = ctk.CTkFrame(
                self.frame,
                fg_color=combo_colors.get("fg_color", self.colors.input_bg),
                border_width=1,
                border_color=combo_colors.get("border_color", self.colors.border),
                corner_radius=6,
                height=self.height,
                width=self.width,
            )
            self._container.pack(side="left")
            self._container.pack_propagate(False)

            # Entry for typing - allows custom input
            self.entry = ctk.CTkEntry(
                self._container,
                font=get_ctk_font(self.font_size),
                width=self.width - 32,
                height=self.height - 4,
                fg_color="transparent",
                text_color=combo_colors.get("text_color", self.colors.fg),
                border_width=0,
                corner_radius=0,
            )
            self.entry.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=2)

            # Arrow button
            self._arrow_btn = ctk.CTkButton(
                self._container,
                text="▼",
                font=get_ctk_font(11),
                width=28,
                height=self.height - 6,
                fg_color=self.colors.surface1,
                text_color=self.colors.fg,
                hover_color=self.colors.surface2,
                corner_radius=4,
                command=self._on_arrow_click,
            )
            self._arrow_btn.pack(side="right", padx=2, pady=2)

            # Bind events
            self.entry.bind("<KeyRelease>", self._on_key_release)
            self.entry.bind("<Return>", self._on_enter)
            self.entry.bind("<Down>", self._on_arrow_down)
            self.entry.bind("<Escape>", lambda e: self._close_dropdown())
            self.entry.bind("<Button-1>", self._on_entry_click)
            self.entry.bind("<FocusOut>", self._on_focus_out)

        else:
            # Tk fallback
            self._container = tk.Frame(
                self.frame, bg=self.colors.input_bg, highlightbackground=self.colors.border, highlightthickness=1
            )
            self._container.pack(side="left")

            self.entry = tk.Entry(
                self._container,
                font=get_tk_font(10),
                bg=self.colors.input_bg,
                fg=self.colors.fg,
                readonlybackground=self.colors.input_bg,
                disabledbackground=self.colors.input_bg,
                relief="flat",
                highlightthickness=0,
                width=max(1, (self.width - 32) // 8),
            )
            self.entry.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=4)

            self._arrow_btn = tk.Button(
                self._container,
                text="▼",
                font=get_tk_font(9),
                bg=self.colors.surface1,
                fg=self.colors.fg,
                relief="flat",
                width=3,
                command=self._on_arrow_click,
            )
            self._arrow_btn.pack(side="right", padx=2, pady=2)

            # Bind events
            self.entry.bind("<KeyRelease>", self._on_key_release)
            self.entry.bind("<Return>", self._on_enter)
            self.entry.bind("<Down>", self._on_arrow_down)
            self.entry.bind("<Escape>", lambda e: self._close_dropdown())
            self.entry.bind("<Button-1>", self._on_entry_click)
            self.entry.bind("<FocusOut>", self._on_focus_out)

    def _compute_filtered_values(self):
        """Recompute _filtered_values from current entry text.

        Ensures the filter is applied immediately when values are refreshed
        or the dropdown is opened while the entry already contains text.
        """
        try:
            if not hasattr(self, "entry") or not self.entry or not self.entry.winfo_exists():
                self._filtered_values = list(self.values)
                return
            search_text = self.entry.get().strip().lower()
            if search_text and search_text != self._selected_value.lower():
                self._filtered_values = [v for v in self.values if search_text in v.lower()]
            else:
                self._filtered_values = list(self.values)
        except (tk.TclError, AttributeError):
            self._filtered_values = list(self.values)

    def _on_entry_click(self, event):
        """Handle click on entry - open dropdown."""
        if not self._dropdown_open and self.state != "disabled":
            self._compute_filtered_values()
            self._open_dropdown()

    def _on_arrow_click(self):
        """Handle click on arrow button - toggle dropdown."""
        if self.state == "disabled":
            return

        if self._dropdown_open:
            self._close_dropdown()
        else:
            self._compute_filtered_values()
            self._open_dropdown()
            self.entry.focus_set()

    def _on_focus_out(self, event):
        """Handle focus leaving entry - update value from typed text."""
        # Cancel any previous pending focus-out callback
        if self._focus_out_id:
            try:
                self.frame.after_cancel(self._focus_out_id)
            except Exception:
                pass
            self._focus_out_id = None

        # When focus leaves, use the typed text as the value if it's different
        typed_text = self.entry.get().strip()
        if typed_text and typed_text != self._selected_value:
            # Capture the current generation so stale callbacks are ignored
            gen = self._selection_gen
            # Delay slightly to allow dropdown click to register first
            self._focus_out_id = self.frame.after(200, lambda: self._check_and_update_value(typed_text, gen))

    def _cancel_focus_out(self):
        """Cancel any pending focus-out value application."""
        if self._focus_out_id:
            try:
                self.frame.after_cancel(self._focus_out_id)
            except Exception:
                pass
            self._focus_out_id = None

    def _check_and_update_value(self, typed_text: str, gen: int):
        """Check if we should update value from typed text."""
        self._focus_out_id = None
        # Bail if a selection happened after this callback was scheduled
        if gen != self._selection_gen:
            return
        # Only update if dropdown is closed (meaning user didn't click an item)
        if not self._dropdown_open and typed_text:
            self._selected_value = typed_text
            if self.variable:
                self.variable.set(typed_text)
            if self.command:
                self.command(typed_text)

    def _on_key_release(self, event):
        """Handle key release - filter the dropdown with debounce."""
        # Ignore navigation keys
        if event.keysym in (
            "Up",
            "Down",
            "Left",
            "Right",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
            "Alt_L",
            "Alt_R",
            "Escape",
            "Return",
            "Tab",
            "Caps_Lock",
        ):
            return

        # Cancel previous debounce
        if self._debounce_id:
            try:
                self.frame.after_cancel(self._debounce_id)
            except Exception:
                pass

        # Schedule new filter with debounce
        self._debounce_id = self.frame.after(self.DEBOUNCE_MS, self._apply_filter)

    def _apply_filter(self):
        """Apply the search filter (called after debounce)."""
        self._debounce_id = None

        search_text = self.entry.get().strip().lower()

        # Filter values efficiently
        if search_text:
            self._filtered_values = [v for v in self.values if search_text in v.lower()]
        else:
            self._filtered_values = list(self.values)

        # Update dropdown if open
        if self._dropdown_open:
            self._refresh_dropdown_items()

    def _on_enter(self, event):
        """Handle Enter key - use typed text as value (custom model support)."""
        typed_text = self.entry.get().strip()
        if typed_text:
            self._select_value(typed_text)
        elif self._filtered_values:
            self._select_value(self._filtered_values[0])
        return "break"

    def _on_arrow_down(self, event):
        """Handle Down arrow - open dropdown."""
        if not self._dropdown_open:
            self._compute_filtered_values()
            self._open_dropdown()
        return "break"

    def _open_dropdown(self):
        """Open the dropdown list using tk.Text for performance."""
        if self._dropdown_open:
            return

        if not self.values:
            return

        self._dropdown_open = True

        # Calculate position
        try:
            self._container.update_idletasks()
            x = self._container.winfo_rootx()
            y = self._container.winfo_rooty() + self._container.winfo_height()
        except tk.TclError:
            self._dropdown_open = False
            return

        # Calculate dropdown dimensions
        num_items = len(self._filtered_values) if self._filtered_values else 1
        visible_items = min(num_items, self.MAX_VISIBLE_ITEMS)
        dropdown_height = max(visible_items * self.ITEM_HEIGHT + 8, 30)

        # Create toplevel
        self._dropdown_window = tk.Toplevel(self.master)
        self._dropdown_window.overrideredirect(True)
        self._dropdown_window.configure(bg=self.colors.border)
        self._dropdown_window.attributes("-topmost", True)

        # Inner frame for border effect
        inner = tk.Frame(self._dropdown_window, bg=self.colors.surface0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # Use tk.Text for high performance (handles 1000+ items smoothly)
        self._text_widget = tk.Text(
            inner,
            font=get_tk_font(10),
            bg=self.colors.surface0,
            fg=self.colors.fg,
            cursor="hand2",
            wrap="none",
            highlightthickness=0,
            relief="flat",
            selectbackground=self.colors.accent,
            selectforeground=self.colors.accent_fg,
            padx=8,
            pady=4,
        )

        # Add scrollbar if needed
        if num_items > self.MAX_VISIBLE_ITEMS:
            scrollbar = tk.Scrollbar(inner, orient="vertical", command=self._text_widget.yview)
            scrollbar.pack(side="right", fill="y")
            self._text_widget.configure(yscrollcommand=scrollbar.set)

        self._text_widget.pack(fill="both", expand=True)

        # Configure tags for styling
        self._text_widget.tag_configure("item", spacing1=2, spacing3=2)
        self._text_widget.tag_configure("hover", background=self.colors.surface1)
        self._text_widget.tag_configure("selected", background=self.colors.accent, foreground=self.colors.accent_fg)

        # Populate items
        self._populate_dropdown_items()

        # Make text widget read-only
        self._text_widget.configure(state="disabled")

        # Bind events
        self._text_widget.bind("<Button-1>", self._on_text_click)
        self._text_widget.bind("<Motion>", self._on_text_motion)
        self._text_widget.bind("<Leave>", self._on_text_leave)
        # Stop scroll propagation
        self._text_widget.bind("<MouseWheel>", self._on_mousewheel)
        self._dropdown_window.bind("<Escape>", lambda e: self._close_dropdown())

        # Position and show
        self._dropdown_window.geometry(f"{self.width}x{dropdown_height}+{x}+{y}")
        self._dropdown_window.lift()

        # Start focus checking
        self._start_focus_check()

    def _populate_dropdown_items(self):
        """Populate the text widget with items."""
        if not self._text_widget:
            return

        self._text_widget.configure(state="normal")
        self._text_widget.delete("1.0", "end")

        if not self._filtered_values:
            self._text_widget.insert("end", "  (no matches)")
            self._text_widget.configure(state="disabled")
            return

        for i, value in enumerate(self._filtered_values):
            if i > 0:
                self._text_widget.insert("end", "\n")

            tags = ["item"]
            if value == self._selected_value:
                tags.append("selected")

            self._text_widget.insert("end", value, tuple(tags))

        self._text_widget.configure(state="disabled")

    def _refresh_dropdown_items(self):
        """Refresh dropdown items after filter change."""
        if not self._dropdown_window or not self._text_widget:
            return

        # Update dropdown height
        num_items = len(self._filtered_values) if self._filtered_values else 1
        visible_items = min(num_items, self.MAX_VISIBLE_ITEMS)
        dropdown_height = max(visible_items * self.ITEM_HEIGHT + 8, 30)

        try:
            x = self._container.winfo_rootx()
            y = self._container.winfo_rooty() + self._container.winfo_height()
            self._dropdown_window.geometry(f"{self.width}x{dropdown_height}+{x}+{y}")
        except tk.TclError:
            pass

        # Re-populate text widget
        self._populate_dropdown_items()

    def _on_mousewheel(self, event):
        """Handle mousewheel scrolling - stop propagation and boost speed."""
        if self._text_widget:
            # Scroll the text widget (3x faster speed)
            units = int(-1 * (event.delta / 120) * 3)
            self._text_widget.yview_scroll(units, "units")
        return "break"

    def _on_text_click(self, event):
        """Handle click on text widget - select item."""
        if not self._text_widget:
            return

        # Get clicked line
        index = self._text_widget.index(f"@{event.x},{event.y}")
        line = int(index.split(".")[0]) - 1

        if 0 <= line < len(self._filtered_values):
            self._select_value(self._filtered_values[line])

    def _on_text_motion(self, event):
        """Handle mouse motion - highlight hovered item."""
        if not self._text_widget:
            return

        # Get hovered line
        index = self._text_widget.index(f"@{event.x},{event.y}")
        line = int(index.split(".")[0]) - 1

        if line != self._hover_line:
            self._hover_line = line

            # Clear previous hover
            self._text_widget.tag_remove("hover", "1.0", "end")

            # Add hover to current line
            if 0 <= line < len(self._filtered_values):
                line_start = f"{line + 1}.0"
                line_end = f"{line + 1}.end"

                # Don't hover if already selected
                if self._filtered_values[line] != self._selected_value:
                    self._text_widget.tag_add("hover", line_start, line_end)

                # Schedule tooltip for this item
                if self._item_tooltip_callback:
                    self._schedule_item_tooltip(
                        self._filtered_values[line],
                        event.x_root,
                        event.y_root,
                    )
            else:
                # Mouse moved off items — hide tooltip
                self._hide_item_tooltip()

    def _on_text_leave(self, event):
        """Handle mouse leaving text widget."""
        if self._text_widget:
            self._text_widget.tag_remove("hover", "1.0", "end")
            self._hover_line = -1
        self._hide_item_tooltip()

    _ITEM_TOOLTIP_DELAY_MS = 350  # Slightly faster than Tooltip's 500ms for dropdown items

    def _show_item_tooltip(self, text: str, x: int, y: int):
        """Show a tooltip near the hovered dropdown item."""
        self._hide_item_tooltip()

        if not text or not self._dropdown_window:
            return

        try:
            from .popups import TRANSPARENCY_COLOR, Tooltip  # Only for accessing tooltip styling pattern
        except ImportError:
            TRANSPARENCY_COLOR = "#010101"

        tw = tk.Toplevel(self._dropdown_window)
        tw.wm_overrideredirect(True)
        tw.wm_attributes("-topmost", True)

        # Apply transparency for rounded corners on Windows to avoid white corners
        if sys.platform == "win32":
            try:
                tw.attributes("-transparentcolor", TRANSPARENCY_COLOR)
                tw.configure(bg=TRANSPARENCY_COLOR)
            except tk.TclError:
                pass

        if HAVE_CTK:
            from .themes import get_ctk_font

            frame = ctk.CTkFrame(
                tw,
                fg_color=self.colors.surface0,
                border_color=self.colors.surface2,
                border_width=1,
                corner_radius=6,
            )
            frame.pack()

            label = ctk.CTkLabel(
                frame,
                text=text,
                font=get_ctk_font(size=11),
                text_color=self.colors.text,
                wraplength=300,
                justify="left",
            )
            label.pack(padx=10, pady=6)
        else:
            frame = tk.Frame(
                tw,
                bg=self.colors.surface0,
                highlightbackground=self.colors.surface2,
                highlightthickness=1,
            )
            frame.pack()

            label = tk.Label(
                frame,
                text=text,
                font=get_tk_font(10),
                bg=self.colors.surface0,
                fg=self.colors.text,
                padx=8,
                pady=4,
                wraplength=300,
                justify=tk.LEFT,
            )
            label.pack()

        # Position next to the mouse cursor instead of beside the dropdown
        try:
            tooltip_x = x + 15
            tooltip_y = y - 10  # Slightly above mouse for readability
            tw.wm_geometry(f"+{tooltip_x}+{tooltip_y}")
        except tk.TclError:
            tw.destroy()
            return

        self._item_tooltip_window = tw

    def _hide_item_tooltip(self):
        """Hide the item tooltip if visible."""
        if self._item_tooltip_after_id:
            try:
                self.frame.after_cancel(self._item_tooltip_after_id)
            except Exception:
                pass
            self._item_tooltip_after_id = None

        if self._item_tooltip_window:
            try:
                self._item_tooltip_window.destroy()
            except tk.TclError:
                pass
            self._item_tooltip_window = None

    def _schedule_item_tooltip(self, value: str, x_root: int, y_root: int):
        """Schedule showing a tooltip for a dropdown item after a delay."""
        self._hide_item_tooltip()

        if not self._item_tooltip_callback:
            return

        text = self._item_tooltip_callback(value)
        if not text:
            return

        self._item_tooltip_after_id = self.frame.after(
            self._ITEM_TOOLTIP_DELAY_MS,
            lambda: self._show_item_tooltip(text, x_root, y_root),
        )

    def _start_focus_check(self):
        """Start periodic check for window focus."""

        def check_focus():
            if not self._dropdown_open or not self._dropdown_window:
                return

            try:
                # Check if our app still has focus
                focus_widget = self.master.winfo_toplevel().focus_get()
                if focus_widget is None:
                    self._close_dropdown()
                    return

                # Schedule next check
                self._focus_check_id = self.frame.after(150, check_focus)

            except tk.TclError:
                self._close_dropdown()

        # Bind click handler on root
        try:
            root = self.master.winfo_toplevel()
            root.bind("<Button-1>", self._on_click_outside, add="+")
        except Exception:
            pass

        # Start periodic focus check
        self._focus_check_id = self.frame.after(150, check_focus)

    def _on_click_outside(self, event):
        """Handle clicks outside the dropdown."""
        if not self._dropdown_window or not self._dropdown_open:
            return

        try:
            x, y = event.x_root, event.y_root

            # Check if click is in dropdown
            dx = self._dropdown_window.winfo_rootx()
            dy = self._dropdown_window.winfo_rooty()
            dw = self._dropdown_window.winfo_width()
            dh = self._dropdown_window.winfo_height()

            if dx <= x <= dx + dw and dy <= y <= dy + dh:
                return

            # Check if click is on the container
            cx = self._container.winfo_rootx()
            cy = self._container.winfo_rooty()
            cw = self._container.winfo_width()
            ch = self._container.winfo_height()

            if cx <= x <= cx + cw and cy <= y <= cy + ch:
                return

            self._close_dropdown()

        except tk.TclError:
            self._close_dropdown()

    def _close_dropdown(self, _value_already_set: bool = False):
        """Close the dropdown.

        Args:
            _value_already_set: Internal flag - True when called from _select_value
                               to skip redundant value application.
        """
        # Cancel all pending timers
        if self._focus_check_id:
            try:
                self.frame.after_cancel(self._focus_check_id)
            except Exception:
                pass
            self._focus_check_id = None

        if self._debounce_id:
            try:
                self.frame.after_cancel(self._debounce_id)
            except Exception:
                pass
            self._debounce_id = None

        # Cancel pending focus-out callback to prevent it from overwriting
        # a valid selection after the dropdown closes
        if _value_already_set:
            self._cancel_focus_out()

        self._hide_item_tooltip()

        if self._dropdown_window:
            try:
                self._dropdown_window.destroy()
            except tk.TclError:
                pass
            self._dropdown_window = None

        self._dropdown_open = False
        self._text_widget = None
        self._hover_line = -1

        # Unbind click handler
        try:
            root = self.master.winfo_toplevel()
            root.unbind("<Button-1>")
        except tk.TclError:
            pass

        # Apply typed value on close (handles click-away without pressing Enter)
        if not _value_already_set:
            try:
                typed_text = self.entry.get().strip()
                if typed_text and typed_text != self._selected_value:
                    self._selected_value = typed_text
                    if self.variable:
                        self.variable.set(typed_text)
                    if self.command:
                        self.command(typed_text)
            except tk.TclError:
                pass

    def _select_value(self, value: str):
        """Select a value."""
        # Bump generation counter so any pending focus-out callback becomes a no-op
        self._selection_gen += 1
        self._cancel_focus_out()

        self._selected_value = value
        self._update_entry_text()
        self._close_dropdown(_value_already_set=True)

        if self.variable:
            self.variable.set(value)

        if self.command:
            self.command(value)

    def _update_entry_text(self):
        """Update the entry text."""
        try:
            # Temporarily enable entry to allow programmatic updates if in readonly/disabled state
            old_state = self.entry.cget("state")
            if old_state in ("readonly", "disabled"):
                self.entry.configure(state="normal") if HAVE_CTK else self.entry.config(state="normal")

            self.entry.delete(0, tk.END)
            self.entry.insert(0, self._selected_value or "")

            if old_state in ("readonly", "disabled"):
                self.entry.configure(state=old_state) if HAVE_CTK else self.entry.config(state=old_state)
        except tk.TclError:
            pass

    # Public API (compatible with CTkComboBox)

    def get(self) -> str:
        """Get current value (returns typed text if different from selection)."""
        try:
            if not hasattr(self, "entry") or not self.entry or not self.entry.winfo_exists():
                return self._selected_value
            typed = self.entry.get().strip()
            return typed if typed else self._selected_value
        except Exception:
            return self._selected_value

    def set(self, value: str):
        """Set current value."""
        self._selected_value = value
        self._update_entry_text()
        if self.variable:
            self.variable.set(value)

    def configure(self, **kwargs):
        """Configure widget options."""
        try:
            if "values" in kwargs:
                self.values = kwargs["values"]
                self._compute_filtered_values()
                # Refresh dropdown if it's currently open
                if self._dropdown_open:
                    self._refresh_dropdown_items()
            if "state" in kwargs:
                self.state = kwargs["state"]
                if HAVE_CTK:
                    if self.state == "disabled":
                        self.entry.configure(state="disabled")
                        self._arrow_btn.configure(state="disabled")
                    elif self.state == "readonly":
                        self.entry.configure(state="readonly")
                        self._arrow_btn.configure(state="normal")
                    else:
                        self.entry.configure(state="normal")
                        self._arrow_btn.configure(state="normal")
                else:
                    if self.state == "disabled":
                        self.entry.config(state="disabled")
                        self._arrow_btn.config(state="disabled")
                    elif self.state == "readonly":
                        self.entry.config(state="readonly")
                        self._arrow_btn.config(state="normal")
                    else:
                        self.entry.config(state="normal")
                        self._arrow_btn.config(state="normal")
        except Exception:
            pass

    def cget(self, key: str):
        """Get configuration value."""
        if key == "values":
            return self.values
        return None

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    def grid(self, **kwargs):
        self.frame.grid(**kwargs)

    def place(self, **kwargs):
        self.frame.place(**kwargs)

    def pack_forget(self):
        self.frame.pack_forget()

    def grid_forget(self):
        self.frame.grid_forget()

    def destroy(self):
        self._close_dropdown()
        self.frame.destroy()


# =============================================================================
# Tkinter Scrollable Frame (Fallback)
# =============================================================================


class TkScrollableFrame(tk.Frame):
    """
    A scrollable frame for standard Tkinter (fallback mode).
    Mimics ctk.CTkScrollableFrame interface partially.
    """

    def __init__(self, container, bg_color=None, *args, **kwargs):
        super().__init__(container, *args, **kwargs)

        # Create a canvas
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        if bg_color:
            self.canvas.configure(bg=bg_color)

        # Create a scrollbar
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)

        # Create the scrollable frame
        self.scrollable_frame = tk.Frame(self.canvas)
        if bg_color:
            self.scrollable_frame.configure(bg=bg_color)

        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        self.window_id = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        # Bind resize to adjust window width
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Bind mousewheel
        self.bind_mousewheel(self.canvas)
        self.bind_mousewheel(self.scrollable_frame)

    def _on_canvas_configure(self, event):
        # Adjust the width of the inner frame to match the canvas
        self.canvas.itemconfig(self.window_id, width=event.width)

    def bind_mousewheel(self, widget):
        # Bind mousewheel to scroll
        # Note: This might need more robust handling for nested widgets
        widget.bind("<MouseWheel>", self._on_mousewheel)
        # For Linux
        widget.bind("<Button-4>", self._on_mousewheel)
        widget.bind("<Button-5>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        if self.canvas.winfo_exists():
            # Windows/MacOS
            if event.delta:
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            # Linux (Button-4/5)
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")
            elif event.num == 4:
                self.canvas.yview_scroll(-1, "units")


# =============================================================================
# Themed Input Dialog (CTk version)
# =============================================================================


class ThemedInputDialog(ctk.CTkToplevel if HAVE_CTK else tk.Toplevel):
    """Themed dialog for getting text input from user."""

    def __init__(self, parent, title: str, prompt: str, colors: ThemeColors):
        super().__init__(parent)
        self.colors = colors
        self.result = None
        self.use_ctk = HAVE_CTK

        self.title(title)
        self.geometry("400x180")
        self.transient(parent)
        self.grab_set()

        if self.use_ctk:
            self.configure(fg_color=colors.bg)
        else:
            self.configure(bg=colors.bg)

        self.withdraw()
        try:
            from .windows.utils import set_dark_titlebar, set_window_icon

            set_dark_titlebar(self)
            set_window_icon(self)
        except ImportError:
            pass

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 200
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 90
        self.geometry(f"+{x}+{y}")

        # Main frame
        main_frame = ctk.CTkFrame(self, fg_color=colors.bg) if self.use_ctk else tk.Frame(self, bg=colors.bg)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Prompt label
        if self.use_ctk:
            from .themes import get_ctk_entry_colors, get_ctk_label_colors

            ctk.CTkLabel(main_frame, text=prompt, font=get_ctk_font(12), **get_ctk_label_colors(colors)).pack(
                anchor="w", pady=(0, 10)
            )

            self.entry = ctk.CTkEntry(
                main_frame, width=360, height=36, font=get_ctk_font(12), **get_ctk_entry_colors(colors)
            )
            self.entry.pack(fill="x", pady=(0, 15))
        else:
            tk.Label(main_frame, text=prompt, font=get_tk_font(11), bg=colors.bg, fg=colors.fg).pack(
                anchor="w", pady=(0, 10)
            )
            self.entry = tk.Entry(main_frame, font=get_tk_font(11), bg=colors.input_bg, fg=colors.fg, width=40)
            self.entry.pack(fill="x", pady=(0, 15), ipady=6)

        self.entry.focus_set()

        # Buttons
        btn_frame = (
            ctk.CTkFrame(main_frame, fg_color="transparent") if self.use_ctk else tk.Frame(main_frame, bg=colors.bg)
        )
        btn_frame.pack()

        if self.use_ctk:
            ctk.CTkButton(
                btn_frame,
                text="OK",
                font=get_ctk_font(11),
                width=80,
                **get_ctk_button_colors(colors, "primary"),
                command=self._ok,
            ).pack(side="left", padx=5)

            ctk.CTkButton(
                btn_frame,
                text="Cancel",
                font=get_ctk_font(11),
                width=80,
                **get_ctk_button_colors(colors, "secondary"),
                command=self._cancel,
            ).pack(side="left", padx=5)
        else:
            tk.Button(btn_frame, text="OK", command=self._ok, bg=colors.accent, fg=colors.accent_fg).pack(
                side="left", padx=5
            )
            tk.Button(btn_frame, text="Cancel", command=self._cancel, bg=colors.surface1, fg=colors.fg).pack(
                side="left", padx=5
            )

        # Bindings
        self.entry.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.deiconify()

    def _ok(self):
        """Accept the input."""
        self.result = self.entry.get().strip()
        self.destroy()

    def _cancel(self):
        """Cancel the dialog."""
        self.result = None
        self.destroy()


def ask_themed_string(parent, title: str, prompt: str, colors: ThemeColors) -> Optional[str]:
    """Show a themed input dialog and return the result."""
    dialog = ThemedInputDialog(parent, title, prompt, colors)
    parent.wait_window(dialog)
    return dialog.result
