#!/usr/bin/env python3
"""
Audio recorder with recording, playback, and level monitoring.

Provides:
- Recording from input devices and WASAPI loopback
- Real-time audio level monitoring (always active)
- Audio playback with seek/pause controls
- FFmpeg-based compression to Opus/OGG format
"""

import io
import logging
import math
import struct
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, List

from .devices import AudioDevice, is_pyaudio_available

# Try to import PyAudioWPatch
try:
    import pyaudiowpatch as pyaudio
    HAVE_PYAUDIO = True
except ImportError:
    HAVE_PYAUDIO = False
    pyaudio = None


# =============================================================================
# Compression Presets
# =============================================================================

COMPRESSION_PRESETS = {
    "recommended": {
        "name": "Recommended",
        "description": "Best for speech with silence removal",
        "ffmpeg_args": "-af silenceremove=start_periods=1:start_duration=0.1:start_threshold=-50dB:detection=peak,aformat=sample_fmts=s16:sample_rates=16000:channel_layouts=mono -c:a libopus -b:a 32k -ar 16000 -ac 1 -compression_level 10",
        "output_ext": ".ogg"
    },
    "preserve_audio": {
        "name": "Preserve Audio",
        "description": "No silence removal, preserves original audio",
        "ffmpeg_args": "-c:a libopus -b:a 32k -ar 16000 -ac 1 -compression_level 10",
        "output_ext": ".ogg"
    },
    "smallest": {
        "name": "Smallest",
        "description": "Maximum compression with silence removal",
        "ffmpeg_args": "-af silenceremove=start_periods=1:start_duration=0.1:start_threshold=-50dB:detection=peak,aformat=sample_fmts=s16:sample_rates=16000:channel_layouts=mono -c:a libopus -b:a 16k -ar 16000 -ac 1 -compression_level 10",
        "output_ext": ".ogg"
    },
    "mp3_compat": {
        "name": "MP3 Compatible",
        "description": "MP3 format for maximum compatibility",
        "ffmpeg_args": "-c:a libmp3lame -b:a 32k -ar 16000 -ac 1 -q:a 9",
        "output_ext": ".mp3"
    },
    "music": {
        "name": "Music",
        "description": "Higher quality for music content",
        "ffmpeg_args": "-c:a libopus -b:a 96k -ar 48000 -ac 2 -compression_level 10",
        "output_ext": ".ogg"
    }
}


def is_ffmpeg_available() -> bool:
    """Check if FFmpeg is available in PATH."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False
    except Exception:
        return False


def get_rms_level(audio_chunk: bytes, sample_width: int = 2) -> float:
    """
    Calculate RMS level from audio chunk.
    
    Args:
        audio_chunk: Raw audio bytes
        sample_width: Bytes per sample (2 for 16-bit)
        
    Returns:
        Normalized RMS level between 0.0 and 1.0
    """
    if not audio_chunk or len(audio_chunk) < sample_width:
        return 0.0
    
    try:
        if sample_width == 2:  # 16-bit audio
            num_samples = len(audio_chunk) // 2
            fmt = f"<{num_samples}h"  # Little-endian signed shorts
            samples = struct.unpack(fmt, audio_chunk[:num_samples * 2])
            
            # Calculate RMS
            sum_squares = sum(s * s for s in samples)
            rms = math.sqrt(sum_squares / len(samples))
            
            # Normalize to 0-1 (32767 is max for 16-bit signed)
            return min(1.0, rms / 32767.0)
        elif sample_width == 4:  # 32-bit float
            num_samples = len(audio_chunk) // 4
            fmt = f"<{num_samples}f"
            samples = struct.unpack(fmt, audio_chunk[:num_samples * 4])
            
            sum_squares = sum(s * s for s in samples)
            rms = math.sqrt(sum_squares / len(samples))
            return min(1.0, rms)
    except Exception as e:
        logging.debug(f"[AudioRecorder] RMS calculation error: {e}")
    
    return 0.0


@dataclass
class RecordingState:
    """Internal state for recording."""
    is_recording: bool = False
    frames: List[bytes] = None
    start_time: float = 0.0
    sample_rate: int = 44100
    channels: int = 2
    sample_width: int = 2
    
    def __post_init__(self):
        if self.frames is None:
            self.frames = []


class AudioRecorder:
    """
    Audio recorder with recording, playback, and level monitoring.
    
    Key features:
    - Records from microphones or WASAPI loopback devices
    - Provides real-time audio level monitoring (always active when monitoring)
    - Supports audio playback with seek/pause
    - Compresses audio using FFmpeg (Opus/OGG or MP3)
    """
    
    CHUNK_SIZE = 512  # Small chunks for responsive level meter
    FORMAT = pyaudio.paInt16 if HAVE_PYAUDIO else None
    
    def __init__(self, device: Optional[AudioDevice] = None):
        """
        Initialize the recorder.
        
        Args:
            device: Audio device to use. If None, uses default.
        """
        if not HAVE_PYAUDIO:
            raise RuntimeError("PyAudioWPatch is not installed. Install with: pip install PyAudioWPatch")
        
        self._device = device
        self._pyaudio: Optional[pyaudio.PyAudio] = None
        
        # Recording state
        self._recording_state = RecordingState()
        self._recording_stream = None
        self._recording_lock = threading.Lock()
        
        # Level monitoring state
        self._monitoring = False
        self._monitor_stream = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_lock = threading.Lock()
        self._current_level = 0.0
        self._level_callback: Optional[Callable[[float], None]] = None
        
        # Playback state
        self._playing = False
        self._paused = False
        self._playback_stream = None
        self._playback_thread: Optional[threading.Thread] = None
        self._playback_lock = threading.Lock()
        self._playback_position = 0.0
        self._playback_data: Optional[bytes] = None
        self._playback_sample_rate = 44100
        self._playback_channels = 2
        self._playback_sample_width = 2
        
        logging.debug(f"[AudioRecorder] Initialized with device: {device}")
    
    @property
    def device(self) -> Optional[AudioDevice]:
        """Get current device."""
        return self._device
    
    @device.setter
    def device(self, device: Optional[AudioDevice]):
        """Set device (stops any active operations first)."""
        self.stop_level_monitor()
        self.stop_recording()
        self._device = device
        logging.debug(f"[AudioRecorder] Device changed to: {device}")
    
    def _get_pyaudio(self) -> pyaudio.PyAudio:
        """Get or create PyAudio instance."""
        if self._pyaudio is None:
            self._pyaudio = pyaudio.PyAudio()
        return self._pyaudio
    
    def _close_pyaudio(self):
        """Close PyAudio instance if no streams are active."""
        if self._pyaudio and not self._monitoring and not self._recording_state.is_recording and not self._playing:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass
            self._pyaudio = None
    
    # =========================================================================
    # Recording
    # =========================================================================
    
    def start_recording(self) -> bool:
        """
        Start recording audio from the current device.
        
        Returns:
            True if recording started successfully, False otherwise.
        """
        with self._recording_lock:
            if self._recording_state.is_recording:
                logging.warning("[AudioRecorder] Already recording")
                return False
            
            if not self._device:
                logging.error("[AudioRecorder] No device set for recording")
                return False
            
            try:
                p = self._get_pyaudio()
                
                # Prepare recording state
                self._recording_state = RecordingState(
                    is_recording=True,
                    frames=[],
                    start_time=time.time(),
                    sample_rate=int(self._device.sample_rate),
                    channels=self._device.channels,
                    sample_width=p.get_sample_size(self.FORMAT)
                )
                
                # Callback for recording
                def recording_callback(in_data, frame_count, time_info, status):
                    if self._recording_state.is_recording:
                        self._recording_state.frames.append(in_data)
                        # Also update level if monitoring
                        if self._monitoring:
                            self._current_level = get_rms_level(in_data, self._recording_state.sample_width)
                            if self._level_callback:
                                try:
                                    self._level_callback(self._current_level)
                                except Exception:
                                    pass
                    return (in_data, pyaudio.paContinue)
                
                # Open recording stream
                self._recording_stream = p.open(
                    format=self.FORMAT,
                    channels=self._device.channels,
                    rate=int(self._device.sample_rate),
                    input=True,
                    input_device_index=self._device.index,
                    frames_per_buffer=self.CHUNK_SIZE,
                    stream_callback=recording_callback
                )
                
                logging.info(f"[AudioRecorder] Recording started on {self._device.name}")
                return True
                
            except Exception as e:
                logging.error(f"[AudioRecorder] Failed to start recording: {e}")
                self._recording_state.is_recording = False
                return False
    
    def stop_recording(self) -> Optional[bytes]:
        """
        Stop recording and return WAV data.
        
        Returns:
            WAV audio data as bytes, or None if not recording.
        """
        with self._recording_lock:
            if not self._recording_state.is_recording:
                return None
            
            self._recording_state.is_recording = False
            
            # Close stream
            if self._recording_stream:
                try:
                    self._recording_stream.stop_stream()
                    self._recording_stream.close()
                except Exception as e:
                    logging.debug(f"[AudioRecorder] Error closing recording stream: {e}")
                self._recording_stream = None
            
            # Build WAV data
            if not self._recording_state.frames:
                logging.warning("[AudioRecorder] No frames recorded")
                self._close_pyaudio()
                return None
            
            try:
                wav_buffer = io.BytesIO()
                with wave.open(wav_buffer, 'wb') as wf:
                    wf.setnchannels(self._recording_state.channels)
                    wf.setsampwidth(self._recording_state.sample_width)
                    wf.setframerate(self._recording_state.sample_rate)
                    wf.writeframes(b''.join(self._recording_state.frames))
                
                wav_data = wav_buffer.getvalue()
                duration = self.get_duration()
                logging.info(f"[AudioRecorder] Recording stopped: {len(wav_data)} bytes, {duration:.1f}s")
                
                # Clear frames
                self._recording_state.frames = []
                self._close_pyaudio()
                
                return wav_data
                
            except Exception as e:
                logging.error(f"[AudioRecorder] Failed to create WAV: {e}")
                self._close_pyaudio()
                return None
    
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._recording_state.is_recording
    
    def get_duration(self) -> float:
        """
        Get current recording duration in seconds.
        
        Returns:
            Duration in seconds (0.0 if not recording).
        """
        if not self._recording_state.is_recording:
            if self._recording_state.frames:
                # Calculate from recorded frames
                total_bytes = sum(len(f) for f in self._recording_state.frames)
                bytes_per_second = (
                    self._recording_state.sample_rate *
                    self._recording_state.channels *
                    self._recording_state.sample_width
                )
                return total_bytes / bytes_per_second if bytes_per_second > 0 else 0.0
            return 0.0
        
        return time.time() - self._recording_state.start_time
    
    # =========================================================================
    # Level Monitoring
    # =========================================================================
    
    def start_level_monitor(self, callback: Optional[Callable[[float], None]] = None) -> bool:
        """
        Start monitoring audio levels from the current device.
        
        This runs continuously, providing real-time level updates even when
        not recording. The level meter should always reflect the selected device.
        
        Args:
            callback: Function called with level (0.0-1.0) on each update
            
        Returns:
            True if monitoring started, False otherwise.
        """
        with self._monitor_lock:
            if self._monitoring:
                # Already monitoring, just update callback
                self._level_callback = callback
                return True
            
            if not self._device:
                logging.error("[AudioRecorder] No device set for monitoring")
                return False
            
            self._level_callback = callback
            self._monitoring = True
            
            # Start monitor thread
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name="AudioLevelMonitor"
            )
            self._monitor_thread.start()
            
            logging.debug(f"[AudioRecorder] Level monitoring started on {self._device.name}")
            return True
    
    def _monitor_loop(self):
        """Background thread for level monitoring."""
        try:
            p = self._get_pyaudio()
            
            def monitor_callback(in_data, frame_count, time_info, status):
                if not self._monitoring:
                    return (in_data, pyaudio.paComplete)
                
                # Update level (only if not recording, as recording callback handles it)
                if not self._recording_state.is_recording:
                    self._current_level = get_rms_level(in_data, 2)
                    if self._level_callback:
                        try:
                            self._level_callback(self._current_level)
                        except Exception:
                            pass
                
                return (in_data, pyaudio.paContinue)
            
            # Open monitor stream
            self._monitor_stream = p.open(
                format=self.FORMAT,
                channels=self._device.channels,
                rate=int(self._device.sample_rate),
                input=True,
                input_device_index=self._device.index,
                frames_per_buffer=self.CHUNK_SIZE,
                stream_callback=monitor_callback
            )
            
            # Keep thread alive while monitoring
            while self._monitoring:
                time.sleep(0.05)
            
        except Exception as e:
            logging.error(f"[AudioRecorder] Monitor loop error: {e}")
        finally:
            if self._monitor_stream:
                try:
                    self._monitor_stream.stop_stream()
                    self._monitor_stream.close()
                except Exception:
                    pass
                self._monitor_stream = None
            
            self._monitoring = False
            self._close_pyaudio()
    
    def stop_level_monitor(self):
        """Stop level monitoring."""
        with self._monitor_lock:
            if not self._monitoring:
                return
            
            self._monitoring = False
            self._current_level = 0.0
            
            # Wait for thread to finish
            if self._monitor_thread and self._monitor_thread.is_alive():
                self._monitor_thread.join(timeout=1.0)
            
            self._monitor_thread = None
            logging.debug("[AudioRecorder] Level monitoring stopped")
    
    def is_monitoring(self) -> bool:
        """Check if level monitoring is active."""
        return self._monitoring
    
    def get_level(self) -> float:
        """
        Get current audio level.
        
        Returns:
            Level between 0.0 and 1.0
        """
        return self._current_level
    
    # =========================================================================
    # Playback
    # =========================================================================
    
    def play(self, audio_data: bytes, start_position: float = 0.0) -> bool:
        """
        Start playing audio data.
        
        Args:
            audio_data: WAV or compressed audio data
            start_position: Position to start from (seconds)
            
        Returns:
            True if playback started, False otherwise.
        """
        with self._playback_lock:
            # Stop any existing playback
            self._stop_playback_internal()
            
            try:
                # Decode audio if compressed
                pcm_data, sample_rate, channels, sample_width = self._decode_audio(audio_data)
                
                if not pcm_data:
                    logging.error("[AudioRecorder] Failed to decode audio for playback")
                    return False
                
                self._playback_data = pcm_data
                self._playback_sample_rate = sample_rate
                self._playback_channels = channels
                self._playback_sample_width = sample_width
                self._playback_position = start_position
                self._playing = True
                self._paused = False
                
                # Start playback thread
                self._playback_thread = threading.Thread(
                    target=self._playback_loop,
                    daemon=True,
                    name="AudioPlayback"
                )
                self._playback_thread.start()
                
                logging.debug(f"[AudioRecorder] Playback started at {start_position:.1f}s")
                return True
                
            except Exception as e:
                logging.error(f"[AudioRecorder] Playback error: {e}")
                return False
    
    def _decode_audio(self, audio_data: bytes) -> tuple:
        """
        Decode audio data to raw PCM.
        
        Returns:
            Tuple of (pcm_data, sample_rate, channels, sample_width)
        """
        # Try WAV first
        try:
            wav_buffer = io.BytesIO(audio_data)
            with wave.open(wav_buffer, 'rb') as wf:
                pcm_data = wf.readframes(wf.getnframes())
                return (pcm_data, wf.getframerate(), wf.getnchannels(), wf.getsampwidth())
        except Exception:
            pass
        
        # Try FFmpeg for compressed formats
        if is_ffmpeg_available():
            try:
                # Write to temp file
                with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp_in:
                    tmp_in.write(audio_data)
                    tmp_in_path = tmp_in.name
                
                tmp_out_path = tmp_in_path + ".wav"
                
                try:
                    result = subprocess.run(
                        [
                            "ffmpeg", "-y", "-i", tmp_in_path,
                            "-f", "wav", "-acodec", "pcm_s16le",
                            tmp_out_path
                        ],
                        capture_output=True,
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                    )
                    
                    if result.returncode == 0 and Path(tmp_out_path).exists():
                        with open(tmp_out_path, 'rb') as f:
                            wav_data = f.read()
                        
                        wav_buffer = io.BytesIO(wav_data)
                        with wave.open(wav_buffer, 'rb') as wf:
                            pcm_data = wf.readframes(wf.getnframes())
                            return (pcm_data, wf.getframerate(), wf.getnchannels(), wf.getsampwidth())
                finally:
                    # Cleanup
                    try:
                        Path(tmp_in_path).unlink(missing_ok=True)
                        Path(tmp_out_path).unlink(missing_ok=True)
                    except Exception:
                        pass
                        
            except Exception as e:
                logging.debug(f"[AudioRecorder] FFmpeg decode failed: {e}")
        
        return (None, 0, 0, 0)
    
    def _playback_loop(self):
        """Background thread for audio playback."""
        try:
            p = self._get_pyaudio()
            
            bytes_per_frame = self._playback_channels * self._playback_sample_width
            bytes_per_second = self._playback_sample_rate * bytes_per_frame
            
            # Calculate start offset
            start_byte = int(self._playback_position * bytes_per_second)
            start_byte = (start_byte // bytes_per_frame) * bytes_per_frame  # Align to frame
            
            current_byte = start_byte
            chunk_size = 1024 * bytes_per_frame
            
            # Open output stream
            self._playback_stream = p.open(
                format=p.get_format_from_width(self._playback_sample_width),
                channels=self._playback_channels,
                rate=self._playback_sample_rate,
                output=True
            )
            
            while self._playing and current_byte < len(self._playback_data):
                if self._paused:
                    time.sleep(0.05)
                    continue
                
                # Get next chunk
                end_byte = min(current_byte + chunk_size, len(self._playback_data))
                chunk = self._playback_data[current_byte:end_byte]
                
                # Write to stream
                self._playback_stream.write(chunk)
                
                # Update position
                current_byte = end_byte
                self._playback_position = current_byte / bytes_per_second
            
            # Playback complete
            self._playing = False
            
        except Exception as e:
            logging.error(f"[AudioRecorder] Playback loop error: {e}")
        finally:
            if self._playback_stream:
                try:
                    self._playback_stream.stop_stream()
                    self._playback_stream.close()
                except Exception:
                    pass
                self._playback_stream = None
            
            self._playing = False
            self._close_pyaudio()
    
    def _stop_playback_internal(self):
        """Stop playback (internal, no lock)."""
        self._playing = False
        self._paused = False
        
        if self._playback_thread and self._playback_thread.is_alive():
            self._playback_thread.join(timeout=1.0)
        
        self._playback_thread = None
        self._playback_position = 0.0
    
    def pause(self):
        """Pause playback."""
        with self._playback_lock:
            if self._playing and not self._paused:
                self._paused = True
                logging.debug("[AudioRecorder] Playback paused")
    
    def resume(self):
        """Resume paused playback."""
        with self._playback_lock:
            if self._playing and self._paused:
                self._paused = False
                logging.debug("[AudioRecorder] Playback resumed")
    
    def stop_playback(self):
        """Stop playback."""
        with self._playback_lock:
            self._stop_playback_internal()
            logging.debug("[AudioRecorder] Playback stopped")
    
    def seek(self, position: float):
        """
        Seek to position in current audio.
        
        Args:
            position: Position in seconds
        """
        with self._playback_lock:
            if self._playback_data:
                bytes_per_frame = self._playback_channels * self._playback_sample_width
                bytes_per_second = self._playback_sample_rate * bytes_per_frame
                max_position = len(self._playback_data) / bytes_per_second
                
                self._playback_position = max(0.0, min(position, max_position))
                logging.debug(f"[AudioRecorder] Seeked to {self._playback_position:.1f}s")
    
    def get_playback_position(self) -> float:
        """Get current playback position in seconds."""
        return self._playback_position
    
    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        return self._playing
    
    def is_paused(self) -> bool:
        """Check if playback is paused."""
        return self._paused
    
    # =========================================================================
    # Compression
    # =========================================================================
    
    def compress_audio(
        self,
        wav_data: bytes,
        preset: str = "recommended"
    ) -> Optional[bytes]:
        """
        Compress WAV audio using FFmpeg.
        
        Args:
            wav_data: Input WAV data
            preset: Compression preset name (from COMPRESSION_PRESETS)
            
        Returns:
            Compressed audio bytes, or None if compression failed
        """
        if not is_ffmpeg_available():
            logging.error("[AudioRecorder] FFmpeg not available for compression")
            return None
        
        preset_config = COMPRESSION_PRESETS.get(preset, COMPRESSION_PRESETS["recommended"])
        output_ext = preset_config.get("output_ext", ".ogg")
        ffmpeg_args = preset_config.get("ffmpeg_args", "")
        
        try:
            # Write input to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
                tmp_in.write(wav_data)
                tmp_in_path = tmp_in.name
            
            tmp_out_path = tmp_in_path.replace(".wav", output_ext)
            
            try:
                # Build FFmpeg command
                cmd = ["ffmpeg", "-y", "-i", tmp_in_path]
                cmd.extend(ffmpeg_args.split())
                cmd.append(tmp_out_path)
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
                
                if result.returncode != 0:
                    logging.error(f"[AudioRecorder] FFmpeg error: {result.stderr.decode()}")
                    return None
                
                if not Path(tmp_out_path).exists():
                    logging.error("[AudioRecorder] FFmpeg output file not created")
                    return None
                
                with open(tmp_out_path, 'rb') as f:
                    compressed_data = f.read()
                
                logging.info(f"[AudioRecorder] Compressed: {len(wav_data)} -> {len(compressed_data)} bytes")
                return compressed_data
                
            finally:
                # Cleanup
                try:
                    Path(tmp_in_path).unlink(missing_ok=True)
                    Path(tmp_out_path).unlink(missing_ok=True)
                except Exception:
                    pass
                    
        except Exception as e:
            logging.error(f"[AudioRecorder] Compression error: {e}")
            return None
    
    def estimate_compressed_size(self, wav_data: bytes, preset: str = "recommended") -> int:
        """
        Estimate compressed size without actually compressing.
        
        Args:
            wav_data: Input WAV data
            preset: Compression preset name
            
        Returns:
            Estimated size in bytes
        """
        preset_config = COMPRESSION_PRESETS.get(preset, COMPRESSION_PRESETS["recommended"])
        
        # Parse bitrate from args
        ffmpeg_args = preset_config.get("ffmpeg_args", "")
        
        # Extract bitrate (e.g., "-b:a 32k" -> 32000)
        bitrate = 32000  # Default 32kbps
        if "-b:a" in ffmpeg_args:
            try:
                parts = ffmpeg_args.split("-b:a")
                if len(parts) > 1:
                    bitrate_str = parts[1].strip().split()[0]
                    if bitrate_str.endswith("k"):
                        bitrate = int(bitrate_str[:-1]) * 1000
                    else:
                        bitrate = int(bitrate_str)
            except Exception:
                pass
        
        # Estimate duration from WAV
        try:
            wav_buffer = io.BytesIO(wav_data)
            with wave.open(wav_buffer, 'rb') as wf:
                duration = wf.getnframes() / wf.getframerate()
        except Exception:
            # Rough estimate: assume 44100Hz, 16-bit, stereo
            duration = len(wav_data) / (44100 * 2 * 2)
        
        # Calculate estimated size
        estimated_bytes = int((bitrate / 8) * duration)
        
        # Add ~5% for container overhead
        return int(estimated_bytes * 1.05)
    
    # =========================================================================
    # Cleanup
    # =========================================================================
    
    def cleanup(self):
        """Clean up all resources."""
        self.stop_level_monitor()
        self.stop_recording()
        self.stop_playback()
        
        if self._pyaudio:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass
            self._pyaudio = None
        
        logging.debug("[AudioRecorder] Cleaned up")
    
    def __del__(self):
        """Destructor."""
        self.cleanup()


def get_audio_duration(audio_data: bytes) -> float:
    """
    Get duration of audio data in seconds.
    
    Args:
        audio_data: WAV or compressed audio data
        
    Returns:
        Duration in seconds
    """
    # Try WAV
    try:
        wav_buffer = io.BytesIO(audio_data)
        with wave.open(wav_buffer, 'rb') as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        pass
    
    # Try FFmpeg probe
    if is_ffmpeg_available():
        try:
            with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name
            
            try:
                result = subprocess.run(
                    [
                        "ffprobe", "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        tmp_path
                    ],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
                
                if result.returncode == 0:
                    return float(result.stdout.strip())
            finally:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass
                    
        except Exception:
            pass
    
    return 0.0
