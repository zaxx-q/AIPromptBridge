#!/usr/bin/env python3
"""
Checkpoint Manager - Save and resume batch processing state

Provides:
- Checkpoint creation and persistence
- Resume from saved state
- Progress tracking across sessions
- Failed files checkpoint for retry
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple


@dataclass
class FileProcessorCheckpoint:
    """
    Checkpoint state for File Processor.
    
    Stores all information needed to resume a batch processing session.
    """
    
    # Session identification
    session_id: str
    created_at: str
    updated_at: str
    
    # Input configuration
    input_path: str
    input_files: List[str]  # Full list of file paths to process
    prompt_key: str  # Name of the prompt used
    prompt_text: str  # Actual prompt content
    
    # Output configuration
    output_mode: str  # "individual" or "combined"
    output_path: str  # Output directory
    naming_template: str  # File naming template
    output_extension: str  # Output file extension
    
    # Execution settings
    provider: str
    model: str
    delay_between_requests: float
    use_batch: bool = False
    
    # Audio processing settings (for resume without re-prompting)
    audio_preprocessing: Optional[Dict[str, Any]] = None
    
    # Custom instructions (for additional user context)
    custom_instructions: Optional[str] = None  # Batch-wide instructions
    per_file_instructions: Dict[str, str] = field(default_factory=dict)  # file_path -> instructions
    skip_per_file_prompts: bool = False  # User chose to skip all per-file prompts
    include_filename: bool = True  # Whether to include filename in AI context
    
    # Progress tracking
    completed_files: List[str] = field(default_factory=list)
    failed_files: List[Dict[str, str]] = field(default_factory=list)  # {"path": str, "error": str}
    current_index: int = 0
    
    # For combined output mode - accumulated content
    combined_output_content: str = ""
    
    # Retry checkpoint metadata
    is_retry_checkpoint: bool = False
    original_session_id: Optional[str] = None
    retry_count: int = 0
    original_errors: List[Dict[str, str]] = field(default_factory=list)  # Preserved from original for display
    
    @property
    def remaining_files(self) -> List[str]:
        """Get list of files not yet processed"""
        completed_set = set(self.completed_files)
        failed_set = {f["path"] for f in self.failed_files}
        processed = completed_set | failed_set
        return [f for f in self.input_files if f not in processed]
    
    @property
    def progress_percent(self) -> float:
        """Get progress as percentage"""
        if not self.input_files:
            return 0.0
        processed = len(self.completed_files) + len(self.failed_files)
        return (processed / len(self.input_files)) * 100
    
    @property
    def is_complete(self) -> bool:
        """Check if all files have been processed"""
        return len(self.remaining_files) == 0
    
    def mark_completed(self, file_path: str):
        """Mark a file as successfully completed"""
        if file_path not in self.completed_files:
            self.completed_files.append(file_path)
        self.current_index = len(self.completed_files) + len(self.failed_files)
        self.updated_at = datetime.now().isoformat()
    
    def mark_failed(self, file_path: str, error: str):
        """Mark a file as failed with error"""
        # Remove from completed if somehow there
        if file_path in self.completed_files:
            self.completed_files.remove(file_path)
        
        # Add to failed (update if already there)
        for i, f in enumerate(self.failed_files):
            if f["path"] == file_path:
                self.failed_files[i]["error"] = error
                break
        else:
            self.failed_files.append({"path": file_path, "error": error})
        
        self.current_index = len(self.completed_files) + len(self.failed_files)
        self.updated_at = datetime.now().isoformat()
    
    def append_combined_content(self, file_path: str, content: str, separator: str = None):
        """Append content to combined output (for combined mode)"""
        if separator is None:
            separator = f"\n\n---\n## {Path(file_path).name}\n\n"
        
        if self.combined_output_content:
            self.combined_output_content += separator
        self.combined_output_content += content
        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileProcessorCheckpoint":
        """Create from dictionary (filters out unknown arguments for compatibility)"""
        import inspect
        sig = inspect.signature(cls)
        valid_args = {k: v for k, v in data.items() if k in sig.parameters}
        return cls(**valid_args)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of checkpoint state"""
        summary = {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "prompt_key": self.prompt_key,
            "total_files": len(self.input_files),
            "completed": len(self.completed_files),
            "failed": len(self.failed_files),
            "remaining": len(self.remaining_files),
            "progress_percent": self.progress_percent,
            "output_path": self.output_path,
            "provider": self.provider,
            "model": self.model,
        }
        
        if self.is_retry_checkpoint:
            summary["is_retry_checkpoint"] = True
            summary["original_session_id"] = self.original_session_id
            summary["retry_count"] = self.retry_count
        
        return summary
    
    def get_failed_files_summary(self) -> List[Dict[str, str]]:
        """Get a list of failed files with their errors"""
        return self.failed_files.copy()
    
    def get_original_errors(self) -> List[Dict[str, str]]:
        """Get original errors for retry checkpoint (for display purposes)"""
        if self.is_retry_checkpoint and self.original_errors:
            return self.original_errors.copy()
        return self.failed_files.copy()
    
    @classmethod
    def create_retry_checkpoint(
        cls,
        original: "FileProcessorCheckpoint",
        failed_only: bool = True
    ) -> Optional["FileProcessorCheckpoint"]:
        """
        Create a new checkpoint for retrying failed files.
        
        Args:
            original: The original checkpoint with failed files
            failed_only: If True, only include failed files
            
        Returns:
            New checkpoint for retrying, or None if no files to retry
        """
        if not original.failed_files:
            return None
        
        # Get list of failed file paths
        failed_paths = [f["path"] for f in original.failed_files]
        
        if not failed_paths:
            return None
        
        now = datetime.now().isoformat()
        
        # Preserve original errors for display
        original_errors = original.failed_files.copy()
        
        # Filter per_file_instructions to only include failed files
        failed_per_file_instructions = {
            path: instructions
            for path, instructions in original.per_file_instructions.items()
            if path in failed_paths
        }
        
        return cls(
            session_id=str(uuid.uuid4())[:8],
            created_at=now,
            updated_at=now,
            input_path=original.input_path,
            input_files=failed_paths,  # Only the failed files
            prompt_key=original.prompt_key,
            prompt_text=original.prompt_text,
            output_mode=original.output_mode,
            output_path=original.output_path,
            naming_template=original.naming_template,
            output_extension=original.output_extension,
            provider=original.provider,
            model=original.model,
            delay_between_requests=original.delay_between_requests,
            use_batch=original.use_batch,
            audio_preprocessing=original.audio_preprocessing,  # Preserve audio settings
            custom_instructions=original.custom_instructions,  # Preserve batch instructions
            per_file_instructions=failed_per_file_instructions,  # Preserve per-file for failed files
            skip_per_file_prompts=original.skip_per_file_prompts,  # Preserve skip preference
            include_filename=original.include_filename,  # Preserve filename context preference
            completed_files=[],
            failed_files=[],  # Reset - these will be tracked fresh
            current_index=0,
            combined_output_content="",
            is_retry_checkpoint=True,
            original_session_id=original.session_id,
            retry_count=original.retry_count + 1,
            original_errors=original_errors  # Preserve original errors for display
        )


class CheckpointManager:
    """
    Manage checkpoint persistence for File Processor.
    
    Features:
    - Save/load checkpoint to JSON file
    - Create new checkpoints
    - Clear completed checkpoints
    - Query checkpoint existence and validity
    - Failed files checkpoint for retry
    """
    
    DEFAULT_CHECKPOINT_FILE = ".file_processor_checkpoint.json"
    FAILED_CHECKPOINT_FILE = ".file_processor_failed.json"
    
    def __init__(self, checkpoint_file: str = None, checkpoint_dir: Path = None):
        """
        Initialize CheckpointManager.
        
        Args:
            checkpoint_file: Checkpoint filename (default: .file_processor_checkpoint.json)
            checkpoint_dir: Directory for checkpoint file (default: current directory)
        """
        self.checkpoint_file = checkpoint_file or self.DEFAULT_CHECKPOINT_FILE
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else Path(".")
    
    @property
    def checkpoint_path(self) -> Path:
        """Get full path to checkpoint file"""
        return self.checkpoint_dir / self.checkpoint_file
    
    @property
    def failed_checkpoint_path(self) -> Path:
        """Get full path to failed files checkpoint"""
        return self.checkpoint_dir / self.FAILED_CHECKPOINT_FILE
    
    def exists(self) -> bool:
        """Check if a checkpoint file exists"""
        return self.checkpoint_path.exists()
    
    def failed_exists(self) -> bool:
        """Check if a failed files checkpoint exists"""
        return self.failed_checkpoint_path.exists()
    
    def load(self) -> Optional[FileProcessorCheckpoint]:
        """
        Load checkpoint from file.
        
        Returns:
            FileProcessorCheckpoint if exists and valid, None otherwise
        """
        if not self.exists():
            return None
        
        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return FileProcessorCheckpoint.from_dict(data)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            print(f"[Warning] Failed to load checkpoint: {e}")
            return None
    
    def save(self, checkpoint: FileProcessorCheckpoint):
        """
        Save checkpoint to file.
        
        Args:
            checkpoint: Checkpoint to save
        """
        checkpoint.updated_at = datetime.now().isoformat()
        
        # Ensure directory exists
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self.checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, indent=2, ensure_ascii=False)
    
    def clear(self):
        """Remove checkpoint file"""
        if self.exists():
            self.checkpoint_path.unlink()
    
    def load_failed(self) -> Optional[FileProcessorCheckpoint]:
        """
        Load failed files checkpoint.
        
        Returns:
            FileProcessorCheckpoint if exists and valid, None otherwise
        """
        if not self.failed_exists():
            return None
        
        try:
            with open(self.failed_checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return FileProcessorCheckpoint.from_dict(data)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            print(f"[Warning] Failed to load failed checkpoint: {e}")
            return None
    
    def save_failed(self, checkpoint: FileProcessorCheckpoint):
        """
        Save failed files checkpoint.
        
        Args:
            checkpoint: Checkpoint to save (should be a retry checkpoint)
        """
        checkpoint.updated_at = datetime.now().isoformat()
        
        # Ensure directory exists
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self.failed_checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, indent=2, ensure_ascii=False)
    
    def clear_failed(self):
        """Remove failed files checkpoint"""
        if self.failed_exists():
            self.failed_checkpoint_path.unlink()
    
    def create_failed_checkpoint(
        self,
        original: FileProcessorCheckpoint
    ) -> Optional[FileProcessorCheckpoint]:
        """
        Create and save a checkpoint for retrying failed files.
        
        Args:
            original: The original checkpoint with failed files
            
        Returns:
            The retry checkpoint, or None if no failed files
        """
        retry_checkpoint = FileProcessorCheckpoint.create_retry_checkpoint(original)
        
        if retry_checkpoint:
            self.save_failed(retry_checkpoint)
        
        return retry_checkpoint
    
    def get_failed_summary(self) -> Optional[Dict[str, Any]]:
        """
        Get summary of failed files checkpoint.
        
        Returns:
            Summary dict if failed checkpoint exists, None otherwise
        """
        checkpoint = self.load_failed()
        if checkpoint:
            return checkpoint.get_summary()
        return None
    
    def has_any_checkpoint(self) -> Tuple[bool, bool]:
        """
        Check for any checkpoint existence.
        
        Returns:
            Tuple of (has_main_checkpoint, has_failed_checkpoint)
        """
        return (self.exists(), self.failed_exists())
    
    def create(
        self,
        input_path: str,
        input_files: List[str],
        prompt_key: str,
        prompt_text: str,
        output_mode: str,
        output_path: str,
        naming_template: str,
        output_extension: str,
        provider: str,
        model: str,
        delay: float,
        use_batch: bool = False,
        audio_preprocessing: Optional[Dict[str, Any]] = None,
        custom_instructions: Optional[str] = None,
        skip_per_file_prompts: bool = False,
        include_filename: bool = True
    ) -> FileProcessorCheckpoint:
        """
        Create a new checkpoint.
        
        Args:
            input_path: Input file or directory path
            input_files: List of file paths to process
            prompt_key: Prompt name/key
            prompt_text: Actual prompt content
            output_mode: "individual" or "combined"
            output_path: Output directory
            naming_template: File naming template
            output_extension: Output file extension
            provider: AI provider name
            model: Model name
            delay: Delay between requests in seconds
            use_batch: Whether to use Batch API
            audio_preprocessing: Audio preprocessing settings (preset, intensity, optimization)
            custom_instructions: Batch-wide custom instructions for AI context
            skip_per_file_prompts: Whether to skip per-file instruction prompts
            include_filename: Whether to include filename in AI context
        
        Returns:
            New FileProcessorCheckpoint
        """
        now = datetime.now().isoformat()
        
        return FileProcessorCheckpoint(
            session_id=str(uuid.uuid4())[:8],
            created_at=now,
            updated_at=now,
            input_path=input_path,
            input_files=input_files,
            prompt_key=prompt_key,
            prompt_text=prompt_text,
            output_mode=output_mode,
            output_path=output_path,
            naming_template=naming_template,
            output_extension=output_extension,
            provider=provider,
            model=model,
            delay_between_requests=delay,
            use_batch=use_batch,
            audio_preprocessing=audio_preprocessing,
            custom_instructions=custom_instructions,
            per_file_instructions={},
            skip_per_file_prompts=skip_per_file_prompts,
            include_filename=include_filename,
            completed_files=[],
            failed_files=[],
            current_index=0,
            combined_output_content=""
        )
    
    def get_summary(self) -> Optional[Dict[str, Any]]:
        """
        Get summary of existing checkpoint without loading full data.
        
        Returns:
            Summary dict if checkpoint exists, None otherwise
        """
        checkpoint = self.load()
        if checkpoint:
            return checkpoint.get_summary()
        return None
    
    def can_resume(self, input_path: str = None) -> bool:
        """
        Check if checkpoint can be resumed.
        
        Args:
            input_path: Optional - verify checkpoint is for this input path
        
        Returns:
            True if checkpoint exists and is resumable
        """
        checkpoint = self.load()
        if not checkpoint:
            return False
        
        if checkpoint.is_complete:
            return False
        
        if input_path and checkpoint.input_path != input_path:
            return False
        
        return True
    
    def can_retry_failed(self) -> bool:
        """
        Check if there's a failed checkpoint that can be retried.
        
        Returns:
            True if failed checkpoint exists with files to retry
        """
        checkpoint = self.load_failed()
        if not checkpoint:
            return False
        
        return len(checkpoint.remaining_files) > 0


# ─────────────────────────────────────────────────────────────────────────────
# TTS Processor Checkpoint
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TTSCheckpoint:
    """
    Checkpoint state for TTS Processor.
    
    Stores all information needed to resume a batch TTS processing session.
    """
    
    # Session identification
    session_id: str
    created_at: str
    updated_at: str
    
    # Input
    input_path: str                      # Path to source text file
    segments: List[str]                  # Ordered list of text segments to synthesize
    split_mode: str                      # "lines", "paragraphs", "sentences", "whole"
    
    # Voice configuration
    voice_name: str
    model: str
    style_instructions: str              # Global style/tone for all segments
    speaker_mode: str                    # "single" or "multi"
    multi_speaker_config: Optional[List[Dict[str, str]]] = None  # [{name, voice}, ...]
    per_segment_styles: Dict[int, str] = field(default_factory=dict)  # idx -> style string
    
    # Output configuration
    output_mode: str = "individual"      # "individual" or "merge"
    output_path: str = ""                # Output directory
    naming_template: str = "{filename}_{index:03d}"
    
    # Execution settings
    delay_between_requests: float = 1.0
    
    # Progress tracking
    completed_segments: List[int] = field(default_factory=list)   # 0-based indices
    failed_segments: List[Dict] = field(default_factory=list)     # {idx, error}
    output_files: List[str] = field(default_factory=list)         # Paths of generated WAVs
    
    # Retry metadata
    is_retry_checkpoint: bool = False
    retry_count: int = 0
    
    @property
    def total_segments(self) -> int:
        return len(self.segments)
    
    @property
    def remaining_indices(self) -> List[int]:
        """Segment indices not yet processed."""
        done = set(self.completed_segments) | {f["idx"] for f in self.failed_segments}
        return [i for i in range(len(self.segments)) if i not in done]
    
    @property
    def progress_percent(self) -> float:
        if not self.segments:
            return 0.0
        processed = len(self.completed_segments) + len(self.failed_segments)
        return (processed / len(self.segments)) * 100
    
    @property
    def is_complete(self) -> bool:
        return len(self.remaining_indices) == 0
    
    def mark_completed(self, idx: int, output_file: str):
        if idx not in self.completed_segments:
            self.completed_segments.append(idx)
        if output_file and output_file not in self.output_files:
            self.output_files.append(output_file)
        self.updated_at = datetime.now().isoformat()
    
    def mark_failed(self, idx: int, error: str):
        # Remove from completed if somehow there
        if idx in self.completed_segments:
            self.completed_segments.remove(idx)
        # Update or append
        for entry in self.failed_segments:
            if entry["idx"] == idx:
                entry["error"] = error
                break
        else:
            self.failed_segments.append({"idx": idx, "error": error})
        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TTSCheckpoint":
        import inspect
        sig = inspect.signature(cls)
        valid_args = {k: v for k, v in data.items() if k in sig.parameters}
        return cls(**valid_args)
    
    def get_summary(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_segments": self.total_segments,
            "completed": len(self.completed_segments),
            "failed": len(self.failed_segments),
            "remaining": len(self.remaining_indices),
            "progress_percent": self.progress_percent,
            "voice_name": self.voice_name,
            "model": self.model,
            "output_path": self.output_path,
            "split_mode": self.split_mode,
        }
    
    @classmethod
    def create_retry_checkpoint(cls, original: "TTSCheckpoint") -> Optional["TTSCheckpoint"]:
        """Create a new checkpoint for retrying only failed segments."""
        if not original.failed_segments:
            return None
        
        now = datetime.now().isoformat()
        failed_indices = {f["idx"] for f in original.failed_segments}
        
        return cls(
            session_id=str(uuid.uuid4())[:8],
            created_at=now,
            updated_at=now,
            input_path=original.input_path,
            segments=original.segments,
            split_mode=original.split_mode,
            voice_name=original.voice_name,
            model=original.model,
            style_instructions=original.style_instructions,
            speaker_mode=original.speaker_mode,
            multi_speaker_config=original.multi_speaker_config,
            per_segment_styles={k: v for k, v in original.per_segment_styles.items() if int(k) in failed_indices},
            output_mode=original.output_mode,
            output_path=original.output_path,
            naming_template=original.naming_template,
            delay_between_requests=original.delay_between_requests,
            completed_segments=[],
            failed_segments=[],
            output_files=list(original.output_files),  # Keep existing outputs for merge
            is_retry_checkpoint=True,
            retry_count=original.retry_count + 1,
        )


class TTSCheckpointManager:
    """
    Manage checkpoint persistence for TTS Processor.
    """
    
    DEFAULT_CHECKPOINT_FILE = ".tts_processor_checkpoint.json"
    FAILED_CHECKPOINT_FILE = ".tts_processor_failed.json"
    
    def __init__(self, checkpoint_dir: Path = None):
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else Path(".")
    
    @property
    def checkpoint_path(self) -> Path:
        return self.checkpoint_dir / self.DEFAULT_CHECKPOINT_FILE
    
    @property
    def failed_checkpoint_path(self) -> Path:
        return self.checkpoint_dir / self.FAILED_CHECKPOINT_FILE
    
    def exists(self) -> bool:
        return self.checkpoint_path.exists()
    
    def failed_exists(self) -> bool:
        return self.failed_checkpoint_path.exists()
    
    def has_any_checkpoint(self) -> Tuple[bool, bool]:
        return (self.exists(), self.failed_exists())
    
    def load(self) -> Optional[TTSCheckpoint]:
        if not self.exists():
            return None
        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return TTSCheckpoint.from_dict(data)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            print(f"[Warning] Failed to load TTS checkpoint: {e}")
            return None
    
    def save(self, checkpoint: TTSCheckpoint):
        checkpoint.updated_at = datetime.now().isoformat()
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        with open(self.checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, indent=2, ensure_ascii=False)
    
    def clear(self):
        if self.exists():
            self.checkpoint_path.unlink()
    
    def load_failed(self) -> Optional[TTSCheckpoint]:
        if not self.failed_exists():
            return None
        try:
            with open(self.failed_checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return TTSCheckpoint.from_dict(data)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            print(f"[Warning] Failed to load TTS failed checkpoint: {e}")
            return None
    
    def save_failed(self, checkpoint: TTSCheckpoint):
        checkpoint.updated_at = datetime.now().isoformat()
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        with open(self.failed_checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, indent=2, ensure_ascii=False)
    
    def clear_failed(self):
        if self.failed_exists():
            self.failed_checkpoint_path.unlink()
    
    def create_failed_checkpoint(self, original: TTSCheckpoint) -> Optional[TTSCheckpoint]:
        retry = TTSCheckpoint.create_retry_checkpoint(original)
        if retry:
            self.save_failed(retry)
        return retry
    
    def create(
        self,
        input_path: str,
        segments: List[str],
        split_mode: str,
        voice_name: str,
        model: str,
        style_instructions: str,
        speaker_mode: str,
        output_mode: str,
        output_path: str,
        naming_template: str,
        delay: float,
        multi_speaker_config: Optional[List[Dict[str, str]]] = None,
        per_segment_styles: Optional[Dict[int, str]] = None,
    ) -> TTSCheckpoint:
        now = datetime.now().isoformat()
        return TTSCheckpoint(
            session_id=str(uuid.uuid4())[:8],
            created_at=now,
            updated_at=now,
            input_path=input_path,
            segments=segments,
            split_mode=split_mode,
            voice_name=voice_name,
            model=model,
            style_instructions=style_instructions,
            speaker_mode=speaker_mode,
            multi_speaker_config=multi_speaker_config,
            per_segment_styles=per_segment_styles or {},
            output_mode=output_mode,
            output_path=output_path,
            naming_template=naming_template,
            delay_between_requests=delay,
            completed_segments=[],
            failed_segments=[],
            output_files=[],
        )
