#!/usr/bin/env python3
"""
Attachment Manager - Handles session attachment storage and retrieval.

Provides persistent storage for session attachments (images, files) as external files,
eliminating the need to store base64 data inline in session JSON.

Storage Structure:
    session_attachments/
    ├── {session_id}/
    │   ├── {message_index}_{timestamp}_{filename}.{format}
    │   └── ...
    └── ...

Supported Formats:
    - WebP (default) - best compression/quality ratio
    - PNG - lossless, larger files
    - JPEG - lossy, smaller files
    - AVIF - modern format, excellent compression (requires pillow-avif-plugin)
"""

import base64
import io
import logging
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Optional PIL import for image processing
try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False
    logging.warning("[AttachmentManager] PIL not available, image conversion disabled")


# Directory for storing session attachments
ATTACHMENTS_DIR = "session_attachments"

# Lock for thread-safe file operations
_FILE_LOCK = threading.Lock()


class AttachmentManager:
    """
    Manages session attachment storage and retrieval.
    
    All methods are class methods for easy access without instantiation.
    Thread-safe for concurrent access from multiple windows/threads.
    """
    
    # Supported image formats with their MIME types
    FORMAT_MIME_MAP = {
        # Images
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "avif": "image/avif",
        "gif": "image/gif",
        "bmp": "image/bmp",
        # Documents
        "pdf": "application/pdf",
        "txt": "text/plain",
        "md": "text/markdown",
        # Audio
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "ogg": "audio/ogg",
        "opus": "audio/opus",
        "flac": "audio/flac",
        "webm": "audio/webm",
    }
    
    # Reverse mapping: MIME type to extension
    MIME_FORMAT_MAP = {
        # Images
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/avif": "avif",
        "image/gif": "gif",
        "image/bmp": "bmp",
        # Documents
        "application/pdf": "pdf",
        "text/plain": "txt",
        "text/markdown": "md",
        # Audio
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/ogg": "ogg",
        "audio/opus": "opus",
        "audio/flac": "flac",
        "audio/webm": "webm",
    }
    
    # Default format and quality
    DEFAULT_FORMAT = "webp"
    DEFAULT_QUALITY = 85
    
    # Formats that should be treated as images for conversion/thumbnailing
    IMAGE_FORMATS = {"png", "jpg", "jpeg", "webp", "avif", "gif", "bmp", "tiff", "tif"}
    
    @classmethod
    def _get_config(cls) -> Tuple[str, int]:
        """
        Get image format and quality from config.
        
        Returns:
            Tuple of (format, quality)
        """
        try:
            from .config import load_config
            config, _, _, _ = load_config()
            fmt = config.get("session_image_format", cls.DEFAULT_FORMAT).lower()
            quality = config.get("session_image_quality", cls.DEFAULT_QUALITY)
            
            # Validate format
            if fmt not in cls.FORMAT_MIME_MAP:
                logging.warning(f"[AttachmentManager] Invalid format '{fmt}', using {cls.DEFAULT_FORMAT}")
                fmt = cls.DEFAULT_FORMAT
            
            # Validate quality
            if not isinstance(quality, int) or quality < 1 or quality > 100:
                logging.warning(f"[AttachmentManager] Invalid quality '{quality}', using {cls.DEFAULT_QUALITY}")
                quality = cls.DEFAULT_QUALITY
            
            return fmt, quality
        except Exception as e:
            logging.debug(f"[AttachmentManager] Config load failed: {e}, using defaults")
            return cls.DEFAULT_FORMAT, cls.DEFAULT_QUALITY
    
    @classmethod
    def _get_session_dir(cls, session_id: int) -> Path:
        """Get the directory path for a session's attachments."""
        return Path(ATTACHMENTS_DIR) / str(session_id)
    
    @classmethod
    def _ensure_session_dir(cls, session_id: int) -> Path:
        """Create session directory if it doesn't exist."""
        session_dir = cls._get_session_dir(session_id)
        with _FILE_LOCK:
            session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir
    
    @classmethod
    def _sanitize_filename(cls, filename: str) -> str:
        """Sanitize filename to be safe for filesystem."""
        # Remove or replace unsafe characters
        safe = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Limit length
        if len(safe) > 50:
            name, ext = os.path.splitext(safe)
            safe = name[:45] + ext
        return safe or "attachment"
    
    @classmethod
    def save_image(
        cls,
        session_id: int,
        image_base64: str,
        mime_type: str,
        message_index: int = 0,
        original_filename: Optional[str] = None
    ) -> str:
        """
        Save image to external file and return relative path.
        
        Converts the image to the configured format (WebP by default) for
        consistent storage and optimal file size.
        
        Args:
            session_id: The session ID
            image_base64: Base64 encoded image data
            mime_type: Original MIME type (e.g., "image/png")
            message_index: Index of the message (for ordering)
            original_filename: Optional original filename
            
        Returns:
            Relative path to saved file (e.g., "session_attachments/5/0_1706000000_image.webp")
        """
        if not HAVE_PIL:
            logging.error("[AttachmentManager] PIL required for image saving")
            return ""
        
        try:
            # Get config
            target_format, quality = cls._get_config()
            target_mime = cls.FORMAT_MIME_MAP.get(target_format, "image/webp")
            
            # Generate filename
            timestamp = int(time.time())
            if original_filename:
                base_name = cls._sanitize_filename(os.path.splitext(original_filename)[0])
            else:
                base_name = "image"
            filename = f"{message_index}_{timestamp}_{base_name}.{target_format}"
            
            # Ensure directory exists
            session_dir = cls._ensure_session_dir(session_id)
            file_path = session_dir / filename
            
            # Decode base64
            image_data = base64.b64decode(image_base64)
            
            # Open and convert image
            with io.BytesIO(image_data) as input_buffer:
                img = Image.open(input_buffer)
                
                # Convert to RGB if necessary (for formats that don't support alpha)
                if target_format in ("jpg", "jpeg") and img.mode in ("RGBA", "P"):
                    # Create white background for transparency
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    background.paste(img, mask=img.split()[-1] if len(img.split()) == 4 else None)
                    img = background
                elif target_format not in ("png", "gif") and img.mode == "P":
                    img = img.convert("RGB")
                
                # Save with quality setting for lossy formats
                with _FILE_LOCK:
                    if target_format in ("jpg", "jpeg", "webp", "avif"):
                        img.save(file_path, quality=quality, optimize=True)
                    elif target_format == "png":
                        img.save(file_path, optimize=True)
                    else:
                        img.save(file_path)
            
            relative_path = str(file_path)
            logging.debug(f"[AttachmentManager] Saved image: {relative_path}")
            return relative_path
            
        except Exception as e:
            logging.error(f"[AttachmentManager] Failed to save image: {e}")
            return ""
    
    @classmethod
    def save_audio(
        cls,
        session_id: int,
        audio_data: bytes,
        mime_type: str,
        message_index: int = 0,
        original_filename: Optional[str] = None
    ) -> str:
        """
        Save audio data to external file and return relative path.
        
        Unlike images, audio files are saved as-is without conversion
        to preserve quality and compatibility.
        
        Args:
            session_id: The session ID
            audio_data: Raw audio bytes
            mime_type: MIME type (e.g., "audio/wav", "audio/ogg")
            message_index: Index of the message (for ordering)
            original_filename: Optional original filename
            
        Returns:
            Relative path to saved file (e.g., "session_attachments/5/0_1706000000_audio.wav")
        """
        try:
            # Determine extension from MIME type
            extension = cls.MIME_FORMAT_MAP.get(mime_type, "wav")
            
            # Generate filename
            timestamp = int(time.time())
            if original_filename:
                base_name = cls._sanitize_filename(os.path.splitext(original_filename)[0])
            else:
                base_name = "audio"
            filename = f"{message_index}_{timestamp}_{base_name}.{extension}"
            
            # Ensure directory exists
            session_dir = cls._ensure_session_dir(session_id)
            file_path = session_dir / filename
            
            # Write audio data
            with _FILE_LOCK:
                with open(file_path, "wb") as f:
                    f.write(audio_data)
            
            relative_path = str(file_path)
            logging.debug(f"[AttachmentManager] Saved audio: {relative_path}")
            return relative_path
            
        except Exception as e:
            logging.error(f"[AttachmentManager] Failed to save audio: {e}")
            return ""
    
    @classmethod
    def save_file(
        cls,
        session_id: int,
        file_path: str,
        message_index: int = 0
    ) -> str:
        """
        Copy a file to session attachments directory.
        
        For images, converts to configured format. For other files, copies as-is.
        
        Args:
            session_id: The session ID
            file_path: Path to the source file
            message_index: Index of the message (for ordering)
            
        Returns:
            Relative path to saved file
        """
        source = Path(file_path)
        if not source.exists():
            logging.error(f"[AttachmentManager] Source file not found: {file_path}")
            return ""
        
        # Check if it's an image that should be converted
        extension = source.suffix.lower().lstrip(".")
        if extension in cls.IMAGE_FORMATS and HAVE_PIL:
            # Read and convert image
            try:
                with open(source, "rb") as f:
                    image_data = f.read()
                image_base64 = base64.b64encode(image_data).decode("ascii")
                mime_type = cls.FORMAT_MIME_MAP.get(extension, "image/png")
                return cls.save_image(
                    session_id, image_base64, mime_type,
                    message_index, source.name
                )
            except Exception as e:
                logging.error(f"[AttachmentManager] Failed to convert image: {e}")
        
        # Non-image file: copy as-is
        try:
            timestamp = int(time.time())
            filename = f"{message_index}_{timestamp}_{cls._sanitize_filename(source.name)}"
            session_dir = cls._ensure_session_dir(session_id)
            dest_path = session_dir / filename
            
            with _FILE_LOCK:
                shutil.copy2(source, dest_path)
            
            logging.debug(f"[AttachmentManager] Copied file: {dest_path}")
            return str(dest_path)
            
        except Exception as e:
            logging.error(f"[AttachmentManager] Failed to copy file: {e}")
            return ""
    
    @classmethod
    def load_image(cls, file_path: str) -> Tuple[str, str]:
        """
        Load image from file and return base64 data.
        
        Args:
            file_path: Path to the image file
            
        Returns:
            Tuple of (base64_data, mime_type)
            Returns ("", "") if file not found or load fails
        """
        path = Path(file_path)
        if not path.exists():
            logging.warning(f"[AttachmentManager] File not found: {file_path}")
            return "", ""
        
        try:
            with _FILE_LOCK:
                with open(path, "rb") as f:
                    data = f.read()
            
            # Determine MIME type from extension
            extension = path.suffix.lower().lstrip(".")
            mime_type = cls.FORMAT_MIME_MAP.get(extension, "application/octet-stream")
            
            # Encode to base64
            base64_data = base64.b64encode(data).decode("ascii")
            
            return base64_data, mime_type
            
        except Exception as e:
            logging.error(f"[AttachmentManager] Failed to load image: {e}")
            return "", ""
    
    @classmethod
    def get_attachment_info(cls, file_path: str) -> Dict:
        """
        Get information about an attachment file.
        
        Args:
            file_path: Path to the attachment
            
        Returns:
            Dict with keys: exists, size, mime_type, width, height (for images)
        """
        path = Path(file_path)
        info = {
            "exists": path.exists(),
            "path": file_path,
            "size": 0,
            "mime_type": "",
        }
        
        if not path.exists():
            return info
        
        try:
            info["size"] = path.stat().st_size
            extension = path.suffix.lower().lstrip(".")
            info["mime_type"] = cls.FORMAT_MIME_MAP.get(extension, "application/octet-stream")
            
            # Get image dimensions if it's an image and PIL is available
            if HAVE_PIL and extension in cls.IMAGE_FORMATS:
                try:
                    with Image.open(path) as img:
                        info["width"] = img.width
                        info["height"] = img.height
                except Exception:
                    pass
            
        except Exception as e:
            logging.debug(f"[AttachmentManager] Error getting info: {e}")
        
        return info
    
    @classmethod
    def list_session_attachments(cls, session_id: int) -> List[str]:
        """
        List all attachment paths for a session.
        
        Args:
            session_id: The session ID
            
        Returns:
            List of relative paths to attachments
        """
        session_dir = cls._get_session_dir(session_id)
        if not session_dir.exists():
            return []
        
        attachments = []
        try:
            for file in session_dir.iterdir():
                if file.is_file():
                    attachments.append(str(file))
        except Exception as e:
            logging.error(f"[AttachmentManager] Failed to list attachments: {e}")
        
        return sorted(attachments)
    
    @classmethod
    def delete_attachment(cls, file_path: str) -> bool:
        """
        Delete a single attachment file.
        
        Args:
            file_path: Path to the attachment
            
        Returns:
            True if deleted successfully
        """
        path = Path(file_path)
        if not path.exists():
            return True  # Already gone
        
        try:
            with _FILE_LOCK:
                path.unlink()
            logging.debug(f"[AttachmentManager] Deleted: {file_path}")
            return True
        except Exception as e:
            logging.error(f"[AttachmentManager] Failed to delete: {e}")
            return False
    
    @classmethod
    def delete_session_attachments(cls, session_id: int) -> bool:
        """
        Delete all attachments for a session.
        
        Args:
            session_id: The session ID
            
        Returns:
            True if deleted successfully
        """
        session_dir = cls._get_session_dir(session_id)
        if not session_dir.exists():
            return True  # Already clean
        
        try:
            with _FILE_LOCK:
                shutil.rmtree(session_dir)
            logging.info(f"[AttachmentManager] Deleted session attachments: {session_id}")
            return True
        except Exception as e:
            logging.error(f"[AttachmentManager] Failed to delete session attachments: {e}")
            return False
    
    @classmethod
    def cleanup_orphaned_attachments(cls) -> int:
        """
        Remove attachment folders for sessions that no longer exist.
        
        Compares attachment directories against existing sessions and
        removes any orphaned directories.
        
        Returns:
            Number of orphaned directories removed
        """
        attachments_path = Path(ATTACHMENTS_DIR)
        if not attachments_path.exists():
            return 0
        
        removed = 0
        
        try:
            # Get existing session IDs
            from .session_manager import CHAT_SESSIONS
            existing_ids = set(str(sid) for sid in CHAT_SESSIONS.keys())
            
            # Check each attachment directory
            for item in attachments_path.iterdir():
                if item.is_dir() and item.name not in existing_ids:
                    try:
                        with _FILE_LOCK:
                            shutil.rmtree(item)
                        logging.info(f"[AttachmentManager] Removed orphaned: {item.name}")
                        removed += 1
                    except Exception as e:
                        logging.warning(f"[AttachmentManager] Failed to remove {item.name}: {e}")
            
        except Exception as e:
            logging.error(f"[AttachmentManager] Cleanup error: {e}")
        
        return removed
    
    @classmethod
    def get_total_size(cls) -> int:
        """
        Get total size of all attachments in bytes.
        
        Returns:
            Total size in bytes
        """
        attachments_path = Path(ATTACHMENTS_DIR)
        if not attachments_path.exists():
            return 0
        
        total = 0
        try:
            for root, _, files in os.walk(attachments_path):
                for file in files:
                    try:
                        total += os.path.getsize(os.path.join(root, file))
                    except OSError:
                        pass
        except Exception:
            pass
        
        return total
    
    @classmethod
    def format_size(cls, size_bytes: int) -> str:
        """Format size in bytes to human-readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


# Convenience functions for external use
def save_session_image(session_id: int, image_base64: str, mime_type: str, 
                       message_index: int = 0) -> str:
    """Save image to session attachments and return path."""
    return AttachmentManager.save_image(session_id, image_base64, mime_type, message_index)


def load_session_image(file_path: str) -> Tuple[str, str]:
    """Load image from session attachments and return (base64, mime_type)."""
    return AttachmentManager.load_image(file_path)


def delete_session_attachments(session_id: int) -> bool:
    """Delete all attachments for a session."""
    return AttachmentManager.delete_session_attachments(session_id)
