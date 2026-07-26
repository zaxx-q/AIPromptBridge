#!/usr/bin/env python3
"""
Audio recorder with recording, playback, and level monitoring.

Provides:
- Recording from microphones and system/desktop sources
  (WASAPI loopback on Windows; PipeWire/Pulse monitors on Linux)
- Real-time audio level monitoring (always active)
- Audio playback with seek/pause controls
- FFmpeg-based compression to Opus/OGG format
"""

from __future__ import annotations

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
from queue import Empty, Queue
from typing import Callable, List, Optional

from .backend import HAVE_PYAUDIO, get_pyaudio_install_hint, pyaudio
from .devices import AudioDevice
from .ffmpeg_utils import (
    get_audio_duration,
    get_creation_flags,
    get_ffmpeg_path,
    is_ffmpeg_available,
)

# =============================================================================
# Compression Presets
# =============================================================================

COMPRESSION_PRESETS = {
    "recommended": {
        "name": "Recommended",
        "description": "Best for speech with silence removal",
        "ffmpeg_args": "-af silenceremove=start_periods=1:start_duration=0.1:start_threshold=-50dB:detection=peak,aformat=sample_fmts=s16:sample_rates=16000:channel_layouts=mono -c:a libopus -b:a 32k -ar 16000 -ac 1 -compression_level 10",
        "output_ext": ".ogg",
    },
    "preserve_audio": {
        "name": "Preserve Audio",
        "description": "Compress but no silence removal, preserves original audio",
        "ffmpeg_args": "-c:a libopus -b:a 32k -ar 16000 -ac 1 -compression_level 10",
        "output_ext": ".ogg",
    },
    "smallest": {
        "name": "Smallest",
        "description": "Maximum compression with silence removal",
        "ffmpeg_args": "-af silenceremove=start_periods=1:start_duration=0.1:start_threshold=-50dB:detection=peak,aformat=sample_fmts=s16:sample_rates=16000:channel_layouts=mono -c:a libopus -b:a 16k -ar 16000 -ac 1 -compression_level 10",
        "output_ext": ".ogg",
    },
    "mp3_compat": {
        "name": "MP3 Compatible",
        "description": "MP3 format for maximum compatibility",
        "ffmpeg_args": "-c:a libmp3lame -b:a 32k -ar 16000 -ac 1 -q:a 9",
        "output_ext": ".mp3",
    },
    "music": {
        "name": "Music",
        "description": "Higher quality for music content",
        "ffmpeg_args": "-c:a libopus -b:a 96k -ar 48000 -ac 2 -compression_level 10",
        "output_ext": ".ogg",
    },
}


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
            samples = struct.unpack(fmt, audio_chunk[: num_samples * 2])

            # Calculate RMS
            sum_squares = sum(s * s for s in samples)
            rms = math.sqrt(sum_squares / len(samples))

            # Normalize to 0-1 (32767 is max for 16-bit signed)
            return min(1.0, rms / 32767.0)
        elif sample_width == 4:  # 32-bit float
            num_samples = len(audio_chunk) // 4
            fmt = f"<{num_samples}f"
            samples = struct.unpack(fmt, audio_chunk[: num_samples * 4])

            sum_squares = sum(s * s for s in samples)
            rms = math.sqrt(sum_squares / len(samples))
            return min(1.0, rms)
    except Exception as e:
        logging.debug(f"[AudioRecorder] RMS calculation error: {e}")

    return 0.0


class AudioRecorder:
    """
    Audio recorder with unified stream architecture for recording, playback, and level monitoring.

    Key features:
    - Single unified stream handles both level monitoring and recording
    - Records from microphones or system/desktop capture devices
    - Provides real-time audio level monitoring (always active when stream is open)
    - Recording is flag-based (instant start/stop, no stream conflicts)
    - Supports audio playback with seek/pause
    - Compresses audio using FFmpeg (Opus/OGG or MP3)

    Architecture:
    - Call start_stream() when device is selected - opens PortAudio input once
    - Recording is controlled via start_recording()/stop_recording() flags
    - Level monitoring runs continuously while stream is active
    - Call stop_stream() when done or changing devices
    """

    CHUNK_SIZE = 512  # Small chunks for responsive level meter
    LOOPBACK_CHUNK_SIZE = 4096  # Larger chunks for loopback/monitor (buffers more)
    FORMAT = pyaudio.paInt16 if HAVE_PYAUDIO else None

    def __init__(self, device: Optional[AudioDevice] = None):
        """
        Initialize the recorder.

        Args:
            device: Audio device to use. If None, uses default.
        """
        # Initialize fields first so __del__/cleanup are safe if construction fails
        self._device = device
        self._pyaudio = None

        # Unified stream state (new architecture - uses thread with blocking reads)
        self._stream = None
        self._stream_active = False
        self._stream_thread: Optional[threading.Thread] = None
        self._stream_lock = threading.Lock()

        # Recording uses a Queue for thread-safe, lossless audio capture
        # The queue approach ensures no data is lost at recording boundaries
        self._is_recording = False
        self._audio_queue: Queue = Queue()  # Thread-safe audio queue
        self._recording_start_time = 0.0
        self._sample_rate = 44100
        self._channels = 2
        self._sample_width = 2

        # Level monitoring (always active when stream is open)
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

        if not HAVE_PYAUDIO:
            raise RuntimeError(f"PyAudio is not installed. Install with: {get_pyaudio_install_hint()}")

        logging.debug(f"[AudioRecorder] Initialized with device: {device}")

    @property
    def device(self) -> Optional[AudioDevice]:
        """Get current device."""
        return self._device

    @device.setter
    def device(self, device: Optional[AudioDevice]):
        """Set device (stops any active operations first)."""
        self.stop_stream()  # New unified approach
        self.stop_level_monitor()  # Legacy compatibility
        self.stop_recording()
        self._device = device
        logging.debug(f"[AudioRecorder] Device changed to: {device}")

    @staticmethod
    def _is_loopback_like_name(name: str) -> bool:
        """Fallback name heuristic when AudioDevice.is_loopback is unset/stale."""
        lower = (name or "").lower()
        return "loopback" in lower or "monitor" in lower

    def _get_pyaudio(self):
        """Get or create PyAudio instance."""
        if self._pyaudio is None:
            self._pyaudio = pyaudio.PyAudio()
        return self._pyaudio

    def _close_pyaudio(self):
        """Close PyAudio instance if no streams are active."""
        if self._pyaudio and not self._playing and not self._stream_active:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass
            self._pyaudio = None

    # =========================================================================
    # Unified Stream Architecture (New)
    # =========================================================================

    def start_stream(self, level_callback: Optional[Callable[[float], None]] = None) -> bool:
        """
        Start the audio input stream for level monitoring and recording.

        Opens a PyAudio stream with a callback. The callback is invoked by the audio
        driver at the appropriate rate. For WASAPI loopback, this is typically once
        per second with a large buffer of audio data.

        Args:
            level_callback: Optional callback for level updates (0.0-1.0)

        Returns:
            True if stream started successfully
        """
        with self._stream_lock:
            if self._stream_active:
                # Already running, just update callback
                self._level_callback = level_callback
                logging.debug("[AudioRecorder] Stream already active, updated callback")
                return True

            if not self._device:
                logging.error("[AudioRecorder] No device set")
                return False

            try:
                self._level_callback = level_callback

                # Store sample info for WAV generation
                self._sample_rate = int(self._device.sample_rate)
                channels = max(1, int(self._device.channels or 1))
                self._channels = channels
                p = self._get_pyaudio()
                self._sample_width = p.get_sample_size(self.FORMAT)

                # Create callback (runs in PyAudio's thread)
                def stream_callback(in_data, frame_count, time_info, status):
                    """PyAudio callback - invoked by audio driver when data is available."""
                    # Update level (always)
                    self._current_level = get_rms_level(in_data, self._sample_width)

                    # Call level callback if set
                    if self._level_callback:
                        try:
                            self._level_callback(self._current_level)
                        except Exception:
                            pass

                    # Queue audio data if recording (always queue, drain later)
                    # This prevents data loss at recording boundaries
                    if self._is_recording:
                        self._audio_queue.put(in_data)

                    return (in_data, pyaudio.paContinue)

                # Loopback/monitor devices often deliver larger, less frequent buffers
                is_loopback = bool(self._device.is_loopback) or self._is_loopback_like_name(self._device.name)
                chunk_size = self.LOOPBACK_CHUNK_SIZE if is_loopback else self.CHUNK_SIZE
                rate = int(self._device.sample_rate)

                # Open stream WITH callback - this uses PyAudio's native threading.
                # If channel count fails (common on some PipeWire nodes), retry mono/stereo.
                last_error: Optional[Exception] = None
                channel_candidates = [channels]
                for alt in (1, 2):
                    if alt not in channel_candidates:
                        channel_candidates.append(alt)

                for try_channels in channel_candidates:
                    try:
                        self._stream = p.open(
                            format=self.FORMAT,
                            channels=try_channels,
                            rate=rate,
                            input=True,
                            input_device_index=self._device.index,
                            frames_per_buffer=chunk_size,
                            stream_callback=stream_callback,
                        )
                        self._channels = try_channels
                        last_error = None
                        break
                    except Exception as open_err:
                        last_error = open_err
                        logging.debug(
                            f"[AudioRecorder] open failed channels={try_channels} "
                            f"rate={rate} device={self._device.name!r}: {open_err}"
                        )
                        self._stream = None

                if self._stream is None:
                    logging.error(
                        f"[AudioRecorder] Failed to start stream on {self._device.name!r} "
                        f"(index={self._device.index}, rate={rate}, channels={channels}): "
                        f"{last_error}"
                    )
                    self._stream_active = False
                    return False

                self._stream_active = True
                logging.info(
                    f"[AudioRecorder] Stream started on {self._device.name} "
                    f"(rate={rate}, channels={self._channels}, "
                    f"{'loopback/monitor' if is_loopback else 'input'})"
                )
                return True

            except Exception as e:
                logging.error(f"[AudioRecorder] Failed to start stream: {e}")
                self._stream_active = False
                return False

    def stop_stream(self):
        """Stop the audio input stream."""
        with self._stream_lock:
            if not self._stream_active:
                return

            self._stream_active = False
            self._is_recording = False

            # Close the stream
            if self._stream:
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception as e:
                    logging.debug(f"[AudioRecorder] Error closing stream: {e}")
                self._stream = None

        self._current_level = 0.0
        self._close_pyaudio()
        logging.debug("[AudioRecorder] Stream stopped")

    def is_stream_active(self) -> bool:
        """Check if the unified stream is active."""
        return self._stream_active

    def start_recording_unified(self) -> bool:
        """
        Start recording audio (unified stream version).

        Note: Stream must be started first via start_stream().
        This sets a flag and clears the queue - the callback queues audio data.

        Returns:
            True if recording started
        """
        if not self._stream_active:
            logging.error("[AudioRecorder] Stream not active - call start_stream() first")
            return False

        if self._is_recording:
            logging.warning("[AudioRecorder] Already recording")
            return False

        # Clear any stale data from the queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except Empty:
                break

        self._recording_start_time = time.time()
        self._is_recording = True

        logging.info("[AudioRecorder] Recording started (queue-based)")
        return True

    def stop_recording_unified(self) -> Optional[bytes]:
        """
        Stop recording and return WAV data (unified stream version).

        Uses queue-based approach to prevent data loss:
        1. Set flag to stop queueing new data
        2. Drain all remaining data from queue
        3. Build WAV from collected frames

        Note: Stream continues running for level monitoring.

        Returns:
            WAV audio data, or None if not recording
        """
        if not self._is_recording:
            return None

        # Stop queueing new data
        self._is_recording = False

        # Small delay to ensure last callback completes
        time.sleep(0.05)

        # Drain all audio data from the queue
        frames = []
        while True:
            try:
                data = self._audio_queue.get_nowait()
                frames.append(data)
            except Empty:
                break

        if not frames:
            logging.warning("[AudioRecorder] No frames recorded")
            return None

        try:
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wf:
                wf.setnchannels(self._channels)
                wf.setsampwidth(self._sample_width)
                wf.setframerate(self._sample_rate)
                wf.writeframes(b"".join(frames))

            wav_data = wav_buffer.getvalue()

            # Calculate duration from frames
            total_bytes = sum(len(f) for f in frames)
            bytes_per_second = self._sample_rate * self._channels * self._sample_width
            duration = total_bytes / bytes_per_second if bytes_per_second > 0 else 0.0

            logging.info(
                f"[AudioRecorder] Recording stopped: {len(wav_data)} bytes, {duration:.1f}s, {len(frames)} chunks"
            )

            return wav_data

        except Exception as e:
            logging.error(f"[AudioRecorder] Failed to create WAV: {e}")
            return None

    def is_recording_unified(self) -> bool:
        """Check if recording is active (unified stream version)."""
        return self._is_recording

    def get_duration_unified(self) -> float:
        """
        Get current recording duration in seconds (unified stream version).

        Returns:
            Duration in seconds (0.0 if not recording).
        """
        if not self._is_recording:
            return 0.0

        # Use elapsed time since recording started (queue-based approach)
        return time.time() - self._recording_start_time

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
                self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True, name="AudioPlayback")
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
            with wave.open(wav_buffer, "rb") as wf:
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
                        [get_ffmpeg_path(), "-y", "-i", tmp_in_path, "-f", "wav", "-acodec", "pcm_s16le", tmp_out_path],
                        capture_output=True,
                        creationflags=get_creation_flags(),
                    )

                    if result.returncode == 0 and Path(tmp_out_path).exists():
                        with open(tmp_out_path, "rb") as f:
                            wav_data = f.read()

                        wav_buffer = io.BytesIO(wav_data)
                        with wave.open(wav_buffer, "rb") as wf:
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
                output=True,
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

    def compress_audio(self, wav_data: bytes, preset: str = "recommended") -> Optional[bytes]:
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
                cmd = [get_ffmpeg_path(), "-y", "-i", tmp_in_path]
                cmd.extend(ffmpeg_args.split())
                cmd.append(tmp_out_path)

                result = subprocess.run(cmd, capture_output=True, creationflags=get_creation_flags())

                if result.returncode != 0:
                    logging.error(f"[AudioRecorder] FFmpeg error: {result.stderr.decode()}")
                    return None

                if not Path(tmp_out_path).exists():
                    logging.error("[AudioRecorder] FFmpeg output file not created")
                    return None

                with open(tmp_out_path, "rb") as f:
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
            with wave.open(wav_buffer, "rb") as wf:
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
        if not hasattr(self, "_stream_lock"):
            return
        self.stop_stream()  # New unified stream
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
        try:
            self.cleanup()
        except Exception:
            pass
