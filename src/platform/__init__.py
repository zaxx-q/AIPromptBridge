"""
OS platform helpers (detection, single-instance, IPC, clipboard, input, screenshot).

Intentionally free of GUI / audio / provider imports.
"""

from .clipboard import (
    capture_selection_for_textedit,
    capture_selection_hybrid,
    copy_bytes,
    copy_rich_text,
    copy_text,
    get_selected_text_wayland,
    has_primary_selection,
    is_wl_clipboard_available,
    list_types,
    paste_bytes,
    paste_image_png,
    paste_text,
)
from .console_input import RawConsole, get_key, is_console_input_available
from .detect import is_linux, is_wayland, is_windows
from .input import (
    copy_via_clipboard_shortcut,
    is_wlrctl_available,
    paste_via_clipboard_shortcut,
    press_chord,
    type_text,
)
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
from .pointer import get_pointer_position
from .screenshot import (
    capture_full_screen,
    capture_output,
    capture_region_interactive,
    is_grim_slurp_available,
)
from .single_instance import InstanceLock, acquire_single_instance, acquire_single_instance_mutex

__all__ = [
    "KNOWN_TRIGGERS",
    "InstanceLock",
    "RawConsole",
    "TriggerServer",
    "acquire_single_instance",
    "acquire_single_instance_mutex",
    "capture_full_screen",
    "capture_output",
    "capture_region_interactive",
    "capture_selection_for_textedit",
    "capture_selection_hybrid",
    "copy_bytes",
    "copy_rich_text",
    "copy_text",
    "copy_via_clipboard_shortcut",
    "decode_message",
    "encode_reply_error",
    "encode_reply_ok",
    "encode_trigger",
    "get_key",
    "get_pointer_position",
    "get_selected_text_wayland",
    "get_socket_path",
    "has_primary_selection",
    "is_console_input_available",
    "is_grim_slurp_available",
    "is_linux",
    "is_wayland",
    "is_windows",
    "is_wl_clipboard_available",
    "is_wlrctl_available",
    "list_types",
    "parse_reply",
    "paste_bytes",
    "paste_image_png",
    "paste_text",
    "paste_via_clipboard_shortcut",
    "press_chord",
    "send_trigger",
    "type_text",
]
