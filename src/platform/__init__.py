"""
OS platform helpers (detection, single-instance, IPC).

Intentionally free of GUI / audio / provider imports.
"""

from .detect import is_linux, is_wayland, is_windows
from .ipc import (
    KNOWN_TRIGGERS,
    TriggerServer,
    decode_message,
    encode_reply_error,
    encode_reply_ok,
    encode_trigger,
    get_socket_path,
    parse_reply,
    send_trigger,
)
from .single_instance import InstanceLock, acquire_single_instance, acquire_single_instance_mutex

__all__ = [
    "KNOWN_TRIGGERS",
    "InstanceLock",
    "TriggerServer",
    "acquire_single_instance",
    "acquire_single_instance_mutex",
    "decode_message",
    "encode_reply_error",
    "encode_reply_ok",
    "encode_trigger",
    "get_socket_path",
    "is_linux",
    "is_wayland",
    "is_windows",
    "parse_reply",
    "send_trigger",
]
