#!/usr/bin/env python3
"""
File Handler - File type detection and content reading

Handles:
- File type detection (image, audio, text, code)
- Directory scanning with type categorization
- Reading file content for API consumption
- Building API messages with file content
"""

import base64
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


@dataclass
class FileInfo:
    """Information about a single file"""
    path: Path
    file_type: str  # "image", "text", "code", "unknown"
    extension: str
    size: int
    mime_type: Optional[str] = None
    
    @property
    def name(self) -> str:
        """Get filename without extension"""
        return self.path.stem
    
    @property
    def full_name(self) -> str:
        """Get full filename with extension"""
        return self.path.name
    
    def __str__(self) -> str:
        return str(self.path)


@dataclass
class ScanResult:
    """Result of scanning a directory or file"""
    input_path: Path
    files: List[FileInfo] = field(default_factory=list)
    by_type: Dict[str, List[FileInfo]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    
    @property
    def total_count(self) -> int:
        """Total number of files"""
        return len(self.files)
    
    @property
    def type_count(self) -> int:
        """Number of different file types"""
        return len(self.by_type)
    
    @property
    def has_mixed_types(self) -> bool:
        """Check if multiple file types are present"""
        return self.type_count > 1
    
    def get_type_summary(self) -> Dict[str, int]:
        """Get count per file type"""
        return {ft: len(files) for ft, files in self.by_type.items()}
    
    def filter_by_type(self, file_type: str) -> List[FileInfo]:
        """Get files of a specific type"""
        return self.by_type.get(file_type, [])


class FileHandler:
    """
    Handle file type detection and content reading.
    
    File Types:
    - image: Visual files processed via vision API
    - audio: Audio files processed via audio API
    - text: Plain text and markdown files
    - code: Source code files (processed as text)
    - unknown: Unrecognized file types
    """
    
    # Default file type mappings
    DEFAULT_FILE_TYPES = {
        "image": [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"],
        "audio": [".mp3", ".wav", ".aiff", ".aac", ".ogg", ".flac", ".m4a", ".wma"],
        "text": [".txt", ".md", ".rst", ".log", ".csv"],
        "document": [".pdf"],
        "code": [
            ".py", ".js", ".ts", ".jsx", ".tsx",  # Python, JavaScript, TypeScript
            ".java", ".kt", ".scala",  # JVM
            ".c", ".cpp", ".h", ".hpp", ".cc",  # C/C++
            ".go", ".rs", ".rb", ".php",  # Go, Rust, Ruby, PHP
            ".cs", ".swift", ".m",  # C#, Swift, Objective-C
            ".html", ".css", ".scss", ".sass", ".less",  # Web
            ".json", ".xml", ".yaml", ".yml", ".toml", ".ini",  # Config
            ".sql", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",  # Scripts
            ".r", ".R", ".jl", ".lua", ".pl", ".pm",  # Other
            ".vue", ".svelte", ".astro",  # Frameworks
            ".dockerfile", ".makefile", ".cmake",  # Build
        ]
    }
    
    def __init__(self, file_types: Dict[str, List[str]] = None):
        """
        Initialize FileHandler.
        
        Args:
            file_types: Custom file type mappings (overrides defaults)
        """
        self.file_types = file_types or self.DEFAULT_FILE_TYPES
        
        # Build reverse lookup (extension -> type)
        self._ext_to_type: Dict[str, str] = {}
        for file_type, extensions in self.file_types.items():
            for ext in extensions:
                self._ext_to_type[ext.lower()] = file_type
    
    def detect_type(self, filepath: Path) -> str:
        """
        Detect file type category.
        
        Args:
            filepath: Path to file
        
        Returns:
            File type: "image", "audio", "text", "code", or "unknown"
        """
        ext = filepath.suffix.lower()
        return self._ext_to_type.get(ext, "unknown")
    
    # Audio MIME type mapping (Gemini supported formats)
    AUDIO_MIME_TYPES = {
        ".mp3": "audio/mp3",
        ".wav": "audio/wav",
        ".aiff": "audio/aiff",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",  # M4A is typically AAC in MP4 container
        ".wma": "audio/x-ms-wma",
    }
    
    def get_file_info(self, filepath: Path) -> FileInfo:
        """
        Get detailed information about a file.
        
        Args:
            filepath: Path to file
        
        Returns:
            FileInfo with file details
        """
        file_type = self.detect_type(filepath)
        mime_type = None
        
        if file_type == "image":
            mime_type = mimetypes.guess_type(str(filepath))[0] or "image/png"
        elif file_type == "audio":
            ext = filepath.suffix.lower()
            mime_type = self.AUDIO_MIME_TYPES.get(ext) or mimetypes.guess_type(str(filepath))[0] or "audio/mp3"
        
        return FileInfo(
            path=filepath,
            file_type=file_type,
            extension=filepath.suffix.lower(),
            size=filepath.stat().st_size if filepath.exists() else 0,
            mime_type=mime_type
        )
    
    def scan(
        self,
        path: Path,
        recursive: bool = False,
        include_unknown: bool = False
    ) -> ScanResult:
        """
        Scan a file or directory.
        
        Args:
            path: Path to file or directory
            recursive: If directory, scan recursively
            include_unknown: Include unknown file types
        
        Returns:
            ScanResult with categorized files
        """
        path = Path(path)
        result = ScanResult(input_path=path)
        
        if path.is_file():
            # Single file
            info = self.get_file_info(path)
            if include_unknown or info.file_type != "unknown":
                result.files.append(info)
                result.by_type.setdefault(info.file_type, []).append(info)
        
        elif path.is_dir():
            # Directory
            pattern = "**/*" if recursive else "*"
            for file_path in sorted(path.glob(pattern)):
                if file_path.is_file():
                    info = self.get_file_info(file_path)
                    if include_unknown or info.file_type != "unknown":
                        result.files.append(info)
                        result.by_type.setdefault(info.file_type, []).append(info)
        
        else:
            result.warnings.append(f"Path does not exist: {path}")
        
        # Check for mixed types
        if result.has_mixed_types:
            result.warnings.append("mixed_file_types")
        
        return result
    
    def read_file(self, filepath: Path) -> Tuple[str, str, Optional[str]]:
        """
        Read file content for API consumption.
        
        Args:
            filepath: Path to file
        
        Returns:
            Tuple of (content_type, content, mime_type)
            - For images: ("image", base64_data, mime_type)
            - For audio: ("audio", base64_data, mime_type)
            - For text/code: ("text", text_content, None)
        """
        file_type = self.detect_type(filepath)
        
        if file_type == "image":
            mime_type = mimetypes.guess_type(str(filepath))[0] or "image/png"
            with open(filepath, "rb") as f:
                base64_data = base64.b64encode(f.read()).decode("utf-8")
            return ("image", base64_data, mime_type)
        
        elif file_type == "audio":
            ext = filepath.suffix.lower()
            mime_type = self.AUDIO_MIME_TYPES.get(ext) or mimetypes.guess_type(str(filepath))[0] or "audio/mp3"
            with open(filepath, "rb") as f:
                base64_data = base64.b64encode(f.read()).decode("utf-8")
            return ("audio", base64_data, mime_type)
        
        elif file_type == "document":
            mime_type = "application/pdf"
            with open(filepath, "rb") as f:
                base64_data = base64.b64encode(f.read()).decode("utf-8")
            return ("document", base64_data, mime_type)
        
        else:
            # Text or code - read as text
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                # Fallback to latin-1 for binary-ish text files
                with open(filepath, "r", encoding="latin-1") as f:
                    content = f.read()
            return ("text", content, None)
    
    def build_api_message(
        self,
        filepath: Path,
        prompt: str,
        include_filename: bool = True,
        display_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build API message with file content.
        
        Args:
            filepath: Path to file
            prompt: Processing prompt
            include_filename: Include filename in prompt for context
            display_name: Override display name for the file (e.g., original name
                         when filepath points to a processed temp file). If None,
                         uses filepath.name.
        
        Returns:
            Message dict in OpenAI format (for images) or Gemini format (for audio)
        """
        from src.messages import build_image_message, build_inline_message, build_text_message
        
        content_type, content, mime_type = self.read_file(filepath)
        
        # For non-text files, filename context is appended at the end of the prompt
        # (not prefixed) so the AI processes the main instructions first.
        filename_context = ""
        if include_filename and content_type in ("image", "audio", "document"):
            # Use the provided display_name, or fall back to the actual filepath name
            name = display_name or filepath.name
            filename_context = f"\n\n[File: {name}]"
        
        full_prompt = f"{prompt}{filename_context}" if filename_context else prompt
        
        if content_type == "image":
            # Returns list of messages; extract the user message (skip system)
            msgs = build_image_message(content, mime_type, full_prompt, None)
            for m in msgs:
                if m["role"] == "user":
                    return m
            return msgs[-1]  # Fallback to last message
        
        elif content_type == "audio":
            # Returns list of messages; extract the user message (skip system)
            msgs = build_inline_message(content, mime_type, full_prompt, None)
            for m in msgs:
                if m["role"] == "user":
                    return m
            return msgs[-1]  # Fallback to last message
        
        elif content_type == "document":
            # Document (PDF) message - use inline_data (preferred for Gemini)
            msgs = build_inline_message(content, mime_type, full_prompt, None)
            for m in msgs:
                if m["role"] == "user":
                    return m
            return msgs[-1]  # Fallback to last message
        
        else:
            # Text/code message - use TextEditTool-style delimiters
            # Note: filename is already included in <file_content> tag for text files
            file_type = self.detect_type(filepath)
            
            # Build file content with appropriate formatting
            if file_type == "code":
                # Code files get language-tagged fence
                ext = filepath.suffix.lower().lstrip(".")
                lang_map = {
                    "py": "python", "js": "javascript", "ts": "typescript",
                    "jsx": "jsx", "tsx": "tsx", "java": "java", "kt": "kotlin",
                    "c": "c", "cpp": "cpp", "h": "c", "hpp": "cpp",
                    "go": "go", "rs": "rust", "rb": "ruby", "php": "php",
                    "cs": "csharp", "swift": "swift", "sh": "bash",
                    "html": "html", "css": "css", "json": "json",
                    "xml": "xml", "yaml": "yaml", "yml": "yaml",
                    "sql": "sql", "md": "markdown",
                }
                lang = lang_map.get(ext, ext)
                file_content = f"```{lang}\n{content}\n```"
            else:
                file_content = content
            
            # Use structured delimiters (TextEditTool-style)
            if include_filename:
                final_prompt = f"{prompt}\n\n<file_content filename=\"{filepath.name}\">\n{file_content}\n</file_content>"
            else:
                final_prompt = f"{prompt}\n\n<file_content>\n{file_content}\n</file_content>"
            
            msgs = build_text_message(final_prompt, "You are a helper.")
            
            # Extract user message
            for m in msgs:
                if m["role"] == "user":
                    return m
            
            # Fallback
            return {"role": "user", "content": final_prompt}
    
    def get_output_path(
        self,
        input_path: Path,
        output_dir: Optional[Path],
        naming_template: str,
        extension: str,
        index: int = 0,
        base_input_path: Optional[Path] = None
    ) -> Path:
        """
        Generate output file path based on template.
        
        Template variables:
        - {filename}: Original filename without extension
        - {extension}: New extension (with dot)
        - {date}: Current date (YYYY-MM-DD)
        - {time}: Current time (HH-MM-SS)
        - {index}: File index (for batch processing)
        
        Args:
            input_path: Original input file path
            output_dir: Output directory (None = same as input)
            naming_template: Naming template string
            extension: Output file extension (e.g., ".md")
            index: File index for {index} variable
            base_input_path: Root input directory for recursive scans.
                When provided, the subdirectory structure of input_path
                relative to base_input_path is preserved under output_dir.
        
        Returns:
            Output file path
        """
        from datetime import datetime
        
        now = datetime.now()
        
        # Build template variables
        variables = {
            "filename": input_path.stem,
            "extension": extension,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H-%M-%S"),
            "index": str(index).zfill(3),
        }
        
        # Apply template
        output_name = naming_template
        for var, value in variables.items():
            output_name = output_name.replace(f"{{{var}}}", value)
        
        # Ensure extension is included
        if not output_name.endswith(extension):
            output_name += extension
        
        # Determine output directory
        if output_dir:
            out_dir = Path(output_dir)
        else:
            out_dir = input_path.parent
        
        # Preserve subdirectory structure for recursive scans
        if base_input_path:
            base = Path(base_input_path)
            try:
                relative_subdir = input_path.parent.relative_to(base)
                out_dir = out_dir / relative_subdir
            except ValueError:
                # input_path is not under base_input_path; fall back to flat
                pass
        
        return out_dir / output_name
    
    @classmethod
    def format_size(cls, size_bytes: int) -> str:
        """Format file size in human-readable form"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"