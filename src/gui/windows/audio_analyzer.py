#!/usr/bin/env python3
"""
Audio Analyzer Window for audio recording and AI analysis.

A full window (visible in taskbar) providing:
- Provider & model selection
- Audio source selection (input/loopback devices)
- Recording controls with real-time level meter
- Compression settings with presets
- Playback controls with seek bar
- Prompt selection for AI analysis
- Result display with copy functionality

Threading Note:
    This must be created on the GUI thread via GUICoordinator.
"""

import base64
import io
import logging
import threading
import time
import tkinter as tk
from typing import Callable, Optional, Dict, List, Any

from ..platform import HAVE_CTK, ctk
from ..themes import (
    get_colors, ThemeColors,
    get_ctk_font, get_ctk_button_colors,
    get_ctk_frame_colors, get_ctk_entry_colors,
    get_ctk_combobox_colors, sync_ctk_appearance
)
from ..core import get_next_window_id, register_window, unregister_window, GUICoordinator
from ..custom_widgets import ScrollableComboBox
from ..popups import Tooltip, CarouselButtonList, ModifierBar, GroupedButtonList, SegmentedToggle
from ..prompts import get_prompts_config
from ..emoji_renderer import prepare_emoji_content
from .utils import set_window_icon


class AudioAnalyzerWindow:
    """
    Full window for audio recording and AI analysis.
    
    Features:
    - Audio device selection (microphone or system loopback)
    - Recording with real-time level meter (always active)
    - Compression presets for optimized file size
    - Audio playback with seek bar
    - Action prompts for transcription, analysis, etc.
    - Result display with copy functionality
    """
    
    LEVEL_UPDATE_INTERVAL = 20  # ms between level meter updates
    DURATION_UPDATE_INTERVAL = 100  # ms between duration display updates
    
    # Level meter sensitivity settings
    LEVEL_AMPLIFICATION = 6.0  # Amplify raw RMS levels for better visibility
    LEVEL_SMOOTHING = 0.3  # Smoothing factor (0 = no smoothing, 1 = max smoothing)
    
    def __init__(
        self,
        parent_root: tk.Tk,
        config: Dict[str, Any],
        ai_params: Dict[str, Any],
        key_managers: Dict[str, Any],
        on_close: Optional[Callable[[], None]] = None,
        on_action: Optional[Callable] = None
    ):
        """
        Initialize the audio analyzer window.
        
        Args:
            parent_root: Parent Tk root (from GUICoordinator)
            config: Application configuration dictionary
            ai_params: AI parameters dictionary
            key_managers: Dictionary of KeyManager instances
            on_close: Optional callback when window closes
            on_action: Optional callback when action selected
        """
        self.parent_root = parent_root
        self.config = config
        self.ai_params = ai_params
        self.key_managers = key_managers
        self.on_close_callback = on_close
        self.on_action_callback = on_action
        
        self.window_id = get_next_window_id()
        self.colors = get_colors()
        self._destroyed = False
        
        # Audio state
        self.recorder = None
        self.current_device = None
        self.recorded_wav: Optional[bytes] = None
        self.compressed_audio: Optional[bytes] = None
        self.audio_duration = 0.0
        
        # Recording state
        self.is_recording = False
        self.recording_start_time = 0.0
        
        # Level meter state
        self._current_level = 0.0
        self._level_monitor_active = False
        
        # Playback state
        self.is_playing = False
        self.playback_position = 0.0
        
        # Compression settings (always enabled with recommended preset by default)
        self.compression_enabled = True
        self.compression_preset = "recommended"
        
        # Provider/Model state
        self.provider = config.get("default_provider", "google")
        self.model = config.get(f"{self.provider}_model", "")
        self.available_models: List[str] = []
        
        # Prompts
        self.prompts = get_prompts_config()
        self.active_modifiers: List[str] = []
        
        # Processing state
        self.is_processing = False
        self.result_text = ""
        
        # UI references
        self.root = None
        self._init_ui_refs()
        
        self._create_window()
    
    def _init_ui_refs(self):
        """Initialize UI element references."""
        self.selected_action_key = "Transcribe"
        self.custom_input = None
        self.action_indicator_label = None
        self.provider_dropdown = None
        self.model_dropdown = None
        self.device_dropdown = None
        self.device_type_var = None
        self.record_btn = None
        self.stop_btn = None
        self.duration_label = None
        self.level_canvas = None  # Canvas-based meter (legacy)
        self.level_bar = None  # CTkProgressBar-based meter (new)
        self.meter_style = self.config.get("audio_level_meter_style", "progressbar")
        self.compression_var = None
        self.preset_dropdown = None
        self.size_label = None
        self.preset_desc_label = None  # New: description label
        self.play_btn = None
        self.pause_btn = None
        self.seek_slider = None
        self.position_label = None
        self.actions_frame = None
        self.carousel = None
        self.modifier_bar = None
        self.send_btn = None
        self.clear_btn = None
        self.result_text_widget = None
        self.copy_btn = None
        self.status_label = None
        self.response_mode_toggle = None
    
    def _get_window_tag(self) -> str:
        """Return unique window tag."""
        return f"audio_analyzer_{self.window_id}"
    
    def _create_window(self):
        """Create the main window."""
        if HAVE_CTK:
            sync_ctk_appearance()
            self.root = ctk.CTkToplevel(self.parent_root)
        else:
            self.root = tk.Toplevel(self.parent_root)
        
        self.root.title("🎤 Audio Analyzer")
        self.root.geometry("800x676")
        self.root.minsize(700, 675)
        
        # Position window
        offset = (self.window_id % 5) * 30
        self.root.geometry(f"+{100 + offset}+{50 + offset}")
        
        # Configure
        if HAVE_CTK:
            self.root.configure(fg_color=self.colors.base)
        else:
            self.root.configure(bg=self.colors.base)
        
        set_window_icon(self.root)
        
        # Build UI
        self._build_ui()
        
        # Register and set close handler
        register_window(self._get_window_tag())
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        
        # Load models in background
        threading.Thread(target=self._load_models, daemon=True).start()
        
        # Initialize audio system - deferred slightly to allow UI build
        self.root.after(100, self._init_audio)
    
    def _build_ui(self):
        """Build the complete UI."""
        if HAVE_CTK:
            self._build_ctk_ui()
        else:
            self._build_tk_ui()
    
    def _build_ctk_ui(self):
        """Build CustomTkinter UI with two-column layout."""
        # === IMPORTANT: Create bottom bar FIRST so it stays visible ===
        self._create_bottom_bar()
        
        # Main container (no scroll)
        main_frame = ctk.CTkFrame(
            self.root,
            fg_color="transparent"
        )
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Configure grid weights for two-column layout
        main_frame.grid_columnconfigure(0, weight=0, minsize=300)  # Left column - fixed width
        main_frame.grid_columnconfigure(1, weight=1)  # Right column - expands
        # Only right column rows expand
        main_frame.grid_rowconfigure(2, weight=1)  # Result row expands
        
        # === Row 0: Top Action Bar with Provider/Model on left, Send/Clear on right ===
        self._create_top_action_bar(main_frame)
        
        # === Left Column (Audio controls - don't stretch vertically) ===
        left_container = ctk.CTkFrame(main_frame, fg_color="transparent")
        left_container.grid(row=1, column=0, rowspan=2, sticky="new", padx=(0, 5), pady=5)
        
        # Audio Source
        self._create_audio_source_section_pack(left_container)
        
        # Recording
        self._create_recording_section_pack(left_container)
        
        # Compression
        self._create_compression_section_pack(left_container)
        
        # Preview
        self._create_preview_section_pack(left_container)
        
        # Response Mode
        self._create_display_options_section_pack(left_container)
        
        # === Right Column (Prompt Selection + Result) ===
        # Row 1: Prompt Selection
        self._create_prompt_section_grid(main_frame, row=1, col=1)
        
        # Row 2: Result (expands)
        self._create_result_section_grid(main_frame, row=2, col=1, rowspan=1)
    
    def _build_tk_ui(self):
        """Build standard Tkinter UI (fallback)."""
        from .audio_analyzer_tk import build_tk_ui
        build_tk_ui(self)
    
    def _create_section_frame_grid(self, parent, title: str, row: int, col: int, rowspan: int = 1) -> Any:
        """Create a titled section frame using grid layout."""
        frame = ctk.CTkFrame(
            parent,
            fg_color=self.colors.surface0,
            corner_radius=10,
            border_color=self.colors.surface2,
            border_width=1
        )
        frame.grid(row=row, column=col, rowspan=rowspan, sticky="nsew", padx=5, pady=5)
        
        # Section title
        ctk.CTkLabel(
            frame,
            text=title,
            font=get_ctk_font(size=12, weight="bold"),
            text_color=self.colors.accent
        ).pack(anchor="w", padx=12, pady=(10, 5))
        
        # Content container
        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        
        return content
    
    def _create_top_action_bar(self, parent):
        """Create top action bar with Provider/Model on left, Send/Clear on right."""
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        
        # === Left side: Provider & Model ===
        left_frame = ctk.CTkFrame(bar, fg_color="transparent")
        left_frame.pack(side="left", fill="x", expand=True)
        
        # Provider dropdown
        ctk.CTkLabel(
            left_frame,
            text="Provider:",
            font=get_ctk_font(size=11),
            text_color=self.colors.text
        ).pack(side="left", padx=(0, 5))
        
        providers = ["google", "openrouter", "custom"]
        self.provider_dropdown = ctk.CTkOptionMenu(
            left_frame,
            values=providers,
            command=self._on_provider_changed,
            width=100,
            height=32,
            corner_radius=6,
            fg_color=self.colors.surface1,
            button_color=self.colors.surface2,
            button_hover_color=self.colors.overlay0,
            dropdown_fg_color=self.colors.surface0,
            dropdown_hover_color=self.colors.surface1,
            text_color=self.colors.text,
            font=get_ctk_font(size=11)
        )
        self.provider_dropdown.set(self.provider)
        self.provider_dropdown.pack(side="left", padx=(0, 15))
        
        # Model dropdown
        ctk.CTkLabel(
            left_frame,
            text="Model:",
            font=get_ctk_font(size=11),
            text_color=self.colors.text
        ).pack(side="left", padx=(0, 5))
        
        self.model_dropdown = ScrollableComboBox(
            left_frame,
            colors=self.colors,
            values=["(loading...)"],
            width=200,
            height=32,
            command=self._on_model_changed
        )
        self.model_dropdown.pack(side="left")
        self.model_dropdown.set(self.model or "(loading...)")
        
        # === Right side: Send/Clear buttons ===
        right_frame = ctk.CTkFrame(bar, fg_color="transparent")
        right_frame.pack(side="right")
        
        # Send button
        send_content = prepare_emoji_content("📤 Send", size=14)
        self.send_btn = ctk.CTkButton(
            right_frame,
            **send_content,
            font=get_ctk_font(size=12, weight="bold"),
            width=100,
            height=36,
            corner_radius=8,
            command=self._send_audio,
            state="disabled",
            **get_ctk_button_colors(self.colors, "success")
        )
        self.send_btn.pack(side="left", padx=(0, 10))
        
        # Clear button
        clear_content = prepare_emoji_content("🗑 Clear Audio", size=14)
        self.clear_btn = ctk.CTkButton(
            right_frame,
            **clear_content,
            font=get_ctk_font(size=11),
            width=120,
            height=36,
            corner_radius=8,
            command=self._clear_audio,
            state="disabled",
            **get_ctk_button_colors(self.colors, "danger")
        )
        self.clear_btn.pack(side="left")
    
    # =========================================================================
    # Pack-based section methods for left column
    # =========================================================================
    
    def _create_section_frame_pack(self, parent, title: str) -> Any:
        """Create a titled section frame using pack layout."""
        frame = ctk.CTkFrame(
            parent,
            fg_color=self.colors.surface0,
            corner_radius=10,
            border_color=self.colors.surface2,
            border_width=1
        )
        frame.pack(fill="x", pady=(0, 8))
        
        # Section title
        ctk.CTkLabel(
            frame,
            text=title,
            font=get_ctk_font(size=12, weight="bold"),
            text_color=self.colors.accent
        ).pack(anchor="w", padx=12, pady=(10, 5))
        
        # Content container
        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.pack(fill="x", padx=12, pady=(0, 10))
        
        return content
    
    def _create_audio_source_section_pack(self, parent):
        """Create audio source selection section (pack layout)."""
        content = self._create_section_frame_pack(parent, "Audio Source")
        
        # Device dropdown row
        device_row = ctk.CTkFrame(content, fg_color="transparent")
        device_row.pack(fill="x", pady=(0, 8))
        
        ctk.CTkLabel(
            device_row,
            text="Device:",
            font=get_ctk_font(size=11),
            text_color=self.colors.text
        ).pack(side="left", padx=(0, 5))
        
        self.device_dropdown = ctk.CTkOptionMenu(
            device_row,
            values=["(loading...)"],
            command=self._on_device_changed,
            width=160,
            height=28,
            corner_radius=6,
            fg_color=self.colors.surface1,
            button_color=self.colors.surface2,
            button_hover_color=self.colors.overlay0,
            dropdown_fg_color=self.colors.surface0,
            dropdown_hover_color=self.colors.surface1,
            text_color=self.colors.text,
            font=get_ctk_font(size=10)
        )
        self.device_dropdown.pack(side="left", fill="x", expand=True, padx=(0, 8))
        
        # Refresh button - using prepare_emoji_content for proper emoji rendering
        refresh_content = prepare_emoji_content("🔄", size=14)
        refresh_btn = ctk.CTkButton(
            device_row,
            **refresh_content,
            width=32,
            height=28,
            corner_radius=6,
            command=self._refresh_devices,
            **get_ctk_button_colors(self.colors, "secondary")
        )
        refresh_btn.pack(side="left")
        Tooltip(refresh_btn, "Refresh device list")
        
        # Device type radio buttons
        type_row = ctk.CTkFrame(content, fg_color="transparent")
        type_row.pack(fill="x")
        
        self.device_type_var = tk.StringVar(value="loopback" if self.config.get("audio_default_loopback", True) else "input")
        
        ctk.CTkRadioButton(
            type_row,
            text="🎤 Input",
            variable=self.device_type_var,
            value="input",
            command=self._on_device_type_changed,
            font=get_ctk_font(size=11),
            text_color=self.colors.text,
            fg_color=self.colors.accent,
            hover_color=self.colors.lavender,
            border_color=self.colors.surface2
        ).pack(side="left", padx=(0, 15))
        
        ctk.CTkRadioButton(
            type_row,
            text="🔊 Loopback",
            variable=self.device_type_var,
            value="loopback",
            command=self._on_device_type_changed,
            font=get_ctk_font(size=11),
            text_color=self.colors.text,
            fg_color=self.colors.accent,
            hover_color=self.colors.lavender,
            border_color=self.colors.surface2
        ).pack(side="left")
    
    def _create_recording_section_pack(self, parent):
        """Create recording controls section (pack layout)."""
        content = self._create_section_frame_pack(parent, "Recording")
        
        # Controls row
        controls_row = ctk.CTkFrame(content, fg_color="transparent")
        controls_row.pack(fill="x")
        
        # Record button
        record_content = prepare_emoji_content("🔴 Record", size=14)
        self.record_btn = ctk.CTkButton(
            controls_row,
            **record_content,
            font=get_ctk_font(size=11, weight="bold"),
            width=90,
            height=32,
            corner_radius=6,
            command=self._start_recording,
            **get_ctk_button_colors(self.colors, "danger")
        )
        self.record_btn.pack(side="left", padx=(0, 5))
        
        # Stop button
        stop_content = prepare_emoji_content("⏹ Stop", size=14)
        self.stop_btn = ctk.CTkButton(
            controls_row,
            **stop_content,
            font=get_ctk_font(size=11),
            width=70,
            height=32,
            corner_radius=6,
            command=self._stop_recording,
            state="disabled",
            **get_ctk_button_colors(self.colors, "secondary")
        )
        self.stop_btn.pack(side="left", padx=(0, 10))
        
        # Duration display
        self.duration_label = ctk.CTkLabel(
            controls_row,
            text="00:00:00",
            font=get_ctk_font(size=12, weight="bold"),
            text_color=self.colors.text
        )
        self.duration_label.pack(side="left")
    
    def _create_compression_section_pack(self, parent):
        """Create compression settings section (pack layout)."""
        content = self._create_section_frame_pack(parent, "Compression")
        
        row_frame = ctk.CTkFrame(content, fg_color="transparent")
        row_frame.pack(fill="x", pady=(0, 5))
        
        # Enable checkbox
        self.compression_var = tk.BooleanVar(value=self.compression_enabled)
        compression_cb = ctk.CTkCheckBox(
            row_frame,
            text="Enable",
            variable=self.compression_var,
            command=self._on_compression_toggled,
            font=get_ctk_font(size=11),
            text_color=self.colors.text,
            fg_color=self.colors.accent,
            hover_color=self.colors.lavender,
            border_color=self.colors.surface2,
            checkmark_color=self.colors.base,
            width=24
        )
        compression_cb.pack(side="left", padx=(0, 10))
        
        # Preset dropdown
        ctk.CTkLabel(
            row_frame,
            text="Preset:",
            font=get_ctk_font(size=11),
            text_color=self.colors.overlay0
        ).pack(side="left", padx=(0, 5))
        
        from ...audio.recorder import COMPRESSION_PRESETS
        preset_names = [p["name"] for p in COMPRESSION_PRESETS.values()]
        
        self.preset_dropdown = ctk.CTkOptionMenu(
            row_frame,
            values=preset_names,
            command=self._on_preset_changed,
            width=110,
            height=28,
            corner_radius=6,
            fg_color=self.colors.surface1,
            button_color=self.colors.surface2,
            button_hover_color=self.colors.overlay0,
            dropdown_fg_color=self.colors.surface0,
            dropdown_hover_color=self.colors.surface1,
            text_color=self.colors.text,
            font=get_ctk_font(size=10)
        )
        # Set current preset
        current_preset = COMPRESSION_PRESETS.get(self.compression_preset, {})
        self.preset_dropdown.set(current_preset.get("name", "Recommended"))
        self.preset_dropdown.pack(side="left")
        
        # Second row: Size estimation and description
        info_row = ctk.CTkFrame(content, fg_color="transparent")
        info_row.pack(fill="x")
        
        # Size estimation
        self.size_label = ctk.CTkLabel(
            info_row,
            text="",
            font=get_ctk_font(size=10),
            text_color=self.colors.overlay0
        )
        self.size_label.pack(side="left")
        
        # Preset description
        desc = current_preset.get("description", "")
        self.preset_desc_label = ctk.CTkLabel(
            info_row,
            text=f"• {desc}" if desc else "",
            font=get_ctk_font(size=9),
            text_color=self.colors.overlay0
        )
        self.preset_desc_label.pack(side="right")
    
    def _create_preview_section_pack(self, parent):
        """Create audio preview/playback section (pack layout)."""
        content = self._create_section_frame_pack(parent, "Preview")
        
        row_frame = ctk.CTkFrame(content, fg_color="transparent")
        row_frame.pack(fill="x")
        
        # Play button
        play_content = prepare_emoji_content("▶", size=14)
        self.play_btn = ctk.CTkButton(
            row_frame,
            **play_content,
            width=40,
            height=32,
            corner_radius=6,
            command=self._play_audio,
            state="disabled",
            **get_ctk_button_colors(self.colors, "success")
        )
        self.play_btn.pack(side="left", padx=(0, 5))
        
        # Pause button
        pause_content = prepare_emoji_content("⏸", size=14)
        self.pause_btn = ctk.CTkButton(
            row_frame,
            **pause_content,
            width=40,
            height=32,
            corner_radius=6,
            command=self._pause_audio,
            state="disabled",
            **get_ctk_button_colors(self.colors, "secondary")
        )
        self.pause_btn.pack(side="left", padx=(0, 8))
        
        # Seek slider
        self.seek_slider = ctk.CTkSlider(
            row_frame,
            from_=0,
            to=100,
            width=80,
            height=16,
            corner_radius=8,
            button_corner_radius=8,
            fg_color=self.colors.surface1,
            progress_color=self.colors.accent,
            button_color=self.colors.accent,
            button_hover_color=self.colors.lavender,
            command=self._on_seek
        )
        self.seek_slider.set(0)
        self.seek_slider.configure(state="disabled")
        self.seek_slider.pack(side="left", fill="x", expand=True, padx=(0, 8))
        
        # Position label
        self.position_label = ctk.CTkLabel(
            row_frame,
            text="00:00",
            font=get_ctk_font(size=10),
            text_color=self.colors.overlay0
        )
        self.position_label.pack(side="left")
    
    def _create_display_options_section_pack(self, parent):
        """Create display options section (pack layout)."""
        content = self._create_section_frame_pack(parent, "Response Mode")
        
        # Segmented toggle
        self.response_mode_toggle = SegmentedToggle(
            content,
            options=[("Default", "default"), ("Result Panel", "result"), ("Chat Window", "show")],
            default_value="default"
        )
        self.response_mode_toggle.pack(pady=(0, 5))
        
        # Description
        ctk.CTkLabel(
            content,
            text="Override where the AI response is shown.",
            font=get_ctk_font(size=10),
            text_color=self.colors.overlay0,
            justify="center",
            wraplength=200
        ).pack(fill="x", padx=5)

    # =========================================================================
    # Grid-based section methods (for right column)
    # =========================================================================
    
    def _create_prompt_section_grid(self, parent, row: int, col: int):
        """Create prompt selection section."""
        content = self._create_section_frame_grid(parent, "Prompt Selection", row, col)
        
        # Custom Task Input with Button
        input_frame = ctk.CTkFrame(content, fg_color="transparent")
        input_frame.pack(fill="x", pady=(0, 10))
        
        self.custom_input = ctk.CTkEntry(
            input_frame,
            placeholder_text="Custom task or question...",
            font=get_ctk_font(size=12),
            height=32,
            border_color=self.colors.surface2
        )
        self.custom_input.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.custom_input.bind('<Return>', self._on_custom_input_set)
        
        from ..custom_widgets import create_emoji_button
        create_emoji_button(
            input_frame, "Set", "⚡", self.colors, "secondary", width=60, height=32,
            command=self._on_custom_input_set
        ).pack(side="right")
        
        settings = self.prompts.get_audio_tool().get("_settings", {})
        use_groups = settings.get("use_groups", True)
        
        if use_groups and settings.get("popup_groups"):
            popup_groups = settings.get("popup_groups", [])
            actions = self.prompts.get_audio_actions()
            
            # Construct group data for GroupedButtonList
            groups = []
            for group_def in popup_groups:
                group_name = group_def.get("name", "")
                item_keys = group_def.get("items", [])
                
                group_items = []
                for key in item_keys:
                    action = actions.get(key)
                    if action:
                        icon = action.get("icon", "")
                        tooltip = action.get("task", "")
                        group_items.append((key, key, icon, tooltip))
                
                if group_items:
                    groups.append({"name": group_name, "items": group_items})
            
            if groups:
                # Use GroupedButtonList instead of flat CarouselButtonList
                self.carousel = GroupedButtonList(
                    content,
                    groups=groups,
                    on_click=self._on_action_click
                )
                self.carousel.pack(fill="x", pady=(0, 8))
        else:
            # Flat list fallback
            actions = self.prompts.get_audio_actions()
            items = []
            for key, action in actions.items():
                if key.startswith("_"):
                    continue
                icon = action.get("icon", "")
                tooltip = action.get("task", "")
                items.append((key, key, icon, tooltip))
            
            items_per_page = settings.get("items_per_page", 6)
            
            if items:
                self.carousel = CarouselButtonList(
                    content,
                    items=items,
                    on_click=self._on_action_click,
                    items_per_page=items_per_page
                )
                self.carousel.pack(fill="x", pady=(0, 8))
            
        # Modifier bar (Fixed position at bottom of prompt section)
        global_modifiers = self.prompts.get_modifiers()
        if global_modifiers:
            self.modifier_bar = ModifierBar(
                content,
                modifiers=global_modifiers,
                on_change=self._on_modifiers_changed
            )
            self.modifier_bar.pack(fill="x")
    
    def _create_result_section_grid(self, parent, row: int, col: int, rowspan: int = 1):
        """Create result display section."""
        frame = ctk.CTkFrame(
            parent,
            fg_color=self.colors.surface0,
            corner_radius=10,
            border_color=self.colors.surface2,
            border_width=1
        )
        frame.grid(row=row, column=col, rowspan=rowspan, sticky="nsew", padx=5, pady=5)
        
        # Header row
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 5))
        
        ctk.CTkLabel(
            header,
            text="Result",
            font=get_ctk_font(size=12, weight="bold"),
            text_color=self.colors.accent
        ).pack(side="left")
        
        # Copy button
        copy_content = prepare_emoji_content("📋 Copy", size=12)
        self.copy_btn = ctk.CTkButton(
            header,
            **copy_content,
            font=get_ctk_font(size=10),
            width=70,
            height=26,
            corner_radius=6,
            command=self._copy_result,
            state="disabled",
            **get_ctk_button_colors(self.colors, "secondary")
        )
        self.copy_btn.pack(side="right")
        
        # Result text widget (tk.Text for markdown support)
        text_frame = ctk.CTkFrame(frame, fg_color=self.colors.text_bg, corner_radius=8)
        text_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        
        self.result_text_widget = tk.Text(
            text_frame,
            wrap=tk.WORD,
            font=("Segoe UI", 11),
            bg=self.colors.text_bg,
            fg=self.colors.text,
            insertbackground=self.colors.text,
            relief=tk.FLAT,
            highlightthickness=0,
            padx=10,
            pady=10,
            state=tk.DISABLED
        )
        self.result_text_widget.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Placeholder text
        self.result_text_widget.configure(state=tk.NORMAL)
        self.result_text_widget.insert("1.0", "(Transcription/analysis result will appear here)")
        self.result_text_widget.configure(state=tk.DISABLED, fg=self.colors.overlay0)
    
    def _create_bottom_bar(self):
        """Create bottom bar with level meter and status."""
        bottom_frame = ctk.CTkFrame(
            self.root,
            fg_color=self.colors.surface0,
            corner_radius=0,
            height=60
        )
        bottom_frame.pack(fill="x", side="bottom")
        bottom_frame.pack_propagate(False)
        
        # Level meter (full width, placed at top of bottom bar)
        meter_container = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        meter_container.pack(fill="x", padx=15, pady=(8, 0))
        
        ctk.CTkLabel(
            meter_container,
            text="Level:",
            font=get_ctk_font(size=10),
            text_color=self.colors.overlay0
        ).pack(side="left", padx=(0, 8))
        
        # Check config for meter style
        if self.meter_style == "progressbar":
            # Simple CTkProgressBar
            self.level_bar = ctk.CTkProgressBar(
                meter_container,
                height=12,
                progress_color=self.colors.accent,
                fg_color=self.colors.surface1
            )
            self.level_bar.pack(side="left", fill="x", expand=True)
            self.level_bar.set(0)
            self.level_canvas = None
        else:
            # Canvas-based meter with grid lines (legacy)
            self.level_canvas = tk.Canvas(
                meter_container,
                height=12,
                bg=self.colors.surface1,
                highlightthickness=1,
                highlightbackground=self.colors.surface2
            )
            self.level_canvas.pack(side="left", fill="x", expand=True)
            self.level_bar = None
            self._canvas_drawn_width = 0
            self.level_canvas.bind("<Configure>", self._on_canvas_resize)
            self.level_canvas.after(50, self._draw_level_grid)
        
        # Status bar (below level meter)
        status_container = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        status_container.pack(fill="x", padx=15, pady=(4, 8))
        
        self.status_label = ctk.CTkLabel(
            status_container,
            text="Ready",
            font=get_ctk_font(size=10),
            text_color=self.colors.overlay0
        )
        self.status_label.pack(side="left")

        # Action Indicator (Right aligned)
        self.action_indicator_label = ctk.CTkLabel(
            status_container,
            text=f"Action: {self.selected_action_key}",
            font=get_ctk_font(size=10, weight="bold"),
            text_color=self.colors.accent
        )
        self.action_indicator_label.pack(side="right")
        
        # Initial display
        self._update_level_display(0.0)
    
    # =========================================================================
    # Audio Initialization
    # =========================================================================
    
    def _init_audio(self):
        """Initialize audio system."""
        try:
            from ...audio import is_pyaudio_available
            
            if not is_pyaudio_available():
                self._update_status("PyAudioWPatch not available", self.colors.red)
                return
            
            # Refresh device list
            self._refresh_devices()
            
        except Exception as e:
            logging.error(f"[AudioAnalyzer] Failed to initialize audio: {e}")
            self._update_status(f"Audio init failed: {e}", self.colors.red)
    
    def _refresh_devices(self):
        """Refresh the device dropdown list."""
        try:
            from ...audio import (
                list_input_devices, list_loopback_devices,
                get_default_input_device, get_default_loopback_device
            )
            
            device_type = self.device_type_var.get() if self.device_type_var else "loopback"
            
            if device_type == "loopback":
                devices = list_loopback_devices()
                system_default = get_default_loopback_device()
            else:
                devices = list_input_devices()
                system_default = get_default_input_device()
            
            if not devices:
                if self.device_dropdown:
                    try:
                        self.device_dropdown.configure(values=["(no devices found)"])
                        self.device_dropdown.set("(no devices found)")
                    except Exception:
                        pass
                self.current_device = None
                return
            
            # Build device name list
            device_names = [d.get_display_name() for d in devices]
            
            if self.device_dropdown:
                try:
                    self.device_dropdown.configure(values=device_names)
                except Exception:
                    pass
            
            # Store device mapping
            self._device_map = {d.get_display_name(): d for d in devices}
            
            # Try to find device by config preference (with partial matching)
            config_device = self.config.get("audio_default_device", "default")
            selected_device = None
            selected_name = None
            
            if config_device and config_device.lower() != "default":
                # Partial case-insensitive matching
                config_lower = config_device.lower()
                for name, device in self._device_map.items():
                    if config_lower in name.lower():
                        selected_device = device
                        selected_name = name
                        logging.info(f"[AudioAnalyzer] Matched config device '{config_device}' to '{name}'")
                        break
            
            # Fall back to system default if no config match
            if not selected_device and system_default:
                selected_name = system_default.get_display_name()
                if selected_name in self._device_map:
                    selected_device = system_default
            
            # Fall back to first device if nothing else works
            if not selected_device and devices:
                selected_device = devices[0]
                selected_name = device_names[0]
            
            # Apply selection
            if selected_device and selected_name and self.device_dropdown:
                try:
                    self.device_dropdown.set(selected_name)
                    self.current_device = selected_device
                except Exception:
                    pass
            
            # Update recorder device
            self._update_recorder_device()
            
            self._update_status(f"Found {len(devices)} device(s)")
            
        except Exception as e:
            logging.error(f"[AudioAnalyzer] Failed to refresh devices: {e}")
            self._update_status(f"Device refresh failed: {e}", self.colors.red)
            
    def _update_recorder_device(self):
        """Update the recorder with current device."""
        try:
            from ...audio import AudioRecorder
            
            # Stop existing stream before cleanup
            if self.recorder:
                self.recorder.stop_stream()
                self.recorder.cleanup()
            
            if self.current_device:
                self.recorder = AudioRecorder(self.current_device)
                print(f"[AudioAnalyzer] Created recorder for device: {self.current_device.name}")
                
                # Start stream immediately with level callback
                callback = self._create_level_callback()
                if self.recorder.start_stream(level_callback=callback):
                    print(f"[AudioAnalyzer] Stream started for: {self.current_device.name}")
                    # Start continuous level updates
                    self._start_continuous_level_updates()
                else:
                    print(f"[AudioAnalyzer] Failed to start stream")
                # NOTE: With unified stream, level meter works continuously!
                
        except Exception as e:
            print(f"[AudioAnalyzer] Failed to update recorder: {e}")
            logging.error(f"[AudioAnalyzer] Failed to update recorder: {e}")
    
    def _create_level_callback(self):
        """Create the level callback function (simplified like transcription_popup.py).
        
        Uses GUICoordinator for thread-safe UI updates and simple progressbar.set().
        The polling in _start_continuous_level_updates handles amplification/smoothing.
        """
        def level_callback(level: float):
            """Handle audio level update (called from audio thread)."""
            if self._destroyed:
                return
            
            # Simple amplification for visibility
            amplified = min(1.0, level * self.LEVEL_AMPLIFICATION)
            
            # Update via GUICoordinator (thread-safe like transcription_popup.py)
            try:
                if self.meter_style == "progressbar" and self.level_bar:
                    GUICoordinator.get_instance().run_on_gui_thread(
                        lambda l=amplified: self.level_bar.set(l)
                    )
            except Exception:
                pass  # Window may be closing
        
        return level_callback
    
    def _start_continuous_level_updates(self):
        """Start continuous polling of level (works before and during recording).
        
        This is used with the unified stream architecture where the stream
        is always active and we just need to poll the level value.
        """
        if self._destroyed:
            return
        
        start_t = time.time()
        
        try:
            # Get level from recorder (always available when stream is active)
            level = self.recorder.get_level() if self.recorder else 0.0
            
            # Apply amplification and smoothing
            amplified = min(1.0, level * self.LEVEL_AMPLIFICATION)
            smoothed = (self._current_level * self.LEVEL_SMOOTHING +
                       amplified * (1.0 - self.LEVEL_SMOOTHING))
            self._current_level = smoothed
            
            # Update display
            self._update_level_display(smoothed)
            
            # Schedule next update (runs continuously while window is open)
            self.root.after(self.LEVEL_UPDATE_INTERVAL, self._start_continuous_level_updates)
            
            # Performance check
            duration = (time.time() - start_t) * 1000
            if duration > 15:  # If update takes more than 15ms
                print(f"[Perf] Level update lagging: {duration:.1f}ms")
            
        except Exception as e:
            logging.debug(f"[AudioAnalyzer] Level update error: {e}")
    
    def _hex_to_rgb(self, hex_color: str) -> tuple:
        """Convert hex color to RGB tuple."""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    def _rgb_to_hex(self, rgb: tuple) -> str:
        """Convert RGB tuple to hex color."""
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
    
    def _interpolate_color(self, color1: str, color2: str, ratio: float) -> str:
        """Interpolate between two hex colors."""
        rgb1 = self._hex_to_rgb(color1)
        rgb2 = self._hex_to_rgb(color2)
        r = int(rgb1[0] + (rgb2[0] - rgb1[0]) * ratio)
        g = int(rgb1[1] + (rgb2[1] - rgb1[1]) * ratio)
        b = int(rgb1[2] + (rgb2[2] - rgb1[2]) * ratio)
        return self._rgb_to_hex((r, g, b))
    
    def _on_canvas_resize(self, event):
        """Handle canvas resize - redraw gradient if width changed significantly."""
        if not self.level_canvas or self._destroyed:
            return
        
        # print(f"[Perf] Canvas resize event: {event.width}x{event.height}")
        
        new_width = event.width
        # Only redraw if width changed by more than 10 pixels (avoid excessive redraws)
        if abs(new_width - self._canvas_drawn_width) > 10:
            self._draw_level_grid()
    
    def _draw_level_grid(self):
        """Draw gradient background and grid lines on canvas (called once or on resize).
        
        Uses pre-rendered gradient rectangles for efficient updates.
        The gradient goes: green (0%) -> yellow (50%) -> red (100%)
        A cover rectangle is moved during updates to reveal the gradient.
        """
        if not self.level_canvas:
            return
        
        # Get actual canvas dimensions
        canvas_width = self.level_canvas.winfo_width()
        canvas_height = self.level_canvas.winfo_height()
        
        # Fallback if not yet mapped
        if canvas_width < 10:
            canvas_width = 400
        if canvas_height < 5:
            canvas_height = 12
        
        # Track drawn width for resize detection
        self._canvas_drawn_width = canvas_width
        
        bar_top = 1
        bar_bottom = canvas_height - 1
        
        # Clear existing drawings before redrawing
        self.level_canvas.delete("gradient")
        self.level_canvas.delete("level_cover")
        self.level_canvas.delete("grid")
        
        # Grid settings - optimization: use larger step for gradient to reduce object count
        step = 4
        
        # Draw gradient as vertical rectangles
        # This is done once at init/resize
        for x in range(0, canvas_width, step):
            # Calculate color for the start of the block
            ratio = x / max(canvas_width - 1, 1)
            if ratio < 0.5:
                # Green to Yellow (0-50%)
                color = self._interpolate_color(
                    self.colors.green,
                    self.colors.accent_yellow,
                    ratio * 2
                )
            else:
                # Yellow to Red (50-100%)
                color = self._interpolate_color(
                    self.colors.accent_yellow,
                    self.colors.red,
                    (ratio - 0.5) * 2
                )
            
            # Draw rectangle for this segment
            # Extend width by step to fill gaps
            self.level_canvas.create_rectangle(
                x, bar_top, x + step, bar_bottom,
                fill=color, outline="", tags="gradient"
            )
        
        # Create cover rectangle (initially covers everything - shows no level)
        self.level_canvas.create_rectangle(
            0, bar_top, canvas_width, bar_bottom,
            fill=self.colors.surface1, outline="", tags="level_cover"
        )
        
        # Draw grid lines on top of everything
        segment_width = canvas_width // 10
        for i in range(11):  # 11 lines for 10 segments (0 to 10 inclusive)
            x = i * segment_width
            self.level_canvas.create_line(
                x, 0, x, canvas_height,
                fill=self.colors.surface2, width=1, tags="grid"
            )
    
    def _update_level_display(self, level: float):
        """Update the level meter display.
        
        For canvas style: Uses efficient cover-moving approach.
        The gradient is pre-rendered once in _draw_level_grid().
        We just move the cover rectangle to reveal the appropriate portion.
        This is O(1) per frame - only one coordinate change.
        """
        if self._destroyed:
            return
        
        try:
            if self.meter_style == "progressbar" and self.level_bar:
                # Simple progressbar update - just set value, no color change
                # (matches transcription_popup.py style - fixed accent color)
                self.level_bar.set(level)
                
            elif self.level_canvas:
                # Efficient canvas update: just move the cover rectangle
                canvas_width = self.level_canvas.winfo_width() or 400
                canvas_height = self.level_canvas.winfo_height() or 12
                bar_top = 1
                bar_bottom = canvas_height - 1
                
                # Calculate where the cover should start (reveals gradient up to this point)
                reveal_x = int(level * canvas_width)
                
                # Move cover to reveal the gradient up to reveal_x
                # Cover starts at reveal_x and goes to canvas_width
                self.level_canvas.coords(
                    "level_cover",
                    reveal_x, bar_top, canvas_width, bar_bottom
                )
                    
        except Exception:
            pass
    
    # =========================================================================
    # Recording Controls
    # =========================================================================
    
    def _start_recording(self):
        """Start audio recording."""
        if not self.recorder or self.is_recording:
            return
        
        try:
            # Unified stream architecture: recording is just a flag toggle
            # Stream is already open, level meter continues working
            if self.recorder.start_recording_unified():
                self.is_recording = True
                self.recording_start_time = time.time()
                
                # Update UI
                self.record_btn.configure(state="disabled")
                self.stop_btn.configure(state="normal")
                
                # Start duration update
                self._update_duration()
                
                # Level meter already running via _start_continuous_level_updates
                self._update_status("Recording...", self.colors.red)
                print("[AudioAnalyzer] Recording started (unified stream)")
            else:
                self._update_status("Failed to start recording", self.colors.red)
                
        except Exception as e:
            logging.error(f"[AudioAnalyzer] Recording error: {e}")
            self._update_status(f"Recording error: {e}", self.colors.red)
    
    def _start_recording_level_updates(self):
        """Start polling the recorder's level during recording."""
        if not self.is_recording or self._destroyed:
            return
        
        try:
            # Poll the recorder's current level (updated by recording callback)
            level = self.recorder.get_level()
            
            # Apply our amplification and smoothing
            amplified = min(1.0, level * self.LEVEL_AMPLIFICATION)
            smoothed = (self._current_level * self.LEVEL_SMOOTHING +
                       amplified * (1.0 - self.LEVEL_SMOOTHING))
            self._current_level = smoothed
            
            # Update display
            self._update_level_display(smoothed)
            
            # Schedule next update
            self.root.after(self.LEVEL_UPDATE_INTERVAL, self._start_recording_level_updates)
            
        except Exception as e:
            logging.debug(f"[AudioAnalyzer] Level update error: {e}")
    
    def _stop_recording(self):
        """Stop audio recording."""
        if not self.recorder or not self.is_recording:
            return
        
        try:
            # Unified stream: recording is just a flag, stream stays open
            wav_data = self.recorder.stop_recording_unified()
            self.is_recording = False
            
            # Level meter continues running via _start_continuous_level_updates
            # No need to reset level display - it will show live input level
            
            if wav_data:
                self.recorded_wav = wav_data
                
                # Calculate duration from data
                from ...audio.recorder import get_audio_duration
                self.audio_duration = get_audio_duration(wav_data)
                
                logging.info(f"[AudioAnalyzer] Recording stopped (unified): {len(wav_data)} bytes, {self.audio_duration:.1f}s")
                print(f"[AudioAnalyzer] Recording stopped (unified): {len(wav_data)} bytes, {self.audio_duration:.1f}s")
                
                # Update compression estimate
                self._update_size_estimate()
                
                # Enable playback and send
                self._enable_audio_controls()
                
                self._update_status(f"Recorded {self._format_duration(self.audio_duration)}", self.colors.green)
            else:
                logging.warning("[AudioAnalyzer] No WAV data returned from stop_recording_unified")
                self._update_status("No audio recorded", self.colors.accent_yellow)
            
            # Update UI
            self.record_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            
        except Exception as e:
            logging.error(f"[AudioAnalyzer] Stop recording error: {e}")
            self._update_status(f"Error: {e}", self.colors.red)
    
    def _update_duration(self):
        """Update duration display during recording."""
        if not self.is_recording or self._destroyed:
            return
        
        elapsed = time.time() - self.recording_start_time
        self.duration_label.configure(text=self._format_duration(elapsed))
        
        # Schedule next update
        self.root.after(self.DURATION_UPDATE_INTERVAL, self._update_duration)
    
    def _format_duration(self, seconds: float) -> str:
        """Format duration as HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    def _format_short_duration(self, seconds: float) -> str:
        """Format duration as MM:SS."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"
    
    def _enable_audio_controls(self):
        """Enable playback and send controls after recording."""
        if self.play_btn: self.play_btn.configure(state="normal")
        if self.seek_slider: self.seek_slider.configure(state="normal")
        if self.send_btn: self.send_btn.configure(state="normal")
        if self.clear_btn: self.clear_btn.configure(state="normal")
        
        # Update position label
        if self.position_label:
            duration_str = self._format_short_duration(self.audio_duration)
            self.position_label.configure(text=f"00:00 / {duration_str}")
    
    def _clear_audio(self):
        """Clear recorded audio."""
        # Stop playback if playing
        if self.is_playing:
            self._stop_playback()
        
        self.recorded_wav = None
        self.compressed_audio = None
        self.audio_duration = 0.0
        
        # Reset UI
        self.duration_label.configure(text="00:00:00")
        self.position_label.configure(text="00:00 / 00:00")
        self.seek_slider.set(0)
        self.size_label.configure(text="")
        
        # Disable controls
        self.play_btn.configure(state="disabled")
        self.pause_btn.configure(state="disabled")
        self.seek_slider.configure(state="disabled")
        self.send_btn.configure(state="disabled")
        self.clear_btn.configure(state="disabled")
        
        # Clear result
        self.result_text_widget.configure(state=tk.NORMAL)
        self.result_text_widget.delete("1.0", tk.END)
        self.result_text_widget.insert("1.0", "(Transcription/analysis result will appear here)")
        self.result_text_widget.configure(state=tk.DISABLED, fg=self.colors.overlay0)
        self.copy_btn.configure(state="disabled")
        
        self._update_status("Audio cleared")
    
    # =========================================================================
    # Playback Controls
    # =========================================================================
    
    def _play_audio(self):
        """Start or resume audio playback."""
        if not self.recorder or not self.recorded_wav:
            return
        
        try:
            # Get audio to play (compressed if enabled, otherwise raw)
            audio_to_play = self._get_playback_audio()
            if not audio_to_play:
                return
            
            position = self.playback_position if self.is_playing else 0.0
            
            if self.recorder.play(audio_to_play, position):
                self.is_playing = True
                self.play_btn.configure(state="disabled")
                self.pause_btn.configure(state="normal")
                
                # Start position update
                self._update_playback_position()
                
                self._update_status("Playing...")
                
        except Exception as e:
            logging.error(f"[AudioAnalyzer] Playback error: {e}")
            self._update_status(f"Playback error: {e}", self.colors.red)
    
    def _pause_audio(self):
        """Pause audio playback."""
        if not self.recorder:
            return
        
        self.recorder.pause()
        self.playback_position = self.recorder.get_playback_position()
        
        self.play_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled")
        
        self._update_status("Paused")
    
    def _stop_playback(self):
        """Stop audio playback."""
        if not self.recorder:
            return
        
        self.recorder.stop_playback()
        self.is_playing = False
        self.playback_position = 0.0
        
        self.play_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled")
        self.seek_slider.set(0)
    
    def _on_seek(self, value):
        """Handle seek slider change."""
        if not self.recorder or self.audio_duration <= 0:
            return
        
        position = (value / 100.0) * self.audio_duration
        self.playback_position = position
        
        if self.is_playing:
            self.recorder.seek(position)
        
        # Update position label
        pos_str = self._format_short_duration(position)
        dur_str = self._format_short_duration(self.audio_duration)
        self.position_label.configure(text=f"{pos_str} / {dur_str}")
    
    def _update_playback_position(self):
        """Update playback position display."""
        if not self.is_playing or self._destroyed or not self.recorder:
            return
        
        if not self.recorder.is_playing():
            # Playback finished
            self.is_playing = False
            self.play_btn.configure(state="normal")
            self.pause_btn.configure(state="disabled")
            self.seek_slider.set(0)
            self.playback_position = 0.0
            self._update_status("Playback complete")
            return
        
        position = self.recorder.get_playback_position()
        self.playback_position = position
        
        # Update slider
        if self.audio_duration > 0:
            slider_value = (position / self.audio_duration) * 100
            self.seek_slider.set(slider_value)
        
        # Update label
        pos_str = self._format_short_duration(position)
        dur_str = self._format_short_duration(self.audio_duration)
        self.position_label.configure(text=f"{pos_str} / {dur_str}")
        
        # Schedule next update
        self.root.after(100, self._update_playback_position)
    
    def _get_playback_audio(self) -> Optional[bytes]:
        """Get audio data for playback (compressed if enabled)."""
        if not self.recorded_wav:
            return None
        
        if self.compression_enabled:
            if not self.compressed_audio:
                # Compress on first playback
                self.compressed_audio = self.recorder.compress_audio(
                    self.recorded_wav,
                    self.compression_preset
                )
            return self.compressed_audio or self.recorded_wav
        
        return self.recorded_wav
    
    # =========================================================================
    # Compression
    # =========================================================================
    
    def _on_compression_toggled(self):
        """Handle compression checkbox toggle."""
        self.compression_enabled = self.compression_var.get()
        self.compressed_audio = None  # Clear cached compressed audio
        self._update_size_estimate()
    
    def _on_preset_changed(self, preset_name: str):
        """Handle compression preset change."""
        from ...audio.recorder import COMPRESSION_PRESETS
        
        # Find preset key by name
        for key, preset in COMPRESSION_PRESETS.items():
            if preset.get("name") == preset_name:
                self.compression_preset = key
                self.compressed_audio = None  # Clear cached
                self._update_size_estimate()
                
                # Update description label
                desc = preset.get("description", "")
                if self.preset_desc_label:
                    self.preset_desc_label.configure(text=f"• {desc}" if desc else "")
                break
    
    def _update_size_estimate(self):
        """Update the size estimation display."""
        if not self.recorded_wav or not self.size_label:
            return
        
        original_size = len(self.recorded_wav)
        original_mb = original_size / (1024 * 1024)
        
        text = ""
        if self.compression_enabled and self.recorder:
            estimated = self.recorder.estimate_compressed_size(
                self.recorded_wav,
                self.compression_preset
            )
            estimated_mb = estimated / (1024 * 1024)
            
            from ...audio.recorder import COMPRESSION_PRESETS
            preset = COMPRESSION_PRESETS.get(self.compression_preset, {})
            ext = preset.get("output_ext", ".ogg").upper().lstrip(".")
            
            text = f"{original_mb:.1f} MB → ~{estimated_mb:.2f} MB ({ext})"
        else:
            text = f"{original_mb:.1f} MB (WAV)"
            
        # Handle label update
        try:
            self.size_label.configure(text=text)
        except Exception:
            # Fallback for standard Tk label if configure fails differently
            pass
    
    # =========================================================================
    # Event Handlers
    # =========================================================================
    
    def _on_provider_changed(self, provider: str):
        """Handle provider dropdown change."""
        self.provider = provider
        self.model = self.config.get(f"{provider}_model", "")
        self.model_dropdown.set(self.model or "(loading...)")
        
        # Reload models for new provider
        threading.Thread(target=self._load_models, daemon=True).start()
    
    def _on_model_changed(self, model: str):
        """Handle model selection change."""
        if model and model not in ("(loading...)", "(no models)", "(no audio models found)"):
            self.model = model
            # Ensure calling code knows about manually typed models
    
    def _on_device_changed(self, device_name: str):
        """Handle device dropdown change."""
        if hasattr(self, '_device_map') and device_name in self._device_map:
            self.current_device = self._device_map[device_name]
            # _update_recorder_device now handles starting level monitoring
            self._update_recorder_device()
    
    def _on_device_type_changed(self):
        """Handle device type radio button change."""
        self._refresh_devices()
    
    def _on_action_click(self, action_key: str):
        """Handle action button click (selects action, does not send)."""
        self.selected_action_key = action_key
        
        # Update indicator text
        if self.action_indicator_label:
            try:
                if HAVE_CTK:
                    self.action_indicator_label.configure(text=f"Action: {action_key}")
                else:
                    self.action_indicator_label.configure(text=f"Action: {action_key}")
            except Exception:
                pass
        
        # Focus custom input if custom action selected
        if action_key in ["_Custom", "_Ask"] and self.custom_input:
            try:
                self.custom_input.focus_set()
            except Exception:
                pass

    def _on_custom_input_set(self, event=None):
        """Handle custom input set action."""
        if self.custom_input:
            try:
                text = self.custom_input.get().strip()
                if text:
                    self.selected_action_key = "_Custom"
                    if self.action_indicator_label:
                        self.action_indicator_label.configure(text="Action: Custom Task")
            except Exception:
                pass
    
    def _on_modifiers_changed(self, active_modifiers: List[str]):
        """Handle modifier toggle changes."""
        self.active_modifiers = active_modifiers
    
    # =========================================================================
    # Model Loading
    # =========================================================================
    
    def _load_models(self):
        """Load available models in background."""
        if self._destroyed:
            return
        
        try:
            from ...api_client import fetch_models
            
            try:
                # Pass current provider to fetch correct models
                models, error = fetch_models(
                    self.config,
                    self.key_managers,
                    provider_override=self.provider
                )
            except Exception as e:
                logging.error(f"[AudioAnalyzer] fetch_models failed: {e}")
                error = str(e)
                models = None
            
            if models and not error and not self._destroyed:
                # Filter for audio-capable models if OpenRouter
                if self.provider == "openrouter":
                    models = self._filter_audio_models(models)
                
                self.available_models = [m['id'] for m in models]
                
                # If no models found (e.g. filtered out), show indicator
                if not self.available_models:
                    self.available_models = ["(no audio models found)"]
                
                def update_dropdown():
                    if self._destroyed or not self.model_dropdown:
                        return
                    
                    # Log for debugging
                    logging.info(f"[AudioAnalyzer] Updating dropdown with {len(self.available_models)} models")
                    
                    try:
                        self.model_dropdown.configure(values=self.available_models)
                        
                        # If current model is in list, keep it. If not, pick first.
                        # Also support keeping manually entered model if it's not in the list but valid context
                        if self.model and self.model in self.available_models:
                            self.model_dropdown.set(self.model)
                        elif self.available_models:
                            # Auto-select first if current invalid
                            # But skip if current is "user typed" (we don't strictly validate that here yet,
                            # relying on it being non-empty. But if they switch provider, we probably want to reset.)
                            self.model_dropdown.set(self.available_models[0])
                            self.model = self.available_models[0]
                        
                        # Handle empty/helper selection
                        if self.available_models == ["(no audio models found)"]:
                            self.model_dropdown.set("(no audio models found)")
                            self.model = ""
                    except Exception:
                        pass
                
                # Use GUICoordinator for thread-safe UI update
                GUICoordinator.get_instance().run_on_gui_thread(update_dropdown)
            elif self.model:
                # Fallback to configured model if fetch failed
                self.available_models = [self.model]
                
                def set_fallback():
                    if self.model_dropdown:
                        try:
                            self.model_dropdown.configure(values=self.available_models)
                            self.model_dropdown.set(self.model)
                        except Exception:
                            pass
                
                GUICoordinator.get_instance().run_on_gui_thread(set_fallback)
                
        except Exception as e:
            logging.error(f"[AudioAnalyzer] Model loading error: {e}")
            import traceback
            traceback.print_exc()
            
            # Fallback
            if self.model:
                self.available_models = [self.model]
                def set_fallback_exc():
                    if self.model_dropdown:
                        try:
                            self.model_dropdown.configure(values=self.available_models)
                            self.model_dropdown.set(self.model)
                        except Exception:
                            pass
                
                GUICoordinator.get_instance().run_on_gui_thread(set_fallback_exc)
    
    def _filter_audio_models(self, models: List[Dict]) -> List[Dict]:
        """Filter OpenRouter models to those supporting audio input."""
        return [
            m for m in models
            if 'audio' in m.get('architecture', {}).get('input_modalities', [])
        ]
    
    # =========================================================================
    # Send Audio for Analysis
    # =========================================================================
    
    def _send_audio(self, action_key: str = None):
        """Send audio to AI for analysis."""
        # Use selected action if not provided
        if action_key is None:
            action_key = self.selected_action_key
            
        if not self.recorded_wav or self.is_processing:
            return
        
        self.is_processing = True
        self._update_status("Processing...", self.colors.accent)
        self.send_btn.configure(state="disabled")
        
        # Get custom input text (must be done on main thread)
        custom_text = None
        if self.custom_input:
            try:
                raw_text = self.custom_input.get()
                # Filter out placeholder text
                if raw_text and raw_text != "Custom task or question...":
                    custom_text = raw_text.strip()
            except Exception:
                pass
        
        # Determine audio data and mime type
        audio_data = self.recorded_wav
        mime_type = "audio/wav"
        
        if self.compression_enabled:
            # Compress in background if needed
            threading.Thread(
                target=self._prepare_and_send_audio,
                args=(action_key, custom_text),
                daemon=True
            ).start()
        else:
            # Run in background thread
            threading.Thread(
                target=self._process_or_callback,
                args=(action_key, audio_data, mime_type, custom_text),
                daemon=True
            ).start()

    def _prepare_and_send_audio(self, action_key: str, custom_text: Optional[str] = None):
        """Compress audio then process."""
        try:
            if not self.compressed_audio:
                self.compressed_audio = self.recorder.compress_audio(
                    self.recorded_wav,
                    self.compression_preset
                )
            
            audio_data = self.compressed_audio or self.recorded_wav
            
            from ...audio.recorder import COMPRESSION_PRESETS
            preset = COMPRESSION_PRESETS.get(self.compression_preset, {})
            mime_type = "audio/ogg" if preset.get("output_ext", ".ogg") == ".ogg" else "audio/mpeg"
            
            self._process_or_callback(action_key, audio_data, mime_type, custom_text)
            
        except Exception as e:
            logging.error(f"[AudioAnalyzer] Compression error: {e}")
            GUICoordinator.get_instance().run_on_gui_thread(
                lambda: self._update_status(f"Compression error: {e}", self.colors.red)
            )
            self.is_processing = False
            GUICoordinator.get_instance().run_on_gui_thread(
                lambda: self.send_btn.configure(state="normal")
            )

    def _process_or_callback(self, action_key, audio_data, mime_type, custom_text: Optional[str] = None):
        """Delegate to callback or process internally."""
        # Check action config for show_chat_window preference
        actions = self.prompts.get_audio_actions()
        action = actions.get(action_key, {})
        
        # Determine strict response mode
        show_chat = True # Default fallback
        
        mode = "default"
        if self.response_mode_toggle:
            mode = self.response_mode_toggle.get()
            
        if mode == "result":
            show_chat = False
        elif mode == "show":
            show_chat = True
        else:
            # Default behavior (follow config)
            show_chat = action.get("show_chat_window", True)

        if self.on_action_callback and show_chat:
            # Delegate to callback (GUI Controller mode) - ONLY if show_chat_window is True
            try:
                self.on_action_callback(
                    action_key=action_key,
                    audio_data=audio_data,
                    mime_type=mime_type,
                    custom_input=custom_text,
                    duration=self.audio_duration,
                    compressed=self.compression_enabled,
                    provider=self.provider,
                    model=self.model
                )
                
                # Reset processing state
                self.is_processing = False
                GUICoordinator.get_instance().run_on_gui_thread(
                    lambda: self.send_btn.configure(state="normal")
                )
                GUICoordinator.get_instance().run_on_gui_thread(
                    lambda: self._update_status("Sent to AI", self.colors.green)
                )
                
            except Exception as e:
                logging.error(f"[AudioAnalyzer] Callback error: {e}")
                self.is_processing = False
                GUICoordinator.get_instance().run_on_gui_thread(
                    lambda: self.send_btn.configure(state="normal")
                )
                GUICoordinator.get_instance().run_on_gui_thread(
                    lambda: self._update_status(f"Error: {e}", self.colors.red)
                )
        else:
            # Process internally (Standalone mode OR show_chat_window=False)
            self._process_audio_internal(action_key, audio_data, mime_type, custom_text)

    def _process_audio_internal(self, action_key: str, audio_data: bytes, mime_type: str, custom_text: Optional[str] = None):
        """Process audio internally."""
        temp_file_path = None
        try:
            from ...request_pipeline import RequestPipeline, RequestContext, RequestOrigin, StreamCallback
            from ...messages import build_audio_message, build_file_message
            from ...api_client import get_provider_for_type
            import tempfile
            import os
            from pathlib import Path
            
            # Get action config
            actions = self.prompts.get_audio_actions()
            action = actions.get(action_key, {})
            
            system_prompt = action.get("system_prompt", "You are an audio analysis assistant.")
            task = action.get("task", "Analyze this audio.")
            
            if action_key in ["_Custom", "_Ask"]:
                # Use custom task template
                template = self.prompts.get_audio_setting("custom_task_template", "Regarding this audio: {custom_input}")
                if custom_text:
                    task = template.replace("{custom_input}", custom_text)
                else:
                    task = "Analyze this audio."
            elif custom_text:
                # Optionally append custom text to other tasks if needed,
                # but currently only _Custom/_Ask uses it explicitly.
                pass
            
            # Apply modifier injections
            if self.active_modifiers:
                modifier_injections = self._build_modifier_injections()
                if modifier_injections:
                    system_prompt = system_prompt + "\n\n" + modifier_injections
            
            messages = []
            
            # Check for large file support if provider is google
            # Gemini Native limit for inline data is ~15MB (safety margin)
            is_large_file = len(audio_data) > 15 * 1024 * 1024
            
            if self.provider == "google" and is_large_file:
                GUICoordinator.get_instance().run_on_gui_thread(
                    lambda: self._update_status("Uploading large file...", self.colors.accent)
                )
                
                # Determine extension based on mime_type
                ext = ".wav"
                if "ogg" in mime_type:
                    ext = ".ogg"
                elif "mpeg" in mime_type or "mp3" in mime_type:
                    ext = ".mp3"
                
                # Create temp file
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
                        f.write(audio_data)
                        temp_file_path = f.name
                    
                    # Get provider to use upload_file
                    key_manager = self.key_managers.get("google")
                    if key_manager:
                        provider = get_provider_for_type("google", key_manager, self.config)
                        
                        # Upload
                        uploaded_file, error = provider.upload_file(Path(temp_file_path))
                        
                        if uploaded_file:
                            messages = build_file_message(uploaded_file.uri, mime_type, task, system_prompt)
                            logging.info(f"[AudioAnalyzer] Uploaded large file: {uploaded_file.uri}")
                        else:
                            logging.error(f"[AudioAnalyzer] Upload failed: {error}")
                            # Will fallback to inline below
                except Exception as e:
                    logging.error(f"[AudioAnalyzer] File upload preparation failed: {e}")
                finally:
                    # Clean up temp file
                    if temp_file_path and os.path.exists(temp_file_path):
                        try:
                            os.unlink(temp_file_path)
                        except Exception:
                            pass
            
            if not messages:
                # Build message with inline audio (fallback or small file)
                audio_b64 = base64.b64encode(audio_data).decode('utf-8')
                messages = build_audio_message(audio_b64, mime_type, task, system_prompt)
            
            # Create request context
            ctx = RequestContext(
                origin=RequestOrigin.AUDIO_TOOL,
                provider=self.provider,
                model=self.model,
                streaming=self.config.get("streaming_enabled", True),
                thinking_enabled=self.config.get("thinking_enabled", False)
            )
            
            # For now, use non-streaming for simplicity
            ctx = RequestPipeline.execute_simple(
                ctx,
                messages,
                self.config,
                self.ai_params,
                self.key_managers
            )
            
            # Update UI on main thread
            def update_result():
                if self._destroyed:
                    return
                
                if ctx.error:
                    self._update_status(f"Error: {ctx.error}", self.colors.red)
                    self.result_text_widget.configure(state=tk.NORMAL)
                    self.result_text_widget.delete("1.0", tk.END)
                    self.result_text_widget.insert("1.0", f"Error: {ctx.error}")
                    self.result_text_widget.configure(state=tk.DISABLED, fg=self.colors.red)
                else:
                    self.result_text = ctx.response_text
                    self.result_text_widget.configure(state=tk.NORMAL, fg=self.colors.text)
                    self.result_text_widget.delete("1.0", tk.END)
                    self.result_text_widget.insert("1.0", ctx.response_text)
                    self.result_text_widget.configure(state=tk.DISABLED)
                    self.copy_btn.configure(state="normal")
                    
                    tokens = ctx.total_tokens
                    self._update_status(f"✅ Complete ({tokens} tokens)", self.colors.green)
                
                self.is_processing = False
                self.send_btn.configure(state="normal")
            
            GUICoordinator.get_instance().run_on_gui_thread(update_result)
            
        except Exception as e:
            logging.error(f"[AudioAnalyzer] Processing error: {e}")
            
            def show_error():
                if not self._destroyed:
                    self._update_status(f"Error: {e}", self.colors.red)
                    self.is_processing = False
                    self.send_btn.configure(state="normal")
            
            GUICoordinator.get_instance().run_on_gui_thread(show_error)
    
    def _build_modifier_injections(self) -> str:
        """Build modifier injection text."""
        modifier_defs = self.prompts.get_modifiers()
        injections = []
        for mod in modifier_defs:
            if mod.get("key") in self.active_modifiers:
                injection = mod.get("injection", "")
                if injection:
                    injections.append(injection)
        return "\n".join(injections)
    
    def _copy_result(self):
        """Copy result text to clipboard."""
        if not self.result_text:
            return
        
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.result_text)
            self._update_status("✅ Copied to clipboard", self.colors.green)
        except Exception as e:
            self._update_status(f"Copy failed: {e}", self.colors.red)
    
    # =========================================================================
    # Status & Cleanup
    # =========================================================================
    
    def _update_status(self, text: str, color: str = None):
        """Update status bar."""
        if self.status_label and not self._destroyed:
            self.status_label.configure(text=text)
            
            # Map CTk text_color to Tk fg for compatibility
            kwargs = {}
            if color:
                if HAVE_CTK:
                    kwargs["text_color"] = color
                else:
                    kwargs["fg"] = color
            else:
                if HAVE_CTK:
                    kwargs["text_color"] = self.colors.overlay0
                else:
                    kwargs["fg"] = self.colors.overlay0
            
            self.status_label.configure(**kwargs)
    
    def _close(self):
        """Close window and cleanup."""
        self._destroyed = True
        
        # Stop unified stream first
        if self.recorder:
            self.recorder.stop_stream()
            print("[AudioAnalyzer] Unified stream stopped on close")
        
        # Stop recording/playback and cleanup
        if self.recorder:
            self.recorder.cleanup()
            self.recorder = None
        
        unregister_window(self._get_window_tag())
        
        if self.on_close_callback:
            self.on_close_callback()
        
        try:
            if self.root:
                self.root.destroy()
        except tk.TclError:
            pass
        
        self.root = None


def create_audio_analyzer_window(
    parent_root: tk.Tk,
    config: Dict[str, Any],
    ai_params: Dict[str, Any],
    key_managers: Dict[str, Any],
    on_close: Optional[Callable[[], None]] = None,
    on_action: Optional[Callable] = None
) -> AudioAnalyzerWindow:
    """
    Create an audio analyzer window.
    
    Args:
        parent_root: Parent Tk root
        config: Application configuration
        ai_params: AI parameters
        key_managers: Key manager instances
        on_close: Optional close callback
        on_action: Optional action callback
        
    Returns:
        The created window instance
    """
    return AudioAnalyzerWindow(
        parent_root, config, ai_params, key_managers, on_close, on_action
    )
