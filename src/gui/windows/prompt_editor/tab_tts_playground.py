#!/usr/bin/env python3
"""
TTS Playground Mixin for the Prompt Editor.

Provides TTS-specific playground controls for testing text-to-speech
with direct speech and AI director modes.
"""

import os
import threading
import time
import tkinter as tk
from tkinter import filedialog

from ....audio.tts_constants import TTS_MODELS, get_voice_details, get_voice_list
from ...custom_widgets import create_emoji_button, create_section_header
from ...platform import HAVE_CTK, ctk
from ...themes import (
    get_ctk_button_colors,
    get_ctk_combobox_colors,
    get_ctk_font,
    get_ctk_label_colors,
    get_ctk_textbox_colors,
    get_tk_font,
)


class TTSPlaygroundMixin:
    """Mixin providing TTS playground controls for PromptEditorWindow."""

    def _create_tts_playground_controls(self, parent):
        """Create TTS-specific playground controls."""
        # --- Mode Toggle: Direct Speech / AI Director ---
        create_section_header(parent, "TTS Mode", self.colors, "🔊")

        self.tts_pg_mode_var = tk.StringVar(master=self.root, value="direct")
        tts_mode_frame = (
            ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        )
        tts_mode_frame.pack(fill="x", pady=(0, 10))

        if self.use_ctk:
            ctk.CTkRadioButton(
                tts_mode_frame,
                text="Direct Speech",
                variable=self.tts_pg_mode_var,
                value="direct",
                font=get_ctk_font(13),
                text_color=self.colors.fg,
                fg_color=self.colors.accent,
                command=self._on_tts_mode_toggle,
            ).pack(side="left", padx=(0, 15))
            ctk.CTkRadioButton(
                tts_mode_frame,
                text="AI Director",
                variable=self.tts_pg_mode_var,
                value="director",
                font=get_ctk_font(13),
                text_color=self.colors.fg,
                fg_color=self.colors.accent,
                command=self._on_tts_mode_toggle,
            ).pack(side="left")
        else:
            tk.Radiobutton(
                tts_mode_frame,
                text="Direct Speech",
                variable=self.tts_pg_mode_var,
                value="direct",
                font=get_tk_font(10),
                bg=self.colors.bg,
                fg=self.colors.fg,
                command=self._on_tts_mode_toggle,
            ).pack(side="left", padx=(0, 15))
            tk.Radiobutton(
                tts_mode_frame,
                text="AI Director",
                variable=self.tts_pg_mode_var,
                value="director",
                font=get_tk_font(10),
                bg=self.colors.bg,
                fg=self.colors.fg,
                command=self._on_tts_mode_toggle,
            ).pack(side="left")

        # --- Model Selection ---
        model_frame = (
            ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        )
        model_frame.pack(fill="x", pady=(0, 8))

        if self.use_ctk:
            ctk.CTkLabel(
                model_frame,
                text="TTS Model:",
                font=get_ctk_font(12),
                width=80,
                anchor="w",
                **get_ctk_label_colors(self.colors),
            ).pack(side="left")
            self.tts_pg_model_var = tk.StringVar(master=self.root, value=TTS_MODELS[0])
            ctk.CTkComboBox(
                model_frame,
                variable=self.tts_pg_model_var,
                values=TTS_MODELS,
                width=280,
                height=32,
                state="readonly",
                font=get_ctk_font(12),
                **get_ctk_combobox_colors(self.colors),
            ).pack(side="left", padx=(8, 0), fill="x", expand=True)
        else:
            tk.Label(model_frame, text="TTS Model:", font=get_tk_font(10), bg=self.colors.bg, fg=self.colors.fg).pack(
                side="left"
            )
            self.tts_pg_model_var = tk.StringVar(value=TTS_MODELS[0])
            from tkinter import ttk

            ttk.Combobox(
                model_frame, textvariable=self.tts_pg_model_var, values=TTS_MODELS, state="readonly", width=35
            ).pack(side="left", padx=(8, 0), fill="x", expand=True)

        # --- Voice Selection ---
        voice_frame = (
            ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        )
        voice_frame.pack(fill="x", pady=(0, 10))

        voice_list = get_voice_list()

        if self.use_ctk:
            ctk.CTkLabel(
                voice_frame,
                text="Voice:",
                font=get_ctk_font(12),
                width=80,
                anchor="w",
                **get_ctk_label_colors(self.colors),
            ).pack(side="left")
            self.tts_pg_voice_var = tk.StringVar(master=self.root, value=voice_list[0] if voice_list else "")
            ctk.CTkComboBox(
                voice_frame,
                variable=self.tts_pg_voice_var,
                values=voice_list,
                width=280,
                height=32,
                state="readonly",
                font=get_ctk_font(12),
                **get_ctk_combobox_colors(self.colors),
            ).pack(side="left", padx=(8, 0), fill="x", expand=True)
        else:
            tk.Label(voice_frame, text="Voice:", font=get_tk_font(10), bg=self.colors.bg, fg=self.colors.fg).pack(
                side="left"
            )
            self.tts_pg_voice_var = tk.StringVar(value=voice_list[0] if voice_list else "")
            from tkinter import ttk

            ttk.Combobox(
                voice_frame, textvariable=self.tts_pg_voice_var, values=voice_list, state="readonly", width=35
            ).pack(side="left", padx=(8, 0), fill="x", expand=True)

        # --- TTS Input Text ---
        create_section_header(parent, "Input Text", self.colors, "📝")

        if self.use_ctk:
            self.tts_pg_input_text = ctk.CTkTextbox(
                parent, height=120, font=get_ctk_font(12), **get_ctk_textbox_colors(self.colors)
            )
        else:
            self.tts_pg_input_text = tk.Text(
                parent, height=5, font=get_tk_font(10), bg=self.colors.input_bg, fg=self.colors.fg, wrap="word"
            )
        self.tts_pg_input_text.pack(fill="x", pady=(0, 10))
        self.tts_pg_input_text.bind("<KeyRelease>", lambda e: self._update_tts_playground_preview())

        # --- Director Section (shown only in AI Director mode) ---
        self.tts_pg_director_frame = (
            ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        )
        # Initially hidden (shown in director mode)

        create_section_header(self.tts_pg_director_frame, "AI Director", self.colors, "🎬")

        # Generate Style button
        dir_btn_frame = (
            ctk.CTkFrame(self.tts_pg_director_frame, fg_color="transparent")
            if self.use_ctk
            else tk.Frame(self.tts_pg_director_frame, bg=self.colors.bg)
        )
        dir_btn_frame.pack(fill="x", pady=(0, 8))

        self.tts_pg_director_btn = create_emoji_button(
            dir_btn_frame, "Generate Style", "🎬", self.colors, "primary", 160, 36, self._run_tts_director_playground
        )
        self.tts_pg_director_btn.pack(side="left")

        # Director status
        if self.use_ctk:
            self.tts_pg_director_status = ctk.CTkLabel(
                dir_btn_frame, text="", font=get_ctk_font(11), text_color=self.colors.blockquote
            )
        else:
            self.tts_pg_director_status = tk.Label(
                dir_btn_frame, text="", font=get_tk_font(9), bg=self.colors.bg, fg=self.colors.blockquote
            )
        self.tts_pg_director_status.pack(side="left", padx=(10, 0))

        # Director output textbox
        if self.use_ctk:
            self.tts_pg_director_output = ctk.CTkTextbox(
                self.tts_pg_director_frame, height=100, font=get_ctk_font(11), **get_ctk_textbox_colors(self.colors)
            )
        else:
            self.tts_pg_director_output = tk.Text(
                self.tts_pg_director_frame,
                height=5,
                font=get_tk_font(10),
                bg=self.colors.input_bg,
                fg=self.colors.fg,
                wrap="word",
            )
        self.tts_pg_director_output.pack(fill="x", pady=(0, 10))

        # --- Generate Audio Button ---
        gen_frame = (
            ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        )
        gen_frame.pack(fill="x", pady=(0, 8))

        self.tts_pg_generate_btn = create_emoji_button(
            gen_frame, "Generate Audio", "🔊", self.colors, "success", 170, 42, self._run_tts_generation_playground
        )
        self.tts_pg_generate_btn.pack(side="left")

        if self.use_ctk:
            self.tts_pg_gen_status = ctk.CTkLabel(
                gen_frame, text="", font=get_ctk_font(11), text_color=self.colors.blockquote
            )
        else:
            self.tts_pg_gen_status = tk.Label(
                gen_frame, text="", font=get_tk_font(9), bg=self.colors.bg, fg=self.colors.blockquote
            )
        self.tts_pg_gen_status.pack(side="left", padx=(10, 0))

        # --- Audio Playback Controls ---
        create_section_header(parent, "Audio Preview", self.colors, "🎧")

        playback_frame = (
            ctk.CTkFrame(parent, fg_color="transparent") if self.use_ctk else tk.Frame(parent, bg=self.colors.bg)
        )
        playback_frame.pack(fill="x", pady=(0, 8))

        self.tts_pg_play_btn = create_emoji_button(
            playback_frame, "▶", "", self.colors, "success", 50, 34, self._toggle_tts_playback
        )
        self.tts_pg_play_btn.pack(side="left", padx=(0, 8))

        if self.use_ctk:
            self.tts_pg_position_label = ctk.CTkLabel(
                playback_frame, text="00:00 / 00:00", font=get_ctk_font(12), text_color=self.colors.blockquote
            )
        else:
            self.tts_pg_position_label = tk.Label(
                playback_frame,
                text="00:00 / 00:00",
                font=get_tk_font(10),
                bg=self.colors.bg,
                fg=self.colors.blockquote,
            )
        self.tts_pg_position_label.pack(side="left", padx=(0, 15))

        # Save button
        self.tts_pg_save_btn = create_emoji_button(
            playback_frame, "Save WAV", "💾", self.colors, "secondary", 110, 34, self._save_tts_audio
        )
        self.tts_pg_save_btn.pack(side="left")

    def _on_tts_mode_toggle(self):
        """Handle direct/director mode toggle for TTS."""
        mode = self.tts_pg_mode_var.get()
        if mode == "director":
            self.tts_pg_director_frame.pack(fill="x", pady=(0, 10))
        else:
            self.tts_pg_director_frame.pack_forget()
        self._update_tts_playground_preview()

    def _update_tts_playground_preview(self):
        """Update the right pane preview for TTS mode."""
        if not hasattr(self, "tts_pg_input_text"):
            return

        # Get input text
        if self.use_ctk:
            input_text = self.tts_pg_input_text.get("0.0", "end").strip()
        else:
            input_text = self.tts_pg_input_text.get("1.0", "end").strip()

        tts_mode = self.tts_pg_mode_var.get()

        if tts_mode == "direct":
            # Direct speech: no system prompt, user message = raw input text
            system_text = ""
            user_text = input_text if input_text else "(Enter text above)"
            meta_text = "🔊 Mode: Direct Speech | No AI processing"
        else:
            # AI Director mode: show director prompt in preview
            system_text = self._get_current_setting(
                "tts_tool", "director_system_prompt", "(Could not load director prompts)"
            )
            task_template = self._get_current_setting("tts_tool", "director_task_template", "")
            user_text = task_template.replace("{text}", input_text) if input_text else task_template

            total_chars = len(system_text) + len(user_text)
            token_estimate = total_chars // 4
            meta_text = f"🎬 Mode: AI Director | Tokens: ~{token_estimate}"

        self._set_preview_text(self.playground_system_preview, system_text, "system")
        self._set_preview_text(self.playground_user_preview, user_text, "user")

        if self.use_ctk:
            self.playground_meta_label.configure(text=meta_text)
        else:
            self.playground_meta_label.configure(text=meta_text)

    def _get_tts_voice_name(self):
        """Extract voice name from the voice dropdown value."""
        voice_display = self.tts_pg_voice_var.get()
        if " — " in voice_display:
            return voice_display.split(" — ")[0]
        return voice_display

    def _run_tts_director_playground(self):
        """Generate style instructions using AI Director in playground."""
        if self.tts_pg_is_directing:
            return

        if self.use_ctk:
            input_text = self.tts_pg_input_text.get("0.0", "end").strip()
        else:
            input_text = self.tts_pg_input_text.get("1.0", "end").strip()

        if not input_text:
            self._set_tts_status(self.tts_pg_director_status, "No input text", self.colors.accent_red)
            return

        self.tts_pg_is_directing = True
        self.tts_pg_director_btn.configure(state="disabled")
        self._set_tts_status(self.tts_pg_director_status, "⏳ Generating style...", self.colors.fg)

        # Get prompts from settings tab if available (live values)
        system_prompt = self._get_current_setting("tts_tool", "director_system_prompt", "")
        task_template = self._get_current_setting("tts_tool", "director_task_template", "")

        def _target():
            try:
                from .... import web_server as _ws
                from ....key_store import KeyStore
                from ....profile_resolver import resolve_profile, resolve_profile_by_name
                from ....request_pipeline import RequestContext, RequestOrigin, RequestPipeline

                key_store = KeyStore.get_instance()
                key_managers = key_store.build_key_managers()

                task = task_template.replace("{text}", input_text)

                messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": task}]

                # Respect playground's profile/manual connection toggle for director generation
                if self.playground_manual_mode_var.get():
                    resolved = resolve_profile(None, _ws.CONFIG, _ws.AI_PARAMS, key_managers)
                    provider = self.playground_provider_var.get()
                    model = self.playground_model_var.get()
                    resolved.provider = provider
                    resolved.model = model
                    resolved.config["default_provider"] = provider
                    resolved.config[f"{provider}_model"] = model
                else:
                    profile_name = self.playground_profile_var.get()
                    if profile_name and profile_name != "(None)":
                        resolved = resolve_profile_by_name(profile_name, _ws.CONFIG, _ws.AI_PARAMS, key_managers)
                    else:
                        resolved = resolve_profile(None, _ws.CONFIG, _ws.AI_PARAMS, key_managers)
                    provider = resolved.provider
                    model = resolved.model

                ctx = RequestContext(
                    origin=RequestOrigin.TTS_TOOL,
                    provider=provider,
                    model=model,
                    streaming=False,
                    thinking_enabled=resolved.config.get("thinking_enabled", False),
                )
                ctx = RequestPipeline.execute_simple(
                    ctx, messages, resolved.config, resolved.ai_params, resolved.key_managers
                )

                def _update():
                    if self._destroyed:
                        return
                    self.tts_pg_is_directing = False
                    self.tts_pg_director_btn.configure(state="normal")
                    if ctx.error:
                        self._set_tts_status(self.tts_pg_director_status, f"❌ {ctx.error}", self.colors.accent_red)
                    else:
                        # Populate director output
                        if self.use_ctk:
                            self.tts_pg_director_output.delete("0.0", "end")
                            self.tts_pg_director_output.insert("0.0", ctx.response_text)
                        else:
                            self.tts_pg_director_output.delete("1.0", "end")
                            self.tts_pg_director_output.insert("1.0", ctx.response_text)
                        self._set_tts_status(
                            self.tts_pg_director_status,
                            f"✅ Style generated ({ctx.total_tokens} tokens)",
                            self.colors.green,
                        )

                self.queue.put(_update)

            except Exception as e:
                error_msg = str(e)

                def _err(err=error_msg):
                    if not self._destroyed:
                        self.tts_pg_is_directing = False
                        self.tts_pg_director_btn.configure(state="normal")
                        self._set_tts_status(self.tts_pg_director_status, f"❌ {err}", self.colors.accent_red)

                self.queue.put(_err)

        threading.Thread(target=_target, daemon=True).start()

    def _run_tts_generation_playground(self):
        """Generate TTS audio in playground."""
        if self.tts_pg_is_generating:
            return

        if self.use_ctk:
            input_text = self.tts_pg_input_text.get("0.0", "end").strip()
        else:
            input_text = self.tts_pg_input_text.get("1.0", "end").strip()

        if not input_text:
            self._set_tts_status(self.tts_pg_gen_status, "No input text", self.colors.accent_red)
            return

        tts_mode = self.tts_pg_mode_var.get()

        # Build prompt
        if tts_mode == "director":
            # Get director output as style instructions
            if self.use_ctk:
                style_text = self.tts_pg_director_output.get("0.0", "end").strip()
            else:
                style_text = self.tts_pg_director_output.get("1.0", "end").strip()

            if not style_text:
                self._set_tts_status(self.tts_pg_gen_status, "Director style is empty", self.colors.accent_red)
                return

            full_prompt = style_text
            if "#### TRANSCRIPT" not in style_text and input_text not in style_text:
                full_prompt += f"\n\n#### TRANSCRIPT\n{input_text}"
        else:
            full_prompt = input_text

        voice_name = self._get_tts_voice_name()
        model = self.tts_pg_model_var.get()

        self.tts_pg_is_generating = True
        self.tts_pg_generate_btn.configure(state="disabled")
        self._set_tts_status(self.tts_pg_gen_status, "⏳ Generating audio...", self.colors.fg)

        def _target():
            try:
                from .... import web_server as _ws
                from ....audio.wav_utils import get_pcm_duration, pcm_to_wav
                from ....key_manager import KeyManager
                from ....profile_resolver import resolve_profile
                from ....providers import create_provider

                # Resolve profile to get merged config with connection keys
                resolved = resolve_profile(None, _ws.CONFIG, _ws.AI_PARAMS, _ws.KEY_MANAGERS)

                from ....key_store import KeyStore

                key_store = KeyStore.get_instance()
                keys_data = key_store.get_pool_for_provider("google")
                key_strings = [kd["key"] for kd in keys_data if kd.get("key")]
                key_manager = KeyManager(key_strings, "google")

                provider = create_provider("google", key_manager, resolved.config)
                pcm_data, error = provider.generate_tts(
                    text=full_prompt, model=model, voice_name=voice_name, multi_speaker_config=None
                )

                if error:

                    def _err():
                        if not self._destroyed:
                            self.tts_pg_is_generating = False
                            self.tts_pg_generate_btn.configure(state="normal")
                            self._set_tts_status(self.tts_pg_gen_status, f"❌ {error}", self.colors.accent_red)

                    self.queue.put(_err)
                    return

                self.tts_pg_pcm_data = pcm_data
                self.tts_pg_audio_data = pcm_to_wav(pcm_data)
                self.tts_pg_audio_duration = get_pcm_duration(pcm_data)

                def _update():
                    if self._destroyed:
                        return
                    self.tts_pg_is_generating = False
                    self.tts_pg_generate_btn.configure(state="normal")

                    dur_str = self._format_tts_duration(self.tts_pg_audio_duration)
                    self._set_tts_status(
                        self.tts_pg_gen_status,
                        f"✅ Audio generated — {dur_str}",
                        self.colors.green if hasattr(self.colors, "green") else self.colors.fg,
                    )

                    # Update position label
                    if self.use_ctk:
                        self.tts_pg_position_label.configure(text=f"00:00 / {dur_str}")
                    else:
                        self.tts_pg_position_label.configure(text=f"00:00 / {dur_str}")

                self.queue.put(_update)

            except Exception as e:
                import traceback

                traceback.print_exc()
                error_msg = str(e)

                def _err(err=error_msg):
                    if not self._destroyed:
                        self.tts_pg_is_generating = False
                        self.tts_pg_generate_btn.configure(state="normal")
                        self._set_tts_status(self.tts_pg_gen_status, f"❌ {err}", self.colors.accent_red)

                self.queue.put(_err)

        threading.Thread(target=_target, daemon=True).start()

    def _toggle_tts_playback(self):
        """Toggle TTS audio playback."""
        if not self.tts_pg_audio_data:
            self._set_tts_status(self.tts_pg_gen_status, "No audio to play", self.colors.accent_red)
            return

        if self.tts_pg_is_playing:
            self._pause_tts_playback()
        else:
            self._play_tts_audio()

    def _play_tts_audio(self):
        """Start TTS audio playback."""
        if not self.tts_pg_audio_data:
            return

        try:
            from ....audio.recorder import AudioRecorder

            if not self.tts_pg_recorder:
                self.tts_pg_recorder = AudioRecorder()

            position = self.tts_pg_playback_position
            if self.tts_pg_recorder.play(self.tts_pg_audio_data, position):
                self.tts_pg_is_playing = True

                # Update button
                if self.use_ctk:
                    self.tts_pg_play_btn.configure(text="⏸")
                else:
                    self.tts_pg_play_btn.configure(text="⏸")

                self._update_tts_playback_position()
        except Exception as e:
            self._set_tts_status(self.tts_pg_gen_status, f"Playback error: {e}", self.colors.accent_red)

    def _pause_tts_playback(self):
        """Pause TTS audio playback."""
        if not self.tts_pg_recorder:
            return

        self.tts_pg_recorder.pause()
        self.tts_pg_is_playing = False
        self.tts_pg_playback_position = self.tts_pg_recorder.get_playback_position()

        if self.use_ctk:
            self.tts_pg_play_btn.configure(text="▶")
        else:
            self.tts_pg_play_btn.configure(text="▶")

    def _update_tts_playback_position(self):
        """Update TTS playback position display."""
        if not self.tts_pg_is_playing or self._destroyed or not self.tts_pg_recorder:
            return

        if not self.tts_pg_recorder.is_playing():
            # Playback finished
            self.tts_pg_is_playing = False
            self.tts_pg_playback_position = 0.0

            if self.use_ctk:
                self.tts_pg_play_btn.configure(text="▶")
            else:
                self.tts_pg_play_btn.configure(text="▶")

            dur_str = self._format_tts_duration(self.tts_pg_audio_duration)
            if self.use_ctk:
                self.tts_pg_position_label.configure(text=f"00:00 / {dur_str}")
            else:
                self.tts_pg_position_label.configure(text=f"00:00 / {dur_str}")
            return

        position = self.tts_pg_recorder.get_playback_position()
        self.tts_pg_playback_position = position

        pos_str = self._format_tts_duration(position)
        dur_str = self._format_tts_duration(self.tts_pg_audio_duration)

        if self.use_ctk:
            self.tts_pg_position_label.configure(text=f"{pos_str} / {dur_str}")
        else:
            self.tts_pg_position_label.configure(text=f"{pos_str} / {dur_str}")

        # Schedule next update
        try:
            if self.root and self.root.winfo_exists():
                self.root.after(100, self._update_tts_playback_position)
        except Exception:
            pass

    def _save_tts_audio(self):
        """Save TTS audio to a WAV file."""
        if not self.tts_pg_pcm_data:
            self._set_tts_status(self.tts_pg_gen_status, "No audio to save", self.colors.accent_red)
            return

        filepath = filedialog.asksaveasfilename(
            title="Save TTS Audio", defaultextension=".wav", filetypes=[("WAV Audio", "*.wav")], parent=self.root
        )
        if not filepath:
            return

        try:
            from ....audio.wav_utils import save_wav

            error = save_wav(filepath, self.tts_pg_pcm_data)
            if error:
                self._set_tts_status(self.tts_pg_gen_status, f"❌ Save failed: {error}", self.colors.accent_red)
            else:
                filename = os.path.basename(filepath)
                self._set_tts_status(
                    self.tts_pg_gen_status,
                    f"✅ Saved: {filename}",
                    self.colors.green if hasattr(self.colors, "green") else self.colors.fg,
                )
        except Exception as e:
            self._set_tts_status(self.tts_pg_gen_status, f"❌ {e}", self.colors.accent_red)

    def _set_tts_status(self, label, text, color=None):
        """Set TTS status label text and color."""
        try:
            target_color = color or self.colors.blockquote
            if self.use_ctk:
                label.configure(text=text, text_color=target_color)
            else:
                label.configure(text=text, fg=target_color)
        except Exception:
            pass

    def _format_tts_duration(self, seconds):
        """Format duration as MM:SS."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"
