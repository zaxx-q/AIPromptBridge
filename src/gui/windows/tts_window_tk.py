#!/usr/bin/env python3
"""
Tkinter Fallback UI Builder for TTS Window.
Provides standard Tkinter layout implementation when CustomTkinter is unavailable.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable, Any

from ..themes import get_colors
from ..popups import Tooltip

# Reuse wrappers from audio_analyzer_tk
from .audio_analyzer_tk import TkOptionMenuWrapper, TkSliderWrapper, TkCheckBoxWrapper


def build_tk_ui(window):
    """
    Build the standard Tkinter UI for TTSWindow.
    Args:
        window: The TTSWindow instance (controller)
    """
    colors = window.colors

    # === Bottom bar FIRST so it stays visible ===
    _create_bottom_bar_tk(window)

    # Main content frame
    main_frame = tk.Frame(window.root, bg=colors.base)
    main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

    # Configure grid weights (simulating the 2-column layout)
    main_frame.grid_columnconfigure(0, weight=0, minsize=280)  # Left fixed
    main_frame.grid_columnconfigure(1, weight=1)  # Right expands
    main_frame.grid_rowconfigure(1, weight=1)  # Content row expands

    # === Row 0: Top Action Bar ===
    _create_top_action_bar_tk(window, main_frame)

    # === Left Column (Controls) ===
    left_container = tk.Frame(main_frame, bg=colors.base)
    left_container.grid(row=1, column=0, sticky="new", padx=(0, 5), pady=5)

    _create_voice_section_tk(window, left_container)
    _create_speaker_mode_section_tk(window, left_container)
    _create_multi_speaker_section_tk(window, left_container)
    _create_preview_section_tk(window, left_container)
    _create_export_section_tk(window, left_container)

    # === Right Column (Content & AI Director) ===
    right_container = tk.Frame(main_frame, bg=colors.base)
    right_container.grid(row=1, column=1, sticky="nsew", padx=(5, 0), pady=5)
    right_container.grid_rowconfigure(0, weight=1)  # Input text expands
    right_container.grid_rowconfigure(1, weight=0)  # Director doesn't expand
    right_container.grid_columnconfigure(0, weight=1)

    _create_input_text_section_tk(window, right_container)
    _create_director_section_tk(window, right_container)


def _create_section_frame_tk(parent, title: str, colors) -> tk.Frame:
    """Create a titled section frame (pack layout)."""
    frame = tk.Frame(
        parent,
        bg=colors.surface0,
        highlightbackground=colors.surface2,
        highlightthickness=1,
        bd=0
    )
    frame.pack(fill="x", pady=(0, 8))

    # Title
    tk.Label(
        frame,
        text=title,
        font=("Segoe UI", 10, "bold"),
        bg=colors.surface0,
        fg=colors.accent
    ).pack(anchor="w", padx=12, pady=(10, 5))

    # Content area
    content = tk.Frame(frame, bg=colors.surface0)
    content.pack(fill="x", padx=12, pady=(0, 10))

    return content


# =========================================================================
# Top Action Bar
# =========================================================================

def _create_top_action_bar_tk(window, parent):
    """Create top action bar with model selector and Generate Audio button."""
    colors = window.colors
    bar = tk.Frame(parent, bg=colors.base)
    bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

    # Left side: Model selector
    left_frame = tk.Frame(bar, bg=colors.base)
    left_frame.pack(side="left", fill="x", expand=True)

    tk.Label(
        left_frame, text="TTS Model:", font=("Segoe UI", 10),
        bg=colors.base, fg=colors.text
    ).pack(side="left", padx=(0, 5))

    window.model_dropdown = TkOptionMenuWrapper(
        left_frame,
        values=window.TTS_MODELS,
        command=window._on_model_changed,
        width=30
    )
    window.model_dropdown.set(window.selected_model)
    window.model_dropdown.pack(side="left")

    # Right side: Generate Audio button
    right_frame = tk.Frame(bar, bg=colors.base)
    right_frame.pack(side="right")

    window.generate_audio_btn = tk.Button(
        right_frame,
        text="🔊 Generate Audio",
        font=("Segoe UI", 11, "bold"),
        bg=colors.green,
        fg=colors.accent_fg,
        relief="flat",
        padx=15,
        pady=5,
        command=window._on_generate_audio
    )
    window.generate_audio_btn.pack(side="right")


# =========================================================================
# Left Column Sections
# =========================================================================

def _create_voice_section_tk(window, parent):
    """Create voice selector section."""
    colors = window.colors
    content = _create_section_frame_tk(parent, "Voice", colors)

    # Build voice list
    try:
        from ...audio.tts_constants import get_voice_list, get_voice_details
        voice_list = get_voice_list()
    except ImportError:
        voice_list = [window.selected_voice]

    window.voice_dropdown = TkOptionMenuWrapper(
        content,
        values=voice_list,
        command=window._on_voice_changed,
        width=30
    )

    # Set default display
    try:
        from ...audio.tts_constants import get_voice_details
        voice_data = get_voice_details(window.selected_voice)
        if voice_data["style"] != "Unknown":
            default_display = f"{window.selected_voice} — {voice_data['gender']}, {voice_data['style']}"
        else:
            default_display = window.selected_voice
    except (ImportError, KeyError):
        default_display = window.selected_voice

    window.voice_dropdown.set(default_display)
    window.voice_dropdown.pack(fill="x")


def _create_speaker_mode_section_tk(window, parent):
    """Create speaker mode toggle section."""
    colors = window.colors
    content = _create_section_frame_tk(parent, "Speaker Mode", colors)

    window.speaker_mode_var = tk.StringVar(value="single")

    mode_row = tk.Frame(content, bg=colors.surface0)
    mode_row.pack(fill="x")

    tk.Radiobutton(
        mode_row,
        text="Single Speaker",
        variable=window.speaker_mode_var,
        value="single",
        command=window._on_speaker_mode_changed,
        font=("Segoe UI", 10),
        bg=colors.surface0,
        fg=colors.text,
        selectcolor=colors.surface0,
        activebackground=colors.surface0,
        activeforeground=colors.text
    ).pack(side="left", padx=(0, 15))

    tk.Radiobutton(
        mode_row,
        text="Multi-Speaker (2)",
        variable=window.speaker_mode_var,
        value="multi",
        command=window._on_speaker_mode_changed,
        font=("Segoe UI", 10),
        bg=colors.surface0,
        fg=colors.text,
        selectcolor=colors.surface0,
        activebackground=colors.surface0,
        activeforeground=colors.text
    ).pack(side="left")


def _create_multi_speaker_section_tk(window, parent):
    """Create multi-speaker configuration (initially hidden)."""
    colors = window.colors

    window.multi_speaker_frame = tk.Frame(
        parent,
        bg=colors.surface0,
        highlightbackground=colors.surface2,
        highlightthickness=1,
        bd=0
    )
    # Initially hidden — pack/forget based on toggle

    tk.Label(
        window.multi_speaker_frame,
        text="Multi-Speaker Config",
        font=("Segoe UI", 10, "bold"),
        bg=colors.surface0,
        fg=colors.accent
    ).pack(anchor="w", padx=12, pady=(10, 5))

    ms_content = tk.Frame(window.multi_speaker_frame, bg=colors.surface0)
    ms_content.pack(fill="x", padx=12, pady=(0, 10))

    # Build voice list for speaker dropdowns
    try:
        from ...audio.tts_constants import get_voice_list, get_voice_details
        voice_list = get_voice_list()
    except ImportError:
        voice_list = [window.selected_voice, "Puck"]

    # Speaker 1
    s1_row = tk.Frame(ms_content, bg=colors.surface0)
    s1_row.pack(fill="x", pady=(0, 5))

    tk.Label(s1_row, text="Speaker 1:", font=("Segoe UI", 9),
             bg=colors.surface0, fg=colors.overlay0).pack(side="left", padx=(0, 5))

    window.speaker1_name_entry = tk.Entry(
        s1_row, font=("Segoe UI", 9), width=10,
        bg=colors.surface1, fg=colors.text, relief="flat",
        insertbackground=colors.text
    )
    window.speaker1_name_entry.insert(0, window.speaker1_name)
    window.speaker1_name_entry.pack(side="left", padx=(0, 5))

    window.speaker1_voice_dropdown = TkOptionMenuWrapper(
        s1_row, values=voice_list, width=18
    )
    try:
        s1_data = get_voice_details(window.speaker1_voice)
        if s1_data["style"] != "Unknown":
            s1_display = f"{window.speaker1_voice} — {s1_data['gender']}, {s1_data['style']}"
        else:
            s1_display = window.speaker1_voice
    except (ImportError, NameError, KeyError):
        s1_display = window.speaker1_voice

    window.speaker1_voice_dropdown.set(s1_display)
    window.speaker1_voice_dropdown.pack(side="left")

    # Speaker 2
    s2_row = tk.Frame(ms_content, bg=colors.surface0)
    s2_row.pack(fill="x")

    tk.Label(s2_row, text="Speaker 2:", font=("Segoe UI", 9),
             bg=colors.surface0, fg=colors.overlay0).pack(side="left", padx=(0, 5))

    window.speaker2_name_entry = tk.Entry(
        s2_row, font=("Segoe UI", 9), width=10,
        bg=colors.surface1, fg=colors.text, relief="flat",
        insertbackground=colors.text
    )
    window.speaker2_name_entry.insert(0, window.speaker2_name)
    window.speaker2_name_entry.pack(side="left", padx=(0, 5))

    window.speaker2_voice_dropdown = TkOptionMenuWrapper(
        s2_row, values=voice_list, width=18
    )
    try:
        s2_data = get_voice_details(window.speaker2_voice)
        if s2_data["style"] != "Unknown":
            s2_display = f"{window.speaker2_voice} — {s2_data['gender']}, {s2_data['style']}"
        else:
            s2_display = window.speaker2_voice
    except (ImportError, NameError, KeyError):
        s2_display = window.speaker2_voice

    window.speaker2_voice_dropdown.set(s2_display)
    window.speaker2_voice_dropdown.pack(side="left")


def _create_preview_section_tk(window, parent):
    """Create audio preview/playback section."""
    colors = window.colors
    content = _create_section_frame_tk(parent, "Audio Preview", colors)

    row_frame = tk.Frame(content, bg=colors.surface0)
    row_frame.pack(fill="x")

    # Play/Pause button
    window.play_pause_btn = tk.Button(
        row_frame, text="▶", font=("Segoe UI", 12),
        bg=colors.green, fg=colors.accent_fg, relief="flat",
        width=3, command=window._toggle_playback, state="disabled"
    )
    window.play_pause_btn.pack(side="left", padx=(0, 8))

    # Seek slider
    window.seek_slider = TkSliderWrapper(
        row_frame, from_=0, to=100, command=window._on_seek
    )
    window.seek_slider.set(0)
    window.seek_slider.configure(state="disabled")
    window.seek_slider.pack(side="left", fill="x", expand=True, padx=(0, 8))

    # Position label
    window.position_label = tk.Label(
        row_frame, text="00:00 / 00:00", font=("Segoe UI", 9),
        bg=colors.surface0, fg=colors.overlay0
    )
    window.position_label.pack(side="left")


def _create_export_section_tk(window, parent):
    """Create save/export section."""
    colors = window.colors
    content = _create_section_frame_tk(parent, "Export", colors)

    # Format info label (read from config)
    fmt = window.config.get("audio_output_format", "ogg").upper()
    tk.Label(
        content,
        text=f"Format: {fmt} (set in config)",
        font=("Segoe UI", 9),
        bg=colors.surface0,
        fg=colors.overlay0
    ).pack(fill="x", pady=(0, 5))

    # Save button
    window.save_btn = tk.Button(
        content,
        text="💾 Save Audio",
        font=("Segoe UI", 10),
        bg=colors.surface1,
        fg=colors.text,
        relief="flat",
        padx=10,
        pady=4,
        command=window._save_audio,
        state="disabled"
    )
    window.save_btn.pack(fill="x")


# =========================================================================
# Right Column Sections
# =========================================================================

def _create_input_text_section_tk(window, parent):
    """Create editable input text section."""
    colors = window.colors

    frame = tk.Frame(
        parent,
        bg=colors.surface0,
        highlightbackground=colors.surface2,
        highlightthickness=1,
        bd=0
    )
    frame.grid(row=0, column=0, sticky="nsew", pady=(0, 5))

    tk.Label(
        frame,
        text="Input Text",
        font=("Segoe UI", 10, "bold"),
        bg=colors.surface0,
        fg=colors.accent
    ).pack(anchor="w", padx=12, pady=(10, 5))

    window.input_textbox = tk.Text(
        frame,
        wrap=tk.WORD,
        font=("Segoe UI", 11),
        bg=colors.text_bg,
        fg=colors.text,
        insertbackground=colors.text,
        relief=tk.FLAT,
        padx=10,
        pady=10
    )
    window.input_textbox.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    # Pre-fill with initial text
    if window.initial_text:
        window.input_textbox.insert("1.0", window.initial_text)


def _create_director_section_tk(window, parent):
    """Create AI Director panel."""
    colors = window.colors

    frame = tk.Frame(
        parent,
        bg=colors.surface0,
        highlightbackground=colors.surface2,
        highlightthickness=1,
        bd=0
    )
    frame.grid(row=1, column=0, sticky="nsew", pady=(5, 0))

    # Header row with title and auto toggle
    header = tk.Frame(frame, bg=colors.surface0)
    header.pack(fill="x", padx=12, pady=(10, 5))

    tk.Label(
        header,
        text="AI Director",
        font=("Segoe UI", 10, "bold"),
        bg=colors.surface0,
        fg=colors.accent
    ).pack(side="left")

    # Auto/Manual toggle
    window.director_auto_var = tk.BooleanVar(value=window.director_auto_mode)
    window.director_toggle = TkCheckBoxWrapper(
        header,
        text="Auto",
        variable=window.director_auto_var
    )
    window.director_toggle.pack(side="right")
    Tooltip(
        window.director_toggle.cb,
        "Automatically generate style instructions when clicking 'Generate Audio' if the style box is empty or still has the default placeholder text."
    )

    # Director controls row
    controls = tk.Frame(frame, bg=colors.surface0)
    controls.pack(fill="x", padx=12, pady=(0, 5))

    tk.Label(
        controls,
        text="Director Model:",
        font=("Segoe UI", 9),
        bg=colors.surface0,
        fg=colors.overlay0
    ).pack(side="left", padx=(0, 5))

    window.director_model_entry = tk.Entry(
        controls,
        font=("Segoe UI", 9),
        width=20,
        bg=colors.surface1,
        fg=colors.text,
        relief="flat",
        insertbackground=colors.text
    )
    if window.director_model:
        window.director_model_entry.insert(0, window.director_model)
    window.director_model_entry.pack(side="left", padx=(0, 8))

    # Generate Style button
    window.generate_style_btn = tk.Button(
        controls,
        text="🎬 Generate Style",
        font=("Segoe UI", 9, "bold"),
        bg=colors.accent,
        fg=colors.accent_fg,
        relief="flat",
        padx=10,
        pady=2,
        command=window._on_generate_style
    )
    window.generate_style_btn.pack(side="right")

    # Style instructions textbox
    window.style_textbox = tk.Text(
        frame,
        wrap=tk.WORD,
        font=("Segoe UI", 10),
        bg=colors.text_bg,
        fg=colors.text,
        insertbackground=colors.text,
        relief=tk.FLAT,
        height=6,
        padx=10,
        pady=10
    )
    window.style_textbox.pack(fill="both", expand=True, padx=12, pady=(0, 10))
    window.style_textbox.insert(
        "1.0",
        "(Style instructions will appear here after clicking 'Generate Style', or you can write your own) "
        "\nClear this text or leave this text as is to have no style instructions applied to input text."
    )


# =========================================================================
# Bottom Bar
# =========================================================================

def _create_bottom_bar_tk(window):
    """Create bottom bar with status."""
    colors = window.colors

    bottom_frame = tk.Frame(window.root, bg=colors.surface0, height=40)
    bottom_frame.pack(fill="x", side="bottom")
    bottom_frame.pack_propagate(False)

    status_container = tk.Frame(bottom_frame, bg=colors.surface0)
    status_container.pack(fill="x", padx=15, pady=(8, 8))

    window.status_label = tk.Label(
        status_container,
        text="Ready — Enter text and click Generate Audio",
        font=("Segoe UI", 9),
        bg=colors.surface0,
        fg=colors.overlay0,
        anchor="w"
    )
    window.status_label.pack(side="left")
