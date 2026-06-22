#!/usr/bin/env python3
"""
Base classes for chat windows.

Provides:
- ChatWindowBase: Unified base class for StandaloneChatWindow and AttachedChatWindow

This base class eliminates code duplication by providing shared UI creation,
message handling, and event processing methods.
"""

import threading
import tkinter as tk
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from ...model_defaults import get_fallback_models
from ...session_manager import add_session
from ..core import get_next_window_id, register_window, unregister_window
from ..custom_widgets import ScrollableComboBox
from ..emoji_renderer import prepare_emoji_content
from ..platform import HAVE_CTK, ctk
from ..themes import (
    ThemeColors,
    get_colors,
    get_ctk_button_colors,
    get_ctk_combobox_colors,
    get_ctk_entry_colors,
    get_ctk_font,
    get_ctk_frame_colors,
    get_ctk_scrollbar_colors,
    get_ctk_textbox_colors,
    get_tk_font,
    scaled_tk_size,
    sync_ctk_appearance,
)
from ..utils import copy_to_clipboard, get_color_scheme, render_markdown, setup_text_tags
from .utils import set_dark_titlebar, set_window_icon


class ChatWindowBase(ABC):
    """
    Base class for chat windows with unified UI creation and message handling.

    Subclasses must implement:
    - _create_root() -> creates the root window (CTk/Tk vs CTkToplevel/Toplevel)
    - _get_window_tag() -> return unique window tag for registration
    - _run_on_gui_thread(func) -> thread-safe callback execution (optional)
    """

    def __init__(self, session, initial_response: Optional[str] = None):
        self.session = session
        self.initial_response = initial_response

        # Window identity
        self.window_id = get_next_window_id()

        # Display state
        self.wrapped = True
        self.markdown = True
        self.auto_scroll = True
        self.last_response = initial_response or self._get_last_assistant_response() or ""
        self.is_loading = False
        self._destroyed = False

        # Streaming state
        self.streaming_text = ""
        self.streaming_thinking = ""
        self.is_streaming = False
        self.thinking_collapsed_states: Dict[int, bool] = {}
        self.last_usage = None

        # Model selection — per-session override takes priority over global
        self.available_models: List[Dict] = []
        from ... import web_server

        # Use session's model_override if set, otherwise None (will show global sentinel)
        self.selected_model = self.session.model_override  # None = use global
        self._last_global_model = web_server.get_active_setting("model", "")

        # Profile selector mode: show profiles instead of model list
        self._use_profile_mode = self._compute_profile_mode()

        # Manual mode: per-session toggle
        self._manual_mode = self.session.manual_mode

        # Theme
        self.theme = get_colors()
        self.colors = get_color_scheme()

        # UI element references (initialized in _build_ui)
        self._init_ui_refs()

    def _init_ui_refs(self):
        """Initialize UI element references to None."""
        self.root = None
        self.status_label = None
        self.wrap_btn = None
        self.md_btn = None
        self.scroll_btn = None
        self.send_btn = None
        self.regen_btn = None
        self.rename_btn = None
        self.delete_btn = None
        self.input_text = None
        self.chat_text = None
        self.model_dropdown = None
        self.model_label_widget = None  # Label widget ("Model:" or "Profile:")

        # Info label (row 0) — stored for dynamic updates
        self.info_label = None

        # Manual mode toggle
        self.manual_toggle_btn = None

        # Right-side container frames for toolbar
        self._profile_widgets_frame = None  # Contains profile label + dropdown
        self._manual_widgets_frame = None  # Contains provider label + dropdown + model label + dropdown

        # Manual mode widgets
        self.provider_dropdown = None
        self.provider_label_widget = None
        self.manual_model_dropdown = None
        self.manual_model_label_widget = None
        self.h_scrollbar = None
        self.v_scrollbar = None
        # Placeholder state
        self._placeholder = "Type your follow-up message here... (Enter to send, Shift+Enter for newline)"
        self._has_placeholder = True
        # Attachment state
        self.attach_btn = None
        self.attachments_frame = None
        self.pending_attachments = []  # List of {"path": str, "thumbnail": PhotoImage, "mime_type": str}
        self._attachment_thumbnails = []  # Keep references to prevent garbage collection
        self._clipboard_temp_files = []  # Temp files from clipboard paste (cleaned up after send/close)
        # Audio playback state
        self._audio_playing_path = None  # Currently playing audio file path
        self._audio_play_buttons = {}  # Map file_path -> play button widget

    @abstractmethod
    def _get_window_tag(self) -> str:
        """Return unique window tag for registration."""
        pass

    def _get_last_assistant_response(self) -> str:
        """Get the last assistant response from session history.

        Used to initialize last_response when reopening an existing session,
        so that Copy Last works immediately without requiring a new API call.
        """
        if self.session and self.session.messages:
            for msg in reversed(self.session.messages):
                if msg.get("role") == "assistant" and msg.get("content"):
                    return msg["content"]
        return ""

    def _compute_profile_mode(self) -> bool:
        """Check if profile selector mode should be active.

        Returns True when profile_selector_enabled=True.
        (A built-in Default profile always exists, so no need to check ProfileStore.)
        """
        from ... import web_server

        return web_server.CONFIG.get("profile_selector_enabled", True)

    def _get_profile_names(self) -> list:
        """Get sorted profile names from ProfileStore."""
        try:
            from ...connection_profiles import ProfileStore

            return ProfileStore.get_instance().get_profile_names()
        except Exception:
            return []

    def _get_profile_tooltip(self, profile_name: str) -> str:
        """Build tooltip text for a profile dropdown item."""
        from .utils import get_profile_tooltip_text

        return get_profile_tooltip_text(profile_name)

    def _safe_after(self, delay: int, func):
        """Schedule callback safely. Override for attached windows."""
        if self._destroyed:
            return
        try:
            if self.root and self.root.winfo_exists():
                self.root.after(delay, func)
        except Exception:
            pass

    # =========================================================================
    # UI Building
    # =========================================================================

    def _configure_window(self):
        """Configure window properties (title, size, position)."""
        self.root.title(f"Chat - {self.session.title or self.session.session_id}")
        self.root.geometry("750x620")
        self.root.minsize(500, 400)

        # Offset windows so they don't stack exactly
        offset = (self.window_id % 5) * 30
        self.root.geometry(f"+{80 + offset}+{80 + offset}")

    def _build_ui(self):
        """Build complete window UI."""
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        self._create_info_label()
        self._create_toolbar()
        self._create_chat_area()
        self._create_input_area()
        self._create_action_buttons()
        # Ensure row resizing behavior
        self.root.rowconfigure(2, weight=1)  # Chat area expands
        self.root.rowconfigure(3, weight=0)  # Input area fixed
        self.root.rowconfigure(4, weight=0)  # Attachments fixed

        register_window(self._get_window_tag())
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        # Subscribe to config changes for global sentinel updates
        from ...config import subscribe_config_change

        subscribe_config_change(self._on_config_changed)

    def _create_info_label(self):
        """Create session info label with dynamic profile/provider info."""
        info_text = self._build_info_text()

        if HAVE_CTK:
            self.info_label = ctk.CTkLabel(
                self.root, text=info_text, font=get_ctk_font(size=11), text_color=self.theme.blockquote
            )
            self.info_label.grid(row=0, column=0, sticky="w", padx=15, pady=(5, 2))
        else:
            self.info_label = tk.Label(
                self.root, text=info_text, font=("Segoe UI", 9), bg=self.colors["bg"], fg=self.colors["blockquote"]
            )
            self.info_label.grid(row=0, column=0, sticky=tk.W, padx=15, pady=(5, 2))

    def _build_info_text(self) -> str:
        """Build the info label text with session info and resolved provider/model."""
        from ... import web_server

        base = f"Session: {self.session.session_id} | Origin: {self.session.origin}"

        # Determine provider/model to display
        if self._manual_mode:
            provider = self.session.provider_override or "—"
            model = self.session.model_override or "—"
        elif self.session.profile_override:
            # Look up profile to get its provider/model
            try:
                from ...connection_profiles import ProfileStore

                profile = ProfileStore.get_instance().get_profile(self.session.profile_override)
                if profile:
                    provider = profile.provider
                    model = profile.model
                else:
                    provider = "?"
                    model = "?"
            except Exception:
                provider = "?"
                model = "?"
        else:
            # Using global/active profile
            try:
                from ...connection_profiles import ProfileStore

                active = ProfileStore.get_instance().get_active_profile()
                provider = active.provider
                model = active.model
            except Exception:
                provider = web_server.get_active_setting("provider", "google")
                model = web_server.get_active_setting("model", "")

        return f"{base} | {provider} / {model}"

    def _update_info_label(self):
        """Refresh the info label text."""
        if self._destroyed or not self.info_label:
            return
        try:
            info_text = self._build_info_text()
            if HAVE_CTK:
                self.info_label.configure(text=info_text)
            else:
                self.info_label.configure(text=info_text)
        except Exception:
            pass

    def _create_toolbar(self):
        """Create the toolbar with session actions, toggle buttons, and model dropdown."""
        if HAVE_CTK:
            btn_frame = ctk.CTkFrame(self.root, fg_color="transparent")
            btn_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=5)

            # Session action buttons (left side)
            warn_colors = get_ctk_button_colors(self.theme, "warning")
            rename_content = prepare_emoji_content("✏️", size=14)
            self.rename_btn = ctk.CTkButton(
                btn_frame,
                **rename_content,
                font=get_ctk_font(size=12),
                width=28,
                height=28,
                corner_radius=6,
                command=self._rename_session,
                **warn_colors,
            )
            self.rename_btn.pack(side="left", padx=(0, 2))

            danger_colors = get_ctk_button_colors(self.theme, "danger")
            delete_content = prepare_emoji_content("🗑️", size=14)
            self.delete_btn = ctk.CTkButton(
                btn_frame,
                **delete_content,
                font=get_ctk_font(size=12),
                width=28,
                height=28,
                corner_radius=6,
                command=self._delete_session,
                **danger_colors,
            )
            self.delete_btn.pack(side="left", padx=(0, 8))

            # Toggle buttons
            btn_colors = get_ctk_button_colors(self.theme, "secondary")

            self.wrap_btn = ctk.CTkButton(
                btn_frame,
                text="Wrap: ON",
                font=get_ctk_font(size=11),
                width=70,
                height=28,
                corner_radius=6,
                command=self._toggle_wrap,
                **btn_colors,
            )
            self.wrap_btn.pack(side="left", padx=2)

            self.md_btn = ctk.CTkButton(
                btn_frame,
                text="Markdown",
                font=get_ctk_font(size=11),
                width=70,
                height=28,
                corner_radius=6,
                command=self._toggle_markdown,
                **btn_colors,
            )
            self.md_btn.pack(side="left", padx=2)

            self.scroll_btn = ctk.CTkButton(
                btn_frame,
                text="Scroll: ON",
                font=get_ctk_font(size=11),
                width=80,
                height=28,
                corner_radius=6,
                command=self._toggle_autoscroll,
                **btn_colors,
            )
            self.scroll_btn.pack(side="left", padx=2)

            # ---- Right-side container ----
            right_container = ctk.CTkFrame(btn_frame, fg_color="transparent")
            right_container.pack(side="right")

            # Toggle button (always visible, leftmost in right group)
            toggle_text = "⚙️ Manual" if self._manual_mode else "📋 Profile"
            toggle_content = prepare_emoji_content(toggle_text, size=14)
            self.manual_toggle_btn = ctk.CTkButton(
                right_container,
                **toggle_content,
                font=get_ctk_font(size=11),
                width=80,
                height=28,
                corner_radius=6,
                command=self._toggle_manual_mode,
                **btn_colors,
            )
            self.manual_toggle_btn.pack(side="left", padx=(0, 6))

            # ---- Profile mode frame ----
            self._profile_widgets_frame = ctk.CTkFrame(right_container, fg_color="transparent")

            if self._use_profile_mode:
                initial_values = ["(Use Global)", *self._get_profile_names()]
                initial_display = self.session.profile_override or "(Use Global)"
            else:
                initial_values = ["(loading...)"]
                initial_display = self.selected_model or self._get_global_sentinel()

            dropdown_label = "Profile:" if self._use_profile_mode else "Model:"

            self.model_label_widget = ctk.CTkLabel(
                self._profile_widgets_frame, text=dropdown_label, font=get_ctk_font(size=11), text_color=self.theme.fg
            )
            self.model_label_widget.pack(side="left", padx=(0, 5))

            self.model_dropdown = ScrollableComboBox(
                self._profile_widgets_frame,
                colors=self.theme,
                values=initial_values,
                width=220,
                height=28,
                command=self._on_model_select,
                item_tooltip_callback=self._get_profile_tooltip if self._use_profile_mode else None,
            )
            self.model_dropdown.pack(side="left", padx=(0, 0))
            self.model_dropdown.set(initial_display)

            # ---- Manual mode frame ----
            self._manual_widgets_frame = ctk.CTkFrame(right_container, fg_color="transparent")

            # Provider dropdown
            from ...providers.registry import PROVIDER_REGISTRY

            provider_ids = sorted(PROVIDER_REGISTRY.keys())

            self.provider_label_widget = ctk.CTkLabel(
                self._manual_widgets_frame, text="Provider:", font=get_ctk_font(size=11), text_color=self.theme.fg
            )
            self.provider_label_widget.pack(side="left", padx=(0, 3))

            self.provider_dropdown = ScrollableComboBox(
                self._manual_widgets_frame,
                colors=self.theme,
                values=provider_ids,
                width=95,
                height=28,
                command=self._on_manual_provider_select,
            )
            self.provider_dropdown.pack(side="left", padx=(0, 8))

            # Model dropdown (manual mode)
            self.manual_model_label_widget = ctk.CTkLabel(
                self._manual_widgets_frame, text="Model:", font=get_ctk_font(size=11), text_color=self.theme.fg
            )
            self.manual_model_label_widget.pack(side="left", padx=(0, 3))

            self.manual_model_dropdown = ScrollableComboBox(
                self._manual_widgets_frame,
                colors=self.theme,
                values=["(select provider)"],
                width=140,
                height=28,
                command=self._on_manual_model_select,
            )
            self.manual_model_dropdown.pack(side="left")

            # Initialize manual mode dropdowns with session state
            if self.session.provider_override:
                self.provider_dropdown.set(self.session.provider_override)
                # Will be populated by _load_manual_models
            if self.session.model_override and self._manual_mode:
                self.manual_model_dropdown.set(self.session.model_override)

            # Show the correct frame based on mode
            if self._manual_mode:
                self._manual_widgets_frame.pack(side="left")
                # Trigger model loading for the current provider
                if self.session.provider_override:
                    threading.Thread(
                        target=self._load_manual_models, args=(self.session.provider_override,), daemon=True
                    ).start()
            else:
                self._profile_widgets_frame.pack(side="left")
        else:
            from tkinter import ttk

            btn_frame = tk.Frame(self.root, bg=self.colors["bg"])
            btn_frame.grid(row=1, column=0, sticky=tk.EW, padx=15, pady=5)

            # Session action buttons (left side)
            self.rename_btn = tk.Button(
                btn_frame,
                text="✏️",
                font=("Segoe UI", 10),
                bg=self.colors.get("accent_yellow", "#f9e2af"),
                fg=self.colors["bg"],
                relief=tk.FLAT,
                padx=4,
                pady=4,
                command=self._rename_session,
                cursor="hand2",
            )
            self.rename_btn.pack(side=tk.LEFT, padx=(0, 2))

            self.delete_btn = tk.Button(
                btn_frame,
                text="🗑️",
                font=("Segoe UI", 10),
                bg=self.colors.get("accent_red", "#f38ba8"),
                fg=self.colors["accent_fg"],
                relief=tk.FLAT,
                padx=4,
                pady=4,
                command=self._delete_session,
                cursor="hand2",
            )
            self.delete_btn.pack(side=tk.LEFT, padx=(0, 8))

            # Toggle buttons
            self.wrap_btn = tk.Button(
                btn_frame,
                text="Wrap: ON",
                font=("Segoe UI", 9),
                bg=self.colors["button_bg"],
                fg=self.colors["fg"],
                relief=tk.FLAT,
                padx=8,
                pady=4,
                command=self._toggle_wrap,
                cursor="hand2",
            )
            self.wrap_btn.pack(side=tk.LEFT, padx=2)

            self.md_btn = tk.Button(
                btn_frame,
                text="Markdown",
                font=("Segoe UI", 9),
                bg=self.colors["button_bg"],
                fg=self.colors["fg"],
                relief=tk.FLAT,
                padx=8,
                pady=4,
                command=self._toggle_markdown,
                cursor="hand2",
            )
            self.md_btn.pack(side=tk.LEFT, padx=2)

            self.scroll_btn = tk.Button(
                btn_frame,
                text="Scroll: ON",
                font=("Segoe UI", 9),
                bg=self.colors["button_bg"],
                fg=self.colors["fg"],
                relief=tk.FLAT,
                padx=8,
                pady=4,
                command=self._toggle_autoscroll,
                cursor="hand2",
            )
            self.scroll_btn.pack(side=tk.LEFT, padx=2)

            # ---- Right-side container ----
            right_container = tk.Frame(btn_frame, bg=self.colors["bg"])
            right_container.pack(side=tk.RIGHT)

            # Toggle button
            toggle_text = "⚙️ Manual" if self._manual_mode else "📋 Profile"
            self.manual_toggle_btn = tk.Button(
                right_container,
                text=toggle_text,
                font=("Segoe UI", 9),
                bg=self.colors["button_bg"],
                fg=self.colors["fg"],
                relief=tk.FLAT,
                padx=8,
                pady=4,
                command=self._toggle_manual_mode,
                cursor="hand2",
            )
            self.manual_toggle_btn.pack(side=tk.LEFT, padx=(0, 8))

            # ---- Profile mode frame ----
            self._profile_widgets_frame = tk.Frame(right_container, bg=self.colors["bg"])

            if self._use_profile_mode:
                initial_values = ["(Use Global)", *self._get_profile_names()]
                initial_display = self.session.profile_override or "(Use Global)"
            else:
                initial_values = ["(loading...)"]
                initial_display = self.selected_model or self._get_global_sentinel()

            dropdown_label = "Profile:" if self._use_profile_mode else "Model:"

            self.model_label_widget = tk.Label(
                self._profile_widgets_frame,
                text=dropdown_label,
                font=("Segoe UI", 9),
                bg=self.colors["bg"],
                fg=self.colors["fg"],
            )
            self.model_label_widget.pack(side=tk.LEFT, padx=(0, 5))

            self.model_dropdown = ScrollableComboBox(
                self._profile_widgets_frame,
                colors=self.theme,
                values=initial_values,
                width=220,
                height=28,
                font_size=11,
                state="readonly",
                command=self._on_model_select,
                item_tooltip_callback=self._get_profile_tooltip if self._use_profile_mode else None,
            )
            self.model_dropdown.pack(side=tk.LEFT)
            self.model_dropdown.set(initial_display)

            # ---- Manual mode frame ----
            self._manual_widgets_frame = tk.Frame(right_container, bg=self.colors["bg"])

            from ...providers.registry import PROVIDER_REGISTRY

            provider_ids = sorted(PROVIDER_REGISTRY.keys())

            self.provider_label_widget = tk.Label(
                self._manual_widgets_frame,
                text="Provider:",
                font=("Segoe UI", 9),
                bg=self.colors["bg"],
                fg=self.colors["fg"],
            )
            self.provider_label_widget.pack(side=tk.LEFT, padx=(0, 3))

            self.provider_dropdown = ttk.Combobox(
                self._manual_widgets_frame, values=provider_ids, width=9, state="readonly"
            )
            self.provider_dropdown.pack(side=tk.LEFT, padx=(0, 8))
            self.provider_dropdown.bind(
                "<<ComboboxSelected>>", lambda e: self._on_manual_provider_select(self.provider_dropdown.get())
            )

            self.manual_model_label_widget = tk.Label(
                self._manual_widgets_frame,
                text="Model:",
                font=("Segoe UI", 9),
                bg=self.colors["bg"],
                fg=self.colors["fg"],
            )
            self.manual_model_label_widget.pack(side=tk.LEFT, padx=(0, 3))

            self.manual_model_dropdown = ttk.Combobox(
                self._manual_widgets_frame, values=["(select provider)"], width=16, state="readonly"
            )
            self.manual_model_dropdown.pack(side=tk.LEFT)
            self.manual_model_dropdown.bind(
                "<<ComboboxSelected>>", lambda e: self._on_manual_model_select(self.manual_model_dropdown.get())
            )

            # Initialize from session state
            if self.session.provider_override:
                self.provider_dropdown.set(self.session.provider_override)
            if self.session.model_override and self._manual_mode:
                self.manual_model_dropdown.set(self.session.model_override)

            # Show correct frame
            if self._manual_mode:
                self._manual_widgets_frame.pack(side=tk.LEFT)
                if self.session.provider_override:
                    threading.Thread(
                        target=self._load_manual_models, args=(self.session.provider_override,), daemon=True
                    ).start()
            else:
                self._profile_widgets_frame.pack(side=tk.LEFT)

        # Schedule model loading
        self._schedule_model_loading()

    def _schedule_model_loading(self):
        """Schedule model loading - skip in profile mode or manual mode."""
        if self._use_profile_mode or self._manual_mode:
            return  # Profile names or manual dropdowns handle their own loading
        threading.Thread(target=self._load_models, daemon=True).start()

    def _create_chat_area(self):
        """Create the chat display area (hybrid: CTkFrame + tk.Text for markdown)."""
        if HAVE_CTK:
            chat_frame = ctk.CTkFrame(
                self.root, corner_radius=10, fg_color=self.theme.text_bg, border_color=self.theme.border, border_width=1
            )
            chat_frame.grid(row=2, column=0, sticky="nsew", padx=15, pady=5)
            chat_frame.columnconfigure(0, weight=1)
            chat_frame.rowconfigure(0, weight=1)

            self.chat_text = tk.Text(
                chat_frame,
                wrap=tk.WORD,
                font=get_tk_font(11),
                bg=self.theme.text_bg,
                fg=self.theme.fg,
                insertbackground=self.theme.fg,
                selectbackground=self.theme.accent,
                selectforeground=self.theme.bg,
                relief=tk.FLAT,
                highlightthickness=0,
                padx=12,
                pady=12,
                borderwidth=0,
            )
            self.chat_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)

            scrollbar_colors = get_ctk_scrollbar_colors(self.theme)
            self.v_scrollbar = ctk.CTkScrollbar(
                chat_frame, command=self.chat_text.yview, corner_radius=4, width=14, **scrollbar_colors
            )
            self.v_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=8)
            self.chat_text.configure(yscrollcommand=self.v_scrollbar.set)

            self.h_scrollbar = ctk.CTkScrollbar(
                chat_frame,
                orientation="horizontal",
                command=self.chat_text.xview,
                corner_radius=4,
                height=14,
                **scrollbar_colors,
            )
            self.h_scrollbar.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
            self.h_scrollbar.grid_remove()
            self.chat_text.configure(xscrollcommand=self.h_scrollbar.set)
        else:
            from tkinter import ttk

            chat_frame = tk.Frame(
                self.root, bg=self.colors["text_bg"], highlightbackground=self.colors["border"], highlightthickness=1
            )
            chat_frame.grid(row=2, column=0, sticky=tk.NSEW, padx=15, pady=5)
            chat_frame.columnconfigure(0, weight=1)
            chat_frame.rowconfigure(0, weight=1)

            self.chat_text = tk.Text(
                chat_frame,
                wrap=tk.WORD,
                font=get_tk_font(11),
                bg=self.colors["text_bg"],
                fg=self.colors["fg"],
                insertbackground=self.colors["fg"],
                selectbackground=self.colors["accent"],
                selectforeground=self.colors["bg"],
                relief=tk.FLAT,
                highlightthickness=0,
                padx=12,
                pady=12,
                borderwidth=0,
            )
            self.chat_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)

            self.v_scrollbar = ttk.Scrollbar(chat_frame, orient=tk.VERTICAL, command=self.chat_text.yview)
            self.v_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=8)
            self.chat_text.configure(yscrollcommand=self.v_scrollbar.set)

            self.h_scrollbar = ttk.Scrollbar(chat_frame, orient=tk.HORIZONTAL, command=self.chat_text.xview)
            self.h_scrollbar.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
            self.h_scrollbar.grid_remove()
            self.chat_text.configure(xscrollcommand=self.h_scrollbar.set)

        # Setup text tags for markdown
        setup_text_tags(self.chat_text, self.colors)
        self.chat_text.tag_bind("thinking_header", "<Button-1>", self._on_thinking_click)

        # Right-click context menu for message editing
        self.chat_text.bind("<Button-3>", self._on_chat_right_click)

    def _create_input_area(self):
        """Create the message input area with attachment button."""
        placeholder = self._placeholder

        if HAVE_CTK:
            input_frame = ctk.CTkFrame(self.root, fg_color="transparent")
            # Moved up to row 3 (was 4), removed header frame
            input_frame.grid(row=3, column=0, sticky="ew", padx=15, pady=5)
            input_frame.columnconfigure(0, weight=1)

            textbox_colors = get_ctk_textbox_colors(self.theme)
            self.input_text = ctk.CTkTextbox(
                input_frame,
                height=75,
                font=get_ctk_font(size=12),
                corner_radius=8,
                border_width=1,
                wrap="word",
                **textbox_colors,
            )
            self.input_text.grid(row=0, column=0, sticky="ew", padx=(0, 5))

            # Pending attachments indicator (inside input frame now)
            self._attachments_label = ctk.CTkLabel(
                input_frame, text="", font=get_ctk_font(size=10), text_color=self.theme.accent_yellow
            )

            # Attachment button (📎)
            attach_colors = get_ctk_button_colors(self.theme, "secondary")
            self.attach_btn = ctk.CTkButton(
                input_frame,
                text="📎",
                font=get_ctk_font(size=16),
                width=40,
                height=40,
                corner_radius=8,
                command=self._on_attach_click,
                **attach_colors,
            )
            self.attach_btn.grid(row=0, column=1, sticky="n", pady=5)

            # Pending attachments preview frame (below input)
            self.attachments_frame = ctk.CTkFrame(self.root, fg_color="transparent", height=0)
            self.attachments_frame.grid(row=4, column=0, sticky="ew", padx=15)  # Row 5 -> 4
            self.attachments_frame.grid_remove()  # Initially hidden

            self.input_text.insert("0.0", placeholder)
            self.input_text.configure(text_color=self.theme.overlay0)

            def on_focus_in(event):
                content = self.input_text.get("0.0", "end-1c")
                if content == placeholder:
                    self.input_text.delete("0.0", "end")
                    self.input_text.configure(text_color=self.theme.fg)
                    self._has_placeholder = False

            def on_focus_out(event):
                content = self.input_text.get("0.0", "end-1c").strip()
                if not content:
                    self.input_text.insert("0.0", placeholder)
                    self.input_text.configure(text_color=self.theme.overlay0)
                    self._has_placeholder = True

            def on_key_return(event):
                if event.state & 0x1:  # Shift held
                    return None
                else:
                    self._send()
                    return "break"

            def on_ctrl_backspace(event):
                try:
                    import re

                    cursor_pos = self.input_text.index(tk.INSERT)
                    line, col = map(int, cursor_pos.split("."))
                    if col == 0:
                        return None
                    line_start = f"{line}.0"
                    text_before = self.input_text.get(line_start, cursor_pos)
                    match = re.search(r"(\s*\S+\s*)$", text_before)
                    if match:
                        delete_start = f"{line}.{col - len(match.group(0))}"
                        self.input_text.delete(delete_start, cursor_pos)
                    return "break"
                except Exception:
                    return None

            self.input_text.bind("<FocusIn>", on_focus_in)
            self.input_text.bind("<FocusOut>", on_focus_out)
            self.input_text.bind("<Return>", on_key_return)
            self.input_text.bind("<Control-BackSpace>", on_ctrl_backspace)
            self.input_text.bind("<Control-v>", self._on_paste)
        else:
            input_frame = tk.Frame(self.root, bg=self.colors["bg"])
            # Moved up to row 3 (was 4), removed header frame
            input_frame.grid(row=3, column=0, sticky=tk.EW, padx=15, pady=5)
            input_frame.columnconfigure(0, weight=1)

            self.input_text = tk.Text(
                input_frame,
                height=4,
                font=("Segoe UI", 11),
                bg=self.colors["input_bg"],
                fg=self.colors["fg"],
                insertbackground=self.colors["fg"],
                relief=tk.FLAT,
                highlightbackground=self.colors["border"],
                highlightthickness=1,
                padx=8,
                pady=8,
                wrap=tk.WORD,
            )
            self.input_text.grid(row=0, column=0, sticky="ew", padx=(0, 5))

            # Pending attachments indicator
            self._attachments_label = tk.Label(
                input_frame, text="", font=("Segoe UI", 9), bg=self.colors["bg"], fg=self.colors["accent"]
            )

            # Attachment button
            self.attach_btn = tk.Button(
                input_frame,
                text="📎",
                font=("Segoe UI", 14),
                bg=self.colors["button_bg"],
                fg=self.colors["fg"],
                relief=tk.FLAT,
                width=3,
                height=2,
                command=self._on_attach_click,
                cursor="hand2",
            )
            self.attach_btn.grid(row=0, column=1, sticky="n", pady=5)

            # Pending attachments preview frame
            self.attachments_frame = tk.Frame(self.root, bg=self.colors["bg"])
            self.attachments_frame.grid(row=4, column=0, sticky=tk.EW, padx=15)  # Row 5 -> 4
            self.attachments_frame.grid_remove()  # Initially hidden

            self.input_text.insert("1.0", placeholder)
            self.input_text.configure(fg=self.colors["blockquote"])

            def on_focus_in(event):
                content = self.input_text.get("1.0", "end-1c")
                if content == placeholder:
                    self.input_text.delete("1.0", tk.END)
                    self.input_text.configure(fg=self.colors["fg"])
                    self._has_placeholder = False

            def on_focus_out(event):
                content = self.input_text.get("1.0", "end-1c").strip()
                if not content:
                    self.input_text.insert("1.0", placeholder)
                    self.input_text.configure(fg=self.colors["blockquote"])
                    self._has_placeholder = True

            def on_key_return(event):
                if event.state & 0x1:
                    return None
                else:
                    self._send()
                    return "break"

            self.input_text.bind("<FocusIn>", on_focus_in)
            self.input_text.bind("<FocusOut>", on_focus_out)
            self.input_text.bind("<Return>", on_key_return)
            self.input_text.bind("<Control-v>", self._on_paste)

    def _create_action_buttons(self):
        """Create the action button row."""
        if HAVE_CTK:
            btn_row = ctk.CTkFrame(self.root, fg_color="transparent")
            btn_row.grid(row=5, column=0, sticky="ew", padx=15, pady=(5, 15))  # Row 6 -> 5

            send_colors = get_ctk_button_colors(self.theme, "success")
            send_content = prepare_emoji_content("📤 Send", size=16)
            self.send_btn = ctk.CTkButton(
                btn_row,
                **send_content,
                font=get_ctk_font(size=12, weight="bold"),
                width=80,
                height=32,
                corner_radius=8,
                command=self._send,
                **send_colors,
            )
            self.send_btn.pack(side="left", padx=2)

            # Regenerate button (warning/yellow color)
            regen_colors = get_ctk_button_colors(self.theme, "warning")
            regen_content = prepare_emoji_content("🔄 Regen", size=16)
            self.regen_btn = ctk.CTkButton(
                btn_row,
                **regen_content,
                font=get_ctk_font(size=12),
                width=85,
                height=32,
                corner_radius=8,
                command=self._regenerate,
                **regen_colors,
            )
            self.regen_btn.pack(side="left", padx=2)

            sec_colors = get_ctk_button_colors(self.theme, "secondary")

            ctk.CTkButton(
                btn_row,
                text="Copy All",
                font=get_ctk_font(size=12),
                width=85,
                height=32,
                corner_radius=8,
                command=self._copy_all,
                **sec_colors,
            ).pack(side="left", padx=2)

            ctk.CTkButton(
                btn_row,
                text="Copy Last",
                font=get_ctk_font(size=12),
                width=85,
                height=32,
                corner_radius=8,
                command=self._copy_last,
                **sec_colors,
            ).pack(side="left", padx=2)

            ctk.CTkButton(
                btn_row,
                text="Close",
                font=get_ctk_font(size=12),
                width=70,
                height=32,
                corner_radius=8,
                command=self._close,
                **sec_colors,
            ).pack(side="left", padx=2)

            self.status_label = ctk.CTkLabel(
                btn_row, text="", font=get_ctk_font(size=11), text_color=self.theme.accent_green
            )
            self.status_label.pack(side="left", padx=15)
        else:
            btn_row = tk.Frame(self.root, bg=self.colors["bg"])
            btn_row.grid(row=5, column=0, sticky=tk.EW, padx=15, pady=(5, 15))  # Row 6 -> 5

            self.send_btn = tk.Button(
                btn_row,
                text="Send",
                font=("Segoe UI", 10, "bold"),
                bg=self.colors["accent"],
                fg=self.colors["accent_fg"],
                relief=tk.FLAT,
                padx=12,
                pady=6,
                command=self._send,
                cursor="hand2",
            )
            self.send_btn.pack(side=tk.LEFT, padx=2)

            # Regenerate button (warning/yellow color)
            self.regen_btn = tk.Button(
                btn_row,
                text="🔄 Regen",
                font=("Segoe UI", 10),
                bg=self.colors.get("accent_yellow", "#f9e2af"),
                fg=self.colors["bg"],
                relief=tk.FLAT,
                padx=10,
                pady=6,
                command=self._regenerate,
                cursor="hand2",
            )
            self.regen_btn.pack(side=tk.LEFT, padx=2)

            for text, cmd in [("Copy All", self._copy_all), ("Copy Last", self._copy_last), ("Close", self._close)]:
                btn = tk.Button(
                    btn_row,
                    text=text,
                    font=("Segoe UI", 10),
                    bg=self.colors["button_bg"],
                    fg=self.colors["fg"],
                    relief=tk.FLAT,
                    padx=10,
                    pady=6,
                    command=cmd,
                    cursor="hand2",
                )
                btn.pack(side=tk.LEFT, padx=2)

            self.status_label = tk.Label(
                btn_row, text="", font=("Segoe UI", 9), bg=self.colors["bg"], fg=self.colors["accent"]
            )
            self.status_label.pack(side=tk.LEFT, padx=15)

    # =========================================================================
    # Chat Display
    # =========================================================================

    def _update_chat_display(self, scroll_to_bottom: bool = False, preserve_scroll: bool = False):
        """Update the chat display with card-style message layout and inline images."""
        if self._destroyed or not self.chat_text:
            return

        saved_scroll = None
        if preserve_scroll:
            saved_scroll = self.chat_text.yview()

        # Clear previous thumbnail references to allow garbage collection
        if hasattr(self, "_chat_thumbnails"):
            self._chat_thumbnails.clear()
        else:
            self._chat_thumbnails = []

        self.chat_text.configure(state=tk.NORMAL)
        self.chat_text.delete("1.0", tk.END)

        # Update button labels
        if self.wrap_btn:
            if HAVE_CTK:
                self.wrap_btn.configure(text=f"Wrap: {'ON' if self.wrapped else 'OFF'}")
            else:
                self.wrap_btn.configure(text=f"Wrap: {'ON' if self.wrapped else 'OFF'}")
        if self.md_btn:
            if HAVE_CTK:
                self.md_btn.configure(text="Markdown" if self.markdown else "Raw Text")
            else:
                self.md_btn.configure(text="Markdown" if self.markdown else "Raw Text")
        if self.scroll_btn:
            if HAVE_CTK:
                self.scroll_btn.configure(text=f"Scroll: {'ON' if self.auto_scroll else 'OFF'}")
            else:
                self.scroll_btn.configure(text=f"Scroll: {'ON' if self.auto_scroll else 'OFF'}")

        # Render messages with card-style layout
        for i, msg in enumerate(self.session.messages):
            role = msg["role"]
            content = msg["content"]
            thinking = msg.get("thinking", "")

            # Add gap between messages (not before first)
            if i > 0:
                self.chat_text.insert(tk.END, "\n", "card_gap")

            # Track message start position for per-message tag
            msg_start = self.chat_text.index(tk.END)

            # Determine styling based on role
            if role == "user":
                accent_tag = "user_accent_bar"
                label_tag = "user_label"
                message_tag = "user_message"
                label_text = "You"
            else:
                accent_tag = "assistant_accent_bar"
                label_tag = "assistant_label"
                message_tag = "assistant_message"
                label_text = "Assistant"

            # Insert accent bar + label with inline action icons
            self.chat_text.insert(tk.END, "▌ ", (accent_tag, message_tag))
            self.chat_text.insert(tk.END, label_text, (label_tag, message_tag))

            # Per-message action icon tags with click handlers + hover highlight
            edit_tag = f"edit_{i}"
            rerun_tag = f"rerun_{i}"
            more_tag = f"more_{i}"
            for atag in (edit_tag, rerun_tag, more_tag):
                self.chat_text.tag_configure(atag)
                self.chat_text.tag_bind(
                    atag,
                    "<Enter>",
                    lambda e, t=atag: (
                        self.chat_text.config(cursor="hand2"),
                        self.chat_text.tag_configure(t, foreground=self.theme.accent),
                    ),
                )
                self.chat_text.tag_bind(
                    atag,
                    "<Leave>",
                    lambda e, t=atag: (
                        self.chat_text.config(cursor=""),
                        self.chat_text.tag_configure(t, foreground=""),
                    ),
                )
            self.chat_text.tag_bind(edit_tag, "<Button-1>", lambda e, idx=i: self._edit_message(idx))
            self.chat_text.tag_bind(rerun_tag, "<Button-1>", lambda e, idx=i: self._rerun_turn(idx))
            self.chat_text.tag_bind(more_tag, "<Button-1>", lambda e, idx=i: self._show_message_context_menu(e, idx))

            self.chat_text.insert(tk.END, "  edit", ("action_icon", edit_tag, message_tag))
            self.chat_text.insert(tk.END, "  rerun", ("action_icon", rerun_tag, message_tag))
            self.chat_text.insert(tk.END, "  \u00b7\u00b7\u00b7", ("action_icon", more_tag, message_tag))
            self.chat_text.insert(tk.END, "\n", (message_tag,))

            # Render per-message attachments
            msg_attachments = msg.get("attachments", [])
            if msg_attachments and role == "user":
                self._render_message_attachments(msg_attachments, message_tag)

            # Thinking section (if assistant and has thinking)
            if role == "assistant" and thinking:
                is_collapsed = self.thinking_collapsed_states.get(i, True)

                # Create per-message thinking header tag
                thinking_tag = f"thinking_header_{i}"
                self.chat_text.tag_configure(
                    thinking_tag,
                    font=get_tk_font(10, "bold"),
                    foreground=self.theme.accent_yellow,
                    spacing1=2,
                    spacing3=2,
                )

                # Bind click event for this specific message
                self.chat_text.tag_bind(thinking_tag, "<Button-1>", lambda e, idx=i: self._toggle_thinking(idx))
                self.chat_text.tag_bind(thinking_tag, "<Enter>", lambda e: self.chat_text.config(cursor="hand2"))
                self.chat_text.tag_bind(thinking_tag, "<Leave>", lambda e: self.chat_text.config(cursor=""))

                # Insert thinking header
                thinking_header = "▶ Thinking..." if is_collapsed else "▼ Thinking:"
                self.chat_text.insert(tk.END, f"  {thinking_header}\n", (thinking_tag, "thinking_block_layout"))

                # Show thinking content if expanded
                if not is_collapsed:
                    if self.markdown:
                        render_markdown(
                            thinking,
                            self.chat_text,
                            self.colors,
                            wrap=self.wrapped,
                            as_role="thinking",
                            block_tag="thinking_block_layout",
                            enable_emojis=True,
                            line_prefix="    ",
                        )
                    else:
                        for t_line in thinking.split("\n"):
                            self.chat_text.insert(
                                tk.END, "    " + t_line + "\n", ("thinking_content", "thinking_block_layout")
                            )

                    # Insert separator between thinking and answer
                    self.chat_text.insert(tk.END, "  " + "─" * 36 + "\n", ("thinking_end_sep", "thinking_block_layout"))

            # Render content
            if self.markdown:
                render_markdown(
                    content,
                    self.chat_text,
                    self.colors,
                    wrap=self.wrapped,
                    as_role=role,
                    block_tag=message_tag,
                    enable_emojis=True,
                    line_prefix="  ",
                )
            else:
                self.chat_text.configure(wrap=tk.WORD if self.wrapped else tk.NONE)
                for c_idx, c_line in enumerate(content.split("\n")):
                    self.chat_text.insert(tk.END, "  " + c_line, ("normal", message_tag))
                    if c_idx < len(content.split("\n")) - 1:
                        self.chat_text.insert(tk.END, "\n", (message_tag,))

            # End of card - add trailing newline
            self.chat_text.insert(tk.END, "\n", (message_tag,))

            # Add per-message tracking tag to entire message range
            msg_idx_tag = f"msg_{i}"
            self.chat_text.tag_configure(msg_idx_tag)
            self.chat_text.tag_add(msg_idx_tag, msg_start, self.chat_text.index(tk.END))

        self.chat_text.configure(state=tk.DISABLED)

        if scroll_to_bottom and self.auto_scroll:
            self.chat_text.see(tk.END)
        elif preserve_scroll and saved_scroll:
            self.chat_text.yview_moveto(saved_scroll[0])

    def _update_streaming_display(self):
        """Update display during streaming with card-style layout."""
        if not self.is_streaming or self._destroyed:
            return

        self.chat_text.configure(state=tk.NORMAL)

        # Find and remove the streaming message
        try:
            gap_pos = self.chat_text.search("▌ Assistant", "end", backwards=True)
            if gap_pos:
                line_num = int(gap_pos.split(".")[0])
                if line_num > 1:
                    self.chat_text.delete(f"{line_num - 1}.0", tk.END)
        except Exception:
            pass

        # Add gap before streaming message
        self.chat_text.insert(tk.END, "\n", "card_gap")

        accent_tag = "assistant_accent_bar"
        message_tag = "assistant_message"

        # Insert assistant label
        self.chat_text.insert(tk.END, "▌ ", (accent_tag, message_tag))
        self.chat_text.insert(tk.END, "Assistant\n", ("assistant_label", message_tag))

        # Streaming message index for thinking toggle
        streaming_idx = len(self.session.messages)

        # Default to expanded during streaming if not explicitly collapsed
        if streaming_idx not in self.thinking_collapsed_states:
            self.thinking_collapsed_states[streaming_idx] = False

        is_collapsed = self.thinking_collapsed_states.get(streaming_idx, False)

        if self.streaming_thinking:
            thinking_header = "▶ Thinking..." if is_collapsed else "▼ Thinking:"
            self.chat_text.insert(tk.END, f"  {thinking_header}\n", ("thinking_header", "thinking_block_layout"))
            if not is_collapsed:
                for t_line in self.streaming_thinking.split("\n"):
                    self.chat_text.insert(tk.END, "    " + t_line + "\n", ("thinking_content", "thinking_block_layout"))

            # Add separator after thinking (even while streaming)
            if self.streaming_text:
                self.chat_text.insert(tk.END, "  " + "─" * 36 + "\n", ("thinking_end_sep", "thinking_block_layout"))

        # Streaming content
        if self.streaming_text:
            for c_idx, c_line in enumerate(self.streaming_text.split("\n")):
                self.chat_text.insert(tk.END, "  " + c_line, ("normal", message_tag))
                if c_idx < len(self.streaming_text.split("\n")) - 1:
                    self.chat_text.insert(tk.END, "\n", (message_tag,))
        else:
            self.chat_text.insert(tk.END, "  ...", ("normal", message_tag))

        self.chat_text.insert(tk.END, "\n", (message_tag,))

        self.chat_text.configure(state=tk.DISABLED)

        if self.auto_scroll:
            self.chat_text.see(tk.END)

    # =========================================================================
    # Toggle Methods
    # =========================================================================

    def _toggle_wrap(self):
        self.wrapped = not self.wrapped
        if self.h_scrollbar:
            if self.wrapped:
                self.h_scrollbar.grid_remove()
            else:
                self.h_scrollbar.grid()
        self._update_chat_display(preserve_scroll=True)
        self._update_status(f"Wrap: {'ON' if self.wrapped else 'OFF'}")

    def _toggle_markdown(self):
        self.markdown = not self.markdown
        self._update_chat_display(preserve_scroll=True)
        self._update_status(f"Mode: {'Markdown' if self.markdown else 'Raw Text'}")

    def _toggle_autoscroll(self):
        self.auto_scroll = not self.auto_scroll
        if self.scroll_btn:
            if HAVE_CTK:
                self.scroll_btn.configure(text=f"Scroll: {'ON' if self.auto_scroll else 'OFF'}")
            else:
                self.scroll_btn.configure(text=f"Scroll: {'ON' if self.auto_scroll else 'OFF'}")
        self._update_status(f"Autoscroll: {'ON' if self.auto_scroll else 'OFF'}")

    def _toggle_thinking(self, message_index: int):
        """Toggle thinking section visibility for a specific message."""
        current = self.thinking_collapsed_states.get(message_index, True)
        self.thinking_collapsed_states[message_index] = not current
        self._update_chat_display(preserve_scroll=True)
        state = "collapsed" if self.thinking_collapsed_states[message_index] else "expanded"
        self._update_status(f"Thinking: {state}")

    def _on_thinking_click(self, event):
        """Legacy handler - toggles all thinking sections."""
        all_collapsed = all(
            self.thinking_collapsed_states.get(i, True)
            for i, msg in enumerate(self.session.messages)
            if msg.get("thinking")
        )
        for i, msg in enumerate(self.session.messages):
            if msg.get("thinking"):
                self.thinking_collapsed_states[i] = not all_collapsed
        self._update_chat_display(preserve_scroll=True)
        self._update_status(f"Thinking: {'collapsed' if all_collapsed else 'expanded'}")

    # =========================================================================
    # Status & Models
    # =========================================================================

    def _update_status(self, text: str, color: str | None = None):
        """Update status label."""
        if not self.status_label:
            return
        if HAVE_CTK:
            self.status_label.configure(text=text)
            if color:
                self.status_label.configure(text_color=color)
        else:
            self.status_label.configure(text=text)
            if color:
                self.status_label.configure(fg=color)

    def _get_global_sentinel(self) -> str:
        """Build the '(Use Global: <model>)' sentinel label from current config."""
        from ... import web_server

        global_model = web_server.get_active_setting("model", "")
        return f"(Use Global: {global_model})" if global_model else "(Use Global)"

    def _toggle_manual_mode(self):
        """Toggle between profile mode and manual mode."""
        self._manual_mode = not self._manual_mode
        self.session.manual_mode = self._manual_mode

        if self._manual_mode:
            # Switch to manual mode
            self._profile_widgets_frame.pack_forget()
            self._manual_widgets_frame.pack(side="left" if HAVE_CTK else tk.LEFT)

            if HAVE_CTK:
                content = prepare_emoji_content("📋 Profile", size=14)
                self.manual_toggle_btn.configure(**content)
            else:
                self.manual_toggle_btn.configure(text="📋 Profile")

            # If provider was previously set, load models for it
            if self.session.provider_override:
                self.provider_dropdown.set(self.session.provider_override)
                if self.session.model_override:
                    self.manual_model_dropdown.set(self.session.model_override)
                threading.Thread(
                    target=self._load_manual_models, args=(self.session.provider_override,), daemon=True
                ).start()

            self._update_status("Manual mode: select provider & model")
        else:
            # Switch to profile mode
            self._manual_widgets_frame.pack_forget()
            self._profile_widgets_frame.pack(side="left" if HAVE_CTK else tk.LEFT)

            if HAVE_CTK:
                content = prepare_emoji_content("⚙️ Manual", size=14)
                self.manual_toggle_btn.configure(**content)
            else:
                self.manual_toggle_btn.configure(text="⚙️ Manual")

            # Clear manual overrides — revert to profile-based resolution
            self.session.provider_override = None
            # Keep model_override only if it was set in profile mode
            if not self.session.profile_override:
                self.session.model_override = None

            self._update_status("Profile mode")

        # Update info label and persist
        self._update_info_label()

        from ... import web_server

        add_session(self.session, web_server.CONFIG.get("max_sessions", 200))

    def _on_manual_provider_select(self, selected: str):
        """Handle provider selection in manual mode."""
        if not selected:
            return

        self.session.provider_override = selected
        self.session.profile_override = None  # Manual mode clears profile
        self.session.model_override = None  # Reset model when provider changes

        # Reset model dropdown
        if HAVE_CTK:
            self.manual_model_dropdown.configure(values=["(loading...)"])
            self.manual_model_dropdown.set("(loading...)")
        else:
            self.manual_model_dropdown.configure(values=["(loading...)"])
            self.manual_model_dropdown.set("(loading...)")

        # Update info label
        self._update_info_label()

        # Load models for the selected provider
        threading.Thread(target=self._load_manual_models, args=(selected,), daemon=True).start()

        self._update_status(f"Provider: {selected}")

        from ... import web_server

        add_session(self.session, web_server.CONFIG.get("max_sessions", 200))

    def _on_manual_model_select(self, selected: str):
        """Handle model selection in manual mode."""
        if not selected or selected in ("(loading...)", "(select provider)", "(no models)"):
            return

        self.session.model_override = selected
        self.selected_model = selected

        # Update info label
        self._update_info_label()

        self._update_status(f"✅ Model: {selected}", self.theme.accent_green)

        from ... import web_server

        add_session(self.session, web_server.CONFIG.get("max_sessions", 200))

    def _load_manual_models(self, provider: str):
        """Load models for a specific provider (manual mode). Runs in background thread."""
        if self._destroyed:
            return

        try:
            from ... import web_server
            from ...api_client import fetch_models
            from ...model_defaults import get_fallback_models

            # Try live fetch first
            models, error = fetch_models(web_server.CONFIG, web_server.KEY_MANAGERS, provider_override=provider)

            if models and not error and not self._destroyed:
                model_ids = [m["id"] for m in models]
            else:
                # Fall back to curated list
                model_ids = get_fallback_models(provider)

            if not model_ids:
                model_ids = ["(no models)"]

            def update_dropdown():
                if self._destroyed:
                    return
                try:
                    if HAVE_CTK:
                        self.manual_model_dropdown.configure(values=model_ids)
                    else:
                        self.manual_model_dropdown.configure(values=model_ids)

                    # Restore session's model if it's in the list
                    if self.session.model_override and self.session.model_override in model_ids:
                        self.manual_model_dropdown.set(self.session.model_override)
                    elif self.session.model_override:
                        # Model not in list but keep showing it
                        self.manual_model_dropdown.set(self.session.model_override)
                    elif model_ids and model_ids[0] != "(no models)":
                        self.manual_model_dropdown.set(model_ids[0])
                except Exception:
                    pass

            self._safe_after(0, update_dropdown)

        except Exception as e:
            print(f"[ChatWindowBase] Error loading manual models: {e}")
            # Use fallback
            from ...model_defaults import get_fallback_models

            fallback = get_fallback_models(provider) or ["(no models)"]

            def update_fallback():
                if self._destroyed:
                    return
                try:
                    if HAVE_CTK:
                        self.manual_model_dropdown.configure(values=fallback)
                    else:
                        self.manual_model_dropdown.configure(values=fallback)
                except Exception:
                    pass

            self._safe_after(0, update_fallback)

    def _refresh_profile_list(self):
        """Refresh the profile dropdown values (called when profiles change)."""
        if self._destroyed or not self.model_dropdown:
            return
        if not self._use_profile_mode or self._manual_mode:
            return  # Only relevant in profile mode

        try:
            profile_names = self._get_profile_names()
            values = ["(Use Global)", *profile_names]
            if HAVE_CTK:
                self.model_dropdown.configure(values=values)
            else:
                self.model_dropdown.configure(values=values)

            # If current profile was deleted, reset to (Use Global)
            current = self.session.profile_override
            if current and current not in profile_names:
                self.session.profile_override = None
                self.model_dropdown.set("(Use Global)")
                self._update_info_label()
        except Exception:
            pass

    def _load_models(self):
        """Load available models in background."""
        if self._destroyed:
            return
        try:
            from ... import web_server
            from ...api_client import fetch_models

            models, error = fetch_models(web_server.CONFIG, web_server.KEY_MANAGERS)

            if models and not error and not self._destroyed:
                self.available_models = models
                model_ids = [m["id"] for m in models]

                def update_dropdown():
                    if self._destroyed:
                        return
                    try:
                        # Prepend dynamic global sentinel to dropdown values
                        sentinel = self._get_global_sentinel()
                        dropdown_values = [sentinel, *model_ids]

                        if HAVE_CTK:
                            self.model_dropdown.configure(values=dropdown_values)
                        else:
                            self.model_dropdown.configure(values=dropdown_values)

                        # Set dropdown value based on session override
                        if self.session.model_override:
                            # Session has a specific model override
                            if self.session.model_override in model_ids:
                                self.model_dropdown.set(self.session.model_override)
                            else:
                                # Model not in list but still use it
                                self.model_dropdown.set(self.session.model_override)
                        else:
                            # No override — show global sentinel
                            self.model_dropdown.set(sentinel)
                    except Exception:
                        pass

                self._safe_after(0, update_dropdown)
            elif not self._destroyed:
                # Fetch failed or returned empty — use fallback list
                provider = web_server.get_active_setting("default_provider", "google")
                fallback_ids = get_fallback_models(provider)
                if fallback_ids:
                    self.available_models = [{"id": mid} for mid in fallback_ids]

                    def update_fallback_dropdown():
                        if self._destroyed:
                            return
                        try:
                            sentinel = self._get_global_sentinel()
                            dropdown_values = [sentinel, *fallback_ids]

                            if HAVE_CTK:
                                self.model_dropdown.configure(values=dropdown_values)
                            else:
                                self.model_dropdown.configure(values=dropdown_values)

                            if self.session.model_override:
                                self.model_dropdown.set(self.session.model_override)
                            else:
                                self.model_dropdown.set(sentinel)
                        except Exception:
                            pass

                    self._safe_after(0, update_fallback_dropdown)
                if error:
                    print(f"[ChatWindowBase] Error loading models: {error}")
        except Exception as e:
            print(f"[ChatWindowBase] Error loading models: {e}")
            # Exception during fetch — try fallback
            if not self._destroyed:
                try:
                    from ... import web_server

                    provider = web_server.get_active_setting("default_provider", "google")
                except Exception:
                    provider = "google"
                fallback_ids = get_fallback_models(provider)
                if fallback_ids:
                    self.available_models = [{"id": mid} for mid in fallback_ids]

                    def update_fallback_on_error():
                        if self._destroyed:
                            return
                        try:
                            sentinel = self._get_global_sentinel()
                            dropdown_values = [sentinel, *fallback_ids]

                            if HAVE_CTK:
                                self.model_dropdown.configure(values=dropdown_values)
                            else:
                                self.model_dropdown.configure(values=dropdown_values)

                            if self.session.model_override:
                                self.model_dropdown.set(self.session.model_override)
                            else:
                                self.model_dropdown.set(sentinel)
                        except Exception:
                            pass

                    self._safe_after(0, update_fallback_on_error)

    def _on_config_changed(self, key: str, value=None):
        """Handle config change events — marshal to GUI thread.

        Called from any thread (config pub/sub). Uses _safe_after to schedule
        the actual UI update on the main thread.
        """
        if self._destroyed:
            return
        # React to profile_selector_enabled toggle
        if key == "profile_selector_enabled" or key == "_bulk_update":
            self._safe_after(0, self._refresh_profile_mode)
        # React to profile list changes (create/delete/rename in ConnectionProfileManager)
        if key == "_profiles_changed" or key == "_bulk_update":
            self._safe_after(0, self._refresh_profile_list)
            self._safe_after(0, self._update_info_label)
        # Only react to model/provider changes in model mode
        if not self._use_profile_mode:
            if key.endswith("_model") or key == "default_provider" or key == "_bulk_update":
                self._safe_after(0, self._refresh_global_sentinel)

    def _refresh_global_sentinel(self):
        """Update the global sentinel label in the dropdown when the global model changes."""
        if self._destroyed or self._use_profile_mode:
            return  # Profile mode doesn't use the global model sentinel
        try:
            from ... import web_server

            current_global = web_server.get_active_setting("model", "")

            if current_global != self._last_global_model:
                self._last_global_model = current_global
                new_sentinel = self._get_global_sentinel()

                # Rebuild dropdown values with updated sentinel
                if self.available_models:
                    model_ids = [m["id"] for m in self.available_models]
                    dropdown_values = [new_sentinel, *model_ids]

                    if HAVE_CTK:
                        self.model_dropdown.configure(values=dropdown_values)
                    else:
                        self.model_dropdown.configure(values=dropdown_values)

                    # If session is using global (no override), update display
                    if self.session.model_override is None:
                        self.model_dropdown.set(new_sentinel)
        except Exception:
            pass

    def _refresh_profile_mode(self):
        """Re-evaluate profile mode and update dropdown if mode changed."""
        if self._destroyed:
            return
        new_mode = self._compute_profile_mode()
        if new_mode == self._use_profile_mode:
            return  # No change

        self._use_profile_mode = new_mode

        # Update label
        if self.model_label_widget:
            label_text = "Profile:" if self._use_profile_mode else "Model:"
            if HAVE_CTK:
                self.model_label_widget.configure(text=label_text)
            else:
                self.model_label_widget.configure(text=label_text)

        if self._use_profile_mode:
            # Switch to profile mode
            profile_names = self._get_profile_names()
            values = ["(Use Global)", *profile_names]
            self.model_dropdown.configure(values=values)
            self.model_dropdown.set(self.session.profile_override or "(Use Global)")
        else:
            # Switch to model mode — trigger model loading
            self.model_dropdown.configure(values=["(loading...)"])
            self.model_dropdown.set("(loading...)")
            threading.Thread(target=self._load_models, daemon=True).start()

    def _on_model_select(self, selected: str):
        """Handle model/profile selection — per-session, not global."""
        from ... import web_server

        if not selected or selected in ("(loading...)", "(no models)"):
            return

        if self._use_profile_mode:
            # Profile mode
            if selected == "(Use Global)":
                self.session.profile_override = None
                self.session.model_override = None
                self.selected_model = None
                self._update_status("✅ Using global settings", self.theme.accent_green)
            else:
                self.session.profile_override = selected
                self.session.model_override = None  # Profile handles model
                self.selected_model = None
                self._update_status(f"✅ Using profile: {selected}", self.theme.accent_green)
        else:
            # Model mode (original behavior)
            if selected.startswith("(Use Global"):
                # User selected the global sentinel — clear override
                self.session.model_override = None
                self.session.profile_override = None
                self.selected_model = None
                self._update_status("✅ Using global model", self.theme.accent_green)
            else:
                # User selected a specific model — set per-session override
                self.session.model_override = selected
                self.session.profile_override = None
                self.selected_model = selected
                self._update_status(f"✅ Session model: {selected}", self.theme.accent_green)

        # Update info label with new selection
        self._update_info_label()

        # Persist to session storage (not global config)
        add_session(self.session, web_server.CONFIG.get("max_sessions", 200))

    # =========================================================================
    # Clipboard
    # =========================================================================

    def _get_conversation_text(self) -> str:
        """Build conversation text for clipboard."""
        parts = []
        for msg in self.session.messages:
            role = "You" if msg["role"] == "user" else "Assistant"
            parts.append(f"[{role}]\n{msg['content']}\n")
        return "\n".join(parts)

    def _copy_all(self):
        text = self._get_conversation_text()
        if copy_to_clipboard(text, self.root):
            self._update_status("✅ Copied all!", self.theme.accent_green)
        else:
            self._update_status("✗ Failed to copy", self.theme.accent_red)

    def _copy_last(self):
        text = self.last_response
        if copy_to_clipboard(text, self.root):
            self._update_status("✅ Copied last response!", self.theme.accent_green)
        else:
            self._update_status("✗ Failed to copy", self.theme.accent_red)

    # =========================================================================
    # Regenerate Response
    # =========================================================================

    def _regenerate(self):
        """Regenerate the last response or generate response for last user message."""
        if self.is_loading or self._destroyed:
            return

        if not self.session.messages:
            self._update_status("No messages to regenerate")
            return

        last_msg = self.session.messages[-1]

        if last_msg["role"] == "assistant":
            # Delete last assistant message and regenerate
            self.session.messages.pop()
            # Save session after modifying messages
            from ... import web_server

            add_session(self.session, web_server.CONFIG.get("max_sessions", 200))
            self._update_chat_display(scroll_to_bottom=True)
            self._update_status("Regenerating response...")
        else:
            # Last message is user - just generate response
            self._update_status("Generating response...")

        # Trigger regeneration
        self._regenerate_response()

    def _regenerate_response(self, on_complete=None):
        """Internal method to regenerate without adding new user message.

        Args:
            on_complete: Optional callback invoked after successful response,
                        before display update. Used by _rerun_turn() to restore
                        saved messages via closure.
        """
        if self._destroyed:
            return

        # Disable input
        self.is_loading = True
        if HAVE_CTK:
            self.send_btn.configure(state="disabled")
            if hasattr(self, "regen_btn") and self.regen_btn:
                self.regen_btn.configure(state="disabled")
            if self.rename_btn:
                self.rename_btn.configure(state="disabled")
            if self.delete_btn:
                self.delete_btn.configure(state="disabled")
            self.input_text.configure(state="disabled")
            if self.attach_btn:
                self.attach_btn.configure(state="disabled")
        else:
            self.send_btn.configure(state=tk.DISABLED)
            if hasattr(self, "regen_btn") and self.regen_btn:
                self.regen_btn.configure(state=tk.DISABLED)
            if self.rename_btn:
                self.rename_btn.configure(state=tk.DISABLED)
            if self.delete_btn:
                self.delete_btn.configure(state=tk.DISABLED)
            self.input_text.configure(state=tk.DISABLED)
            if self.attach_btn:
                self.attach_btn.configure(state=tk.DISABLED)

        # Reset streaming state
        self.streaming_text = ""
        self.streaming_thinking = ""
        self.is_streaming = False
        self.last_usage = None

        def process_regeneration():
            from ... import web_server
            from ...profile_resolver import resolve_profile, resolve_profile_by_name
            from ...request_pipeline import RequestContext, RequestOrigin, RequestPipeline, StreamCallback

            # Always resolve profile to get a merged config with connection keys
            if self.session.profile_override:
                resolved = resolve_profile_by_name(
                    self.session.profile_override, web_server.CONFIG, web_server.AI_PARAMS, web_server.KEY_MANAGERS
                )
            else:
                resolved = resolve_profile(None, web_server.CONFIG, web_server.AI_PARAMS, web_server.KEY_MANAGERS)

            current_provider = resolved.provider
            current_model = self.session.model_override or resolved.model
            streaming_enabled = resolved.streaming
            thinking_enabled = resolved.thinking_enabled
            effective_config = resolved.config
            effective_ai_params = resolved.ai_params
            effective_key_managers = resolved.key_managers

            # Manual mode: apply per-session provider override
            if self.session.provider_override:
                current_provider = self.session.provider_override
                # Update effective config so downstream provider resolution works
                effective_config["default_provider"] = current_provider
                if current_model:
                    effective_config[f"{current_provider}_model"] = current_model

            ctx = RequestContext(
                origin=RequestOrigin.CHAT_WINDOW,
                provider=current_provider,
                model=current_model,
                streaming=streaming_enabled,
                thinking_enabled=thinking_enabled,
                session_id=str(self.session.session_id),
            )

            def on_text(content):
                if self._destroyed:
                    return
                self.streaming_text += content
                self._safe_after(0, self._update_streaming_display)

            def on_thinking(content):
                if self._destroyed:
                    return
                self.streaming_thinking += content
                self._safe_after(0, self._update_streaming_display)

            def on_usage(content):
                self.last_usage = content

            def on_error(content):
                if self._destroyed:
                    return
                self._safe_after(0, lambda: self._update_status(f"Error: {content}", self.theme.accent_red))

            callbacks = StreamCallback(on_text=on_text, on_thinking=on_thinking, on_usage=on_usage, on_error=on_error)

            self.is_streaming = True
            self._safe_after(0, lambda: self._update_status("Streaming..." if streaming_enabled else "Processing..."))

            if streaming_enabled and current_provider in ("custom", "google", "openrouter"):
                ctx = RequestPipeline.execute_streaming(
                    ctx, self.session, effective_config, effective_ai_params, effective_key_managers, callbacks
                )
            else:
                self.is_streaming = False
                messages = self.session.get_conversation_for_api(include_image=True)
                ctx = RequestPipeline.execute_simple(
                    ctx, messages, effective_config, effective_ai_params, effective_key_managers
                )

            self.is_streaming = False
            self.last_usage = {
                "prompt_tokens": ctx.input_tokens,
                "completion_tokens": ctx.output_tokens,
                "total_tokens": ctx.total_tokens,
                "estimated": ctx.estimated,
            }

            if self._destroyed:
                return

            def handle_response():
                if self._destroyed:
                    return

                if ctx.error:
                    self._update_status(f"Error: {ctx.error}", self.theme.accent_red)
                else:
                    self.session.add_message("assistant", ctx.response_text, gemini_parts=ctx.gemini_parts)
                    thinking_content = self.streaming_thinking or ctx.reasoning_text
                    if thinking_content and len(self.session.messages) > 0:
                        self.session.messages[-1]["thinking"] = thinking_content

                    # Auto-collapse thinking after streaming finishes
                    msg_idx = len(self.session.messages) - 1
                    if msg_idx in self.thinking_collapsed_states:
                        self.thinking_collapsed_states[msg_idx] = True

                    self.last_response = ctx.response_text

                # Always restore saved messages (rerun turn) — even on error
                # so subsequent messages are never permanently lost.
                # Pass success flag so closure can also restore the original
                # assistant message on failure.
                if on_complete:
                    on_complete(success=not ctx.error)

                # Always refresh display — on success to show new response,
                # on error to restore the original conversation state
                self._update_chat_display(scroll_to_bottom=True)

                if not ctx.error:
                    usage_str = ""
                    if self.last_usage:
                        usage_str = f" | {self.last_usage.get('total_tokens', 0)} tokens"

                    self._update_status(f"✅ Regenerated{usage_str}", self.theme.accent_green)

                add_session(self.session, web_server.CONFIG.get("max_sessions", 200))

                self.is_loading = False
                if HAVE_CTK:
                    self.send_btn.configure(state="normal")
                    if hasattr(self, "regen_btn") and self.regen_btn:
                        self.regen_btn.configure(state="normal")
                    if self.rename_btn:
                        self.rename_btn.configure(state="normal")
                    if self.delete_btn:
                        self.delete_btn.configure(state="normal")
                    self.input_text.configure(state="normal")
                    if self.attach_btn:
                        self.attach_btn.configure(state="normal")
                else:
                    self.send_btn.configure(state=tk.NORMAL)
                    if hasattr(self, "regen_btn") and self.regen_btn:
                        self.regen_btn.configure(state=tk.NORMAL)
                    if self.rename_btn:
                        self.rename_btn.configure(state=tk.NORMAL)
                    if self.delete_btn:
                        self.delete_btn.configure(state=tk.NORMAL)
                    self.input_text.configure(state=tk.NORMAL)
                    if self.attach_btn:
                        self.attach_btn.configure(state=tk.NORMAL)

                self.streaming_text = ""
                self.streaming_thinking = ""

            self._safe_after(0, handle_response)

        threading.Thread(target=process_regeneration, daemon=True).start()

    # =========================================================================
    # Attachment Handling
    # =========================================================================

    def _on_paste(self, event):
        """Handle Ctrl+V: attach clipboard image if present, otherwise allow normal text paste."""
        try:
            from PIL import ImageGrab

            clip = ImageGrab.grabclipboard()

            if clip is None:
                # No image in clipboard — fall through to default text paste
                return None

            # Case 1: PIL Image (bitmap from clipboard — screenshot, snip, etc.)
            if hasattr(clip, "save"):
                import os
                import tempfile

                # Save clipboard image to a temp .png file
                fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="clipboard_")
                os.close(fd)
                clip.save(tmp_path, "PNG")
                self._clipboard_temp_files.append(tmp_path)
                self._add_pending_attachment(tmp_path)

                # Clear placeholder text if still showing
                if self._has_placeholder:
                    if HAVE_CTK:
                        self.input_text.delete("0.0", "end")
                        self.input_text.configure(text_color=self.theme.fg)
                    else:
                        self.input_text.delete("1.0", tk.END)
                        self.input_text.configure(fg=self.colors["fg"])
                    self._has_placeholder = False

                return "break"  # Consume the event — don't paste image as text

            # Case 2: List of file paths (files copied from Explorer)
            if isinstance(clip, list):
                image_exts = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
                audio_exts = {"wav", "mp3", "ogg", "opus", "flac", "webm", "m4a"}
                other_exts = {"pdf"}
                supported_exts = image_exts | audio_exts | other_exts

                added = False
                for fpath in clip:
                    if isinstance(fpath, str):
                        ext = fpath.rsplit(".", 1)[-1].lower() if "." in fpath else ""
                        if ext in supported_exts:
                            self._add_pending_attachment(fpath)
                            added = True

                if added:
                    # Clear placeholder text if still showing
                    if self._has_placeholder:
                        if HAVE_CTK:
                            self.input_text.delete("0.0", "end")
                            self.input_text.configure(text_color=self.theme.fg)
                        else:
                            self.input_text.delete("1.0", tk.END)
                            self.input_text.configure(fg=self.colors["fg"])
                        self._has_placeholder = False
                    return "break"

        except Exception as e:
            print(f"[ChatWindow] Clipboard paste check failed: {e}")

        # Fall through to default text paste behavior
        return None

    def _on_attach_click(self):
        """Open file selector for attachments."""
        from tkinter import filedialog

        filetypes = [
            ("Images", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
            ("Audio", "*.wav *.mp3 *.ogg *.opus *.flac *.webm *.m4a"),
            (
                "All supported",
                "*.png *.jpg *.jpeg *.gif *.webp *.bmp *.pdf *.wav *.mp3 *.ogg *.opus *.flac *.webm *.m4a",
            ),
            ("All files", "*.*"),
        ]

        files = filedialog.askopenfilenames(title="Select file(s) to attach", filetypes=filetypes, parent=self.root)

        if files:
            for file_path in files:
                self._add_pending_attachment(file_path)

    def _add_pending_attachment(self, file_path: str):
        """Add file to pending attachments with thumbnail preview."""
        import os
        from pathlib import Path

        path = Path(file_path)
        if not path.exists():
            self._update_status(f"File not found: {path.name}")
            return

        # Check if already added
        for attach in self.pending_attachments:
            if attach.get("source_path") == file_path:
                self._update_status(f"Already attached: {path.name}")
                return

        # Determine MIME type
        ext = path.suffix.lower().lstrip(".")
        mime_map = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "webp": "image/webp",
            "bmp": "image/bmp",
            "pdf": "application/pdf",
            "wav": "audio/wav",
            "mp3": "audio/mpeg",
            "ogg": "audio/ogg",
            "opus": "audio/opus",
            "flac": "audio/flac",
            "webm": "audio/webm",
            "m4a": "audio/mp4",
        }
        mime_type = mime_map.get(ext, "application/octet-stream")

        # Create thumbnail for preview (if it's an image)
        thumbnail = None
        if mime_type.startswith("image/"):
            try:
                from PIL import Image, ImageTk

                with Image.open(file_path) as img:
                    # Create thumbnail (max 48x48)
                    img.thumbnail((48, 48), Image.Resampling.LANCZOS)
                    thumbnail = ImageTk.PhotoImage(img)
                    self._attachment_thumbnails.append(thumbnail)  # Keep reference
            except Exception as e:
                print(f"[ChatWindow] Failed to create thumbnail: {e}")

        # For audio files, we'll use a speaker emoji icon indicator
        is_audio = mime_type.startswith("audio/")

        # Add to pending list
        attach_info = {
            "source_path": file_path,
            "filename": path.name,
            "mime_type": mime_type,
            "thumbnail": thumbnail,
            "is_audio": is_audio,
        }
        self.pending_attachments.append(attach_info)

        # Update UI
        self._update_attachments_display()
        self._update_status(f"Attached: {path.name}")

    def _remove_pending_attachment(self, index: int):
        """Remove attachment from pending list."""
        if 0 <= index < len(self.pending_attachments):
            removed = self.pending_attachments.pop(index)
            self._update_attachments_display()
            self._update_status(f"Removed: {removed.get('filename', 'attachment')}")

    def _clear_pending_attachments(self):
        """Clear all pending attachments after sending."""
        self.pending_attachments.clear()
        self._attachment_thumbnails.clear()
        self._update_attachments_display()

    def _render_message_attachments(self, attachments: List[Dict], message_tag: str):
        """Render attachment thumbnails inline in chat for a message."""
        if not attachments:
            return

        try:
            from PIL import Image, ImageTk

            from ...attachment_manager import AttachmentManager
        except ImportError:
            return

        for attach in attachments:
            file_path = attach.get("path", "")
            if not file_path:
                continue

            mime_type = attach.get("mime_type", "")
            filename = attach.get("filename", "attachment")

            # Handle audio files with inline player
            if mime_type.startswith("audio/"):
                self._render_audio_player(file_path, filename, message_tag)
                continue

            # Handle non-image files
            if not mime_type.startswith("image/"):
                # Show file icon for non-images
                self.chat_text.insert(tk.END, "  📎 ", (message_tag,))
                self.chat_text.insert(tk.END, f"{filename}\n", ("normal", message_tag))
                continue

            try:
                # Load and create thumbnail for images
                b64, _mime = AttachmentManager.load_image(file_path)
                if not b64:
                    continue

                import base64
                import io

                image_data = base64.b64decode(b64)
                with io.BytesIO(image_data) as buffer:
                    img = Image.open(buffer)
                    # Create thumbnail (max 150x150 for chat display)
                    img.thumbnail((150, 150), Image.Resampling.LANCZOS)
                    thumbnail = ImageTk.PhotoImage(img)

                # Store reference to prevent garbage collection
                if not hasattr(self, "_chat_thumbnails"):
                    self._chat_thumbnails = []
                self._chat_thumbnails.append(thumbnail)

                # Create unique tag for this image
                img_tag = f"img_{id(thumbnail)}"

                # Insert indentation
                self.chat_text.insert(tk.END, "  ", (message_tag,))

                # Insert image
                self.chat_text.image_create(tk.END, image=thumbnail)

                # Add image tag for click handling
                current_pos = self.chat_text.index(tk.INSERT)
                line = int(current_pos.split(".")[0])
                img_start = f"{line}.2"  # After the indentation
                img_end = f"{line}.3"
                self.chat_text.tag_add(img_tag, img_start, img_end)

                # Bind click events
                self.chat_text.tag_bind(
                    img_tag, "<Button-1>", lambda e, path=file_path: self._on_image_left_click(e, path)
                )
                self.chat_text.tag_bind(
                    img_tag, "<Button-3>", lambda e, path=file_path: self._on_image_right_click(e, path)
                )
                self.chat_text.tag_bind(img_tag, "<Enter>", lambda e: self.chat_text.config(cursor="hand2"))
                self.chat_text.tag_bind(img_tag, "<Leave>", lambda e: self.chat_text.config(cursor=""))

                # Add newline after image
                self.chat_text.insert(tk.END, "\n", (message_tag,))

            except Exception as e:
                print(f"[ChatWindow] Failed to render attachment: {e}")
                self.chat_text.insert(tk.END, f"  📎 {filename}\n", ("normal", message_tag))

    def _render_audio_player(self, file_path: str, filename: str, message_tag: str):
        """Render an inline audio player widget in the chat."""
        import os

        # Create a frame for the audio player
        if HAVE_CTK:
            player_frame = ctk.CTkFrame(self.chat_text, fg_color=self.theme.surface0, corner_radius=6, height=36)
        else:
            player_frame = tk.Frame(self.chat_text, bg=self.colors["surface0"], height=36)

        # Keep reference to prevent GC
        if not hasattr(self, "_audio_player_frames"):
            self._audio_player_frames = []
        self._audio_player_frames.append(player_frame)

        # Speaker icon
        if HAVE_CTK:
            icon_label = ctk.CTkLabel(player_frame, text="🔊", font=get_ctk_font(size=14), width=24)
            icon_label.pack(side="left", padx=(8, 4))

            # Filename (truncated)
            display_name = filename[:30] + "..." if len(filename) > 30 else filename
            name_label = ctk.CTkLabel(
                player_frame, text=display_name, font=get_ctk_font(size=11), text_color=self.theme.fg
            )
            name_label.pack(side="left", padx=4)

            # Play/Stop button
            play_btn = ctk.CTkButton(
                player_frame,
                text="▶",
                font=get_ctk_font(size=12),
                width=32,
                height=24,
                corner_radius=4,
                fg_color=self.theme.accent,
                hover_color=self.theme.surface1,
                command=lambda p=file_path: self._toggle_audio(p),
            )
            play_btn.pack(side="left", padx=4)

            # Store button reference for toggling
            self._audio_play_buttons[file_path] = play_btn

            # Open externally button
            open_btn = ctk.CTkButton(
                player_frame,
                text="📂",
                font=get_ctk_font(size=12),
                width=32,
                height=24,
                corner_radius=4,
                fg_color=self.theme.surface1,
                hover_color=self.theme.overlay0,
                command=lambda p=file_path: self._open_file_external(p),
            )
            open_btn.pack(side="left", padx=(0, 8))
        else:
            icon_label = tk.Label(
                player_frame, text="🔊", font=("Segoe UI", 12), bg=self.colors["surface0"], fg=self.colors["fg"]
            )
            icon_label.pack(side=tk.LEFT, padx=(8, 4))

            display_name = filename[:30] + "..." if len(filename) > 30 else filename
            name_label = tk.Label(
                player_frame, text=display_name, font=("Segoe UI", 10), bg=self.colors["surface0"], fg=self.colors["fg"]
            )
            name_label.pack(side=tk.LEFT, padx=4)

            play_btn = tk.Button(
                player_frame,
                text="▶",
                font=("Segoe UI", 10),
                bg=self.colors["accent"],
                fg=self.colors["accent_fg"],
                relief=tk.FLAT,
                width=3,
                command=lambda p=file_path: self._toggle_audio(p),
                cursor="hand2",
            )
            play_btn.pack(side=tk.LEFT, padx=4)

            # Store button reference for toggling
            self._audio_play_buttons[file_path] = play_btn

            open_btn = tk.Button(
                player_frame,
                text="📂",
                font=("Segoe UI", 10),
                bg=self.colors["surface0"],
                fg=self.colors["fg"],
                relief=tk.FLAT,
                width=3,
                command=lambda p=file_path: self._open_file_external(p),
                cursor="hand2",
            )
            open_btn.pack(side=tk.LEFT, padx=(0, 8))

        # Insert the frame into the text widget
        self.chat_text.insert(tk.END, "  ", (message_tag,))
        self.chat_text.window_create(tk.END, window=player_frame)
        self.chat_text.insert(tk.END, "\n", (message_tag,))

    def _toggle_audio(self, file_path: str):
        """Toggle audio playback - play if stopped, stop if playing."""
        import os

        if not os.path.exists(file_path):
            self._update_status("Audio file not found")
            return

        # Check if this file is currently playing
        if self._audio_playing_path == file_path:
            # Stop playback
            self._stop_audio()
            return

        # If another file is playing, stop it first
        if self._audio_playing_path:
            self._stop_audio()

        # Start playing this file
        try:
            from ...audio.recorder import AudioRecorder

            if not hasattr(self, "_audio_recorder"):
                self._audio_recorder = AudioRecorder()

            # Read the audio file
            with open(file_path, "rb") as f:
                audio_data = f.read()

            self._audio_recorder.play(audio_data)
            self._audio_playing_path = file_path

            # Update button to show stop icon
            btn = self._audio_play_buttons.get(file_path)
            if btn:
                if HAVE_CTK:
                    btn.configure(text="■", fg_color=self.theme.accent_red)
                else:
                    btn.configure(text="■", bg=self.colors.get("accent_red", "#f38ba8"))

            self._update_status(f"Playing: {os.path.basename(file_path)}")

        except Exception as e:
            print(f"[ChatWindow] AudioRecorder playback failed: {e}")
            # Fallback to system player
            self._open_file_external(file_path)

    def _stop_audio(self):
        """Stop current audio playback and reset button state."""
        if not self._audio_playing_path:
            return

        try:
            if hasattr(self, "_audio_recorder"):
                self._audio_recorder.stop_playback()
        except Exception as e:
            print(f"[ChatWindow] Failed to stop audio: {e}")

        # Reset button to play icon
        btn = self._audio_play_buttons.get(self._audio_playing_path)
        if btn:
            if HAVE_CTK:
                btn.configure(text="▶", fg_color=self.theme.accent)
            else:
                btn.configure(text="▶", bg=self.colors["accent"])

        self._update_status("Playback stopped")
        self._audio_playing_path = None

    def _open_file_external(self, file_path: str):
        """Open file in system default application."""
        import os
        import subprocess
        import sys

        if not os.path.exists(file_path):
            self._update_status("File not found")
            return

        try:
            if sys.platform == "win32":
                os.startfile(file_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", file_path])
            else:
                subprocess.run(["xdg-open", file_path])
            self._update_status(f"Opened: {os.path.basename(file_path)}")
        except Exception as e:
            print(f"[ChatWindow] Failed to open file: {e}")
            self._update_status("Failed to open file")

    def _on_image_left_click(self, event, file_path: str):
        """Show enlarged image in a modal window on left click."""
        try:
            import base64
            import io

            from PIL import Image, ImageTk

            from ...attachment_manager import AttachmentManager

            # Load full image
            b64, _mime = AttachmentManager.load_image(file_path)
            if not b64:
                return

            image_data = base64.b64decode(b64)
            with io.BytesIO(image_data) as buffer:
                img = Image.open(buffer)
                orig_width, orig_height = img.size

                # Scale to fit screen (max 80% of screen size)
                if self.root:
                    screen_w = self.root.winfo_screenwidth()
                    screen_h = self.root.winfo_screenheight()
                    max_w = int(screen_w * 0.8)
                    max_h = int(screen_h * 0.8)

                    if orig_width > max_w or orig_height > max_h:
                        img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

                photo = ImageTk.PhotoImage(img)

            # Create modal window (withdraw first to prevent white titlebar flash)
            if HAVE_CTK:
                modal = ctk.CTkToplevel(self.root)
                modal.withdraw()
                modal.configure(fg_color=self.theme.bg)
            else:
                modal = tk.Toplevel(self.root)
                modal.withdraw()
                modal.configure(bg=self.colors["bg"])

            modal.title("Image Preview")
            modal.transient(self.root)
            set_window_icon(modal)
            set_dark_titlebar(modal)

            # Center on screen
            w = photo.width() + 20
            h = photo.height() + 60
            x = (self.root.winfo_screenwidth() - w) // 2
            y = (self.root.winfo_screenheight() - h) // 2
            modal.geometry(f"{w}x{h}+{x}+{y}")
            modal.deiconify()

            # Display image
            img_label = tk.Label(modal, image=photo, bg=self.theme.bg if HAVE_CTK else self.colors["bg"])
            img_label.image = photo  # Keep reference
            img_label.pack(padx=10, pady=10)

            # Close button
            if HAVE_CTK:
                close_btn = ctk.CTkButton(
                    modal, text="Close", command=modal.destroy, **get_ctk_button_colors(self.theme, "secondary")
                )
                close_btn.pack(pady=(0, 10))
            else:
                close_btn = tk.Button(
                    modal, text="Close", command=modal.destroy, bg=self.colors["button_bg"], fg=self.colors["fg"]
                )
                close_btn.pack(pady=(0, 10))

            # Close on click or Escape
            modal.bind("<Button-1>", lambda e: modal.destroy() if e.widget == modal else None)
            modal.bind("<Escape>", lambda e: modal.destroy())

            modal.focus_set()

        except Exception as e:
            print(f"[ChatWindow] Failed to show image preview: {e}")

    def _on_image_right_click(self, event, file_path: str):
        """Open image in system default viewer on right click."""
        import os
        import subprocess
        import sys

        if not os.path.exists(file_path):
            self._update_status("Image file not found")
            return

        try:
            if sys.platform == "win32":
                os.startfile(file_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", file_path])
            else:
                subprocess.run(["xdg-open", file_path])
            self._update_status("Opened in external viewer")
        except Exception as e:
            print(f"[ChatWindow] Failed to open image: {e}")
            self._update_status("Failed to open image")

    def _update_attachments_display(self):
        """Update the attachments preview frame."""
        if not self.attachments_frame:
            return

        # Clear existing preview
        for widget in self.attachments_frame.winfo_children():
            widget.destroy()

        if not self.pending_attachments:
            self.attachments_frame.grid_remove()
            if hasattr(self, "_attachments_label") and self._attachments_label:
                if HAVE_CTK:
                    self._attachments_label.configure(text="")
                else:
                    self._attachments_label.configure(text="")
                self._attachments_label.grid_remove()  # Hide label
            return

        # Show frame
        self.attachments_frame.grid()

        # Update header label
        count = len(self.pending_attachments)
        label_text = f"📎 {count} file{'s' if count > 1 else ''} attached"
        if hasattr(self, "_attachments_label") and self._attachments_label:
            if HAVE_CTK:
                self._attachments_label.configure(text=label_text)
            else:
                self._attachments_label.configure(text=label_text)
            self._attachments_label.grid(row=1, column=0, sticky="w", padx=5)  # Show label

        # Create preview items
        if HAVE_CTK:
            for i, attach in enumerate(self.pending_attachments):
                item_frame = ctk.CTkFrame(self.attachments_frame, fg_color=self.theme.surface0, corner_radius=6)
                item_frame.pack(side="left", padx=2, pady=2)

                # Thumbnail or icon
                if attach.get("thumbnail"):
                    # Use tk.Label for image (CTkLabel doesn't handle PhotoImage well with transparency)
                    thumb_label = tk.Label(item_frame, image=attach["thumbnail"], bg=self.theme.surface0)
                    thumb_label.pack(side="left", padx=4, pady=4)
                else:
                    ctk.CTkLabel(item_frame, text="📄", font=get_ctk_font(size=20)).pack(side="left", padx=4, pady=4)

                # Filename (truncated)
                name = attach.get("filename", "file")[:20]
                if len(attach.get("filename", "")) > 20:
                    name += "..."
                ctk.CTkLabel(item_frame, text=name, font=get_ctk_font(size=10), text_color=self.theme.fg).pack(
                    side="left", padx=2
                )

                # Remove button
                remove_btn = ctk.CTkButton(
                    item_frame,
                    text="×",
                    width=20,
                    height=20,
                    font=get_ctk_font(size=12),
                    corner_radius=4,
                    fg_color="transparent",
                    hover_color=self.theme.accent_red,
                    command=lambda idx=i: self._remove_pending_attachment(idx),
                )
                remove_btn.pack(side="left", padx=2)
        else:
            for i, attach in enumerate(self.pending_attachments):
                item_frame = tk.Frame(self.attachments_frame, bg=self.colors["surface0"])
                item_frame.pack(side=tk.LEFT, padx=2, pady=2)

                # Thumbnail or icon
                if attach.get("thumbnail"):
                    thumb_label = tk.Label(item_frame, image=attach["thumbnail"], bg=self.colors["surface0"])
                    thumb_label.pack(side=tk.LEFT, padx=4, pady=4)
                else:
                    tk.Label(
                        item_frame, text="📄", font=("Segoe UI", 16), bg=self.colors["surface0"], fg=self.colors["fg"]
                    ).pack(side=tk.LEFT, padx=4, pady=4)

                # Filename
                name = attach.get("filename", "file")[:20]
                if len(attach.get("filename", "")) > 20:
                    name += "..."
                tk.Label(
                    item_frame, text=name, font=("Segoe UI", 9), bg=self.colors["surface0"], fg=self.colors["fg"]
                ).pack(side=tk.LEFT, padx=2)

                # Remove button
                remove_btn = tk.Button(
                    item_frame,
                    text="×",
                    font=("Segoe UI", 10),
                    bg=self.colors["surface0"],
                    fg=self.colors["fg"],
                    relief=tk.FLAT,
                    cursor="hand2",
                    command=lambda idx=i: self._remove_pending_attachment(idx),
                )
                remove_btn.pack(side=tk.LEFT, padx=2)

    # =========================================================================
    # Send Message
    # =========================================================================

    def _send(self):
        """Send a message with streaming support and attachment handling."""
        if self.is_loading or self._destroyed:
            return

        if HAVE_CTK:
            user_input = self.input_text.get("0.0", "end-1c").strip()
        else:
            user_input = self.input_text.get("1.0", tk.END).strip()

        placeholder = self._placeholder

        if not user_input or user_input == placeholder:
            self._update_status("Please enter a message")
            return

        # Capture pending attachments and temp files before clearing
        attachments_to_send = list(self.pending_attachments)
        clipboard_temps_to_clean = list(self._clipboard_temp_files)
        self._clipboard_temp_files.clear()

        # Disable input
        self.is_loading = True
        if HAVE_CTK:
            self.send_btn.configure(state="disabled")
            if self.rename_btn:
                self.rename_btn.configure(state="disabled")
            if self.delete_btn:
                self.delete_btn.configure(state="disabled")
            self.input_text.configure(state="disabled")
            if self.attach_btn:
                self.attach_btn.configure(state="disabled")
        else:
            self.send_btn.configure(state=tk.DISABLED)
            if self.rename_btn:
                self.rename_btn.configure(state=tk.DISABLED)
            if self.delete_btn:
                self.delete_btn.configure(state=tk.DISABLED)
            self.input_text.configure(state=tk.DISABLED)
            if self.attach_btn:
                self.attach_btn.configure(state=tk.DISABLED)
        self._update_status("Sending...")

        # Clear pending attachments from UI
        self._clear_pending_attachments()

        # Reset streaming state
        self.streaming_text = ""
        self.streaming_thinking = ""
        self.is_streaming = False
        self.last_usage = None

        def process_message():
            from ... import web_server
            from ...attachment_manager import AttachmentManager
            from ...request_pipeline import RequestContext, RequestOrigin, RequestPipeline, StreamCallback

            # Process attachments: save to storage and build attachment list
            message_attachments = []
            message_index = len(self.session.messages)

            for attach in attachments_to_send:
                source_path = attach.get("source_path")
                if source_path:
                    # Save file to session attachments
                    saved_path = AttachmentManager.save_file(
                        session_id=self.session.session_id, file_path=source_path, message_index=message_index
                    )
                    if saved_path:
                        message_attachments.append(
                            {
                                "path": saved_path,
                                "mime_type": attach.get("mime_type", "application/octet-stream"),
                                "filename": attach.get("filename", "attachment"),
                            }
                        )

            # Clean up clipboard temp files now that save_file() has copied them
            import os

            for tmp in clipboard_temps_to_clean:
                try:
                    os.remove(tmp)
                except OSError:
                    pass

            # Add message with attachments
            self.session.add_message("user", user_input, attachments=message_attachments)

            # Save session immediately after adding user message (allows retry on failure)
            add_session(self.session, web_server.CONFIG.get("max_sessions", 200))

            # Update display and clear input
            def update_ui():
                self._update_chat_display(scroll_to_bottom=True)
                if HAVE_CTK:
                    self.input_text.configure(state="normal")
                    self.input_text.delete("0.0", "end")
                else:
                    self.input_text.configure(state=tk.NORMAL)
                    self.input_text.delete("1.0", tk.END)

            self._safe_after(0, update_ui)

            from ...profile_resolver import resolve_profile, resolve_profile_by_name

            # Always resolve profile to get a merged config with connection keys
            if self.session.profile_override:
                resolved = resolve_profile_by_name(
                    self.session.profile_override, web_server.CONFIG, web_server.AI_PARAMS, web_server.KEY_MANAGERS
                )
            else:
                resolved = resolve_profile(None, web_server.CONFIG, web_server.AI_PARAMS, web_server.KEY_MANAGERS)

            current_provider = resolved.provider
            current_model = self.session.model_override or resolved.model
            streaming_enabled = resolved.streaming
            thinking_enabled = resolved.thinking_enabled
            effective_config = resolved.config
            effective_ai_params = resolved.ai_params
            effective_key_managers = resolved.key_managers

            # Manual mode: apply per-session provider override
            if self.session.provider_override:
                current_provider = self.session.provider_override
                # Update effective config so downstream provider resolution works
                effective_config["default_provider"] = current_provider
                if current_model:
                    effective_config[f"{current_provider}_model"] = current_model

            ctx = RequestContext(
                origin=RequestOrigin.CHAT_WINDOW,
                provider=current_provider,
                model=current_model,
                streaming=streaming_enabled,
                thinking_enabled=thinking_enabled,
                session_id=str(self.session.session_id),
            )

            def on_text(content):
                if self._destroyed:
                    return
                self.streaming_text += content
                self._safe_after(0, self._update_streaming_display)

            def on_thinking(content):
                if self._destroyed:
                    return
                self.streaming_thinking += content
                self._safe_after(0, self._update_streaming_display)

            def on_usage(content):
                self.last_usage = content

            def on_error(content):
                if self._destroyed:
                    return
                self._safe_after(0, lambda: self._update_status(f"Error: {content}", self.theme.accent_red))

            callbacks = StreamCallback(on_text=on_text, on_thinking=on_thinking, on_usage=on_usage, on_error=on_error)

            self.is_streaming = True
            self._safe_after(0, lambda: self._update_status("Streaming..." if streaming_enabled else "Processing..."))

            if streaming_enabled and current_provider in ("custom", "google", "openrouter"):
                ctx = RequestPipeline.execute_streaming(
                    ctx, self.session, effective_config, effective_ai_params, effective_key_managers, callbacks
                )
            else:
                self.is_streaming = False
                messages = self.session.get_conversation_for_api(include_image=True)
                ctx = RequestPipeline.execute_simple(
                    ctx, messages, effective_config, effective_ai_params, effective_key_managers
                )

            self.is_streaming = False
            self.last_usage = {
                "prompt_tokens": ctx.input_tokens,
                "completion_tokens": ctx.output_tokens,
                "total_tokens": ctx.total_tokens,
                "estimated": ctx.estimated,
            }

            if self._destroyed:
                return

            def handle_response():
                if self._destroyed:
                    return

                if ctx.error:
                    self._update_status(f"Error: {ctx.error}", self.theme.accent_red)
                    # Don't pop user message - keep it for retry via Regen button
                else:
                    self.session.add_message("assistant", ctx.response_text, gemini_parts=ctx.gemini_parts)
                    thinking_content = self.streaming_thinking or ctx.reasoning_text
                    if thinking_content and len(self.session.messages) > 0:
                        self.session.messages[-1]["thinking"] = thinking_content

                    # Auto-collapse thinking after streaming finishes
                    msg_idx = len(self.session.messages) - 1
                    if msg_idx in self.thinking_collapsed_states:
                        self.thinking_collapsed_states[msg_idx] = True

                    self.last_response = ctx.response_text
                    self._update_chat_display(scroll_to_bottom=True)

                    usage_str = ""
                    if self.last_usage:
                        usage_str = f" | {self.last_usage.get('total_tokens', 0)} tokens"

                    self._update_status(f"✅ Response received{usage_str}", self.theme.accent_green)
                    add_session(self.session, web_server.CONFIG.get("max_sessions", 200))

                self.is_loading = False
                if HAVE_CTK:
                    self.send_btn.configure(state="normal")
                    if self.rename_btn:
                        self.rename_btn.configure(state="normal")
                    if self.delete_btn:
                        self.delete_btn.configure(state="normal")
                    self.input_text.configure(state="normal")
                    if self.attach_btn:
                        self.attach_btn.configure(state="normal")
                else:
                    self.send_btn.configure(state=tk.NORMAL)
                    if self.rename_btn:
                        self.rename_btn.configure(state=tk.NORMAL)
                    if self.delete_btn:
                        self.delete_btn.configure(state=tk.NORMAL)
                    self.input_text.configure(state=tk.NORMAL)
                    if self.attach_btn:
                        self.attach_btn.configure(state=tk.NORMAL)

                self.streaming_text = ""
                self.streaming_thinking = ""

            self._safe_after(0, handle_response)

        threading.Thread(target=process_message, daemon=True).start()

    # =========================================================================
    # Message Editing & Context Menu
    # =========================================================================

    def _get_message_index_at(self, event) -> Optional[int]:
        """Get message index from click position by checking msg_N tags."""
        try:
            index = self.chat_text.index(f"@{event.x},{event.y}")
            tags = self.chat_text.tag_names(index)
            for tag in tags:
                if tag.startswith("msg_"):
                    try:
                        return int(tag[4:])
                    except ValueError:
                        pass
        except tk.TclError:
            pass
        return None

    def _save_and_refresh(self):
        """Save session and refresh display after mutation."""
        from ... import web_server

        add_session(self.session, web_server.CONFIG.get("max_sessions", 200))
        self._update_chat_display(preserve_scroll=True)

    def _on_chat_right_click(self, event):
        """Handle right-click on chat text for context menu."""
        # Don't show context menu when right-clicking on inline images
        # (they have their own <Button-3> handler via img_ tags)
        try:
            pos = self.chat_text.index(f"@{event.x},{event.y}")
            tags = self.chat_text.tag_names(pos)
            for tag in tags:
                if tag.startswith("img_"):
                    return
        except tk.TclError:
            pass

        index = self._get_message_index_at(event)
        if index is not None:
            self._show_message_context_menu(event, index)

    def _show_message_context_menu(self, event, index: int):
        """Show context menu for a specific message."""
        if self.is_loading or index >= len(self.session.messages):
            return

        msg = self.session.messages[index]
        role = msg["role"]
        is_user = role == "user"

        # Theme the context menu to match the chat window
        menu = tk.Menu(
            self.root,
            tearoff=0,
            bg=self.colors.get("surface0", self.colors.get("bg", "#1e1e2e")),
            fg=self.colors.get("fg", "#cdd6f4"),
            activebackground=self.colors.get("accent", "#89b4fa"),
            activeforeground=self.colors.get("bg", "#1e1e2e"),
            relief=tk.FLAT,
            borderwidth=1,
            font=("Segoe UI", 10),
        )

        label_edit = "Edit Message" if is_user else "Edit Response"
        label_copy = "Copy Message" if is_user else "Copy Response"
        label_delete = "Delete Message" if is_user else "Delete Response"

        menu.add_command(label=f"  {label_edit}", command=lambda: self._edit_message(index))
        menu.add_command(label="  Rerun This Turn", command=lambda: self._rerun_turn(index))
        menu.add_command(label=f"  {label_copy}", command=lambda: self._copy_message(index))
        menu.add_separator()
        menu.add_command(label=f"  {label_delete}", command=lambda: self._delete_message(index))
        menu.add_command(label="  Delete From Here", command=lambda: self._delete_from_here(index))
        menu.add_command(label="  Branch From Here", command=lambda: self._branch_from_here(index))

        try:
            menu.post(event.x_root, event.y_root)
        except (tk.TclError, AttributeError):
            # Fallback for events without x_root/y_root
            x = self.chat_text.winfo_rootx() + event.x
            y = self.chat_text.winfo_rooty() + event.y
            menu.post(x, y)

    def _delete_message(self, index: int):
        """Delete a single message from the session."""
        if self.is_loading:
            return
        if 0 <= index < len(self.session.messages):
            self.session.messages.pop(index)
            self._save_and_refresh()
            self._update_status("Message deleted")

    def _delete_from_here(self, index: int):
        """Delete the target message and all subsequent messages."""
        if self.is_loading:
            return
        if 0 <= index < len(self.session.messages):
            count = len(self.session.messages) - index
            if count > 1:
                from tkinter import messagebox

                if not messagebox.askyesno(
                    "Confirm Delete", f"Delete {count} messages from here to end?", parent=self.root
                ):
                    return
            self.session.messages = self.session.messages[:index]
            self._save_and_refresh()
            self._update_status(f"Deleted {count} message(s)")

    def _copy_message(self, index: int):
        """Copy a single message's content to clipboard."""
        if 0 <= index < len(self.session.messages):
            content = self.session.messages[index]["content"]
            if copy_to_clipboard(content, self.root):
                self._update_status("✅ Copied!", self.theme.accent_green)
            else:
                self._update_status("✗ Failed to copy", self.theme.accent_red)

    def _edit_message(self, index: int):
        """Open modal dialog to edit a message's content."""
        if self.is_loading or index >= len(self.session.messages):
            return

        msg = self.session.messages[index]
        dialog = _EditMessageDialog(self.root, msg, self.theme, self.colors)

        if dialog.result is None:
            return

        action, new_text = dialog.result
        self.session.messages[index]["content"] = new_text

        if action == "save":
            self._save_and_refresh()
            self._update_status("✅ Message edited", self.theme.accent_green)
        elif action == "save_rerun":
            self._rerun_turn(index)

    def _rerun_turn(self, index: int):
        """Rerun a turn: regenerate the assistant response without deleting subsequent messages.

        Uses closure-based state to capture and restore messages after the target,
        avoiding fragile instance-level state.
        """
        if self.is_loading or index >= len(self.session.messages):
            return

        msg = self.session.messages[index]
        removed_assistant = None  # The original assistant message being replaced

        if msg["role"] == "user":
            # Target the assistant response at index+1 (if it exists)
            assistant_idx = index + 1
            if (
                assistant_idx < len(self.session.messages)
                and self.session.messages[assistant_idx]["role"] == "assistant"
            ):
                removed_assistant = self.session.messages[assistant_idx].copy()
                saved_messages = self.session.messages[assistant_idx + 1 :]
                self.session.messages = self.session.messages[:assistant_idx]
            else:
                # No assistant response after this user message — just generate
                saved_messages = self.session.messages[index + 1 :]
                self.session.messages = self.session.messages[: index + 1]
        else:
            # Assistant message — regenerate this response
            removed_assistant = self.session.messages[index].copy()
            saved_messages = self.session.messages[index + 1 :]
            self.session.messages = self.session.messages[:index]

        def restore_after_rerun(success=True):
            """Closure captures saved_messages and removed_assistant.
            On failure, restores the original assistant message too."""
            if not success and removed_assistant:
                self.session.messages.append(removed_assistant)
            self.session.messages.extend(saved_messages)

        self._update_chat_display(scroll_to_bottom=True)
        self._update_status("Rerunning turn...")
        self._regenerate_response(on_complete=restore_after_rerun)

    def _branch_from_here(self, index: int):
        """Create a new session branched from the selected message and open it."""
        if index >= len(self.session.messages):
            return

        from ... import web_server
        from ...session_manager import ChatSession

        # Carry over the parent's origin so origin-aware system prompts are preserved
        new_session = ChatSession(origin=self.session.origin)
        new_session.messages = [msg.copy() for msg in self.session.messages[: index + 1]]
        new_session.title = f"Branch: {self.session.title or 'Untitled'}"
        new_session.system_instruction = self.session.system_instruction
        # Carry over model override so branched sessions use the same model
        new_session.model_override = self.session.model_override
        new_session.profile_override = self.session.profile_override
        new_session.manual_mode = self.session.manual_mode
        new_session.provider_override = self.session.provider_override

        # Save the branched session
        add_session(new_session, web_server.CONFIG.get("max_sessions", 200))

        # Open new chat window via coordinator
        from ..core import GUICoordinator

        coordinator = GUICoordinator.get_instance()
        if coordinator:
            coordinator.request_chat_window(new_session)

        self._update_status(f"✅ Branched to session #{new_session.session_id}", self.theme.accent_green)

    # =========================================================================
    # Session Rename & Delete
    # =========================================================================

    def _rename_session(self):
        """Rename current chat session via modal dialog."""
        if self.is_loading or self._destroyed:
            return

        from ...session_manager import save_sessions

        current_title = self.session.title or ""

        # Create modal dialog (withdraw → DWM → deiconify pattern)
        if HAVE_CTK:
            dialog = ctk.CTkToplevel(self.root)
            dialog.withdraw()
            dialog.configure(fg_color=self.theme.bg)
        else:
            dialog = tk.Toplevel(self.root)
            dialog.withdraw()
            dialog.configure(bg=self.colors["bg"])

        dialog.title("Rename Session")
        dialog.geometry("400x130")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        set_window_icon(dialog)
        set_dark_titlebar(dialog)

        # Center on parent
        px = self.root.winfo_rootx() + (self.root.winfo_width() - 400) // 2
        py = self.root.winfo_rooty() + (self.root.winfo_height() - 130) // 2
        dialog.geometry(f"+{max(0, px)}+{max(0, py)}")

        dialog.deiconify()
        dialog.grab_set()

        title_var = tk.StringVar(value=current_title)

        def do_save():
            new_title = title_var.get().strip()
            if new_title:
                self.session.title = new_title
                save_sessions()
                # Notify any open browser windows to refresh
                from .session_browser import notify_browsers_refresh

                notify_browsers_refresh()
                # Update window title bar
                try:
                    if self.root and not self._destroyed:
                        self.root.title(f"Chat - {new_title}")
                except Exception:
                    pass
                self._update_status(f"✅ Renamed: {new_title}", self.theme.accent_green)
            dialog.destroy()

        def do_cancel():
            dialog.destroy()

        # Build UI
        if HAVE_CTK:
            ctk.CTkLabel(dialog, text="Session Title:", font=get_ctk_font(size=12), text_color=self.theme.fg).pack(
                anchor="w", padx=20, pady=(15, 5)
            )

            entry_colors = get_ctk_entry_colors(self.theme)
            entry = ctk.CTkEntry(
                dialog, textvariable=title_var, font=get_ctk_font(size=12), height=32, corner_radius=8, **entry_colors
            )
            entry.pack(fill="x", padx=20, pady=(0, 10))

            btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
            btn_frame.pack(fill="x", padx=20, pady=(0, 15))

            success_colors = get_ctk_button_colors(self.theme, "success")
            ctk.CTkButton(
                btn_frame,
                text="Save",
                font=get_ctk_font(size=12),
                width=70,
                height=32,
                corner_radius=8,
                command=do_save,
                **success_colors,
            ).pack(side="right", padx=(5, 0))

            sec_colors = get_ctk_button_colors(self.theme, "secondary")
            ctk.CTkButton(
                btn_frame,
                text="Cancel",
                font=get_ctk_font(size=12),
                width=70,
                height=32,
                corner_radius=8,
                command=do_cancel,
                **sec_colors,
            ).pack(side="right")
        else:
            tk.Label(
                dialog, text="Session Title:", font=("Segoe UI", 10), bg=self.colors["bg"], fg=self.colors["fg"]
            ).pack(anchor="w", padx=20, pady=(15, 5))

            entry = tk.Entry(
                dialog,
                textvariable=title_var,
                font=("Segoe UI", 10),
                bg=self.colors.get("input_bg", self.colors["text_bg"]),
                fg=self.colors["fg"],
                insertbackground=self.colors["fg"],
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground=self.colors["border"],
            )
            entry.pack(fill="x", padx=20, pady=(0, 10))

            btn_frame = tk.Frame(dialog, bg=self.colors["bg"])
            btn_frame.pack(fill="x", padx=20, pady=(0, 15))

            tk.Button(
                btn_frame,
                text="Save",
                font=("Segoe UI", 10),
                bg=self.colors["accent"],
                fg=self.colors["accent_fg"],
                relief=tk.FLAT,
                padx=10,
                pady=6,
                command=do_save,
                cursor="hand2",
            ).pack(side="right", padx=(5, 0))

            tk.Button(
                btn_frame,
                text="Cancel",
                font=("Segoe UI", 10),
                bg=self.colors["button_bg"],
                fg=self.colors["fg"],
                relief=tk.FLAT,
                padx=10,
                pady=6,
                command=do_cancel,
                cursor="hand2",
            ).pack(side="right")

        # Select all text
        try:
            entry.select_range(0, tk.END)
        except (AttributeError, tk.TclError):
            pass

        # Keyboard shortcuts
        dialog.protocol("WM_DELETE_WINDOW", do_cancel)
        dialog.bind("<Escape>", lambda e: do_cancel())
        dialog.bind("<Return>", lambda e: do_save())

        entry.focus_set()
        dialog.wait_window()

    def _delete_session(self):
        """Delete current chat session after confirmation."""
        if self.is_loading or self._destroyed:
            return

        from tkinter import messagebox

        from ...session_manager import delete_session, save_sessions

        session_title = self.session.title or f"Session {self.session.session_id}"

        if not messagebox.askyesno(
            "Delete Session",
            f'Permanently delete "{session_title}"?\n\nThis will close the chat window and remove all messages.',
            parent=self.root,
        ):
            return

        sid = self.session.session_id
        if delete_session(sid):
            save_sessions()
            # Notify any open browser windows to refresh
            from .session_browser import notify_browsers_refresh

            notify_browsers_refresh()
            self._close()
        else:
            self._update_status("Failed to delete session", self.theme.accent_red)

    # =========================================================================
    # Focus & Close
    # =========================================================================

    def _focus_window(self):
        """Focus the window reliably."""
        if self._destroyed or not self.root:
            return
        try:
            self.root.lift()
            self.root.focus_force()
            self.root.attributes("-topmost", True)
            self.root.after(
                100, lambda: self.root.attributes("-topmost", False) if self.root and not self._destroyed else None
            )
        except tk.TclError:
            pass

    def _close(self):
        """Close window and cleanup."""
        self._destroyed = True
        self.is_streaming = False
        unregister_window(self._get_window_tag())

        # Unsubscribe from config change events
        from ...config import unsubscribe_config_change

        unsubscribe_config_change(self._on_config_changed)

        # Clean up any remaining clipboard temp files
        import os

        for tmp in getattr(self, "_clipboard_temp_files", []):
            try:
                os.remove(tmp)
            except OSError:
                pass

        try:
            if self.root:
                self.root.destroy()
        except tk.TclError:
            pass
        self.root = None


class _EditMessageDialog:
    """Modal dialog for editing a message's content."""

    def __init__(self, parent, message: dict, theme, colors):
        self.result = None  # ("save", text) | ("save_rerun", text) | None

        role = message["role"]
        title = "Edit Message" if role == "user" else "Edit Response"
        content = message["content"]

        # Create dialog window (withdraw first to prevent white titlebar flash)
        if HAVE_CTK:
            self.dialog = ctk.CTkToplevel(parent)
            self.dialog.withdraw()
            self.dialog.configure(fg_color=theme.bg)
        else:
            self.dialog = tk.Toplevel(parent)
            self.dialog.withdraw()
            self.dialog.configure(bg=colors["bg"])

        self.dialog.title(title)
        self.dialog.geometry("600x400")
        self.dialog.transient(parent)
        set_window_icon(self.dialog)
        set_dark_titlebar(self.dialog)

        # Center on parent
        px = parent.winfo_rootx() + (parent.winfo_width() - 600) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - 400) // 2
        self.dialog.geometry(f"+{max(0, px)}+{max(0, py)}")
        self.dialog.deiconify()
        self.dialog.grab_set()

        self.dialog.columnconfigure(0, weight=1)
        self.dialog.rowconfigure(1, weight=1)

        # Title label
        if HAVE_CTK:
            ctk.CTkLabel(
                self.dialog, text=title, font=get_ctk_font(size=14, weight="bold"), text_color=theme.accent
            ).grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")
        else:
            tk.Label(self.dialog, text=title, font=("Segoe UI", 12, "bold"), bg=colors["bg"], fg=colors["accent"]).grid(
                row=0, column=0, padx=15, pady=(15, 5), sticky="w"
            )

        # Text area
        if HAVE_CTK:
            textbox_colors = get_ctk_textbox_colors(theme)
            self.text_area = ctk.CTkTextbox(
                self.dialog, font=get_ctk_font(size=12), corner_radius=8, border_width=1, wrap="word", **textbox_colors
            )
            self.text_area.grid(row=1, column=0, padx=15, pady=5, sticky="nsew")
            self.text_area.insert("0.0", content)
        else:
            self.text_area = tk.Text(
                self.dialog,
                font=("Segoe UI", 11),
                wrap=tk.WORD,
                bg=colors.get("input_bg", colors["text_bg"]),
                fg=colors["fg"],
                insertbackground=colors["fg"],
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground=colors["border"],
            )
            self.text_area.grid(row=1, column=0, padx=15, pady=5, sticky="nsew")
            self.text_area.insert("1.0", content)

        # Button row
        if HAVE_CTK:
            btn_frame = ctk.CTkFrame(self.dialog, fg_color="transparent")
            btn_frame.grid(row=2, column=0, padx=15, pady=(5, 15), sticky="e")

            warn_colors = get_ctk_button_colors(theme, "warning")
            ctk.CTkButton(
                btn_frame,
                text="Save & Rerun",
                font=get_ctk_font(size=12),
                width=110,
                height=32,
                corner_radius=8,
                command=self._save_and_rerun,
                **warn_colors,
            ).pack(side="left", padx=2)

            success_colors = get_ctk_button_colors(theme, "success")
            ctk.CTkButton(
                btn_frame,
                text="Save",
                font=get_ctk_font(size=12),
                width=70,
                height=32,
                corner_radius=8,
                command=self._save,
                **success_colors,
            ).pack(side="left", padx=2)

            sec_colors = get_ctk_button_colors(theme, "secondary")
            ctk.CTkButton(
                btn_frame,
                text="Cancel",
                font=get_ctk_font(size=12),
                width=70,
                height=32,
                corner_radius=8,
                command=self._cancel,
                **sec_colors,
            ).pack(side="left", padx=2)
        else:
            btn_frame = tk.Frame(self.dialog, bg=colors["bg"])
            btn_frame.grid(row=2, column=0, padx=15, pady=(5, 15), sticky="e")

            tk.Button(
                btn_frame,
                text="Save & Rerun",
                font=("Segoe UI", 10),
                bg=colors.get("accent_yellow", "#f9e2af"),
                fg=colors["bg"],
                relief=tk.FLAT,
                padx=10,
                pady=6,
                command=self._save_and_rerun,
                cursor="hand2",
            ).pack(side=tk.LEFT, padx=2)

            tk.Button(
                btn_frame,
                text="Save",
                font=("Segoe UI", 10),
                bg=colors["accent"],
                fg=colors["accent_fg"],
                relief=tk.FLAT,
                padx=10,
                pady=6,
                command=self._save,
                cursor="hand2",
            ).pack(side=tk.LEFT, padx=2)

            tk.Button(
                btn_frame,
                text="Cancel",
                font=("Segoe UI", 10),
                bg=colors["button_bg"],
                fg=colors["fg"],
                relief=tk.FLAT,
                padx=10,
                pady=6,
                command=self._cancel,
                cursor="hand2",
            ).pack(side=tk.LEFT, padx=2)

        # Keyboard shortcuts
        self.dialog.protocol("WM_DELETE_WINDOW", self._cancel)
        self.dialog.bind("<Escape>", lambda e: self._cancel())

        # Focus the text area
        self.text_area.focus_set()

        # Block until dialog closes
        self.dialog.wait_window()

    def _get_text(self) -> str:
        """Get current text content from the text area."""
        if HAVE_CTK:
            return self.text_area.get("0.0", "end-1c")
        else:
            return self.text_area.get("1.0", "end-1c")

    def _save(self):
        self.result = ("save", self._get_text())
        self.dialog.destroy()

    def _save_and_rerun(self):
        self.result = ("save_rerun", self._get_text())
        self.dialog.destroy()

    def _cancel(self):
        self.result = None
        self.dialog.destroy()
