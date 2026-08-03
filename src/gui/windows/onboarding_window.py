#!/usr/bin/env python3
"""
Onboarding Wizard window.

Guided multi-step setup experience for first-time startup.
Configures API Keys (stored in KeyStore) and default connection profile (ProfileStore).
"""

import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, ClassVar, Dict, List, Optional

from ...config import load_config, save_config_value
from ...connection_profiles import ConnectionProfile, ProfileStore
from ...key_store import KeyStore
from ...providers.registry import get_provider_definitions
from ...version import __version__
from ..custom_widgets import ScrollableButtonList, ScrollableComboBox, TkScrollableFrame, create_emoji_button
from ..platform import HAVE_CTK, ctk
from ..themes import (
    ThemeColors,
    get_colors,
    get_ctk_button_colors,
    get_ctk_combobox_colors,
    get_ctk_entry_colors,
    get_ctk_font,
    get_ctk_frame_colors,
    get_ctk_label_colors,
    get_ctk_segmented_colors,
    get_tk_font,
)
from .utils import set_dark_titlebar, set_window_icon

try:
    from ..emoji_renderer import HAVE_PIL, get_emoji_renderer, prepare_emoji_content

    HAVE_EMOJI = HAVE_PIL and HAVE_CTK
except ImportError:
    HAVE_EMOJI = False
    prepare_emoji_content = None
    get_emoji_renderer = None

from ...model_defaults import get_fallback_models


def _adjust_hex_color(hex_color: str, factor: float) -> str:
    """Adjust brightness of a hex color by a factor. factor < 1.0 darkens, > 1.0 lightens."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return f"#{hex_color}"
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        r = max(0, min(255, int(r * factor)))
        g = max(0, min(255, int(g * factor)))
        b = max(0, min(255, int(b * factor)))

        return f"#{r:02x}{g:02x}{b:02x}"
    except ValueError:
        return f"#{hex_color}"


class OnboardingWizard:
    """
    Onboarding wizard guiding first-time users through configuration.
    """

    WIZARD_MINIMAL_TEXT_EDIT: ClassVar[set[str]] = {
        "Explain",
        "Proofread",
        "Refine",
        "Translate to English",
        "Answer",
        "Humanize",
    }
    WIZARD_MINIMAL_SNIP: ClassVar[set[str]] = {
        "Quick Extract",
        "Smart Extract",
        "Explain",
        "Answer",
        "Describe",
        "Translate to English",
    }
    WIZARD_MINIMAL_AUDIO: ClassVar[set[str]] = {"Transcribe", "Summarize", "Translate to English"}
    WIZARD_MINIMAL_MODIFIERS: ClassVar[set[str]] = {"direct", "shorter", "longer", "language"}

    def __init__(self, master=None, on_close=None):
        self.master = master
        self.on_close_callback = on_close
        self.use_ctk = HAVE_CTK
        self.colors = get_colors()
        self.current_page = 0
        self._destroyed = False
        self._keys_added = []
        self._model_status_label = None

        # Get stores
        self._key_store = KeyStore.get_instance()
        self._key_store.load()
        self._profile_store = ProfileStore.get_instance()

        # Create Window
        if self.master:
            self.root = ctk.CTkToplevel(self.master) if self.use_ctk else tk.Toplevel(self.master)
        else:
            if self.use_ctk:
                self.root = ctk.CTk()
            else:
                self.root = tk.Tk()

        if self.use_ctk:
            try:
                from ..ctk_bootstrap import ensure_ctk_window_ready

                ensure_ctk_window_ready(self.root)
            except Exception:
                pass

        self.root.title("Welcome to AIPromptBridge")
        self.root.geometry("750x700")
        self.root.resizable(False, False)

        if self.use_ctk:
            self.root.configure(fg_color=self.colors.bg)
        else:
            self.root.configure(bg=self.colors.bg)

        self.root.withdraw()
        set_dark_titlebar(self.root)
        set_window_icon(self.root)

        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Escape>", lambda e: self._close())

        # Focus
        self.root.lift()
        self.root.focus_force()

    def show(self):
        c = self.colors

        # Center the window on the screen
        self.root.update_idletasks()
        w = 750
        h = 700
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        # Bottom navigation layout first (prevents squashing when content_frame expands)
        self.nav_frame = (
            ctk.CTkFrame(self.root, fg_color=c.surface0, height=64)
            if self.use_ctk
            else tk.Frame(self.root, bg=c.surface0, height=64)
        )
        self.nav_frame.pack(fill="x", side="bottom")
        self.nav_frame.pack_propagate(False)

        # Main Content Layout (takes remaining space)
        self.content_frame = (
            ctk.CTkFrame(self.root, fg_color="transparent") if self.use_ctk else tk.Frame(self.root, bg=c.bg)
        )
        self.content_frame.pack(fill="both", expand=True, padx=25, pady=(20, 10))

        self._build_nav_frame(self.nav_frame)
        self._show_page(0)

        self.root.deiconify()
        self.root.focus_force()

        if not self.master:
            self._run_event_loop()

    def _build_nav_frame(self, parent):
        c = self.colors

        # Left side: Skip button
        if self.use_ctk:
            self.btn_skip = ctk.CTkButton(
                parent, text="Skip Setup", width=100, command=self._skip, **get_ctk_button_colors(c, "ghost")
            )
        else:
            self.btn_skip = tk.Button(
                parent,
                text="Skip Setup",
                bg=c.surface0,
                fg=c.fg,
                bd=0,
                activebackground=c.surface1,
                activeforeground=c.fg,
                command=self._skip,
            )
        self.btn_skip.pack(side="left", padx=15, pady=12)

        # Right side: Navigation buttons
        if self.use_ctk:
            self.btn_next = ctk.CTkButton(
                parent, text="Next", width=100, command=self._go_next, **get_ctk_button_colors(c, "primary")
            )
            self.btn_back = ctk.CTkButton(
                parent, text="Back", width=100, command=self._go_back, **get_ctk_button_colors(c, "secondary")
            )
        else:
            self.btn_next = tk.Button(parent, text="Next", bg=c.accent, fg=c.accent_fg, width=12, command=self._go_next)
            self.btn_back = tk.Button(parent, text="Back", bg=c.surface1, fg=c.fg, width=12, command=self._go_back)

        self.btn_next.pack(side="right", padx=15, pady=12)
        self.btn_back.pack(side="right", padx=5, pady=12)

        # Center: Step Dots Indicator
        dots_container = (
            ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=c.surface0)
        )
        dots_container.pack(side="left", expand=True, fill="both")

        dots_sub = (
            ctk.CTkFrame(dots_container, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(dots_container, bg=c.surface0)
        )
        dots_sub.pack(expand=True, pady=10)

        self.step_dots = []
        for i in range(6):
            if self.use_ctk:
                dot = ctk.CTkLabel(dots_sub, text="○", font=get_ctk_font(16, "bold"), text_color=c.overlay0)
            else:
                dot = tk.Label(dots_sub, text="○", font=get_tk_font(12, "bold"), bg=c.surface0, fg=c.blockquote)
            dot.pack(side="left", padx=5)
            self.step_dots.append(dot)

    def _show_page(self, index):
        self.current_page = index

        # Clear existing content frame
        for child in self.content_frame.winfo_children():
            child.destroy()

        # Render corresponding page contents
        if index == 0:
            self._create_welcome_page(self.content_frame)
        elif index == 1:
            self._create_keys_page(self.content_frame)
        elif index == 2:
            self._create_profile_page(self.content_frame)
        elif index == 3:
            self._create_tools_page(self.content_frame)
        elif index == 4:
            self._create_actions_page(self.content_frame)
        elif index == 5:
            self._create_complete_page(self.content_frame)

        self._update_step_indicator()

    def _update_step_indicator(self):
        c = self.colors

        # Highlight current dot
        for i, dot in enumerate(self.step_dots):
            if i == self.current_page:
                if self.use_ctk:
                    dot.configure(text="●", text_color=c.accent)
                else:
                    dot.configure(text="●", fg=c.accent)
            else:
                if self.use_ctk:
                    dot.configure(text="○", text_color=c.overlay0)
                else:
                    dot.configure(text="○", fg=c.blockquote)

        # Back button configuration
        if self.current_page == 0:
            if self.use_ctk:
                self.btn_back.configure(state="disabled")
            else:
                self.btn_back.configure(state="disabled")
        else:
            if self.use_ctk:
                self.btn_back.configure(state="normal")
            else:
                self.btn_back.configure(state="normal")

        # Next/Finish button configuration
        if self.current_page == len(self.step_dots) - 1:
            if self.use_ctk:
                self.btn_next.configure(
                    text="Finish", fg_color=c.accent_green, hover_color=_adjust_hex_color(c.accent_green, 0.85)
                )
            else:
                self.btn_next.configure(text="Finish", bg=c.accent_green)
        else:
            if self.use_ctk:
                self.btn_next.configure(text="Next", fg_color=c.accent, hover_color=c.lavender)
            else:
                self.btn_next.configure(text="Next", bg=c.accent)

        # Skip button configuration
        if self.current_page == len(self.step_dots) - 1:
            if self.use_ctk:
                self.btn_skip.configure(state="disabled")
            else:
                self.btn_skip.configure(state="disabled")
        else:
            if self.use_ctk:
                self.btn_skip.configure(state="normal")
            else:
                self.btn_skip.configure(state="normal")

    def _go_next(self):
        # Validation on API Key page
        if self.current_page == 1:
            has_any = False
            for pool_id in ["google", "anthropic", "openai", "openrouter", "xai", "mistral", "cohere", "custom"]:
                if self._key_store.get_pool(pool_id):
                    has_any = True
                    break

            if not has_any:
                ans = messagebox.askyesno(
                    "No API Keys Added",
                    "You have not added any API keys yet. Without a key, AI features will not work.\n\n"
                    "Would you like to proceed anyway?",
                    parent=self.root,
                )
                if not ans:
                    return

        # Save profile on Default Profile page
        elif self.current_page == 2:
            self._save_profile()

        # Save tool toggles on Tools page
        elif self.current_page == 3:
            self._save_tool_toggles()

        # Save action/modifier visibility on Actions page
        elif self.current_page == 4:
            self._save_action_visibility()

        if self.current_page < len(self.step_dots) - 1:
            self._show_page(self.current_page + 1)
        else:
            self._finish()

    def _go_back(self):
        if self.current_page > 0:
            self._show_page(self.current_page - 1)

    def _skip(self):
        ans = messagebox.askyesno(
            "Skip Welcome Guide",
            "Are you sure you want to skip the welcome guide? You can run it again later.",
            parent=self.root,
        )
        if ans:
            self._mark_completed()
            self._close()

    def _finish(self):
        self._mark_completed()
        self._close()

    def _mark_completed(self):
        try:
            save_config_value("onboarding_completed", True)
        except Exception as e:
            print(f"[Onboarding] Error marking onboarding as completed: {e}")

    def _close(self):
        self._destroyed = True
        if self.on_close_callback:
            try:
                self.on_close_callback()
            except Exception as e:
                print(f"[Onboarding] Error in on_close callback: {e}")

        if self.root:
            try:
                self.root.destroy()
            except Exception:
                pass

    def _run_event_loop(self):
        """Run event loop without blocking other Tk instances (for standalone use)."""
        try:
            while self.root is not None and not self._destroyed:
                try:
                    if not self.root.winfo_exists():
                        break
                    self.root.update()
                    time.sleep(0.01)
                except tk.TclError:
                    break
        except Exception:
            pass

    # ─── Pages ──────────────────────────────────────────────────────────

    def _create_welcome_page(self, parent):
        c = self.colors

        if self.use_ctk:
            title = ctk.CTkLabel(
                parent, text="Welcome to AIPromptBridge", font=get_ctk_font(22, "bold"), **get_ctk_label_colors(c)
            )
            title.pack(pady=(20, 5))

            ver = ctk.CTkLabel(
                parent, text=f"Version {__version__}", font=get_ctk_font(12), **get_ctk_label_colors(c, muted=True)
            )
            ver.pack()

            desc = ctk.CTkLabel(
                parent,
                text="A Windows system-wide app that brings AI assistance to your fingertips.\n"
                "Edit text, capture screens, transcribe audio, and chat with AI — all from your system tray.\n"
                "Let's get you set up in just a few quick steps!",
                font=get_ctk_font(13),
                justify="center",
                wraplength=600,
                **get_ctk_label_colors(c),
            )
            desc.pack(pady=(15, 10))

            features_frame = ctk.CTkFrame(parent, fg_color="transparent")
            features_frame.pack(fill="x", expand=True, padx=20)
        else:
            title = tk.Label(parent, text="Welcome to AIPromptBridge", font=get_tk_font(18, "bold"), bg=c.bg, fg=c.fg)
            title.pack(pady=(20, 5))

            ver = tk.Label(parent, text=f"Version {__version__}", font=get_tk_font(9), bg=c.bg, fg=c.blockquote)
            ver.pack()

            desc = tk.Label(
                parent,
                text="A Windows system-wide app that brings AI assistance to your fingertips.\n"
                "Edit text, capture screens, transcribe audio, and chat with AI — all from your system tray.\n"
                "Let's get you set up in just a few quick steps!",
                font=get_tk_font(10),
                justify="center",
                bg=c.bg,
                fg=c.fg,
            )
            desc.pack(pady=(15, 10))

            features_frame = tk.Frame(parent, bg=c.bg)
            features_frame.pack(fill="x", expand=True, padx=20)

        features = [
            (
                "🔑",
                "Secure API Keys",
                "Keys saved locally with XOR obfuscation. Add multiple per provider for auto-rotation.",
            ),
            ("🤖", "Multi-Provider AI", "Gemini, Claude, OpenAI, OpenRouter, xAI, Mistral, Cohere & custom endpoints."),
            (
                "⚡",
                "Global Hotkeys",
                "Edit text, capture screens, transcribe speech, or hear AI read aloud — anywhere.",
            ),
            ("💬", "Chat Interface", "Streaming responses, markdown rendering, and full session history."),
            (
                "🎨",
                "Themes & Customization",
                "6 themes with dark/light modes, custom prompts, and per-action profiles.",
            ),
        ]

        for emoji, name, text in features:
            row = (
                ctk.CTkFrame(features_frame, fg_color=c.surface0, corner_radius=8)
                if self.use_ctk
                else tk.Frame(features_frame, bg=c.surface0, bd=1, relief="solid", pady=4)
            )
            row.pack(fill="x", pady=4, ipady=4)

            if self.use_ctk:
                if HAVE_EMOJI and prepare_emoji_content:
                    icon_lbl = ctk.CTkLabel(
                        row,
                        font=get_ctk_font(24),
                        width=40,
                        **prepare_emoji_content(emoji, size=24),
                        **get_ctk_label_colors(c),
                    )
                else:
                    icon_lbl = ctk.CTkLabel(row, text=emoji, font=get_ctk_font(24), width=40, **get_ctk_label_colors(c))
                icon_lbl.pack(side="left", padx=(15, 10))

                txt_container = ctk.CTkFrame(row, fg_color="transparent")
                txt_container.pack(side="left", fill="both", expand=True)

                title_lbl = ctk.CTkLabel(
                    txt_container, text=name, font=get_ctk_font(12, "bold"), anchor="w", **get_ctk_label_colors(c)
                )
                title_lbl.pack(anchor="w")

                body_lbl = ctk.CTkLabel(
                    txt_container,
                    text=text,
                    font=get_ctk_font(11),
                    anchor="w",
                    wraplength=530,
                    **get_ctk_label_colors(c, muted=True),
                )
                body_lbl.pack(anchor="w")
            else:
                icon_lbl = tk.Label(row, text=emoji, font=get_tk_font(18), width=4, bg=c.surface0, fg=c.fg)
                icon_lbl.pack(side="left", padx=10)

                txt_container = tk.Frame(row, bg=c.surface0)
                txt_container.pack(side="left", fill="both", expand=True)

                title_lbl = tk.Label(
                    txt_container, text=name, font=get_tk_font(9, "bold"), anchor="w", bg=c.surface0, fg=c.fg
                )
                title_lbl.pack(anchor="w")

                body_lbl = tk.Label(
                    txt_container,
                    text=text,
                    font=get_tk_font(8),
                    anchor="w",
                    wraplength=530,
                    bg=c.surface0,
                    fg=c.blockquote,
                )
                body_lbl.pack(anchor="w")

    def _create_keys_page(self, parent):
        c = self.colors

        if self.use_ctk:
            title = ctk.CTkLabel(parent, text="Configure API Keys", font=get_ctk_font(22, "bold"), text_color=c.accent)
            title.pack(pady=(10, 5))

            subtitle = ctk.CTkLabel(
                parent,
                text="Add your API keys to get started. You can add multiple keys and organize them in pools.",
                font=get_ctk_font(13),
                text_color=c.blockquote,
                wraplength=600,
            )
            subtitle.pack(pady=(0, 15))
        else:
            title = tk.Label(parent, text="Configure API Keys", font=get_tk_font(14, "bold"), bg=c.bg, fg=c.fg)
            title.pack(pady=(10, 5))

            subtitle = tk.Label(
                parent,
                text="Add your API keys to get started. You can add multiple keys and organize them in pools.",
                font=get_tk_font(9),
                justify="left",
                bg=c.bg,
                fg=c.blockquote,
            )
            subtitle.pack(pady=(0, 15))

        # Split layout: left form + right list
        if self.use_ctk:
            split_frame = ctk.CTkFrame(parent, fg_color="transparent")
        else:
            split_frame = tk.Frame(parent, bg=c.bg)
        split_frame.pack(fill="both", expand=True)
        split_frame.columnconfigure(0, weight=1, minsize=300)
        split_frame.columnconfigure(1, weight=1, minsize=280)
        split_frame.rowconfigure(0, weight=1)

        # ── Left Column: Add New Key Form ──────────────────────────────
        if self.use_ctk:
            form_frame = ctk.CTkFrame(
                split_frame, fg_color=c.surface0, border_color=c.surface2, border_width=1, corner_radius=10
            )
        else:
            form_frame = tk.Frame(split_frame, bg=c.surface0, bd=1, relief="solid")
        form_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        if self.use_ctk:
            ctk.CTkLabel(form_frame, text="Add New Key", font=get_ctk_font(14, "bold"), text_color=c.accent).pack(
                anchor="w", padx=15, pady=(15, 10)
            )
        else:
            tk.Label(form_frame, text="Add New Key", font=get_tk_font(11, "bold"), bg=c.surface0, fg=c.fg).pack(
                anchor="w", padx=15, pady=(12, 8)
            )

        # Provider Pool dropdown
        self._pool_mapping = {
            "Google Gemini": "google",
            "Anthropic Claude": "anthropic",
            "OpenAI": "openai",
            "OpenRouter": "openrouter",
            "xAI (Grok)": "xai",
            "Mistral": "mistral",
            "Cohere": "cohere",
            "Custom OpenAI-Compatible": "custom",
        }
        if self.use_ctk:
            ctk.CTkLabel(form_frame, text="Provider Pool:", font=get_ctk_font(12), text_color=c.fg).pack(
                anchor="w", padx=15, pady=(5, 2)
            )
        else:
            tk.Label(form_frame, text="Provider Pool:", font=get_tk_font(9), bg=c.surface0, fg=c.fg).pack(
                anchor="w", padx=15, pady=(5, 2)
            )

        self._pool_var = tk.StringVar(value="Google Gemini")
        if self.use_ctk:
            self._pool_dropdown = ctk.CTkOptionMenu(
                form_frame,
                variable=self._pool_var,
                values=list(self._pool_mapping.keys()),
                command=self._on_pool_changed,
                height=32,
                fg_color=c.surface1,
                button_color=c.surface2,
                button_hover_color=c.overlay0,
                dropdown_fg_color=c.surface0,
                dropdown_hover_color=c.surface1,
                text_color=c.fg,
                font=get_ctk_font(12),
            )
            self._pool_dropdown.pack(fill="x", padx=15, pady=(0, 10))
        else:
            self._pool_dropdown = ttk.Combobox(
                form_frame, textvariable=self._pool_var, values=list(self._pool_mapping.keys()), state="readonly"
            )
            self._pool_dropdown.pack(fill="x", padx=15, pady=(0, 10))
            self._pool_dropdown.bind("<<ComboboxSelected>>", lambda e: self._on_pool_changed(self._pool_var.get()))

        # API Key entry with show/hide toggle
        if self.use_ctk:
            ctk.CTkLabel(form_frame, text="API Key:", font=get_ctk_font(12), text_color=c.fg).pack(
                anchor="w", padx=15, pady=(5, 2)
            )
        else:
            tk.Label(form_frame, text="API Key:", font=get_tk_font(9), bg=c.surface0, fg=c.fg).pack(
                anchor="w", padx=15, pady=(5, 2)
            )

        key_input_row = (
            ctk.CTkFrame(form_frame, fg_color="transparent") if self.use_ctk else tk.Frame(form_frame, bg=c.surface0)
        )
        key_input_row.pack(fill="x", padx=15, pady=(0, 10))

        self._key_entry_var = tk.StringVar()
        self._show_key = False

        if self.use_ctk:
            self._key_entry = ctk.CTkEntry(
                key_input_row,
                textvariable=self._key_entry_var,
                font=get_ctk_font(12),
                height=32,
                show="*",
                placeholder_text="Paste your API key here...",
                fg_color=c.input_bg,
                border_color=c.surface1,
                text_color=c.fg,
            )
            self._key_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

            _eye_kwargs = (
                prepare_emoji_content("👁", size=16) if (HAVE_EMOJI and prepare_emoji_content) else {"text": "👁"}
            )
            self._btn_show_key = ctk.CTkButton(
                key_input_row,
                width=32,
                height=32,
                fg_color=c.surface1,
                hover_color=c.surface2,
                text_color=c.fg,
                command=self._toggle_key_visibility,
                **_eye_kwargs,
            )
            self._btn_show_key.pack(side="right")
        else:
            self._key_entry = tk.Entry(key_input_row, textvariable=self._key_entry_var, font=get_tk_font(9), show="*")
            self._key_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

            self._btn_show_key = tk.Button(
                key_input_row,
                text="👁",
                font=get_tk_font(9),
                bg=c.surface1,
                fg=c.fg,
                command=self._toggle_key_visibility,
            )
            self._btn_show_key.pack(side="right")

        # Optional name/label
        if self.use_ctk:
            ctk.CTkLabel(form_frame, text="Name / Label (Optional):", font=get_ctk_font(12), text_color=c.fg).pack(
                anchor="w", padx=15, pady=(5, 2)
            )
        else:
            tk.Label(form_frame, text="Name / Label (Optional):", font=get_tk_font(9), bg=c.surface0, fg=c.fg).pack(
                anchor="w", padx=15, pady=(5, 2)
            )

        self._key_name_var = tk.StringVar()
        if self.use_ctk:
            ctk.CTkEntry(
                form_frame,
                textvariable=self._key_name_var,
                font=get_ctk_font(12),
                height=32,
                placeholder_text="e.g. My Primary Key",
                fg_color=c.input_bg,
                border_color=c.surface1,
                text_color=c.fg,
            ).pack(fill="x", padx=15, pady=(0, 15))
        else:
            tk.Entry(form_frame, textvariable=self._key_name_var, font=get_tk_font(9)).pack(
                fill="x", padx=15, pady=(0, 15)
            )

        create_emoji_button(form_frame, "Add Key", "➕", c, variant="success", height=34, command=self._add_key).pack(
            fill="x", padx=15, pady=(0, 15)
        )

        # ── Right Column: Key List ─────────────────────────────────────
        if self.use_ctk:
            list_container = ctk.CTkFrame(
                split_frame, fg_color=c.surface0, border_color=c.surface2, border_width=1, corner_radius=10
            )
        else:
            list_container = tk.Frame(split_frame, bg=c.surface0, bd=1, relief="solid")
        list_container.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        self._list_header_var = tk.StringVar(value="Current Keys (google)")
        if self.use_ctk:
            ctk.CTkLabel(
                list_container, textvariable=self._list_header_var, font=get_ctk_font(14, "bold"), text_color=c.accent
            ).pack(anchor="w", padx=15, pady=(15, 10))
        else:
            tk.Label(
                list_container,
                textvariable=self._list_header_var,
                font=get_tk_font(10, "bold"),
                bg=c.surface0,
                fg=c.fg,
            ).pack(anchor="w", padx=15, pady=(12, 8))

        self._key_list = ScrollableButtonList(
            list_container, colors=c, command=self._on_key_selected, corner_radius=6, fg_color=c.input_bg
        )
        self._key_list.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        self._btn_remove_key = create_emoji_button(
            list_container, "Remove Selected Key", "✕", c, variant="danger", height=32, command=self._remove_key
        )
        self._btn_remove_key.pack(fill="x", padx=15, pady=(0, 15))
        self._btn_remove_key.configure(state="disabled")

        self._refresh_key_display()

    def _on_pool_changed(self, value):
        pool_id = self._pool_mapping.get(value, "google")
        self._list_header_var.set(f"Current Keys ({pool_id})")
        self._key_list.selection_clear()
        self._btn_remove_key.configure(state="disabled")
        self._refresh_key_display()

    def _toggle_key_visibility(self):
        self._show_key = not self._show_key
        if self._show_key:
            self._key_entry.configure(show="")
            if self.use_ctk and HAVE_EMOJI and prepare_emoji_content:
                self._btn_show_key.configure(**prepare_emoji_content("🔒", size=16))
            else:
                self._btn_show_key.configure(text="🔒")
        else:
            self._key_entry.configure(show="*")
            if self.use_ctk and HAVE_EMOJI and prepare_emoji_content:
                self._btn_show_key.configure(**prepare_emoji_content("👁", size=16))
            else:
                self._btn_show_key.configure(text="👁")

    def _refresh_key_display(self):
        if not hasattr(self, "_key_list"):
            return
        pool_id = self._pool_mapping.get(self._pool_var.get(), "google")
        self._key_list.clear()
        keys_data = self._key_store.get_pool(pool_id)
        for i, kd in enumerate(keys_data):
            masked = self._mask_key(kd)
            self._key_list.add_item(str(i), masked, "🔑")

    def _mask_key(self, key_data: dict) -> str:
        key = key_data.get("key", "")
        name = key_data.get("name", "")
        if len(key) <= 8:
            masked = "*" * len(key)
        else:
            masked = key[:4] + "…" + key[-4:]
        if name:
            return f"{masked}  ({name})"
        return masked

    def _add_key(self):
        pool_id = self._pool_mapping.get(self._pool_var.get(), "google")
        key = self._key_entry_var.get().strip()
        name = self._key_name_var.get().strip()
        if not key:
            messagebox.showwarning("Empty Key", "Please enter a valid API key.", parent=self.root)
            return
        self._key_store.add_key(pool_id, key, name)
        self._key_store.save()
        self._key_entry_var.set("")
        self._key_name_var.set("")
        self._refresh_key_display()

    def _on_key_selected(self, item_id):
        if hasattr(self, "_btn_remove_key") and self._btn_remove_key:
            self._btn_remove_key.configure(state="normal")

    def _remove_key(self):
        pool_id = self._pool_mapping.get(self._pool_var.get(), "google")
        selected = self._key_list.get_selected()
        if selected is not None:
            idx = int(selected)
            self._key_store.remove_key(pool_id, idx)
            self._key_store.save()
            self._key_list.selection_clear()
            self._btn_remove_key.configure(state="disabled")
            self._refresh_key_display()

    def _delete_key(self, pool_id, idx):
        """Legacy helper kept for compatibility — delegates to remove."""
        if self._key_store.remove_key(pool_id, idx):
            self._key_store.save()
            self._refresh_key_display()

    def _create_profile_page(self, parent):
        c = self.colors

        if self.use_ctk:
            title = ctk.CTkLabel(
                parent, text="Step 2: Choose Default Model", font=get_ctk_font(18, "bold"), **get_ctk_label_colors(c)
            )
            title.pack(anchor="w", pady=(10, 5))

            subtitle = ctk.CTkLabel(
                parent,
                text="Configure which AI provider and model will be your global default. You can change this anytime.",
                font=get_ctk_font(12),
                justify="left",
                **get_ctk_label_colors(c, muted=True),
            )
            subtitle.pack(anchor="w", pady=(0, 15))

            form_frame = ctk.CTkFrame(parent, fg_color=c.surface0, corner_radius=8)
            form_frame.pack(fill="both", expand=True, padx=5, pady=5, ipady=10)
        else:
            title = tk.Label(
                parent, text="Step 2: Choose Default Model", font=get_tk_font(14, "bold"), bg=c.bg, fg=c.fg
            )
            title.pack(anchor="w", pady=(10, 5))

            subtitle = tk.Label(
                parent,
                text="Configure which AI provider and model will be your global default. You can change this anytime.",
                font=get_tk_font(9),
                justify="left",
                bg=c.bg,
                fg=c.blockquote,
            )
            subtitle.pack(anchor="w", pady=(0, 15))

            form_frame = tk.Frame(parent, bg=c.surface0, bd=1, relief="solid")
            form_frame.pack(fill="both", expand=True, padx=5, pady=5, ipady=10)

        # Variables initialization
        if not hasattr(self, "_provider_var"):
            profile = self._profile_store.get_profile("Default")
            if not profile:
                profile = ConnectionProfile()

            self._provider_var = tk.StringVar(value=profile.provider)
            self._model_var = tk.StringVar(value=profile.model)
            self._base_url_var = tk.StringVar(value=profile.base_url or "")

            defs = get_provider_definitions()
            self.provider_id_map = {defs[pid].name: pid for pid in defs}
            self.provider_names_list = sorted(list(self.provider_id_map.keys()))

        # Provider Selector Row
        row1 = ctk.CTkFrame(form_frame, fg_color="transparent") if self.use_ctk else tk.Frame(form_frame, bg=c.surface0)
        row1.pack(fill="x", padx=20, pady=8)

        defs = get_provider_definitions()
        current_display = (
            defs[self._provider_var.get()].name if self._provider_var.get() in defs else self._provider_var.get()
        )
        self.profile_provider_display_var = tk.StringVar(value=current_display)

        if self.use_ctk:
            ctk.CTkLabel(
                row1, text="Provider:", font=get_ctk_font(13, "bold"), width=120, anchor="w", **get_ctk_label_colors(c)
            ).pack(side="left")
            combo = ctk.CTkComboBox(
                row1,
                variable=self.profile_provider_display_var,
                values=self.provider_names_list,
                width=240,
                height=32,
                font=get_ctk_font(13),
                state="readonly",
                command=self._on_profile_provider_change,
                **get_ctk_combobox_colors(c),
            )
            combo.pack(side="left")
        else:
            tk.Label(
                row1, text="Provider:", font=get_tk_font(10, "bold"), width=14, anchor="w", bg=c.surface0, fg=c.fg
            ).pack(side="left")
            combo = ttk.Combobox(
                row1,
                textvariable=self.profile_provider_display_var,
                values=self.provider_names_list,
                width=28,
                state="readonly",
            )
            combo.pack(side="left")
            combo.bind(
                "<<ComboboxSelected>>",
                lambda e: self._on_profile_provider_change(self.profile_provider_display_var.get()),
            )

        # Model Selector Row
        row2 = ctk.CTkFrame(form_frame, fg_color="transparent") if self.use_ctk else tk.Frame(form_frame, bg=c.surface0)
        row2.pack(fill="x", padx=20, pady=8)

        if self.use_ctk:
            ctk.CTkLabel(
                row2, text="Model:", font=get_ctk_font(13, "bold"), width=120, anchor="w", **get_ctk_label_colors(c)
            ).pack(side="left")

            self.model_combo = ScrollableComboBox(
                row2, colors=c, variable=self._model_var, values=[], width=240, height=32, font_size=13
            )
            self.model_combo.pack(side="left")

            create_emoji_button(row2, "", "🔄", c, "secondary", 34, 32, self._refresh_models).pack(
                side="left", padx=(8, 0)
            )

            self._model_status_label = ctk.CTkLabel(
                row2, text="", font=get_ctk_font(11), **get_ctk_label_colors(c, muted=True)
            )
            self._model_status_label.pack(side="left", padx=(10, 0))
        else:
            tk.Label(
                row2, text="Model:", font=get_tk_font(10, "bold"), width=14, anchor="w", bg=c.surface0, fg=c.fg
            ).pack(side="left")
            self.model_combo = ttk.Combobox(row2, textvariable=self._model_var, values=[], width=26)
            self.model_combo.pack(side="left")

            tk.Button(row2, text="🔄", font=get_tk_font(9), bg=c.surface1, fg=c.fg, command=self._refresh_models).pack(
                side="left", padx=(6, 0)
            )

            self._model_status_label = tk.Label(row2, text="", font=get_tk_font(9), bg=c.surface0, fg=c.blockquote)
            self._model_status_label.pack(side="left", padx=(8, 0))

        # Base URL row — only shown for custom (OAI-compatible) provider
        self._base_url_row = (
            ctk.CTkFrame(form_frame, fg_color="transparent") if self.use_ctk else tk.Frame(form_frame, bg=c.surface0)
        )
        # (not packed yet; shown dynamically by _on_profile_provider_change)

        if self.use_ctk:
            ctk.CTkLabel(
                self._base_url_row,
                text="Base URL:",
                font=get_ctk_font(13, "bold"),
                width=120,
                anchor="w",
                **get_ctk_label_colors(c),
            ).pack(side="left")
            ctk.CTkEntry(
                self._base_url_row,
                textvariable=self._base_url_var,
                font=get_ctk_font(12),
                width=320,
                height=32,
                placeholder_text="https://api.example.com/v1",
                fg_color=c.input_bg,
                border_color=c.surface1,
                text_color=c.fg,
            ).pack(side="left")
        else:
            tk.Label(
                self._base_url_row,
                text="Base URL:",
                font=get_tk_font(10, "bold"),
                width=14,
                anchor="w",
                bg=c.surface0,
                fg=c.fg,
            ).pack(side="left")
            tk.Entry(self._base_url_row, textvariable=self._base_url_var, font=get_tk_font(9), width=35).pack(
                side="left"
            )

        # Populate model dropdown and trigger visibility logic
        self._on_profile_provider_change(self.profile_provider_display_var.get(), update_var=False)

    def _on_profile_provider_change(self, display_name, update_var=True):
        provider_id = self.provider_id_map.get(display_name, "google")
        if update_var:
            self._provider_var.set(provider_id)

        # Show Base URL field only for custom OAI-compatible provider
        if hasattr(self, "_base_url_row"):
            if provider_id == "custom":
                self._base_url_row.pack(fill="x", padx=20, pady=(0, 8))
            else:
                self._base_url_row.pack_forget()

        models = get_fallback_models(provider_id)
        self.model_combo.configure(values=models)

        if models:
            current_model = self._model_var.get()
            # Only overwrite if current model is empty
            if not current_model.strip():
                self._model_var.set(models[0])

    def _refresh_models(self):
        provider = self._provider_var.get()
        if not provider:
            self._set_model_status("Select provider first", "error")
            return

        # Capture base_url before entering the thread
        base_url = ""
        if provider == "custom":
            base_url = self._base_url_var.get().strip() if hasattr(self, "_base_url_var") else ""
            if not base_url:
                self._set_model_status("Enter Base URL first", "error")
                return

        self._set_model_status("🔄 Loading...", "info")

        def _fetch():
            try:
                from ...key_manager import KeyManager
                from ...key_store import KeyStore
                from ...providers import create_provider

                key_store = KeyStore.get_instance()
                keys_data = key_store.get_pool_for_provider(provider)
                key_strings = [kd["key"] for kd in keys_data if kd.get("key")]
                if not key_strings:
                    self._schedule_ui(lambda: self._set_model_status("Requires API Key", "error"))
                    return

                temp_km = KeyManager(key_strings, provider)
                temp_config = {"request_timeout": 30}

                # Use the user-provided base URL for custom, or provider default
                if base_url:
                    temp_config["base_url"] = base_url
                else:
                    defs = get_provider_definitions()
                    if provider in defs:
                        temp_config["base_url"] = defs[provider].default_base_url

                provider_instance = create_provider(provider, temp_km, temp_config)
                models, error = provider_instance.fetch_models()

                if error:
                    err_msg = str(error)[:35]
                    fallback = get_fallback_models(provider)

                    def _fallback_with_error(msg=err_msg, fb=fallback):
                        if hasattr(self, "model_combo") and self.model_combo:
                            self.model_combo.configure(values=fb)
                            # Only overwrite if empty
                            if fb and not self._model_var.get().strip():
                                self._model_var.set(fb[0])
                        self._set_model_status(msg, "error")

                    self._schedule_ui(_fallback_with_error)
                    return

                if not models:
                    fallback = get_fallback_models(provider)

                    def _fallback_no_models(fb=fallback):
                        if hasattr(self, "model_combo") and self.model_combo:
                            self.model_combo.configure(values=fb)
                            # Only overwrite if empty
                            if fb and not self._model_var.get().strip():
                                self._model_var.set(fb[0])
                        self._set_model_status("No models", "warning")

                    self._schedule_ui(_fallback_no_models)
                    return

                model_ids = [m.get("id", str(m)) for m in models]

                def _update():
                    if hasattr(self, "model_combo") and self.model_combo:
                        self.model_combo.configure(values=model_ids)
                        if model_ids:
                            self._model_var.set(model_ids[0])
                    self._set_model_status(f"✅ {len(model_ids)} models", "success")

                self._schedule_ui(_update)

            except Exception as e:
                err_msg = str(e)[:30]
                fallback = get_fallback_models(provider)

                def _fallback_on_exception(msg=err_msg, fb=fallback):
                    if hasattr(self, "model_combo") and self.model_combo:
                        self.model_combo.configure(values=fb)
                        # Only overwrite if empty
                        if fb and not self._model_var.get().strip():
                            self._model_var.set(fb[0])
                    self._set_model_status(msg, "error")

                self._schedule_ui(_fallback_on_exception)

        threading.Thread(target=_fetch, daemon=True).start()

    def _set_model_status(self, text: str, level: str = "info"):
        if not self._model_status_label:
            return
        c = self.colors
        color_map = {
            "error": c.accent_red,
            "success": c.accent_green,
            "warning": getattr(c, "accent_yellow", c.accent),
            "info": c.accent,
        }
        color = color_map.get(level, c.blockquote)
        if self.use_ctk:
            self._model_status_label.configure(text=text, text_color=color)
        else:
            self._model_status_label.configure(text=text, fg=color)

    def _schedule_ui(self, callback):
        if self._destroyed:
            return

        def safe_wrapper():
            if not self._destroyed:
                try:
                    callback()
                except Exception:
                    pass

        try:
            from ..core import GUICoordinator

            GUICoordinator.get_instance().run_on_gui_thread(safe_wrapper)
        except Exception:
            try:
                if self.root and self.root.winfo_exists():
                    self.root.after(0, safe_wrapper)
            except Exception:
                pass

    def _save_profile(self):
        provider = self._provider_var.get()
        model = self._model_var.get()
        base_url = self._base_url_var.get().strip() if hasattr(self, "_base_url_var") else ""

        profile = self._profile_store.get_profile("Default")
        if not profile:
            profile = ConnectionProfile()

        profile.provider = provider
        profile.model = model
        profile.streaming = True  # always on for simplicity
        profile.thinking = False  # always off by default
        if provider == "custom" and base_url:
            profile.base_url = base_url

        self._profile_store.set_profile("Default", profile)

        # Ensure Default is set as the active profile
        self._profile_store.set_active_profile("Default")
        try:
            from ...web_server import switch_active_profile

            switch_active_profile("Default")
        except Exception:
            pass

    def _create_tools_page(self, parent):
        """Create Step 3: Tool Toggles page."""
        c = self.colors

        if self.use_ctk:
            title = ctk.CTkLabel(
                parent, text="Step 3: Enable/Disable Tools", font=get_ctk_font(18, "bold"), **get_ctk_label_colors(c)
            )
            title.pack(anchor="w", pady=(10, 5))

            subtitle = ctk.CTkLabel(
                parent,
                text="Choose which tools to activate. Disabled tools won't register hotkeys or appear in menus.\nYou can change these anytime in Settings.",
                font=get_ctk_font(12),
                justify="left",
                **get_ctk_label_colors(c, muted=True),
            )
            subtitle.pack(anchor="w", pady=(0, 15))
        else:
            title = tk.Label(
                parent, text="Step 3: Enable/Disable Tools", font=get_tk_font(14, "bold"), bg=c.bg, fg=c.fg
            )
            title.pack(anchor="w", pady=(10, 5))

            subtitle = tk.Label(
                parent,
                text="Choose which tools to activate. Disabled tools won't register hotkeys or appear in menus.\nYou can change these anytime in Settings.",
                font=get_tk_font(9),
                justify="left",
                bg=c.bg,
                fg=c.blockquote,
            )
            subtitle.pack(anchor="w", pady=(0, 15))

        # Load current config values
        config = load_config()

        onboarding_completed = config.get("onboarding_completed", False)
        if isinstance(onboarding_completed, str):
            onboarding_completed = onboarding_completed.strip().lower() in ("true", "1")
        is_first_run = not onboarding_completed

        # Initialize toggle vars
        self._tool_vars = {}

        tools = [
            (
                "text_edit_tool_enabled",
                "✏️ Text Edit Tool",
                "ctrl+space",
                "Select text anywhere and transform it with AI — edit, rewrite, translate, or ask questions about it.",
                True if is_first_run else config.get("text_edit_tool_enabled", True),
            ),
            (
                "screen_snip_enabled",
                "📸 Screen Snip Tool",
                "ctrl+alt+x",
                "Capture any screen area to extract text, analyze images, solve problems, or ask questions.",
                True if is_first_run else config.get("screen_snip_enabled", True),
            ),
            (
                "audio_tool_enabled",
                "🎙️ Audio Tool",
                "ctrl+alt+a",
                "Record microphone or system audio for transcription, analysis, and AI processing.",
                True if is_first_run else config.get("audio_tool_enabled", True),
            ),
            (
                "tts_enabled",
                "🔊 Text-to-Speech",
                "ctrl+alt+t",
                "Select text and hear AI read it aloud with expressive, natural-sounding voices.",
                False if is_first_run else config.get("tts_enabled", False),
            ),
        ]

        for config_key, name, hotkey, desc, default_on in tools:
            self._tool_vars[config_key] = tk.BooleanVar(value=default_on)

            if self.use_ctk:
                card = ctk.CTkFrame(parent, fg_color=c.surface0, corner_radius=8)
                card.pack(fill="x", pady=5, ipady=6)

                # Left: Toggle switch
                switch = ctk.CTkSwitch(
                    card,
                    text="",
                    variable=self._tool_vars[config_key],
                    fg_color=c.surface2,
                    progress_color=c.accent_green,
                    width=46,
                )
                switch.pack(side="left", padx=(15, 10), pady=8)

                # Center: Info
                info = ctk.CTkFrame(card, fg_color="transparent")
                info.pack(side="left", fill="both", expand=True, pady=8)

                header_row = ctk.CTkFrame(info, fg_color="transparent")
                header_row.pack(fill="x")

                if HAVE_EMOJI and prepare_emoji_content:
                    kwargs = prepare_emoji_content(name, size=18)
                    ctk.CTkLabel(header_row, font=get_ctk_font(13, "bold"), **kwargs, **get_ctk_label_colors(c)).pack(
                        side="left"
                    )
                else:
                    ctk.CTkLabel(header_row, text=name, font=get_ctk_font(13, "bold"), **get_ctk_label_colors(c)).pack(
                        side="left"
                    )

                # Hotkey badge
                tag = ctk.CTkFrame(header_row, fg_color=c.accent, corner_radius=4)
                tag.pack(side="left", padx=(10, 0))
                ctk.CTkLabel(tag, text=hotkey.upper(), font=get_ctk_font(10, "bold"), text_color=c.accent_fg).pack(
                    padx=6, pady=2
                )

                ctk.CTkLabel(
                    info,
                    text=desc,
                    font=get_ctk_font(11),
                    justify="left",
                    wraplength=550,
                    **get_ctk_label_colors(c, muted=True),
                ).pack(anchor="w")
            else:
                # Tk fallback with Checkbutton
                card = tk.Frame(parent, bg=c.surface0, bd=1, relief="solid")
                card.pack(fill="x", pady=4, ipady=4)
                tk.Checkbutton(
                    card,
                    text=name,
                    variable=self._tool_vars[config_key],
                    font=get_tk_font(10, "bold"),
                    bg=c.surface0,
                    fg=c.fg,
                    selectcolor=c.input_bg,
                ).pack(anchor="w", padx=10, pady=(5, 0))
                tk.Label(
                    card,
                    text=desc,
                    font=get_tk_font(8),
                    bg=c.surface0,
                    fg=c.blockquote,
                    wraplength=600,
                    justify="left",
                ).pack(anchor="w", padx=30)

        # Note about restart
        if is_first_run:
            note_text = "💡 These choices will take effect immediately upon completing the setup."
        else:
            note_text = "⚠️ Note: Tool changes made during a re-run require a restart to take effect."

        if self.use_ctk:
            ctk.CTkLabel(parent, text=note_text, font=get_ctk_font(11), **get_ctk_label_colors(c, muted=True)).pack(
                anchor="w", pady=(15, 0)
            )
        else:
            tk.Label(parent, text=note_text, font=get_tk_font(9), bg=c.bg, fg=c.blockquote).pack(
                anchor="w", pady=(10, 0)
            )

    def _save_tool_toggles(self):
        """Save tool enable/disable states to config.ini."""
        if not hasattr(self, "_tool_vars"):
            return
        for config_key, var in self._tool_vars.items():
            try:
                save_config_value(config_key, var.get())
            except Exception as e:
                print(f"[Onboarding] Error saving {config_key}: {e}")

    def _create_actions_page(self, parent):
        """Create Step 4: Actions & Modifiers selection page."""
        c = self.colors

        if self.use_ctk:
            title = ctk.CTkLabel(
                parent, text="Step 4: Choose Default Actions", font=get_ctk_font(18, "bold"), **get_ctk_label_colors(c)
            )
            title.pack(anchor="w", pady=(10, 3))

            subtitle = ctk.CTkLabel(
                parent,
                text="Select which actions appear in tool popups. Start minimal, you can enable more anytime in the Prompt Editor.",
                font=get_ctk_font(12),
                justify="left",
                wraplength=680,
                **get_ctk_label_colors(c, muted=True),
            )
            subtitle.pack(anchor="w", pady=(0, 10))

            # Sub-tabs
            self._actions_subtab = ctk.CTkSegmentedButton(
                parent,
                values=["Text Edit", "Snip Tool", "Audio Tool", "Modifiers"],
                command=self._on_actions_subtab_change,
                font=get_ctk_font(12, "bold"),
                **get_ctk_segmented_colors(c),
            )
            self._actions_subtab.set("Text Edit")
            self._actions_subtab.pack(fill="x", pady=(0, 8))

            # Container for list content
            self._actions_content_frame = ctk.CTkFrame(parent, fg_color="transparent")
            self._actions_content_frame.pack(fill="both", expand=True)
        else:
            # tk fallback - simple notebook or manual tabs
            title = tk.Label(
                parent, text="Step 4: Choose Default Actions", font=get_tk_font(14, "bold"), bg=c.bg, fg=c.fg
            )
            title.pack(anchor="w", pady=(10, 3))

            subtitle = tk.Label(
                parent,
                text="Select which actions appear in tool popups. Start minimal, you can enable more anytime in the Prompt Editor.",
                font=get_tk_font(9),
                bg=c.bg,
                fg=c.blockquote,
                justify="left",
            )
            subtitle.pack(anchor="w", pady=(0, 10))

            self._actions_content_frame = tk.Frame(parent, bg=c.bg)
            self._actions_content_frame.pack(fill="both", expand=True)

        # Initialize tab frames cache
        self._tab_frames = {}

        # Initialize toggle vars for all default actions
        self._init_action_toggles()

        # Show first sub-tab
        self._show_actions_subtab("Text Edit")

    def _init_action_toggles(self):
        """Initialize toggle variables for all default actions and modifiers."""
        from ..prompts import (
            DEFAULT_AUDIO_ACTIONS,
            DEFAULT_GLOBAL_SETTINGS,
            DEFAULT_SNIP_ACTIONS,
            DEFAULT_TEXT_EDIT_ACTIONS,
            PromptsConfig,
        )

        # Check if onboarding completed already (re-run wizard scenario)
        prompts_config = PromptsConfig.get_instance()
        config_data = load_config()
        onboarding_completed = config_data.get("onboarding_completed", False)
        if isinstance(onboarding_completed, str):
            onboarding_completed = onboarding_completed.strip().lower() in ("true", "1")
        is_rerun = onboarding_completed

        # Action toggles: {tool: {action_name: BooleanVar}}
        self._action_toggle_vars = {}

        # Text Edit Tool
        self._action_toggle_vars["text_edit_tool"] = {}
        for name in DEFAULT_TEXT_EDIT_ACTIONS:
            if name.startswith("_"):
                continue  # Skip _Custom, _Ask
            if is_rerun:
                # On re-run, use current visibility state
                existing = prompts_config.get_text_edit_tool().get(name, {})
                default_visible = not existing.get("_hidden", False)
            else:
                # First time: use minimal selection
                default_visible = name in self.WIZARD_MINIMAL_TEXT_EDIT
            self._action_toggle_vars["text_edit_tool"][name] = tk.BooleanVar(value=default_visible)

        # Snip Tool
        self._action_toggle_vars["snip_tool"] = {}
        for name in DEFAULT_SNIP_ACTIONS:
            if name.startswith("_"):
                continue
            if is_rerun:
                existing = prompts_config.get_snip_tool().get(name, {})
                default_visible = not existing.get("_hidden", False)
            else:
                default_visible = name in self.WIZARD_MINIMAL_SNIP
            self._action_toggle_vars["snip_tool"][name] = tk.BooleanVar(value=default_visible)

        # Audio Tool
        self._action_toggle_vars["audio_tool"] = {}
        for name in DEFAULT_AUDIO_ACTIONS:
            if name.startswith("_"):
                continue
            if is_rerun:
                existing = prompts_config.get_audio_tool().get(name, {})
                default_visible = not existing.get("_hidden", False)
            else:
                default_visible = name in self.WIZARD_MINIMAL_AUDIO
            self._action_toggle_vars["audio_tool"][name] = tk.BooleanVar(value=default_visible)

        # Modifiers
        self._modifier_toggle_vars = {}
        default_modifiers = DEFAULT_GLOBAL_SETTINGS.get("modifiers", [])
        for mod in default_modifiers:
            key = mod.get("key", "")
            if not key:
                continue
            if is_rerun:
                # Check current state
                current_mods = prompts_config.get_modifiers(include_hidden=True)
                existing_mod = next((m for m in current_mods if m.get("key") == key), None)
                default_visible = not (existing_mod.get("_hidden", False) if existing_mod else False)
            else:
                default_visible = key in self.WIZARD_MINIMAL_MODIFIERS
            self._modifier_toggle_vars[key] = tk.BooleanVar(value=default_visible)

    def _on_actions_subtab_change(self, value):
        self._show_actions_subtab(value)

    def _show_actions_subtab(self, tab_name):
        """Render the action toggle list for the selected sub-tab."""
        c = self.colors

        # Initialize tab frames cache if not present
        if not hasattr(self, "_tab_frames"):
            self._tab_frames = {}

        # Hide all tab frames
        for name, frame in self._tab_frames.items():
            frame.pack_forget()

        # If already created, just show it
        if tab_name in self._tab_frames:
            self._tab_frames[tab_name].pack(fill="both", expand=True)
            return

        # Otherwise, create the frame and populate it
        tab_frame = (
            ctk.CTkFrame(self._actions_content_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(self._actions_content_frame, bg=c.bg)
        )
        self._tab_frames[tab_name] = tab_frame
        tab_frame.pack(fill="both", expand=True)

        if tab_name == "Modifiers":
            self._render_modifier_toggles(tab_frame)
            return

        # Map tab name to tool key and action defaults
        from ..prompts import DEFAULT_AUDIO_ACTIONS, DEFAULT_SNIP_ACTIONS, DEFAULT_TEXT_EDIT_ACTIONS

        tool_map = {
            "Text Edit": ("text_edit_tool", DEFAULT_TEXT_EDIT_ACTIONS),
            "Snip Tool": ("snip_tool", DEFAULT_SNIP_ACTIONS),
            "Audio Tool": ("audio_tool", DEFAULT_AUDIO_ACTIONS),
        }

        tool_key, defaults = tool_map[tab_name]
        toggles = self._action_toggle_vars.get(tool_key, {})

        # Select All / Deselect All buttons
        btn_row = ctk.CTkFrame(tab_frame, fg_color="transparent") if self.use_ctk else tk.Frame(tab_frame, bg=c.bg)
        btn_row.pack(fill="x", pady=(0, 5))

        def select_all():
            for var in toggles.values():
                var.set(True)

        def deselect_all():
            for var in toggles.values():
                var.set(False)

        def select_minimal():
            minimal_set = set()
            if tool_key == "text_edit_tool":
                minimal_set = self.WIZARD_MINIMAL_TEXT_EDIT
            elif tool_key == "snip_tool":
                minimal_set = self.WIZARD_MINIMAL_SNIP
            elif tool_key == "audio_tool":
                minimal_set = self.WIZARD_MINIMAL_AUDIO

            for k, var in toggles.items():
                var.set(k in minimal_set)

        create_emoji_button(btn_row, "All On", "✅", c, "success", 80, 28, select_all).pack(side="left", padx=3)
        create_emoji_button(btn_row, "All Off", "❌", c, "danger", 80, 28, deselect_all).pack(side="left", padx=3)
        create_emoji_button(btn_row, "Minimal", "✨", c, "secondary", 80, 28, select_minimal).pack(side="left", padx=3)

        # Lightweight scrollable list using Canvas + tk.Checkbuttons (much faster than CTkScrollableFrame + CTk widgets)
        canvas_frame = tk.Frame(tab_frame, bg=c.bg)
        canvas_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(canvas_frame, bg=c.bg, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=c.bg)

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Mousewheel binding
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<MouseWheel>", _on_mousewheel)
        inner.bind("<MouseWheel>", _on_mousewheel)

        for name in defaults:
            if name.startswith("_"):
                continue
            if name not in toggles:
                continue

            action = defaults[name]
            icon = action.get("icon", "")
            task = action.get("task", "")

            row = tk.Frame(inner, bg=c.surface0, padx=6, pady=4)
            row.pack(fill="x", pady=1, padx=2)
            row.bind("<MouseWheel>", _on_mousewheel)

            initial_select_color = c.accent_green if toggles[name].get() else c.surface0
            cb = tk.Checkbutton(
                row,
                variable=toggles[name],
                bg=c.surface0,
                activebackground=c.surface0,
                selectcolor=initial_select_color,
                relief="flat",
                bd=0,
            )
            cb.pack(side="left", padx=(4, 6))
            cb.bind("<MouseWheel>", _on_mousewheel)

            def on_var_change(*args, n=name, cb_w=cb):
                try:
                    if cb_w.winfo_exists():
                        cb_w.configure(selectcolor=c.accent_green if toggles[n].get() else c.surface0)
                except Exception:
                    pass

            toggles[name].trace_add("write", on_var_change)

            # Icon
            if HAVE_EMOJI and get_emoji_renderer and icon:
                renderer = get_emoji_renderer()
                img = renderer.get_emoji_image(icon, size=16)
                if img:
                    icon_lbl = tk.Label(row, image=img, bg=c.surface0)
                    icon_lbl.image = img  # Keep reference to prevent GC
                    icon_lbl.pack(side="left", padx=(0, 4))
                    icon_lbl.bind("<Button-1>", lambda e, v=toggles[name]: v.set(not v.get()))
                    icon_lbl.bind("<MouseWheel>", _on_mousewheel)
                else:
                    icon_lbl = tk.Label(row, text=icon, font=get_tk_font(10), bg=c.surface0, fg=c.fg)
                    icon_lbl.pack(side="left", padx=(0, 4))
                    icon_lbl.bind("<Button-1>", lambda e, v=toggles[name]: v.set(not v.get()))
                    icon_lbl.bind("<MouseWheel>", _on_mousewheel)
            elif icon:
                icon_lbl = tk.Label(row, text=icon, font=get_tk_font(10), bg=c.surface0, fg=c.fg)
                icon_lbl.pack(side="left", padx=(0, 4))
                icon_lbl.bind("<Button-1>", lambda e, v=toggles[name]: v.set(not v.get()))
                icon_lbl.bind("<MouseWheel>", _on_mousewheel)

            # Name label
            name_lbl = tk.Label(
                row,
                text=name,
                font=get_tk_font(10, "bold"),
                bg=c.surface0,
                fg=c.fg,
                anchor="w",
            )
            name_lbl.pack(side="left", padx=(0, 8))
            name_lbl.bind("<Button-1>", lambda e, v=toggles[name]: v.set(not v.get()))
            name_lbl.bind("<MouseWheel>", _on_mousewheel)

            if task:
                truncated = task[:80] + "..." if len(task) > 80 else task
                desc_lbl = tk.Label(
                    row,
                    text=truncated,
                    font=get_tk_font(8),
                    bg=c.surface0,
                    fg=c.blockquote,
                    anchor="w",
                )
                desc_lbl.pack(side="left", fill="x", expand=True, padx=(0, 6))
                desc_lbl.bind("<Button-1>", lambda e, v=toggles[name]: v.set(not v.get()))
                desc_lbl.bind("<MouseWheel>", _on_mousewheel)

    def _render_modifier_toggles(self, parent):
        """Render modifier toggle list."""
        c = self.colors
        from ..prompts import DEFAULT_GLOBAL_SETTINGS

        # Select All / Deselect All
        btn_row = ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=c.bg)
        btn_row.pack(fill="x", pady=(0, 5))

        def select_all():
            for var in self._modifier_toggle_vars.values():
                var.set(True)

        def deselect_all():
            for var in self._modifier_toggle_vars.values():
                var.set(False)

        def select_minimal():
            for k, var in self._modifier_toggle_vars.items():
                var.set(k in self.WIZARD_MINIMAL_MODIFIERS)

        create_emoji_button(btn_row, "All On", "✅", c, "success", 80, 28, select_all).pack(side="left", padx=3)
        create_emoji_button(btn_row, "All Off", "❌", c, "danger", 80, 28, deselect_all).pack(side="left", padx=3)
        create_emoji_button(btn_row, "Minimal", "✨", c, "secondary", 80, 28, select_minimal).pack(side="left", padx=3)

        # Lightweight scrollable list using Canvas + tk.Checkbuttons
        canvas_frame = tk.Frame(parent, bg=c.bg)
        canvas_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(canvas_frame, bg=c.bg, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=c.bg)

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<MouseWheel>", _on_mousewheel)
        inner.bind("<MouseWheel>", _on_mousewheel)

        default_modifiers = DEFAULT_GLOBAL_SETTINGS.get("modifiers", [])
        for mod in default_modifiers:
            key = mod.get("key", "")
            if not key or key not in self._modifier_toggle_vars:
                continue

            icon = mod.get("icon", "")
            label = mod.get("label", key)
            tooltip = mod.get("tooltip", "")

            row = tk.Frame(inner, bg=c.surface0, padx=6, pady=4)
            row.pack(fill="x", pady=1, padx=2)
            row.bind("<MouseWheel>", _on_mousewheel)

            initial_select_color = c.accent_green if self._modifier_toggle_vars[key].get() else c.surface0
            cb = tk.Checkbutton(
                row,
                variable=self._modifier_toggle_vars[key],
                bg=c.surface0,
                activebackground=c.surface0,
                selectcolor=initial_select_color,
                relief="flat",
                bd=0,
            )
            cb.pack(side="left", padx=(4, 6))
            cb.bind("<MouseWheel>", _on_mousewheel)

            def on_mod_change(*args, k=key, cb_w=cb):
                try:
                    if cb_w.winfo_exists():
                        cb_w.configure(
                            selectcolor=c.accent_green if self._modifier_toggle_vars[k].get() else c.surface0
                        )
                except Exception:
                    pass

            self._modifier_toggle_vars[key].trace_add("write", on_mod_change)

            # Icon
            if HAVE_EMOJI and get_emoji_renderer and icon:
                renderer = get_emoji_renderer()
                img = renderer.get_emoji_image(icon, size=16)
                if img:
                    icon_lbl = tk.Label(row, image=img, bg=c.surface0)
                    icon_lbl.image = img  # Keep reference to prevent GC
                    icon_lbl.pack(side="left", padx=(0, 4))
                    icon_lbl.bind("<Button-1>", lambda e, v=self._modifier_toggle_vars[key]: v.set(not v.get()))
                    icon_lbl.bind("<MouseWheel>", _on_mousewheel)
                else:
                    icon_lbl = tk.Label(row, text=icon, font=get_tk_font(10), bg=c.surface0, fg=c.fg)
                    icon_lbl.pack(side="left", padx=(0, 4))
                    icon_lbl.bind("<Button-1>", lambda e, v=self._modifier_toggle_vars[key]: v.set(not v.get()))
                    icon_lbl.bind("<MouseWheel>", _on_mousewheel)
            elif icon:
                icon_lbl = tk.Label(row, text=icon, font=get_tk_font(10), bg=c.surface0, fg=c.fg)
                icon_lbl.pack(side="left", padx=(0, 4))
                icon_lbl.bind("<Button-1>", lambda e, v=self._modifier_toggle_vars[key]: v.set(not v.get()))
                icon_lbl.bind("<MouseWheel>", _on_mousewheel)

            name_lbl = tk.Label(
                row,
                text=label,
                font=get_tk_font(10, "bold"),
                bg=c.surface0,
                fg=c.fg,
                anchor="w",
            )
            name_lbl.pack(side="left", padx=(0, 8))
            name_lbl.bind("<Button-1>", lambda e, v=self._modifier_toggle_vars[key]: v.set(not v.get()))
            name_lbl.bind("<MouseWheel>", _on_mousewheel)

            if tooltip:
                desc_lbl = tk.Label(
                    row,
                    text=tooltip,
                    font=get_tk_font(8),
                    bg=c.surface0,
                    fg=c.blockquote,
                    anchor="w",
                )
                desc_lbl.pack(side="left", fill="x", expand=True, padx=(0, 6))
                desc_lbl.bind("<Button-1>", lambda e, v=self._modifier_toggle_vars[key]: v.set(not v.get()))
                desc_lbl.bind("<MouseWheel>", _on_mousewheel)

    def _save_action_visibility(self):
        """Apply action/modifier visibility selections to prompts.json."""
        from ..prompts import PromptsConfig

        prompts_config = PromptsConfig.get_instance()
        config = prompts_config._config  # Direct access for bulk mutation

        # Apply action toggles
        for tool_key, toggles in self._action_toggle_vars.items():
            tool_data = config.setdefault(tool_key, {})
            for action_name, var in toggles.items():
                action = tool_data.get(action_name)
                if isinstance(action, dict):
                    if var.get():
                        # Visible — remove _hidden if present
                        action.pop("_hidden", None)
                    else:
                        # Hidden
                        action["_hidden"] = True

        # Apply modifier toggles
        modifiers = config.get("_global_settings", {}).get("modifiers", [])
        for mod in modifiers:
            key = mod.get("key", "")
            if key in self._modifier_toggle_vars:
                if self._modifier_toggle_vars[key].get():
                    mod.pop("_hidden", None)
                else:
                    mod["_hidden"] = True

        # Save to file
        prompts_config._save()
        print("[Onboarding] Action/modifier visibility preferences saved")

    def _create_complete_page(self, parent):
        c = self.colors

        if self.use_ctk:
            if HAVE_EMOJI and prepare_emoji_content:
                title_kwargs = prepare_emoji_content("🎉 All Set!", size=30)
                title = ctk.CTkLabel(parent, font=get_ctk_font(22, "bold"), **title_kwargs, **get_ctk_label_colors(c))
            else:
                title = ctk.CTkLabel(
                    parent, text="All Set! 🎉", font=get_ctk_font(22, "bold"), **get_ctk_label_colors(c)
                )
            title.pack(pady=(20, 10))

            desc = ctk.CTkLabel(
                parent,
                text="AIPromptBridge is fully configured and ready to use.\nBelow is a summary of your configuration:",
                font=get_ctk_font(13),
                justify="center",
                **get_ctk_label_colors(c),
            )
            desc.pack(pady=(0, 20))

            summary_box = ctk.CTkFrame(parent, fg_color=c.surface0, corner_radius=8)
            summary_box.pack(fill="x", padx=40, pady=10, ipady=15)
        else:
            title = tk.Label(parent, text="All Set! 🎉", font=get_tk_font(18, "bold"), bg=c.bg, fg=c.fg)
            title.pack(pady=(20, 10))

            desc = tk.Label(
                parent,
                text="AIPromptBridge is fully configured and ready to use.\nBelow is a summary of your configuration:",
                font=get_tk_font(10),
                justify="center",
                bg=c.bg,
                fg=c.fg,
            )
            desc.pack(pady=(0, 20))

            summary_box = tk.Frame(parent, bg=c.surface0, bd=1, relief="solid")
            summary_box.pack(fill="x", padx=40, pady=10, ipady=15)

        # Config Summary
        pools_with_keys = []
        for pool_id in ["google", "anthropic", "openai", "openrouter", "xai", "mistral", "cohere", "custom"]:
            if self._key_store.get_pool(pool_id):
                pools_with_keys.append(self._key_store.get_pool_display_name(pool_id))

        keys_summary = ", ".join(pools_with_keys) if pools_with_keys else "None (Add later in Settings)"

        defs = get_provider_definitions()
        provider_name = (
            defs[self._provider_var.get()].name if self._provider_var.get() in defs else self._provider_var.get()
        )
        model_name = self._model_var.get()

        # (emoji, label_text, value) — emoji in separate column for vertical alignment
        summary_details = [
            ("🔑", "API Keys Configured:", keys_summary),
            ("📡", "Default AI Provider:", provider_name),
            ("🤖", "Default Model:", model_name),
        ]

        # Show Base URL in summary only for custom provider when configured
        base_url = self._base_url_var.get().strip() if hasattr(self, "_base_url_var") else ""
        if self._provider_var.get() == "custom" and base_url:
            summary_details.append(("🌐", "Base URL:", base_url))

        # Show enabled tools in summary
        enabled_tools = []
        if hasattr(self, "_tool_vars"):
            tool_names = {
                "text_edit_tool_enabled": "TextEdit",
                "screen_snip_enabled": "ScreenSnip",
                "audio_tool_enabled": "AudioTool",
                "tts_enabled": "TTS",
            }
            for key, var in self._tool_vars.items():
                if var.get():
                    enabled_tools.append(tool_names.get(key, key))

        tools_text = ", ".join(enabled_tools) if enabled_tools else "None"
        summary_details.append(("🔧", "Enabled Tools:", tools_text))

        summary_box.columnconfigure(0, weight=0, minsize=35)  # emoji column
        summary_box.columnconfigure(1, weight=1)  # label column
        summary_box.columnconfigure(2, weight=1)  # value column

        for idx, (emoji, label, val) in enumerate(summary_details):
            if self.use_ctk:
                # Emoji column — fixed width, centered
                if HAVE_EMOJI and prepare_emoji_content:
                    emoji_kwargs = prepare_emoji_content(emoji, size=20)
                    lbl_emoji = ctk.CTkLabel(
                        summary_box,
                        font=get_ctk_font(16),
                        anchor="center",
                        **emoji_kwargs,
                        **get_ctk_label_colors(c, muted=True),
                    )
                else:
                    lbl_emoji = ctk.CTkLabel(
                        summary_box,
                        text=emoji,
                        font=get_ctk_font(16),
                        anchor="center",
                        **get_ctk_label_colors(c, muted=True),
                    )
                lbl_emoji.grid(row=idx, column=0, padx=(15, 2), pady=4, sticky="e")

                # Label column
                lbl_l = ctk.CTkLabel(
                    summary_box,
                    text=label,
                    font=get_ctk_font(12, "bold"),
                    anchor="e",
                    **get_ctk_label_colors(c, muted=True),
                )
                lbl_l.grid(row=idx, column=1, padx=(2, 10), pady=4, sticky="e")

                # Value column
                lbl_r = ctk.CTkLabel(
                    summary_box, text=val, font=get_ctk_font(12, "bold"), anchor="w", **get_ctk_label_colors(c)
                )
                lbl_r.grid(row=idx, column=2, padx=(10, 20), pady=4, sticky="w")
            else:
                lbl_emoji = tk.Label(
                    summary_box,
                    text=emoji,
                    font=get_tk_font(12),
                    anchor="center",
                    bg=c.surface0,
                    fg=c.blockquote,
                    width=3,
                )
                lbl_emoji.grid(row=idx, column=0, padx=(15, 2), pady=4, sticky="e")

                lbl_l = tk.Label(
                    summary_box, text=label, font=get_tk_font(9, "bold"), anchor="e", bg=c.surface0, fg=c.blockquote
                )
                lbl_l.grid(row=idx, column=1, padx=(2, 10), pady=4, sticky="e")

                lbl_r = tk.Label(summary_box, text=val, font=get_tk_font(9, "bold"), anchor="w", bg=c.surface0, fg=c.fg)
                lbl_r.grid(row=idx, column=2, padx=(10, 20), pady=4, sticky="w")

        next_text = (
            "AIPromptBridge will stay active in the system tray.\nDouble-click the tray icon to hide/show the console."
        )
        if self.use_ctk:
            ctk.CTkLabel(
                parent, text=next_text, font=get_ctk_font(11), justify="center", **get_ctk_label_colors(c, muted=True)
            ).pack(pady=(15, 5))
        else:
            tk.Label(parent, text=next_text, font=get_tk_font(9), justify="center", bg=c.bg, fg=c.blockquote).pack(
                pady=(15, 5)
            )

        # Tips & Next Steps
        tips_title_text = "Tips & Next Steps"
        if self.use_ctk:
            ctk.CTkLabel(parent, text=tips_title_text, font=get_ctk_font(12, "bold"), **get_ctk_label_colors(c)).pack(
                pady=(10, 5)
            )
        else:
            tk.Label(parent, text=tips_title_text, font=get_tk_font(10, "bold"), bg=c.bg, fg=c.fg).pack(pady=(10, 5))

        tips = [
            ("🔑", "Get a free API key from Google AI Studio (aistudio.google.com) to start quickly"),
            ("✏️", "Customize AI prompts and actions in the Prompt Editor (tray menu)"),
            ("🎨", "Switch between 6 themes and dark/light modes in Settings"),
            ("📋", "Use Connection Profiles to switch providers and models on the fly"),
        ]
        if self.use_ctk:
            tips_frame = ctk.CTkFrame(parent, fg_color="transparent")
            tips_frame.pack(fill="x", padx=40)
            for emoji, tip_text in tips:
                tip_row = ctk.CTkFrame(tips_frame, fg_color="transparent")
                tip_row.pack(fill="x", pady=1)
                if HAVE_EMOJI and prepare_emoji_content:
                    icon_kwargs = prepare_emoji_content(emoji, size=16)
                    ctk.CTkLabel(
                        tip_row, font=get_ctk_font(16), width=28, **icon_kwargs, **get_ctk_label_colors(c, muted=True)
                    ).pack(side="left", padx=(0, 6))
                else:
                    ctk.CTkLabel(
                        tip_row, text=emoji, font=get_ctk_font(16), width=28, **get_ctk_label_colors(c, muted=True)
                    ).pack(side="left", padx=(0, 6))
                ctk.CTkLabel(
                    tip_row, text=tip_text, font=get_ctk_font(11), anchor="w", **get_ctk_label_colors(c, muted=True)
                ).pack(side="left", fill="x", expand=True)
        else:
            tips_frame = tk.Frame(parent, bg=c.bg)
            tips_frame.pack(fill="x", padx=40)
            for emoji, tip_text in tips:
                tip_row = tk.Frame(tips_frame, bg=c.bg)
                tip_row.pack(fill="x", pady=1)
                tk.Label(tip_row, text=emoji, font=get_tk_font(12), bg=c.bg, fg=c.fg, width=3).pack(
                    side="left", padx=(0, 4)
                )
                tk.Label(tip_row, text=tip_text, font=get_tk_font(9), anchor="w", bg=c.bg, fg=c.blockquote).pack(
                    side="left", fill="x", expand=True
                )


class AttachedOnboardingWindow:
    """
    Onboarding wizard window as Toplevel attached to GUICoordinator's root.
    Used for centralized GUI threading.
    """

    def __init__(self, parent_root, on_close=None):
        self.parent_root = parent_root
        wizard = OnboardingWizard(master=parent_root, on_close=on_close)
        wizard.show()


def create_attached_onboarding_window(parent_root, on_close=None):
    """Create an onboarding wizard (called on GUI thread)."""
    AttachedOnboardingWindow(parent_root, on_close)


def show_onboarding_blocking():
    """
    Show onboarding window and block until it is closed.
    Can be run from any thread, and will dispatch to GUICoordinator.
    """
    from ..core import GUICoordinator

    coordinator = GUICoordinator.get_instance()

    done_event = threading.Event()

    def on_close():
        done_event.set()

    coordinator.request_onboarding_window(on_close=on_close)
    done_event.wait()
    return True
