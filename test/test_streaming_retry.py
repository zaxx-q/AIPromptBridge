#!/usr/bin/env python3
"""
Test script for verifying streaming retry logic in providers.
Simulates API failures and verifies correct retry behavior.
"""

import unittest
from unittest.mock import MagicMock, patch
import json
import requests
from src.providers.openai_compatible import OpenAICompatibleProvider, CallbackType, RetryReason
from src.providers.gemini_native import GeminiNativeProvider
from src.key_manager import KeyManager

class TestStreamingRetry(unittest.TestCase):
    def setUp(self):
        self.key_manager = MagicMock(spec=KeyManager)
        self.key_manager.has_keys.return_value = True
        self.key_manager.get_current_key.return_value = "fake-key"
        self.key_manager.get_key_number.return_value = 1
        
        self.config = {
            "request_timeout": 1,  # Short timeout for testing
            "retry_delays": {      # Override delays to speed up tests
                "rate_limit": 0.01,
                "server_error": 0.01,
                "network_error": 0.01,
                "empty_response": 0.01
            }
        }
        
    @patch('requests.post')
    @patch('time.sleep')  # Mock sleep to run tests fast
    def test_openai_429_retry(self, mock_sleep, mock_post):
        """Test retry on 429 Rate Limit"""
        provider = OpenAICompatibleProvider("custom", "http://fake.url", self.key_manager, self.config)
        
        # Mock responses: 429, then 200 Success
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.text = "Rate limit exceeded"
        
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.iter_lines.return_value = [
            'data: {"choices": [{"delta": {"content": "Success"}}]}',
            'data: [DONE]'
        ]
        
        mock_post.side_effect = [mock_response_429, mock_response_200]
        
        callback = MagicMock()
        
        result = provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            model="test-model",
            params={},
            callback=callback
        )
        
        # Verify
        self.assertTrue(result.success)
        self.assertEqual(result.content, "Success")
        self.assertEqual(result.retry_count, 1)
        
        # Verify key rotation was called (rate limits trigger immediate rotation)
        self.key_manager.rotate_key.assert_called()
        
        # Sleep should NOT be called for rate limits (immediate retry)
        mock_sleep.assert_not_called()

    @patch('requests.post')
    @patch('time.sleep')
    def test_openai_empty_response_retry(self, mock_sleep, mock_post):
        """Test retry on empty response (0 tokens)"""
        provider = OpenAICompatibleProvider("custom", "http://fake.url", self.key_manager, self.config)
        
        # Mock responses: Empty 200, then Valid 200
        mock_response_empty = MagicMock()
        mock_response_empty.status_code = 200
        # Stream finishes immediately without content
        mock_response_empty.iter_lines.return_value = [
            'data: {"usage": {"completion_tokens": 0}}',
            'data: [DONE]'
        ]
        
        mock_response_valid = MagicMock()
        mock_response_valid.status_code = 200
        mock_response_valid.iter_lines.return_value = [
            'data: {"choices": [{"delta": {"content": "Valid"}}]}',
            'data: {"usage": {"completion_tokens": 5}}',
            'data: [DONE]'
        ]
        
        mock_post.side_effect = [mock_response_empty, mock_response_valid]
        
        callback = MagicMock()
        
        result = provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            model="test-model",
            params={},
            callback=callback
        )
        
        # Verify
        self.assertTrue(result.success)
        self.assertEqual(result.content, "Valid")
        self.assertEqual(result.retry_count, 1)
        self.key_manager.rotate_key.assert_called() # Should rotate on empty response

    @patch('requests.post')
    @patch('time.sleep')
    def test_gemini_network_error_retry(self, mock_sleep, mock_post):
        """Test retry on network error"""
        provider = GeminiNativeProvider(self.key_manager, self.config)
        
        # Mock side effect: Exception, then Success
        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        # Gemini format
        mock_response_success.iter_lines.return_value = [
            'data: {"candidates": [{"content": {"parts": [{"text": "Gemini Success"}]}}]}',
        ]
        
        mock_post.side_effect = [requests.exceptions.ConnectionError("Network down"), mock_response_success]
        
        callback = MagicMock()
        
        result = provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            model="gemini-2.0-flash",
            params={},
            callback=callback
        )
        
        # Verify
        self.assertTrue(result.success)
        self.assertEqual(result.content, "Gemini Success")
        self.assertEqual(result.retry_count, 1)
        self.key_manager.rotate_key.assert_called() # Should rotate on network error

    @patch('requests.post')
    @patch('time.sleep')
    def test_openai_thinking_extraction_streaming(self, mock_sleep, mock_post):
        """Test thinking content extraction from OpenAI-compatible streaming"""
        provider = OpenAICompatibleProvider("custom", "http://fake.url", self.key_manager, self.config)
        
        # Mock streaming response with reasoning_content
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            'data: {"choices": [{"delta": {"reasoning_content": "Let me think..."}}]}',
            'data: {"choices": [{"delta": {"reasoning_content": " this is complex"}}]}',
            'data: {"choices": [{"delta": {"content": "Final answer"}}]}',
            'data: {"usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}',
            'data: [DONE]'
        ]
        
        mock_post.return_value = mock_response
        
        # Track callback invocations
        callback_data = {
            CallbackType.THINKING: [],
            CallbackType.TEXT: [],
            CallbackType.USAGE: None
        }
        
        def track_callback(cb_type, data):
            if cb_type == CallbackType.THINKING:
                callback_data[CallbackType.THINKING].append(data)
            elif cb_type == CallbackType.TEXT:
                callback_data[CallbackType.TEXT].append(data)
            elif cb_type == CallbackType.USAGE:
                callback_data[CallbackType.USAGE] = data
        
        result = provider.generate_stream(
            messages=[{"role": "user", "content": "Test"}],
            model="test-model",
            params={},
            callback=track_callback,
            thinking_enabled=True
        )
        
        # Verify
        self.assertTrue(result.success)
        self.assertEqual(result.thinking_content, "Let me think... this is complex")
        self.assertEqual(result.content, "Final answer")
        self.assertEqual(callback_data[CallbackType.THINKING], ["Let me think...", " this is complex"])
        self.assertEqual(callback_data[CallbackType.TEXT], ["Final answer"])
        self.assertIsNotNone(callback_data[CallbackType.USAGE])
        self.assertEqual(result.usage.completion_tokens, 20)

    @patch('requests.post')
    @patch('time.sleep')
    def test_openai_thinking_extraction_nonstreaming(self, mock_sleep, mock_post):
        """Test thinking content extraction from OpenAI-compatible non-streaming"""
        provider = OpenAICompatibleProvider("custom", "http://fake.url", self.key_manager, self.config)
        
        # Mock non-streaming response with reasoning_content
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "Here's my answer",
                    "reasoning_content": "First I analyzed... then concluded"
                }
            }],
            "usage": {
                "prompt_tokens": 15,
                "completion_tokens": 25,
                "total_tokens": 40
            }
        }
        
        mock_post.return_value = mock_response
        
        result = provider.generate(
            messages=[{"role": "user", "content": "Explain"}],
            model="test-model",
            params={},
            thinking_enabled=True
        )
        
        # Verify
        self.assertTrue(result.success)
        self.assertEqual(result.content, "Here's my answer")
        self.assertEqual(result.thinking_content, "First I analyzed... then concluded")
        self.assertEqual(result.usage.prompt_tokens, 15)
        self.assertEqual(result.usage.completion_tokens, 25)

    @patch('requests.post')
    @patch('time.sleep')
    def test_gemini_thinking_extraction_streaming(self, mock_sleep, mock_post):
        """Test thinking content extraction from Gemini native streaming"""
        provider = GeminiNativeProvider(self.key_manager, self.config)
        
        # Mock Gemini streaming with thought parts
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            'data: {"candidates": [{"content": {"parts": [{"text": "Analyzing...", "thought": true}]}}]}',
            'data: {"candidates": [{"content": {"parts": [{"text": " considering factors", "thought": true}]}}]}',
            'data: {"candidates": [{"content": {"parts": [{"text": "Based on analysis: success"}]}}]}',
            'data: {"usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 18, "totalTokenCount": 30}}'
        ]
        
        mock_post.return_value = mock_response
        
        # Track callbacks
        callback_data = {
            CallbackType.THINKING: [],
            CallbackType.TEXT: []
        }
        
        def track_callback(cb_type, data):
            if cb_type == CallbackType.THINKING:
                callback_data[CallbackType.THINKING].append(data)
            elif cb_type == CallbackType.TEXT:
                callback_data[CallbackType.TEXT].append(data)
        
        result = provider.generate_stream(
            messages=[{"role": "user", "content": "Test"}],
            model="gemini-2.5-flash",
            params={},
            callback=track_callback,
            thinking_enabled=True
        )
        
        # Verify
        self.assertTrue(result.success)
        self.assertEqual(result.thinking_content, "Analyzing... considering factors")
        self.assertEqual(result.content, "Based on analysis: success")
        self.assertEqual(callback_data[CallbackType.THINKING], ["Analyzing...", " considering factors"])
        self.assertEqual(callback_data[CallbackType.TEXT], ["Based on analysis: success"])
        self.assertEqual(result.usage.completion_tokens, 18)

    @patch('requests.post')
    @patch('time.sleep')
    def test_gemini_thinking_extraction_nonstreaming(self, mock_sleep, mock_post):
        """Test thinking content extraction from Gemini native non-streaming"""
        provider = GeminiNativeProvider(self.key_manager, self.config)
        
        # Mock Gemini non-streaming with thought parts
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [
                        {"text": "Let me reason through this", "thought": True},
                        {"text": "Final conclusion: approved"}
                    ]
                }
            }],
            "usageMetadata": {
                "promptTokenCount": 20,
                "candidatesTokenCount": 30,
                "totalTokenCount": 50
            }
        }
        
        mock_post.return_value = mock_response
        
        result = provider.generate(
            messages=[{"role": "user", "content": "Decide"}],
            model="gemini-2.5-flash",
            params={},
            thinking_enabled=True
        )
        
        # Verify
        self.assertTrue(result.success)
        self.assertEqual(result.thinking_content, "Let me reason through this")
        self.assertEqual(result.content, "Final conclusion: approved")
        self.assertEqual(result.usage.prompt_tokens, 20)
        self.assertEqual(result.usage.completion_tokens, 30)

    @patch('requests.post')
    @patch('time.sleep')
    def test_thinking_config_in_request_body_openai(self, mock_sleep, mock_post):
        """Verify thinking config is added to OpenAI request body when enabled"""
        provider = OpenAICompatibleProvider(
            "custom",
            "http://fake.url",
            self.key_manager,
            {"reasoning_effort": "high"}
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = ['data: [DONE]']
        mock_post.return_value = mock_response
        
        provider.generate_stream(
            messages=[{"role": "user", "content": "Test"}],
            model="test-model",
            params={},
            callback=MagicMock(),
            thinking_enabled=True
        )
        
        # Check the request body sent to the API
        call_args = mock_post.call_args
        request_body = call_args.kwargs['json']
        
        # Verify reasoning_effort is included
        self.assertIn("reasoning_effort", request_body)
        self.assertEqual(request_body["reasoning_effort"], "high")

    @patch('requests.post')
    @patch('time.sleep')
    def test_thinking_config_in_request_body_gemini(self, mock_sleep, mock_post):
        """Verify thinkingConfig is added to Gemini request body when enabled"""
        provider = GeminiNativeProvider(
            self.key_manager,
            {"thinking_budget": -1}  # -1 = auto/unlimited for 2.5
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = []
        mock_post.return_value = mock_response
        
        provider.generate_stream(
            messages=[{"role": "user", "content": "Test"}],
            model="gemini-2.5-flash",
            params={},
            callback=MagicMock(),
            thinking_enabled=True
        )
        
        # Check the request body
        call_args = mock_post.call_args
        request_body = call_args.kwargs['json']
        
        # Verify thinkingConfig is included
        self.assertIn("generationConfig", request_body)
        gen_config = request_body["generationConfig"]
        self.assertIn("thinkingConfig", gen_config)
        self.assertEqual(gen_config["thinkingConfig"]["thinkingBudget"], -1)
        self.assertTrue(gen_config["thinkingConfig"]["includeThoughts"])

    @patch('requests.post')
    @patch('time.sleep')
    def test_gemini_3_uses_thinking_level(self, mock_sleep, mock_post):
        """Verify Gemini 3.x uses thinkingLevel instead of thinkingBudget"""
        provider = GeminiNativeProvider(
            self.key_manager,
            {"thinking_level": "high"}
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = []
        mock_post.return_value = mock_response
        
        provider.generate_stream(
            messages=[{"role": "user", "content": "Test"}],
            model="gemini-3-pro-preview",  # 3.x model
            params={},
            callback=MagicMock(),
            thinking_enabled=True
        )
        
        # Check request body
        call_args = mock_post.call_args
        request_body = call_args.kwargs['json']
        
        gen_config = request_body["generationConfig"]
        thinking_config = gen_config["thinkingConfig"]
        
        # Should have thinkingLevel, not thinkingBudget
        self.assertIn("thinkingLevel", thinking_config)
        self.assertEqual(thinking_config["thinkingLevel"], "high")
        self.assertNotIn("thinkingBudget", thinking_config)
    @patch('requests.post')
    @patch('time.sleep')
    def test_openai_inline_thinking_extraction_streaming(self, mock_sleep, mock_post):
        """Test inline thinking block extraction from OpenAI-compatible streaming content"""
        provider = OpenAICompatibleProvider("custom", "http://fake.url", self.key_manager, self.config)
        
        # Mock streaming response where the think block is inside content chunk
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            'data: {"choices": [{"delta": {"content": "<think>Let me "}}]}',
            'data: {"choices": [{"delta": {"content": "think about this</think>Answer text"}}]}',
            'data: [DONE]'
        ]
        mock_post.return_value = mock_response
        
        callback = MagicMock()
        result = provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            model="test-model",
            params={},
            callback=callback
        )
        
        # Verify result contains the split fields
        self.assertTrue(result.success)
        self.assertEqual(result.content, "Answer text")
        self.assertEqual(result.thinking_content, "Let me think about this")

    @patch('requests.post')
    @patch('time.sleep')
    def test_openai_inline_thinking_extraction_nonstreaming(self, mock_sleep, mock_post):
        """Test inline thinking block extraction from OpenAI-compatible non-streaming content"""
        provider = OpenAICompatibleProvider("custom", "http://fake.url", self.key_manager, self.config)
        
        # Mock non-streaming response where the think block is inside message content
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "<think>Let me analyze</think>Final conclusion"
                }
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30
            }
        }
        mock_post.return_value = mock_response
        
        result = provider.generate(
            messages=[{"role": "user", "content": "hi"}],
            model="test-model",
            params={}
        )
        
        # Verify
        self.assertTrue(result.success)
        self.assertEqual(result.content, "Final conclusion")
        self.assertEqual(result.thinking_content, "Let me analyze")

    @patch('requests.post')
    @patch('time.sleep')
    def test_openai_inline_thinking_only_triggers_empty_retry(self, mock_sleep, mock_post):
        """Test that a response with ONLY inline thinking block is retried as empty"""
        provider = OpenAICompatibleProvider("custom", "http://fake.url", self.key_manager, self.config)
        
        # First attempt: only think tag
        mock_response_empty = MagicMock()
        mock_response_empty.status_code = 200
        mock_response_empty.iter_lines.return_value = [
            'data: {"choices": [{"delta": {"content": "<think>Thinking only</think>"}}]}',
            'data: [DONE]'
        ]
        
        # Second attempt: actual content
        mock_response_valid = MagicMock()
        mock_response_valid.status_code = 200
        mock_response_valid.iter_lines.return_value = [
            'data: {"choices": [{"delta": {"content": "<think>Thinking</think>Actual response"}}]}',
            'data: [DONE]'
        ]
        
        mock_post.side_effect = [mock_response_empty, mock_response_valid]
        
        callback = MagicMock()
        result = provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            model="test-model",
            params={},
            callback=callback
        )
        
        # Verify it retried and got the valid response
        self.assertTrue(result.success)
        self.assertEqual(result.content, "Actual response")
        self.assertEqual(result.thinking_content, "Thinking")
        self.assertEqual(result.retry_count, 1)

if __name__ == '__main__':
    unittest.main()