"""Best-effort desktop notifications for Linux desktop workflows.

Keeps notification subprocesses outside GUI code.  A missing notification
daemon or ``notify-send`` is intentionally silent: notifications supplement
the app UI and must never block a tool action.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

from .detect import is_linux

logger = logging.getLogger(__name__)


def send_desktop_notification(title: str, message: str, *, timeout_ms: int = 5000) -> bool:
    """Send a non-blocking freedesktop notification when ``notify-send`` is available."""
    if not is_linux():
        return False

    notify_send = shutil.which("notify-send")
    if not notify_send:
        return False

    try:
        subprocess.Popen(
            [
                notify_send,
                "--app-name=AIPromptBridge",
                f"--expire-time={max(0, int(timeout_ms))}",
                title,
                message,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError as exc:
        logger.debug("Could not send desktop notification: %s", exc)
        return False
