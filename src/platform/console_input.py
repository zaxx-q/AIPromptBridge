"""
Cross-platform non-blocking single-key console input.

Windows: ``msvcrt.kbhit`` / ``msvcrt.getch``
Unix/Linux: ``termios`` cbreak + ``select`` + ``os.read`` on the TTY fd

Holds non-canonical (cbreak) mode for the duration of a ``RawConsole``
context so keys register without requiring Enter. Use ``cooked()`` (or
``line_input()``) around blocking ``input()`` prompts so line editing works.

Nesting model (Unix):
- ``raw_depth`` counts active ``RawConsole`` / enable scopes
- ``suspend_depth`` counts active ``cooked()`` scopes
- TTY is cbreak iff ``raw_depth > suspend_depth``
  (so a batch-tool key listener can re-enter raw under an outer cooked tools menu)

No GUI imports. Safe for the terminal session manager daemon thread and
batch-tool pause/stop listeners.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import os
import sys
import threading
import time
from collections.abc import Iterator
from typing import Optional

from .detect import is_windows

logger = logging.getLogger(__name__)

# ── Unix raw-mode state (process-wide, reentrant) ─────────────────────────────
_lock = threading.RLock()
_raw_depth = 0
_suspend_depth = 0
_saved_attrs: Optional[list] = None
_fd: Optional[int] = None
_atexit_registered = False

# Windows msvcrt (imported lazily)
_msvcrt = None
_msvcrt_checked = False


def _load_msvcrt():
    global _msvcrt, _msvcrt_checked
    if _msvcrt_checked:
        return _msvcrt
    _msvcrt_checked = True
    if not is_windows():
        return None
    try:
        import msvcrt as _m

        _msvcrt = _m
    except ImportError:
        _msvcrt = None
    return _msvcrt


def _stdin_fd() -> Optional[int]:
    """Return stdin fileno when it is a real TTY; else None."""
    try:
        if not sys.stdin.isatty():
            return None
        return sys.stdin.fileno()
    except (OSError, ValueError, AttributeError):
        return None


def is_console_input_available() -> bool:
    """
    True when single-key non-blocking reads can work.

    Windows: msvcrt present. Unix: stdin is a TTY.
    """
    if is_windows():
        return _load_msvcrt() is not None
    return _stdin_fd() is not None


def _unix_tcgetattr(fd: int):
    import termios

    return termios.tcgetattr(fd)


def _unix_tcsetattr(fd: int, attrs) -> None:
    import termios

    termios.tcsetattr(fd, termios.TCSADRAIN, attrs)


def _unix_setcbreak(fd: int) -> None:
    import tty

    tty.setcbreak(fd)


def _is_effectively_raw() -> bool:
    """Cbreak should be active when more raw holders than cooked suspends."""
    return _raw_depth > _suspend_depth


def _sync_tty_mode() -> None:
    """Apply cbreak or restore cooked attrs to match current depths."""
    if _fd is None or _saved_attrs is None:
        return
    try:
        if _is_effectively_raw():
            _unix_setcbreak(_fd)
        else:
            _unix_tcsetattr(_fd, _saved_attrs)
    except Exception as exc:
        logger.debug("console_input: sync mode failed: %s", exc)


def _ensure_atexit() -> None:
    global _atexit_registered
    if _atexit_registered:
        return
    _atexit_registered = True
    atexit.register(_force_restore)


def _force_restore() -> None:
    """Best-effort restore of terminal attrs on interpreter exit."""
    global _raw_depth, _suspend_depth, _saved_attrs, _fd
    with _lock:
        if _saved_attrs is not None and _fd is not None:
            with contextlib.suppress(Exception):
                _unix_tcsetattr(_fd, _saved_attrs)
        _raw_depth = 0
        _suspend_depth = 0
        _saved_attrs = None
        _fd = None


def _enable_raw_unix() -> bool:
    """Enter one level of raw interest (reentrant). Returns False if unavailable."""
    global _raw_depth, _saved_attrs, _fd
    with _lock:
        fd = _stdin_fd()
        if fd is None:
            return False
        try:
            if _raw_depth == 0:
                _saved_attrs = _unix_tcgetattr(fd)
                _fd = fd
                _ensure_atexit()
            _raw_depth += 1
            _sync_tty_mode()
            return True
        except Exception as exc:
            logger.debug("console_input: enable raw failed: %s", exc)
            if _raw_depth == 0:
                _saved_attrs = None
                _fd = None
            return False


def _disable_raw_unix() -> None:
    """Leave one level of raw interest."""
    global _raw_depth, _saved_attrs, _fd
    with _lock:
        if _raw_depth <= 0:
            return
        _raw_depth -= 1
        if _raw_depth == 0:
            if _saved_attrs is not None and _fd is not None:
                with contextlib.suppress(Exception):
                    _unix_tcsetattr(_fd, _saved_attrs)
            _saved_attrs = None
            _fd = None
        else:
            _sync_tty_mode()


@contextlib.contextmanager
def _cooked_unix() -> Iterator[None]:
    """Temporarily prefer canonical mode while raw interest is held."""
    global _suspend_depth
    with _lock:
        _suspend_depth += 1
        _sync_tty_mode()
    try:
        yield
    finally:
        with _lock:
            _suspend_depth = max(0, _suspend_depth - 1)
            _sync_tty_mode()


def _read_key_windows(timeout: float) -> Optional[str]:
    msvcrt = _load_msvcrt()
    if msvcrt is None:
        if timeout > 0:
            time.sleep(timeout)
        return None

    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                # Extended / function keys: discard second byte
                if ch in (b"\x00", b"\xe0"):
                    if msvcrt.kbhit():
                        msvcrt.getch()
                    return None
                return ch.decode("utf-8", errors="ignore").lower()
        except Exception:
            return None

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(0.05, remaining))


def _drain_escape_sequence(fd: int) -> None:
    """Consume rest of an ESC/CSI sequence with a short timeout."""
    import select

    deadline = time.monotonic() + 0.05
    while time.monotonic() < deadline:
        try:
            ready, _, _ = select.select([fd], [], [], 0.01)
        except (OSError, ValueError):
            break
        if not ready:
            break
        try:
            chunk = os.read(fd, 1)
        except OSError:
            break
        if not chunk:
            break
        # CSI final bytes are typically @-~ ; keep reading until one lands
        if 0x40 <= chunk[0] <= 0x7E and chunk not in (b"[", b"O"):
            break


def _read_key_unix(timeout: float, *, hold_raw: bool) -> Optional[str]:
    """
    Read one byte from the TTY.

    If *hold_raw* is False, briefly enter cbreak for the poll (less ideal;
    prefer ``RawConsole`` for continuous command loops).
    """
    import select

    fd = _stdin_fd()
    if fd is None:
        if timeout > 0:
            time.sleep(timeout)
        return None

    entered = False
    if not hold_raw:
        entered = _enable_raw_unix()
        if not entered:
            if timeout > 0:
                time.sleep(timeout)
            return None

    try:
        with _lock:
            # Outer cooked() without a nested RawConsole — do not steal
            # keystrokes from input()/line editing.
            if hold_raw and not _is_effectively_raw():
                effectively_raw = False
            else:
                effectively_raw = _is_effectively_raw() if hold_raw else True

        if not effectively_raw:
            if timeout > 0:
                time.sleep(timeout)
            return None

        try:
            ready, _, _ = select.select([fd], [], [], max(0.0, timeout))
        except (OSError, ValueError):
            return None
        if not ready:
            return None

        try:
            data = os.read(fd, 1)
        except OSError:
            return None
        if not data:
            return None

        # Drain common CSI escape sequences (arrows, etc.) so they do not
        # leak as separate phantom keypresses into the command loop.
        if data == b"\x1b":
            _drain_escape_sequence(fd)
            return None

        return data.decode("utf-8", errors="ignore").lower()
    finally:
        if entered:
            _disable_raw_unix()


def get_key(timeout: float = 0.1) -> Optional[str]:
    """
    Non-blocking single-key read.

    Returns a lowercase 1-char string, or ``None`` if no key within *timeout*
    (or an extended/function key was pressed).

    When a ``RawConsole`` is active and not fully suspended by ``cooked()``,
    uses held cbreak mode. Otherwise briefly enables cbreak on Unix for the
    duration of the poll.
    """
    if is_windows():
        return _read_key_windows(timeout)

    with _lock:
        hold_raw = _raw_depth > 0
    return _read_key_unix(timeout, hold_raw=hold_raw)


class RawConsole:
    """
    Context manager that keeps the TTY in cbreak mode for efficient key polls.

    On Windows this is a no-op for terminal modes (msvcrt needs none).

    Example::

        with RawConsole() as keys:
            while True:
                ch = keys.get_key(0.1)
                if ch == "q":
                    break
                if ch == "m":
                    name = keys.line_input("Model: ")
    """

    def __enter__(self) -> RawConsole:
        if not is_windows():
            _enable_raw_unix()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not is_windows():
            _disable_raw_unix()

    def get_key(self, timeout: float = 0.1) -> Optional[str]:
        """Read one key; see module-level :func:`get_key`."""
        return get_key(timeout)

    @contextlib.contextmanager
    def cooked(self) -> Iterator[None]:
        """Temporarily restore canonical/cooked mode for ``input()`` prompts."""
        if is_windows():
            yield
            return
        with _cooked_unix():
            yield

    def line_input(self, prompt: str = "") -> str:
        """
        Read a full line with echo and editing (cooked mode).

        Equivalent to ``input(prompt)`` but safe while this context holds raw mode.
        """
        with self.cooked():
            return input(prompt)
