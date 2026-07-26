"""Unit tests for Wayland screenshot service (mocked subprocess — no compositor)."""

from __future__ import annotations

import base64
import io
import subprocess
from unittest.mock import patch

import pytest
from PIL import Image

from src.platform import screenshot as screenshot_mod
from src.platform.screenshot import (
    capture_full_screen,
    capture_output,
    capture_region_interactive,
    is_grim_slurp_available,
)


# Minimal valid 1x1 PNG (red pixel) for grim stdout mocks
def _make_png_bytes(width: int = 2, height: int = 3) -> bytes:
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


PNG_BYTES = _make_png_bytes()


@pytest.fixture(autouse=True)
def _reset_screenshot_cache():
    """Reset process-lifetime binary cache between tests."""
    screenshot_mod._grim_path = None
    screenshot_mod._slurp_path = None
    screenshot_mod._availability_checked = False
    screenshot_mod._missing_warned = False
    yield
    screenshot_mod._grim_path = None
    screenshot_mod._slurp_path = None
    screenshot_mod._availability_checked = False
    screenshot_mod._missing_warned = False


def _completed(
    returncode: int = 0,
    stdout: bytes | str = b"",
    stderr: bytes | str = b"",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_is_grim_slurp_available_false_when_missing():
    with (
        patch.object(screenshot_mod, "is_linux", return_value=True),
        patch.object(screenshot_mod.shutil, "which", return_value=None),
    ):
        assert is_grim_slurp_available() is False


def test_is_grim_slurp_available_true_when_both_present():
    def which(name: str):
        return {"grim": "/usr/bin/grim", "slurp": "/usr/bin/slurp"}.get(name)

    with (
        patch.object(screenshot_mod, "is_linux", return_value=True),
        patch.object(screenshot_mod.shutil, "which", side_effect=which),
    ):
        assert is_grim_slurp_available() is True


def test_is_grim_slurp_available_false_when_only_grim():
    def which(name: str):
        return {"grim": "/usr/bin/grim"}.get(name)

    with (
        patch.object(screenshot_mod, "is_linux", return_value=True),
        patch.object(screenshot_mod.shutil, "which", side_effect=which),
    ):
        assert is_grim_slurp_available() is False


def test_is_grim_slurp_available_false_on_non_linux():
    with patch.object(screenshot_mod, "is_linux", return_value=False):
        assert is_grim_slurp_available() is False
        assert capture_region_interactive() is None
        assert capture_full_screen() is None


def test_missing_binaries_safe_failure():
    with (
        patch.object(screenshot_mod, "is_linux", return_value=True),
        patch.object(screenshot_mod.shutil, "which", return_value=None),
    ):
        assert capture_region_interactive() is None
        assert capture_full_screen() is None
        assert capture_output("DP-1") is None


def test_capture_region_interactive_success():
    geom = "10,20 100x50"
    calls: list[list[str]] = []

    def which(name: str):
        return {"grim": "/usr/bin/grim", "slurp": "/usr/bin/slurp"}.get(name)

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        # text=True for slurp
        if "slurp" in cmd[0]:
            assert kwargs.get("text") is True
            assert kwargs.get("timeout") == screenshot_mod._SLURP_TIMEOUT
            assert kwargs.get("shell") in (None, False)
            return _completed(stdout=geom + "\n")
        # grim returns binary PNG
        assert kwargs.get("timeout") == screenshot_mod._GRIM_TIMEOUT
        assert kwargs.get("shell") in (None, False)
        return _completed(stdout=PNG_BYTES)

    with (
        patch.object(screenshot_mod, "is_linux", return_value=True),
        patch.object(screenshot_mod.shutil, "which", side_effect=which),
        patch.object(screenshot_mod.subprocess, "run", side_effect=run),
    ):
        result = capture_region_interactive()
        assert result == PNG_BYTES

    assert calls[0] == ["/usr/bin/slurp"]
    assert calls[1] == ["/usr/bin/grim", "-g", geom, "-"]


def test_capture_region_slurp_cancel_nonzero():
    def which(name: str):
        return {"grim": "/usr/bin/grim", "slurp": "/usr/bin/slurp"}.get(name)

    def run(cmd, **kwargs):
        if "slurp" in cmd[0]:
            return _completed(returncode=1, stdout="", stderr="")
        raise AssertionError("grim must not run after slurp cancel")

    with (
        patch.object(screenshot_mod, "is_linux", return_value=True),
        patch.object(screenshot_mod.shutil, "which", side_effect=which),
        patch.object(screenshot_mod.subprocess, "run", side_effect=run),
    ):
        assert capture_region_interactive() is None


def test_capture_region_slurp_empty_geometry():
    def which(name: str):
        return {"grim": "/usr/bin/grim", "slurp": "/usr/bin/slurp"}.get(name)

    def run(cmd, **kwargs):
        if "slurp" in cmd[0]:
            return _completed(returncode=0, stdout="   \n")
        raise AssertionError("grim must not run on empty geometry")

    with (
        patch.object(screenshot_mod, "is_linux", return_value=True),
        patch.object(screenshot_mod.shutil, "which", side_effect=which),
        patch.object(screenshot_mod.subprocess, "run", side_effect=run),
    ):
        assert capture_region_interactive() is None


def test_capture_region_grim_failure():
    def which(name: str):
        return {"grim": "/usr/bin/grim", "slurp": "/usr/bin/slurp"}.get(name)

    def run(cmd, **kwargs):
        if "slurp" in cmd[0]:
            return _completed(stdout="0,0 10x10")
        return _completed(returncode=1, stdout=b"", stderr=b"nope")

    with (
        patch.object(screenshot_mod, "is_linux", return_value=True),
        patch.object(screenshot_mod.shutil, "which", side_effect=which),
        patch.object(screenshot_mod.subprocess, "run", side_effect=run),
    ):
        assert capture_region_interactive() is None


def test_capture_region_grim_rejects_non_png():
    def which(name: str):
        return {"grim": "/usr/bin/grim", "slurp": "/usr/bin/slurp"}.get(name)

    def run(cmd, **kwargs):
        if "slurp" in cmd[0]:
            return _completed(stdout="0,0 10x10")
        return _completed(stdout=b"not-a-png")

    with (
        patch.object(screenshot_mod, "is_linux", return_value=True),
        patch.object(screenshot_mod.shutil, "which", side_effect=which),
        patch.object(screenshot_mod.subprocess, "run", side_effect=run),
    ):
        assert capture_region_interactive() is None


def test_capture_full_screen_argv():
    def which(name: str):
        return {"grim": "/usr/bin/grim", "slurp": "/usr/bin/slurp"}.get(name)

    with (
        patch.object(screenshot_mod, "is_linux", return_value=True),
        patch.object(screenshot_mod.shutil, "which", side_effect=which),
        patch.object(
            screenshot_mod.subprocess,
            "run",
            return_value=_completed(stdout=PNG_BYTES),
        ) as run,
    ):
        result = capture_full_screen()
        assert result == PNG_BYTES
        args = run.call_args[0][0]
        assert args == ["/usr/bin/grim", "-"]
        assert run.call_args[1].get("shell") in (None, False)


def test_capture_output_argv():
    def which(name: str):
        return {"grim": "/usr/bin/grim", "slurp": "/usr/bin/slurp"}.get(name)

    with (
        patch.object(screenshot_mod, "is_linux", return_value=True),
        patch.object(screenshot_mod.shutil, "which", side_effect=which),
        patch.object(
            screenshot_mod.subprocess,
            "run",
            return_value=_completed(stdout=PNG_BYTES),
        ) as run,
    ):
        result = capture_output("eDP-1")
        assert result == PNG_BYTES
        args = run.call_args[0][0]
        assert args == ["/usr/bin/grim", "-o", "eDP-1", "-"]


def test_capture_output_empty_name():
    def which(name: str):
        return {"grim": "/usr/bin/grim", "slurp": "/usr/bin/slurp"}.get(name)

    with (
        patch.object(screenshot_mod, "is_linux", return_value=True),
        patch.object(screenshot_mod.shutil, "which", side_effect=which),
        patch.object(screenshot_mod.subprocess, "run") as run,
    ):
        assert capture_output("") is None
        assert capture_output("   ") is None
        run.assert_not_called()


def test_png_bytes_to_capture_result():
    """Conversion helper lives in GUI layer (Option A)."""
    from src.gui.screen_snip import CaptureResult, png_bytes_to_capture_result

    result = png_bytes_to_capture_result(PNG_BYTES)
    assert isinstance(result, CaptureResult)
    assert result.mime_type == "image/png"
    assert result.width == 2
    assert result.height == 3
    assert result.pil_image is not None
    assert result.pil_image.size == (2, 3)
    assert base64.b64decode(result.image_base64) == PNG_BYTES


def test_png_bytes_to_capture_result_empty():
    from src.gui.screen_snip import png_bytes_to_capture_result

    assert png_bytes_to_capture_result(b"") is None
    assert png_bytes_to_capture_result(b"not-png") is None


def test_never_uses_shell_true():
    """Guardrail: no shell=True on any subprocess call."""
    def which(name: str):
        return {"grim": "/usr/bin/grim", "slurp": "/usr/bin/slurp"}.get(name)

    seen_shell: list[bool] = []

    def run(cmd, **kwargs):
        seen_shell.append(bool(kwargs.get("shell")))
        if "slurp" in cmd[0]:
            return _completed(stdout="1,1 2x2")
        return _completed(stdout=PNG_BYTES)

    with (
        patch.object(screenshot_mod, "is_linux", return_value=True),
        patch.object(screenshot_mod.shutil, "which", side_effect=which),
        patch.object(screenshot_mod.subprocess, "run", side_effect=run),
    ):
        capture_region_interactive()
        capture_full_screen()
        capture_output("HDMI-A-1")

    assert seen_shell
    assert all(s is False for s in seen_shell)
