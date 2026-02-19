#!/usr/bin/env python3
"""
Tools Package - AI-powered file processing tools

This package provides tools for batch processing files with AI.
Currently includes:
- File Processor: Process images, audio, text, and code files with AI prompts
- Audio Processor: Split/amplify/normalize audio files with voice enhancement (requires FFmpeg)
  - 8 voice enhancement presets with Low/Medium/High intensity
  - Advanced mode for custom effect chains
"""

from .base import BaseTool, ToolResult, ToolStatus
from .file_handler import FileHandler, FileInfo, ScanResult
from .checkpoint import CheckpointManager, FileProcessorCheckpoint, TTSCheckpoint, TTSCheckpointManager
from .config import (
    load_tools_config,
    get_file_processor_prompts,
    get_prompt_by_key,
    get_setting,
    list_available_prompts,
    resolve_endpoint_prompt,
    ensure_tools_config,
    get_default_config,
    TOOLS_CONFIG_FILE,
)
from .audio_processor import (
    # Core classes
    AudioProcessor,
    AudioInfo,
    AudioChunk,
    ChunkingResult,
    ProcessingResult,
    # Voice enhancement system
    AudioEffect,
    AudioPreset,
    Intensity,
    # Output optimization
    OutputOptimization,
    SAMPLE_RATE_OPTIONS,
    BITRATE_OPTIONS,
    # Preset functions
    get_preset,
    get_all_presets,
    get_presets_by_category,
    AUDIO_PRESETS,
    # Utility functions
    check_ffmpeg_available,
    needs_chunking,
    is_audio_file,
)
from .file_processor import FileProcessor, show_tools_menu
from .tts_processor import TTSProcessor

__all__ = [
    # Base classes
    "BaseTool",
    "ToolResult",
    "ToolStatus",
    # File handling
    "FileHandler",
    "FileInfo",
    "ScanResult",
    # Audio processor - core
    "AudioProcessor",
    "AudioInfo",
    "AudioChunk",
    "ChunkingResult",
    "ProcessingResult",
    # Audio processor - voice enhancement
    "AudioEffect",
    "AudioPreset",
    "Intensity",
    "get_preset",
    "get_all_presets",
    "get_presets_by_category",
    "AUDIO_PRESETS",
    # Audio processor - output optimization
    "OutputOptimization",
    "SAMPLE_RATE_OPTIONS",
    "BITRATE_OPTIONS",
    # Audio processor - utilities
    "check_ffmpeg_available",
    "needs_chunking",
    "is_audio_file",
    # Checkpoint
    "CheckpointManager",
    "FileProcessorCheckpoint",
    "TTSCheckpoint",
    "TTSCheckpointManager",
    # Config
    "load_tools_config",
    "get_file_processor_prompts",
    "get_prompt_by_key",
    "get_setting",
    "list_available_prompts",
    "resolve_endpoint_prompt",
    "ensure_tools_config",
    "get_default_config",
    "TOOLS_CONFIG_FILE",
    # File Processor
    "FileProcessor",
    "show_tools_menu",
    # TTS Processor
    "TTSProcessor",
]
