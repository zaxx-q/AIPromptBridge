#!/usr/bin/env python3
"""
Unit tests for API retry loop abort and clean cancellation handling across
RequestPipeline, providers, TextEditTool, SnipTool, and error popups.
"""

import threading
from unittest.mock import MagicMock, patch

from src.gui.popups import show_error_popup
from src.request_pipeline import (
    RequestOrigin,
    RequestPipeline,
    StreamCallback,
    create_request_context,
)


class TestRequestPipelineAbort:
    def test_log_request_complete_shows_cancelled_not_failed(self, monkeypatch):
        """Verify that aborted/cancelled requests are logged as CANCELLED, not FAILED."""
        ctx = create_request_context(
            origin=RequestOrigin.CHAT_WINDOW,
            provider="google",
            model="gemini-2.5-flash",
            streaming=True,
        )
        ctx.aborted = True
        ctx.error = "Request aborted"

        logged_panels = []
        logged_prints = []

        monkeypatch.setattr(
            "src.request_pipeline.print_panel",
            lambda text, title="", **kwargs: logged_panels.append((title, text)),
        )
        monkeypatch.setattr(
            "builtins.print",
            lambda *args, **kwargs: logged_prints.append(" ".join(str(a) for a in args)),
        )

        RequestPipeline.log_request_complete(ctx)

        # In Rich mode or non-rich mode, title or text must say CANCELLED and never FAILED
        all_text = " ".join(t[0] for t in logged_panels) + " ".join(logged_prints)
        assert "CANCELLED" in all_text
        assert "FAILED" not in all_text

    @patch("src.api_client.call_api_stream_unified")
    def test_execute_unified_stream_aborted_callback(self, mock_stream):
        """Unified stream abort calls on_aborted and NOT on_error, marks ctx.aborted."""
        abort_event = threading.Event()
        abort_event.set()

        def fake_call(*args, **kwargs):
            cb = kwargs.get("callback")
            if cb:
                cb("aborted", None)
            return None, None, None, "Request aborted"

        mock_stream.side_effect = fake_call

        ctx = create_request_context(
            origin=RequestOrigin.POPUP_INPUT,
            provider="custom",
            model="test-model",
            streaming=True,
        )

        on_aborted_called = []
        on_error_called = []

        callbacks = StreamCallback(
            on_aborted=lambda: on_aborted_called.append(True),
            on_error=lambda err: on_error_called.append(err),
        )

        result_ctx = RequestPipeline.execute_unified_stream(
            ctx,
            messages=[{"role": "user", "content": "hi"}],
            config={},
            ai_params={},
            key_managers={},
            callbacks=callbacks,
            abort_event=abort_event,
        )

        assert result_ctx.aborted is True
        assert len(on_aborted_called) == 1
        assert len(on_error_called) == 0

    @patch("src.api_client.call_api_chat_stream")
    def test_execute_streaming_aborted_callback(self, mock_stream):
        """Streaming chat abort calls on_aborted and NOT on_error, marks ctx.aborted."""
        abort_event = threading.Event()
        abort_event.set()

        def fake_call(*args, **kwargs):
            cb = args[4]
            if cb:
                cb("aborted", None)
            return None, None, None, "Request aborted"

        mock_stream.side_effect = fake_call

        session = MagicMock()
        ctx = create_request_context(
            origin=RequestOrigin.POPUP_INPUT,
            provider="google",
            model="gemini-2.5-flash",
            streaming=True,
        )

        on_aborted_called = []
        on_error_called = []

        callbacks = StreamCallback(
            on_aborted=lambda: on_aborted_called.append(True),
            on_error=lambda err: on_error_called.append(err),
        )

        result_ctx = RequestPipeline.execute_streaming(
            ctx,
            session=session,
            config={},
            ai_params={},
            key_managers={},
            callbacks=callbacks,
            abort_event=abort_event,
        )

        assert result_ctx.aborted is True
        assert len(on_aborted_called) == 1
        assert len(on_error_called) == 0

    @patch("src.api_client.call_api_with_retry")
    def test_execute_simple_aborted(self, mock_simple):
        """Non-streaming simple call marks ctx.aborted on abort_event."""
        abort_event = threading.Event()
        abort_event.set()

        def fake_call(*args, **kwargs):
            res_out = kwargs.get("result_out")
            if isinstance(res_out, dict):
                res_out["aborted"] = True
            return None, "Request aborted"

        mock_simple.side_effect = fake_call

        ctx = create_request_context(
            origin=RequestOrigin.SNIP_TOOL,
            provider="google",
            model="gemini-2.5-flash",
            streaming=False,
        )

        result_ctx = RequestPipeline.execute_simple(
            ctx,
            messages=[{"role": "user", "content": "hi"}],
            config={},
            ai_params={},
            key_managers={},
            abort_event=abort_event,
        )

        assert result_ctx.aborted is True


class TestErrorPopupSuppression:
    @patch("src.gui.core.GUICoordinator.get_instance")
    def test_show_error_popup_suppressed_on_abort_or_cancel(self, mock_coord):
        """show_error_popup suppresses popup when message or details contain 'aborted' or 'cancelled'."""
        coordinator = MagicMock()
        mock_coord.return_value = coordinator

        # Should be suppressed
        show_error_popup("API Request Failed", "Failed to get response", details="Request aborted")
        show_error_popup("API Request Failed", "Request cancelled", details=None)
        show_error_popup("Request Cancelled", "Operation was cancelled by user", details=None)

        coordinator.request_error_popup.assert_not_called()

        # Genuine errors should NOT be suppressed
        show_error_popup("API Request Failed", "Failed to connect to server", details="503 Service Unavailable")
        coordinator.request_error_popup.assert_called_once_with(
            "API Request Failed", "Failed to connect to server", "503 Service Unavailable"
        )

    @patch("src.gui.core.GUICoordinator.get_instance")
    def test_connection_aborted_network_error_not_suppressed(self, mock_coord):
        """Verify requests network error 'Connection aborted.' is NOT suppressed as user cancellation."""
        coordinator = MagicMock()
        mock_coord.return_value = coordinator

        # Network error "Connection aborted." must NOT be suppressed
        show_error_popup(
            "API Request Failed",
            "Network error occurred",
            details="requests.exceptions.ConnectionError: ('Connection aborted.', RemoteDisconnected())",
        )
        coordinator.request_error_popup.assert_called_once_with(
            "API Request Failed",
            "Network error occurred",
            "requests.exceptions.ConnectionError: ('Connection aborted.', RemoteDisconnected())",
        )


class TestNetworkErrorDistinction:
    def test_connection_aborted_logged_as_failed_not_cancelled(self, monkeypatch):
        """Verify that network error 'Connection aborted.' logs as FAILED, not CANCELLED."""
        ctx = create_request_context(
            origin=RequestOrigin.CHAT_WINDOW,
            provider="google",
            model="gemini-2.5-flash",
            streaming=True,
        )
        ctx.aborted = False
        ctx.error = "requests.exceptions.ConnectionError: ('Connection aborted.', RemoteDisconnected())"

        logged_panels = []
        logged_prints = []

        monkeypatch.setattr(
            "src.request_pipeline.print_panel",
            lambda text, title="", **kwargs: logged_panels.append((title, text)),
        )
        monkeypatch.setattr(
            "builtins.print",
            lambda *args, **kwargs: logged_prints.append(" ".join(str(a) for a in args)),
        )

        RequestPipeline.log_request_complete(ctx)

        all_text = " ".join(t[0] for t in logged_panels) + " ".join(logged_prints)
        assert "FAILED" in all_text
        assert "CANCELLED" not in all_text


class TestProviderSocketLeakPrevention:
    @patch("requests.post")
    def test_response_closed_when_abort_fires_immediately_after_post_openai(self, mock_post):
        """Verify response.close() is called if abort is set immediately after requests.post in OpenAI provider."""
        from src.key_manager import KeyManager
        from src.providers.openai_compatible import OpenAICompatibleProvider

        km = MagicMock(spec=KeyManager)
        km.has_keys.return_value = True
        km.get_current_key.return_value = "fake-key"
        km.get_key_label.return_value = "1"

        provider = OpenAICompatibleProvider("custom", "http://fake.url", km, {})

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        abort_event = threading.Event()

        def post_and_abort(*args, **kwargs):
            abort_event.set()
            return mock_resp

        mock_post.side_effect = post_and_abort

        cb = MagicMock()
        res = provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            model="test",
            params={},
            callback=cb,
            abort_event=abort_event,
        )

        assert res.aborted is True
        mock_resp.close.assert_called()

    @patch("requests.post")
    def test_response_closed_when_abort_fires_immediately_after_post_gemini(self, mock_post):
        """Verify response.close() is called if abort is set immediately after requests.post in Gemini provider."""
        from src.key_manager import KeyManager
        from src.providers.gemini_native import GeminiNativeProvider

        km = MagicMock(spec=KeyManager)
        km.has_keys.return_value = True
        km.get_current_key.return_value = "fake-key"
        km.get_key_label.return_value = "1"

        provider = GeminiNativeProvider(km, {})

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        abort_event = threading.Event()

        def post_and_abort(*args, **kwargs):
            abort_event.set()
            return mock_resp

        mock_post.side_effect = post_and_abort

        cb = MagicMock()
        res = provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            model="gemini-2.5-flash",
            params={},
            callback=cb,
            abort_event=abort_event,
        )

        assert res.aborted is True
        mock_resp.close.assert_called()

    @patch("requests.post")
    def test_response_closed_when_abort_fires_immediately_after_post_anthropic(self, mock_post):
        """Verify response.close() is called if abort is set immediately after requests.post in Anthropic provider."""
        from src.key_manager import KeyManager
        from src.providers.anthropic import AnthropicProvider

        km = MagicMock(spec=KeyManager)
        km.has_keys.return_value = True
        km.get_current_key.return_value = "fake-key"
        km.get_key_label.return_value = "1"

        provider = AnthropicProvider(base_url="https://api.anthropic.com/v1", key_manager=km, config={})

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        abort_event = threading.Event()

        def post_and_abort(*args, **kwargs):
            abort_event.set()
            return mock_resp

        mock_post.side_effect = post_and_abort

        cb = MagicMock()
        res = provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            model="claude-3-5-sonnet",
            params={},
            callback=cb,
            abort_event=abort_event,
        )

        assert res.aborted is True
        mock_resp.close.assert_called()


class TestTextEditToolAbortSuppression:
    def test_call_api_returns_cancelled_and_inherits_current_abort_event(self):
        """_call_api inherits self._current_abort_event and returns 'Request cancelled' when aborted."""
        from src.gui.text_edit_tool import TextEditToolApp

        app = TextEditToolApp.__new__(TextEditToolApp)
        app.config = {"default_provider": "google", "streaming_enabled": True}
        app.ai_params = {}
        app.key_managers = {"google": MagicMock()}
        app.cancel_requested = False
        app.streaming_aborted = False

        abort_event = threading.Event()
        app._current_abort_event = abort_event

        with patch("src.request_pipeline.RequestPipeline.execute_streaming") as mock_exec:
            mock_ctx = MagicMock()
            mock_ctx.aborted = True
            mock_ctx.error = "Request aborted"
            mock_ctx.response_text = ""
            mock_exec.return_value = mock_ctx

            abort_event.set()
            response, error = app._call_api([{"role": "user", "content": "test"}])

            assert response is None
            assert error == "Request cancelled"
            # Verify abort_event was passed down into RequestPipeline
            call_kwargs = mock_exec.call_args.kwargs
            assert call_kwargs.get("abort_event") is abort_event

    def test_abort_listener_creates_event_if_none(self):
        """_start_abort_listener creates a threading.Event if not provided and sets _current_abort_event."""
        from src.gui.text_edit_tool import TextEditToolApp

        app = TextEditToolApp.__new__(TextEditToolApp)
        app.abort_hotkey = "escape"
        app.streaming_aborted = True
        app._current_abort_event = None

        with patch("pynput.keyboard.Listener"):
            ev = app._start_abort_listener(None)
            assert isinstance(ev, threading.Event)
            assert app._current_abort_event is ev
            assert app.streaming_aborted is False


class TestChatWindowAbort:
    def test_watch_abort_closes_response_on_event_set(self):
        """_watch_abort_for_response immediately calls response.close() when abort_event is set."""
        import time

        from src.providers.base import BaseProvider

        class DummyProvider(BaseProvider):
            def _do_generate(self, *args, **kwargs):
                pass

            def _do_generate_stream(self, *args, **kwargs):
                pass

            def fetch_models(self):
                return [], None

        provider = DummyProvider.__new__(DummyProvider)
        mock_resp = MagicMock()
        abort_event = threading.Event()

        provider._watch_abort_for_response(mock_resp, abort_event)
        mock_resp.close.assert_not_called()

        abort_event.set()
        time.sleep(0.05)
        mock_resp.close.assert_called_once()

    def test_stop_request_immediately_unlocks_ui(self):
        """_stop_request immediately clears loading/streaming flags, restores Send, and enables inputs."""
        from src.gui.windows.chat_base import ChatWindowBase

        class DummyChatWindow(ChatWindowBase):
            def _get_window_tag(self) -> str:
                return "dummy"

        chat = DummyChatWindow.__new__(DummyChatWindow)
        chat.is_loading = True
        chat.is_streaming = True
        chat.streaming_text = "partial text"
        chat.streaming_thinking = "thinking"
        chat._abort_event = threading.Event()

        chat.send_btn = MagicMock()
        chat.input_text = MagicMock()
        chat.attach_btn = MagicMock()
        chat.rename_btn = MagicMock()
        chat.delete_btn = MagicMock()
        chat.regen_btn = MagicMock()
        chat.status_label = MagicMock()
        chat.chat_text = MagicMock()

        chat._set_send_button_loading = MagicMock()
        chat._set_inputs_enabled = MagicMock()
        chat._update_chat_display = MagicMock()
        chat._update_status = MagicMock()

        chat._stop_request()

        assert chat._abort_event.is_set() is True
        assert chat.is_loading is False
        assert chat.is_streaming is False
        assert chat.streaming_text == ""
        assert chat.streaming_thinking == ""

        chat._set_send_button_loading.assert_called_once_with(False)
        chat._set_inputs_enabled.assert_called_once_with(True)
        chat._update_chat_display.assert_called_once_with(scroll_to_bottom=True)
        chat._update_status.assert_called_once_with("Request stopped")
