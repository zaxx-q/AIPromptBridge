#!/usr/bin/env python3
"""
Main TextEditTool application controller

Settings Override Hierarchy (for display mode):
1. Radio button in popup (if not "Default") - highest priority
2. show_chat_window_instead_of_replace per-action option - per-action default
3. show_ai_response_in_chat_window in config - global default (AttachedInputPopup only)

For API endpoints, the ?show= URL parameter takes highest priority.
"""

import logging
import threading
import time
from typing import Dict, Optional

from .hotkey import HotkeyListener
from .prompts import get_prompts_config
from .text_handler import TextHandler


class TextEditToolApp:
    """
    Main TextEditTool application controller.
    Coordinates hotkey listening, text handling, UI, and AI requests.
    """

    def __init__(self, config: Dict, ai_params: Dict, key_managers: Dict):
        """
        Initialize the TextEditTool application.

        Args:
            config: Main configuration dictionary
            ai_params: AI parameters dictionary
            key_managers: Dictionary of KeyManager instances
        """
        self.config = config
        self.ai_params = ai_params
        self.key_managers = key_managers

        # Live reference to PromptsConfig singleton (like SnipTool pattern)
        # Reads are always fresh - no stale snapshot caching
        self.prompts = get_prompts_config()

        # Get TextEditTool-specific config
        self.enabled = config.get("text_edit_tool_enabled", True)
        self.hotkey = config.get("text_edit_tool_hotkey", "ctrl+space")
        self.abort_hotkey = config.get("text_edit_tool_abort_hotkey", "escape")

        # Typing speed settings
        self.typing_delay_ms = config.get("streaming_typing_delay", 0)

        # Initialize components
        self.hotkey_listener: Optional[HotkeyListener] = None
        self.text_handler = TextHandler()

        # Current state
        self.popup = None
        self.chat_window = None
        self.current_selected_text = ""
        self._active_tasks = 0
        self._tasks_lock = threading.Lock()
        self.cancel_requested = False

        # Streaming abort state
        self.streaming_aborted = False
        self._abort_listener = None

        logging.debug("TextEditToolApp initialized")

    def _begin_task(self):
        """Increment active task counter (thread-safe)."""
        with self._tasks_lock:
            self._active_tasks += 1

    def _end_task(self):
        """Decrement active task counter (thread-safe)."""
        with self._tasks_lock:
            self._active_tasks = max(0, self._active_tasks - 1)

    @property
    def is_processing(self):
        """Check if any tasks are currently active (thread-safe)."""
        with self._tasks_lock:
            return self._active_tasks > 0

    def _get_setting(self, key: str, default=None):
        """Get a setting from the _settings section of options.

        Reads live from PromptsConfig singleton - no stale snapshots.
        """
        return self.prompts.get_text_edit_setting(key, default)

    def _get_action_options(self) -> Dict:
        """Get action options (excluding _settings).

        Reads live from PromptsConfig singleton - no stale snapshots.
        """
        return self.prompts.get_text_edit_actions()

    def start(self):
        """Start the TextEditTool application."""
        if not self.enabled:
            logging.info("TextEditTool is disabled")
            return

        logging.info(f"Starting TextEditTool with hotkey: {self.hotkey}")

        # Create and start hotkey listener (no-op on Linux — use --trigger textedit / chat)
        self.hotkey_listener = HotkeyListener(shortcut=self.hotkey, callback=self._on_hotkey_pressed)
        self.hotkey_listener.start()

        if self.hotkey_listener.is_running():
            print(f"  ✅ TextEditTool: Hotkey '{self.hotkey}' registered")
        else:
            print("  ✅ TextEditTool: Ready (trigger via: --trigger textedit)")

    def stop(self):
        """Stop the TextEditTool application."""
        logging.info("Stopping TextEditTool")

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
        """Handle hotkey press event."""
        logging.debug("Hotkey pressed")

        # Show popup immediately in a new thread
        # Multiple concurrent invocations are allowed - each operates independently
        threading.Thread(target=self._show_popup, daemon=True).start()

    def _show_popup(self):
        """Show the appropriate popup window via GUICoordinator."""
        logging.debug("Showing popup window via GUICoordinator")

        from .core import GUICoordinator

        # Get selected text (captured locally to avoid race conditions
        # when multiple hotkey presses trigger concurrent popups)
        if self.config.get("text_edit_slow_app_retry", False):
            selected_text = self.text_handler.get_selected_text_with_retry()
        else:
            selected_text = self.text_handler.get_selected_text()

        # Only offer TTS button in popups if TTS is enabled
        on_tts = self._on_tts_requested if self.config.get("tts_enabled", True) else None

        if selected_text:
            logging.debug(f'Selected text: "{selected_text[:50]}..."')
            # Text selected - show prompt selection popup via coordinator
            # Pass live options from PromptsConfig (including _settings for popup_items_per_page)
            GUICoordinator.get_instance().request_prompt_popup(
                options=self.prompts.get_text_edit_tool(),
                on_option_selected=self._on_option_selected,
                on_close=self._on_popup_closed,
                selected_text=selected_text,
                on_tts=on_tts,
                on_request_compare_text=self._on_request_compare_text,
            )
        else:
            # No text selected - show simple input popup via coordinator
            logging.debug("No text selected, showing input popup")
            GUICoordinator.get_instance().request_input_popup(
                on_submit=self._on_direct_chat, on_close=self._on_popup_closed, on_tts=on_tts
            )

    def _on_popup_closed(self):
        """Handle popup window close."""
        logging.debug("Popup window closed")
        self.popup = None

    def _on_tts_requested(self, text: str):
        """Handle TTS request from popup.

        Opens the TTS Window with the provided text for speech synthesis.

        Args:
            text: Text to convert to speech (from input field or selected text)
        """
        logging.debug(f'TTS requested for text: "{text[:50]}..."')

        from .core import GUICoordinator

        GUICoordinator.get_instance().request_tts_window(
            config=self.config, ai_params=self.ai_params, key_managers=self.key_managers, initial_text=text
        )

    def _on_direct_chat(self, user_input: str, response_mode: str = "default", profile_override: Optional[str] = None):
        """
        Handle direct chat input (no selected text).

        Args:
            user_input: The user's chat input
            response_mode: Response mode ("default", "copy", "replace", or "show")
            profile_override: Optional model profile name to override for this request
        """
        logging.debug(f"Direct chat input: {user_input[:50]}..., mode: {response_mode}, profile: {profile_override}")

        self._begin_task()

        threading.Thread(
            target=self._process_direct_chat, args=(user_input, response_mode, profile_override), daemon=True
        ).start()

    def _on_request_compare_text(self, on_captured, on_cancelled):
        """
        Handle request for a second text selection (compare mode).

        Shows a toast notification instructing the user to select text and
        press Ctrl+C. Listens for Ctrl+C via pynput, reads the clipboard
        after a short delay, then invokes on_captured/on_cancelled on the
        GUI thread (via GUICoordinator.run_on_gui_thread) to avoid the
        "main thread is not in main loop" Tkinter error.

        Args:
            on_captured: Callable[[str], None] - called with the second text
            on_cancelled: Callable[[], None] - called if no text was captured
        """
        import pyperclip
        from pynput import keyboard as pykeyboard

        from .core import GUICoordinator

        TIMEOUT_SECS = 20

        logging.debug("[TextEditTool] Compare mode: waiting for Ctrl+C with second text...")

        # Show user instruction via toast notification
        GUICoordinator.get_instance().request_toast_notification(
            title="Compare Mode — Select 2nd text",
            message=f"Select text, press Ctrl+C to confirm  •  Esc to cancel  •  ({TIMEOUT_SECS}s timeout)",
            timeout_ms=TIMEOUT_SECS * 1000,
        )

        captured = [False]
        ctrl_held = [False]
        _listener_ref = [None]

        def _finish(text_or_none):
            """Call on_captured/on_cancelled safely on the GUI thread."""
            if captured[0]:
                return
            captured[0] = True
            if _listener_ref[0]:
                try:
                    _listener_ref[0].stop()
                except Exception:
                    pass

            # Dismiss the toast notification
            GUICoordinator.get_instance().request_dismiss_toast_notification()

            if text_or_none:
                logging.debug(f'[TextEditTool] Compare text captured: "{text_or_none[:50]}..."')
                print(f"[TextEditTool] Compare text captured ({len(text_or_none)} chars)")
                GUICoordinator.get_instance().run_on_gui_thread(lambda: on_captured(text_or_none))
            else:
                logging.debug("[TextEditTool] Compare mode: cancelled / timed out")
                print("[TextEditTool] Compare mode: cancelled - no second text captured")
                GUICoordinator.get_instance().run_on_gui_thread(on_cancelled)

        def _on_press(key):
            try:
                # Escape cancels the compare mode
                if key == pykeyboard.Key.esc:
                    logging.debug("[TextEditTool] Compare mode cancelled by Escape")
                    _finish(None)
                    return False  # Stop listener

                if key in (pykeyboard.Key.ctrl_l, pykeyboard.Key.ctrl_r):
                    ctrl_held[0] = True
                    return

                # Detect C key (char 'c' or control-char '\x03') while Ctrl held
                is_c = False
                try:
                    if key.char in ("c", "\x03"):
                        is_c = True
                except AttributeError:
                    pass

                if is_c and ctrl_held[0]:
                    # Ctrl+C detected — read clipboard after OS has updated it
                    def _delayed_read():
                        time.sleep(0.15)  # Give OS time to copy selection
                        try:
                            text = pyperclip.paste()
                        except Exception:
                            text = ""
                        _finish(text.strip() or None)

                    threading.Thread(target=_delayed_read, daemon=True).start()
                    return False  # Stop listener
            except Exception as e:
                logging.error(f"[TextEditTool] Compare key listener error: {e}")

        def _on_release(key):
            if key in (pykeyboard.Key.ctrl_l, pykeyboard.Key.ctrl_r):
                ctrl_held[0] = False

        listener = pykeyboard.Listener(on_press=_on_press, on_release=_on_release)
        _listener_ref[0] = listener
        listener.start()

        # Timeout fallback
        def _timeout():
            time.sleep(TIMEOUT_SECS)
            _finish(None)

        threading.Thread(target=_timeout, daemon=True).start()

    def _on_option_selected(
        self,
        option_key: str,
        selected_text: str,
        custom_input: Optional[str],
        response_mode: str = "default",
        active_modifiers: list | None = None,
        compare_text: Optional[str] = None,
        profile_override: Optional[str] = None,
    ):
        """
        Handle option selection from popup.

        Args:
            option_key: The selected option key
            selected_text: The selected text
            custom_input: Custom input text (for Custom option)
            response_mode: Response mode ("default", "replace", or "show")
            active_modifiers: List of active modifier keys
            compare_text: Optional second text for compare mode
            profile_override: Optional model profile name to override for this request
        """
        if active_modifiers is None:
            active_modifiers = []

        logging.debug(
            f"Option selected: {option_key}, mode: {response_mode}, modifiers: {active_modifiers}, compare={bool(compare_text)}, profile: {profile_override}"
        )

        self._begin_task()

        threading.Thread(
            target=self._process_option,
            args=(
                option_key,
                selected_text,
                custom_input,
                response_mode,
                active_modifiers,
                compare_text,
                profile_override,
            ),
            daemon=True,
        ).start()

    def _call_api(
        self,
        messages,
        provider=None,
        model=None,
        on_chunk=None,
        origin_override=None,
        action_config=None,
        abort_event=None,
    ):
        """
        Call the AI API with streaming support when enabled.

        Args:
            messages: API messages
            provider: Optional provider override
            model: Optional model override
            on_chunk: Optional callback for each text chunk (for real-time typing)
            origin_override: Optional RequestOrigin override
            action_config: Optional action config dict (may contain connection_profile)
            abort_event: Optional threading.Event to abort the request
        """
        from ..profile_resolver import resolve_profile
        from ..request_pipeline import RequestContext, RequestOrigin, RequestPipeline, StreamCallback
        from ..session_manager import ChatSession

        # Resolve profile overrides from action config
        resolved = resolve_profile(action_config, self.config, self.ai_params, self.key_managers)

        if not provider:
            provider = resolved.provider

        streaming_enabled = resolved.config.get("streaming_enabled", True)

        # Determine origin
        origin = origin_override or RequestOrigin.POPUP_INPUT

        # Setup context
        ctx = RequestContext(
            origin=origin,
            provider=provider,
            model=model or resolved.model,
            streaming=streaming_enabled,
            thinking_enabled=resolved.thinking_enabled,
        )

        if streaming_enabled:
            # Create a temporary session (uses current config, not stored provider/model)
            session = ChatSession(origin="textedit")
            # Add messages directly
            for msg in messages:
                session.messages.append({"role": msg["role"], "content": msg["content"]})

            # Setup callbacks
            def on_text(content):
                if on_chunk:
                    on_chunk(content)
                else:
                    # Print streaming to console only if no handler
                    print(content, end="", flush=True)

            def on_done():
                if not on_chunk:
                    print()  # Newline after streaming

            callbacks = StreamCallback(on_text=on_text, on_done=on_done)

            ctx = RequestPipeline.execute_streaming(
                ctx,
                session,
                resolved.config,
                resolved.ai_params,
                resolved.key_managers,
                callbacks,
                abort_event=abort_event,
            )

            if self.cancel_requested:
                return None, "Request cancelled"

            return ctx.response_text, ctx.error
        else:
            # Non-streaming
            ctx = RequestPipeline.execute_simple(
                ctx, messages, resolved.config, resolved.ai_params, resolved.key_managers, abort_event=abort_event
            )

            if self.cancel_requested:
                return None, "Request cancelled"

            return ctx.response_text, ctx.error

    def _start_abort_listener(self, abort_event=None):
        """
        Start listening for abort hotkey (e.g., Escape).
        When pressed, sets streaming_aborted flag and provides immediate feedback.
        Also unlocks the hotkey so new triggers can work immediately.

        Args:
            abort_event: Optional threading.Event to set on abort (for cancelling API calls)
        """
        from pynput import keyboard as pykeyboard

        self.streaming_aborted = False
        self._current_abort_event = abort_event

        # Parse abort hotkey to pynput key
        abort_key = self._parse_hotkey(self.abort_hotkey)

        def on_press(key):
            if self._key_matches(key, abort_key):
                self.streaming_aborted = True
                self.cancel_requested = True
                if self._current_abort_event:
                    self._current_abort_event.set()
                logging.debug("Abort hotkey pressed - stopping stream")

                # Provide immediate visual feedback
                from .core import dismiss_typing_indicator

                dismiss_typing_indicator()
                print("\n⚠️ Streaming aborted by user")

                return False  # Stop listener

        self._abort_listener = pykeyboard.Listener(on_press=on_press)
        self._abort_listener.start()

    def _stop_abort_listener(self):
        """Stop the abort hotkey listener."""
        if self._abort_listener:
            try:
                self._abort_listener.stop()
            except Exception:
                pass
            self._abort_listener = None
        self._current_abort_event = None

    def _parse_hotkey(self, hotkey_str: str):
        """Parse hotkey string to pynput key."""
        from pynput import keyboard as pykeyboard

        key_map = {
            "escape": pykeyboard.Key.esc,
            "esc": pykeyboard.Key.esc,
            "f1": pykeyboard.Key.f1,
            "f2": pykeyboard.Key.f2,
            "f3": pykeyboard.Key.f3,
            "f4": pykeyboard.Key.f4,
            "f5": pykeyboard.Key.f5,
            "f6": pykeyboard.Key.f6,
            "f7": pykeyboard.Key.f7,
            "f8": pykeyboard.Key.f8,
            "f9": pykeyboard.Key.f9,
            "f10": pykeyboard.Key.f10,
            "f11": pykeyboard.Key.f11,
            "f12": pykeyboard.Key.f12,
            "pause": pykeyboard.Key.pause,
            "break": pykeyboard.Key.pause,
            "scroll_lock": pykeyboard.Key.scroll_lock,
        }

        key_lower = hotkey_str.lower().strip()
        return key_map.get(key_lower, pykeyboard.Key.esc)

    def _key_matches(self, pressed_key, target_key):
        """Check if pressed key matches target."""
        try:
            return pressed_key == target_key
        except Exception:
            return False

    def _type_text_chunk(self, text: str) -> bool:
        """
        Insert text chunk using keyboard typing with rate limiting.
        Used for STREAMING mode only - types character by character.
        Avoids clipboard to prevent filling clipboard managers.
        Uses configurable delay between characters for stability.

        Newlines are sent as Shift+Enter to avoid triggering form submissions
        in applications like chat inputs, Discord, etc.

        Args:
            text: Text to type

        Returns:
            True if successful, False if aborted
        """
        import time

        from pynput import keyboard as pykeyboard

        try:
            keyboard = pykeyboard.Controller()

            # Delay per character (0 = no limit)
            char_delay = self.typing_delay_ms / 1000.0

            # Type each character with configured delay
            for char in text:
                # Check abort flag
                if self.streaming_aborted:
                    logging.debug("Typing aborted by user")
                    return False

                # Handle newlines with Shift+Enter to avoid form submissions
                if char == "\n":
                    keyboard.press(pykeyboard.Key.shift)
                    keyboard.press(pykeyboard.Key.enter)
                    keyboard.release(pykeyboard.Key.enter)
                    keyboard.release(pykeyboard.Key.shift)
                elif char == "\r":
                    # Skip carriage return (Windows line endings)
                    continue
                else:
                    keyboard.type(char)

                if char_delay > 0:
                    time.sleep(char_delay)

            # Small delay after chunk for application responsiveness
            if self.typing_delay_ms > 0:
                time.sleep(0.01)

            return True

        except Exception as e:
            logging.error(f"Error typing text chunk: {e}")
            return False

    def _paste_text_instant(self, text: str) -> bool:
        """
        Paste text instantly using clipboard.
        Used for NON-STREAMING mode - pastes all text at once.

        This is faster than character-by-character typing and provides
        a better user experience when streaming is disabled.

        Args:
            text: The text to paste

        Returns:
            True if successful, False otherwise
        """
        import time

        import pyperclip

        if not text:
            return False

        # Backup current clipboard
        try:
            clipboard_backup = pyperclip.paste()
        except Exception:
            clipboard_backup = ""

        try:
            # Clean and copy new text to clipboard
            cleaned_text = text.rstrip("\n")
            pyperclip.copy(cleaned_text)

            # Small delay to ensure clipboard is updated
            time.sleep(0.05)

            # Paste using SendInput with VK codes
            # (avoids Caps Lock / keyboard layout issues with pynput)
            self.text_handler._send_paste_keystroke()

            # Wait for paste to complete
            time.sleep(0.1)

            # Restore original clipboard
            pyperclip.copy(clipboard_backup)

            logging.debug(f"Pasted {len(cleaned_text)} chars instantly")
            return True

        except Exception as e:
            logging.error(f"Error pasting text: {e}")
            # Try to restore clipboard
            try:
                pyperclip.copy(clipboard_backup)
            except Exception:
                pass
            return False

    def _resolve_followup_system_instruction(self, session_origin: str) -> str:
        """
        Resolve the system instruction for follow-up messages based on session origin.

        When chat_use_origin_system_prompt is enabled, looks up the action's system_prompt
        from prompts.json. Otherwise falls back to chat_window_system_instruction.

        Args:
            session_origin: The session origin string (e.g., "textedit:Explain", "directchat")

        Returns:
            The resolved system instruction string
        """
        use_origin = self.config.get("chat_use_origin_system_prompt", True)

        if use_origin:
            resolved = self.prompts.get_system_prompt_for_origin(session_origin)
            if resolved:
                return resolved

        # Fallback to global chat_window_system_instruction
        return self.prompts.get_chat_window_system_instruction()

    def _copy_to_clipboard_with_notification(self, messages, action_key="AI Response", action_config=None):
        """Execute non-streaming request, copy result to clipboard, show notification.

        Args:
            messages: API messages to send
            action_key: Label for logging and notification
            action_config: Optional action config dict (may contain connection_profile)
        """
        import pyperclip

        from ..profile_resolver import resolve_profile
        from ..request_pipeline import RequestContext, RequestOrigin, RequestPipeline

        resolved = resolve_profile(action_config, self.config, self.ai_params, self.key_managers)

        ctx = RequestContext(
            origin=RequestOrigin.POPUP_INPUT,
            provider=resolved.provider,
            model=resolved.model,
            streaming=False,  # Must be non-streaming for copy mode
            thinking_enabled=resolved.thinking_enabled,
        )

        ctx = RequestPipeline.execute_simple(ctx, messages, resolved.config, resolved.ai_params, resolved.key_managers)

        if ctx.error:
            logging.error(f"Copy mode request failed: {ctx.error}")
            print(f"  [Error] {ctx.error}")
            from .popups import show_error_popup

            show_error_popup(
                title="API Request Failed", message="Failed to get AI response for copy.", details=ctx.error
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
                    title=f"{action_key}", message=ctx.response_text
                )

                print(f"  \u2705 Copied to clipboard ({len(ctx.response_text)} chars)")
            except Exception as e:
                logging.error(f"Failed to copy to clipboard: {e}")
                print(f"  [Error] Failed to copy: {e}")

    def _process_direct_chat(
        self, user_input: str, response_mode: str = "default", profile_override: Optional[str] = None
    ):
        """
        Process direct chat input.

        Args:
            user_input: The user's chat input
            response_mode: Response mode ("default", "copy", "replace", or "show")
                - "show": Force show in chat window
                - "copy": Copy response to clipboard
                - "replace": Force type to active field
                - "default": Use show_ai_response_in_chat_window config setting
            profile_override: Optional model profile name to override for this request
        """
        self.cancel_requested = False
        try:
            from ..messages import build_text_message

            # Get system instruction from settings
            chat_system_instruction = self._get_setting("chat_system_instruction", "You are a helpful AI assistant.")

            messages = build_text_message(user_input, chat_system_instruction)

            # Build action config for profile override (direct chat has no action config)
            action_config = {"connection_profile": profile_override} if profile_override else None

            # Store action config for profile resolution in streaming paths
            self._current_action_config = action_config

            # Resolve profile early for streaming decision (respects profile override)
            from ..profile_resolver import resolve_profile

            resolved = resolve_profile(action_config, self.config, self.ai_params, self.key_managers)

            # Session origin for direct chat (no text selected)
            session_origin = "directchat"

            # Determine display mode based on hierarchy:
            # 1. Radio button (if not "default")
            # 2. "Custom" action setting from text_edit_tool_options.json
            # 3. Config setting show_ai_response_in_chat_window
            if response_mode == "show":
                show_gui = True
            elif response_mode == "copy":
                show_gui = None  # Handled separately below
            elif response_mode == "replace":
                show_gui = False
            else:  # "default"
                # For direct chat, strictly use global config
                show_gui = self.config.get("show_ai_response_in_chat_window", False)

            # Resolve followup system instruction based on origin
            followup_system_instruction = self._resolve_followup_system_instruction(session_origin)

            if response_mode == "copy":
                # Copy mode: non-streaming request, copy result to clipboard
                print(f"\n{'\u2500' * 60}")
                print("[AI Response] Copying to clipboard...")

                self._copy_to_clipboard_with_notification(messages, action_key="AI Chat", action_config=action_config)

                print(f"{'\u2500' * 60}\n")
            elif show_gui:
                # Stream directly into chat window for real-time display
                streaming_enabled = resolved.config.get("streaming_enabled", True)

                print(f"\n{'─' * 60}")
                print(f"[AI Response] Opening chat window{'...' if streaming_enabled else ' (non-streaming)...'}")

                from ..request_pipeline import RequestOrigin

                if streaming_enabled:
                    # Streaming mode: open window immediately and stream content into it
                    self._stream_to_chat_window(
                        messages=messages,
                        window_title="AI Chat",
                        origin=RequestOrigin.POPUP_INPUT,
                        session_origin=session_origin,
                        followup_system_instruction=followup_system_instruction,
                    )
                else:
                    # Non-streaming: wait for response, then show window
                    response, error = self._call_api(
                        messages, origin_override=RequestOrigin.POPUP_INPUT, action_config=action_config
                    )

                    if error:
                        logging.error(f"Direct chat failed: {error}")
                        print(f"  [Error] {error}")

                        from .popups import show_error_popup

                        show_error_popup(
                            title="API Request Failed",
                            message="Failed to get response from AI provider.",
                            details=error,
                        )
                        return

                    if response:
                        self._show_chat_window(
                            messages=messages,
                            response=response,
                            window_title="AI Chat",
                            session_origin=session_origin,
                            followup_system_instruction=followup_system_instruction,
                        )

                print(f"{'─' * 60}\n")
            else:
                # Replace mode: type response to active field
                streaming_enabled = resolved.config.get("streaming_enabled", True)

                if streaming_enabled:
                    print(f"[AI Response] Streaming to active field... [{self.abort_hotkey.title()} to abort]")

                    # Start abort listener and typing indicator
                    self._start_abort_listener()
                    from .core import dismiss_typing_indicator, show_typing_indicator

                    show_typing_indicator(self.abort_hotkey)

                    # Buffer to accumulate chunks before typing (helps with Unicode)
                    chunk_buffer = []
                    buffer_size = 0
                    MIN_BUFFER_CHARS = 20  # Accumulate at least 20 chars before typing
                    typing_aborted = False

                    def type_chunk(chunk):
                        """Buffer chunks and type when buffer is large enough"""
                        nonlocal chunk_buffer, buffer_size, typing_aborted

                        # Check if aborted
                        if self.streaming_aborted or typing_aborted:
                            return

                        chunk_buffer.append(chunk)
                        buffer_size += len(chunk)

                        # Type when buffer reaches minimum size
                        if buffer_size >= MIN_BUFFER_CHARS:
                            text_to_type = "".join(chunk_buffer)
                            chunk_buffer.clear()
                            buffer_size = 0
                            if not self._type_text_chunk(text_to_type):
                                typing_aborted = True

                    try:
                        from ..request_pipeline import RequestOrigin

                        response, error = self._call_api(
                            messages,
                            on_chunk=type_chunk,
                            origin_override=RequestOrigin.POPUP_INPUT,
                            action_config=action_config,
                        )

                        # Type any remaining buffered text (unless aborted)
                        if chunk_buffer and not self.streaming_aborted and not typing_aborted:
                            self._type_text_chunk("".join(chunk_buffer))
                    finally:
                        # Always clean up abort listener and indicator
                        self._stop_abort_listener()
                        dismiss_typing_indicator()

                    # Note: Abort message is now shown immediately in _start_abort_listener
                    # so we don't need to show it again here
                else:
                    # Non-streaming: get full response then paste instantly
                    from ..request_pipeline import RequestOrigin

                    print(f"[AI Response] Processing... [{self.abort_hotkey.title()} to abort]")

                    abort_event = threading.Event()
                    self._start_abort_listener(abort_event)
                    from .core import dismiss_typing_indicator, show_typing_indicator

                    show_typing_indicator(self.abort_hotkey)

                    try:
                        response, error = self._call_api(
                            messages,
                            origin_override=RequestOrigin.POPUP_INPUT,
                            action_config=action_config,
                            abort_event=abort_event,
                        )
                    finally:
                        self._stop_abort_listener()
                        dismiss_typing_indicator()

                    if self.streaming_aborted:
                        return

                    # Paste the full response instantly using clipboard
                    if response and not error:
                        print("[Pasting to active field...]")
                        self._paste_text_instant(response)

                if error:
                    logging.error(f"Direct chat failed: {error}")
                    print(f"  [Error] {error}")

                    # Show error popup to user
                    from .popups import show_error_popup

                    show_error_popup(
                        title="API Request Failed", message="Failed to get response from AI provider.", details=error
                    )
                    return

                if streaming_enabled and not self.streaming_aborted:
                    print(f"\n✅ Response streamed ({len(response) if response else 0} chars)")
                elif not streaming_enabled:
                    print(f"✅ Response pasted ({len(response) if response else 0} chars)")

        except Exception as e:
            logging.error(f"Error in direct chat: {e}")
        finally:
            self._end_task()

    def _process_option(
        self,
        option_key: str,
        selected_text: str,
        custom_input: Optional[str],
        response_mode: str = "default",
        active_modifiers: list | None = None,
        compare_text: Optional[str] = None,
        profile_override: Optional[str] = None,
    ):
        """
        Process the selected option.

        Args:
            option_key: The selected option key (including "Custom" and "_Ask")
            selected_text: The selected text
            custom_input: Custom input text (for Custom edit or _Ask question)
            response_mode: Response mode ("default", "copy", "replace", or "show")
            active_modifiers: List of active modifier keys
            compare_text: Optional second text for compare mode

        Display Mode Override Hierarchy:
            1. response_mode from popup radio button (if not "default")
            2. Modifiers with forces_chat_window=true
            3. show_chat_window_instead_of_replace per-action setting
            4. Falls back to False (replace mode)

        Prompt Structure (single text):
            SYSTEM: {system_prompt}
                    {modifier_injections}
            USER: {task}
                   {base_output_rules}
                   {text_delimiter}
                   {selected_text}
                   {text_delimiter_close}

        Prompt Structure (compare mode):
            Uses build_text_comparison_message() with both texts.

        Both "Custom" and "_Ask" use the same pattern:
            - Get action options from config (system_prompt, prompt_type, show_chat_window_instead_of_replace)
            - Use task template with {custom_input} placeholder
            - "Custom" uses custom_task_template, "_Ask" uses ask_task_template
        """
        if active_modifiers is None:
            active_modifiers = []

        self.cancel_requested = False
        try:
            action_options = self._get_action_options()
            option = action_options.get(option_key, {})

            # Apply popup-level profile override (takes priority over action's connection_profile)
            if profile_override:
                option = dict(option)  # Don't mutate the original
                option["connection_profile"] = profile_override

            # Store action config for profile resolution in streaming paths
            self._current_action_config = option

            # Resolve profile early for streaming_enabled checks
            from ..profile_resolver import resolve_profile

            resolved = resolve_profile(option, self.config, self.ai_params, self.key_managers)
            # Get modifier definitions from global settings
            modifier_defs = self.prompts.get_modifiers()

            # Check if any active modifier forces chat window
            forces_chat_window = self._modifiers_force_chat_window(active_modifiers, modifier_defs)

            # Compare mode always shows in chat window
            is_compare_mode = bool(compare_text)

            # Determine if this should open in a window based on response mode
            # Hierarchy: radio button > compare mode > modifiers > per-action setting > default (False)
            if response_mode == "show":
                show_in_chat_window = True
            elif response_mode == "copy":
                show_in_chat_window = None  # Handled separately below
            elif response_mode == "replace":
                show_in_chat_window = False
            elif is_compare_mode:
                show_in_chat_window = True  # Compare mode always shows result in chat window
            elif forces_chat_window:
                show_in_chat_window = True
            else:  # "default" - use the action's setting
                show_in_chat_window = option.get("show_chat_window_instead_of_replace", False)

            # Build prompt using new structure
            # Keys: system_prompt, task, prompt_type
            system_prompt = option.get("system_prompt", "")
            task = option.get("task", "")

            # Inject modifier prompts into system prompt
            if active_modifiers:
                modifier_injections = self._build_modifier_injections(active_modifiers, modifier_defs)
                if modifier_injections:
                    system_prompt = system_prompt + "\n\n" + modifier_injections

            # Get prompt type (default to "edit")
            # "edit" prompts use base_output_rules_edit (strict, no explanations)
            # "general" prompts use base_output_rules_general (more permissive)
            prompt_type = option.get("prompt_type", "edit")

            # Select output rules based on prompt type
            if prompt_type == "general":
                base_output_rules = self._get_setting("base_output_rules_general", "")
            else:
                base_output_rules = self._get_setting("base_output_rules_edit", "")

            text_delimiter = self._get_setting("text_delimiter", "\n\n<text_to_process>\n")
            text_delimiter_close = self._get_setting("text_delimiter_close", "\n</text_to_process>")

            # Handle _Custom action - use custom_task_template
            if option_key == "_Custom" and custom_input:
                custom_task_template = self._get_setting(
                    "custom_task_template", "Apply the following change to the text: {custom_input}"
                )
                task = custom_task_template.format(custom_input=custom_input)

            # Handle _Ask action - use ask_task_template (same pattern as Custom)
            elif option_key == "_Ask" and custom_input:
                ask_task_template = self._get_setting(
                    "ask_task_template", "Answer the following question about the text: {custom_input}"
                )
                task = ask_task_template.format(custom_input=custom_input)

            # Build messages - compare mode uses dual-text structure
            if is_compare_mode:
                from ..messages import build_text_comparison_message

                # Build combined task (include output rules in task for comparison)
                task_with_rules = task
                if base_output_rules:
                    task_with_rules = task + "\n\n" + base_output_rules

                messages = build_text_comparison_message(
                    text1=selected_text, text2=compare_text, task=task_with_rules, system_prompt=system_prompt
                )

                logging.debug(
                    f"[TextEditTool] Compare mode: {option_key} on {len(selected_text)}+{len(compare_text)} chars"
                )
                print(f"[TextEditTool] Compare mode: {len(selected_text)} vs {len(compare_text)} chars")
            else:
                # Build user message: task + output rules + delimiter + text
                user_message_parts = []
                if task:
                    user_message_parts.append(task)
                if base_output_rules:
                    user_message_parts.append(base_output_rules)

                user_message = "\n\n".join(user_message_parts)
                user_message += text_delimiter + selected_text + text_delimiter_close

                from ..messages import build_text_message

                messages = build_text_message(user_message, system_prompt)

            logging.debug(f"Getting AI response for {option_key}")

            from ..request_pipeline import RequestOrigin

            # Determine session origin for tracking
            session_origin = f"textedit:{option_key}"

            # Resolve followup system instruction based on origin
            followup_system_instruction = self._resolve_followup_system_instruction(session_origin)

            if response_mode == "copy":
                # Copy mode: non-streaming request, copy result to clipboard
                print(f"\n{'\u2500' * 60}")
                print("[AI Response] Copying to clipboard...")

                self._copy_to_clipboard_with_notification(messages, action_key=option_key, action_config=option)

                print(f"{'\u2500' * 60}\n")
            elif show_in_chat_window:
                # Stream directly into chat window for real-time display
                streaming_enabled = resolved.config.get("streaming_enabled", True)

                print(f"\n{'─' * 60}")
                print(f"[AI Response] Opening chat window{'...' if streaming_enabled else ' (non-streaming)...'}")

                if streaming_enabled:
                    # Streaming mode: open window immediately and stream content into it
                    self._stream_to_chat_window(
                        messages=messages,
                        window_title=f"{option_key} Result",
                        origin=RequestOrigin.POPUP_PROMPT,
                        session_origin=session_origin,
                        followup_system_instruction=followup_system_instruction,
                    )
                else:
                    # Non-streaming: wait for response, then show window
                    response, error = self._call_api(
                        messages, origin_override=RequestOrigin.POPUP_PROMPT, action_config=option
                    )

                    if error:
                        logging.error(f"Option processing failed: {error}")
                        print(f"  [Error] {error}")

                        from .popups import show_error_popup

                        show_error_popup(
                            title=f"'{option_key}' Failed", message="Failed to process your request.", details=error
                        )
                        return

                    if not response:
                        logging.error("No response from AI")
                        return

                    # Show chat window with response
                    self._show_chat_window(
                        messages=messages,
                        response=response,
                        window_title=f"{option_key} Result",
                        session_origin=session_origin,
                        followup_system_instruction=followup_system_instruction,
                    )

                print(f"{'─' * 60}\n")
            else:
                # Replace mode: type response to active field (same as direct chat)
                streaming_enabled = resolved.config.get("streaming_enabled", True)

                if streaming_enabled:
                    print(f"[AI Response] Streaming to active field... [{self.abort_hotkey.title()} to abort]")

                    # Start abort listener and typing indicator
                    self._start_abort_listener()
                    from .core import dismiss_typing_indicator, show_typing_indicator

                    show_typing_indicator(self.abort_hotkey)

                    # Buffer to accumulate chunks before typing (helps with Unicode)
                    chunk_buffer = []
                    buffer_size = 0
                    MIN_BUFFER_CHARS = 20  # Accumulate at least 20 chars before typing
                    typing_aborted = False

                    def type_chunk(chunk):
                        """Buffer chunks and type when buffer is large enough"""
                        nonlocal chunk_buffer, buffer_size, typing_aborted

                        # Check if aborted
                        if self.streaming_aborted or typing_aborted:
                            return

                        chunk_buffer.append(chunk)
                        buffer_size += len(chunk)

                        # Type when buffer reaches minimum size
                        if buffer_size >= MIN_BUFFER_CHARS:
                            text_to_type = "".join(chunk_buffer)
                            chunk_buffer.clear()
                            buffer_size = 0
                            if not self._type_text_chunk(text_to_type):
                                typing_aborted = True

                    try:
                        response, error = self._call_api(
                            messages,
                            on_chunk=type_chunk,
                            origin_override=RequestOrigin.POPUP_PROMPT,
                            action_config=option,
                        )

                        # Type any remaining buffered text (unless aborted)
                        if chunk_buffer and not self.streaming_aborted and not typing_aborted:
                            self._type_text_chunk("".join(chunk_buffer))
                    finally:
                        # Always clean up abort listener and indicator
                        self._stop_abort_listener()
                        dismiss_typing_indicator()

                    # Note: Abort message is now shown immediately in _start_abort_listener
                    # so we don't need to show it again here
                else:
                    # Non-streaming: get full response then paste instantly
                    print(f"[AI Response] Processing... [{self.abort_hotkey.title()} to abort]")

                    abort_event = threading.Event()
                    self._start_abort_listener(abort_event)
                    from .core import dismiss_typing_indicator, show_typing_indicator

                    show_typing_indicator(self.abort_hotkey)

                    try:
                        response, error = self._call_api(
                            messages,
                            origin_override=RequestOrigin.POPUP_PROMPT,
                            action_config=option,
                            abort_event=abort_event,
                        )
                    finally:
                        self._stop_abort_listener()
                        dismiss_typing_indicator()

                    if self.streaming_aborted:
                        # Skip paste, update status message below
                        pass
                    elif response and not error:
                        print("[Pasting to active field...]")
                        self._paste_text_instant(response)

                if error:
                    logging.error(f"Option processing failed: {error}")
                    print(f"  [Error] {error}")

                    # Show error popup to user
                    from .popups import show_error_popup

                    show_error_popup(
                        title=f"'{option_key}' Failed", message="Failed to process your request.", details=error
                    )
                    return

                if not response:
                    logging.error("No response from AI")
                    return

                if streaming_enabled and not self.streaming_aborted:
                    print(f"\n✅ Response streamed ({len(response) if response else 0} chars)")
                elif not streaming_enabled:
                    print(f"✅ Response pasted ({len(response) if response else 0} chars)")

        except Exception as e:
            logging.error(f"Error processing option: {e}")
        finally:
            self._end_task()

    def _build_modifier_injections(self, active_modifiers: list, modifier_defs: list) -> str:
        """
        Build modifier injection text to append to system prompt.

        Args:
            active_modifiers: List of active modifier keys
            modifier_defs: List of modifier definitions from settings

        Returns:
            Combined injection text from all active modifiers
        """
        injections = []
        for mod in modifier_defs:
            if mod.get("key") in active_modifiers:
                injection = mod.get("injection", "")
                if injection:
                    injections.append(injection)

        return "\n".join(injections)

    def _modifiers_force_chat_window(self, active_modifiers: list, modifier_defs: list) -> bool:
        """
        Check if any active modifier forces chat window display.

        Args:
            active_modifiers: List of active modifier keys
            modifier_defs: List of modifier definitions from settings

        Returns:
            True if any active modifier has forces_chat_window=True
        """
        for mod in modifier_defs:
            if mod.get("key") in active_modifiers:
                if mod.get("forces_chat_window", False):
                    return True
        return False

    def _extract_user_content_from_messages(self, messages: list) -> str:
        """
        Extract user text content from API messages.

        Handles both string and multimodal (list) content formats.
        Preserves proper formatting for compare mode (<text_1>, <text_2> tags).

        Args:
            messages: API messages list (messages[0] is system, messages[1] is user)

        Returns:
            Extracted user text content
        """
        if len(messages) >= 2:
            user_content = messages[1].get("content", "")
            # Handle both string and list content formats
            if isinstance(user_content, list):
                # Multimodal content - extract text parts
                text_parts = [item.get("text", "") for item in user_content if item.get("type") == "text"]
                return text_parts[-1] if text_parts else ""
            else:
                return user_content
        return ""

    def _stream_to_chat_window(
        self,
        messages: list,
        window_title: str,
        origin,
        session_origin: str = "textedit",
        followup_system_instruction: Optional[str] = None,
    ):
        """
        Open a chat window immediately and stream API response into it.

        Args:
            messages: API messages to send (with the correct system prompt for initial request)
            window_title: Title for the chat window
            origin: RequestOrigin for logging
            session_origin: Origin string for session tracking (e.g., "textedit:Explain", "directchat")
            followup_system_instruction: System instruction to use for follow-up messages.
        """
        from ..request_pipeline import RequestContext, RequestPipeline, StreamCallback
        from ..session_manager import ChatSession
        from .core import GUICoordinator

        # Create session with user message already added
        session = ChatSession(origin=session_origin)
        session.title = window_title

        # Carry over profile override to the chat session
        action_config = getattr(self, "_current_action_config", None)
        if action_config and action_config.get("connection_profile"):
            session.profile_override = action_config["connection_profile"]

        # Extract user content from the already-built messages
        user_text = self._extract_user_content_from_messages(messages)
        if user_text:
            session.add_message("user", user_text)

        # Set system instruction for follow-up messages NOW (before request)
        # This ensures it's available for regeneration even if the initial request fails.
        # The initial request uses messages directly (with correct system prompt),
        # so this won't affect the initial request - only follow-ups and regeneration.
        if followup_system_instruction:
            session.system_instruction = followup_system_instruction
        else:
            # Fallback to global chat_window_system_instruction
            session.system_instruction = self.prompts.get_chat_window_system_instruction()

        # Request streaming chat window (opens immediately)
        callbacks = GUICoordinator.get_instance().request_streaming_chat_window(session)

        if not callbacks.on_text:
            logging.error("Failed to create streaming chat window")
            print("  [Error] Failed to create chat window")
            return

        # Accumulated response for finalization
        full_response = []
        full_thinking = []

        # Resolve profile from action_config if available
        from ..profile_resolver import resolve_profile

        resolved = resolve_profile(
            getattr(self, "_current_action_config", None), self.config, self.ai_params, self.key_managers
        )

        provider = resolved.provider

        # Setup context
        ctx = RequestContext(
            origin=origin,
            provider=provider,
            model=resolved.model,
            streaming=True,
            thinking_enabled=resolved.thinking_enabled,
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

        stream_callbacks = StreamCallback(on_text=on_text, on_thinking=on_thinking, on_done=on_done)

        # Execute streaming request using execute_unified_stream
        # This takes messages directly (with correct system prompt), not from session
        ctx = RequestPipeline.execute_unified_stream(
            ctx,
            messages,  # Use the original messages with correct system prompt
            resolved.config,
            resolved.ai_params,
            resolved.key_managers,
            stream_callbacks,
        )

        if ctx.error:
            logging.error(f"Streaming to chat window failed: {ctx.error}")
            print(f"  [Error] {ctx.error}")

            from .popups import show_error_popup

            show_error_popup(
                title="Request Failed", message="Failed to get response from AI provider.", details=ctx.error
            )
            return

        # NOW set the system instruction for follow-up messages (after initial request completed)
        if followup_system_instruction:
            session.system_instruction = followup_system_instruction
        else:
            # Fallback to global chat_window_system_instruction
            session.system_instruction = self.prompts.get_chat_window_system_instruction()

        # Finalize: add the complete message to session
        response_text = "".join(full_response) or ctx.response_text or ""
        thinking_text = "".join(full_thinking) or ctx.reasoning_text or ""

        callbacks.finalize(response_text, thinking_text)

        # Auto-save session if configured
        # Note: callbacks.finalize adds the assistant message, so session is ready to save
        self._handle_auto_save(session)

        print(f"  ✅ Response streamed to chat window ({len(response_text)} chars)")

    def _show_chat_window(
        self,
        messages: list,
        response: str,
        window_title: str,
        session_origin: str = "textedit",
        followup_system_instruction: Optional[str] = None,
    ):
        """
        Show the response in a chat window (non-streaming path).

        Args:
            messages: API messages (with the correct system prompt)
            response: AI response text
            window_title: Title for the chat window
            session_origin: Origin string for session tracking (e.g., "textedit:Explain")
            followup_system_instruction: System instruction to use for follow-up messages.
        """
        logging.debug("Showing chat window")

        # Import here to avoid circular dependency
        from ..session_manager import ChatSession
        from .core import show_chat_gui

        # Create a temporary session for this response
        session = ChatSession(origin=session_origin)
        session.title = window_title

        # Carry over profile override to the chat session
        action_config = getattr(self, "_current_action_config", None)
        if action_config and action_config.get("connection_profile"):
            session.profile_override = action_config["connection_profile"]

        # Extract user content from the already-built messages
        user_text = self._extract_user_content_from_messages(messages)
        if user_text:
            session.add_message("user", user_text)

        session.add_message("assistant", response)

        # Store system instruction for follow-up messages
        if followup_system_instruction:
            session.system_instruction = followup_system_instruction
        else:
            # Fallback to global chat_window_system_instruction
            session.system_instruction = self.prompts.get_chat_window_system_instruction()

        # Show the chat window
        show_chat_gui(session, initial_response=response)

        # Auto-save session if configured
        self._handle_auto_save(session)

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
            # Avoid circular import
            from ..session_manager import add_session

            add_session(session, self.config.get("max_sessions", 200))
            logging.debug(f"Auto-saved session {session.session_id} (mode: {auto_save})")

    def is_running(self) -> bool:
        """Check if TextEditTool is running."""
        return self.hotkey_listener is not None and self.hotkey_listener.is_running()

    def is_paused(self) -> bool:
        """Check if TextEditTool is paused."""
        return self.hotkey_listener is not None and self.hotkey_listener.is_paused()

    def is_copying(self) -> bool:
        """
        Check if TextHandler is currently performing a copy operation (Ctrl+C).
        Includes a grace period to catch delayed signals.
        """
        # Check active flag OR if we just copied in the last 200ms
        # This prevents race conditions where the thread finishes faster than the signal handler fires
        return self.text_handler.is_copying or (time.time() - self.text_handler.last_copy_time < 0.2)

    def get_status(self) -> Dict:
        """Get current status."""
        return {
            "enabled": self.enabled,
            "running": self.is_running(),
            "paused": self.is_paused(),
            "hotkey": self.hotkey,
            "processing": self.is_processing,
        }

    def reload_options(self):
        """
        Reload options from file without restart.
        This is called when the prompt editor saves changes.

        Note: Since we now read live from PromptsConfig singleton (like SnipTool),
        this just ensures the singleton is refreshed. All subsequent reads via
        _get_setting() and _get_action_options() will automatically return fresh data.
        """
        logging.info("Reloading TextEditTool options...")
        self.prompts.reload()
        print("[TextEditTool] PromptsConfig reloaded - live reads will reflect changes")


# Global reference for hot-reload
_TEXT_EDIT_TOOL_INSTANCE: Optional[TextEditToolApp] = None


def set_instance(app: TextEditToolApp):
    """Set the global TextEditTool instance for hot-reload access."""
    global _TEXT_EDIT_TOOL_INSTANCE
    _TEXT_EDIT_TOOL_INSTANCE = app


def get_instance() -> Optional[TextEditToolApp]:
    """Get the global TextEditTool instance."""
    return _TEXT_EDIT_TOOL_INSTANCE


def reload_options():
    """
    Reload TextEditTool options from file.
    Called by prompt_editor when saving.
    """
    if _TEXT_EDIT_TOOL_INSTANCE:
        _TEXT_EDIT_TOOL_INSTANCE.reload_options()
    else:
        print("[TextEditTool] No instance to reload options for")
