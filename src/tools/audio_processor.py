#!/usr/bin/env python3
"""
Audio Processor - Process audio files using FFmpeg

Handles:
- FFmpeg availability detection
- Audio duration and bitrate analysis
- Splitting audio into ~15 MB chunks
- Volume amplification/normalization
- Voice enhancement presets with intensity levels
- Advanced custom filter chains
- Output text merging after processing
"""

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from src.audio.ffmpeg_utils import (
    is_ffmpeg_available as _is_ffmpeg_available,
    is_ffprobe_available as _is_ffprobe_available,
    is_ffplay_available as _is_ffplay_available,
    get_ffmpeg_path,
    get_ffprobe_path,
    get_ffplay_path,
    get_ffmpeg_version as _get_ffmpeg_version,
    get_creation_flags,
)
from src.console import console, print_warning, print_info, print_error, print_success


# Target chunk size in bytes (~14.5 MB to stay safely under 15 MB limit after base64)
TARGET_CHUNK_SIZE_BYTES = 14.5 * 1024 * 1024

# Supported audio formats
AUDIO_EXTENSIONS = {".mp3", ".wav", ".aiff", ".aac", ".ogg", ".flac", ".m4a", ".wma"}


# =============================================================================
# AUDIO EFFECTS SYSTEM
# =============================================================================

class Intensity(Enum):
    """Effect intensity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class AudioEffect:
    """Single FFmpeg audio filter with parameters"""
    name: str           # Filter name (e.g., "highpass")
    params: Dict[str, Any] = field(default_factory=dict)  # Filter parameters
    description: str = ""  # Human-readable description
    
    def to_filter_string(self) -> str:
        """Convert to FFmpeg filter syntax"""
        if not self.params:
            return self.name
        params_str = ":".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.name}={params_str}"
    
    def with_params(self, **kwargs) -> 'AudioEffect':
        """Create a copy with modified parameters"""
        new_params = {**self.params, **kwargs}
        return AudioEffect(self.name, new_params, self.description)


@dataclass
class AudioPreset:
    """Collection of effects forming a preset with intensity variants"""
    id: str
    name: str
    description: str
    category: str  # "voice", "cleanup", "volume", "custom"
    effects_by_intensity: Dict[Intensity, List[AudioEffect]] = field(default_factory=dict)
    
    def get_effects(self, intensity: Intensity = Intensity.MEDIUM) -> List[AudioEffect]:
        """Get effects for specified intensity"""
        return self.effects_by_intensity.get(intensity, [])
    
    def to_filter_chain(self, intensity: Intensity = Intensity.MEDIUM) -> str:
        """Convert to FFmpeg -af chain for specified intensity"""
        effects = self.get_effects(intensity)
        if not effects:
            return ""
        return ",".join(e.to_filter_string() for e in effects)
    
    @property
    def available_intensities(self) -> List[Intensity]:
        """Get list of available intensity levels"""
        return list(self.effects_by_intensity.keys())


# =============================================================================
# BUILT-IN PRESETS
# =============================================================================

def _create_voice_clarity_preset() -> AudioPreset:
    """Voice Clarity - Enhance speech intelligibility"""
    return AudioPreset(
        id="voice_clarity",
        name="🎤 Voice Clarity",
        description="Enhance speech intelligibility with EQ and normalization",
        category="voice",
        effects_by_intensity={
            Intensity.LOW: [
                AudioEffect("highpass", {"f": 60}, "Remove very low rumble"),
                AudioEffect("speechnorm", {"e": 6.25, "r": 0.00001, "l": 1}, "Light speech normalization"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "EBU R128 loudness"),
            ],
            Intensity.MEDIUM: [
                AudioEffect("highpass", {"f": 80}, "Remove low rumble"),
                AudioEffect("speechnorm", {"e": 12.5, "r": 0.0001, "l": 1}, "Speech normalization"),
                AudioEffect("equalizer", {"f": 3000, "t": "q", "w": 1.5, "g": 2}, "Boost presence"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "EBU R128 loudness"),
            ],
            Intensity.HIGH: [
                AudioEffect("highpass", {"f": 100}, "Remove rumble"),
                AudioEffect("speechnorm", {"e": 20, "r": 0.0001, "l": 1}, "Strong speech normalization"),
                AudioEffect("equalizer", {"f": 200, "t": "q", "w": 2, "g": -2}, "Reduce mud"),
                AudioEffect("equalizer", {"f": 3000, "t": "q", "w": 1.5, "g": 4}, "Boost presence"),
                AudioEffect("equalizer", {"f": 5000, "t": "q", "w": 2, "g": 2}, "Add clarity"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "EBU R128 loudness"),
            ],
        }
    )


def _create_noise_reduction_preset() -> AudioPreset:
    """Noise Reduction - Remove background noise"""
    return AudioPreset(
        id="noise_reduction",
        name="🔇 Noise Reduction",
        description="Remove background noise and hiss",
        category="cleanup",
        effects_by_intensity={
            Intensity.LOW: [
                AudioEffect("afftdn", {"nr": 8, "nf": -50, "tn": 1}, "Light FFT denoising"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
            Intensity.MEDIUM: [
                AudioEffect("afftdn", {"nr": 15, "nf": -40, "tn": 1}, "Medium FFT denoising"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
            Intensity.HIGH: [
                AudioEffect("afftdn", {"nr": 25, "nf": -30, "tn": 1}, "Strong FFT denoising"),
                AudioEffect("anlmdn", {"s": 0.3, "p": 0.002, "r": 0.002}, "Non-local means denoise"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
        }
    )


def _create_podcast_preset() -> AudioPreset:
    """Podcast Ready - Broadcast-quality voice processing"""
    return AudioPreset(
        id="podcast",
        name="🎙️ Podcast Ready",
        description="Broadcast-quality voice processing for podcasts/videos",
        category="voice",
        effects_by_intensity={
            Intensity.LOW: [
                AudioEffect("highpass", {"f": 80}, "Remove rumble"),
                AudioEffect("compand", {
                    "attacks": 0.1,
                    "decays": 0.3,
                    "points": "-80/-80|-45/-45|-30/-30|-20/-25|0/-10"
                }, "Light compression"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Broadcast loudness"),
            ],
            Intensity.MEDIUM: [
                AudioEffect("highpass", {"f": 80}, "Remove rumble"),
                AudioEffect("equalizer", {"f": 120, "t": "q", "w": 2, "g": 1}, "Add warmth"),
                AudioEffect("compand", {
                    "attacks": 0.08,
                    "decays": 0.25,
                    "points": "-80/-80|-45/-45|-27/-27|-20/-23|-10/-15|0/-8"
                }, "Medium compression"),
                AudioEffect("equalizer", {"f": 3500, "t": "q", "w": 1.5, "g": 2}, "Presence boost"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Broadcast loudness"),
            ],
            Intensity.HIGH: [
                AudioEffect("highpass", {"f": 100}, "Remove rumble"),
                AudioEffect("lowpass", {"f": 14000}, "Remove ultra-high hiss"),
                AudioEffect("equalizer", {"f": 120, "t": "q", "w": 2, "g": 2}, "Add warmth"),
                AudioEffect("equalizer", {"f": 300, "t": "q", "w": 2, "g": -2}, "Reduce mud"),
                AudioEffect("compand", {
                    "attacks": 0.05,
                    "decays": 0.2,
                    "points": "-80/-80|-45/-45|-25/-25|-18/-20|-10/-12|-5/-8|0/-5"
                }, "Strong compression"),
                AudioEffect("equalizer", {"f": 3500, "t": "q", "w": 1.5, "g": 3}, "Presence boost"),
                AudioEffect("equalizer", {"f": 7000, "t": "q", "w": 2, "g": 1}, "Air/brightness"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Broadcast loudness"),
            ],
        }
    )


def _create_phone_recording_preset() -> AudioPreset:
    """Phone Recording - Enhance low-quality phone/voice memo audio"""
    return AudioPreset(
        id="phone_recording",
        name="📱 Phone Recording",
        description="Enhance low-quality phone and voice memo recordings",
        category="voice",
        effects_by_intensity={
            Intensity.LOW: [
                AudioEffect("highpass", {"f": 80}, "Remove phone rumble"),
                AudioEffect("lowpass", {"f": 12000}, "Remove ultra-high hiss"),
                AudioEffect("speechnorm", {"e": 6.25, "r": 0.00001, "l": 1}, "Light speech normalization"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
            Intensity.MEDIUM: [
                AudioEffect("highpass", {"f": 100}, "Remove phone rumble"),
                AudioEffect("lowpass", {"f": 10000}, "Remove harsh highs"),
                AudioEffect("afftdn", {"nr": 10, "nf": -45, "tn": 1}, "Reduce phone noise"),
                AudioEffect("speechnorm", {"e": 12.5, "r": 0.0001, "l": 1}, "Normalize speech"),
                AudioEffect("equalizer", {"f": 3000, "t": "q", "w": 1.5, "g": 2}, "Restore clarity"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
            Intensity.HIGH: [
                AudioEffect("highpass", {"f": 120}, "Aggressive rumble removal"),
                AudioEffect("lowpass", {"f": 8500}, "Remove harsh highs"),
                AudioEffect("afftdn", {"nr": 15, "nf": -40, "tn": 1}, "Strong noise reduction"),
                AudioEffect("speechnorm", {"e": 20, "r": 0.0001, "l": 1}, "Balanced normalization"),
                AudioEffect("equalizer", {"f": 200, "t": "q", "w": 2, "g": -2}, "Reduce mud"),
                AudioEffect("equalizer", {"f": 3000, "t": "q", "w": 1.5, "g": 4}, "Restore clarity"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
        }
    )


def _create_dynamic_volume_preset() -> AudioPreset:
    """Dynamic Volume - Even out quiet and loud sections"""
    return AudioPreset(
        id="dynamic_volume",
        name="📊 Dynamic Volume",
        description="Even out volume differences between quiet and loud sections",
        category="volume",
        effects_by_intensity={
            Intensity.LOW: [
                AudioEffect("dynaudnorm", {"f": 500, "g": 5, "p": 0.9}, "Light dynamic normalization"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Final loudness"),
            ],
            Intensity.MEDIUM: [
                AudioEffect("dynaudnorm", {"f": 300, "g": 10, "p": 0.9}, "Medium dynamic normalization"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Final loudness"),
            ],
            Intensity.HIGH: [
                AudioEffect("dynaudnorm", {"f": 150, "g": 20, "p": 0.95}, "Strong dynamic normalization"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Final loudness"),
            ],
        }
    )


def _create_boost_quiet_preset() -> AudioPreset:
    """Boost Quiet Speech - Amplify quiet sections without clipping"""
    return AudioPreset(
        id="boost_quiet",
        name="🔊 Boost Quiet Speech",
        description="Amplify quiet speech sections while preventing clipping",
        category="volume",
        effects_by_intensity={
            Intensity.LOW: [
                AudioEffect("speechnorm", {"e": 6.25, "r": 0.00001, "l": 1}, "Light speech-aware boost"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
            Intensity.MEDIUM: [
                AudioEffect("speechnorm", {"e": 12.5, "r": 0.0001, "l": 1}, "Medium speech boost"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
            Intensity.HIGH: [
                AudioEffect("speechnorm", {"e": 20, "r": 0.0001, "l": 1}, "Strong speech boost"),
                AudioEffect("loudnorm", {"I": -14, "LRA": 7, "TP": -1.5}, "Louder target"),
            ],
        }
    )


def _create_de_ess_preset() -> AudioPreset:
    """De-Ess - Reduce harsh sibilance (s/sh sounds)"""
    return AudioPreset(
        id="de_ess",
        name="🐍 De-Ess (Reduce Sibilance)",
        description="Reduce harsh 's' and 'sh' sounds in speech",
        category="cleanup",
        effects_by_intensity={
            Intensity.LOW: [
                AudioEffect("equalizer", {"f": 6000, "t": "q", "w": 1, "g": -2}, "Light de-ess"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
            Intensity.MEDIUM: [
                AudioEffect("equalizer", {"f": 5500, "t": "q", "w": 1, "g": -3}, "De-ess lower sibilance"),
                AudioEffect("equalizer", {"f": 7500, "t": "q", "w": 1, "g": -3}, "De-ess upper sibilance"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
            Intensity.HIGH: [
                AudioEffect("equalizer", {"f": 5000, "t": "q", "w": 0.8, "g": -4}, "Strong de-ess low"),
                AudioEffect("equalizer", {"f": 6500, "t": "q", "w": 0.8, "g": -4}, "Strong de-ess mid"),
                AudioEffect("equalizer", {"f": 8000, "t": "q", "w": 0.8, "g": -4}, "Strong de-ess high"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
        }
    )


def _create_room_echo_reduction_preset() -> AudioPreset:
    """Room Echo Reduction - Reduce reverb and room echo"""
    return AudioPreset(
        id="room_echo",
        name="🏠 Room Echo Reduction",
        description="Reduce reverb and room echo (limited effectiveness)",
        category="cleanup",
        effects_by_intensity={
            Intensity.LOW: [
                AudioEffect("highpass", {"f": 80}, "Remove low rumble"),
                AudioEffect("afftdn", {"nr": 5, "nf": -60, "tn": 1}, "Light reverb reduction"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
            Intensity.MEDIUM: [
                AudioEffect("highpass", {"f": 100}, "Remove low reverb"),
                AudioEffect("afftdn", {"nr": 10, "nf": -50, "tn": 1}, "Reverb reduction"),
                AudioEffect("compand", {
                    "attacks": 0.05,
                    "decays": 0.2,
                    "points": "-80/-80|-45/-45|-30/-32|-20/-22|0/-10"
                }, "Gentle expansion"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
            Intensity.HIGH: [
                AudioEffect("highpass", {"f": 120}, "Remove low reverb"),
                AudioEffect("afftdn", {"nr": 18, "nf": -45, "tn": 1}, "Strong reverb reduction"),
                AudioEffect("compand", {
                    "attacks": 0.02,
                    "decays": 0.1,
                    "points": "-80/-80|-40/-45|-25/-30|-15/-20|0/-8"
                }, "Medium gate"),
                AudioEffect("loudnorm", {"I": -16, "LRA": 11, "TP": -1.5}, "Normalize"),
            ],
        }
    )


# Registry of all built-in presets
AUDIO_PRESETS: Dict[str, AudioPreset] = {}


def _init_presets():
    """Initialize built-in presets"""
    global AUDIO_PRESETS
    presets = [
        _create_voice_clarity_preset(),
        _create_noise_reduction_preset(),
        _create_podcast_preset(),
        _create_phone_recording_preset(),
        _create_dynamic_volume_preset(),
        _create_boost_quiet_preset(),
        _create_de_ess_preset(),
        _create_room_echo_reduction_preset(),
    ]
    AUDIO_PRESETS = {p.id: p for p in presets}


_init_presets()


def get_preset(preset_id: str) -> Optional[AudioPreset]:
    """Get a preset by ID"""
    return AUDIO_PRESETS.get(preset_id)


def get_all_presets() -> List[AudioPreset]:
    """Get all available presets"""
    return list(AUDIO_PRESETS.values())


def get_presets_by_category(category: str) -> List[AudioPreset]:
    """Get presets filtered by category"""
    return [p for p in AUDIO_PRESETS.values() if p.category == category]


# =============================================================================
# OUTPUT OPTIMIZATION OPTIONS
# =============================================================================

@dataclass
class OutputOptimization:
    """
    Audio output optimization settings for file size reduction.
    
    Optimized for voice/speech and AI processing.
    """
    # Channel settings
    convert_to_mono: bool = False  # Convert stereo/multichannel to mono
    
    # Sample rate (Hz) - None means keep original
    # Recommended for voice: 16000 (smallest), 22050 (good), 44100 (high quality)
    sample_rate: Optional[int] = None
    
    # Bitrate (kbps) - None means use codec default
    # Recommended for voice: 32 (min), 48 (phone), 64 (good), 96 (high), 128 (default)
    bitrate_kbps: Optional[int] = None
    
    def to_ffmpeg_args(self) -> List[str]:
        """Convert to FFmpeg command-line arguments"""
        args = []
        
        if self.convert_to_mono:
            # -ac 1 forces mono output, properly downmixing stereo
            args.extend(["-ac", "1"])
        
        if self.sample_rate:
            args.extend(["-ar", str(self.sample_rate)])
        
        if self.bitrate_kbps:
            args.extend(["-b:a", f"{self.bitrate_kbps}k"])
        
        return args
    
    def describe(self) -> str:
        """Human-readable description of settings"""
        parts = []
        
        if self.convert_to_mono:
            parts.append("Mono")
        
        if self.sample_rate:
            parts.append(f"{self.sample_rate} Hz")
        
        if self.bitrate_kbps:
            parts.append(f"{self.bitrate_kbps} kbps")
        
        return ", ".join(parts) if parts else "No optimization"
    
    @classmethod
    def for_voice_small(cls) -> 'OutputOptimization':
        """Preset: Smallest file size for voice (phone quality)"""
        return cls(convert_to_mono=True, sample_rate=16000, bitrate_kbps=32)
    
    @classmethod
    def for_voice_balanced(cls) -> 'OutputOptimization':
        """Preset: Balanced quality/size for voice (recommended)"""
        return cls(convert_to_mono=True, sample_rate=22050, bitrate_kbps=64)
    
    @classmethod
    def for_voice_quality(cls) -> 'OutputOptimization':
        """Preset: Higher quality voice"""
        return cls(convert_to_mono=True, sample_rate=44100, bitrate_kbps=96)
    
    @classmethod
    def mono_only(cls) -> 'OutputOptimization':
        """Preset: Just convert to mono, keep other settings"""
        return cls(convert_to_mono=True)


# Voice-optimized sample rate options
SAMPLE_RATE_OPTIONS = {
    16000: "16 kHz - Phone quality (smallest, good for AI)",
    22050: "22 kHz - Voice optimized (recommended for speech)",
    32000: "32 kHz - FM radio quality",
    44100: "44 kHz - CD quality (larger files)",
    48000: "48 kHz - Professional (largest)",
}

# Voice-optimized bitrate options (for MP3/AAC)
BITRATE_OPTIONS = {
    32: "32 kbps - Very compressed (smallest, phone quality)",
    48: "48 kbps - Compressed (phone/voice memo quality)",
    64: "64 kbps - Good for speech (recommended)",
    96: "96 kbps - High quality voice",
    128: "128 kbps - Default quality (larger files)",
    192: "192 kbps - High quality (unnecessary for voice)",
}


@dataclass
class AudioInfo:
    """Information about an audio file"""
    path: Path
    duration_seconds: float
    bitrate_kbps: float
    size_bytes: int
    format: str
    sample_rate: int = 0
    channels: int = 0
    volume_db: float = 0.0  # Peak volume in dB
    
    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)
    
    @property
    def estimated_chunk_count(self) -> int:
        """Estimate number of chunks needed"""
        if self.size_bytes <= TARGET_CHUNK_SIZE_BYTES:
            return 1
        return max(1, int(self.size_bytes / TARGET_CHUNK_SIZE_BYTES) + 1)
    
    @property
    def is_mono(self) -> bool:
        """Check if audio is mono"""
        return self.channels == 1
    
    @property
    def is_stereo(self) -> bool:
        """Check if audio is stereo"""
        return self.channels == 2
    
    @property
    def is_multichannel(self) -> bool:
        """Check if audio has more than 2 channels"""
        return self.channels > 2


@dataclass
class AudioChunk:
    """A single chunk of audio"""
    path: Path
    index: int
    start_time: float
    end_time: float
    duration: float
    size_bytes: int
    
    @property
    def time_range_str(self) -> str:
        """Format time range as MM:SS - MM:SS"""
        def fmt(secs):
            m, s = divmod(int(secs), 60)
            return f"{m:02d}:{s:02d}"
        return f"{fmt(self.start_time)} - {fmt(self.end_time)}"


@dataclass
class ChunkingResult:
    """Result of chunking operation"""
    success: bool
    chunks: List[AudioChunk] = field(default_factory=list)
    temp_dir: Optional[Path] = None
    error: Optional[str] = None
    original_info: Optional[AudioInfo] = None
    
    def cleanup(self):
        """Remove temporary chunk files"""
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)


@dataclass
class ProcessingResult:
    """Result of audio processing operation"""
    success: bool
    output_path: Optional[Path] = None
    error: Optional[str] = None
    original_info: Optional[AudioInfo] = None
    temp_file: bool = False  # True if output is a temp file that needs cleanup
    
    def cleanup(self):
        """Remove temp file if applicable"""
        if self.temp_file and self.output_path and self.output_path.exists():
            try:
                self.output_path.unlink()
            except Exception:
                pass


class AudioProcessor:
    """
    Handle audio file processing including chunking and volume adjustments.
    
    Uses FFmpeg for all audio operations. Requires FFmpeg to be
    installed and available on the system PATH.
    
    Binary detection is delegated to ``src.audio.ffmpeg_utils`` which
    caches PATH lookups at the module level for efficiency.
    """
    
    def is_available(self) -> bool:
        """Check if FFmpeg and FFprobe are available on PATH (cached)."""
        return _is_ffmpeg_available() and _is_ffprobe_available()
    
    def is_ffplay_available(self) -> bool:
        """Check if FFplay is available for audio preview (cached)."""
        return _is_ffplay_available()
    
    def get_ffmpeg_version(self) -> Optional[str]:
        """Get FFmpeg version string."""
        return _get_ffmpeg_version()
    
    def get_audio_info(self, filepath: Path) -> Optional[AudioInfo]:
        """
        Get detailed information about an audio file.
        
        Args:
            filepath: Path to audio file
            
        Returns:
            AudioInfo or None if ffprobe fails
        """
        if not self.is_available():
            return None
        
        try:
            result = subprocess.run(
                [
                    get_ffprobe_path(),
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    "-show_streams",
                    str(filepath)
                ],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=get_creation_flags()
            )
            
            if result.returncode != 0:
                return None
            
            data = json.loads(result.stdout)
            fmt = data.get("format", {})
            
            # Find audio stream
            audio_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "audio":
                    audio_stream = stream
                    break
            
            duration = float(fmt.get("duration", 0))
            size = int(fmt.get("size", filepath.stat().st_size))
            bitrate = float(fmt.get("bit_rate", 0)) / 1000  # Convert to kbps
            
            return AudioInfo(
                path=filepath,
                duration_seconds=duration,
                bitrate_kbps=bitrate,
                size_bytes=size,
                format=fmt.get("format_name", "unknown"),
                sample_rate=int(audio_stream.get("sample_rate", 0)) if audio_stream else 0,
                channels=int(audio_stream.get("channels", 0)) if audio_stream else 0
            )
        
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
            print_error(f"Failed to get audio info: {e}")
            return None
    
    def get_peak_volume(self, filepath: Path) -> Optional[float]:
        """
        Analyze audio to get peak volume level.
        
        Args:
            filepath: Path to audio file
            
        Returns:
            Peak volume in dB (negative values, 0 = max) or None on error
        """
        if not self.is_available():
            return None
        
        try:
            result = subprocess.run(
                [
                    get_ffmpeg_path(),
                    "-i", str(filepath),
                    "-af", "volumedetect",
                    "-f", "null",
                    "-"
                ],
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=get_creation_flags()
            )
            
            # Parse output for max_volume
            for line in result.stderr.split("\n"):
                if "max_volume" in line:
                    # Format: [Parsed_volumedetect_0 @ ...] max_volume: -5.2 dB
                    parts = line.split("max_volume:")
                    if len(parts) > 1:
                        vol_str = parts[1].strip().replace("dB", "").strip()
                        return float(vol_str)
            
            return None
        except Exception as e:
            print_error(f"Failed to analyze volume: {e}")
            return None
    
    def amplify_volume(
        self,
        filepath: Path,
        volume_change_db: Optional[float] = None,
        volume_percent: Optional[int] = None,
        normalize: bool = False,
        output_path: Optional[Path] = None
    ) -> ProcessingResult:
        """
        Amplify or adjust audio volume.
        
        Args:
            filepath: Path to audio file
            volume_change_db: Volume change in decibels (e.g., 5 for +5dB)
            volume_percent: Volume as percentage (e.g., 150 for 150%)
            normalize: If True, use EBU R128 loudness normalization (same as preview)
            output_path: Where to save output. If None, creates temp file.
            
        Returns:
            ProcessingResult with output path
            
        Note: Provide either volume_change_db OR volume_percent, not both.
              normalize uses the loudnorm filter for consistent loudness.
        """
        if not self.is_available():
            return ProcessingResult(
                success=False,
                error="FFmpeg not available on PATH"
            )
        
        audio_info = self.get_audio_info(filepath)
        if not audio_info:
            return ProcessingResult(
                success=False,
                error=f"Could not analyze audio file: {filepath}"
            )
        
        # Determine volume filter
        volume_filter = None
        
        if normalize:
            # Use EBU R128 loudness normalization (same as preview)
            # I=-16 = integrated loudness target (-16 LUFS)
            # LRA=11 = loudness range target
            # TP=-1.5 = true peak limit (-1.5 dBTP)
            volume_filter = "loudnorm=I=-16:LRA=11:TP=-1.5"
            print_info("Normalizing with EBU R128 loudness standard")
        elif volume_change_db is not None:
            # dB adjustment
            volume_filter = f"volume={volume_change_db}dB"
        elif volume_percent is not None:
            # Percentage adjustment (100 = no change, 200 = double)
            volume_multiplier = volume_percent / 100.0
            volume_filter = f"volume={volume_multiplier}"
        else:
            return ProcessingResult(
                success=False,
                error="Must specify volume_change_db, volume_percent, or normalize=True"
            )
        
        # Determine output path
        temp_file = False
        if output_path is None:
            # Create temp file with same extension
            suffix = filepath.suffix or ".mp3"
            fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix="amplified_")
            os.close(fd)
            output_path = Path(temp_path)
            temp_file = True
        
        try:
            # Build command - always re-encode when using audio filters
            cmd = [
                get_ffmpeg_path(),
                "-y",  # Overwrite
                "-i", str(filepath),
                "-af", volume_filter,
            ]
            
            # Choose codec based on output format
            if output_path.suffix.lower() == ".mp3":
                cmd.extend(["-c:a", "libmp3lame", "-q:a", "2"])  # High quality MP3
            elif output_path.suffix.lower() == ".m4a":
                cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            elif output_path.suffix.lower() == ".flac":
                cmd.extend(["-c:a", "flac"])
            elif output_path.suffix.lower() == ".wav":
                cmd.extend(["-c:a", "pcm_s16le"])
            # else: let FFmpeg auto-select codec
            
            cmd.append(str(output_path))
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                creationflags=get_creation_flags()
            )
            
            if result.returncode != 0:
                if temp_file:
                    output_path.unlink(missing_ok=True)
                return ProcessingResult(
                    success=False,
                    error=f"FFmpeg failed: {result.stderr[:500]}"
                )
            
            return ProcessingResult(
                success=True,
                output_path=output_path,
                original_info=audio_info,
                temp_file=temp_file
            )
        
        except Exception as e:
            if temp_file and output_path.exists():
                output_path.unlink(missing_ok=True)
            return ProcessingResult(
                success=False,
                error=str(e)
            )
    
    def apply_preset(
        self,
        filepath: Path,
        preset_id: str,
        intensity: Intensity = Intensity.MEDIUM,
        output_path: Optional[Path] = None,
        optimization: Optional[OutputOptimization] = None
    ) -> ProcessingResult:
        """
        Apply a voice enhancement preset to an audio file.
        
        Args:
            filepath: Path to audio file
            preset_id: ID of the preset to apply (e.g., "voice_clarity")
            intensity: Intensity level (LOW, MEDIUM, HIGH)
            output_path: Where to save output. If None, creates temp file.
            optimization: Optional output optimization settings (mono, bitrate, sample rate)
            
        Returns:
            ProcessingResult with output path
        """
        preset = get_preset(preset_id)
        if not preset:
            return ProcessingResult(
                success=False,
                error=f"Unknown preset: {preset_id}"
            )
        
        filter_chain = preset.to_filter_chain(intensity)
        if not filter_chain:
            return ProcessingResult(
                success=False,
                error=f"Preset {preset_id} has no effects for intensity {intensity.value}"
            )
        
        print_info(f"Applying preset: {preset.name} ({intensity.value})")
        return self.apply_filter_chain(filepath, filter_chain, output_path, optimization)
    
    def apply_effects(
        self,
        filepath: Path,
        effects: List[AudioEffect],
        output_path: Optional[Path] = None,
        optimization: Optional[OutputOptimization] = None
    ) -> ProcessingResult:
        """
        Apply a custom list of audio effects to a file.
        
        Args:
            filepath: Path to audio file
            effects: List of AudioEffect objects to apply
            output_path: Where to save output. If None, creates temp file.
            optimization: Optional output optimization settings
            
        Returns:
            ProcessingResult with output path
        """
        if not effects:
            return ProcessingResult(
                success=False,
                error="No effects specified"
            )
        
        filter_chain = ",".join(e.to_filter_string() for e in effects)
        print_info(f"Applying {len(effects)} custom effects")
        return self.apply_filter_chain(filepath, filter_chain, output_path, optimization)
    
    def apply_filter_chain(
        self,
        filepath: Path,
        filter_chain: str,
        output_path: Optional[Path] = None,
        optimization: Optional[OutputOptimization] = None
    ) -> ProcessingResult:
        """
        Apply an FFmpeg audio filter chain to a file.
        
        Args:
            filepath: Path to audio file
            filter_chain: FFmpeg -af filter string (e.g., "highpass=f=80,loudnorm")
            output_path: Where to save output. If None, creates temp file.
            optimization: Optional output optimization settings (mono, bitrate, sample rate)
            
        Returns:
            ProcessingResult with output path
        """
        if not self.is_available():
            return ProcessingResult(
                success=False,
                error="FFmpeg not available on PATH"
            )
        
        audio_info = self.get_audio_info(filepath)
        if not audio_info:
            return ProcessingResult(
                success=False,
                error=f"Could not analyze audio file: {filepath}"
            )
        
        # Determine output path
        temp_file = False
        if output_path is None:
            suffix = filepath.suffix or ".mp3"
            fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix="processed_")
            os.close(fd)
            output_path = Path(temp_path)
            temp_file = True
        
        try:
            cmd = [
                get_ffmpeg_path(),
                "-y",  # Overwrite
                "-i", str(filepath),
            ]
            
            # Add filter chain if provided
            if filter_chain:
                cmd.extend(["-af", filter_chain])
            
            # Add optimization settings (before codec selection)
            if optimization:
                opt_args = optimization.to_ffmpeg_args()
                if opt_args:
                    cmd.extend(opt_args)
                    print_info(f"Optimizing output: {optimization.describe()}")
            
            # Choose codec based on output format
            # Note: if optimization specifies bitrate, don't override with quality setting
            has_bitrate = optimization and optimization.bitrate_kbps
            
            if output_path.suffix.lower() == ".mp3":
                cmd.extend(["-c:a", "libmp3lame"])
                if not has_bitrate:
                    cmd.extend(["-q:a", "2"])  # High quality MP3
            elif output_path.suffix.lower() == ".m4a":
                cmd.extend(["-c:a", "aac"])
                if not has_bitrate:
                    cmd.extend(["-b:a", "192k"])
            elif output_path.suffix.lower() == ".flac":
                cmd.extend(["-c:a", "flac"])
            elif output_path.suffix.lower() == ".wav":
                cmd.extend(["-c:a", "pcm_s16le"])
            
            cmd.append(str(output_path))
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1200,  # Allow more time for complex filter chains
                creationflags=get_creation_flags()
            )
            
            if result.returncode != 0:
                if temp_file:
                    output_path.unlink(missing_ok=True)
                return ProcessingResult(
                    success=False,
                    error=f"FFmpeg failed: {result.stderr[:500]}"
                )
            
            return ProcessingResult(
                success=True,
                output_path=output_path,
                original_info=audio_info,
                temp_file=temp_file
            )
        
        except Exception as e:
            if temp_file and output_path.exists():
                output_path.unlink(missing_ok=True)
            return ProcessingResult(
                success=False,
                error=str(e)
            )
    
    def apply_optimization_only(
        self,
        filepath: Path,
        optimization: OutputOptimization,
        output_path: Optional[Path] = None
    ) -> ProcessingResult:
        """
        Apply only output optimization (mono, bitrate, sample rate) without effects.
        
        Args:
            filepath: Path to audio file
            optimization: Output optimization settings
            output_path: Where to save output. If None, creates temp file.
            
        Returns:
            ProcessingResult with output path
        """
        return self.apply_filter_chain(filepath, "", output_path, optimization)
    
    def preview_preset(
        self,
        filepath: Path,
        preset_id: str,
        intensity: Intensity = Intensity.MEDIUM,
        duration_seconds: float = 10.0,
        start_seconds: float = 0.0
    ) -> bool:
        """
        Preview a preset without creating a file.
        
        Args:
            filepath: Path to audio file
            preset_id: ID of the preset to preview
            intensity: Intensity level
            duration_seconds: Preview duration
            start_seconds: Start position
            
        Returns:
            True if preview played successfully
        """
        preset = get_preset(preset_id)
        if not preset:
            print_error(f"Unknown preset: {preset_id}")
            return False
        
        filter_chain = preset.to_filter_chain(intensity)
        if not filter_chain:
            print_error(f"Preset has no effects for this intensity")
            return False
        
        print_info(f"Previewing: {preset.name} ({intensity.value})")
        return self.preview_filter_chain(filepath, filter_chain, duration_seconds, start_seconds)
    
    def preview_effects(
        self,
        filepath: Path,
        effects: List[AudioEffect],
        duration_seconds: float = 10.0,
        start_seconds: float = 0.0
    ) -> bool:
        """
        Preview custom effects without creating a file.
        
        Args:
            filepath: Path to audio file
            effects: List of effects to preview
            duration_seconds: Preview duration
            start_seconds: Start position
            
        Returns:
            True if preview played successfully
        """
        if not effects:
            print_error("No effects to preview")
            return False
        
        filter_chain = ",".join(e.to_filter_string() for e in effects)
        return self.preview_filter_chain(filepath, filter_chain, duration_seconds, start_seconds)
    
    def preview_filter_chain(
        self,
        filepath: Path,
        filter_chain: str,
        duration_seconds: float = 10.0,
        start_seconds: float = 0.0
    ) -> bool:
        """
        Preview an FFmpeg filter chain without creating a file.
        
        Args:
            filepath: Path to audio file
            filter_chain: FFmpeg -af filter string
            duration_seconds: Preview duration
            start_seconds: Start position
            
        Returns:
            True if preview played successfully
        """
        if not self.is_ffplay_available():
            print_error("FFplay not available - cannot preview audio")
            return False
        
        try:
            cmd = [
                get_ffplay_path(),
                "-nodisp",
                "-autoexit",
                "-ss", str(start_seconds),
                "-t", str(duration_seconds),
                "-af", filter_chain,
                "-i", str(filepath)
            ]
            
            print_info(f"Previewing {duration_seconds}s... (press 'q' to stop)")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            self._wait_with_keypress(process, duration_seconds + 10)
            return True
        
        except Exception as e:
            print_error(f"Preview failed: {e}")
            return False
    
    def _wait_with_keypress(self, process: subprocess.Popen, timeout: float) -> bool:
        """
        Wait for process to complete, checking for 'q' key to stop early.
        
        Args:
            process: The subprocess to monitor
            timeout: Maximum time to wait
            
        Returns:
            True if completed normally, False if stopped by user
        """
        import time
        try:
            import msvcrt  # Windows-only
            has_msvcrt = True
        except ImportError:
            has_msvcrt = False
        
        start = time.time()
        while process.poll() is None:
            elapsed = time.time() - start
            if elapsed > timeout:
                process.terminate()
                break
            
            # Check for 'q' key press (Windows only)
            if has_msvcrt and msvcrt.kbhit():
                key = msvcrt.getch()
                if key.lower() == b'q':
                    process.terminate()
                    print("\n⏹️ Stopped by user")
                    return False
            
            time.sleep(0.1)  # Small delay to prevent CPU spinning
        
        return True
    
    def play_audio(
        self,
        filepath: Path,
        duration_seconds: Optional[float] = None,
        start_seconds: float = 0.0
    ) -> bool:
        """
        Play audio file using ffplay.
        
        Args:
            filepath: Path to audio file
            duration_seconds: Optional max duration to play (None = full file)
            start_seconds: Start position in seconds
            
        Returns:
            True if playback started successfully
        """
        if not self.is_ffplay_available():
            print_error("FFplay not available - cannot preview audio")
            return False
        
        try:
            cmd = [
                get_ffplay_path(),
                "-nodisp",  # No video display window
                "-autoexit",  # Exit when done
                "-ss", str(start_seconds),
            ]
            
            if duration_seconds:
                cmd.extend(["-t", str(duration_seconds)])
            
            cmd.extend(["-i", str(filepath)])
            
            # Run ffplay with Popen for better control
            print_info(f"Playing audio... (press 'q' to stop)")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Wait for process with keyboard check
            timeout = duration_seconds + 5 if duration_seconds else 3600
            self._wait_with_keypress(process, timeout)
            
            return True
        
        except Exception as e:
            print_error(f"Playback failed: {e}")
            return False
    
    def preview_with_effects(
        self,
        filepath: Path,
        volume_percent: Optional[int] = None,
        volume_db: Optional[float] = None,
        normalize: bool = False,
        duration_seconds: float = 10.0,
        start_seconds: float = 0.0
    ) -> bool:
        """
        Preview audio with effects applied (without creating a file).
        
        Args:
            filepath: Path to audio file
            volume_percent: Volume as percentage (100 = normal)
            volume_db: Volume adjustment in dB
            normalize: If True, normalize audio using EBU R128
            duration_seconds: Preview duration (default 10s)
            start_seconds: Start position
            
        Returns:
            True if preview played successfully
        """
        if not self.is_ffplay_available():
            print_error("FFplay not available - cannot preview audio")
            return False
        
        try:
            # Build audio filter
            filters = []
            
            if normalize:
                # Use EBU R128 loudness normalization (same as file processing)
                filters.append("loudnorm=I=-16:LRA=11:TP=-1.5")
            elif volume_db is not None:
                filters.append(f"volume={volume_db}dB")
            elif volume_percent is not None and volume_percent != 100:
                filters.append(f"volume={volume_percent / 100.0}")
            
            cmd = [
                get_ffplay_path(),
                "-nodisp",
                "-autoexit",
                "-ss", str(start_seconds),
                "-t", str(duration_seconds),
            ]
            
            if filters:
                cmd.extend(["-af", ",".join(filters)])
            
            cmd.extend(["-i", str(filepath)])
            
            # Run ffplay with Popen for better control
            print_info(f"Previewing {duration_seconds}s... (press 'q' to stop)")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Wait for process with keyboard check
            self._wait_with_keypress(process, duration_seconds + 5)
            
            return True
        
        except Exception as e:
            print_error(f"Preview failed: {e}")
            return False
    
    def estimate_chunk_duration(self, audio_info: AudioInfo, target_bitrate_kbps: Optional[float] = None) -> float:
        """
        Estimate duration per chunk to stay under size limit.
        
        Args:
            audio_info: Audio file information
            target_bitrate_kbps: Target bitrate if transcoding (to accurately predict size)
            
        Returns:
            Recommended chunk duration in seconds
        """
        if audio_info.size_bytes <= TARGET_CHUNK_SIZE_BYTES and not target_bitrate_kbps:
            return audio_info.duration_seconds
        
        # Calculate bytes per second
        # Use target bitrate if transcoding, else use estimated from file
        if target_bitrate_kbps and target_bitrate_kbps > 0:
            bytes_per_second = (target_bitrate_kbps * 1000) / 8
        elif audio_info.bitrate_kbps > 0:
            bytes_per_second = (audio_info.bitrate_kbps * 1000) / 8
        else:
            bytes_per_second = audio_info.size_bytes / audio_info.duration_seconds
        
        # Add 10% safety margin for VBR peaks and container overhead
        bytes_per_second *= 1.1
        
        # Target duration to hit ~14.5 MB
        target_duration = TARGET_CHUNK_SIZE_BYTES / bytes_per_second
        
        # Round down to nearest 10 seconds for cleaner splits, but cap max length
        # to avoid extremely long chunks in very low bitrate files
        chunk_len = max(30, int(target_duration / 10) * 10)
        
        # Return duration, capped at 30 minutes to avoid timeouts
        return min(chunk_len, 1800)
    
    def split_audio(
        self,
        filepath: Path,
        output_format: Optional[str] = None,
        target_bitrate: Optional[str] = None,
        volume_change_db: Optional[float] = None
    ) -> ChunkingResult:
        """
        Split audio file into chunks under the size limit.
        
        Args:
            filepath: Path to audio file
            output_format: Output format for chunks (default: follows input or mp3)
            target_bitrate: Optional target bitrate (e.g., "128k")
            volume_change_db: Optional volume adjustment in dB
            
        Returns:
            ChunkingResult with list of chunk paths
        """
        if not self.is_available():
            return ChunkingResult(
                success=False,
                error="FFmpeg not available on PATH"
            )
        
        audio_info = self.get_audio_info(filepath)
        if not audio_info:
            return ChunkingResult(
                success=False,
                error=f"Could not analyze audio file: {filepath}"
            )
        
        if output_format is None:
            output_format = filepath.suffix.lstrip(".").lower()
            if not output_format:
                output_format = "mp3"
        
        # Check if chunking is even needed
        if audio_info.size_bytes <= TARGET_CHUNK_SIZE_BYTES:
            print_info(f"Audio file is under 15 MB, no chunking needed")
            return ChunkingResult(
                success=True,
                chunks=[AudioChunk(
                    path=filepath,
                    index=0,
                    start_time=0,
                    end_time=audio_info.duration_seconds,
                    duration=audio_info.duration_seconds,
                    size_bytes=audio_info.size_bytes
                )],
                original_info=audio_info
            )
        
        # Create temp directory for chunks
        temp_dir = Path(tempfile.mkdtemp(prefix="audio_chunks_"))
        chunks = []
        
        try:
            target_kbps = None
            if target_bitrate:
                # Handle formats like "128k" or "128000"
                try:
                    if target_bitrate.endswith("k") or target_bitrate.endswith("K"):
                        target_kbps = float(target_bitrate[:-1])
                    else:
                        target_kbps = float(target_bitrate) / 1000.0
                except ValueError:
                    pass
            elif volume_change_db is not None or filepath.suffix.lstrip(".").lower() != output_format:
                # If we are transcoding but no bitrate provided, assume default MP3/AAC ~128kbps
                target_kbps = 128.0
            
            chunk_duration = self.estimate_chunk_duration(audio_info, target_kbps)
            total_duration = audio_info.duration_seconds
            
            print_info(f"Splitting {audio_info.size_mb:.1f} MB audio into ~{chunk_duration:.0f}s chunks")
            
            current_time = 0.0
            chunk_index = 0
            
            while current_time < total_duration:
                end_time = min(current_time + chunk_duration, total_duration)
                chunk_path = temp_dir / f"chunk_{chunk_index:03d}.{output_format}"
                
                # Build FFmpeg command
                cmd = [
                    get_ffmpeg_path(),
                    "-y",  # Overwrite
                    "-i", str(filepath),
                    "-ss", str(current_time),
                    "-t", str(end_time - current_time),
                    "-vn",  # No video
                ]
                
                # Add audio filters
                filters = []
                if volume_change_db is not None:
                    filters.append(f"volume={volume_change_db}dB")
                
                if filters:
                    cmd.extend(["-af", ",".join(filters)])
                
                if target_bitrate:
                    cmd.extend(["-b:a", target_bitrate])
                elif not filters and filepath.suffix.lstrip(".").lower() == output_format:
                    cmd.extend(["-c:a", "copy"])
                
                cmd.append(str(chunk_path))
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    creationflags=get_creation_flags()
                )
                
                if result.returncode != 0:
                    raise RuntimeError(f"FFmpeg failed: {result.stderr[:500]}")
                
                # Get actual chunk size
                chunk_size = chunk_path.stat().st_size
                
                chunks.append(AudioChunk(
                    path=chunk_path,
                    index=chunk_index,
                    start_time=current_time,
                    end_time=end_time,
                    duration=end_time - current_time,
                    size_bytes=chunk_size
                ))
                
                current_time = end_time
                chunk_index += 1
            
            print_info(f"Created {len(chunks)} chunks in {temp_dir}")
            
            return ChunkingResult(
                success=True,
                chunks=chunks,
                temp_dir=temp_dir,
                original_info=audio_info
            )
        
        except Exception as e:
            # Cleanup on failure
            shutil.rmtree(temp_dir, ignore_errors=True)
            return ChunkingResult(
                success=False,
                error=str(e)
            )
    
    @staticmethod
    def merge_transcripts(
        chunk_outputs: List[Tuple[AudioChunk, str]],
        include_timestamps: bool = True
    ) -> str:
        """
        Merge transcripts from multiple chunks into a single output.
        
        Args:
            chunk_outputs: List of (chunk, transcript_text) tuples
            include_timestamps: Whether to add chunk timestamps as headers
            
        Returns:
            Merged transcript text
        """
        if not chunk_outputs:
            return ""
        
        if len(chunk_outputs) == 1:
            return chunk_outputs[0][1]
        
        parts = []
        for chunk, text in sorted(chunk_outputs, key=lambda x: x[0].index):
            if include_timestamps:
                parts.append(f"### [{chunk.time_range_str}]\n\n{text.strip()}")
            else:
                parts.append(text.strip())
        
        return "\n\n".join(parts)



def check_ffmpeg_available() -> Tuple[bool, Optional[str]]:
    """
    Quick check if FFmpeg is available.
    
    Returns:
        Tuple of (is_available, version_string)
    """
    if _is_ffmpeg_available():
        return True, _get_ffmpeg_version()
    return False, None


def needs_chunking(filepath: Path) -> bool:
    """Check if a file needs chunking (>15 MB)"""
    try:
        return filepath.stat().st_size > TARGET_CHUNK_SIZE_BYTES
    except Exception:
        return False


def is_audio_file(filepath: Path) -> bool:
    """Check if file is a supported audio format"""
    return filepath.suffix.lower() in AUDIO_EXTENSIONS