"""
Native Gemini API Provider

Uses the native Gemini API format (camelCase) with full feature support:
- thinkingConfig with thinkingBudget (Gemini 2.5) or thinkingLevel (Gemini 3)
- Safety settings with BLOCK_NONE
- Streaming via streamGenerateContent endpoint
- Full retry logic matching reverse-proxy behavior
- Files API for large file uploads (>15 MB)

"""

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
import requests

from .base import (
    BaseProvider,
    ProviderResult,
    StreamCallback,
    UsageData,
    CallbackType,
    RetryReason,
    estimate_tokens,
    estimate_message_tokens
)


# Base URL for Gemini API
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Safety settings - must use BLOCK_NONE per JSON-request-reference.md
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
]


# Maximum size for inline data (15 MB to be safe, actual limit is 20 MB for total request)
MAX_INLINE_SIZE_BYTES = 15 * 1024 * 1024


@dataclass
class UploadedFile:
    """Represents a file uploaded to the Gemini Files API"""
    name: str
    uri: str
    mime_type: str
    size_bytes: int
    display_name: Optional[str] = None
    
    def to_file_data_part(self) -> Dict:
        """Convert to fileData part for generateContent request"""
        return {
            "fileData": {
                "mimeType": self.mime_type,
                "fileUri": self.uri
            }
        }


class GeminiNativeProvider(BaseProvider):
    """
    Provider for native Gemini API.
    
    Features:
    - Native Gemini format (camelCase)
    - thinkingConfig with budget (2.5) or level (3.x)
    - Streaming with retry logic
    - Empty response detection and retry
    - Key rotation on errors
    
    Thinking configuration (per JSON-request-reference.md):
    - Gemini 2.5: thinkingBudget (integer token count, -1 = auto/unlimited)
    - Gemini 3.x: thinkingLevel ("low" or "high")
    
    Files API:
    - Files > 15 MB are uploaded via Files API
    - Files are automatically deleted after 48 hours
    - Maximum file size: 2 GB
    - Maximum storage: 20 GB per project
    """
    
    def __init__(self, key_manager=None, config: Optional[Dict] = None):
        """
        Initialize the Gemini Native provider.
        
        Args:
            key_manager: Key manager for API key rotation
            config: Configuration dict with thinking settings:
                - thinking_budget: Token budget for 2.5 models (-1 = auto)
                - thinking_level: Level for 3.x models ("high" or "low")
        """

        super().__init__("Gemini-Native", key_manager, config)
        
        # Use custom endpoint if configured, otherwise default
        self.base_url = self.config.get("gemini_endpoint")
        if not self.base_url:
            self.base_url = GEMINI_BASE_URL
            
        self._uploaded_files: Dict[str, UploadedFile] = {}  # Cache of uploaded files
    
    # =========================================================================
    # FILES API METHODS
    # =========================================================================
    
    def upload_file(self, filepath: Path, display_name: Optional[str] = None) -> Tuple[Optional[UploadedFile], Optional[str]]:
        """
        Upload a file to Gemini Files API using resumable upload.
        
        Files are automatically deleted after 48 hours.
        
        Args:
            filepath: Path to file to upload
            display_name: Optional display name for the file
            
        Returns:
            Tuple of (UploadedFile, None) on success or (None, error_message) on failure
        """
        if not self.key_manager or not self.key_manager.has_keys():
            return None, "No API keys configured for Gemini"
        
        current_key = self.key_manager.get_current_key()
        if not current_key:
            return None, "No API key available"
        
        filepath = Path(filepath)
        if not filepath.exists():
            return None, f"File not found: {filepath}"
        
        # Detect MIME type
        import mimetypes
        mime_type = mimetypes.guess_type(str(filepath))[0]
        if not mime_type:
            # Fallback for common audio types
            ext_to_mime = {
                ".mp3": "audio/mp3",
                ".wav": "audio/wav",
                ".aiff": "audio/aiff",
                ".aac": "audio/aac",
                ".ogg": "audio/ogg",
                ".flac": "audio/flac",
                ".m4a": "audio/mp4",
                ".wma": "audio/x-ms-wma",
            }
            mime_type = ext_to_mime.get(filepath.suffix.lower(), "application/octet-stream")
        
        file_size = filepath.stat().st_size
        if display_name is None:
            display_name = filepath.name
        
        self.log("info", f"Uploading file: {filepath.name} ({file_size / (1024*1024):.1f} MB)")
        
        try:
            # Step 1: Initiate resumable upload
            # Handle base URL that might already have /v1beta (strip it for upload)
            base = self.base_url
            if base.endswith("/v1beta"):
                base = base[:-7]
            
            init_url = f"{base}/upload/v1beta/files"
            
            init_headers = {
                "x-goog-api-key": current_key,
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(file_size),
                "X-Goog-Upload-Header-Content-Type": mime_type,
                "Content-Type": "application/json"
            }
            
            init_body = {
                "file": {
                    "display_name": display_name
                }
            }
            
            init_response = requests.post(
                init_url,
                headers=init_headers,
                json=init_body,
                timeout=60
            )
            
            if init_response.status_code != 200:
                return None, f"Failed to initiate upload ({init_response.status_code}): {init_response.text[:200]}"
            
            # Get upload URL from response headers
            upload_url = init_response.headers.get("x-goog-upload-url")
            if not upload_url:
                # Sometimes it's in a different header
                upload_url = init_response.headers.get("X-Goog-Upload-URL")
            
            if not upload_url:
                return None, "Failed to get upload URL from response headers"
            
            # Step 2: Upload the actual file bytes
            with open(filepath, "rb") as f:
                file_data = f.read()
            
            upload_headers = {
                "Content-Length": str(file_size),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize"
            }
            
            upload_response = requests.post(
                upload_url,
                headers=upload_headers,
                data=file_data,
                timeout=300  # 5 minutes for large files
            )
            
            if upload_response.status_code != 200:
                return None, f"Failed to upload file ({upload_response.status_code}): {upload_response.text[:200]}"
            
            # Parse response to get file info
            file_info = upload_response.json()
            file_obj = file_info.get("file", {})
            
            uploaded = UploadedFile(
                name=file_obj.get("name", ""),
                uri=file_obj.get("uri", ""),
                mime_type=mime_type,
                size_bytes=file_size,
                display_name=display_name
            )
            
            # Cache the uploaded file
            self._uploaded_files[str(filepath)] = uploaded
            
            self.log("info", f"File uploaded successfully: {uploaded.uri}")
            return uploaded, None
            
        except requests.exceptions.Timeout:
            return None, "Upload timed out"
        except requests.exceptions.RequestException as e:
            return None, f"Upload failed: {e}"
        except Exception as e:
            return None, f"Unexpected error during upload: {e}"
    
    def get_file_info(self, file_name: str) -> Tuple[Optional[Dict], Optional[str]]:
        """
        Get metadata for an uploaded file.
        
        Args:
            file_name: The file name returned from upload (e.g., "files/abc123")
            
        Returns:
            Tuple of (file_info_dict, None) on success or (None, error_message) on failure
        """
        if not self.key_manager or not self.key_manager.has_keys():
            return None, "No API keys configured"
        
        current_key = self.key_manager.get_current_key()
        if not current_key:
            return None, "No API key available"
        
        url = f"{self.base_url}/{file_name}"
        headers = {"x-goog-api-key": current_key}
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                return None, f"Failed to get file info ({response.status_code}): {response.text[:200]}"
            
            return response.json(), None
            
        except Exception as e:
            return None, f"Error getting file info: {e}"
    
    def delete_file(self, file_name: str) -> Tuple[bool, Optional[str]]:
        """
        Delete an uploaded file.
        
        Args:
            file_name: The file name to delete (e.g., "files/abc123")
            
        Returns:
            Tuple of (success, error_message)
        """
        if not self.key_manager or not self.key_manager.has_keys():
            return False, "No API keys configured"
        
        current_key = self.key_manager.get_current_key()
        if not current_key:
            return False, "No API key available"
        
        url = f"{self.base_url}/{file_name}"
        headers = {"x-goog-api-key": current_key}
        
        try:
            response = requests.delete(url, headers=headers, timeout=30)
            
            if response.status_code not in (200, 204):
                return False, f"Failed to delete file ({response.status_code}): {response.text[:200]}"
            
            self.log("info", f"File deleted: {file_name}")
            return True, None
            
        except Exception as e:
            return False, f"Error deleting file: {e}"
    
    def list_files(self, page_size: int = 100) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """
        List all uploaded files.
        
        Args:
            page_size: Maximum number of files to return
            
        Returns:
            Tuple of (list_of_files, None) on success or (None, error_message) on failure
        """
        if not self.key_manager or not self.key_manager.has_keys():
            return None, "No API keys configured"
        
        current_key = self.key_manager.get_current_key()
        if not current_key:
            return None, "No API key available"
        
        url = f"{self.base_url}/files?pageSize={page_size}"
        headers = {"x-goog-api-key": current_key}
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                return None, f"Failed to list files ({response.status_code}): {response.text[:200]}"
            
            data = response.json()
            return data.get("files", []), None
            
        except Exception as e:
            return None, f"Error listing files: {e}"
    
    @staticmethod
    def should_use_files_api(filepath: Path) -> bool:
        """Check if a file should be uploaded via Files API (>15 MB)"""
        try:
            return filepath.stat().st_size > MAX_INLINE_SIZE_BYTES
        except Exception:
            return False
            
    # =========================================================================
    # BATCH API METHODS
    # =========================================================================
    
    def create_batch(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        display_name: Optional[str] = None
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """
        Create a batch job (Batch API).
        
        Args:
            messages: List of messages in OpenAI format
            model: Model name
            params: Generation parameters
            display_name: Optional display name for the batch
            
        Returns:
            Tuple of (operation_dict, error_message)
        """
        if not self.key_manager or not self.key_manager.has_keys():
            return None, "No API keys configured"
        
        current_key = self.key_manager.get_current_key()
        if not current_key:
            return None, "No API key available"
        
        # Build the request body using the standard helper
        # Ref: gemini-batch-api.md
        
        url = f"{self.base_url}/models/{model}:batchGenerateContent"
        
        # Build the single GenerateContentRequest
        gen_req_body = self._build_request_body(messages, model, params, thinking_enabled=False)
        
        req_body = {
            "displayName": display_name or f"batch_{int(time.time())}",
            "requests": [
                {
                    "request": gen_req_body
                }
            ]
        }

        try:
            response = requests.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": current_key
                },
                json=req_body,
                timeout=30
            )
            
            if response.status_code != 200:
                return None, f"Failed to create batch ({response.status_code}): {response.text[:200]}"
            
            return response.json(), None
            
        except Exception as e:
            return None, f"Error creating batch: {e}"

    def get_batch(self, batch_name: str) -> Tuple[Optional[Dict], Optional[str]]:
        """Get batch status"""
        if not self.key_manager or not self.key_manager.has_keys():
            return None, "No API keys configured"
        
        current_key = self.key_manager.get_current_key()
        url = f"{self.base_url}/{batch_name}"
        
        try:
            response = requests.get(
                url,
                headers={"x-goog-api-key": current_key},
                timeout=30
            )
            if response.status_code != 200:
                return None, f"Failed to get batch ({response.status_code}): {response.text[:200]}"
            return response.json(), None
        except Exception as e:
            return None, f"Error getting batch: {e}"

    def list_batches(self, page_size: int = 50) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """List batches"""
        if not self.key_manager or not self.key_manager.has_keys():
            return None, "No API keys configured"
        
        current_key = self.key_manager.get_current_key()
        url = f"{self.base_url}/batches?pageSize={page_size}"
        
        try:
            response = requests.get(
                url,
                headers={"x-goog-api-key": current_key},
                timeout=30
            )
            if response.status_code != 200:
                return None, f"Failed to list batches ({response.status_code}): {response.text[:200]}"
            return response.json().get("batches", []), None
        except Exception as e:
            return None, f"Error listing batches: {e}"

    def cancel_batch(self, batch_name: str) -> Tuple[bool, Optional[str]]:
        """Cancel batch"""
        if not self.key_manager or not self.key_manager.has_keys():
            return False, "No API keys configured"
        
        current_key = self.key_manager.get_current_key()
        url = f"{self.base_url}/{batch_name}:cancel"
        
        try:
            response = requests.post(
                url,
                headers={"x-goog-api-key": current_key},
                timeout=30
            )
            if response.status_code != 200:
                return False, f"Failed to cancel batch ({response.status_code}): {response.text[:200]}"
            return True, None
        except Exception as e:
            return False, f"Error cancelling batch: {e}"
    
    # =========================================================================
    # ERROR HANDLING
    # =========================================================================
    
    def get_retry_reason(self, status_code: int, error_text: str = "") -> RetryReason:
        """
        Override to handle Google's specific 400 error for invalid keys.
        """
        if status_code == 400:
            # Check for Google's specific API key invalid reason
            if "API_KEY_INVALID" in error_text or "API key not valid" in error_text:
                return RetryReason.AUTH_ERROR
                
        # Fallback to base logic for 429, 401, 403, 5xx, etc.
        return super().get_retry_reason(status_code, error_text)

    def detect_empty_response(
        self,
        content: str,
        thinking: str,
        tool_calls: List,
        output_tokens: int
    ) -> bool:
        """
        Detect an empty response.
        
        Overridden for Gemini to treat "Thinking only" responses as empty/failed.
        Sometimes the model streams thinking but cuts off before the actual response
        (upstream issue). This ensures we retry in those cases.
        """
        # A valid response must have either actual text content OR tool calls.
        # Thinking content alone is not enough to be considered successful.
        has_actual_content = bool(
            content.strip() or
            tool_calls
        )
        
        return not has_actual_content

    def _extract_error_brief(self, error_text: str, status_code: int = 0) -> str:
        """
        Extract a brief, readable error message from API error response.
        
        Args:
            error_text: Raw error response text (may be JSON or plain text)
            status_code: HTTP status code
            
        Returns:
            Brief error description (max ~100 chars)
        """
        try:
            # Try to parse as JSON and extract error message
            import json
            error_data = json.loads(error_text)
            if "error" in error_data:
                error_obj = error_data["error"]
                if isinstance(error_obj, dict):
                    # Standard Google API error format: {"error": {"message": "...", "status": "..."}}
                    msg = error_obj.get("message", "")
                    status = error_obj.get("status", "")
                    if msg:
                        brief = msg[:80]
                        if status:
                            brief = f"{status}: {brief}"[:100]
                        return brief
                    if status:
                        return f"Status: {status}"
                elif isinstance(error_obj, str):
                    return error_obj[:100]
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
        
        # Fallback: use first line or truncated text
        first_line = error_text.split('\n')[0][:100] if error_text else ""
        if status_code:
            return f"HTTP {status_code}: {first_line[:80]}"
        return first_line or "Unknown error"
    
    def _is_gemini_3(self, model: str) -> bool:
        """Check if model is Gemini 3.x (uses thinkingLevel instead of thinkingBudget)"""
        lower = model.lower()
        return "gemini" in lower and "3" in lower
    
    def _is_gemini_25(self, model: str) -> bool:
        """Check if model is Gemini 2.5 (uses thinkingBudget)"""
        lower = model.lower()
        return "gemini" in lower and "2.5" in lower
    
    def _is_gemma(self, model: str) -> bool:
        """Check if model is Gemma (doesn't support systemInstruction)"""
        lower = model.lower()
        return "gemma" in lower
    
    def _get_url(self, model: str, streaming: bool) -> str:
        """Build the API URL"""
        if streaming:
            return f"{self.base_url}/models/{model}:streamGenerateContent?alt=sse"
        else:
            return f"{self.base_url}/models/{model}:generateContent"
    
    def _convert_messages_to_contents(
        self,
        messages: List[Dict],
        prepend_system_to_user: bool = False
    ) -> tuple[List[Dict], Optional[str]]:
        """
        Convert OpenAI-format messages to Gemini native format.
        
        Args:
            messages: List of messages in OpenAI format
            prepend_system_to_user: If True, prepend system message to first user message
                                   (for Gemma models that don't support systemInstruction)
        
        Returns:
            Tuple of (contents, system_instruction)
            If prepend_system_to_user is True, system_instruction will always be None
        """
        contents = []
        system_instruction = None
        pending_system_text = None
        
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            
            # Handle system message
            if role == "system":
                system_text = self._extract_text_content(content)
                if prepend_system_to_user:
                    # Store for prepending to first user message
                    pending_system_text = system_text
                else:
                    # Use as systemInstruction field
                    system_instruction = system_text
                continue
            
            # Convert role: assistant -> model
            gemini_role = "model" if role == "assistant" else "user"
            
            # Convert content to parts
            parts = self._convert_content_to_parts(content)
            
            # If we have a pending system message and this is a user message,
            # prepend the system text to the user message
            if pending_system_text and gemini_role == "user" and parts:
                # Prepend system instruction to the first text part
                system_parts = [{"text": pending_system_text + "\n\n"}]
                parts = system_parts + parts
                pending_system_text = None  # Only prepend once
            
            if parts:
                contents.append({
                    "role": gemini_role,
                    "parts": parts
                })
        
        return contents, system_instruction
    
    def _extract_text_content(self, content: Any) -> str:
        """Extract text from content (string or array)"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for item in content:
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
            return " ".join(texts)
        return ""
    
    def _convert_content_to_parts(self, content: Any) -> List[Dict]:
        """Convert OpenAI content format to Gemini parts"""
        if isinstance(content, str):
            return [{"text": content}]
        
        if isinstance(content, list):
            all_parts = []
            media_count = 0
            
            for item in content:
                part = None
                is_media = False
                
                if item.get("type") == "text":
                    part = {"text": item.get("text", "")}
                elif item.get("type") == "image_url":
                    image_url = item.get("image_url", {}).get("url", "")
                    # Parse data URL
                    match = re.match(r"data:([^;]+);base64,(.+)", image_url)
                    if match:
                        mime_type, b64_data = match.groups()
                        part = {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": b64_data
                            }
                        }
                        is_media = True
                elif item.get("type") == "inline_data":
                    # Native inline data (audio, etc.)
                    inline = item.get("inline_data", {})
                    part = {
                        "inline_data": {
                            "mime_type": inline.get("mime_type", ""),
                            "data": inline.get("data", "")
                        }
                    }
                    is_media = True
                elif item.get("type") == "file":
                    # Generic file type (PDF, etc.)
                    # Can be nested {"file": {"url": ...}} or flat {"url": ...}
                    file_obj = item.get("file", {})
                    url = file_obj.get("url", "") or item.get("url", "")
                    
                    # Check for data URL
                    match = re.match(r"data:([^;]+);base64,(.+)", url)
                    if match:
                        mime_type, b64_data = match.groups()
                        part = {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": b64_data
                            }
                        }
                        is_media = True
                elif item.get("type") == "file_data":
                    # File uploaded via Files API
                    file_data = item.get("file_data", {})
                    part = {
                        "fileData": {
                            "mimeType": file_data.get("mime_type", ""),
                            "fileUri": file_data.get("file_uri", "")
                        }
                    }
                    is_media = True
                
                if part:
                    all_parts.append(part)
                    if is_media:
                        media_count += 1
            
            # Gemini Native Reordering Logic:
            # If exactly ONE media item, move it to the start (Media First).
            # This optimizes for Context Caching and reduces recency bias for simple queries
            # by placing the single image/file before the text instructions.
            # If multiple media items (e.g. interleaved document), preserve original order.
            if media_count == 1:
                media_parts = [p for p in all_parts if "text" not in p]
                text_parts = [p for p in all_parts if "text" in p]
                return media_parts + text_parts
            
            return all_parts
        
        return [{"text": str(content)}]
    
    def _build_generation_config(
        self,
        params: Dict,
        thinking_enabled: bool,
        model: str
    ) -> Dict:
        """
        Build generationConfig with thinking settings.
        
        Per JSON-request-reference.md:
        - Gemini 2.5: thinkingBudget (integer)
        - Gemini 3.x: thinkingLevel ("low" or "high")
        
        Optional parameters (only included if explicitly set in config):
        - max_tokens: Maps to maxOutputTokens
        """
        config = {
            "temperature": params.get("temperature", 1.0),
            "topP": params.get("top_p", 0.95),
            "topK": params.get("top_k", 0),
        }
        
        # Optional: maxOutputTokens (only include if explicitly set)
        if "max_tokens" in params and params["max_tokens"] is not None:
            config["maxOutputTokens"] = params["max_tokens"]
        
        if thinking_enabled:
            if self._is_gemini_3(model):
                # Gemini 3.x uses thinkingLevel
                level = self.config.get("thinking_level", "high")
                config["thinkingConfig"] = {
                    "thinkingLevel": level,
                    "includeThoughts": True
                }
            else:
                # Gemini 2.5 uses thinkingBudget
                budget = self.config.get("thinking_budget", -1)  # -1 = auto/unlimited
                config["thinkingConfig"] = {
                    "thinkingBudget": budget,
                    "includeThoughts": True
                }
        
        return config
    
    def _build_request_body(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        thinking_enabled: bool
    ) -> Dict:
        """Build the full request body"""
        # Gemma models don't support systemInstruction - prepend to first user message instead
        is_gemma = self._is_gemma(model)
        
        contents, system_instruction = self._convert_messages_to_contents(
            messages,
            prepend_system_to_user=is_gemma
        )
        
        body = {
            "contents": contents,
            "generationConfig": self._build_generation_config(params, thinking_enabled, model),
            "safetySettings": SAFETY_SETTINGS
        }
        
        if system_instruction and not is_gemma:
            # systemInstruction is a top-level field - omit "role" (best practice)
            # Never use "role": "user" here as it conflicts with system instruction purpose
            # Gemma models don't support this field, so we skip it for them
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
        
        return body
    
    def generate_stream(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        callback: StreamCallback,
        thinking_enabled: bool = False,
        retry_count: int = 0
    ) -> ProviderResult:
        """
        Generate a streaming response with full retry logic.
        """
        if not self.key_manager or not self.key_manager.has_keys():
            return ProviderResult(
                success=False,
                error="No API keys configured for Gemini"
            )
        
        current_key = self.key_manager.get_current_key()
        if not current_key:
            return ProviderResult(
                success=False,
                error="No API key available"
            )
        
        key_num = self.key_manager.get_key_number()
        timeout = self.config.get("request_timeout", 120)
        
        url = self._get_url(model, streaming=True)
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": current_key
        }
        body = self._build_request_body(messages, model, params, thinking_enabled)
        
        self.log_request(model, key_num, thinking_enabled, streaming=True, retry=retry_count)
        
        # Accumulators
        accumulated_content = ""
        accumulated_thinking = ""
        accumulated_tool_calls = []
        usage_data = None
        
        try:
            response = requests.post(
                url,
                headers=headers,
                json=body,
                timeout=timeout,
                stream=True
            )
            
            # Handle error responses
            if response.status_code != 200:
                error_text = response.text[:500]
                status_code = response.status_code
                
                reason = self.get_retry_reason(status_code, error_text)
                
                if self.should_retry(reason, retry_count):
                    delay = self.get_retry_delay(reason)
                    # Extract brief error description from response
                    error_brief = self._extract_error_brief(error_text, status_code)
                    self.log_retry(reason, retry_count + 1, delay, error_brief)
                    
                    if reason in (RetryReason.RATE_LIMITED, RetryReason.AUTH_ERROR):
                        self.rotate_key_if_possible(f"({reason.value})")
                    
                    if delay > 0:
                        time.sleep(delay)
                    
                    return self.generate_stream(
                        messages, model, params, callback, thinking_enabled, retry_count + 1
                    )
                
                self.log_error(f"API error: {error_text}", status_code)
                callback(CallbackType.ERROR, error_text)
                return ProviderResult(
                    success=False,
                    error=f"API error ({status_code}): {error_text}",
                    retry_count=retry_count
                )
            
            # Process streaming response
            response.encoding = 'utf-8'
            buffer = ""
            
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                
                if not line.startswith("data: "):
                    continue
                
                try:
                    data = json.loads(line[6:])
                    candidate = data.get("candidates", [{}])[0]
                    content_parts = candidate.get("content", {}).get("parts", [])
                    
                    for part in content_parts:
                        # Handle thinking content (thought: true)
                        if part.get("thought") is True and part.get("text"):
                            thinking_text = part["text"]
                            accumulated_thinking += thinking_text
                            callback(CallbackType.THINKING, thinking_text)
                        
                        # Handle regular text
                        elif "text" in part and not part.get("thought"):
                            text = part["text"]
                            accumulated_content += text
                            callback(CallbackType.TEXT, text)
                        
                        # Handle function calls
                        elif "functionCall" in part:
                            fc = part["functionCall"]
                            tool_call = {
                                "id": fc.get("id", f"call_{len(accumulated_tool_calls)}"),
                                "type": "function",
                                "function": {
                                    "name": fc.get("name", ""),
                                    "arguments": json.dumps(fc.get("args", {}))
                                }
                            }
                            accumulated_tool_calls.append(tool_call)
                            callback(CallbackType.TOOL_CALLS, [tool_call])
                    
                    # Capture usage metadata
                    if "usageMetadata" in data:
                        usage = data["usageMetadata"]
                        usage_data = UsageData(
                            prompt_tokens=usage.get("promptTokenCount", 0),
                            completion_tokens=usage.get("candidatesTokenCount", 0),
                            total_tokens=usage.get("totalTokenCount", 0)
                        )
                        callback(CallbackType.USAGE, usage_data.to_dict())
                
                except json.JSONDecodeError:
                    continue
            
            callback(CallbackType.DONE, None)
            
            # Check for empty response
            output_tokens = usage_data.completion_tokens if usage_data else 0
            
            if self.detect_empty_response(
                accumulated_content,
                accumulated_thinking,
                accumulated_tool_calls,
                output_tokens
            ):
                self.log("warn", "Empty or incomplete response detected (no text/tools)")
                
                if self.should_retry(RetryReason.EMPTY_RESPONSE, retry_count):
                    delay = self.get_retry_delay(RetryReason.EMPTY_RESPONSE)
                    self.log_retry(RetryReason.EMPTY_RESPONSE, retry_count + 1, delay, "0 output tokens, no content")
                    self.rotate_key_if_possible("(empty response)")
                    
                    if delay > 0:
                        time.sleep(delay)
                    
                    return self.generate_stream(
                        messages, model, params, callback, thinking_enabled, retry_count + 1
                    )
                
                return ProviderResult(
                    success=False,
                    error="Empty response after retries exhausted",
                    retry_count=retry_count
                )
            
            # Estimate usage if not provided
            if not usage_data:
                input_tokens = estimate_message_tokens(messages)
                output_tokens = estimate_tokens(accumulated_content + accumulated_thinking)
                usage_data = UsageData(
                    prompt_tokens=input_tokens,
                    completion_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    estimated=True
                )
                callback(CallbackType.USAGE, usage_data.to_dict())
            
            self.log_success(key_num)
            
            return ProviderResult(
                success=True,
                content=accumulated_content,
                thinking_content=accumulated_thinking,
                tool_calls=accumulated_tool_calls,
                usage=usage_data,
                retry_count=retry_count
            )
        
        except requests.exceptions.Timeout:
            self.log_error(f"Request timeout after {timeout}s")
            
            if self.should_retry(RetryReason.NETWORK_ERROR, retry_count):
                delay = self.get_retry_delay(RetryReason.NETWORK_ERROR)
                self.log_retry(RetryReason.NETWORK_ERROR, retry_count + 1, delay, f"timeout after {timeout}s")
                self.rotate_key_if_possible("(timeout)")
                
                if delay > 0:
                    time.sleep(delay)
                
                return self.generate_stream(
                    messages, model, params, callback, thinking_enabled, retry_count + 1
                )
            
            callback(CallbackType.ERROR, f"Request timeout after {timeout}s")
            return ProviderResult(
                success=False,
                error=f"Request timeout after {timeout}s",
                retry_count=retry_count
            )
        
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            self.log_error(f"Network error: {error_msg}")
            
            if self.should_retry(RetryReason.NETWORK_ERROR, retry_count):
                delay = self.get_retry_delay(RetryReason.NETWORK_ERROR)
                self.log_retry(RetryReason.NETWORK_ERROR, retry_count + 1, delay, error_msg[:100])
                self.rotate_key_if_possible("(network error)")
                
                if delay > 0:
                    time.sleep(delay)
                
                return self.generate_stream(
                    messages, model, params, callback, thinking_enabled, retry_count + 1
                )
            
            callback(CallbackType.ERROR, error_msg)
            return ProviderResult(
                success=False,
                error=f"Network error: {error_msg}",
                retry_count=retry_count
            )
        
        except Exception as e:
            error_msg = str(e)
            self.log_error(f"Unexpected error: {error_msg}")
            
            if self.should_retry(RetryReason.SERVER_ERROR, retry_count):
                delay = self.get_retry_delay(RetryReason.SERVER_ERROR)
                self.log_retry(RetryReason.SERVER_ERROR, retry_count + 1, delay, error_msg[:100])
                
                if delay > 0:
                    time.sleep(delay)
                
                return self.generate_stream(
                    messages, model, params, callback, thinking_enabled, retry_count + 1
                )
            
            callback(CallbackType.ERROR, error_msg)
            return ProviderResult(
                success=False,
                error=f"Unexpected error: {error_msg}",
                retry_count=retry_count
            )
    
    def generate(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        thinking_enabled: bool = False,
        retry_count: int = 0
    ) -> ProviderResult:
        """
        Generate a non-streaming response with retry logic.
        """
        if not self.key_manager or not self.key_manager.has_keys():
            return ProviderResult(
                success=False,
                error="No API keys configured for Gemini"
            )
        
        current_key = self.key_manager.get_current_key()
        if not current_key:
            return ProviderResult(
                success=False,
                error="No API key available"
            )
        
        key_num = self.key_manager.get_key_number()
        timeout = self.config.get("request_timeout", 120)
        
        url = self._get_url(model, streaming=False)
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": current_key
        }
        body = self._build_request_body(messages, model, params, thinking_enabled)
        
        self.log_request(model, key_num, thinking_enabled, streaming=False, retry=retry_count)
        
        try:
            response = requests.post(url, headers=headers, json=body, timeout=timeout)
            
            # Handle error responses
            if response.status_code != 200:
                error_text = response.text[:500]
                status_code = response.status_code
                
                reason = self.get_retry_reason(status_code, error_text)
                
                if self.should_retry(reason, retry_count):
                    delay = self.get_retry_delay(reason)
                    error_brief = self._extract_error_brief(error_text, status_code)
                    self.log_retry(reason, retry_count + 1, delay, error_brief)
                    
                    if reason in (RetryReason.RATE_LIMITED, RetryReason.AUTH_ERROR):
                        self.rotate_key_if_possible(f"({reason.value})")
                    
                    if delay > 0:
                        time.sleep(delay)
                    
                    return self.generate(messages, model, params, thinking_enabled, retry_count + 1)
                
                self.log_error(f"API error: {error_text}", status_code)
                return ProviderResult(
                    success=False,
                    error=f"API error ({status_code}): {error_text}",
                    retry_count=retry_count
                )
            
            # Parse response
            data = response.json()
            candidate = data.get("candidates", [{}])[0]
            content_parts = candidate.get("content", {}).get("parts", [])
            
            accumulated_content = ""
            accumulated_thinking = ""
            tool_calls = []
            
            for part in content_parts:
                if part.get("thought") is True and part.get("text"):
                    accumulated_thinking += part["text"]
                elif "text" in part and not part.get("thought"):
                    accumulated_content += part["text"]
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    tool_calls.append({
                        "id": fc.get("id", f"call_{len(tool_calls)}"),
                        "type": "function",
                        "function": {
                            "name": fc.get("name", ""),
                            "arguments": json.dumps(fc.get("args", {}))
                        }
                    })
            
            # Parse usage
            usage_meta = data.get("usageMetadata", {})
            usage_data = UsageData(
                prompt_tokens=usage_meta.get("promptTokenCount", 0),
                completion_tokens=usage_meta.get("candidatesTokenCount", 0),
                total_tokens=usage_meta.get("totalTokenCount", 0)
            )
            
            # Check for empty response
            if self.detect_empty_response(
                accumulated_content,
                accumulated_thinking,
                tool_calls,
                usage_data.completion_tokens
            ):
                self.log("warn", "Empty or incomplete response detected")
                
                if self.should_retry(RetryReason.EMPTY_RESPONSE, retry_count):
                    delay = self.get_retry_delay(RetryReason.EMPTY_RESPONSE)
                    self.log_retry(RetryReason.EMPTY_RESPONSE, retry_count + 1, delay, "0 output tokens, no content")
                    self.rotate_key_if_possible("(empty response)")
                    
                    if delay > 0:
                        time.sleep(delay)
                    
                    return self.generate(messages, model, params, thinking_enabled, retry_count + 1)
                
                return ProviderResult(
                    success=False,
                    error="Empty response after retries exhausted",
                    retry_count=retry_count
                )
            
            self.log_success(key_num)
            
            return ProviderResult(
                success=True,
                content=accumulated_content,
                thinking_content=accumulated_thinking,
                tool_calls=tool_calls,
                usage=usage_data,
                retry_count=retry_count
            )
        
        except requests.exceptions.Timeout:
            self.log_error(f"Request timeout after {timeout}s")
            
            if self.should_retry(RetryReason.NETWORK_ERROR, retry_count):
                delay = self.get_retry_delay(RetryReason.NETWORK_ERROR)
                self.log_retry(RetryReason.NETWORK_ERROR, retry_count + 1, delay, f"timeout after {timeout}s")
                self.rotate_key_if_possible("(timeout)")
                
                if delay > 0:
                    time.sleep(delay)
                
                return self.generate(messages, model, params, thinking_enabled, retry_count + 1)
            
            return ProviderResult(
                success=False,
                error=f"Request timeout after {timeout}s",
                retry_count=retry_count
            )
        
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            self.log_error(f"Network error: {error_msg}")
            
            if self.should_retry(RetryReason.NETWORK_ERROR, retry_count):
                delay = self.get_retry_delay(RetryReason.NETWORK_ERROR)
                self.log_retry(RetryReason.NETWORK_ERROR, retry_count + 1, delay, error_msg[:100])
                self.rotate_key_if_possible("(network error)")
                
                if delay > 0:
                    time.sleep(delay)
                
                return self.generate(messages, model, params, thinking_enabled, retry_count + 1)
            
            return ProviderResult(
                success=False,
                error=f"Network error: {error_msg}",
                retry_count=retry_count
            )
        
        except Exception as e:
            error_msg = str(e)
            self.log_error(f"Unexpected error: {error_msg}")
            
            return ProviderResult(
                success=False,
                error=f"Unexpected error: {error_msg}",
                retry_count=retry_count
            )
    
    def fetch_models(self) -> tuple[List[Dict], Optional[str]]:
        """
        Fetch available models from Gemini API with full metadata.
        
        Returns models with fields:
        - id: Model ID (e.g., "gemini-2.5-flash")
        - name: Display name (e.g., "Gemini 2.5 Flash")
        - context_length: Input token limit (for terminal compatibility)
        - output_token_limit: Max output tokens
        - thinking: Whether model supports thinking mode
        - description: Model description
        - version: Model version
        - supported_methods: List of supported generation methods
        - temperature: Default temperature
        - top_p: Default top_p
        - top_k: Default top_k
        - max_temperature: Maximum allowed temperature
        - _raw: Original API response for future-proofing
        """
        if not self.key_manager or not self.key_manager.has_keys():
            return None, "No API keys configured for Gemini"
        
        current_key = self.key_manager.get_current_key()
        if not current_key:
            return None, "No API key available"
        
        # Request more models per page (default is 50)
        url = f"{self.base_url}/models?pageSize=1000"
        headers = {"x-goog-api-key": current_key}
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                return None, f"Failed to fetch models ({response.status_code}): {response.text[:200]}"
            
            data = response.json()
            
            if "models" in data and isinstance(data["models"], list):
                models = []
                for model in data["models"]:
                    model_name = model.get("name", "")
                    # Extract model ID from "models/gemini-2.0-flash" format
                    model_id = model_name.replace("models/", "") if model_name.startswith("models/") else model_name
                    display_name = model.get("displayName", model_id)
                    
                    # Filter to only include generateContent-capable models
                    supported_methods = model.get("supportedGenerationMethods", [])
                    if "generateContent" in supported_methods:
                        models.append({
                            # Core fields
                            "id": model_id,
                            "name": display_name,
                            # Token limits - use context_length for terminal compatibility
                            "context_length": model.get("inputTokenLimit"),
                            "input_token_limit": model.get("inputTokenLimit"),
                            "output_token_limit": model.get("outputTokenLimit"),
                            # Features
                            "thinking": model.get("thinking", False),
                            # Metadata
                            "description": model.get("description", ""),
                            "version": model.get("version", ""),
                            "supported_methods": supported_methods,
                            # Generation defaults
                            "temperature": model.get("temperature"),
                            "top_p": model.get("topP"),
                            "top_k": model.get("topK"),
                            "max_temperature": model.get("maxTemperature"),
                            # Store raw response for future-proofing
                            "_raw": model
                        })
                
                return models, None
            
            return None, "Unknown models response format"
        
        except requests.exceptions.RequestException as e:
            return None, f"Request failed: {e}"
        except Exception as e:
            return None, f"Error fetching models: {e}"