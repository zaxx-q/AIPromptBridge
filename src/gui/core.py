#!/usr/bin/env python3
"""
GUI core initialization and threading - CustomTkinter implementation

This module provides a centralized GUI coordinator that ensures all GUI
operations happen on a single dedicated GUI thread. This is necessary because
Tkinter/CustomTkinter is not thread-safe and doesn't support multiple CTk()
instances across different threads.

Architecture:
    - One dedicated GUI thread runs a single CTk() root with an event loop
    - All window creation requests go through a queue
    - The GUI thread processes the queue and creates windows as CTkToplevel
    - Background threads can safely request window creation without conflicts
    
CustomTkinter Migration Notes:
    - CTk() replaces tk.Tk() for modern appearance
    - CTkToplevel replaces tk.Toplevel
    - Appearance mode synced with theme config
    - Uses existing ThemeColors for widget styling
"""

import queue
import threading
import time
import tkinter as tk
from typing import Optional, Callable, Any
from dataclasses import dataclass, field

# Import CustomTkinter with fallback
from .platform import HAVE_CTK, ctk

# GUI is available if either tk or ctk works
HAVE_GUI = True

# Track open windows for status
OPEN_WINDOWS = set()
OPEN_WINDOWS_LOCK = threading.Lock()
WINDOW_COUNTER = 0
WINDOW_COUNTER_LOCK = threading.Lock()


@dataclass
class StreamingChatCallbacks:
    """
    Container for streaming chat window callbacks.
    
    Used to pass callbacks from GUI thread back to caller thread
    for real-time streaming updates to chat window.
    """
    on_text: Optional[Callable[[str], None]] = None
    on_thinking: Optional[Callable[[str], None]] = None
    on_done: Optional[Callable[[], None]] = None
    window: Any = None  # Reference to the AttachedChatWindow
    ready: threading.Event = field(default_factory=threading.Event)
    
    def finalize(self, response_text: str, thinking_text: str = ""):
        """
        Finalize streaming and add the complete message to session.
        Call this when streaming is complete to persist the message.
        """
        if self.window and not self.window._destroyed:
            def do_finalize():
                if self.window._destroyed:
                    return
                # Stop streaming mode
                self.window.is_streaming = False
                
                # Add assistant message to session IF NOT ALREADY THERE
                # Streaming handlers might have already added it to ensure persistence before autosave
                # Check for duplication carefully to avoid duplicate messages
                already_exists = False
                if self.window.session.messages:
                    last_msg = self.window.session.messages[-1]
                    if last_msg["role"] == "assistant" and last_msg["content"] == response_text:
                        already_exists = True
                
                if not already_exists:
                    self.window.session.add_message("assistant", response_text)
                
                # Always ensure thinking content is attached if available
                if thinking_text and len(self.window.session.messages) > 0:
                    self.window.session.messages[-1]["thinking"] = thinking_text
                
                # Auto-collapse thinking now that the message is in session
                # Must be computed AFTER add_message to get the correct index,
                # since callers (e.g. SnipTool) may add the message before
                # this deferred callback runs, causing an off-by-one.
                msg_idx = len(self.window.session.messages) - 1
                if msg_idx in self.window.thinking_collapsed_states:
                    self.window.thinking_collapsed_states[msg_idx] = True
                
                # Update last response for copy functionality
                self.window.last_response = response_text
                
                # Refresh display with final content
                self.window._update_chat_display(scroll_to_bottom=True)
                
                # Update status
                self.window._update_status("✅ Response received", self.window.theme.accent_green)
                
                # Reset streaming state
                self.window.streaming_text = ""
                self.window.streaming_thinking = ""
            
            self.window._safe_after(0, do_finalize)


def get_next_window_id():
    """Get next unique window ID"""
    global WINDOW_COUNTER
    with WINDOW_COUNTER_LOCK:
        WINDOW_COUNTER += 1
        return WINDOW_COUNTER


def register_window(window_tag):
    """Register a window as open"""
    with OPEN_WINDOWS_LOCK:
        OPEN_WINDOWS.add(window_tag)


def unregister_window(window_tag):
    """Unregister a window when closed"""
    with OPEN_WINDOWS_LOCK:
        OPEN_WINDOWS.discard(window_tag)


def has_open_windows():
    """Check if any windows are open"""
    with OPEN_WINDOWS_LOCK:
        return len(OPEN_WINDOWS) > 0


class GUICoordinator:
    """
    Centralized coordinator for all GUI operations.
    
    Ensures all Tkinter operations happen on a single dedicated thread,
    avoiding the threading issues that occur with multiple Tk() instances.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        self._root: Optional[tk.Tk] = None
        self._request_queue: queue.Queue = queue.Queue()
        self._running = False
        self._gui_thread: Optional[threading.Thread] = None
        self._started = threading.Event()
    
    @classmethod
    def get_instance(cls) -> 'GUICoordinator':
        """Get singleton instance"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def ensure_running(self):
        """Ensure the GUI thread is running"""
        if not self._running:
            with self._lock:
                if not self._running:
                    self._start_gui_thread()
                    # Wait for GUI thread to initialize
                    self._started.wait(timeout=5.0)
    
    def _start_gui_thread(self):
        """Start the dedicated GUI thread"""
        def run_gui():
            try:
                # Initialize CustomTkinter appearance mode from config
                if HAVE_CTK:
                    self._sync_appearance_mode()
                    self._root = ctk.CTk()
                else:
                    self._root = tk.Tk()
                
                self._root.withdraw()  # Hidden root window
                self._running = True
                self._started.set()
                
                # Main event loop
                while self._running:
                    # Process pending window creation requests
                    self._process_queue()
                    
                    # Update Tk event loop
                    try:
                        self._root.update()
                    except tk.TclError:
                        break
                    
                    time.sleep(0.01)  # ~100 FPS
                    
            except Exception as e:
                print(f"[GUICoordinator] Error in GUI thread: {e}")
            finally:
                self._running = False
                self._started.set()  # Unblock waiters
        
        self._gui_thread = threading.Thread(target=run_gui, daemon=True, name="GUI-Thread")
        self._gui_thread.start()
    
    def _sync_appearance_mode(self):
        """Sync CustomTkinter appearance mode with config."""
        if not HAVE_CTK:
            return
        
        try:
            from .. import web_server
            mode = web_server.CONFIG.get("ui_theme_mode", "auto")
            
            if mode == "auto":
                ctk.set_appearance_mode("system")
            elif mode == "light":
                ctk.set_appearance_mode("light")
            else:
                ctk.set_appearance_mode("dark")
        except (ImportError, AttributeError):
            # Fallback to system if config not available
            ctk.set_appearance_mode("system")
    
    def _process_queue(self):
        """Process pending window creation requests"""
        while not self._request_queue.empty():
            try:
                request = self._request_queue.get_nowait()
                request_type = request.get('type')
                
                if request_type == 'chat':
                    self._create_chat_window(request)
                elif request_type == 'browser':
                    self._create_browser_window(request)
                elif request_type == 'popup_input':
                    self._create_input_popup(request)
                elif request_type == 'popup_prompt':
                    self._create_prompt_popup(request)
                elif request_type == 'typing_indicator':
                    self._create_typing_indicator(request)
                elif request_type == 'dismiss_typing_indicator':
                    self._dismiss_typing_indicator()
                elif request_type == 'toast_notification':
                    self._create_toast_notification(request)
                elif request_type == 'dismiss_toast_notification':
                    self._dismiss_toast_notification()
                elif request_type == 'settings':
                    self._create_settings_window(request)
                elif request_type == 'prompt_editor':
                    self._create_prompt_editor_window(request)
                elif request_type == 'connection_manager':
                    self._create_connection_manager(request)
                elif request_type == 'error_popup':
                    self._create_error_popup(request)
                elif request_type == 'streaming_chat':
                    self._create_streaming_chat_window(request)
                elif request_type == 'snip_overlay':
                    self._create_snip_overlay(request)
                elif request_type == 'snip_popup':
                    self._create_snip_popup(request)
                elif request_type == 'audio_analyzer':
                    self._create_audio_analyzer_window(request)
                elif request_type == 'tts_window':
                    self._create_tts_window(request)
                elif request_type == 'onboarding':
                    self._create_onboarding_window(request)
                elif request_type == 'callback':
                    # Generic callback execution on GUI thread
                    callback = request.get('callback')
                    if callback:
                        try:
                            callback()
                        except Exception as e:
                            print(f"[GUICoordinator] Callback error: {e}")
                            
            except queue.Empty:
                break
            except Exception as e:
                print(f"[GUICoordinator] Error processing request: {e}")
    
    def _create_chat_window(self, request):
        """Create a chat window on the GUI thread"""
        from .windows import create_attached_chat_window
        session = request.get('session')
        initial_response = request.get('initial_response')
        if session:
            create_attached_chat_window(self._root, session, initial_response)
    
    def _create_browser_window(self, request):
        """Create a session browser window on the GUI thread"""
        from .windows import create_attached_browser_window
        create_attached_browser_window(self._root)
    
    def _create_input_popup(self, request):
        """Create an input popup on the GUI thread"""
        from .popups import create_attached_input_popup
        on_submit = request.get('on_submit')
        on_close = request.get('on_close')
        x = request.get('x')
        y = request.get('y')
        on_tts = request.get('on_tts')
        create_attached_input_popup(self._root, on_submit, on_close, x, y, on_tts)
    
    def _create_prompt_popup(self, request):
        """Create a prompt selection popup on the GUI thread"""
        from .popups import create_attached_prompt_popup
        options = request.get('options')
        on_option_selected = request.get('on_option_selected')
        on_close = request.get('on_close')
        selected_text = request.get('selected_text')
        x = request.get('x')
        y = request.get('y')
        on_tts = request.get('on_tts')
        on_request_compare_text = request.get('on_request_compare_text')
        create_attached_prompt_popup(self._root, options, on_option_selected, on_close, selected_text, x, y, on_tts, on_request_compare_text)
    
    def _create_typing_indicator(self, request):
        """Create a typing indicator on the GUI thread"""
        from .popups import create_typing_indicator
        abort_hotkey = request.get('abort_hotkey', 'Escape')
        on_dismiss = request.get('on_dismiss')
        create_typing_indicator(self._root, abort_hotkey, on_dismiss)
    
    def _dismiss_typing_indicator(self):
        """Dismiss the typing indicator on the GUI thread"""
        from .popups import dismiss_typing_indicator
        dismiss_typing_indicator()
    
    def _create_toast_notification(self, request):
        """Create a toast notification on the GUI thread"""
        from .popups import create_toast_notification
        title = request.get('title')
        message = request.get('message')
        timeout_ms = request.get('timeout_ms', 3000)
        create_toast_notification(self._root, title, message, timeout_ms)
    
    def _dismiss_toast_notification(self):
        """Dismiss the toast notification on the GUI thread"""
        from .popups import dismiss_toast_notification
        dismiss_toast_notification()
    
    def _create_settings_window(self, request):
        """Create a settings window on the GUI thread"""
        from .windows import create_attached_settings_window
        on_close = request.get('on_close')
        initial_tab = request.get('initial_tab')
        create_attached_settings_window(self._root, on_close, initial_tab)

    def _create_prompt_editor_window(self, request):
        """Create a prompt editor window on the GUI thread"""
        from .windows import create_attached_prompt_editor_window
        create_attached_prompt_editor_window(self._root)

    def _create_connection_manager(self, request):
        """Create a connection profile manager window on the GUI thread"""
        from .windows.connection_manager import create_attached_connection_manager
        on_close = request.get('on_close')
        create_attached_connection_manager(self._root, on_close)
    
    def _create_error_popup(self, request):
        """Create an error popup on the GUI thread"""
        from .popups import create_error_popup
        title = request.get('title', 'Error')
        message = request.get('message', 'An error occurred')
        details = request.get('details')
        create_error_popup(self._root, title, message, details)
    
    def _create_streaming_chat_window(self, request):
        """Create a chat window in streaming mode on the GUI thread"""
        from .windows import AttachedChatWindow
        
        session = request.get('session')
        callbacks = request.get('callbacks')
        
        if not session or not callbacks:
            if callbacks:
                callbacks.ready.set()
            return
        
        try:
            # Create window with no initial response
            window = AttachedChatWindow(self._root, session, initial_response=None)
            
            # Put window in streaming mode
            window.is_streaming = True
            window.streaming_text = ""
            window.streaming_thinking = ""
            
            # Show initial streaming indicator
            window._update_streaming_display()
            
            # Create callbacks for streaming updates
            def on_text(content):
                if window._destroyed:
                    return
                window.streaming_text += content
                window._safe_after(0, window._update_streaming_display)
            
            def on_thinking(content):
                if window._destroyed:
                    return
                window.streaming_thinking += content
                window._safe_after(0, window._update_streaming_display)
            
            def on_done():
                if window._destroyed:
                    return
                # Just update display, finalize() will be called separately
                window._safe_after(0, window._update_streaming_display)
            
            # Populate callbacks container
            callbacks.on_text = on_text
            callbacks.on_thinking = on_thinking
            callbacks.on_done = on_done
            callbacks.window = window
            
        except Exception as e:
            print(f"[GUICoordinator] Error creating streaming chat window: {e}")
        finally:
            # Signal that window is ready
            callbacks.ready.set()
    
    def _create_snip_overlay(self, request):
        """Create a screen snip overlay on the GUI thread"""
        from .screen_snip import ScreenSnipOverlay
        
        on_capture = request.get('on_capture')
        on_cancel = request.get('on_cancel')
        
        if on_capture and on_cancel:
            ScreenSnipOverlay(self._root, on_capture, on_cancel)
    
    def _create_snip_popup(self, request):
        """Create a snip popup on the GUI thread"""
        from .snip_popup import create_attached_snip_popup
        
        capture_result = request.get('capture_result')
        prompts_config = request.get('prompts_config')
        on_action = request.get('on_action')
        on_close = request.get('on_close')
        on_request_compare_capture = request.get('on_request_compare_capture')
        x = request.get('x')
        y = request.get('y')
        
        if capture_result and prompts_config and on_action:
            create_attached_snip_popup(
                self._root, capture_result, prompts_config,
                on_action, on_close, on_request_compare_capture, x, y
            )
    
    def _create_audio_analyzer_window(self, request):
        """Create an audio analyzer window on the GUI thread"""
        from .windows import create_audio_analyzer_window
        
        prompts_config = request.get('prompts_config')  # Actually 'config' from AudioToolApp
        on_action = request.get('on_action')  # Actually 'ai_params'
        on_close = request.get('on_close')    # Actually 'key_managers'
        
        # Proper parameter extraction
        config = request.get('config')
        ai_params = request.get('ai_params')
        key_managers = request.get('key_managers')
        
        real_on_action = request.get('real_on_action')
        real_on_close = request.get('real_on_close')
        
        # ai_params might be empty dict, so check for None explicitly
        if config is not None and ai_params is not None and key_managers is not None:
            create_audio_analyzer_window(
                self._root, config, ai_params, key_managers, real_on_close, real_on_action
            )
    
    def request_chat_window(self, session, initial_response=None):
        """Request creation of a chat window (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'chat',
            'session': session,
            'initial_response': initial_response
        })
    
    def request_streaming_chat_window(self, session, timeout: float = 5.0) -> StreamingChatCallbacks:
        """
        Request creation of a streaming chat window (thread-safe).
        
        Opens the chat window immediately and returns callbacks for
        streaming content into it.
        
        Args:
            session: ChatSession to display (should have user message already)
            timeout: Max time to wait for window creation
            
        Returns:
            StreamingChatCallbacks with on_text, on_thinking callbacks
        """
        self.ensure_running()
        
        callbacks = StreamingChatCallbacks()
        
        self._request_queue.put({
            'type': 'streaming_chat',
            'session': session,
            'callbacks': callbacks
        })
        
        # Wait for window to be created on GUI thread
        callbacks.ready.wait(timeout=timeout)
        
        return callbacks
    
    def request_browser_window(self):
        """Request creation of a session browser window (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'browser'
        })
    
    def request_input_popup(self, on_submit: Callable, on_close: Optional[Callable] = None,
                           x: Optional[int] = None, y: Optional[int] = None,
                           on_tts: Optional[Callable] = None):
        """Request creation of an input popup (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'popup_input',
            'on_submit': on_submit,
            'on_close': on_close,
            'x': x,
            'y': y,
            'on_tts': on_tts
        })
    
    def request_prompt_popup(self, options: dict, on_option_selected: Callable,
                            on_close: Optional[Callable], selected_text: str,
                            x: Optional[int] = None, y: Optional[int] = None,
                            on_tts: Optional[Callable] = None,
                            on_request_compare_text: Optional[Callable] = None):
        """Request creation of a prompt selection popup (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'popup_prompt',
            'options': options,
            'on_option_selected': on_option_selected,
            'on_close': on_close,
            'selected_text': selected_text,
            'x': x,
            'y': y,
            'on_tts': on_tts,
            'on_request_compare_text': on_request_compare_text
        })
    
    def run_on_gui_thread(self, callback: Callable):
        """Run a callback on the GUI thread (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'callback',
            'callback': callback
        })
    
    def request_typing_indicator(self, abort_hotkey: str = "Escape",
                                  on_dismiss: Optional[Callable] = None):
        """Request showing a typing indicator (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'typing_indicator',
            'abort_hotkey': abort_hotkey,
            'on_dismiss': on_dismiss
        })
    
    def request_dismiss_typing_indicator(self):
        """Request dismissing the typing indicator (thread-safe)"""
        if self._running:
            self._request_queue.put({
                'type': 'dismiss_typing_indicator'
            })
    
    def request_toast_notification(self, title: str, message: str, timeout_ms: int = 3000):
        """Request a toast notification (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'toast_notification',
            'title': title,
            'message': message,
            'timeout_ms': timeout_ms
        })
    
    def request_dismiss_toast_notification(self):
        """Request dismissing the toast notification (thread-safe)"""
        if self._running:
            self._request_queue.put({
                'type': 'dismiss_toast_notification'
            })
    
    def request_settings_window(self, on_close: Optional[Callable] = None, initial_tab: str = None):
        """Request creation of a settings window (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'settings',
            'on_close': on_close,
            'initial_tab': initial_tab
        })
    
    def request_prompt_editor_window(self):
        """Request creation of a prompt editor window (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'prompt_editor'
        })

    def request_connection_manager(self, on_close=None):
        """Request creation of a connection profile manager window (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'connection_manager',
            'on_close': on_close
        })
    
    def request_snip_overlay(
        self,
        on_capture,
        on_cancel
    ):
        """Request creation of a screen snip overlay (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'snip_overlay',
            'on_capture': on_capture,
            'on_cancel': on_cancel
        })
    
    def request_snip_popup(
        self,
        capture_result,
        prompts_config,
        on_action,
        on_close=None,
        on_request_compare_capture=None,
        x=None,
        y=None
    ):
        """Request creation of a snip popup (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'snip_popup',
            'capture_result': capture_result,
            'prompts_config': prompts_config,
            'on_action': on_action,
            'on_close': on_close,
            'on_request_compare_capture': on_request_compare_capture,
            'x': x,
            'y': y
        })
    
    def request_audio_analyzer_window(
        self,
        config,
        ai_params,
        key_managers,
        on_action=None,
        on_close=None
    ):
        """Request creation of an audio analyzer window (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'audio_analyzer',
            'config': config,
            'ai_params': ai_params,
            'key_managers': key_managers,
            'real_on_action': on_action,
            'real_on_close': on_close
        })
    
    def _create_tts_window(self, request):
        """Create a TTS window on the GUI thread"""
        from .windows import create_tts_window
        
        config = request.get('config')
        ai_params = request.get('ai_params')
        key_managers = request.get('key_managers')
        initial_text = request.get('initial_text', '')
        on_close = request.get('on_close')
        
        if config is not None and ai_params is not None and key_managers is not None:
            create_tts_window(
                self._root, config, ai_params, key_managers, initial_text, on_close
            )
    
    def request_tts_window(
        self,
        config=None,
        ai_params=None,
        key_managers=None,
        initial_text: str = "",
        on_close=None
    ):
        """Request creation of a TTS window (thread-safe)"""
        self.ensure_running()
        
        # If parameters not provided, use globals from web_server
        if config is None or ai_params is None or key_managers is None:
            try:
                from .. import web_server
                config = config or web_server.CONFIG
                ai_params = ai_params or web_server.AI_PARAMS
                key_managers = key_managers or web_server.KEY_MANAGERS
            except ImportError:
                pass
                
        self._request_queue.put({
            'type': 'tts_window',
            'config': config,
            'ai_params': ai_params,
            'key_managers': key_managers,
            'initial_text': initial_text,
            'on_close': on_close
        })
    
    def _create_onboarding_window(self, request):
        """Create an onboarding wizard window on the GUI thread"""
        from .windows import create_attached_onboarding_window
        on_close = request.get('on_close')
        create_attached_onboarding_window(self._root, on_close)

    def request_onboarding_window(self, on_close: Optional[Callable] = None):
        """Request creation of an onboarding window (thread-safe)"""
        self.ensure_running()
        self._request_queue.put({
            'type': 'onboarding',
            'on_close': on_close
        })
    
    def get_root(self):
        """Get the root CTk/Tk instance (only safe to use from GUI thread!)"""
        return self._root
    
    def refresh_appearance_mode(self):
        """Refresh appearance mode (call when theme changes)"""
        if HAVE_CTK:
            self._sync_appearance_mode()
    
    def is_running(self) -> bool:
        """Check if GUI thread is running"""
        return self._running
    
    def shutdown(self):
        """Shutdown the GUI coordinator"""
        self._running = False


def show_chat_gui(session, initial_response=None):
    """Show a chat GUI window (thread-safe)"""
    coordinator = GUICoordinator.get_instance()
    coordinator.request_chat_window(session, initial_response)
    return True


def show_session_browser():
    """Show a session browser window (thread-safe)"""
    coordinator = GUICoordinator.get_instance()
    coordinator.request_browser_window()
    return True


def get_gui_status():
    """Get current GUI status"""
    coordinator = GUICoordinator.get_instance()
    return {
        "available": HAVE_GUI,
        "running": coordinator.is_running(),
        "open_windows": len(OPEN_WINDOWS)
    }


def show_typing_indicator(abort_hotkey: str = "Escape", on_dismiss: Optional[Callable] = None):
    """Show a typing indicator near the cursor (thread-safe)"""
    coordinator = GUICoordinator.get_instance()
    coordinator.request_typing_indicator(abort_hotkey, on_dismiss)


def dismiss_typing_indicator():
    """Dismiss the typing indicator (thread-safe)"""
    coordinator = GUICoordinator.get_instance()
    coordinator.request_dismiss_typing_indicator()


def show_settings_window(initial_tab: str = None):
    """Show settings window (thread-safe)"""
    coordinator = GUICoordinator.get_instance()
    coordinator.request_settings_window(initial_tab=initial_tab)
    return True


def show_settings_window_blocking(initial_tab: str = None):
    """
    Show settings window and block until it is closed.
    Uses the GUICoordinator to ensure thread safety and keep the GUI root alive.
    
    Args:
        initial_tab: Name of the tab to select initially
    """
    coordinator = GUICoordinator.get_instance()
    
    done_event = threading.Event()
    
    def on_close():
        done_event.set()
        
    coordinator.request_settings_window(on_close=on_close, initial_tab=initial_tab)
    done_event.wait()
    return True


def show_prompt_editor():
    """Show prompt editor window (thread-safe)"""
    coordinator = GUICoordinator.get_instance()
    coordinator.request_prompt_editor_window()
    return True


def show_connection_manager():
    """Show connection profile manager window (thread-safe)"""
    coordinator = GUICoordinator.get_instance()
    coordinator.request_connection_manager()
    return True
