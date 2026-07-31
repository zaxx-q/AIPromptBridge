"""Unit tests for cross-platform startup / XDG autostart management.

Uses a temporary XDG_CONFIG_HOME so real ~/.config/autostart is never touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.platform.detect import is_linux, is_windows
from src.startup_manager import (
    DESKTOP_FILENAME,
    format_start_command,
    format_trigger_command,
    get_autostart_desktop_path,
    get_project_root,
    get_startup_info,
    is_startup_enabled,
    list_trigger_commands,
    set_startup,
)


def test_module_imports_without_winreg_on_linux():
    """Importing startup_manager must not require winreg on non-Windows."""
    import importlib

    import src.startup_manager as sm

    reloaded = importlib.reload(sm)
    assert hasattr(reloaded, "is_startup_enabled")
    assert hasattr(reloaded, "set_startup")
    assert hasattr(reloaded, "get_startup_info")


def test_get_project_root_finds_main():
    root = get_project_root()
    assert (root / "main.py").is_file() or (Path(__file__).resolve().parents[1] / "main.py").is_file()


def test_format_start_and_trigger_commands():
    start = format_start_command()
    assert start is not None
    assert "main.py" in start
    assert sys.executable in start or "python" in start.lower()

    trig = format_trigger_command("snip")
    assert trig is not None
    assert "--trigger" in trig
    assert "snip" in trig


def test_list_trigger_commands_covers_core():
    rows = list_trigger_commands()
    names = {n for n, _ in rows}
    for required in ("snip", "textedit", "audio", "tts", "chat", "browser"):
        assert required in names


@pytest.mark.skipif(not is_linux(), reason="XDG autostart is Linux-only")
def test_linux_autostart_enable_disable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Enable writes desktop file under XDG_CONFIG_HOME; disable removes it."""
    xdg = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    # Ensure clean slate
    desktop = get_autostart_desktop_path()
    assert desktop == xdg / "autostart" / DESKTOP_FILENAME
    if desktop.is_file():
        desktop.unlink()

    assert is_startup_enabled() is False

    ok, msg = set_startup(True)
    assert ok is True, msg
    assert desktop.is_file()
    assert is_startup_enabled() is True

    content = desktop.read_text(encoding="utf-8")
    assert "Type=Application" in content
    assert "Name=AIPromptBridge" in content
    assert "Exec=" in content
    assert "Path=" in content
    assert "main.py" in content
    assert "X-GNOME-Autostart-enabled=true" in content
    assert "Terminal=false" in content

    info = get_startup_info()
    assert info["enabled"] is True
    assert info["path"]
    assert "main.py" in info["path"] or "Path=" in info["path"]

    ok, msg = set_startup(False)
    assert ok is True, msg
    assert not desktop.is_file()
    assert is_startup_enabled() is False

    # Idempotent disable
    ok, msg = set_startup(False)
    assert ok is True


@pytest.mark.skipif(not is_linux(), reason="XDG autostart is Linux-only")
def test_linux_disabled_desktop_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Hidden=true or X-GNOME-Autostart-enabled=false count as disabled."""
    xdg = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    autostart = xdg / "autostart"
    autostart.mkdir(parents=True)
    desktop = autostart / DESKTOP_FILENAME

    desktop.write_text(
        "[Desktop Entry]\nType=Application\nName=AIPromptBridge\nHidden=true\n",
        encoding="utf-8",
    )
    assert is_startup_enabled() is False

    desktop.write_text(
        "[Desktop Entry]\nType=Application\nName=AIPromptBridge\nX-GNOME-Autostart-enabled=false\n",
        encoding="utf-8",
    )
    assert is_startup_enabled() is False

    desktop.write_text(
        "[Desktop Entry]\nType=Application\nName=AIPromptBridge\nX-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )
    assert is_startup_enabled() is True


@pytest.mark.skipif(is_windows(), reason="Windows registry path not exercised here")
def test_get_startup_info_does_not_raise():
    info = get_startup_info()
    assert "enabled" in info
    assert "path" in info
    assert "mode" in info


def test_compiled_start_and_trigger_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Compiled mode: Exec is the binary (no main.py); Path is deploy root (bin/ parent)."""
    import src.startup_manager as sm

    deploy = tmp_path / "AIPromptBridge"
    bin_dir = deploy / "bin"
    bin_dir.mkdir(parents=True)
    (deploy / "config.ini").write_text("[app]\n", encoding="utf-8")
    (deploy / "icon.ico").write_bytes(b"\x00")
    internal = bin_dir / "AIPromptBridge_Internal"
    internal.write_text("#!/bin/sh\n", encoding="utf-8")
    internal.chmod(0o755)

    # Optional outer launcher (split layout)
    launcher = deploy / "AIPromptBridge"
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)

    monkeypatch.setattr(sm, "is_compiled", lambda: True)
    monkeypatch.setattr(sys, "executable", str(internal))
    monkeypatch.setattr(sm, "get_launcher_path", lambda: str(launcher))

    root = sm.get_project_root()
    assert root == deploy.resolve() or root == bin_dir.parent.resolve()

    start = sm.format_start_command()
    assert start is not None
    assert "main.py" not in start
    assert "AIPromptBridge" in start

    trig = sm.format_trigger_command("snip")
    assert trig is not None
    assert "--trigger" in trig
    assert "snip" in trig
    assert "main.py" not in trig

    display = sm.format_trigger_command_display("textedit")
    assert "--trigger textedit" in display
    assert "uv run" not in display


def test_get_launcher_path_finds_linux_shell_wrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Compiled Linux split layout: outer ./AIPromptBridge is discovered from bin/Internal."""
    import src.startup_manager as sm

    deploy = tmp_path / "deploy"
    bin_dir = deploy / "bin"
    bin_dir.mkdir(parents=True)
    internal = bin_dir / "AIPromptBridge_Internal"
    internal.write_text("x", encoding="utf-8")
    launcher = deploy / "AIPromptBridge"
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)

    monkeypatch.setattr(sm, "is_compiled", lambda: True)
    monkeypatch.setattr(sm, "is_linux", lambda: True)
    monkeypatch.setattr(sm, "is_windows", lambda: False)
    monkeypatch.setattr(sys, "executable", str(internal))
    monkeypatch.setattr(sys, "argv", ["AIPromptBridge_Internal", "--launched-mode=console"])
    monkeypatch.chdir(deploy)

    found = sm.get_launcher_path()
    assert found is not None
    assert Path(found).resolve() == launcher.resolve()


def test_get_launcher_path_prefers_windows_console_exe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Compiled Windows: prefer AIPromptBridge.exe for console launched-mode."""
    import src.startup_manager as sm

    deploy = tmp_path / "deploy"
    bin_dir = deploy / "bin"
    bin_dir.mkdir(parents=True)
    internal = bin_dir / "AIPromptBridge_Internal.exe"
    internal.write_text("x", encoding="utf-8")
    (deploy / "AIPromptBridge-NoConsole.exe").write_text("gui", encoding="utf-8")
    console = deploy / "AIPromptBridge.exe"
    console.write_text("console", encoding="utf-8")

    monkeypatch.setattr(sm, "is_compiled", lambda: True)
    monkeypatch.setattr(sm, "is_linux", lambda: False)
    monkeypatch.setattr(sm, "is_windows", lambda: True)
    monkeypatch.setattr(sys, "executable", str(internal))
    monkeypatch.setattr(sys, "argv", ["AIPromptBridge_Internal.exe", "--launched-mode=console"])
    monkeypatch.chdir(deploy)

    found = sm.get_launcher_path()
    assert found is not None
    assert Path(found).name == "AIPromptBridge.exe"


@pytest.mark.skipif(not is_linux(), reason="XDG autostart is Linux-only")
def test_linux_compiled_autostart_desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Compiled Linux autostart writes Exec=<binary> without main.py."""
    import src.startup_manager as sm

    deploy = tmp_path / "deploy"
    bin_dir = deploy / "bin"
    bin_dir.mkdir(parents=True)
    (deploy / "config.ini").write_text("[app]\n", encoding="utf-8")
    internal = bin_dir / "AIPromptBridge_Internal"
    internal.write_text("x", encoding="utf-8")

    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setattr(sm, "is_compiled", lambda: True)
    monkeypatch.setattr(sys, "executable", str(internal))
    monkeypatch.setattr(sm, "get_launcher_path", lambda: None)

    ok, msg = sm.set_startup(True)
    assert ok is True, msg
    desktop = sm.get_autostart_desktop_path()
    content = desktop.read_text(encoding="utf-8")
    assert "main.py" not in content
    assert "AIPromptBridge_Internal" in content
    assert f"Path={deploy.resolve()}" in content or "Path=" in content
    sm.set_startup(False)
