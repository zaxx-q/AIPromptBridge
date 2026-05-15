#!/usr/bin/env python3
"""
Tkinter Fallback UI Builder for Audio Analyzer Window.
Provides standard Tkinter layout implementation when CustomTkinter is unavailable.
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Any, Optional

from ..custom_widgets import ScrollableComboBox
from ..popups import ModifierBar, Tooltip, CarouselButtonList, SegmentedToggle
from ..themes import get_colors

class TkOptionMenuWrapper:
    """
    Wrapper for ttk.Combobox to mimic CTkOptionMenu interface.
    Allows the controller to use .configure(values=...) and .set() uniformly.
    """
    def __init__(self, parent, values, command: Optional[Callable[[str], None]] = None, width: int = 20, **kwargs):
        self.command = command
        self._var = tk.StringVar()
        
        # Configure colors for consistency
        colors = get_colors()
        
        self.combo = ttk.Combobox(
            parent,
            textvariable=self._var,
            values=values,
            state="readonly",
            width=width
        )
        
        # Bind virtual event for selection
        self.combo.bind("<<ComboboxSelected>>", self._on_select)
        
        # Store kwargs that might be relevant?
        # CTk style kwargs might need translation or ignoring
        
    def _on_select(self, event):
        if self.command:
            self.command(self._var.get())
            
    def configure(self, values=None, state=None, **kwargs):
        """Update configuration."""
        if values is not None:
            self.combo['values'] = values
        if state is not None:
            # map ctk states to tk states if needed, though 'normal'/'disabled' are similar
            # ttk combobox uses 'readonly' usually. 'disabled' is valid.
            if state == "normal":
                self.combo.configure(state="readonly")
            else:
                self.combo.configure(state=state)
                
    def set(self, value: str):
        self.combo.set(value)
        
    def get(self) -> str:
        return self.combo.get()
        
    def pack(self, **kwargs):
        self.combo.pack(**kwargs)
        
    def grid(self, **kwargs):
        self.combo.grid(**kwargs)

class TkSliderWrapper:
    """Wrapper for tk.Scale to mimic CTkSlider interface."""
    def __init__(self, parent, from_=0, to=100, command=None, width=None, **kwargs):
        self.command = command
        self.scale = tk.Scale(
            parent,
            from_=from_,
            to=to,
            orient="horizontal",
            showvalue=0, # No value label next to slider
            command=self._on_change
        )
        if width:
            self.scale.configure(length=width)
            
    def _on_change(self, val):
        if self.command:
            self.command(float(val))
            
    def set(self, value):
        self.scale.set(value)
        
    def get(self):
        return self.scale.get()
        
    def configure(self, state=None, **kwargs):
        if state:
            self.scale.configure(state=state)
            
    def pack(self, **kwargs):
        self.scale.pack(**kwargs)

class TkCheckBoxWrapper:
    """Wrapper for tk.Checkbutton to match CTkCheckBox interface."""
    def __init__(self, parent, text, variable, command=None, **kwargs):
        colors = get_colors()
        self.cb = tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            command=command,
            bg=colors.surface0,
            fg=colors.text,
            selectcolor=colors.surface1,
            activebackground=colors.surface1,
            activeforeground=colors.text
        )
        
    def configure(self, **kwargs):
        # Map CTk config keys to Tk keys where possible
        tk_kwargs = {}
        if "text" in kwargs:
            tk_kwargs["text"] = kwargs["text"]
        if "state" in kwargs:
            tk_kwargs["state"] = kwargs["state"]
            
        self.cb.configure(**tk_kwargs)
        
    def pack(self, **kwargs):
        self.cb.pack(**kwargs)


def build_tk_ui(window):
    """
    Build the standard Tkinter UI for AudioAnalyzerWindow.
    Args:
        window: The AudioAnalyzerWindow instance (controller)
    """
    colors = get_colors()
    
    # === Main Container ===
    # Create bottom bar FIRST so it stays visible (pack bottom)
    _create_bottom_bar_tk(window)
    
    # Main content frame
    main_frame = tk.Frame(window.root, bg=window.colors.base)
    main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
    
    # Configure grid weights (simulating the 2-column layout)
    main_frame.grid_columnconfigure(0, weight=0, minsize=300) # Left fixed
    main_frame.grid_columnconfigure(1, weight=1) # Right expands
    main_frame.grid_rowconfigure(2, weight=1) # Result area expands
    
    # === Row 0: Top Action Bar ===
    _create_top_action_bar_tk(window, main_frame)
    
    # === Left Column: Audio Controls ===
    left_container = tk.Frame(main_frame, bg=window.colors.base)
    left_container.grid(row=1, column=0, rowspan=2, sticky="new", padx=(0, 10), pady=0)
    
    _create_audio_source_section_tk(window, left_container)
    _create_recording_section_tk(window, left_container)
    _create_compression_section_tk(window, left_container)
    _create_preview_section_tk(window, left_container)
    _create_display_options_section_tk(window, left_container)
    
    # === Right Column: Prompt & Result ===
    _create_prompt_section_tk(window, main_frame, row=1, col=1)
    _create_result_section_tk(window, main_frame, row=2, col=1)

def _create_section_frame_tk(parent, title: str, colors) -> tk.Frame:
    """Create a titled section frame (pack layout)."""
    frame = tk.Frame(
        parent,
        bg=colors.surface0,
        highlightbackground=colors.surface2,
        highlightthickness=1,
        bd=0
    )
    frame.pack(fill="x", pady=(0, 10))
    
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

def _create_top_action_bar_tk(window, parent):
    """Create top action bar (Provider/Model left, Send/Clear right)."""
    colors = get_colors()
    bar = tk.Frame(parent, bg=colors.base)
    bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 15))
    
    # Left: Provider/Model
    left_frame = tk.Frame(bar, bg=colors.base)
    left_frame.pack(side="left", fill="x")
    
    # Provider (hidden in profile mode)
    window.provider_label_widget = tk.Label(
        left_frame, text="Provider:", font=("Segoe UI", 10),
        bg=colors.base, fg=colors.text
    )
    
    providers = ["google", "openrouter", "custom"]
    window.provider_dropdown = TkOptionMenuWrapper(
        left_frame,
        values=providers,
        command=window._on_provider_changed,
        width=12
    )
    window.provider_dropdown.set(window.provider)
    
    if not window._use_profile_mode:
        window.provider_label_widget.pack(side="left", padx=(0, 5))
        window.provider_dropdown.pack(side="left", padx=(0, 15))
    
    # Model/Preset
    dropdown_label = "Preset:" if window._use_profile_mode else "Model:"
    window.model_label_widget = tk.Label(
        left_frame, text=dropdown_label, font=("Segoe UI", 10),
        bg=colors.base, fg=colors.text
    )
    window.model_label_widget.pack(side="left", padx=(0, 5))
    
    if window._use_profile_mode:
        initial_values = ["(Default)"] + window._get_profile_names()
        initial_display = "(Default)"
    else:
        initial_values = ["(loading...)"]
        initial_display = window.model or "(loading...)"
    
    window.model_dropdown = ScrollableComboBox(
        left_frame,
        colors=colors,
        values=initial_values,
        width=250,
        height=28,
        command=window._on_model_changed
    )
    window.model_dropdown.pack(side="left")
    window.model_dropdown.set(initial_display)
    
    # Right: Buttons
    right_frame = tk.Frame(bar, bg=colors.base)
    right_frame.pack(side="right")
    
    # Send
    window.send_btn = tk.Button(
        right_frame,
        text="📤 Send",
        font=("Segoe UI", 10, "bold"),
        bg=colors.green,
        fg="#ffffff",
        relief="flat",
        padx=15,
        pady=5,
        command=window._send_audio,
        state="disabled"
    )
    window.send_btn.pack(side="left", padx=(0, 10))
    
    # Save Audio
    window.save_btn = tk.Button(
        right_frame,
        text="💾 Save Audio",
        font=("Segoe UI", 10),
        bg=colors.surface1,
        fg=colors.text,
        relief="flat",
        padx=10,
        pady=5,
        command=window._save_audio,
        state="disabled"
    )
    window.save_btn.pack(side="left")

def _create_audio_source_section_tk(window, parent):
    """Create audio source section."""
    colors = get_colors()
    content = _create_section_frame_tk(parent, "Audio Source", colors)
    
    # Device Row
    row = tk.Frame(content, bg=colors.surface0)
    row.pack(fill="x", pady=(0, 8))
    
    tk.Label(
        row, text="Device:", font=("Segoe UI", 9),
        bg=colors.surface0, fg=colors.text
    ).pack(side="left", padx=(0, 5))
    
    # Device Dropdown
    window.device_dropdown = TkOptionMenuWrapper(
        row,
        values=["(loading...)"],
        command=window._on_device_changed,
        width=25
    )
    window.device_dropdown.pack(side="left", fill="x", expand=True, padx=(0, 5))
    
    # Refresh Button
    refresh_btn = tk.Button(
        row,
        text="🔄",
        font=("Segoe UI", 10),
        bg=colors.surface1,
        fg=colors.text,
        relief="flat",
        command=window._refresh_devices,
        width=3
    )
    refresh_btn.pack(side="left")
    Tooltip(refresh_btn, "Refresh device list")
    
    # Type Row
    type_row = tk.Frame(content, bg=colors.surface0)
    type_row.pack(fill="x")
    
    window.device_type_var = tk.StringVar(value="loopback" if window.config.get("audio_default_loopback", True) else "input")
    
    # Styles for Radiobuttons in Tk need care to match theme
    def create_radio(text, val):
        return tk.Radiobutton(
            type_row,
            text=text,
            variable=window.device_type_var,
            value=val,
            command=window._on_device_type_changed,
            bg=colors.surface0,
            fg=colors.text,
            selectcolor=colors.surface0,
            activebackground=colors.surface0,
            activeforeground=colors.text,
            font=("Segoe UI", 9)
        )
        
    create_radio("🎤 Input", "input").pack(side="left", padx=(0, 15))
    create_radio("🔊 Loopback", "loopback").pack(side="left")

def _create_recording_section_tk(window, parent):
    """Create recording/upload controls section (pack layout)."""
    colors = get_colors()
    content = _create_section_frame_tk(parent, "Audio Input", colors)
    
    row = tk.Frame(content, bg=colors.surface0)
    row.pack(fill="x")
    
    # Record/Stop Button (Merged)
    window.record_btn = tk.Button(
        row,
        text="🔴 Record",
        font=("Segoe UI", 10, "bold"),
        bg=colors.red,
        fg="#ffffff",
        relief="flat",
        padx=12,
        pady=4,
        command=window._toggle_recording
    )
    window.record_btn.pack(side="left", padx=(0, 10))
    
    # Duration
    window.duration_label = tk.Label(
        row,
        text="00:00:00",
        font=("Segoe UI", 11, "bold"),
        bg=colors.surface0,
        fg=colors.text
    )
    window.duration_label.pack(side="left")
    
    # Upload Button
    upload_btn = tk.Button(
        row,
        text="📁 Upload",
        font=("Segoe UI", 10),
        bg=colors.surface1,
        fg=colors.text,
        relief="flat",
        padx=10,
        pady=4,
        command=window._upload_audio_file
    )
    upload_btn.pack(side="right", padx=(5, 0))

def _create_compression_section_tk(window, parent):
    """Create compression section."""
    colors = get_colors()
    content = _create_section_frame_tk(parent, "Compression", colors)
    
    row = tk.Frame(content, bg=colors.surface0)
    row.pack(fill="x", pady=(0, 5))
    
    # Checkbox
    window.compression_var = tk.BooleanVar(value=window.compression_enabled)
    window.compression_cb = TkCheckBoxWrapper(
        row,
        text="Enable",
        variable=window.compression_var,
        command=window._on_compression_toggled
    )
    window.compression_cb.pack(side="left", padx=(0, 10))
    
    # Preset Dropdown
    tk.Label(row, text="Preset:", font=("Segoe UI", 9), bg=colors.surface0, fg=colors.overlay0).pack(side="left", padx=(0, 5))
    
    from ...audio.recorder import COMPRESSION_PRESETS
    preset_names = [p["name"] for p in COMPRESSION_PRESETS.values()]
    
    window.profile_dropdown = TkOptionMenuWrapper(
        row,
        values=preset_names,
        command=window._on_preset_changed,
        width=15
    )
    
    # Set current preset
    current_preset = COMPRESSION_PRESETS.get(window.compression_preset, {})
    window.profile_dropdown.set(current_preset.get("name", "Recommended"))
    window.profile_dropdown.pack(side="left")
    
    # Info Row
    info_row = tk.Frame(content, bg=colors.surface0)
    info_row.pack(fill="x")
    
    window.size_label = tk.Label(info_row, text="", font=("Segoe UI", 8), bg=colors.surface0, fg=colors.overlay0)
    window.size_label.pack(side="left")
    
    desc = current_preset.get("description", "")
    window.preset_desc_label = tk.Label(info_row, text=f"• {desc}" if desc else "", font=("Segoe UI", 8), bg=colors.surface0, fg=colors.overlay0)
    window.preset_desc_label.pack(side="right")

def _create_preview_section_tk(window, parent):
    """Create preview section."""
    colors = get_colors()
    content = _create_section_frame_tk(parent, "Preview", colors)
    
    row = tk.Frame(content, bg=colors.surface0)
    row.pack(fill="x")
    
    # Play/Pause
    window.play_pause_btn = tk.Button(
        row, text="▶", font=("Segoe UI", 12),
        bg=colors.green, fg="#ffffff", relief="flat",
        width=3, command=window._toggle_playback, state="disabled"
    )
    window.play_pause_btn.pack(side="left", padx=(0, 8))
    
    # Seek Slider 
    window.seek_slider = TkSliderWrapper(
        row, from_=0, to=100, command=window._on_seek,
        bg=colors.surface0, troughcolor=colors.surface1, activebackground=colors.accent
    )
    # Note: tk.Scale colors are tricky, above are mild attempts
    window.seek_slider.pack(side="left", fill="x", expand=True, padx=(0, 8))
    window.seek_slider.configure(state="disabled")
    
    # Position
    window.position_label = tk.Label(
        row, text="00:00", font=("Segoe UI", 9),
        bg=colors.surface0, fg=colors.overlay0
    )
    window.position_label.pack(side="left")

def _create_display_options_section_tk(window, parent):
    """Create display options section (pack layout)."""
    colors = get_colors()
    content = _create_section_frame_tk(parent, "Response Mode", colors)
    
    # Segmented toggle
    window.response_mode_toggle = SegmentedToggle(
        content,
        options=[("Default", "default"), ("Result Panel", "result"), ("Chat Window", "show")],
        default_value="default"
    )
    window.response_mode_toggle.pack(pady=(0, 5))
    
    # Description
    tk.Label(
        content,
        text="Override where the AI response is shown.",
        font=("Segoe UI", 8),
        bg=colors.surface0,
        fg=colors.overlay0,
        justify="center",
        wraplength=250
    ).pack(fill="x", padx=5)

def _create_prompt_section_tk(window, parent, row, col):
    """Create prompt section (Right column)."""
    colors = get_colors()
    
    # Frame with grid positioning
    frame = tk.Frame(
        parent,
        bg=colors.surface0,
        highlightbackground=colors.surface2,
        highlightthickness=1,
        bd=0
    )
    frame.grid(row=row, column=col, sticky="new", padx=5, pady=0)
    
    tk.Label(
        frame, text="Prompt Selection", font=("Segoe UI", 10, "bold"),
        bg=colors.surface0, fg=colors.accent
    ).pack(anchor="w", padx=12, pady=(10, 5))
    
    content = tk.Frame(frame, bg=colors.surface0)
    content.pack(fill="x", padx=12, pady=(0, 10))
    
    # Custom Input with Set Button
    input_frame = tk.Frame(content, bg=colors.surface0)
    input_frame.pack(fill="x", pady=(0, 10))
    
    window.custom_input = tk.Entry(
        input_frame,
        font=("Segoe UI", 10),
        bg=colors.surface1,
        fg=colors.text,
        relief="flat",
        insertbackground=colors.text
    )
    window.custom_input.pack(side="left", fill="x", expand=True, padx=(0, 5), ipady=4)
    window.custom_input.bind('<Return>', window._on_custom_input_set)
    
    placeholder = "Custom task or question..."
    window.custom_input.insert(0, placeholder)
    window.custom_input.configure(fg=colors.overlay0)
    
    def on_focus_in(event):
        if window.custom_input.get() == placeholder:
            window.custom_input.delete(0, tk.END)
            window.custom_input.configure(fg=colors.text)
    
    def on_focus_out(event):
        if not window.custom_input.get():
            window.custom_input.insert(0, placeholder)
            window.custom_input.configure(fg=colors.overlay0)
            
    window.custom_input.bind("<FocusIn>", on_focus_in)
    window.custom_input.bind("<FocusOut>", on_focus_out)
    
    set_btn = tk.Button(
        input_frame,
        text="Set",
        font=("Segoe UI", 9),
        bg=colors.surface1,
        fg=colors.text,
        relief="flat",
        command=window._on_custom_input_set,
        width=4
    )
    set_btn.pack(side="right")
    
    # Carousel (Handles fallback internally)
    from ..popups import GroupedButtonList
    
    settings = window.prompts.get_audio_tool().get("_settings", {})
    use_groups = settings.get("popup_use_groups", True) or settings.get("use_groups", True)
    
    if use_groups:
        popup_groups = settings.get("popup_groups", [])
        actions = window.prompts.get_audio_actions()
        
        groups = []
        for group_def in popup_groups:
            if not group_def.get("enabled", True):
                continue
            group_name = group_def.get("name", "")
            item_keys = group_def.get("items", [])
            
            group_items = []
            for key in item_keys:
                action = actions.get(key)
                if action:
                    group_items.append((key, key, action.get("icon", ""), action.get("task", "")))
            
            if group_items:
                groups.append({"name": group_name, "items": group_items})
                
        if groups:
            window.carousel = GroupedButtonList(
                content, groups=groups, on_click=window._on_action_click
            )
            window.carousel.pack(fill="x", pady=(0, 8))
    else:
        # Flat fallback
        actions = window.prompts.get_audio_actions()
        items = []
        for key, action in actions.items():
            if key.startswith("_"): continue
            items.append((key, key, action.get("icon", ""), action.get("task", "")))
            
        items_per_page = settings.get("items_per_page", 6)
            
        if items:
            window.carousel = CarouselButtonList(
                content, items=items, on_click=window._on_action_click, items_per_page=items_per_page
            )
            window.carousel.pack(fill="x", pady=(0, 8))
        
    # Modifier Bar (Handles fallback internally)
    global_modifiers = window.prompts.get_modifiers()
    default_active = window.prompts.get_default_modifier_keys_for_tool("audio_tool")
    if global_modifiers:
        window.modifier_bar = ModifierBar(
            content, modifiers=global_modifiers, on_change=window._on_modifiers_changed,
            default_active=default_active
        )
        window.modifier_bar.pack(fill="x")

def _create_result_section_tk(window, parent, row, col):
    """Create result section."""
    colors = get_colors()
    
    frame = tk.Frame(
        parent,
        bg=colors.surface0,
        highlightbackground=colors.surface2,
        highlightthickness=1,
        bd=0
    )
    frame.grid(row=row, column=col, sticky="nsew", padx=5, pady=10)
    
    # Header
    header = tk.Frame(frame, bg=colors.surface0)
    header.pack(fill="x", padx=12, pady=(10, 5))
    
    tk.Label(
        header, text="Result", font=("Segoe UI", 10, "bold"),
        bg=colors.surface0, fg=colors.accent
    ).pack(side="left")
    
    window.copy_btn = tk.Button(
        header, text="📋 Copy", font=("Segoe UI", 9),
        bg=colors.surface1, fg=colors.text, relief="flat",
        padx=8, pady=2, command=window._copy_result, state="disabled"
    )
    window.copy_btn.pack(side="right")
    
    # Text Area
    text_frame = tk.Frame(frame, bg=colors.text_bg)
    text_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
    
    window.result_text_widget = tk.Text(
        text_frame, wrap=tk.WORD, font=("Segoe UI", 11),
        bg=colors.text_bg, fg=colors.text,
        insertbackground=colors.text, relief=tk.FLAT,
        padx=10, pady=10
    )
    window.result_text_widget.pack(fill="both", expand=True, padx=1, pady=1)
    
    window.result_text_widget.insert("1.0", "(Transcription/analysis result will appear here)")
    window.result_text_widget.configure(state=tk.DISABLED, fg=colors.overlay0)

def _create_bottom_bar_tk(window):
    """Create bottom status bar (packed first)."""
    colors = get_colors()
    
    bottom_frame = tk.Frame(window.root, bg=colors.surface0, height=60)
    bottom_frame.pack(side="bottom", fill="x")
    bottom_frame.pack_propagate(False)
    
    # Meter Row
    meter_row = tk.Frame(bottom_frame, bg=colors.surface0)
    meter_row.pack(fill="x", padx=15, pady=(8, 0))
    
    tk.Label(
        meter_row, text="Level:", font=("Segoe UI", 9),
        bg=colors.surface0, fg=colors.overlay0
    ).pack(side="left", padx=(0, 8))
    
    # Canvas Meter (Legacy/Standard Tk)
    window.level_canvas = tk.Canvas(
        meter_row, height=12, bg=colors.surface1,
        highlightthickness=1, highlightbackground=colors.surface2
    )
    window.level_canvas.pack(side="left", fill="x", expand=True)
    window.level_bar = None # Not used in Tk fallback usually, unless we want ttk.Progressbar
    
    window._canvas_drawn_width = 0
    window.level_canvas.bind("<Configure>", window._on_canvas_resize)
    window.level_canvas.after(50, window._draw_level_grid)
    
    # Status Row
    status_row = tk.Frame(bottom_frame, bg=colors.surface0)
    status_row.pack(fill="x", padx=15, pady=(4, 8))
    
    window.status_label = tk.Label(
        status_row, text="Ready", font=("Segoe UI", 9),
        bg=colors.surface0, fg=colors.overlay0, anchor="w"
    )
    window.status_label.pack(side="left")
    
    # Action Indicator (Right aligned)
    window.action_indicator_label = tk.Label(
        status_row, text=f"Action: {window.selected_action_key}",
        font=("Segoe UI", 9, "bold"),
        bg=colors.surface0, fg=colors.accent, anchor="e"
    )
    window.action_indicator_label.pack(side="right")
    
    window._update_level_display(0.0)
