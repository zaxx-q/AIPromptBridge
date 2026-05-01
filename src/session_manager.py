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
    
    def __init__(self, session_id=None, origin=None):
        # Use provided ID or generate sequential one
        if session_id is None:
            self.session_id = get_next_session_id()
        else:
            self.session_id = session_id
        self.origin = origin or "chat"
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        
        self.messages = []
        self.title = None
        # System instruction for follow-up messages in chat window
        # Not persisted, only used for active sessions
        self.system_instruction = None
        # Per-session model override (None = use global config model)
        self.model_override = None
        # Per-session preset override (None = no preset selected)
        self.preset_override = None
    
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
            include_image: Whether to include image data in messages
            include_system_instruction: Whether to prepend system instruction if available
        """
        messages = []
        
        # Prepend system instruction if available and requested
        if include_system_instruction and self.system_instruction:
            messages.append({"role": "system", "content": self.system_instruction})
        
        for msg in self.messages:
            role = msg["role"]
            content = msg["content"]
            msg_attachments = msg.get("attachments", [])
            
            if role == "user":
                # Per-message attachments only
                has_attachments = bool(msg_attachments) and include_image
                
                if has_attachments:
                    # Use array format with media and text
                    content_parts = []
                    from .attachment_manager import AttachmentManager
                    
                    # Add attachments
                    for attach in msg_attachments:
                        attach_path = attach.get("path", "")
                        if attach_path:
                            # load_image works for any file (returns base64)
                            b64, mime = AttachmentManager.load_image(attach_path)
                            if b64:
                                mime = attach.get("mime_type", mime)
                                
                                if mime.startswith("audio/"):
                                    # Audio uses inline_data
                                    content_parts.append({
                                        "type": "inline_data",
                                        "inline_data": {
                                            "mime_type": mime,
                                            "data": b64
                                        }
                                    })
                                elif mime.startswith("image/"):
                                    # Images use image_url (standard abstraction)
                                    data_url = f"data:{mime};base64,{b64}"
                                    content_parts.append({"type": "image_url", "image_url": {"url": data_url}})
                                else:
                                    # Documents (PDFs, etc.) use inline_data
                                    # Providers convert this to their native format
                                    # (e.g., OpenRouter file type, Gemini inline_data)
                                    content_parts.append({
                                        "type": "inline_data",
                                        "inline_data": {
                                            "mime_type": mime,
                                            "data": b64
                                        },
                                        "filename": attach.get("filename", "")
                                    })
                    
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
        d = {
            "session_id": self.session_id,
            "origin": self.origin,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "title": self.title,
            "messages": self.messages,
        }
        # Only include model_override when set (keep JSON clean)
        if self.model_override is not None:
            d["model_override"] = self.model_override
        if self.preset_override is not None:
            d["preset_override"] = self.preset_override
        return d
    
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
        session.origin = data.get("origin", "chat")
        session.created_at = data.get("created_at", datetime.now().isoformat())
        session.updated_at = data.get("updated_at", session.created_at)
        session.title = data.get("title")
        session.messages = data.get("messages", [])
        session.model_override = data.get("model_override", None)
        session.preset_override = data.get("preset_override", None)
        
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


def add_session(session, max_sessions=200):
    """Add a session and manage max limit"""
    removed_ids = []
    with SESSION_LOCK:
        while len(CHAT_SESSIONS) >= max_sessions:
            oldest_id = next(iter(CHAT_SESSIONS))
            del CHAT_SESSIONS[oldest_id]
            removed_ids.append(oldest_id)
        CHAT_SESSIONS[session.session_id] = session
    
    threading.Thread(target=save_sessions, daemon=True).start()

    # Cleanup attachments for removed sessions
    # (Only runs if items were actually removed)
    if removed_ids:
        def cleanup():
            import time
            from .attachment_manager import delete_session_attachments
            
            # Initial delay to let the main operation finish
            time.sleep(2.0)
            
            for sid in removed_ids:
                try:
                    # Clean up attachments - handle string/int IDs
                    numeric_id = int(sid) if isinstance(sid, str) and sid.isdigit() else sid
                    if isinstance(numeric_id, int):
                        delete_session_attachments(numeric_id)
                        # Yield CPU after each deletion
                        time.sleep(0.1)
                except Exception as e:
                    print(f"[Warning] Failed to cleanup session {sid}: {e}")
        
        # Start cleanup in background
        t = threading.Thread(target=cleanup, daemon=True)
        t.start()


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
                "origin": session.origin,
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
