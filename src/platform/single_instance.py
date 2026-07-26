"""
Single-instance ownership.

Windows: named mutex (same behavior as the former main.acquire_single_instance_mutex).
Linux:   Unix-domain socket bind (socket also used by IPC trigger server).

No GUI / audio / provider imports.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
from typing import Any, Optional

from .detect import is_linux, is_windows
from .ipc import _bind_listen_socket, _unlink_socket, get_socket_path


class InstanceLock:
    """
    Holds single-instance ownership for the process lifetime.

    Call ``release()`` on shutdown (also safe if never acquired).
    """

    def __init__(self) -> None:
        self._mutex_handle: Any = None
        self._listen_sock: Optional[socket.socket] = None
        self._socket_path: Optional[str] = None
        self._acquired = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    @property
    def listen_socket(self) -> Optional[socket.socket]:
        """Linux: bound AF_UNIX listen socket for the IPC server. Windows: None."""
        return self._listen_sock

    @property
    def socket_path(self) -> Optional[str]:
        return self._socket_path

    def release(self) -> None:
        """Release ownership and free OS resources."""
        if self._listen_sock is not None:
            try:
                self._listen_sock.close()
            except OSError:
                pass
            self._listen_sock = None
            if self._socket_path:
                _unlink_socket(self._socket_path)
            self._socket_path = None

        if self._mutex_handle is not None and is_windows():
            try:
                import ctypes

                ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
            except Exception:
                pass
            self._mutex_handle = None

        self._acquired = False


def acquire_single_instance() -> Optional[InstanceLock]:
    """
    Try to become the sole running instance.

    Returns:
        InstanceLock on success (caller must keep it alive / release on exit).
        None if another instance already owns the lock.
    """
    if is_windows():
        return _acquire_windows_mutex()
    if is_linux():
        return _acquire_linux_socket()

    # Other platforms (macOS, etc.): no enforcement yet — allow start.
    lock = InstanceLock()
    lock._acquired = True
    return lock


def _acquire_windows_mutex() -> Optional[InstanceLock]:
    """
    Acquire named mutex ``AIPromptBridge_SingleInstance``.

    Preserves the previous main.py behavior:
      - CreateMutexW(None, False, name)
      - GetLastError() == 183 (ERROR_ALREADY_EXISTS) → another instance
      - Keep handle alive for process lifetime
    """
    import ctypes

    kernel32 = ctypes.windll.kernel32
    mutex_name = "AIPromptBridge_SingleInstance"

    # CreateMutexW(security_attributes, initial_owner, name)
    mutex = kernel32.CreateMutexW(None, False, mutex_name)

    # ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == 183:
        if mutex:
            kernel32.CloseHandle(mutex)
        return None

    lock = InstanceLock()
    lock._mutex_handle = mutex
    lock._acquired = True
    return lock


def _acquire_linux_socket() -> Optional[InstanceLock]:
    """
    Bind the IPC Unix socket as ownership proof.

    If the path is already live (another instance), return None.
    If the path is stale, replace it.
    """
    path = get_socket_path()
    # Ensure parent directory exists (XDG_RUNTIME_DIR should; /tmp always does).
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, mode=0o700, exist_ok=True)
        except OSError as e:
            logging.warning("Could not create IPC runtime dir %s: %s", parent, e)

    try:
        listen_sock = _bind_listen_socket(path)
    except OSError as e:
        logging.debug("Single-instance socket bind failed (%s): %s", path, e)
        return None

    lock = InstanceLock()
    lock._listen_sock = listen_sock
    lock._socket_path = path
    lock._acquired = True
    return lock


# ---------------------------------------------------------------------------
# Backward-compatible wrapper matching the old main.py API
# ---------------------------------------------------------------------------


def acquire_single_instance_mutex():
    """
    Legacy API used by older call sites.

    Windows: returns mutex handle (truthy) or None if already running.
    Non-Windows (legacy): returned the string ``\"NotWindows\"`` without enforcing
    single-instance. Prefer :func:`acquire_single_instance` for new code.
    """
    if sys.platform != "win32":
        return "NotWindows"

    lock = _acquire_windows_mutex()
    if lock is None:
        return None
    # Keep the lock object alive by stashing on the function (handle is inside).
    acquire_single_instance_mutex._lock = lock  # type: ignore[attr-defined]
    return lock._mutex_handle
