"""
Extract leading inline reasoning blocks that some models emit
instead of using provider-native thinking channels.

Common with models served via OpenRouter, custom endpoints, etc.

Handles formats:
- XML: <think>...</think>, <thinking>...</thinking>, <thought>...</thought>
- Pipe: <|think|>...<|/think|>
- Channel: <|channel>thought...<channel|>
"""

import re
from dataclasses import dataclass

XML_THINKING_BLOCK_RE = re.compile(r"^(\s*)<(think|thinking|thought)>([\s\S]*?)</\2>", re.IGNORECASE)
PIPE_THINKING_BLOCK_RE = re.compile(r"^(\s*)<\|think\|>([\s\S]*?)<\|/think\|>", re.IGNORECASE)
CHANNEL_THINKING_BLOCK_RE = re.compile(r"^(\s*)<\|channel>thought\b([\s\S]*?)<channel\|>", re.IGNORECASE)


@dataclass
class ThinkingExtraction:
    content: str
    thinking: str
    stripped: bool


def extract_leading_thinking_blocks(text: str) -> ThinkingExtraction:
    """Extract leading inline reasoning blocks from model output."""
    remaining = text
    stripped = False
    chunks = []

    while True:
        match = XML_THINKING_BLOCK_RE.match(remaining)
        if match:
            stripped = True
            thinking = (match.group(3) or "").strip()
            if thinking:
                chunks.append(thinking)
            remaining = remaining[match.end() :].lstrip()
            continue

        match = PIPE_THINKING_BLOCK_RE.match(remaining)
        if match:
            stripped = True
            thinking = (match.group(2) or "").strip()
            if thinking:
                chunks.append(thinking)
            remaining = remaining[match.end() :].lstrip()
            continue

        match = CHANNEL_THINKING_BLOCK_RE.match(remaining)
        if match:
            stripped = True
            thinking = (match.group(2) or "").strip()
            if thinking:
                chunks.append(thinking)
            remaining = remaining[match.end() :].lstrip()
            continue

        break

    return ThinkingExtraction(
        content=remaining,
        thinking="\n\n".join(chunks),
        stripped=stripped,
    )
