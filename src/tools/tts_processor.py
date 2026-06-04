#!/usr/bin/env python3
"""TTS Processor Tool - Batch text-to-speech generation using Gemini TTS API."""

import re
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import msvcrt

    HAVE_MSVCRT = True
except ImportError:
    HAVE_MSVCRT = False

from src.console import HAVE_RICH, print_error, print_info, print_success, print_warning

from .base import BaseTool, ToolResult, ToolStatus
from .checkpoint import TTSCheckpoint, TTSCheckpointManager

# ── Text splitting utilities ──────────────────────────────────────────────────


def split_text_lines(text: str) -> List[str]:
    """Split text into non-empty lines."""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def split_text_paragraphs(text: str) -> List[str]:
    """Split on blank lines."""
    paras = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in paras if p.strip()]


def split_text_sentences(text: str) -> List[str]:
    """Simple sentence splitter (no NLTK dependency)."""
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in raw if s.strip()]


# ── Main class ────────────────────────────────────────────────────────────────


class TTSProcessor(BaseTool):
    """Batch TTS Processor — convert text segments to WAV audio via Gemini TTS."""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("tts_processor", config)
        self.checkpoint_manager = TTSCheckpointManager()
        self._current_checkpoint: Optional[TTSCheckpoint] = None
        self._stop_requested: bool = False
        self._keyboard_stop_event: Optional[threading.Event] = None

    # ── Public interface ──────────────────────────────────────────────────────

    def run_interactive(self) -> ToolResult:
        """Run the interactive TTS processing wizard."""
        try:
            main_exists, failed_exists = self.checkpoint_manager.has_any_checkpoint()

            if main_exists:
                resume = self._prompt_resume_checkpoint()
                if resume is None:
                    return ToolResult(success=False, message="Cancelled")
                elif resume:
                    return self._resume_from_checkpoint()
                else:
                    self.checkpoint_manager.clear()

            if not main_exists and failed_exists:
                retry = self._prompt_retry_failed()
                if retry is None:
                    return ToolResult(success=False, message="Cancelled")
                elif retry:
                    return self._resume_from_failed_checkpoint()
                else:
                    self.checkpoint_manager.clear_failed()

            # Step 1: Input
            input_config = self._step1_input_selection()
            if input_config is None:
                return ToolResult(success=False, message="Cancelled")

            # Step 2: Voice & model
            voice_config = self._step2_voice_model()
            if voice_config is None:
                return ToolResult(success=False, message="Cancelled")

            # Step 3: Style instructions
            style_config = self._step3_style_instructions(input_config["segments"])
            if style_config is None:
                return ToolResult(success=False, message="Cancelled")

            # Step 4: Output config
            output_config = self._step4_output_config(input_config)
            if output_config is None:
                return ToolResult(success=False, message="Cancelled")

            # Step 5: Execution settings
            exec_settings = self._step5_execution_settings()
            if exec_settings is None:
                return ToolResult(success=False, message="Cancelled")

            # Create checkpoint
            self._current_checkpoint = self.checkpoint_manager.create(
                input_path=input_config["input_path"],
                segments=input_config["segments"],
                split_mode=input_config["split_mode"],
                voice_name=voice_config["voice_name"],
                model=voice_config["model"],
                style_instructions=style_config["style_instructions"],
                per_segment_styles=style_config.get("per_segment_styles"),
                speaker_mode=voice_config["speaker_mode"],
                multi_speaker_config=voice_config.get("multi_speaker_config"),
                output_mode=output_config["mode"],
                output_path=output_config["path"],
                naming_template=output_config["naming"],
                delay=exec_settings["delay"],
            )

            return self._execute_processing()

        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted by user")
            if self._current_checkpoint:
                self.checkpoint_manager.save(self._current_checkpoint)
                print("💾 Progress saved. Resume with [X] Tools → TTS Processor")
            return ToolResult(success=False, message="Interrupted")

    def run_batch(self, input_path: str, prompt: str, output_config: Dict[str, Any], **kwargs) -> ToolResult:
        """Not implemented for TTSProcessor (uses run_interactive instead)."""
        return ToolResult(success=False, message="Use run_interactive() for TTSProcessor")

    # ── Wizard Steps ──────────────────────────────────────────────────────────

    def _step1_input_selection(self) -> Optional[dict]:
        """Step 1: Select input file and text splitting mode."""
        self._print_header("🔊 TTS PROCESSOR - Step 1: Input & Text Splitting")

        while True:
            print("\nEnter path to text file (or 'q' to cancel):")
            try:
                path_str = input("> ").strip().strip('"')
            except (EOFError, KeyboardInterrupt):
                return None

            if path_str.lower() == "q":
                return None
            if not path_str:
                continue

            path = Path(path_str)
            if not path.exists() or not path.is_file():
                print_error(f"File not found: {path}")
                continue

            try:
                text = path.read_text(encoding="utf-8")
            except Exception as e:
                print_error(f"Cannot read file: {e}")
                continue

            if not text.strip():
                print_error("File is empty")
                continue

            print(f"\n✅ Loaded: {path.name} ({len(text):,} characters)")

            # Split mode
            print("\nText splitting mode:")
            print("  [1] Lines      - One segment per non-empty line")
            print("  [2] Paragraphs - One segment per blank-line-separated block")
            print("  [3] Sentences  - One segment per sentence")
            print("  [4] Whole file - Single segment (entire file)")

            try:
                mode_choice = input("\nChoice [1]: ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                return None

            mode_map = {"1": "lines", "2": "paragraphs", "3": "sentences", "4": "whole"}
            split_mode = mode_map.get(mode_choice, "lines")

            if split_mode == "lines":
                segments = split_text_lines(text)
            elif split_mode == "paragraphs":
                segments = split_text_paragraphs(text)
            elif split_mode == "sentences":
                segments = split_text_sentences(text)
            else:
                segments = [text.strip()]

            if not segments:
                print_error("No segments found after splitting")
                continue

            print(f"\n📊 {len(segments)} segment(s) found ({split_mode} mode)")
            # Preview first 3 segments
            for i, seg in enumerate(segments[:3]):
                preview = seg[:80].replace("\n", " ")
                print(f"  [{i + 1}] {preview}{'...' if len(seg) > 80 else ''}")
            if len(segments) > 3:
                print(f"  ... and {len(segments) - 3} more")

            try:
                confirm = input(f"\nProceed with {len(segments)} segment(s)? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return None

            if confirm == "n":
                continue

            return {"input_path": str(path), "segments": segments, "split_mode": split_mode}

    def _step2_voice_model(self) -> Optional[dict]:
        """Step 2: Select voice, speaker mode, and TTS model."""
        self._print_header("🔊 TTS PROCESSOR - Step 2: Voice & Model")

        from src.audio.tts_constants import TTS_VOICES

        # Config defaults
        default_voice = (self.config or {}).get("tts_default_voice", "Kore")
        default_model = (self.config or {}).get("tts_default_model", "gemini-2.5-flash-preview-tts")

        # Speaker mode
        print("\nSpeaker mode:")
        print("  [1] Single speaker - One voice for all segments")
        print("  [2] Multi-speaker  - Different voices per named speaker")

        try:
            mode_choice = input("\nChoice [1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            return None

        speaker_mode = "multi" if mode_choice == "2" else "single"
        multi_speaker_config = None

        if speaker_mode == "single":
            # Voice list
            voice_list = list(TTS_VOICES.keys())
            print("\nAvailable voices:")
            for i, v in enumerate(voice_list, 1):
                marker = " ◄" if v == default_voice else ""
                details = TTS_VOICES.get(v, {})
                desc = f"{details.get('gender', '?')}, {details.get('style', '?')}"
                print(f"  [{i:2d}] {v:<12} {desc}{marker}")

            try:
                voice_input = input(f"\nVoice name or number [{default_voice}]: ").strip()
            except (EOFError, KeyboardInterrupt):
                return None

            if not voice_input:
                voice_name = default_voice
            elif voice_input.isdigit():
                idx = int(voice_input) - 1
                voice_name = voice_list[idx] if 0 <= idx < len(voice_list) else default_voice
            else:
                voice_name = voice_input

            print(f"✅ Voice: {voice_name}")

        else:
            # Multi-speaker config
            voice_list = list(TTS_VOICES.keys())
            print("\nMulti-speaker mode: configure up to 2 speakers")
            multi_speaker_config = []

            for speaker_num in range(1, 3):
                print(f"\n  Speaker {speaker_num}:")
                try:
                    name = input("    Name (e.g. 'Host', 'Guest'): ").strip()
                    if not name:
                        if speaker_num == 1:
                            print_warning("At least one speaker required")
                            return None
                        break
                    voice_in = input(f"    Voice [{default_voice}]: ").strip() or default_voice
                except (EOFError, KeyboardInterrupt):
                    return None

                # Use format expected by generate_tts: {"speaker": str, "voice_name": str}
                multi_speaker_config.append({"speaker": name, "voice_name": voice_in})

            voice_name = multi_speaker_config[0]["voice_name"] if multi_speaker_config else default_voice
            print(f"✅ Configured {len(multi_speaker_config)} speaker(s)")

        # Model selection
        models = [
            "gemini-2.5-flash-preview-tts",
            "gemini-2.5-pro-preview-tts",
        ]
        print("\nTTS Model:")
        for i, m in enumerate(models, 1):
            marker = " ◄" if m == default_model else ""
            print(f"  [{i}] {m}{marker}")

        try:
            model_input = input(f"\nModel [{default_model}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

        if not model_input:
            model = default_model
        elif model_input.isdigit():
            idx = int(model_input) - 1
            model = models[idx] if 0 <= idx < len(models) else default_model
        else:
            model = model_input

        print(f"✅ Model: {model}")

        return {
            "voice_name": voice_name,
            "model": model,
            "speaker_mode": speaker_mode,
            "multi_speaker_config": multi_speaker_config,
        }

    def _step3_style_instructions(self, segments: List[str]) -> Optional[Dict[str, Any]]:
        """
        Step 3: Choose style instructions (manual, default, or AI Director).

        Returns:
            Dict with:
                - style_instructions: str (the base style, without embedded transcript)
                - per_segment_styles: Optional[Dict[int, str]] (if per-segment mode)
            Or None if cancelled.
        """
        self._print_header("🔊 TTS PROCESSOR - Step 3: Style Instructions")

        # Hardcoded defaults (not configurable via config.ini)
        default_style = "Read aloud naturally"
        director_enabled = (self.config or {}).get("tts_director_enabled", True)

        print("\nStyle instructions tell Gemini how to speak the text.")
        print("Examples: 'Speak warmly and professionally', 'Use a dramatic tone'")

        print("\nOptions:")
        print("  [1] Enter style manually")
        print(f"  [2] Use default: '{default_style}'")
        print("  [3] No style - Send text directly to TTS")
        if director_enabled:
            print("  [4] AI Director - Single style for all segments")
            print("  [5] AI Director (Per-Segment) - Unique style for each segment")
        print("  [Q] Cancel")

        try:
            choice = input("\nChoice [2]: ").strip().lower() or "2"
        except (EOFError, KeyboardInterrupt):
            return None

        if choice == "q":
            return None

        if choice == "1":
            print("\nEnter style instructions:")
            try:
                style = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if not style:
                style = default_style
            print(f"✅ Style: {style}")
            return {"style_instructions": style, "per_segment_styles": None}

        if choice == "3":
            # No style - send text directly
            print("✅ No style - text will be sent directly to TTS")
            return {"style_instructions": "", "per_segment_styles": None}

        if choice == "4" and director_enabled:
            # Single style for all segments (aggregate analysis)
            return self._run_director_single_style(segments, default_style)

        if choice == "5" and director_enabled:
            # Per-segment style (unique for each)
            return self._run_director_per_segment(segments, default_style)

        # Default (choice == '2' or anything else)
        print(f"✅ Style: {default_style}")
        return {"style_instructions": default_style, "per_segment_styles": None}

    def _run_director_single_style(self, segments: List[str], default_style: str) -> Optional[Dict[str, Any]]:
        """
        Run AI Director once on a sample of segments to generate a single style.

        Uses first few segments as context for better style matching.
        Strips embedded transcript from Director output.
        """
        n_segments = len(segments)
        default_sample_count = min(3, n_segments)

        # Ask user how many segments to analyze
        print(f"\n📊 {n_segments} segment(s) total. How many to analyze for style context?")
        print("   (More segments = better context, but longer processing)")
        try:
            count_input = input(f"   Segments to analyze [{default_sample_count}]: ").strip()
            if count_input:
                sample_count = min(int(count_input), n_segments)
            else:
                sample_count = default_sample_count
        except (ValueError, EOFError, KeyboardInterrupt):
            sample_count = default_sample_count

        # Use first N segments as sample for better context
        sample_segments = segments[:sample_count]
        sample_text = "\n\n".join(sample_segments)

        print(f"\n🎭 Running AI Director on first {len(sample_segments)} segment(s)...")
        raw_style = self._generate_style_with_director(sample_text)

        if raw_style:
            # Strip the embedded transcript - we'll add per-segment transcripts later
            style = self._strip_transcript_from_style(raw_style)

            print("\n📋 Generated style:")
            print("─" * 40)
            # Show preview (first 500 chars)
            preview = style[:500] + "..." if len(style) > 500 else style
            print(preview)
            print("─" * 40)

            try:
                keep = input("\nUse this style? [Y/n/r=regenerate]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return None

            if keep == "r":
                # Regenerate
                return self._run_director_single_style(segments, default_style)
            if keep != "n":
                return {"style_instructions": style, "per_segment_styles": None}
        else:
            print_warning("Director failed, using default")

        return {"style_instructions": default_style, "per_segment_styles": None}

    def _run_director_per_segment(self, segments: List[str], default_style: str) -> Optional[Dict[str, Any]]:
        """
        Run AI Director on each segment individually for unique styles.

        More API calls but better style matching per segment.
        """
        n_segments = len(segments)

        print("\n🎭 AI Director Per-Segment Mode")
        print(f"   This will make {n_segments} API calls to generate unique styles.")
        print("   Recommended for smaller batches or when segments have varying tones.")

        try:
            confirm = input(f"\nProceed with {n_segments} Director calls? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if confirm == "n":
            return None

        per_segment_styles: Dict[int, str] = {}

        for i, segment in enumerate(segments):
            print(f"\n   [{i + 1}/{n_segments}] Analyzing segment {i + 1}...")
            raw_style = self._generate_style_with_director(segment)

            if raw_style:
                # Strip embedded transcript
                style = self._strip_transcript_from_style(raw_style)
                per_segment_styles[i] = style
                print("      ✅ Style generated")
            else:
                # Fall back to default for this segment
                per_segment_styles[i] = default_style
                print("      ⚠️ Using default (Director failed)")

        # Use the first segment's style as the base style (for fallback/display)
        base_style = per_segment_styles.get(0, default_style)

        print(f"\n✅ Generated {len(per_segment_styles)} unique styles")
        return {"style_instructions": base_style, "per_segment_styles": per_segment_styles}

    def _strip_transcript_from_style(self, style: str) -> str:
        """
        Strip embedded transcript from AI Director output.

        The Director prompt instructs it to include '#### TRANSCRIPT' section.
        We strip this because each segment needs its own transcript appended.
        """
        if "#### TRANSCRIPT" in style:
            # Split on the transcript marker and take only the style part
            style = style.split("#### TRANSCRIPT")[0].strip()
        return style

    def _step4_output_config(self, input_config: dict) -> Optional[dict]:
        """Step 4: Configure output directory, mode, and naming."""
        self._print_header("🔊 TTS PROCESSOR - Step 4: Output Configuration")

        input_path = Path(input_config["input_path"])
        default_output = str(input_path.parent)
        n_segments = len(input_config["segments"])

        # Output mode (only ask if multiple segments)
        if n_segments > 1:
            print("\nOutput mode:")
            print("  [1] Individual WAV  - One .wav file per segment")
            print("  [2] Merged WAV      - All segments merged into one .wav file")

            try:
                mode_choice = input("\nChoice [1]: ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                return None

            output_mode = "merge" if mode_choice == "2" else "individual"
        else:
            output_mode = "individual"

        # Output directory
        print("\nOutput directory:")
        try:
            out_dir = input(f"  [{default_output}]: ").strip() or default_output
        except (EOFError, KeyboardInterrupt):
            return None

        out_path = Path(out_dir)
        if not out_path.exists():
            try:
                create = input("Directory doesn't exist. Create? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return None
            if create != "n":
                out_path.mkdir(parents=True, exist_ok=True)
            else:
                return None

        # Naming template
        stem = input_path.stem
        if output_mode == "individual":
            default_naming = f"{stem}_{{index:03d}}"
            print("\nNaming template (available vars: {filename}, {index:03d}, {date}, {time}):")
            try:
                naming = input(f"  [{default_naming}]: ").strip() or default_naming
            except (EOFError, KeyboardInterrupt):
                return None
        else:
            naming = f"{stem}_merged"
            print("\nOutput filename (without .wav):")
            try:
                custom = input(f"  [{naming}]: ").strip()
                if custom:
                    naming = custom
            except (EOFError, KeyboardInterrupt):
                return None

        print(f"\n✅ Output: {output_mode} → {out_dir}")
        return {"mode": output_mode, "path": str(out_path), "naming": naming}

    def _step5_execution_settings(self) -> Optional[dict]:
        """Step 5: Configure delay between requests."""
        self._print_header("🔊 TTS PROCESSOR - Step 5: Execution Settings")

        # Hardcoded default
        default_delay = 1.0

        print("\nDelay between API calls (seconds):")
        try:
            delay_str = input(f"  [{default_delay}]: ").strip()
            delay = float(delay_str) if delay_str else default_delay
        except (ValueError, EOFError, KeyboardInterrupt):
            delay = default_delay

        print(f"\n✅ Delay: {delay}s")
        return {"delay": delay}

    # ── Execution ─────────────────────────────────────────────────────────────

    def _execute_processing(self) -> ToolResult:
        """Run the main processing loop."""
        cp = self._current_checkpoint
        remaining = cp.remaining_indices
        total = cp.total_segments

        self._start_keyboard_listener()

        self._print_header("🔊 TTS PROCESSOR - Generating Audio")
        print(f"\n🚀 Processing {len(remaining)} of {total} segment(s)")
        print(f"   Voice: {cp.voice_name}  |  Model: {cp.model}")
        print(f"   Output: {cp.output_mode}")
        if HAVE_MSVCRT:
            print("\n   Controls: [P] Pause   [S] Stop & save progress")
        print("─" * 60)

        self.status = ToolStatus.RUNNING
        result = ToolResult(success=True, total_count=total)

        try:
            self._execute_sequential(cp, remaining, result)
        finally:
            self._stop_keyboard_listener()

        # Merge mode: combine all segment WAVs
        if cp.output_mode == "merge" and cp.output_files:
            print(f"\n🔗 Merging {len(cp.output_files)} WAV file(s)...")
            merged_name = cp.naming_template + ".wav"
            merged_path = Path(cp.output_path) / merged_name
            try:
                self._merge_wav_files(cp.output_files, str(merged_path))
                print(f"✅ Merged → {merged_path.name}")
                result.output_path = str(merged_path)
                # Clean up individual segment WAVs
                for f in cp.output_files:
                    try:
                        Path(f).unlink(missing_ok=True)
                    except Exception:
                        pass
            except Exception as e:
                print_error(f"Merge failed: {e}")

        # Final summary
        print(f"\n{'─' * 60}")
        if result.processed_count > 0:
            print_success(f"Completed: {result.processed_count}/{total} segments generated")
        if result.failed_count > 0:
            print_error(f"Failed: {result.failed_count} segment(s)")

        # Handle checkpoint cleanup / failed-checkpoint creation
        if cp.is_complete:
            self.checkpoint_manager.clear()
            if cp.failed_segments:
                self.checkpoint_manager.create_failed_checkpoint(cp)
                print(f"\n💾 {len(cp.failed_segments)} failed segment(s) saved for retry.")
                result.message = f"Generated {result.processed_count} segments, {result.failed_count} failed"
            else:
                self.checkpoint_manager.clear_failed()
                result.message = f"Generated {result.processed_count} WAV file(s) successfully"
        else:
            # Incomplete — was stopped/interrupted
            self.checkpoint_manager.save(cp)
            result.success = False
            result.message = f"Stopped — {result.processed_count}/{total} segments completed (progress saved)"

        self.status = ToolStatus.COMPLETED
        return result

    def _execute_sequential(self, cp: TTSCheckpoint, remaining: List[int], result: ToolResult):
        """Process segments one at a time with pause/stop support."""
        for loop_idx, seg_idx in enumerate(remaining):
            # Pause/stop check
            if not self.check_pause():
                self.checkpoint_manager.save(cp)
                if getattr(self, "_stop_requested", False):
                    print("\n⏹️  Stopped. Progress saved.")
                    result.message = "Stopped by user"
                    return
                # Paused — wait for user
                print("\n⏸️  Paused. Press Enter to resume, 'q' to stop...")
                try:
                    resume_input = input().strip().lower()
                    if resume_input == "q":
                        result.message = "Stopped by user"
                        return
                    self.request_resume()
                    self._stop_requested = False
                    self._start_keyboard_listener()
                except (EOFError, KeyboardInterrupt):
                    result.message = "Stopped by user"
                    return

            seg_text = cp.segments[seg_idx]
            done_so_far = len(cp.completed_segments) + len(cp.failed_segments) + 1
            print(f"\n[{done_so_far}/{cp.total_segments}] Segment {seg_idx + 1}")
            preview = seg_text[:60].replace("\n", " ")
            print(f'   "{preview}{"..." if len(seg_text) > 60 else ""}"')

            output_file = self._process_single_segment(seg_idx, seg_text, cp)
            if output_file:
                cp.mark_completed(seg_idx, output_file)
                result.processed_count += 1
                print(f"   ✅ → {Path(output_file).name}")
            else:
                result.failed_count += 1
                print("   ❌ Failed")

            self.checkpoint_manager.save(cp)

            if loop_idx < len(remaining) - 1 and cp.delay_between_requests > 0:
                time.sleep(cp.delay_between_requests)

    def _process_single_segment(self, idx: int, seg_text: str, cp: TTSCheckpoint) -> Optional[str]:
        """Call Gemini TTS for one segment and save the resulting WAV. Returns output path or None."""
        try:
            from src.gui.tts_tool import get_instance as get_tts_tool

            tts_tool = get_tts_tool()
            if not tts_tool:
                cp.mark_failed(idx, "TTS Tool not initialized")
                return None

            # Per-segment style override (dict keys may be int or str after JSON load)
            style = cp.per_segment_styles.get(idx) or cp.per_segment_styles.get(str(idx)) or cp.style_instructions

            # Combine style instructions with text (TTS API expects single text field)
            if style:
                full_text = style
                # Add transcript marker if style doesn't already contain the text
                if "#### TRANSCRIPT" not in style and seg_text not in style:
                    full_text = f"{style}\n\n#### TRANSCRIPT\n{seg_text}"
            else:
                full_text = seg_text

            # Build multi_speaker_config for multi-speaker mode
            multi_speaker_config = None
            if cp.speaker_mode == "multi" and cp.multi_speaker_config:
                multi_speaker_config = cp.multi_speaker_config

            # Use async method with blocking wait
            result = {"pcm": None, "wav": None, "duration": None, "error": None}
            event = threading.Event()

            def on_success(pcm, wav, duration):
                result["pcm"], result["wav"], result["duration"] = pcm, wav, duration
                event.set()

            def on_error(err):
                result["error"] = err
                event.set()

            tts_tool.generate_audio(
                text=full_text,
                voice_name=cp.voice_name,
                model=cp.model,
                multi_config=multi_speaker_config,
                callback_success=on_success,
                callback_error=on_error,
            )
            event.wait(timeout=300)  # 5 min timeout per segment
            if not event.is_set():
                cp.mark_failed(idx, "TTS API timeout (300s)")
                return None

            if result["error"]:
                cp.mark_failed(idx, result["error"][:120])
                return None

            if not result["pcm"]:
                cp.mark_failed(idx, "Empty audio response from API")
                return None

            # Resolve output filename from template
            stem = Path(cp.input_path).stem
            now = datetime.now()
            naming = cp.naming_template
            naming = naming.replace("{filename}", stem)
            naming = naming.replace("{date}", now.strftime("%Y%m%d"))
            naming = naming.replace("{time}", now.strftime("%H%M%S"))
            # Handle {index:03d} style
            if "{index:03d}" in naming:
                naming = naming.replace("{index:03d}", f"{idx:03d}")
            elif "{index}" in naming:
                naming = naming.replace("{index}", str(idx))
            else:
                naming = f"{naming}_{idx:03d}"

            output_path = Path(cp.output_path) / f"{naming}.wav"
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Use save_audio_file from TTSToolApp for consistency
            filename, save_error = tts_tool.save_audio_file(
                pcm_data=result["pcm"],
                wav_data=result["wav"],
                directory=str(output_path.parent),
                voice_name=cp.voice_name,
                format_ext="wav",
            )

            if save_error:
                cp.mark_failed(idx, save_error[:120])
                return None

            # Rename to match our naming template
            if filename:
                actual_path = Path(cp.output_path) / filename
                if actual_path.name != f"{naming}.wav":
                    actual_path.rename(output_path)

            return str(output_path)

        except Exception as e:
            cp.mark_failed(idx, str(e)[:120])
            return None

    # ── AI Director ───────────────────────────────────────────────────────────

    def _generate_style_with_director(self, text: str) -> Optional[str]:
        """Use AI Director to auto-generate TTS style instructions from text content."""
        try:
            from src.gui.tts_tool import get_instance as get_tts_tool

            tts_tool = get_tts_tool()
            if not tts_tool:
                print_warning("TTS Tool not initialized")
                return None

            # Use async method with blocking wait
            result = {"style": None, "error": None}
            event = threading.Event()

            def on_success(style, tokens):
                result["style"] = style
                event.set()

            def on_error(err):
                result["error"] = err
                event.set()

            tts_tool.run_director(text, callback_success=on_success, callback_error=on_error)
            event.wait(timeout=120)  # 2 min timeout for director
            if not event.is_set():
                print_warning("Director timed out (120s)")
                return None

            if result["error"]:
                print_warning(result["error"])
                return None

            return result["style"]

        except Exception as e:
            print_warning(f"Director error: {e}")
            return None

    # ── WAV merge ─────────────────────────────────────────────────────────────

    def _merge_wav_files(self, wav_paths: List[str], output_path: str):
        """Concatenate multiple WAV files into one (all must be 24kHz/16-bit/mono)."""
        output = wave.open(output_path, "wb")
        try:
            params_set = False

            for path in wav_paths:
                p = Path(path)
                if not p.exists():
                    continue
                with wave.open(str(p), "rb") as wf:
                    if not params_set:
                        output.setparams(wf.getparams())
                        params_set = True
                    output.writeframes(wf.readframes(wf.getnframes()))

            if not params_set:
                raise ValueError("No valid WAV files found to merge")
        finally:
            output.close()

    # ── Checkpoint resume helpers ─────────────────────────────────────────────

    def _prompt_resume_checkpoint(self) -> Optional[bool]:
        """Ask user whether to resume an existing main checkpoint. Returns True/False/None(cancel)."""
        cp = self.checkpoint_manager.load()
        if not cp:
            return False
        summary = cp.get_summary()
        self._print_header("⏸️  TTS CHECKPOINT FOUND")
        print(f"\nSession started: {summary['created_at'][:19]}")
        print(f"Progress:        {summary['completed']}/{summary['total_segments']} segments done")
        print(f"Voice: {summary['voice_name']}  |  Split: {summary['split_mode']}")
        print(f"Output: {summary['output_path']}")
        print("\n[R] Resume     [N] Start new job     [Q] Cancel")
        try:
            choice = input("\nChoice: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if choice == "r":
            return True
        if choice == "n":
            return False
        return None

    def _resume_from_checkpoint(self) -> ToolResult:
        self._current_checkpoint = self.checkpoint_manager.load()
        if not self._current_checkpoint:
            return ToolResult(success=False, message="Failed to load TTS checkpoint")
        return self._execute_processing()

    def _prompt_retry_failed(self) -> Optional[bool]:
        """Ask user whether to retry a failed-segments checkpoint. Returns True/False/None(cancel)."""
        cp = self.checkpoint_manager.load_failed()
        if not cp:
            return False
        self._print_header("⚠️  TTS FAILED CHECKPOINT FOUND")
        print(f"\n{len(cp.failed_segments)} segment(s) failed in a previous run.")
        print(f"Voice: {cp.voice_name}  |  Model: {cp.model}")
        print("\n[R] Retry failed segments     [N] Discard     [Q] Cancel")
        try:
            choice = input("\nChoice: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if choice == "r":
            return True
        if choice == "n":
            return False
        return None

    def _resume_from_failed_checkpoint(self) -> ToolResult:
        self._current_checkpoint = self.checkpoint_manager.load_failed()
        if not self._current_checkpoint:
            return ToolResult(success=False, message="Failed to load TTS failed checkpoint")
        self.checkpoint_manager.clear_failed()
        self.checkpoint_manager.save(self._current_checkpoint)
        return self._execute_processing()

    # ── Keyboard listener ─────────────────────────────────────────────────────

    def _start_keyboard_listener(self):
        """Start background thread listening for [P]ause and [S]top keys."""
        if not HAVE_MSVCRT:
            return
        # Stop any existing listener first
        self._stop_keyboard_listener()
        self._keyboard_stop_event = threading.Event()
        self._stop_requested = False

        def _listener():
            event = self._keyboard_stop_event  # Local reference to avoid race condition
            if event is None:
                return
            while not event.is_set():
                try:
                    if msvcrt.kbhit():
                        key = msvcrt.getch()
                        # Skip extended key codes
                        if key in (b"\x00", b"\xe0"):
                            msvcrt.getch()
                            continue
                        key_lower = key.lower()
                        if key_lower == b"p":
                            self.request_pause()
                            print("\n⏸️  Pause requested (press Enter in console to resume)...")
                        elif key_lower == b"s":
                            self.request_pause()
                            self._stop_requested = True
                            print("\n⏹️  Stop requested...")
                    time.sleep(0.05)
                except Exception:
                    break

        t = threading.Thread(target=_listener, daemon=True, name="tts_keyboard_listener")
        t.start()

    def _stop_keyboard_listener(self):
        """Signal the keyboard listener thread to stop."""
        if self._keyboard_stop_event is not None:
            self._keyboard_stop_event.set()
            self._keyboard_stop_event = None

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _print_header(self, title: str):
        print(f"\n{'═' * 60}")
        print(f" {title}")
        print(f"{'═' * 60}")
