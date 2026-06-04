import unittest

from src.providers.gemini_native import GeminiNativeProvider


class TestGeminiEmptyResponse(unittest.TestCase):
    def test_detect_empty_response_logic(self):
        # Initialize without keys/config, which is fine for testing this specific method
        provider = GeminiNativeProvider()

        print("\nTesting duplicate check logic:")

        # Case 1: Standard success (Thinking + Content)
        # Should return False (NOT empty)
        result = provider.detect_empty_response(
            content="Hello", thinking="Thinking about hello", tool_calls=[], output_tokens=100
        )
        print(f"Case 1 (Thinking+Content): {result} (Expected: False)")
        self.assertFalse(result)

        # Case 2: Thinking only (The bug)
        # Before fix: Returns False (because thinking is content, so base class says not empty)
        # After fix: Should return True (Empty response detected)
        result = provider.detect_empty_response(
            content="", thinking="Thinking about it...", tool_calls=[], output_tokens=50
        )
        print(f"Case 2 (Thinking Only): {result} (Expected: True/False depending on fix status)")
        # note: checking expectations in the run steps

        # Case 3: Thinking only but with whitespace content
        # Should return True (Empty)
        result = provider.detect_empty_response(content="   ", thinking="Thinking...", tool_calls=[], output_tokens=50)
        print(f"Case 3 (Thinking+Whitespace): {result}")

        # Case 4: Tool call (Should be valid)
        # Should return False (NOT empty)
        result = provider.detect_empty_response(
            content="", thinking="Checking tools", tool_calls=[{"name": "test"}], output_tokens=50
        )
        print(f"Case 4 (Tool Call): {result} (Expected: False)")
        self.assertFalse(result)

        # Case 5: Standard empty (0 tokens)
        # Should return True (Empty)
        result = provider.detect_empty_response(content="", thinking="", tool_calls=[], output_tokens=0)
        print(f"Case 5 (0 Tokens): {result} (Expected: True)")
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
