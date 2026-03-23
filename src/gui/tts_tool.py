#!/usr/bin/env python3
"""
TTS Tool - Main Controller

Coordinates hotkey listening, backend logic, and window UI requests for the Text-to-Speech feature.
"""

import logging
import threading
import os
from typing import Optional, Dict, Any, List, Callable

from .hotkey import HotkeyListener
from .prompts import PromptsConfig
from ..request_pipeline import RequestPipeline, RequestContext, RequestOrigin
from ..api_client import get_provider_for_type
from ..audio.wav_utils import pcm_to_wav, get_pcm_duration, save_wav
from ..audio.tts_constants import get_voice_details


class TTSToolApp:
    """
    Main controller for TTS feature.
    
    Manages the lifecycle of:
    - Hotkey listener for activation
    - TTS window request
    - Backend TTS generation logic
    - AI Director logic
    """
    
    def __init__(
        self,
        config: Dict[str, Any],
        ai_params: Dict[str, Any],
        key_managers: Dict[str, Any]
    ):
        """
        Initialize the TTS tool.
        
        Args:
            config: Main application configuration
            ai_params: AI parameters dictionary
            key_managers: Dictionary of KeyManager instances for each provider
        """
        self.config = config
        self.ai_params = ai_params
        self.key_managers = key_managers
        
        # Feature settings
        self.enabled = config.get("tts_enabled", True)
        self.hotkey = config.get("tts_hotkey", "ctrl+alt+t")
        
        # Load prompts via unified config
        self.prompts = PromptsConfig.get_instance()
        
        # State
        self.hotkey_listener: Optional[HotkeyListener] = None
        self._window_open = False
        
        logging.debug('TTSToolApp initialized')
    
    def start(self):
        """Start the TTS tool with hotkey listener."""
        if not self.enabled:
            logging.info('TTS Tool is disabled')
            return
        
        logging.info(f'Starting TTSTool with hotkey: {self.hotkey}')
        
        self.hotkey_listener = HotkeyListener(
            shortcut=self.hotkey,
            callback=self._on_hotkey_pressed
        )
        self.hotkey_listener.start()
        
        print(f"  ✅ TTSTool: Hotkey '{self.hotkey}' registered")
    
    def stop(self):
        """Stop the TTS tool."""
        logging.info('Stopping TTSTool')
        
        if self.hotkey_listener:
            self.hotkey_listener.stop()
            self.hotkey_listener = None
            
    def pause(self):
        """Pause the hotkey listener."""
        if self.hotkey_listener:
            self.hotkey_listener.pause()
    
    def resume(self):
        """Resume the hotkey listener."""
        if self.hotkey_listener:
            self.hotkey_listener.resume()
    
    def _on_hotkey_pressed(self):
        """Handle hotkey press - show TTS window."""
        logging.debug('TTS Tool hotkey pressed')
        
        if self._window_open:
            logging.debug('TTS Window already open, ignoring hotkey')
            return
        
        self._window_open = True
        
        # Request window via GUICoordinator (runs on GUI thread)
        from .core import GUICoordinator
        GUICoordinator.get_instance().request_tts_window(
            initial_text="",
            on_close=self._on_window_closed
        )
    
    def _on_window_closed(self):
        """Handle window close."""
        logging.debug('TTS window closed')
        self._window_open = False

    def is_running(self) -> bool:
        """Check if TTSTool is running."""
        return self.hotkey_listener is not None and self.hotkey_listener.is_running()
    
    def is_paused(self) -> bool:
        """Check if TTSTool is paused."""
        return self.hotkey_listener is not None and self.hotkey_listener.is_paused()
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        return {
            "enabled": self.enabled,
            "running": self.is_running(),
            "paused": self.is_paused(),
            "hotkey": self.hotkey,
            "window_open": self._window_open
        }

    def reload_prompts(self):
        """Reload configuration."""
        self.prompts.reload()
        # Also reload hotkey from config if changed (requires restart usually, but we can try)
        logging.info("TTSTool prompts reloaded")

    # =========================================================================
    # Backend Logic - Exposed for Window and External Use
    # =========================================================================

    def _build_gender_constraint(self, voice_info: Optional[Dict[str, Any]]) -> str:
        """
        Build a gender constraint string from voice info for the AI Director.
        
        Args:
            voice_info: Dict with voice info. Single-speaker: {"voice": "Kore"}.
                        Multi-speaker: {"multi": True, "speakers": [{"name": "...", "voice": "..."}, ...]}.
        
        Returns:
            Gender constraint string to append to the director task, or empty string.
        """
        if not voice_info:
            return ""
        
        if voice_info.get("multi"):
            # Multi-speaker mode
            speakers = voice_info.get("speakers", [])
            if not speakers:
                return ""
            
            parts = []
            for s in speakers:
                details = get_voice_details(s.get("voice", ""))
                gender = details.get("gender", "Unknown")
                if gender != "Unknown":
                    parts.append(f"{s.get('name', 'Speaker')} uses a {gender} voice.")
            
            if not parts:
                return ""
            
            speaker_info = " ".join(parts)
            return (
                f"\n\nVoice gender constraint: This is a multi-speaker script. "
                f"{speaker_info} "
                f"Each speaker's audio profile must match their voice gender."
            )
        else:
            # Single-speaker mode
            voice_name = voice_info.get("voice", "")
            if not voice_name:
                return ""
            
            details = get_voice_details(voice_name)
            gender = details.get("gender", "Unknown")
            if gender == "Unknown":
                return ""
            
            return (
                f"\n\nVoice gender constraint: The selected TTS voice is {gender}. "
                f"The audio profile character must be {gender}."
            )

    def run_director(
        self,
        input_text: str,
        model_override: str = "",
        voice_info: Optional[Dict[str, Any]] = None,
        callback_success: Optional[Callable[[str, int], None]] = None,
        callback_error: Optional[Callable[[str], None]] = None
    ):
        """
        Run the AI Director to generate style instructions.
        
        Args:
            input_text: The text to analyze and style.
            model_override: Optional model name to override default provider.
            voice_info: Optional dict with voice info for gender injection.
                Single-speaker: {"voice": "Kore"}
                Multi-speaker: {"multi": True, "speakers": [{"name": "S1", "voice": "Kore"}, ...]}
            callback_success: Callback function(response_text, token_count).
            callback_error: Callback function(error_message).
        """
        def _target():
            try:
                # Get director prompts
                system_prompt = self.prompts.get_tts_director_system_prompt()
                task_template = self.prompts.get_tts_director_task_template()
                task = task_template.replace("{text}", input_text)
                
                # Inject voice gender constraint
                task += self._build_gender_constraint(voice_info)
                
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": task}
                ]
                
                provider = self.config.get("default_provider", "google")
                model = model_override or self.config.get(f"{provider}_model", "")
                
                thinking_enabled = self.config.get("thinking_enabled", False)
                ctx = RequestContext(
                    origin=RequestOrigin.TTS_TOOL,
                    provider=provider,
                    model=model,
                    streaming=False,
                    thinking_enabled=thinking_enabled
                )
                
                ctx = RequestPipeline.execute_simple(
                    ctx, messages, self.config, self.ai_params, self.key_managers
                )
                
                if ctx.error:
                    if callback_error:
                        callback_error(f"Director error: {ctx.error}")
                else:
                    if callback_success:
                        callback_success(ctx.response_text, ctx.total_tokens)
                        
            except Exception as e:
                logging.error(f"[TTS] Director error: {e}")
                if callback_error:
                    callback_error(f"Director error: {str(e)}")

        threading.Thread(target=_target, daemon=True).start()

    def generate_audio(
        self,
        text: str,
        voice_name: str,
        model: str,
        multi_config: Optional[List[Dict]] = None,
        callback_success: Optional[Callable[[bytes, bytes, float], None]] = None,
        callback_error: Optional[Callable[[str], None]] = None
    ):
        """
        Generate TTS audio using Google Gemini.
        
        Args:
            text: The text to synthesize.
            voice_name: The voice name to use.
            model: The TTS model name.
            multi_config: Optional multi-speaker configuration.
            callback_success: Callback function(pcm_data, wav_data, duration).
            callback_error: Callback function(error_message).
        """
        def _target():
            try:
                key_manager = self.key_managers.get("google")
                if not key_manager:
                    if callback_error:
                        callback_error("No Google API key configured")
                    return
                
                provider = get_provider_for_type("google", key_manager, self.config)
                
                pcm_data, error = provider.generate_tts(
                    text=text,
                    model=model,
                    voice_name=voice_name,
                    multi_speaker_config=multi_config
                )
                
                if error:
                    if callback_error:
                        callback_error(f"TTS error: {error}")
                    return
                
                wav_data = pcm_to_wav(pcm_data)
                duration = get_pcm_duration(pcm_data)
                
                if callback_success:
                    callback_success(pcm_data, wav_data, duration)
                    
            except Exception as e:
                logging.error(f"[TTS] Generation error: {e}")
                if callback_error:
                    callback_error(f"Error: {e}")

        threading.Thread(target=_target, daemon=True).start()

    def save_audio_file(
        self,
        pcm_data: bytes,
        wav_data: Optional[bytes],
        directory: str,
        voice_name: str,
        format_ext: str,
        transcript_text: Optional[str] = None
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Save audio data to a file using centralized export utilities.
        
        Args:
            pcm_data: Raw PCM bytes.
            wav_data: WAV bytes (optional, will be generated if None and needed).
            directory: Directory to save to.
            voice_name: Name of the voice (for filename fallback).
            format_ext: File extension (wav, mp3, ogg, etc.).
            transcript_text: Optional transcript to embed as metadata and use for filename.
            
        Returns:
            (filename, error_message)
        """
        from ..audio.export import build_output_filename, export_audio_file
        
        os.makedirs(directory, exist_ok=True)
        
        # Build filename: transcript text → voice name fallback
        fallback = voice_name.lower().replace(" ", "_")
        filename = build_output_filename(
            prefix="tts",
            text_source=transcript_text,
            fallback_name=fallback,
            format_ext=format_ext
        )
        filepath = os.path.join(directory, filename)
        
        # Ensure we have WAV data for encoding
        if format_ext == "wav":
            error = save_wav(filepath, pcm_data)
        else:
            if not wav_data:
                wav_data = pcm_to_wav(pcm_data)
            
            error = export_audio_file(
                wav_data=wav_data,
                output_path=filepath,
                format_ext=format_ext,
                metadata_comment=transcript_text
            )
        
        return (filename if not error else None), error


# =============================================================================
# Global instance management
# =============================================================================

_TTS_TOOL_INSTANCE: Optional[TTSToolApp] = None


def set_instance(app: TTSToolApp):
    """Set the global TTSTool instance."""
    global _TTS_TOOL_INSTANCE
    _TTS_TOOL_INSTANCE = app


def get_instance() -> Optional[TTSToolApp]:
    """Get the global TTSTool instance."""
    return _TTS_TOOL_INSTANCE
