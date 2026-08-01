"""
Unix-domain-socket IPC for Linux tool triggers.

Protocol (one line UTF-8 per request/response):
  Client → Server:  ``<trigger>\\n``   e.g. ``snip\\n``
  Server → Client:  ``ok\\n``  or  ``error <message>\\n``

Socket path (v1 fixed name):
  $XDG_RUNTIME_DIR/aipromptbridge.sock  or  /tmp/aipromptbridge-<uid>.sock

No GUI / audio / provider imports — safe for early startup and unit tests.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
from collections.abc import Callable
from typing import Optional, Tuple

# Fixed socket basename for v1 (not versioned / not per-user-id).
SOCKET_NAME = "aipromptbridge.sock"

# Triggers accepted by CLI / server. Keep in sync with main.parse_args().
KNOWN_TRIGGERS = (
    "snip",
    "textedit",
    "audio",
    "tts",
    "chat",
    "browser",
    "settings",
    "prompts",
)

# Handler: trigger_name -> (ok: bool, detail: str)
# detail is empty on success; on failure it is the error message body
# (without the ``error `` prefix).
TriggerHandler = Callable[[str], Tuple[bool, str]]


def get_socket_path() -> str:
    """
    Resolve the IPC socket path.

    Prefer $XDG_RUNTIME_DIR (per-user, cleaned on logout). Fall back to /tmp/aipromptbridge-<uid>.sock
    to prevent cross-user socket collision/hijacking in public /tmp.
    """
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if runtime_dir:
        return os.path.join(runtime_dir, SOCKET_NAME)

    try:
        uid = os.getuid()
        return os.path.join("/tmp", f"aipromptbridge-{uid}.sock")
    except AttributeError:
        return os.path.join("/tmp", SOCKET_NAME)


def encode_trigger(name: str) -> bytes:
    """Encode a trigger name as a single-line request payload."""
    return f"{name.strip().lower()}\n".encode("utf-8")


def decode_message(data: bytes) -> str:
    """
    Decode a client request line into a trigger name.

    Accepts bare ``snip`` and the alternate ``trigger snip`` form; normalizes
    to the bare name. Empty / whitespace-only input becomes ``\"\"``.
    """
    line = data.decode("utf-8", errors="replace").strip().lower()
    # Tolerate multi-line payloads by taking the first non-empty line.
    if "\n" in line:
        line = line.split("\n", 1)[0].strip()
    if line.startswith("trigger "):
        line = line[len("trigger ") :].strip()
    return line


def encode_reply_ok() -> bytes:
    """Encode a successful reply."""
    return b"ok\n"


def encode_reply_error(message: str) -> bytes:
    """Encode an error reply. Message should not include the ``error `` prefix."""
    clean = (message or "unknown error").replace("\n", " ").strip()
    return f"error {clean}\n".encode("utf-8")


def parse_reply(data: bytes) -> Tuple[bool, str]:
    """
    Parse a server reply into (ok, message).

    ``ok\\n`` → (True, \"ok\")
    ``error foo\\n`` → (False, \"foo\")
    """
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return False, "empty reply"
    # First line only
    if "\n" in text:
        text = text.split("\n", 1)[0].strip()
    lower = text.lower()
    if lower == "ok":
        return True, "ok"
    if lower.startswith("error"):
        # ``error`` or ``error <msg>``
        detail = text[5:].strip() if len(text) > 5 else "unknown error"
        # Drop a single leading separator space already handled by strip
        return False, detail or "unknown error"
    return False, text


def send_trigger(
    name: str,
    socket_path: Optional[str] = None,
    timeout: float = 5.0,
) -> Tuple[bool, str]:
    """
    Client: connect to the running instance, send a trigger, return (ok, message).

    If no instance is listening, returns a clear non-zero-style failure message.
    Does **not** auto-start the full application.
    """
    path = socket_path or get_socket_path()
    trigger = name.strip().lower()
    if not trigger:
        return False, "missing trigger name"
    if trigger not in KNOWN_TRIGGERS:
        return False, f"unknown trigger: {trigger}"

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except (OSError, AttributeError) as e:
        return False, f"Unix sockets not available: {e}"

    try:
        sock.settimeout(timeout)
        try:
            sock.connect(path)
        except (FileNotFoundError, ConnectionRefusedError):
            return (
                False,
                "No running AIPromptBridge instance found. "
                "Start the app first (e.g. uv run main.py --show-console), "
                "then retry --trigger.",
            )
        except OSError as e:
            return (
                False,
                f"Cannot connect to AIPromptBridge IPC socket ({path}): {e}. Is the app running?",
            )

        sock.sendall(encode_trigger(trigger))
        # Read until newline or peer close
        chunks: list[bytes] = []
        while True:
            try:
                part = sock.recv(4096)
            except socket.timeout:
                return False, "timeout waiting for reply from running instance"
            if not part:
                break
            chunks.append(part)
            if b"\n" in part:
                break
        return parse_reply(b"".join(chunks))
    finally:
        try:
            sock.close()
        except OSError:
            pass


def cli_main(argv: list[str] | None = None) -> int:
    """
    Fast CLI for ``--trigger`` / ``python -m src.platform.ipc <name>``.

    Stdlib-only module path: safe for compositor binds. Exit 0 on ok, 1 on error.
    Quiet on success (niri-friendly); errors go to stderr.
    """
    import sys

    raw = list(sys.argv[1:] if argv is None else argv)
    # Accept bare name, ``--trigger name``, or ``--trigger=name``
    name = ""
    if not raw or raw[0] in ("-h", "--help"):
        print(
            "Usage: python -m src.platform.ipc <trigger>\n"
            f"Triggers: {', '.join(KNOWN_TRIGGERS)}\n"
            "Requires a running AIPromptBridge instance (does not auto-start).",
            file=sys.stderr,
        )
        return 0 if raw and raw[0] in ("-h", "--help") else 1

    if raw[0] == "--trigger":
        if len(raw) < 2:
            print("error: missing trigger name after --trigger", file=sys.stderr)
            return 1
        name = raw[1].strip().lower()
    elif raw[0].startswith("--trigger="):
        name = raw[0].split("=", 1)[1].strip().lower()
    elif raw[0].startswith("-"):
        print(f"error: unknown option: {raw[0]}", file=sys.stderr)
        return 1
    else:
        name = raw[0].strip().lower()

    if not name:
        print("error: missing trigger name", file=sys.stderr)
        return 1

    if sys.platform == "win32":
        print(
            "error: IPC --trigger is only available on Linux (Windows uses tray / global hotkeys).",
            file=sys.stderr,
        )
        return 1

    ok, message = send_trigger(name)
    if ok:
        return 0
    print(f"error: trigger {name}: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(cli_main())


class TriggerServer:
    """
    Background AF_UNIX server that dispatches trigger messages.

    Can take ownership of an already-bound listen socket (from single-instance
    lock) or bind itself to ``socket_path``.
    """

    def __init__(
        self,
        handler: TriggerHandler,
        socket_path: Optional[str] = None,
        listen_sock: Optional[socket.socket] = None,
        unlink_on_stop: bool = True,
    ):
        self._handler = handler
        self._socket_path = socket_path or get_socket_path()
        self._sock = listen_sock
        # Whether to unlink the filesystem path on stop. Default True so both
        # self-bound and transferred single-instance sockets clean up.
        self._unlink_on_stop = unlink_on_stop
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._ready = threading.Event()  # tools initialized gate for callers
        # Until mark_ready(), handlers still run but may return not-ready.

    @property
    def socket_path(self) -> str:
        return self._socket_path

    def mark_ready(self) -> None:
        """Signal that tool dispatch is fully initialized."""
        self._ready.set()

    def is_ready(self) -> bool:
        return self._ready.is_set()

    def start(self) -> None:
        """Bind (if needed) and start the accept loop on a daemon thread."""
        if self._thread and self._thread.is_alive():
            return

        if self._sock is None:
            self._sock = _bind_listen_socket(self._socket_path)

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._serve_loop,
            name="aipb-ipc-server",
            daemon=True,
        )
        self._thread.start()
        logging.debug("IPC trigger server listening on %s", self._socket_path)

    def stop(self) -> None:
        """Stop the accept loop and close the listen socket."""
        self._stop.set()
        # Nudge accept() by connecting to ourselves if possible
        if self._sock is not None:
            try:
                nudge = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                nudge.settimeout(0.2)
                try:
                    nudge.connect(self._socket_path)
                except OSError:
                    pass
                finally:
                    try:
                        nudge.close()
                    except OSError:
                        pass
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

        if self._unlink_on_stop:
            _unlink_socket(self._socket_path)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _serve_loop(self) -> None:
        assert self._sock is not None
        try:
            self._sock.settimeout(1.0)
        except OSError:
            pass

        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                continue

            try:
                self._handle_connection(conn)
            except Exception as e:
                logging.debug("IPC connection error: %s", e)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _handle_connection(self, conn: socket.socket) -> None:
        conn.settimeout(5.0)
        chunks: list[bytes] = []
        while True:
            try:
                part = conn.recv(4096)
            except socket.timeout:
                conn.sendall(encode_reply_error("timeout reading request"))
                return
            if not part:
                break
            chunks.append(part)
            if b"\n" in part:
                break

        raw = b"".join(chunks)
        if not raw:
            conn.sendall(encode_reply_error("empty request"))
            return

        name = decode_message(raw)
        if not name:
            conn.sendall(encode_reply_error("missing trigger name"))
            return
        if name not in KNOWN_TRIGGERS:
            conn.sendall(encode_reply_error(f"unknown trigger: {name}"))
            return

        try:
            ok, detail = self._handler(name)
        except Exception as e:
            logging.exception("IPC trigger handler failed for %s", name)
            conn.sendall(encode_reply_error(f"handler failed: {e}"))
            return

        if ok:
            conn.sendall(encode_reply_ok())
        else:
            conn.sendall(encode_reply_error(detail or "tool unavailable"))


def _unlink_socket(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass


def _bind_listen_socket(path: str) -> socket.socket:
    """
    Bind an AF_UNIX listen socket at path.

    If a stale socket file exists (previous crash), remove it and retry.
    Raises OSError if another live instance owns the path.
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(path)
    except OSError:
        # Stale path? Probe with a short connect.
        if _socket_is_live(path):
            sock.close()
            raise
        _unlink_socket(path)
        try:
            sock.bind(path)
        except OSError:
            sock.close()
            raise

    # Restrict socket file permissions to owner-only (0o600)
    try:
        os.chmod(path, 0o600)
    except OSError as e:
        logging.warning("Could not set 0600 permissions on IPC socket %s: %s", path, e)

    sock.listen(8)
    return sock


def _socket_is_live(path: str) -> bool:
    """Return True if something accepts connections on the Unix socket path."""
    if not os.path.exists(path):
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.5)
        probe.connect(path)
        return True
    except OSError:
        return False
    finally:
        try:
            probe.close()
        except OSError:
            pass
