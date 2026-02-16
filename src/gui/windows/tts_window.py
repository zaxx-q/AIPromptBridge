#!/usr/bin/env python3
"""
TTS (Text-to-Speech) Window for Gemini TTS generation.

A full window (visible in taskbar) providing:
- Input text display (editable)
- Voice selector (30 prebuilt voices)
- Model selector (flash/pro TTS)
- Single/Multi-speaker toggle
- AI Director panel for style generation
- Audio playback with seek bar
- Save/Export as WAV

Threading Note:
    This must be created on the GUI thread via GUICoordinator.
"""

import logging
import os
import threading
import time
import tkinter as tk
from datetime import datetime
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
from ..prompts import get_prompts_config
from ..emoji_renderer import prepare_emoji_content
from .utils import set_window_icon
from ...audio.tts_constants import TTS_MODELS, TTS_VOICES, get_voice_list, get_voice_details
from ...audio.recorder import AudioRecorder


class TTSWindow:
    """
    Full window for TTS (Text-to-Speech) generation using Gemini TTS models.
    
    Features:
    - Editable input text area
    - Voice selection from 30 prebuilt voices
    - Model selection (flash/pro TTS)
    - Single/Multi-speaker mode toggle
    - AI Director for automated style instruction generation
    - Audio playback with play/pause/seek
    - Save as WAV export
    """
    
    # TTS models available
    TTS_MODELS = TTS_MODELS
    
    def __init__(
        self,
        parent_root: tk.Tk,
        config: Dict[str, Any],
        ai_params: Dict[str, Any],
        key_managers: Dict[str, Any],
        initial_text: str = "",
        on_close: Optional[Callable[[], None]] = None
    ):
        """
        Initialize the TTS window.
        
        Args:
            parent_root: Parent Tk root (from GUICoordinator)
            config: Application configuration dictionary
            ai_params: AI parameters dictionary
            key_managers: Dictionary of KeyManager instances
            initial_text: Text to pre-fill in the input area
            on_close: Optional callback when window closes
        """
        self.parent_root = parent_root
        self.config = config
        self.ai_params = ai_params
        self.key_managers = key_managers
        self.initial_text = initial_text
        self.on_close_callback = on_close
        
        self.window_id = get_next_window_id()
        self.colors = get_colors()
        self._destroyed = False
        
        # Prompts config
        self.prompts = get_prompts_config()
        
        # TTS state
        self.selected_voice = config.get("tts_default_voice", "Kore")
        self.selected_model = config.get("tts_default_model", self.TTS_MODELS[0])
        
        self.is_multi_speaker = False
        self.speaker1_name = "Speaker1"
        self.speaker2_name = "Speaker2"
        self.speaker1_voice = self.selected_voice
        self.speaker2_voice = "Puck"
        
        # AI Director state
        self.director_enabled = config.get("tts_director_enabled", True)
        self.director_auto_mode = config.get("tts_director_auto_mode", False)
        self.director_model = config.get("tts_director_model", "")
        
        # Audio state
        self.pcm_audio: Optional[bytes] = None
        self.wav_audio: Optional[bytes] = None
        self.audio_duration = 0.0
        
        try:
            self.recorder = AudioRecorder()
        except Exception:
            self.recorder = None
            
        self.is_playing = False
        self.playback_position = 0.0
        
        # Processing state
        self.is_generating = False
        self.is_directing = False
        
        # UI references
        self.root = None
        self._init_ui_refs()
        
        self._create_window()
    
    def _init_ui_refs(self):
        """Initialize UI element references."""
        self.input_textbox = None
        self.voice_dropdown = None
        self.model_dropdown = None
        self.speaker_mode_toggle = None
        self.multi_speaker_frame = None
        self.speaker1_name_entry = None
        self.speaker2_name_entry = None
        self.speaker1_voice_dropdown = None
        self.speaker2_voice_dropdown = None
        self.style_textbox = None
        self.director_toggle = None
        self.director_model_dropdown = None
        self.generate_style_btn = None
        self.generate_audio_btn = None
        self.play_pause_btn = None
        self.seek_slider = None
        self.position_label = None
        self.format_dropdown = None
        self.save_btn = None
        self.status_label = None
    
    def _get_window_tag(self) -> str:
        """Return unique window tag."""
        return f"tts_window_{self.window_id}"
    
    def _create_window(self):
        """Create the main window."""
        if HAVE_CTK:
            sync_ctk_appearance()
            self.root = ctk.CTkToplevel(self.parent_root)
        else:
            self.root = tk.Toplevel(self.parent_root)
        
        self.root.title("🔊 Text-to-Speech")
        self.root.geometry("900x700")
        self.root.minsize(750, 600)
        
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
        if HAVE_CTK:
            self._build_ctk_ui()
        else:
            self._build_tk_fallback_ui()
        
        # Register and set close handler
        register_window(self._get_window_tag())
        self.root.protocol("WM_DELETE_WINDOW", self._close)
    
    def _build_tk_fallback_ui(self):
        """Build standard Tkinter fallback UI from separate module."""
        from .tts_window_tk import build_tk_ui
        build_tk_ui(self)
    
    def _build_ctk_ui(self):
        """Build CustomTkinter UI with two-column layout."""
        # === Bottom bar FIRST so it stays visible ===
        self._create_bottom_bar()
        
        # Main container
        main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Configure grid weights for two-column layout
        main_frame.grid_columnconfigure(0, weight=0, minsize=280)  # Left column - fixed width
        main_frame.grid_columnconfigure(1, weight=1)  # Right column - expands
        main_frame.grid_rowconfigure(1, weight=1)  # Content row expands
        
        # === Row 0: Top Action Bar ===
        self._create_top_action_bar(main_frame)
        
        # === Left Column (Controls) ===
        left_container = ctk.CTkFrame(main_frame, fg_color="transparent")
        left_container.grid(row=1, column=0, sticky="new", padx=(0, 5), pady=5)
        
        self._create_voice_section(left_container)
        self._create_speaker_mode_section(left_container)
        self._create_multi_speaker_section(left_container)
        self._create_preview_section(left_container)
        self._create_export_section(left_container)
        
        # === Right Column (Content & AI Director) ===
        right_container = ctk.CTkFrame(main_frame, fg_color="transparent")
        right_container.grid(row=1, column=1, sticky="nsew", padx=(5, 0), pady=5)
        right_container.grid_rowconfigure(0, weight=1)  # Input text expands
        right_container.grid_rowconfigure(1, weight=0)  # Director doesn't expand
        right_container.grid_columnconfigure(0, weight=1)
        
        self._create_input_text_section(right_container)
        self._create_director_section(right_container)
    
    # =========================================================================
    # Section Helpers
    # =========================================================================
    
    def _create_section_frame(self, parent, title: str) -> Any:
        """Create a titled section frame using pack layout."""
        frame = ctk.CTkFrame(
            parent,
            fg_color=self.colors.surface0,
            corner_radius=10,
            border_color=self.colors.surface2,
            border_width=1
        )
        frame.pack(fill="x", pady=(0, 8))
        
        ctk.CTkLabel(
            frame,
            text=title,
            font=get_ctk_font(size=12, weight="bold"),
            text_color=self.colors.accent
        ).pack(anchor="w", padx=12, pady=(10, 5))
        
        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.pack(fill="x", padx=12, pady=(0, 10))
        
        return content
    
    # =========================================================================
    # Top Action Bar
    # =========================================================================
    
    def _create_top_action_bar(self, parent):
        """Create top action bar with model selector and Generate Audio button."""
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        
        # Left side: Model selector
        left_frame = ctk.CTkFrame(bar, fg_color="transparent")
        left_frame.pack(side="left", fill="x", expand=True)
        
        ctk.CTkLabel(
            left_frame,
            text="TTS Model:",
            font=get_ctk_font(size=11),
            text_color=self.colors.text
        ).pack(side="left", padx=(0, 5))
        
        self.model_dropdown = ctk.CTkOptionMenu(
            left_frame,
            values=self.TTS_MODELS,
            command=self._on_model_changed,
            width=240,
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
        self.model_dropdown.set(self.selected_model)
        self.model_dropdown.pack(side="left")
        
        # Right side: Generate Audio button
        right_frame = ctk.CTkFrame(bar, fg_color="transparent")
        right_frame.pack(side="right")
        
        gen_content = prepare_emoji_content("🔊 Generate Audio", size=14)
        self.generate_audio_btn = ctk.CTkButton(
            right_frame,
            **gen_content,
            font=get_ctk_font(size=12, weight="bold"),
            width=160,
            height=38,
            corner_radius=8,
            command=self._on_generate_audio,
            **get_ctk_button_colors(self.colors, "success")
        )
        self.generate_audio_btn.pack(side="right")
    
    # =========================================================================
    # Left Column Sections
    # =========================================================================
    
    def _create_voice_section(self, parent):
        """Create voice selector section."""
        content = self._create_section_frame(parent, "Voice")
        
        # Build voice list with style descriptors
        voice_list = get_voice_list()
        
        self.voice_dropdown = ScrollableComboBox(
            content,
            colors=self.colors,
            values=voice_list,
            width=240,
            height=32,
            command=self._on_voice_changed
        )
        
        # Set default
        voice_data = get_voice_details(self.selected_voice)
        if voice_data["style"] != "Unknown":
            default_display = f"{self.selected_voice} — {voice_data['gender']}, {voice_data['style']}"
        else:
            default_display = self.selected_voice
            
        self.voice_dropdown.set(default_display)
        self.voice_dropdown.pack(fill="x")
    
    def _create_speaker_mode_section(self, parent):
        """Create speaker mode toggle section."""
        content = self._create_section_frame(parent, "Speaker Mode")
        
        self.speaker_mode_var = tk.StringVar(value="single")
        
        mode_row = ctk.CTkFrame(content, fg_color="transparent")
        mode_row.pack(fill="x")
        
        ctk.CTkRadioButton(
            mode_row,
            text="Single Speaker",
            variable=self.speaker_mode_var,
            value="single",
            command=self._on_speaker_mode_changed,
            font=get_ctk_font(size=11),
            text_color=self.colors.text,
            fg_color=self.colors.accent,
            hover_color=self.colors.lavender,
            border_color=self.colors.surface2
        ).pack(side="left", padx=(0, 15))
        
        ctk.CTkRadioButton(
            mode_row,
            text="Multi-Speaker (2)",
            variable=self.speaker_mode_var,
            value="multi",
            command=self._on_speaker_mode_changed,
            font=get_ctk_font(size=11),
            text_color=self.colors.text,
            fg_color=self.colors.accent,
            hover_color=self.colors.lavender,
            border_color=self.colors.surface2
        ).pack(side="left")
    
    def _create_multi_speaker_section(self, parent):
        """Create multi-speaker configuration (initially hidden)."""
        self.multi_speaker_frame = ctk.CTkFrame(
            parent,
            fg_color=self.colors.surface0,
            corner_radius=10,
            border_color=self.colors.surface2,
            border_width=1
        )
        # Initially hidden - pack/forget based on toggle
        
        ctk.CTkLabel(
            self.multi_speaker_frame,
            text="Multi-Speaker Config",
            font=get_ctk_font(size=12, weight="bold"),
            text_color=self.colors.accent
        ).pack(anchor="w", padx=12, pady=(10, 5))
        
        ms_content = ctk.CTkFrame(self.multi_speaker_frame, fg_color="transparent")
        ms_content.pack(fill="x", padx=12, pady=(0, 10))
        
        voice_list = get_voice_list()
        
        # Speaker 1
        s1_row = ctk.CTkFrame(ms_content, fg_color="transparent")
        s1_row.pack(fill="x", pady=(0, 5))
        
        ctk.CTkLabel(s1_row, text="Speaker 1:", font=get_ctk_font(size=10),
                     text_color=self.colors.overlay0).pack(side="left", padx=(0, 5))
        
        self.speaker1_name_entry = ctk.CTkEntry(
            s1_row, placeholder_text="Name...", width=80, height=28,
            font=get_ctk_font(size=10), border_color=self.colors.surface2
        )
        self.speaker1_name_entry.insert(0, self.speaker1_name)
        self.speaker1_name_entry.pack(side="left", padx=(0, 5))
        
        self.speaker1_voice_dropdown = ctk.CTkOptionMenu(
            s1_row, values=voice_list, width=140, height=28,
            corner_radius=6,
            fg_color=self.colors.surface1,
            button_color=self.colors.surface2,
            button_hover_color=self.colors.overlay0,
            dropdown_fg_color=self.colors.surface0,
            dropdown_hover_color=self.colors.surface1,
            text_color=self.colors.text,
            font=get_ctk_font(size=9)
        )
        
        s1_data = get_voice_details(self.speaker1_voice)
        if s1_data["style"] != "Unknown":
            s1_display = f"{self.speaker1_voice} — {s1_data['gender']}, {s1_data['style']}"
        else:
            s1_display = self.speaker1_voice
            
        self.speaker1_voice_dropdown.set(s1_display)
        self.speaker1_voice_dropdown.pack(side="left")
        
        # Speaker 2
        s2_row = ctk.CTkFrame(ms_content, fg_color="transparent")
        s2_row.pack(fill="x")
        
        ctk.CTkLabel(s2_row, text="Speaker 2:", font=get_ctk_font(size=10),
                     text_color=self.colors.overlay0).pack(side="left", padx=(0, 5))
        
        self.speaker2_name_entry = ctk.CTkEntry(
            s2_row, placeholder_text="Name...", width=80, height=28,
            font=get_ctk_font(size=10), border_color=self.colors.surface2
        )
        self.speaker2_name_entry.insert(0, self.speaker2_name)
        self.speaker2_name_entry.pack(side="left", padx=(0, 5))
        
        self.speaker2_voice_dropdown = ctk.CTkOptionMenu(
            s2_row, values=voice_list, width=140, height=28,
            corner_radius=6,
            fg_color=self.colors.surface1,
            button_color=self.colors.surface2,
            button_hover_color=self.colors.overlay0,
            dropdown_fg_color=self.colors.surface0,
            dropdown_hover_color=self.colors.surface1,
            text_color=self.colors.text,
            font=get_ctk_font(size=9)
        )
        s2_data = get_voice_details(self.speaker2_voice)
        if s2_data["style"] != "Unknown":
            s2_display = f"{self.speaker2_voice} — {s2_data['gender']}, {s2_data['style']}"
        else:
            s2_display = self.speaker2_voice
            
        self.speaker2_voice_dropdown.set(s2_display)
        self.speaker2_voice_dropdown.pack(side="left")
    
    def _create_preview_section(self, parent):
        """Create audio preview/playback section."""
        content = self._create_section_frame(parent, "Audio Preview")
        
        row_frame = ctk.CTkFrame(content, fg_color="transparent")
        row_frame.pack(fill="x")
        
        # Play/Pause button
        play_content = prepare_emoji_content("▶", size=14)
        self.play_pause_btn = ctk.CTkButton(
            row_frame,
            **play_content,
            width=40,
            height=32,
            corner_radius=6,
            command=self._toggle_playback,
            state="disabled",
            **get_ctk_button_colors(self.colors, "success")
        )
        self.play_pause_btn.pack(side="left", padx=(0, 8))
        
        # Seek slider
        self.seek_slider = ctk.CTkSlider(
            row_frame,
            from_=0, to=100,
            width=80, height=16,
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
            text="00:00 / 00:00",
            font=get_ctk_font(size=10),
            text_color=self.colors.overlay0
        )
        self.position_label.pack(side="left")
    
    def _create_export_section(self, parent):
        """Create save/export section."""
        content = self._create_section_frame(parent, "Export")
        
        # Format selection
        row = ctk.CTkFrame(content, fg_color="transparent")
        row.pack(fill="x", pady=(0, 5))
        
        ctk.CTkLabel(row, text="Format:", font=get_ctk_font(size=11),
                     text_color=self.colors.text).pack(side="left", padx=(0, 5))
        
        from ...audio.ffmpeg_utils import is_ffmpeg_available
        
        formats = ["WAV"]
        if is_ffmpeg_available():
            formats.extend(["MP3", "OGG", "FLAC", "AAC"])
            
        self.format_dropdown = ctk.CTkOptionMenu(
            row,
            values=formats,
            width=90,
            height=24,
            font=get_ctk_font(size=11),
            fg_color=self.colors.surface1,
            button_color=self.colors.surface2,
            button_hover_color=self.colors.overlay0,
            dropdown_fg_color=self.colors.surface0,
            text_color=self.colors.text
        )
        self.format_dropdown.set("WAV")
        self.format_dropdown.pack(side="left", fill="x", expand=True)

        save_content = prepare_emoji_content("💾 Save Audio", size=12)
        self.save_btn = ctk.CTkButton(
            content,
            **save_content,
            font=get_ctk_font(size=11),
            width=200,
            height=32,
            corner_radius=6,
            command=self._save_audio,
            state="disabled",
            **get_ctk_button_colors(self.colors, "secondary")
        )
        self.save_btn.pack(fill="x")
    
    # =========================================================================
    # Right Column Sections
    # =========================================================================
    
    def _create_input_text_section(self, parent):
        """Create editable input text section."""
        frame = ctk.CTkFrame(
            parent,
            fg_color=self.colors.surface0,
            corner_radius=10,
            border_color=self.colors.surface2,
            border_width=1
        )
        frame.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        
        ctk.CTkLabel(
            frame,
            text="Input Text",
            font=get_ctk_font(size=12, weight="bold"),
            text_color=self.colors.accent
        ).pack(anchor="w", padx=12, pady=(10, 5))
        
        self.input_textbox = ctk.CTkTextbox(
            frame,
            font=get_ctk_font(size=12),
            fg_color=self.colors.text_bg,
            text_color=self.colors.text,
            border_color=self.colors.surface2,
            border_width=1,
            corner_radius=8,
            wrap="word"
        )
        self.input_textbox.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        
        # Pre-fill with initial text
        if self.initial_text:
            self.input_textbox.insert("1.0", self.initial_text)
    
    def _create_director_section(self, parent):
        """Create AI Director panel."""
        frame = ctk.CTkFrame(
            parent,
            fg_color=self.colors.surface0,
            corner_radius=10,
            border_color=self.colors.surface2,
            border_width=1
        )
        frame.grid(row=1, column=0, sticky="nsew", pady=(5, 0))
        
        # Header row with title and mode toggle
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 5))
        
        ctk.CTkLabel(
            header,
            text="AI Director",
            font=get_ctk_font(size=12, weight="bold"),
            text_color=self.colors.accent
        ).pack(side="left")
        
        # Auto/Manual toggle
        self.director_auto_var = tk.BooleanVar(value=self.director_auto_mode)
        self.director_toggle = ctk.CTkCheckBox(
            header,
            text="Auto",
            variable=self.director_auto_var,
            font=get_ctk_font(size=10),
            text_color=self.colors.overlay0,
            fg_color=self.colors.accent,
            hover_color=self.colors.lavender,
            border_color=self.colors.surface2,
            checkmark_color=self.colors.base,
            width=24
        )
        self.director_toggle.pack(side="right")
        
        # Director controls row
        controls = ctk.CTkFrame(frame, fg_color="transparent")
        controls.pack(fill="x", padx=12, pady=(0, 5))
        
        # Director model override (optional)
        ctk.CTkLabel(
            controls,
            text="Director Model:",
            font=get_ctk_font(size=10),
            text_color=self.colors.overlay0
        ).pack(side="left", padx=(0, 5))
        
        self.director_model_entry = ctk.CTkEntry(
            controls,
            placeholder_text="(uses default provider)",
            width=160,
            height=28,
            font=get_ctk_font(size=10),
            border_color=self.colors.surface2
        )
        if self.director_model:
            self.director_model_entry.insert(0, self.director_model)
        self.director_model_entry.pack(side="left", padx=(0, 8))
        
        # Generate Style button
        style_content = prepare_emoji_content("🎬 Generate Style", size=12)
        self.generate_style_btn = ctk.CTkButton(
            controls,
            **style_content,
            font=get_ctk_font(size=10, weight="bold"),
            width=130,
            height=28,
            corner_radius=6,
            command=self._on_generate_style,
            **get_ctk_button_colors(self.colors, "primary")
        )
        self.generate_style_btn.pack(side="right")
        
        # Style instructions textbox
        self.style_textbox = ctk.CTkTextbox(
            frame,
            font=get_ctk_font(size=11),
            fg_color=self.colors.text_bg,
            text_color=self.colors.text,
            border_color=self.colors.surface2,
            border_width=1,
            corner_radius=8,
            height=120,
            wrap="word"
        )
        self.style_textbox.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.style_textbox.insert("1.0", "(Style instructions will appear here after clicking 'Generate Style', or you can write your own) \nClear this text or leave this text as is to have no style instructions applied to input text.")
    
    # =========================================================================
    # Bottom Bar
    # =========================================================================
    
    def _create_bottom_bar(self):
        """Create bottom bar with status."""
        bottom_frame = ctk.CTkFrame(
            self.root,
            fg_color=self.colors.surface0,
            corner_radius=0,
            height=40
        )
        bottom_frame.pack(fill="x", side="bottom")
        bottom_frame.pack_propagate(False)
        
        status_container = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        status_container.pack(fill="x", padx=15, pady=(8, 8))
        
        self.status_label = ctk.CTkLabel(
            status_container,
            text="Ready — Enter text and click Generate Audio",
            font=get_ctk_font(size=10),
            text_color=self.colors.overlay0
        )
        self.status_label.pack(side="left")
    
    # =========================================================================
    # Event Handlers
    # =========================================================================
    
    def _on_voice_changed(self, value: str):
        """Handle voice dropdown change."""
        # Extract voice name from "Name — Style" format
        if " — " in value:
            self.selected_voice = value.split(" — ")[0]
        else:
            self.selected_voice = value
    
    def _on_model_changed(self, value: str):
        """Handle model dropdown change."""
        self.selected_model = value
    
    def _on_speaker_mode_changed(self):
        """Handle speaker mode toggle."""
        mode = self.speaker_mode_var.get()
        self.is_multi_speaker = (mode == "multi")
        
        if self.is_multi_speaker:
            self.multi_speaker_frame.pack(fill="x", pady=(0, 8))
        else:
            self.multi_speaker_frame.pack_forget()
    
    def _get_multi_speaker_config(self) -> Optional[List[Dict]]:
        """Build multi-speaker config from UI entries."""
        if not self.is_multi_speaker:
            return None
        
        s1_name = self.speaker1_name_entry.get().strip() or "Speaker1"
        s2_name = self.speaker2_name_entry.get().strip() or "Speaker2"
        
        s1_voice_display = self.speaker1_voice_dropdown.get()
        s2_voice_display = self.speaker2_voice_dropdown.get()
        
        s1_voice = s1_voice_display.split(" — ")[0] if " — " in s1_voice_display else s1_voice_display
        s2_voice = s2_voice_display.split(" — ")[0] if " — " in s2_voice_display else s2_voice_display
        
        return [
            {"speaker": s1_name, "voice_name": s1_voice},
            {"speaker": s2_name, "voice_name": s2_voice}
        ]
    
    # =========================================================================
    # AI Director
    # =========================================================================
    
    def _on_generate_style(self):
        """Generate style instructions using AI Director."""
        if self.is_directing:
            return
        
        input_text = self.input_textbox.get("1.0", "end-1c").strip()
        if not input_text:
            self._update_status("No input text to analyze", self.colors.red)
            return
        
        self.is_directing = True
        self.generate_style_btn.configure(state="disabled")
        self._update_status("Generating style instructions...", self.colors.accent)
        
        threading.Thread(target=self._run_director, args=(input_text,), daemon=True).start()
    
    def _run_director(self, input_text: str):
        """Run the AI Director in a background thread."""
        try:
            from ...request_pipeline import RequestPipeline, RequestContext, RequestOrigin
            
            # Get director prompts
            system_prompt = self.prompts.get_tts_director_system_prompt()
            task_template = self.prompts.get_tts_director_task_template()
            task = task_template.replace("{text}", input_text)
            
            # Build messages
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task}
            ]
            
            # Determine provider/model for director
            director_model_override = self.director_model_entry.get().strip() if self.director_model_entry else ""
            provider = self.config.get("default_provider", "google")
            model = director_model_override or self.config.get(f"{provider}_model", "")
            
            ctx = RequestContext(
                origin=RequestOrigin.TTS_TOOL,
                provider=provider,
                model=model,
                streaming=False,
                thinking_enabled=False
            )
            
            ctx = RequestPipeline.execute_simple(
                ctx, messages, self.config, self.ai_params, self.key_managers
            )
            
            def update_ui():
                if self._destroyed:
                    return
                
                if ctx.error:
                    self._update_status(f"Director error: {ctx.error}", self.colors.red)
                else:
                    # Populate style textbox
                    self.style_textbox.delete("1.0", "end")
                    self.style_textbox.insert("1.0", ctx.response_text)
                    self._update_status(
                        f"Style generated ({ctx.total_tokens} tokens)",
                        self.colors.green
                    )
                
                self.is_directing = False
                self.generate_style_btn.configure(state="normal")
            
            GUICoordinator.get_instance().run_on_gui_thread(update_ui)
            
        except Exception as e:
            logging.error(f"[TTS] Director error: {e}")
            
            def show_error():
                if not self._destroyed:
                    self._update_status(f"Director error: {e}", self.colors.red)
                    self.is_directing = False
                    self.generate_style_btn.configure(state="normal")
            
            GUICoordinator.get_instance().run_on_gui_thread(show_error)
    
    # =========================================================================
    # TTS Generation
    # =========================================================================
    
    def _on_generate_audio(self):
        """Handle Generate Audio button click."""
        if self.is_generating:
            return
        
        input_text = self.input_textbox.get("1.0", "end-1c").strip()
        if not input_text:
            self._update_status("No input text", self.colors.red)
            return
        
        # Check if auto-director mode is enabled
        if self.director_auto_var.get():
            # Check if style textbox has actual content (not placeholder)
            style_text = self.style_textbox.get("1.0", "end-1c").strip()
            if not style_text or style_text.startswith("(Style instructions"):
                # Auto-run director first, then generate
                self.is_generating = True
                self.generate_audio_btn.configure(state="disabled")
                self._update_status("Auto-directing then generating...", self.colors.accent)
                threading.Thread(
                    target=self._auto_direct_then_generate, 
                    args=(input_text,), daemon=True
                ).start()
                return
        
        # Normal generation
        self.is_generating = True
        self.generate_audio_btn.configure(state="disabled")
        self._update_status("Generating audio...", self.colors.accent)
        
        # Get style instructions
        style_text = self.style_textbox.get("1.0", "end-1c").strip()
        if style_text.startswith("(Style instructions"):
            style_text = ""  # Ignore placeholder
        
        # Combine style + transcript
        if style_text:
            full_prompt = style_text
            # Robust detection: check for transcript marker OR exact content match
            # This prevents duplication if AI output varies slightly in whitespace
            if "#### TRANSCRIPT" not in style_text and input_text not in style_text:
                full_prompt += f"\n\n#### TRANSCRIPT\n{input_text}"
        else:
            full_prompt = input_text
        
        threading.Thread(
            target=self._run_tts_generation,
            args=(full_prompt,),
            daemon=True
        ).start()
    
    def _auto_direct_then_generate(self, input_text: str):
        """Run director first, then generate audio (auto mode)."""
        try:
            from ...request_pipeline import RequestPipeline, RequestContext, RequestOrigin
            
            # Step 1: Run director
            system_prompt = self.prompts.get_tts_director_system_prompt()
            task_template = self.prompts.get_tts_director_task_template()
            task = task_template.replace("{text}", input_text)
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task}
            ]
            
            provider = self.config.get("default_provider", "google")
            director_model_override = ""
            if self.director_model_entry:
                def get_entry():
                    self._director_entry_text = self.director_model_entry.get().strip()
                GUICoordinator.get_instance().run_on_gui_thread(get_entry)
                time.sleep(0.1)  # Wait for UI thread
                director_model_override = getattr(self, '_director_entry_text', '')
            
            model = director_model_override or self.config.get(f"{provider}_model", "")
            
            ctx = RequestContext(
                origin=RequestOrigin.TTS_TOOL,
                provider=provider,
                model=model,
                streaming=False,
                thinking_enabled=False
            )
            
            GUICoordinator.get_instance().run_on_gui_thread(
                lambda: self._update_status("Step 1/2: Generating style...", self.colors.accent)
            )
            
            ctx = RequestPipeline.execute_simple(
                ctx, messages, self.config, self.ai_params, self.key_managers
            )
            
            if ctx.error:
                def show_err():
                    if not self._destroyed:
                        self._update_status(f"Director error: {ctx.error}", self.colors.red)
                        self.is_generating = False
                        self.generate_audio_btn.configure(state="normal")
                GUICoordinator.get_instance().run_on_gui_thread(show_err)
                return
            
            style_text = ctx.response_text
            
            # Update style textbox on UI thread
            def update_style():
                if not self._destroyed:
                    self.style_textbox.delete("1.0", "end")
                    self.style_textbox.insert("1.0", style_text)
            GUICoordinator.get_instance().run_on_gui_thread(update_style)
            
            # Step 2: Generate audio with the style
            full_prompt = style_text
            # Robust detection: check for transcript marker OR exact content match
            if "#### TRANSCRIPT" not in style_text and input_text not in style_text:
                full_prompt += f"\n\n#### TRANSCRIPT\n{input_text}"
            
            GUICoordinator.get_instance().run_on_gui_thread(
                lambda: self._update_status("Step 2/2: Generating audio...", self.colors.accent)
            )
            
            self._run_tts_generation(full_prompt)
            
        except Exception as e:
            logging.error(f"[TTS] Auto-direct error: {e}")
            def show_error():
                if not self._destroyed:
                    self._update_status(f"Error: {e}", self.colors.red)
                    self.is_generating = False
                    self.generate_audio_btn.configure(state="normal")
            GUICoordinator.get_instance().run_on_gui_thread(show_error)
    
    def _run_tts_generation(self, full_prompt: str):
        """Run TTS generation in a background thread."""
        try:
            from ...api_client import get_provider_for_type
            from ...audio.wav_utils import pcm_to_wav, get_pcm_duration
            
            # TTS is always Gemini - get the google key manager
            key_manager = self.key_managers.get("google")
            if not key_manager:
                def show_err():
                    if not self._destroyed:
                        self._update_status("No Google API key configured", self.colors.red)
                        self.is_generating = False
                        self.generate_audio_btn.configure(state="normal")
                GUICoordinator.get_instance().run_on_gui_thread(show_err)
                return
            
            provider = get_provider_for_type("google", key_manager, self.config)
            
            # Build multi-speaker config if needed
            multi_config = None
            if self.is_multi_speaker:
                def get_ms_config():
                    self._ms_config = self._get_multi_speaker_config()
                GUICoordinator.get_instance().run_on_gui_thread(get_ms_config)
                time.sleep(0.1)
                multi_config = getattr(self, '_ms_config', None)
            
            # Call generate_tts
            pcm_data, error = provider.generate_tts(
                text=full_prompt,
                model=self.selected_model,
                voice_name=self.selected_voice,
                multi_speaker_config=multi_config
            )
            
            if error:
                def show_err():
                    if not self._destroyed:
                        self._update_status(f"TTS error: {error}", self.colors.red)
                        self.is_generating = False
                        self.generate_audio_btn.configure(state="normal")
                GUICoordinator.get_instance().run_on_gui_thread(show_err)
                return
            
            # Convert PCM to WAV
            self.pcm_audio = pcm_data
            self.wav_audio = pcm_to_wav(pcm_data)
            self.audio_duration = get_pcm_duration(pcm_data)
            
            def update_ui():
                if self._destroyed:
                    return
                
                duration_str = self._format_short_duration(self.audio_duration)
                self._update_status(
                    f"✅ Audio generated — {duration_str} ({len(pcm_data)} bytes PCM)",
                    self.colors.green
                )
                
                # Enable playback controls
                self.play_pause_btn.configure(state="normal")
                self.seek_slider.configure(state="normal")
                self.save_btn.configure(state="normal")
                self.position_label.configure(text=f"00:00 / {duration_str}")
                self.seek_slider.set(0)
                
                self.is_generating = False
                self.generate_audio_btn.configure(state="normal")

                # Autoplay if enabled
                if self.config.get("tts_autoplay", True):
                    self._play_audio()
            
            GUICoordinator.get_instance().run_on_gui_thread(update_ui)
            
        except Exception as e:
            logging.error(f"[TTS] Generation error: {e}")
            import traceback
            traceback.print_exc()
            
            def show_error():
                if not self._destroyed:
                    self._update_status(f"Error: {e}", self.colors.red)
                    self.is_generating = False
                    self.generate_audio_btn.configure(state="normal")
            GUICoordinator.get_instance().run_on_gui_thread(show_error)
    
    # =========================================================================
    # Audio Playback
    # =========================================================================
    
    def _toggle_playback(self):
        """Toggle playback state."""
        if self.is_playing:
            self._pause_audio()
        else:
            self._play_audio()

    def _play_audio(self):
        """Start or resume audio playback."""
        if not self.recorder or not self.wav_audio:
            return
        
        try:
            position = self.playback_position
            
            if self.recorder.play(self.wav_audio, position):
                self.is_playing = True
                
                # Switch to Pause button
                self._set_play_button_icon("pause")
                
                # Start position update
                self._update_playback_position()
                
                self._update_status("Playing...", self.colors.accent)
        except Exception as e:
            logging.error(f"[TTS] Playback error: {e}")
            self._update_status(f"Playback error: {e}", self.colors.red)
    
    def _pause_audio(self):
        """Pause audio playback."""
        if not self.recorder:
            return
        
        self.recorder.pause()
        self.is_playing = False
        self.playback_position = self.recorder.get_playback_position()
        
        # Switch to Play button
        self._set_play_button_icon("play")
        
        self._update_status("Paused", self.colors.overlay0)
    
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
            
            self._set_play_button_icon("play")
            
            self.seek_slider.set(0)
            self.playback_position = 0.0
            dur_str = self._format_short_duration(self.audio_duration)
            self.position_label.configure(text=f"00:00 / {dur_str}")
            self._update_status("Playback complete", self.colors.green)
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
    
    # =========================================================================
    # Save / Export
    # =========================================================================
    
    def _save_audio(self):
        """Save generated audio as file."""
        if not self.pcm_audio:
            return
        
        from ...audio.wav_utils import save_wav
        from ...audio.ffmpeg_utils import get_ffmpeg_path, get_creation_flags
        import subprocess
        
        # Create output directory
        save_dir = self.config.get("tts_save_directory", "tts_output")
        os.makedirs(save_dir, exist_ok=True)
        
        # Get format
        fmt = self.format_dropdown.get().lower()
        if fmt == "aac":
            ext = "m4a"
        else:
            ext = fmt
            
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        voice = self.selected_voice.lower().replace(" ", "_")
        filename = f"tts_{voice}_{timestamp}.{ext}"
        filepath = os.path.join(save_dir, filename)
        
        error = None
        
        if fmt == "wav":
            error = save_wav(filepath, self.pcm_audio)
        else:
            # Check if we have WAV data (header + PCM)
            if not self.wav_audio:
                # Fallback: create wav bytes from PCM
                from ...audio.wav_utils import pcm_to_wav
                self.wav_audio = pcm_to_wav(self.pcm_audio)
                
            # Use FFmpeg to convert
            ffmpeg_path = get_ffmpeg_path()
            if not ffmpeg_path:
                self._update_status("FFmpeg not available for conversion", self.colors.red)
                return
                
            try:
                # -y overwrite, -i pipe:0 read from stdin
                cmd = [ffmpeg_path, "-y", "-i", "pipe:0", "-v", "error"]
                
                # Use libopus for OGG
                if ext == "ogg":
                    cmd.extend(["-c:a", "libopus"])
                
                cmd.append(filepath)
                
                creation_flags = get_creation_flags()
                
                result = subprocess.run(
                    cmd,
                    input=self.wav_audio,
                    capture_output=True,
                    creationflags=creation_flags
                )
                
                if result.returncode != 0:
                    error = f"FFmpeg: {result.stderr.decode('utf-8')}"
                    
            except Exception as e:
                error = str(e)
        
        if error:
            self._update_status(f"Save failed: {error}", self.colors.red)
        else:
            self._update_status(f"✅ Saved: {filename}", self.colors.green)
    
    # =========================================================================
    # Utilities
    # =========================================================================
    
    def _format_short_duration(self, seconds: float) -> str:
        """Format duration as MM:SS."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"
    
    def _set_play_button_icon(self, mode: str):
        """Set play/pause button icon, handling both CTk and Tk widgets.
        
        Args:
            mode: "play" for ▶ or "pause" for ⏸
        """
        if not self.play_pause_btn:
            return
        
        if HAVE_CTK and isinstance(self.play_pause_btn, ctk.CTkButton):
            if mode == "pause":
                content = prepare_emoji_content("⏸", size=14)
                self.play_pause_btn.configure(
                    **content,
                    **get_ctk_button_colors(self.colors, "secondary")
                )
            else:
                content = prepare_emoji_content("▶", size=14)
                self.play_pause_btn.configure(
                    **content,
                    **get_ctk_button_colors(self.colors, "success")
                )
        else:
            # Standard Tk button
            if mode == "pause":
                self.play_pause_btn.configure(
                    text="⏸",
                    bg=self.colors.surface1,
                    fg=self.colors.text
                )
            else:
                self.play_pause_btn.configure(
                    text="▶",
                    bg=self.colors.green,
                    fg="#ffffff"
                )
    
    def _update_status(self, text: str, color: str = None):
        """Update status bar. Handles both CTk and Tk label widgets."""
        if self.status_label and not self._destroyed:
            self.status_label.configure(text=text)
            target_color = color or self.colors.overlay0
            if HAVE_CTK and isinstance(self.status_label, ctk.CTkLabel):
                self.status_label.configure(text_color=target_color)
            else:
                self.status_label.configure(fg=target_color)
    
    def _close(self):
        """Close window and cleanup."""
        self._destroyed = True
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


def create_tts_window(
    parent_root: tk.Tk,
    config: Dict[str, Any],
    ai_params: Dict[str, Any],
    key_managers: Dict[str, Any],
    initial_text: str = "",
    on_close: Optional[Callable[[], None]] = None
) -> TTSWindow:
    """
    Create a TTS window.
    
    Args:
        parent_root: Parent Tk root
        config: Application configuration
        ai_params: AI parameters
        key_managers: Key manager instances
        initial_text: Text to pre-fill
        on_close: Optional close callback
        
    Returns:
        The created window instance
    """
    return TTSWindow(
        parent_root, config, ai_params, key_managers, initial_text, on_close
    )
