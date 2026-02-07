#!/usr/bin/env python3
"""
Screen Snipping Tool - Main Controller

Coordinates hotkey listening, screen capture, popup UI, and AI processing
for the screen snipping feature. Similar architecture to TextEditToolApp.

Flow:
1. User presses hotkey (e.g., Ctrl+Shift+X)
2. Screen overlay appears for region selection
3. After selection, popup appears with image preview and actions
4. User selects action or asks custom question
5. AI processes image and shows result in chat window
"""

import logging
import threading
from typing import Optional, Dict, Any, List

from .hotkey import HotkeyListener
from .prompts import PromptsConfig
from .screen_snip import CaptureResult


class SnipToolApp:
    """
    Main controller for screen snipping feature.
    
    Manages the lifecycle of:
    - Hotkey listener for activation
    - Screen capture overlay
    - Image analysis popup
    - AI request processing
    """
    
    def __init__(
        self,
        config: Dict[str, Any],
        ai_params: Dict[str, Any],
        key_managers: Dict[str, Any]
    ):
        """
        Initialize the snip tool.
        
        Args:
            config: Main application configuration
            ai_params: AI parameters dictionary
            key_managers: Dictionary of KeyManager instances for each provider
        """
        self.config = config
        self.ai_params = ai_params
        self.key_managers = key_managers
        
        # Feature settings
        self.enabled = config.get("screen_snip_enabled", True)
        self.hotkey = config.get("screen_snip_hotkey", "ctrl+shift+x")
        
        # Load prompts via unified config
        self.prompts = PromptsConfig.get_instance()
        
        # State
        self.hotkey_listener: Optional[HotkeyListener] = None
        self.current_capture: Optional[CaptureResult] = None
        self.is_processing = False
        self.cancel_requested = False
        
        logging.debug('SnipToolApp initialized')
    
    def start(self):
        """Start the snip tool with hotkey listener."""
        if not self.enabled:
            logging.info('SnipTool is disabled')
            return
        
        logging.info(f'Starting SnipTool with hotkey: {self.hotkey}')
        
        self.hotkey_listener = HotkeyListener(
            shortcut=self.hotkey,
            callback=self._on_hotkey_pressed
        )
        self.hotkey_listener.start()
        
        print(f"  ✅ SnipTool: Hotkey '{self.hotkey}' registered")
    
    def stop(self):
        """Stop the snip tool."""
        logging.info('Stopping SnipTool')
        
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
        """Handle hotkey press - show snip overlay."""
        logging.debug('SnipTool hotkey pressed')
        
        if self.is_processing:
            logging.debug('Already processing, ignoring hotkey')
            return
        
        self.cancel_requested = False
        
        # Request overlay via GUICoordinator (runs on GUI thread)
        from .core import GUICoordinator
        GUICoordinator.get_instance().request_snip_overlay(
            on_capture=self._on_image_captured,
            on_cancel=self._on_snip_cancelled
        )
    
    def _on_snip_cancelled(self):
        """Handle snip cancellation."""
        logging.debug('Snip cancelled by user')
        self.current_capture = None
    
    def _on_image_captured(self, capture_result: CaptureResult):
        """Handle successful capture - show popup."""
        logging.debug(f'Image captured: {capture_result.width}x{capture_result.height}')
        self.current_capture = capture_result
        
        # Get combined prompts for popup
        prompts_config = self._get_combined_prompts()
        
        from .core import GUICoordinator
        GUICoordinator.get_instance().request_snip_popup(
            capture_result=capture_result,
            prompts_config=prompts_config,
            on_action=self._on_action_selected,
            on_close=self._on_popup_closed,
            on_request_compare_capture=self._on_request_compare_capture
        )
    
    def _on_request_compare_capture(self, on_capture, on_cancel):
        """Handle request for second capture (compare mode)."""
        logging.debug('[SnipTool] Initiating second capture for comparison')
        
        from .core import GUICoordinator
        GUICoordinator.get_instance().request_snip_overlay(
            on_capture=on_capture,
            on_cancel=on_cancel
        )
    
    def _get_combined_prompts(self) -> Dict[str, Any]:
        """Get combined prompts for popup (snip + optionally text_edit)."""
        result = {
            "snip_tool": self.prompts.get_snip_tool()
        }
        
        if self.prompts.can_use_text_edit_actions():
            result["text_edit_tool"] = self.prompts.get_text_edit_tool()
        
        return result
    
    def _on_popup_closed(self):
        """Handle popup close without action."""
        logging.debug('Snip popup closed')
        # Keep capture for potential re-opening? Or clear?
        # For now, keep it - user might want to try again
    
    def _on_action_selected(
        self,
        source: str,
        action_key: str,
        custom_input: Optional[str],
        active_modifiers: List[str] = None,
        compare_mode: bool = False,
        compare_capture: Optional[CaptureResult] = None,
        response_mode: str = "default"
    ):
        """
        Handle action selection from popup.
        
        Args:
            source: "snip", "text_edit", or "file_processor"
            action_key: The action name (e.g., "Describe", "Proofread")
            custom_input: Custom question text (if any)
            active_modifiers: List of active modifier keys
            compare_mode: Whether compare mode is enabled
            compare_capture: Second capture result (if compare mode)
            response_mode: "default", "copy", or "show"
        """
        if active_modifiers is None:
            active_modifiers = []
        
        logging.debug(f'Action selected: source={source}, key={action_key}, custom={bool(custom_input)}, modifiers={active_modifiers}, compare={compare_mode}, mode={response_mode}')
        
        if not self.current_capture:
            logging.error('No capture available for action')
            return
        
        self.is_processing = True
        
        # Process in background thread
        threading.Thread(
            target=self._process_action,
            args=(source, action_key, custom_input, active_modifiers, compare_mode, compare_capture, response_mode),
            daemon=True
        ).start()
    
    def _build_modifier_injections(self, active_modifiers: List[str]) -> str:
        """Build modifier injection text to append to system prompt."""
        modifier_defs = self.prompts.get_modifiers()
        injections = []
        for mod in modifier_defs:
            if mod.get("key") in active_modifiers:
                injection = mod.get("injection", "")
                if injection:
                    injections.append(injection)
        return "\n".join(injections)
    
    def _modifiers_force_chat_window(self, active_modifiers: List[str]) -> bool:
        """Check if any active modifier forces chat window display."""
        modifier_defs = self.prompts.get_modifiers()
        for mod in modifier_defs:
            if mod.get("key") in active_modifiers and mod.get("forces_chat_window", False):
                return True
        return False
    
    def _process_action(
        self,
        source: str,
        action_key: str,
        custom_input: Optional[str],
        active_modifiers: List[str] = None,
        compare_mode: bool = False,
        compare_capture: Optional[CaptureResult] = None,
        response_mode: str = "default"
    ):
        """Process the selected action with image context."""
        if active_modifiers is None:
            active_modifiers = []
        
        try:
            from ..messages import build_image_message, build_comparison_message

            # Handle File Processor source separately
            if source == "file_processor":
                system_prompt, task = self._get_file_processor_prompt(action_key)
                action = {}
            else:
                # Get action config based on source
                if source == "text_edit":
                    actions = self.prompts.get_text_edit_actions()
                    settings = self.prompts.get_text_edit_tool().get("_settings", {})
                else:
                    actions = self.prompts.get_snip_actions()
                    settings = self.prompts.get_snip_tool().get("_settings", {})
                
                action = actions.get(action_key, {})
                
                # Build prompt
                system_prompt = action.get("system_prompt", "You are an AI assistant analyzing images.")
                task = action.get("task", "Analyze this image.")
                
                # Handle custom input
                if action_key == "_Custom" and custom_input:
                    template = settings.get(
                        "custom_task_template",
                        "Regarding this image: {custom_input}"
                    )
                    task = template.format(custom_input=custom_input)
            
            # Determine display mode
            if response_mode == "show":
                show_in_chat = True
            elif response_mode == "copy":
                show_in_chat = False
            else:  # "default"
                # Check action config
                # Default for SnipTool actions is usually show_chat_window=True
                # But we should respect the config if present
                show_in_chat = action.get("show_chat_window", True)
                
                # Check modifiers (some might force chat window)
                if not show_in_chat and self._modifiers_force_chat_window(active_modifiers):
                    show_in_chat = True

            # Apply modifier injections to system prompt
            if active_modifiers:
                modifier_injections = self._build_modifier_injections(active_modifiers)
                if modifier_injections:
                    system_prompt = system_prompt + "\n\n" + modifier_injections
            
            # Build multimodal message (single or comparison)
            if compare_mode and compare_capture:
                messages = build_comparison_message(
                    image1_b64=self.current_capture.image_base64,
                    image2_b64=compare_capture.image_base64,
                    mime_type=self.current_capture.mime_type,
                    task=task,
                    system_prompt=system_prompt
                )
                window_title = f"🔀 {action_key}"
                image_info = f"{self.current_capture.width}x{self.current_capture.height} vs {compare_capture.width}x{compare_capture.height}"
            else:
                messages = build_image_message(
                    image_b64=self.current_capture.image_base64,
                    mime_type=self.current_capture.mime_type,
                    task=task,
                    system_prompt=system_prompt
                )
                window_title = f"📷 {action_key}"
                image_info = f"{self.current_capture.width}x{self.current_capture.height}"
            
            # Log the request
            print(f"\n{'─'*60}")
            print(f"[SnipTool] Processing: {action_key}")
            print(f"[SnipTool] Image{'s' if compare_mode else ''}: {image_info}")
            if compare_mode:
                print(f"[SnipTool] Compare Mode: Enabled")
            if active_modifiers:
                print(f"[SnipTool] Modifiers: {', '.join(active_modifiers)}")
            print(f"[SnipTool] Mode: {response_mode} (Output: {'Chat Window' if show_in_chat else 'Clipboard'})")
            
            if show_in_chat:
                from ..request_pipeline import RequestOrigin
                self._stream_to_chat_window(
                    messages=messages,
                    window_title=window_title,
                    origin=RequestOrigin.SNIP_TOOL,
                    compare_capture=compare_capture
                )
            else:
                self._copy_to_clipboard_with_notification(messages, action_key)
            
            print(f"{'─'*60}\n")
            
        except Exception as e:
            logging.error(f'Error processing snip action: {e}')
            
            from .popups import show_error_popup
            show_error_popup(
                title="Snip Tool Error",
                message=f"Failed to process '{action_key}' action.",
                details=str(e)
            )
        finally:
            self.is_processing = False
    
    def _get_file_processor_prompt(self, action_key: str) -> tuple:
        """
        Get prompt from File Processor tools_config.json.
        
        File Processor prompts have only a user prompt, no system prompt.
        
        Args:
            action_key: The prompt key name
            
        Returns:
            Tuple of (system_prompt, task)
        """
        try:
            from ..tools.config import load_tools_config, get_prompt_by_key
            config = load_tools_config(create_if_missing=False)
            prompt_config = get_prompt_by_key(config, action_key)
            
            if prompt_config:
                # File Processor prompts only have a user prompt, use minimal system prompt
                system_prompt = "You are a helpful AI assistant processing images."
                task = prompt_config.get("prompt", "Analyze this image.")
                return system_prompt, task
        except Exception as e:
            logging.error(f"[SnipTool] Failed to load file processor prompt '{action_key}': {e}")
        
        # Fallback
        return "You are a helpful AI assistant.", "Analyze this image."
    
    # _build_image_message and _build_comparison_message removed in favor of src/gui/messages.py
    
    def _copy_to_clipboard_with_notification(self, messages, action_key):
        """Execute non-streaming request, copy to clipboard, show notification."""
        from ..request_pipeline import RequestPipeline, RequestContext, RequestOrigin
        import pyperclip
        
        provider = self.config.get("default_provider", "google")
        
        ctx = RequestContext(
            origin=RequestOrigin.SNIP_TOOL,
            provider=provider,
            model=self.config.get(f"{provider}_model"),
            streaming=False,  # Must be non-streaming for copy mode
            thinking_enabled=self.config.get("thinking_enabled", False)
        )
        
        ctx = RequestPipeline.execute_simple(
            ctx, messages, self.config, self.ai_params, self.key_managers
        )
        
        if ctx.error:
            logging.error(f'Copy mode request failed: {ctx.error}')
            print(f"  [Error] {ctx.error}")
            from .popups import show_error_popup
            show_error_popup(
                title="API Request Failed",
                message="Failed to process image for copy.",
                details=ctx.error
            )
            return
        
        if ctx.response_text:
            # Copy to clipboard
            try:
                pyperclip.copy(ctx.response_text)
                
                # Play sound
                from ..utils import play_sound
                play_sound("assets/snip.wav")
                
                # Show toast notification
                from .core import GUICoordinator
                GUICoordinator.get_instance().request_toast_notification(
                    title=f"{action_key}",
                    message=ctx.response_text
                )
                
                print(f"  ✅ Copied to clipboard ({len(ctx.response_text)} chars)")
            except Exception as e:
                logging.error(f"Failed to copy to clipboard: {e}")
                print(f"  [Error] Failed to copy: {e}")

    def _stream_to_chat_window(
        self,
        messages: List[Dict[str, Any]],
        window_title: str,
        origin,
        compare_capture: Optional[CaptureResult] = None
    ):
        """
        Open a chat window and stream API response into it.
        
        Args:
            messages: API messages with image(s)
            window_title: Title for the chat window
            origin: RequestOrigin for logging
            compare_capture: Optional second capture for comparison mode
        """
        from .core import GUICoordinator
        from ..session_manager import ChatSession
        from ..attachment_manager import AttachmentManager
        from ..request_pipeline import RequestPipeline, RequestContext, StreamCallback
        
        # Create session (empty image initially, properly utilizing attachments)
        session = ChatSession(
            endpoint="snip",
            mime_type=None
        )
        session.title = window_title
        
        attachments = []
        
        # Helper to detect mime from path
        def get_mime_from_path(path):
            if path.lower().endswith(".webp"): return "image/webp"
            if path.lower().endswith(".png"): return "image/png"
            if path.lower().endswith(".jpg") or path.lower().endswith(".jpeg"): return "image/jpeg"
            return "application/octet-stream"

        # Save primary image to external file for persistence
        attachment_path = AttachmentManager.save_image(
            session_id=session.session_id,
            image_base64=self.current_capture.image_base64,
            mime_type=self.current_capture.mime_type,
            message_index=0
        )
        
        if attachment_path:
            attachments.append({
                "path": attachment_path,
                "mime_type": get_mime_from_path(attachment_path)
            })
        
        # Save comparison image if present
        if compare_capture:
            compare_path = AttachmentManager.save_image(
                session_id=session.session_id,
                image_base64=compare_capture.image_base64,
                mime_type=compare_capture.mime_type,
                message_index=1
            )
            if compare_path:
                attachments.append({
                    "path": compare_path,
                    "mime_type": get_mime_from_path(compare_path)
                })
        
        if attachments:
            # Update session mime type to match first attachment if available
            if len(attachments) > 0:
                session.mime_type = attachments[0]["mime_type"]
        
        # Add user message
        # Extract text from multimodal message
        user_content = messages[1]["content"]
        if isinstance(user_content, list):
            # In comparison mode, there are multiple text parts ("Image 1:", "Image 2:", Task)
            # We want the last one which is the actual task
            text_parts = [item["text"] for item in user_content if item.get("type") == "text"]
            raw_task = text_parts[-1] if text_parts else "Analyze this image."
            task_text = raw_task
        else:
            task_text = user_content
        
        # Add message with attachments (attachments belong to message, not session)
        session.add_message("user", task_text, attachments=attachments)
        
        # Set system instruction for follow-ups (use global setting)
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
                    message="Failed to analyze image.",
                    details=ctx.error
                )
                return
            
            # Finalize
            response_text = ''.join(full_response) or ctx.response_text or ""
            thinking_text = ''.join(full_thinking) or ctx.reasoning_text or ""
            
            callbacks.finalize(response_text, thinking_text)

            # Explicitly add assistant message to session before auto-save
            # The streaming window displays it, but we need to ensure it's in the session object for persistence
            if response_text and not any(m["role"] == "assistant" and m["content"] == response_text for m in session.messages):
                session.add_message("assistant", response_text)

            # Auto-save session if configured
            self._handle_auto_save(session)
            
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
                logging.error(f'Image analysis failed: {ctx.error}')
                print(f"  [Error] {ctx.error}")
                
                from .popups import show_error_popup
                show_error_popup(
                    title="API Request Failed",
                    message="Failed to analyze image.",
                    details=ctx.error
                )
                return
            
            if ctx.response_text:
                # Show chat window with response
                session.add_message("assistant", ctx.response_text)
                
                from .core import show_chat_gui
                show_chat_gui(session, initial_response=ctx.response_text)

                # Auto-save session if confgured
                self._handle_auto_save(session)
                
                print(f"  ✅ Response received ({len(ctx.response_text)} chars)")
    
    def _handle_auto_save(self, session):
        """Handle auto-saving session based on configuration."""
        auto_save = self.config.get("auto_save_session", "on_followup")
        
        should_save = False
        if auto_save == "always_window":
            should_save = True
        elif auto_save == "on_attachment":
            # Check if any message has attachments
            for msg in session.messages:
                if msg.get("attachments"):
                    should_save = True
                    break
                    
        if should_save:
            from ..session_manager import add_session
            add_session(session, self.config.get("max_sessions", 50))
            logging.debug(f"Auto-saved session {session.session_id} (mode: {auto_save})")

    def is_running(self) -> bool:
        """Check if SnipTool is running."""
        return self.hotkey_listener is not None and self.hotkey_listener.is_running()
    
    def is_paused(self) -> bool:
        """Check if SnipTool is paused."""
        return self.hotkey_listener is not None and self.hotkey_listener.is_paused()
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        return {
            "enabled": self.enabled,
            "running": self.is_running(),
            "paused": self.is_paused(),
            "hotkey": self.hotkey,
            "processing": self.is_processing
        }
    
    def reload_prompts(self):
        """Reload prompts configuration."""
        self.prompts.reload()
        logging.info("SnipTool prompts reloaded")


# =============================================================================
# Global instance management
# =============================================================================

_SNIP_TOOL_INSTANCE: Optional[SnipToolApp] = None


def set_instance(app: SnipToolApp):
    """Set the global SnipTool instance."""
    global _SNIP_TOOL_INSTANCE
    _SNIP_TOOL_INSTANCE = app


def get_instance() -> Optional[SnipToolApp]:
    """Get the global SnipTool instance."""
    return _SNIP_TOOL_INSTANCE


def reload_prompts():
    """Reload SnipTool prompts from file."""
    if _SNIP_TOOL_INSTANCE:
        _SNIP_TOOL_INSTANCE.reload_prompts()
    else:
        logging.debug("[SnipTool] No instance to reload prompts for")