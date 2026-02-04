#!/usr/bin/env python3
"""
Audio Analyzer Tool - Main Controller

Coordinates hotkey listening, audio recording, window UI, and AI processing
for the audio analysis feature. Similar architecture to SnipToolApp.

Flow:
1. User presses hotkey (e.g., Ctrl+Shift+A)
2. AudioAnalyzerWindow appears with device selection and recording controls
3. User records audio and selects action
4. AI processes audio and shows result in chat window
"""

import logging
import threading
from typing import Optional, Dict, Any, List

from .hotkey import HotkeyListener
from .prompts import PromptsConfig


class AudioToolApp:
    """
    Main controller for audio analyzer feature.
    
    Manages the lifecycle of:
    - Hotkey listener for activation
    - Audio analyzer window
    - AI request processing
    """
    
    def __init__(
        self,
        config: Dict[str, Any],
        ai_params: Dict[str, Any],
        key_managers: Dict[str, Any]
    ):
        """
        Initialize the audio tool.
        
        Args:
            config: Main application configuration
            ai_params: AI parameters dictionary
            key_managers: Dictionary of KeyManager instances for each provider
        """
        self.config = config
        self.ai_params = ai_params
        self.key_managers = key_managers
        
        # Feature settings
        self.enabled = config.get("audio_tool_enabled", True)
        self.hotkey = config.get("audio_tool_hotkey", "ctrl+shift+a")
        
        # Load prompts via unified config
        self.prompts = PromptsConfig.get_instance()
        
        # State
        self.hotkey_listener: Optional[HotkeyListener] = None
        self.is_processing = False
        self.cancel_requested = False
        self._window_open = False
        
        logging.debug('AudioToolApp initialized')
    
    def start(self):
        """Start the audio tool with hotkey listener."""
        if not self.enabled:
            logging.info('AudioTool is disabled')
            return
        
        logging.info(f'Starting AudioTool with hotkey: {self.hotkey}')
        
        self.hotkey_listener = HotkeyListener(
            shortcut=self.hotkey,
            callback=self._on_hotkey_pressed
        )
        self.hotkey_listener.start()
        
        print(f"  ✅ AudioTool: Hotkey '{self.hotkey}' registered")
    
    def stop(self):
        """Stop the audio tool."""
        logging.info('Stopping AudioTool')
        
        if self.hotkey_listener:
            self.hotkey_listener.stop()
            self.hotkey_listener = None
        
        self.cancel_requested = True
    
    def pause(self):
        """Pause the hotkey listener."""
        if self.hotkey_listener:
            self.hotkey_listener.pause()
    
    def resume(self):
        """Resume the hotkey listener."""
        if self.hotkey_listener:
            self.hotkey_listener.resume()
    
    def _on_hotkey_pressed(self):
        """Handle hotkey press - show audio analyzer window."""
        logging.debug('AudioTool hotkey pressed')
        
        if self._window_open:
            logging.debug('Window already open, ignoring hotkey')
            return
        
        self.cancel_requested = False
        self._window_open = True
        
        # Request window via GUICoordinator (runs on GUI thread)
        from .core import GUICoordinator
        GUICoordinator.get_instance().request_audio_analyzer_window(
            config=self.config,
            ai_params=self.ai_params,
            key_managers=self.key_managers,
            on_action=self._on_action_selected,
            on_close=self._on_window_closed
        )
    
    def _on_window_closed(self):
        """Handle window close."""
        logging.debug('Audio analyzer window closed')
        self._window_open = False
    
    def _on_action_selected(
        self,
        action_key: str,
        audio_data: bytes,
        mime_type: str,
        custom_input: Optional[str] = None,
        duration: float = 0.0,
        compressed: bool = False
    ):
        """
        Handle action selection from window.
        
        Args:
            action_key: The action name (e.g., "Transcribe", "Summarize")
            audio_data: Raw audio bytes (WAV or compressed)
            mime_type: MIME type of the audio
            custom_input: Custom question text (if any)
            duration: Duration in seconds
            compressed: Whether audio is compressed
        """
        logging.debug(f'Action selected: key={action_key}, custom={bool(custom_input)}, duration={duration:.1f}s, compressed={compressed}')
        
        if not audio_data:
            logging.error('No audio data available for action')
            return
        
        self.is_processing = True
        
        # Process in background thread
        threading.Thread(
            target=self._process_action,
            args=(action_key, audio_data, mime_type, custom_input, duration),
            daemon=True
        ).start()
    
    def _process_action(
        self,
        action_key: str,
        audio_data: bytes,
        mime_type: str,
        custom_input: Optional[str],
        duration: float
    ):
        """Process the selected action with audio context."""
        try:
            import base64
            from ..messages import build_audio_message
            
            # Get action config
            actions = self.prompts.get_audio_actions()
            settings = self.prompts.get_audio_tool().get("_settings", {})
            
            action = actions.get(action_key, {})
            
            # Build prompt
            system_prompt = action.get("system_prompt", "You are an AI assistant analyzing audio.")
            task = action.get("task", "Analyze this audio.")
            
            # Handle custom input
            if action_key == "_Custom" and custom_input:
                template = settings.get(
                    "custom_task_template",
                    "Regarding this audio: {custom_input}"
                )
                task = template.format(custom_input=custom_input)
            
            # Build multimodal message with audio
            audio_b64 = base64.b64encode(audio_data).decode('utf-8')
            messages = build_audio_message(
                audio_b64=audio_b64,
                mime_type=mime_type,
                task=task,
                system_prompt=system_prompt
            )
            
            window_title = f"🎤 {action_key}"
            
            # Log the request
            print(f"\n{'─'*60}")
            print(f"[AudioTool] Processing: {action_key}")
            print(f"[AudioTool] Audio: {duration:.1f}s, {len(audio_data) / 1024:.1f} KB, {mime_type}")
            
            # Stream to chat window
            from ..request_pipeline import RequestOrigin
            self._stream_to_chat_window(
                messages=messages,
                window_title=window_title,
                origin=RequestOrigin.AUDIO_TOOL,
                audio_data=audio_data,
                mime_type=mime_type,
                duration=duration
            )
            
            print(f"{'─'*60}\n")
            
        except Exception as e:
            logging.error(f'Error processing audio action: {e}')
            
            from .popups import show_error_popup
            show_error_popup(
                title="Audio Tool Error",
                message=f"Failed to process '{action_key}' action.",
                details=str(e)
            )
        finally:
            self.is_processing = False
    
    # _build_audio_message removed in favor of src/gui/messages.py
    # _get_audio_format removed as it's no longer needed for inline_data
    
    def _stream_to_chat_window(
        self,
        messages: List[Dict[str, Any]],
        window_title: str,
        origin,
        audio_data: bytes,
        mime_type: str,
        duration: float
    ):
        """
        Open a chat window and stream API response into it.
        
        Args:
            messages: API messages with audio
            window_title: Title for the chat window
            origin: RequestOrigin for logging
            audio_data: Audio bytes for attachment
            mime_type: Audio MIME type
            duration: Audio duration in seconds
        """
        from .core import GUICoordinator
        from ..session_manager import ChatSession
        from ..attachment_manager import AttachmentManager
        from ..request_pipeline import RequestPipeline, RequestContext, StreamCallback
        
        # Create session with audio info
        session = ChatSession(endpoint="audio")
        session.title = window_title
        
        # Save audio to external file for persistence
        attachment_path = AttachmentManager.save_audio(
            session_id=session.session_id,
            audio_data=audio_data,
            mime_type=mime_type,
            message_index=0
        )
        attachments = []
        if attachment_path:
            attachments.append({
                "path": attachment_path,
                "mime_type": mime_type,
                "duration": duration
            })
            session.attachments = attachments
        
        # Add user message (just the task text, audio is in session)
        # Extract text from multimodal message
        user_content = messages[1]["content"]
        if isinstance(user_content, list):
            task_text = next(
                (item["text"] for item in user_content if item.get("type") == "text"),
                "Analyze this audio."
            )
        else:
            task_text = user_content
        
        session.add_message("user", task_text)
        
        # Set system instruction for follow-ups
        session.system_instruction = self.prompts.get_chat_window_system_instruction()
        
        # Check if streaming is enabled
        streaming_enabled = self.config.get("streaming_enabled", True)
        
        if streaming_enabled:
            # Request streaming chat window
            callbacks = GUICoordinator.get_instance().request_streaming_chat_window(session)
            
            if not callbacks.on_text:
                logging.error("Failed to create streaming chat window")
                print("  [Error] Failed to create chat window")
                return
            
            # Accumulated response
            full_response = []
            full_thinking = []
            
            provider = self.config.get("default_provider", "google")
            
            # Setup context
            ctx = RequestContext(
                origin=origin,
                provider=provider,
                model=self.config.get(f"{provider}_model"),
                streaming=True,
                thinking_enabled=self.config.get("thinking_enabled", False)
            )
            
            # Stream callbacks
            def on_text(content):
                full_response.append(content)
                if callbacks.on_text:
                    callbacks.on_text(content)
            
            def on_thinking(content):
                full_thinking.append(content)
                if callbacks.on_thinking:
                    callbacks.on_thinking(content)
            
            def on_done():
                if callbacks.on_done:
                    callbacks.on_done()
            
            stream_callbacks = StreamCallback(
                on_text=on_text,
                on_thinking=on_thinking,
                on_done=on_done
            )
            
            # Execute streaming request
            ctx = RequestPipeline.execute_unified_stream(
                ctx,
                messages,
                self.config,
                self.ai_params,
                self.key_managers,
                stream_callbacks
            )
            
            if ctx.error:
                logging.error(f'Streaming to chat window failed: {ctx.error}')
                print(f"  [Error] {ctx.error}")
                
                from .popups import show_error_popup
                show_error_popup(
                    title="API Request Failed",
                    message="Failed to analyze audio.",
                    details=ctx.error
                )
                return
            
            # Finalize
            response_text = ''.join(full_response) or ctx.response_text or ""
            thinking_text = ''.join(full_thinking) or ctx.reasoning_text or ""
            
            callbacks.finalize(response_text, thinking_text)
            
            print(f"  ✅ Response streamed to chat window ({len(response_text)} chars)")
        else:
            # Non-streaming: execute simple request, then show window
            provider = self.config.get("default_provider", "google")
            
            ctx = RequestContext(
                origin=origin,
                provider=provider,
                model=self.config.get(f"{provider}_model"),
                streaming=False,
                thinking_enabled=self.config.get("thinking_enabled", False)
            )
            
            ctx = RequestPipeline.execute_simple(
                ctx,
                messages,
                self.config,
                self.ai_params,
                self.key_managers
            )
            
            if ctx.error:
                logging.error(f'Audio analysis failed: {ctx.error}')
                print(f"  [Error] {ctx.error}")
                
                from .popups import show_error_popup
                show_error_popup(
                    title="API Request Failed",
                    message="Failed to analyze audio.",
                    details=ctx.error
                )
                return
            
            if ctx.response_text:
                # Show chat window with response
                session.add_message("assistant", ctx.response_text)
                
                from .core import show_chat_gui
                show_chat_gui(session, initial_response=ctx.response_text)
                
                print(f"  ✅ Response received ({len(ctx.response_text)} chars)")
    
    def is_running(self) -> bool:
        """Check if AudioTool is running."""
        return self.hotkey_listener is not None and self.hotkey_listener.is_running()
    
    def is_paused(self) -> bool:
        """Check if AudioTool is paused."""
        return self.hotkey_listener is not None and self.hotkey_listener.is_paused()
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        return {
            "enabled": self.enabled,
            "running": self.is_running(),
            "paused": self.is_paused(),
            "hotkey": self.hotkey,
            "processing": self.is_processing,
            "window_open": self._window_open
        }
    
    def reload_prompts(self):
        """Reload prompts configuration."""
        self.prompts.reload()
        logging.info("AudioTool prompts reloaded")


# =============================================================================
# Global instance management
# =============================================================================

_AUDIO_TOOL_INSTANCE: Optional[AudioToolApp] = None


def set_instance(app: AudioToolApp):
    """Set the global AudioTool instance."""
    global _AUDIO_TOOL_INSTANCE
    _AUDIO_TOOL_INSTANCE = app


def get_instance() -> Optional[AudioToolApp]:
    """Get the global AudioTool instance."""
    return _AUDIO_TOOL_INSTANCE


def reload_prompts():
    """Reload AudioTool prompts from file."""
    if _AUDIO_TOOL_INSTANCE:
        _AUDIO_TOOL_INSTANCE.reload_prompts()
    else:
        logging.debug("[AudioTool] No instance to reload prompts for")
