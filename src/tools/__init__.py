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

from .audio_processor import (
    AUDIO_PRESETS,
    BITRATE_OPTIONS,
    SAMPLE_RATE_OPTIONS,
    AudioChunk,
    # Voice enhancement system
    AudioEffect,
    AudioInfo,
    AudioPreset,
    # Core classes
    AudioProcessor,
    ChunkingResult,
    Intensity,
    # Output optimization
    OutputOptimization,
    ProcessingResult,
    # Utility functions
    check_ffmpeg_available,
    get_all_presets,
    # Preset functions
    get_preset,
    get_presets_by_category,
    is_audio_file,
    needs_chunking,
)
from .base import BaseTool, ToolResult, ToolStatus
from .checkpoint import CheckpointManager, FileProcessorCheckpoint, TTSCheckpoint, TTSCheckpointManager
from .config import (
    TOOLS_CONFIG_FILE,
    ensure_tools_config,
    get_default_config,
    get_file_processor_prompts,
    get_prompt_by_key,
    get_setting,
    list_available_prompts,
    load_tools_config,
)
from .file_handler import FileHandler, FileInfo, ScanResult
from .file_processor import FileProcessor, show_tools_menu
from .tts_processor import TTSProcessor

__all__ = [
    "AUDIO_PRESETS",
    "BITRATE_OPTIONS",
    "SAMPLE_RATE_OPTIONS",
    "TOOLS_CONFIG_FILE",
    "AudioChunk",
    # Audio processor - voice enhancement
    "AudioEffect",
    "AudioInfo",
    "AudioPreset",
    # Audio processor - core
    "AudioProcessor",
    # Base classes
    "BaseTool",
    # Checkpoint
    "CheckpointManager",
    "ChunkingResult",
    # File handling
    "FileHandler",
    "FileInfo",
    # File Processor
    "FileProcessor",
    "FileProcessorCheckpoint",
    "Intensity",
    # Audio processor - output optimization
    "OutputOptimization",
    "ProcessingResult",
    "ScanResult",
    "TTSCheckpoint",
    "TTSCheckpointManager",
    # TTS Processor
    "TTSProcessor",
    "ToolResult",
    "ToolStatus",
    # Audio processor - utilities
    "check_ffmpeg_available",
    "ensure_tools_config",
    "get_all_presets",
    "get_default_config",
    "get_file_processor_prompts",
    "get_preset",
    "get_presets_by_category",
    "get_prompt_by_key",
    "get_setting",
    "is_audio_file",
    "list_available_prompts",
    # Config
    "load_tools_config",
    "needs_chunking",
    "show_tools_menu",
]
