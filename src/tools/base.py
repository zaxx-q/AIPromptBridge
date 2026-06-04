#!/usr/bin/env python3
"""
Base Tool Abstract Class

Provides common interface and utilities for all tools.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ToolStatus(Enum):
    """Status of a tool operation"""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ToolResult:
    """Result from a tool operation"""

    success: bool
    message: str = ""
    output_path: Optional[str] = None
    output_paths: List[str] = field(default_factory=list)
    processed_count: int = 0
    failed_count: int = 0
    total_count: int = 0
    elapsed_time: float = 0.0
    errors: List[Dict[str, str]] = field(default_factory=list)

    def add_error(self, file_path: str, error: str):
        """Add an error for a specific file"""
        self.errors.append({"path": file_path, "error": error})
        self.failed_count += 1


class BaseTool(ABC):
    """
    Abstract base class for all tools.

    Tools are interactive workflows that process files or data using AI.
    They support:
    - Configuration via tools_config.json
    - Progress tracking
    - Pause/Resume functionality
    - Checkpoint persistence
    """

    def __init__(self, name: str, config: Dict[str, Any] | None = None):
        """
        Initialize a tool.

        Args:
            name: Tool name (used for config lookup)
            config: Tool configuration dictionary
        """
        self.name = name
        self.config = config or {}
        self.status = ToolStatus.IDLE
        self._abort_requested = False
        self._pause_requested = False

    @property
    def is_running(self) -> bool:
        """Check if tool is currently running"""
        return self.status == ToolStatus.RUNNING

    @property
    def is_paused(self) -> bool:
        """Check if tool is paused"""
        return self.status == ToolStatus.PAUSED

    def request_abort(self):
        """Request the tool to abort processing"""
        self._abort_requested = True

    def request_pause(self):
        """Request the tool to pause processing"""
        self._pause_requested = True

    def request_resume(self):
        """Request the tool to resume processing"""
        self._pause_requested = False
        if self.status == ToolStatus.PAUSED:
            self.status = ToolStatus.RUNNING

    def check_abort(self) -> bool:
        """Check if abort was requested"""
        return self._abort_requested

    def check_pause(self) -> bool:
        """
        Check if pause was requested.
        If paused, blocks until resume or abort.

        Returns:
            True if should continue, False if aborted
        """
        if self._pause_requested:
            self.status = ToolStatus.PAUSED
            # Will be handled by the processing loop
            return False
        return True

    def reset(self):
        """Reset tool state for new run"""
        self.status = ToolStatus.IDLE
        self._abort_requested = False
        self._pause_requested = False

    @abstractmethod
    def run_interactive(self) -> ToolResult:
        """
        Run the tool interactively in terminal.

        This method should:
        1. Gather input from user
        2. Configure processing options
        3. Execute processing with progress display
        4. Return result

        Returns:
            ToolResult with processing outcome
        """
        raise NotImplementedError

    @abstractmethod
    def run_batch(self, input_path: str, prompt: str, output_config: Dict[str, Any], **kwargs) -> ToolResult:
        """
        Run the tool in batch mode (non-interactive).

        Args:
            input_path: Path to input file or folder
            prompt: Processing prompt
            output_config: Output configuration
            **kwargs: Additional tool-specific options

        Returns:
            ToolResult with processing outcome
        """
        raise NotImplementedError

    def get_config_value(self, key: str, default: Any = None) -> Any:
        """Get a configuration value with fallback to default"""
        return self.config.get(key, default)
