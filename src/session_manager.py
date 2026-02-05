#!/usr/bin/env python3
"""
Chat session management with persistence
"""

import json
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from .config import SESSIONS_FILE

# Global session storage
CHAT_SESSIONS = OrderedDict()
SESSION_LOCK = threading.Lock()

# Persistent session counter for sequential IDs
SESSION_COUNTER = 0


def get_next_session_id():
    """Get next sequential session ID"""
    global SESSION_COUNTER
    SESSION_COUNTER += 1
    return SESSION_COUNTER


class ChatSession:
    """Represents a chat session with history"""
    
    def __init__(self, session_id=None, endpoint=None, image_base64=None, mime_type=None):
        # Use provided ID or generate sequential one
        if session_id is None:
            self.session_id = get_next_session_id()
        else:
            self.session_id = session_id
        self.endpoint = endpoint or "chat"
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        
        # Legacy in-memory image (for backward compatibility)
        # New code should use attachments instead
        self.image_base64 = image_base64
        self.mime_type = mime_type or "image/png"
        
        # Session-level attachments (paths to external files)
        # Structure: [{"path": "session_attachments/5/0_img.webp", "mime_type": "image/webp"}]
        self.attachments = []
        
        self.messages = []
        self.title = None
        # System instruction for follow-up messages in chat window
        # Not persisted, only used for active sessions
        self.system_instruction = None
    
    def add_message(self, role, content, attachments=None):
        """
        Add a message to the session.
        
        Args:
            role: "user" or "assistant"
            content: Text content
            attachments: Optional list of attachment dicts [{"path": "...", "mime_type": "..."}]
        """
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        if attachments:
            message["attachments"] = attachments
        self.messages.append(message)
        self.updated_at = datetime.now().isoformat()
        if not self.title and role == "user":
            self.title = content[:50] + ("..." if len(content) > 50 else "")
    
    def get_conversation_for_api(self, include_image=True, include_system_instruction=True):
        """
        Convert session messages to API format.
        
        Args:
            include_image: Whether to include image data in the first user message
            include_system_instruction: Whether to prepend system instruction if available
        """
        messages = []
        
        # Prepend system instruction if available and requested
        if include_system_instruction and self.system_instruction:
            messages.append({"role": "system", "content": self.system_instruction})
        
        for i, msg in enumerate(self.messages):
            role = msg["role"]
            content = msg["content"]
            msg_attachments = msg.get("attachments", [])
            
            if role == "user":
                # Check if we need to include images/audio for this user message
                # 1. Session-level image/audio (on first message only)
                #    Includes legacy self.image_base64 and new self.attachments
                #    Important: If the first message uses attachments (new system),
                #    we must ensure we don't duplicate them if they are also set as
                #    session-level attachments (which happens for snip tool/audio tool).
                #    The convention is: session.attachments is the master record for
                #    session-wide context, while msg.attachments is for specific message uploads.
                
                has_session_attachments = (i == 0 and include_image and
                                          (self.image_base64 or self.attachments))
                
                # Check for duplications: if all session attachments are present in msg_attachments,
                # ignore session attachments to avoid double inclusion.
                if i == 0 and self.attachments and msg_attachments:
                    # Check if session attachments are a subset of message attachments (by path)
                    session_paths = set(a.get("path") for a in self.attachments)
                    msg_paths = set(a.get("path") for a in msg_attachments)
                    if session_paths.issubset(msg_paths):
                        has_session_attachments = False  # They are already in msg_attachments
                
                # 2. Per-message attachments
                has_msg_attachments = bool(msg_attachments) and include_image
                
                if has_session_attachments or has_msg_attachments:
                    # Use array format with media and text
                    content_parts = []
                    
                    # Helper to add media part
                    def add_media_part(b64_data, mime_type):
                        if mime_type.startswith("audio/"):
                            # Audio uses inline_data
                            content_parts.append({
                                "type": "inline_data",
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": b64_data
                                }
                            })
                        else:
                            # Images use image_url (standard abstraction)
                            # Note: RequestPipeline converts this if needed for specific providers
                            data_url = f"data:{mime_type};base64,{b64_data}"
                            content_parts.append({"type": "image_url", "image_url": {"url": data_url}})

                    # Add session-level legacy image
                    if i == 0 and include_image and self.image_base64:
                        add_media_part(self.image_base64, self.mime_type)
                    
                    from .attachment_manager import AttachmentManager

                    # Add session-level attachments (new system)
                    if i == 0 and include_image and self.attachments:
                        for attach in self.attachments:
                            attach_path = attach.get("path", "")
                            if attach_path:
                                # load_image works for any file (returns base64)
                                b64, mime = AttachmentManager.load_image(attach_path)
                                if b64:
                                    # Prefer mime from attachment metadata if available
                                    mime = attach.get("mime_type", mime)
                                    add_media_part(b64, mime)

                    # Add per-message attachments
                    if has_msg_attachments:
                        for attach in msg_attachments:
                            attach_path = attach.get("path", "")
                            if attach_path:
                                b64, mime = AttachmentManager.load_image(attach_path)
                                if b64:
                                    mime = attach.get("mime_type", mime)
                                    add_media_part(b64, mime)
                    
                    # Add text content last (context -> question ordering)
                    content_parts.append({"type": "text", "text": content})
                    messages.append({"role": "user", "content": content_parts})
                else:
                    # Simple string format for user messages without media
                    messages.append({"role": "user", "content": content})
            else:
                # Preserve original role (system, assistant, etc.)
                messages.append({"role": role, "content": content})
        
        return messages
    
    def to_dict(self):
        """Convert session to dictionary for serialization"""
        # Save any in-memory image to file first (migration)
        if self.image_base64 and not self.attachments:
            self._migrate_inline_image()
        
        return {
            "session_id": self.session_id,
            "endpoint": self.endpoint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "title": self.title,
            "messages": self.messages,  # Now includes attachments per-message
            "attachments": self.attachments,  # Session-level attachments
            "mime_type": self.mime_type
        }
    
    def _migrate_inline_image(self):
        """Migrate in-memory base64 image to external file storage."""
        if not self.image_base64:
            return
        
        try:
            from .attachment_manager import AttachmentManager
            path = AttachmentManager.save_image(
                session_id=self.session_id,
                image_base64=self.image_base64,
                mime_type=self.mime_type,
                message_index=0
            )
            if path:
                self.attachments = [{"path": path, "mime_type": self.mime_type}]
                # Keep image_base64 in memory for immediate use, but don't serialize it
        except Exception as e:
            import logging
            logging.warning(f"[ChatSession] Failed to migrate image: {e}")
    
    @classmethod
    def from_dict(cls, data):
        """Create session from dictionary"""
        # Get session_id - convert old UUID format to int if needed
        raw_id = data.get("session_id")
        if isinstance(raw_id, int):
            session_id = raw_id
        elif isinstance(raw_id, str):
            # Old UUID format - will get a new ID during migration
            session_id = None
        else:
            session_id = None
        
        session = cls(session_id=session_id)
        session.endpoint = data.get("endpoint", "chat")
        session.created_at = data.get("created_at", datetime.now().isoformat())
        session.updated_at = data.get("updated_at", session.created_at)
        session.title = data.get("title")
        session.messages = data.get("messages", [])
        session.mime_type = data.get("mime_type", "image/png")
        
        # Load attachments
        session.attachments = data.get("attachments", [])
        
        # Backward compatibility logic:
        # If there are attachments, we rely on them and do NOT auto-load into image_base64
        # unless it was a legacy session without attachments where we might need to restore it.
        # But here, we explicitly avoid setting image_base64 if attachments exist,
        # to prevent duplication in get_conversation_for_api.
        if session.attachments:
            # We have attachments, so we don't need image_base64.
            # The get_conversation_for_api method checks `needs_session_image` which is
            # `i == 0 and include_image and self.image_base64`.
            # If we set image_base64 here, it duplicates the first attachment.
            session.image_base64 = None
            
            # Use the mime type from the first attachment if available
            if session.attachments:
                session.mime_type = session.attachments[0].get("mime_type", session.mime_type)
        else:
            session.image_base64 = None
        
        return session


def save_sessions():
    """Save all sessions to file with persistent counter"""
    global SESSION_COUNTER
    with SESSION_LOCK:
        try:
            data = {
                "_counter": SESSION_COUNTER,
                "sessions": {str(sid): session.to_dict() for sid, session in CHAT_SESSIONS.items()}
            }
            with open(SESSIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Warning] Failed to save sessions: {e}")


def load_sessions():
    """Load sessions from file"""
    global CHAT_SESSIONS, SESSION_COUNTER
    try:
        if Path(SESSIONS_FILE).exists():
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle new format with _counter and sessions
            if "_counter" in data:
                SESSION_COUNTER = data.get("_counter", 0)
                sessions_data = data.get("sessions", {})
            else:
                # Old format - data is directly sessions dict
                sessions_data = data
                # Set counter to max session ID found
                SESSION_COUNTER = 0
            
            with SESSION_LOCK:
                for sid, session_data in sessions_data.items():
                    session = ChatSession.from_dict(session_data)
                    # Use session's ID (which may have been assigned during from_dict)
                    CHAT_SESSIONS[session.session_id] = session
                    # Track highest ID for counter
                    if isinstance(session.session_id, int) and session.session_id > SESSION_COUNTER:
                        SESSION_COUNTER = session.session_id
            
            print(f"    ✅ Loaded {len(CHAT_SESSIONS)} saved session(s) (counter: {SESSION_COUNTER})")
            print()
    except Exception as e:
        print(f"[Warning] Failed to load sessions: {e}")


def add_session(session, max_sessions=50):
    """Add a session and manage max limit"""
    with SESSION_LOCK:
        while len(CHAT_SESSIONS) >= max_sessions:
            oldest_id = next(iter(CHAT_SESSIONS))
            del CHAT_SESSIONS[oldest_id]
        CHAT_SESSIONS[session.session_id] = session
    threading.Thread(target=save_sessions, daemon=True).start()


def get_session(session_id):
    """Get a session by ID (handles both string and int IDs)"""
    with SESSION_LOCK:
        # Try direct lookup first
        if session_id in CHAT_SESSIONS:
            return CHAT_SESSIONS.get(session_id)
        
        # Try converting string to int for integer IDs
        if isinstance(session_id, str):
            try:
                int_id = int(session_id)
                if int_id in CHAT_SESSIONS:
                    return CHAT_SESSIONS.get(int_id)
            except ValueError:
                pass
        
        # Try converting int to string for old UUID format
        if isinstance(session_id, int):
            str_id = str(session_id)
            if str_id in CHAT_SESSIONS:
                return CHAT_SESSIONS.get(str_id)
        
        return None


def list_sessions():
    """List all sessions in reverse chronological order"""
    with SESSION_LOCK:
        sessions = []
        for sid, session in reversed(list(CHAT_SESSIONS.items())):
            sessions.append({
                "id": sid,
                "title": session.title or "(No title)",
                "endpoint": session.endpoint,
                "messages": len(session.messages),
                "updated": session.updated_at,
                "created": session.created_at
            })
        return sessions


def delete_session(session_id):
    """Delete a session by ID (handles both string and int IDs)"""
    deleted_id = None
    
    with SESSION_LOCK:
        # Try direct lookup first
        if session_id in CHAT_SESSIONS:
            deleted_id = session_id
            del CHAT_SESSIONS[session_id]
        
        # Try converting string to int
        elif isinstance(session_id, str):
            try:
                int_id = int(session_id)
                if int_id in CHAT_SESSIONS:
                    deleted_id = int_id
                    del CHAT_SESSIONS[int_id]
            except ValueError:
                pass
        
        # Try converting int to string for old UUID format
        elif isinstance(session_id, int):
            str_id = str(session_id)
            if str_id in CHAT_SESSIONS:
                deleted_id = str_id
                del CHAT_SESSIONS[str_id]
    
    # Clean up attachments outside of lock
    if deleted_id is not None:
        try:
            from .attachment_manager import delete_session_attachments
            # Use the numeric ID for attachment cleanup
            numeric_id = int(deleted_id) if isinstance(deleted_id, str) and deleted_id.isdigit() else deleted_id
            if isinstance(numeric_id, int):
                delete_session_attachments(numeric_id)
        except Exception:
            pass  # Attachment cleanup is best-effort
        return True
    
    return False


def clear_all_sessions():
    """Clear all sessions"""
    with SESSION_LOCK:
        CHAT_SESSIONS.clear()
