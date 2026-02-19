#!/usr/bin/env python3
"""
Message structures for AI API requests.

This module provides a centralized factory for building multimodal messages
(Text, Audio, Image, Comparison) in a format compatible with the RequestPipeline.

It ensures consistency across:
- AudioAnalyzerWindow
- AudioToolApp
- SnipToolApp
- TextEditToolApp
- PromptEditorWindow
- FileProcessor
- FileHandler

Compatibility:
- Uses 'inline_data' for media to support Gemini Native and other providers.
- Follows the standard [{"role": "system", ...}, {"role": "user", ...}] structure.
"""

from typing import List, Dict, Any, Optional

def build_text_message(
    task: str,
    system_prompt: str
) -> List[Dict[str, Any]]:
    """
    Build a standard text-only message.
    
    Args:
        task: The user's query or instruction.
        system_prompt: The system instruction.
        
    Returns:
        List of message dictionaries.
    """
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task}
    ]

def build_audio_message(
    audio_b64: str,
    mime_type: str,
    task: str,
    system_prompt: str
) -> List[Dict[str, Any]]:
    """
    Build a multimodal message with audio.
    
    Uses 'inline_data' for generic provider compatibility (especially Gemini Native).
    Audio is typically placed before text content.
    
    Args:
        audio_b64: Base64 encoded audio data.
        mime_type: MIME type of the audio (e.g., "audio/wav", "audio/ogg").
        task: The user's instruction.
        system_prompt: The system instruction.
        
    Returns:
        List of message dictionaries.
    """
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {
                "type": "inline_data", 
                "inline_data": {
                    "mime_type": mime_type, 
                    "data": audio_b64
                }
            },
            {"type": "text", "text": task}
        ]}
    ]

def build_image_message(
    image_b64: str,
    mime_type: str,
    task: str,
    system_prompt: str
) -> List[Dict[str, Any]]:
    """
    Build a multimodal message with a single image.
    
    Uses 'image_url' (data URI format) which is the standard abstraction
    used by the OpenAI-compatible provider but also supported by Gemini Native
    adapter in the pipeline.
    
    Args:
        image_b64: Base64 encoded image data.
        mime_type: MIME type of the image (e.g., "image/png").
        task: The user's instruction.
        system_prompt: The system instruction.
        
    Returns:
        List of message dictionaries.
    """
    data_url = f"data:{mime_type};base64,{image_b64}"
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": task}
        ]}
    ]

def build_comparison_message(
    image1_b64: str,
    image2_b64: str,
    mime_type: str,
    task: str,
    system_prompt: str
) -> List[Dict[str, Any]]:
    """
    Build a multimodal message with two images for comparison.
    
    Images are labeled and placed before the text instruction.
    
    Args:
        image1_b64: Base64 encoded first image.
        image2_b64: Base64 encoded second image.
        mime_type: MIME type for both images.
        task: The user's instruction.
        system_prompt: The system instruction.
        
    Returns:
        List of message dictionaries.
    """
    data_url1 = f"data:{mime_type};base64,{image1_b64}"
    data_url2 = f"data:{mime_type};base64,{image2_b64}"
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": "Image 1:"},
            {"type": "image_url", "image_url": {"url": data_url1}},
            {"type": "text", "text": "Image 2:"},
            {"type": "image_url", "image_url": {"url": data_url2}},
            {"type": "text", "text": task}
        ]}
    ]

def build_text_comparison_message(
    text1: str,
    text2: str,
    task: str,
    system_prompt: str
) -> List[Dict[str, Any]]:
    """
    Build a text comparison message with two labeled text blocks.

    Both texts are wrapped in explicit XML-style delimiters so the AI
    can clearly distinguish them.

    Args:
        text1: The first text to compare.
        text2: The second text to compare.
        task: The comparison instruction.
        system_prompt: The system instruction.

    Returns:
        List of message dictionaries.
    """
    user_content = (
        f"{task}"
        f"\n\n<text_1>\n{text1}\n</text_1>"
        f"\n\n<text_2>\n{text2}\n</text_2>"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]


def build_file_message(
    file_uri: str,
    mime_type: str,
    task: str,
    system_prompt: str = None
) -> List[Dict[str, Any]]:
    """
    Build a multimodal message with a file reference (Files API).
    
    Uses 'file_data' for Gemini Files API compatibility.
    
    Args:
        file_uri: URI of the file (e.g., from Files API upload).
        mime_type: MIME type of the file.
        task: The user's instruction.
        system_prompt: The system instruction (optional).
        
    Returns:
        List of message dictionaries.
    """
    message = {
        "role": "user",
        "content": [
            {
                "type": "file_data",
                "file_data": {
                    "mime_type": mime_type,
                    "file_uri": file_uri
                }
            },
            {"type": "text", "text": task}
        ]
    }
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append(message)
    
    return messages

def build_inline_message(
    data_b64: str,
    mime_type: str,
    task: str,
    system_prompt: str = None
) -> List[Dict[str, Any]]:
    """
    Build a multimodal message with inline data (generic).
    
    Uses 'inline_data' for Gemini Native compatibility.
    Suitable for audio, video, or small images/files.
    
    Args:
        data_b64: Base64 encoded data.
        mime_type: MIME type of the data.
        task: The user's instruction.
        system_prompt: The system instruction (optional).
        
    Returns:
        List of message dictionaries.
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    
    messages.append({
        "role": "user",
        "content": [
            {
                "type": "inline_data",
                "inline_data": {
                    "mime_type": mime_type,
                    "data": data_b64
                }
            },
            {"type": "text", "text": task}
        ]
    })
    
    return messages
