#!/usr/bin/env python3
"""
AIPromptBridge - AI Desktop Tools & Integration Bridge
Main entry point

Usage:
    python main.py              # Start with tray (console hidden)
    python main.py --show-console   # Start with tray + console visible
    python main.py --no-wt      # Skip Windows Terminal auto-detection
    python main.py --trigger snip   # Linux: trigger tool on running instance

Nuitka Configuration:
(Moved to .github/workflows/manual_release.yml)
"""

import argparse
import contextlib
import ctypes
import logging
import os
import shutil
import signal
import socket
import sys
import threading
from pathlib import Path

from src import web_server
from src.attachment_manager import AttachmentManager
from src.config import CONFIG_FILE, OPENROUTER_URL, generate_example_config, load_config
from src.console import HAVE_RICH, Panel, Table, console, print_error, print_panel, print_success, print_warning
from src.key_store import KeyStore
from src.platform import (
    KNOWN_TRIGGERS,
    InstanceLock,
    TriggerServer,
    acquire_single_instance,
    is_linux,
    is_windows,
    send_trigger,
)
from src.session_manager import list_sessions, load_sessions
from src.terminal import print_commands_box, terminal_session_manager
from src.version import __version__

# GUI core is optional (e.g. Linux hosts without tkinter) — soft import
try:
    from src.gui.core import HAVE_GUI, show_settings_window_blocking
except ImportError:
    HAVE_GUI = False
    show_settings_window_blocking = None  # type: ignore[assignment]

# System tray support (Windows: infi.systray / Linux: pystray)
HAVE_TRAY = False
try:
    from src.tray import HAVE_SYSTRAY, TrayApp, hide_console, show_console

    HAVE_TRAY = HAVE_SYSTRAY
except ImportError:
    pass

# TextEditTool - now part of gui module
TEXT_EDIT_TOOL_APP = None
try:
    from src.gui.text_edit_tool import TextEditToolApp

    HAVE_TEXT_EDIT_TOOL = True
except ImportError:
    TextEditToolApp = None  # type: ignore[assignment,misc]
    HAVE_TEXT_EDIT_TOOL = False
    # Silent - will show in startup

# SnipTool - screen snipping feature
SNIP_TOOL_APP = None
try:
    from src.gui.snip_tool import SnipToolApp

    HAVE_SNIP_TOOL = True
except ImportError:
    SnipToolApp = None  # type: ignore[assignment,misc]
    HAVE_SNIP_TOOL = False
    # Silent - will show in startup

# AudioTool - audio analysis feature
AUDIO_TOOL_APP = None
try:
    from src.gui.audio_tool import AudioToolApp

    HAVE_AUDIO_TOOL = True
except ImportError:
    AudioToolApp = None  # type: ignore[assignment,misc]
    HAVE_AUDIO_TOOL = False
    # Silent - will show in startup

# TTSTool - text-to-speech feature
TTS_TOOL_APP = None
try:
    from src.gui.tts_tool import TTSToolApp

    HAVE_TTS_TOOL = True
except ImportError:
    TTSToolApp = None  # type: ignore[assignment,misc]
    HAVE_TTS_TOOL = False
    # Silent - will show in startup

# IPC trigger server (Linux) + readiness gate for early-started socket
_INSTANCE_LOCK = None  # Optional[InstanceLock]
_TRIGGER_SERVER = None  # Optional[TriggerServer]
_TOOLS_READY = False


def get_base_url(config, provider, profile=None):
    """Get the base URL for a provider.

    Args:
        config: Config dict (used as fallback when profile is None).
        provider: Provider name string.
        profile: Optional ConnectionProfile — preferred source for URL fields.
    """
    url = (profile.base_url if profile else None) or config.get("base_url", "")
    if not url:
        try:
            from src.providers.registry import get_provider_definition

            defn = get_provider_definition(provider)
            if defn:
                url = defn.default_base_url
        except Exception:
            pass

    if url:
        if "://" in url:
            url = url.split("://")[-1]
        if "/chat/completions" in url:
            url = url.replace("/chat/completions", "")
        if "/v1beta" in url:
            url = url.split("/v1beta")[0]
        return url

    # Legacy fallbacks
    if provider == "custom":
        url = config.get("custom_url", "")
        if url:
            if "://" in url:
                url = url.split("://")[-1]
            if "/chat/completions" in url:
                url = url.replace("/chat/completions", "")
            return url
        return "Not configured"
    elif provider == "openrouter":
        return "openrouter.ai/api/v1"
    elif provider == "google":
        return config.get("gemini_endpoint") or "generativelanguage.googleapis.com"
    return "Unknown"


def initialize():
    """Initialize the server with compact, informative output"""

    # ─── Banner ───────────────────────────────────────────────────────────
    if HAVE_RICH:
        console.print()
        print_panel(
            f"[bold cyan]🌉 AIPromptBridge v{__version__}[/bold cyan]\n[dim]AI Desktop Tools & Integration Bridge[/dim]",
            border_style="cyan",
        )
        console.print()
    else:
        print()
        print("┌" + "─" * 62 + "┐")
        print(f"│  🌉 AIPromptBridge v{__version__}".ljust(63) + "│")
        print("│  AI Desktop Tools & Integration Bridge                        │")
        print("└" + "─" * 62 + "┘")
        print()

    # Load configuration
    config = load_config()
    ai_params = {}

    # Set global configuration
    web_server.CONFIG = config
    web_server.AI_PARAMS = ai_params

    # Initialize key managers via KeyStore (pool-based)
    key_store = KeyStore.get_instance()
    key_store.load()
    web_server.KEY_MANAGERS = key_store.build_key_managers()

    # ─── Set active connection profile ────────────────────────────────────
    from src.connection_profiles import ProfileStore

    profile_store = ProfileStore.get_instance()
    active_profile = profile_store.get_active_profile()
    # Profile is the source of truth — no longer populating CONFIG/AI_PARAMS
    # (connection keys are read via ACTIVE_PROFILE / get_active_setting() / resolve_profile())

    # ─── Configuration Summary ────────────────────────────────────────────
    provider = active_profile.provider
    model = active_profile.model
    base_url = get_base_url(config, provider, profile=active_profile)
    streaming = active_profile.streaming
    thinking = active_profile.thinking

    if HAVE_RICH:
        # Create a nice table for configuration
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="dim")
        table.add_column("Value")

        table.add_row("📡 Provider", f"[cyan]{provider}[/cyan] → [dim]{base_url}[/dim]")
        table.add_row("🤖 Model", f"[green]{model}[/green]")
        stream_icon = "[green]✓[/green]" if streaming else "[red]✗[/red]"
        think_icon = "[green]✓[/green]" if thinking else "[red]✗[/red]"
        table.add_row("🌊 Streaming", stream_icon)
        table.add_row("💭 Thinking", think_icon)

        console.print("[bold]⚙️  Configuration[/bold]")
        console.print(table)
        console.print()
    else:
        print("⚙️  Configuration")
        print(f"    📡 Provider:  {provider} → {base_url}")
        print(f"    🤖 Model:     {model}")
        stream_icon = "✓" if streaming else "✗"
        think_icon = "✓" if thinking else "✗"
        print(f"    🌊 Streaming: {stream_icon}")
        print(f"    💭 Thinking:  {think_icon}")
        print()

    # ─── API Keys ─────────────────────────────────────────────────────────
    if HAVE_RICH:
        key_parts = []
        for p in ["custom", "openrouter", "google"]:
            count = web_server.KEY_MANAGERS[p].get_key_count()
            if count > 0:
                marker = " ◄" if p == provider else ""
                key_parts.append(f"[green]✓[/green] {p} ({count}){marker}")
            else:
                key_parts.append(f"[red]✗[/red] {p}")
        console.print(f"[bold]🔑 API Keys[/bold]  {key_parts[0]}  {key_parts[1]}  {key_parts[2]}")
        console.print()
    else:
        print("🔑 API Keys")
        key_status = []
        for p in ["custom", "openrouter", "google"]:
            count = web_server.KEY_MANAGERS[p].get_key_count()
            if count > 0:
                marker = " ◄" if p == provider else ""
                key_status.append(f"✓ {p} ({count}){marker}")
            else:
                key_status.append(f"✗ {p}")
        print(f"    {key_status[0]}   {key_status[1]}   {key_status[2]}")
        print()

    # ─── Sessions ─────────────────────────────────────────────────────────
    load_sessions()
    sessions = list_sessions()

    # Cleanup orphaned attachments from deleted sessions
    # (Runs in background to avoid slowing down startup)
    threading.Thread(target=AttachmentManager.cleanup_orphaned_attachments, daemon=True).start()

    if HAVE_RICH:
        console.print(f"[bold]📂 Sessions[/bold]  {len(sessions)} loaded")
        console.print()
    else:
        print(f"📂 Sessions: {len(sessions)} loaded")
        print()

    # Initialize web server (silent)
    web_server.init_web_server(config, ai_params, web_server.KEY_MANAGERS)

    return config, ai_params


def initialize_text_edit_tool(config, ai_params):
    """Initialize TextEditTool if enabled"""
    global TEXT_EDIT_TOOL_APP

    if not HAVE_TEXT_EDIT_TOOL:
        if HAVE_RICH:
            console.print("  [red]✗[/red] TextEditTool: Not available (missing dependencies)")
        else:
            print("  ✗ TextEditTool: Not available (missing dependencies)")
        return None

    if not config.get("text_edit_tool_enabled", True):
        if HAVE_RICH:
            console.print("  [red]✗[/red] TextEditTool: Disabled in config")
        else:
            print("  ✗ TextEditTool: Disabled in config")
        return None

    try:
        if HAVE_RICH:
            console.print("\nInitializing TextEditTool...")
        else:
            print("\nInitializing TextEditTool...")
        TEXT_EDIT_TOOL_APP = TextEditToolApp(config=config, ai_params=ai_params, key_managers=web_server.KEY_MANAGERS)
        TEXT_EDIT_TOOL_APP.start()

        # Register instance for hot-reload
        from src.gui.text_edit_tool import set_instance

        set_instance(TEXT_EDIT_TOOL_APP)

        return TEXT_EDIT_TOOL_APP
    except Exception as e:
        if HAVE_RICH:
            console.print(f"  [red]✗ TextEditTool: Failed to initialize: {e}[/red]")
        else:
            print(f"  ✗ TextEditTool: Failed to initialize: {e}")
        return None


def initialize_snip_tool(config, ai_params):
    """Initialize SnipTool if enabled"""
    global SNIP_TOOL_APP

    if not HAVE_SNIP_TOOL:
        if HAVE_RICH:
            console.print("  [red]✗[/red] SnipTool: Not available (missing dependencies)")
        else:
            print("  ✗ SnipTool: Not available (missing dependencies)")
        return None

    if not config.get("screen_snip_enabled", True):
        if HAVE_RICH:
            console.print("  [red]✗[/red] SnipTool: Disabled in config")
        else:
            print("  ✗ SnipTool: Disabled in config")
        return None

    try:
        SNIP_TOOL_APP = SnipToolApp(config=config, ai_params=ai_params, key_managers=web_server.KEY_MANAGERS)
        SNIP_TOOL_APP.start()

        # Register instance for hot-reload
        from src.gui.snip_tool import set_instance

        set_instance(SNIP_TOOL_APP)

        return SNIP_TOOL_APP
    except Exception as e:
        if HAVE_RICH:
            console.print(f"  [red]✗ SnipTool: Failed to initialize: {e}[/red]")
        else:
            print(f"  ✗ SnipTool: Failed to initialize: {e}")
        return None


def initialize_audio_tool(config, ai_params):
    """Initialize AudioTool if enabled"""
    global AUDIO_TOOL_APP

    if not HAVE_AUDIO_TOOL:
        if HAVE_RICH:
            console.print("  [red]✗[/red] AudioTool: Not available (missing dependencies)")
        else:
            print("  ✗ AudioTool: Not available (missing dependencies)")
        return None

    if not config.get("audio_tool_enabled", True):
        if HAVE_RICH:
            console.print("  [red]✗[/red] AudioTool: Disabled in config")
        else:
            print("  ✗ AudioTool: Disabled in config")
        return None

    try:
        AUDIO_TOOL_APP = AudioToolApp(config=config, ai_params=ai_params, key_managers=web_server.KEY_MANAGERS)
        AUDIO_TOOL_APP.start()

        # Register instance for hot-reload
        from src.gui.audio_tool import set_instance

        set_instance(AUDIO_TOOL_APP)

        return AUDIO_TOOL_APP
    except Exception as e:
        if HAVE_RICH:
            console.print(f"  [red]✗ AudioTool: Failed to initialize: {e}[/red]")
        else:
            print(f"  ✗ AudioTool: Failed to initialize: {e}")
        return None


def initialize_tts_tool(config, ai_params):
    """Initialize TTSTool if enabled"""
    global TTS_TOOL_APP

    if not HAVE_TTS_TOOL:
        if HAVE_RICH:
            console.print("  [red]✗[/red] TTSTool: Not available (missing dependencies)")
        else:
            print("  ✗ TTSTool: Not available (missing dependencies)")
        return None

    if not config.get("tts_enabled", True):
        return None

    # Check if Gemini key is available (TTS is Gemini-only)
    gemini_key_manager = web_server.KEY_MANAGERS.get("google")
    if not gemini_key_manager or not gemini_key_manager.has_keys():
        if HAVE_RICH:
            console.print("  [red]✗[/red] TTSTool: Requires Google Gemini API key")
        else:
            print("  ✗ TTSTool: Requires Google Gemini API key")
        return None

    try:
        TTS_TOOL_APP = TTSToolApp(config=config, ai_params=ai_params, key_managers=web_server.KEY_MANAGERS)
        TTS_TOOL_APP.start()

        # Register instance for hot-reload
        from src.gui.tts_tool import set_instance

        set_instance(TTS_TOOL_APP)

        return TTS_TOOL_APP
    except Exception as e:
        if HAVE_RICH:
            console.print(f"  [red]✗ TTSTool: Failed to initialize: {e}[/red]")
        else:
            print(f"  ✗ TTSTool: Failed to initialize: {e}")
        return None


def cleanup():
    """Cleanup on shutdown"""
    global TEXT_EDIT_TOOL_APP, SNIP_TOOL_APP, AUDIO_TOOL_APP, TTS_TOOL_APP
    global _TRIGGER_SERVER, _INSTANCE_LOCK, _TOOLS_READY

    _TOOLS_READY = False

    if _TRIGGER_SERVER is not None:
        with contextlib.suppress(Exception):
            _TRIGGER_SERVER.stop()
        _TRIGGER_SERVER = None

    if _INSTANCE_LOCK is not None:
        with contextlib.suppress(Exception):
            _INSTANCE_LOCK.release()
        _INSTANCE_LOCK = None

    if TEXT_EDIT_TOOL_APP:
        if HAVE_RICH:
            console.print("\nStopping TextEditTool...")
        else:
            print("\nStopping TextEditTool...")
        TEXT_EDIT_TOOL_APP.stop()
        TEXT_EDIT_TOOL_APP = None

    if SNIP_TOOL_APP:
        if HAVE_RICH:
            console.print("Stopping SnipTool...")
        else:
            print("Stopping SnipTool...")
        SNIP_TOOL_APP.stop()
        SNIP_TOOL_APP = None

    if AUDIO_TOOL_APP:
        if HAVE_RICH:
            console.print("Stopping AudioTool...")
        else:
            print("Stopping AudioTool...")
        AUDIO_TOOL_APP.stop()
        AUDIO_TOOL_APP = None

    if TTS_TOOL_APP:
        if HAVE_RICH:
            console.print("Stopping TTSTool...")
        else:
            print("Stopping TTSTool...")
        TTS_TOOL_APP.stop()
        TTS_TOOL_APP = None


def signal_handler(signum, frame):
    """Handle interrupt signals"""
    # Check if TextEditTool is currently copying (Ctrl+C simulation)
    # If so, ignore the signal as it's self-inflicted
    global TEXT_EDIT_TOOL_APP, SNIP_TOOL_APP
    if TEXT_EDIT_TOOL_APP and hasattr(TEXT_EDIT_TOOL_APP, "is_copying") and TEXT_EDIT_TOOL_APP.is_copying():
        return

    if HAVE_RICH:
        console.print("\n\n[bold yellow]Shutdown signal received...[/bold yellow]")
    else:
        print("\n\nShutdown signal received...")
    cleanup()
    # Force exit to prevent SystemExit issues with daemon threads
    os._exit(0)


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="AIPromptBridge - AI Desktop Tools & Integration Bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                  Start application (console hidden by default)
  python main.py --show-console   Start application with console visible
  python main.py --no-wt          Skip Windows Terminal auto-detection
  python main.py --trigger snip   Linux: invoke tool on the running instance

Linux Wayland (niri / wlroots) supported:
  Global hotkeys are not registered. Bind window-manager keys to a running
  instance (does not auto-start the full app), e.g. niri:
    bind "Mod+Shift+T" { spawn "uv" "run" "main.py" "--trigger" "textedit"; }
    bind "Mod+Shift+S" { spawn "uv" "run" "main.py" "--trigger" "snip"; }
    bind "Mod+Shift+A" { spawn "uv" "run" "main.py" "--trigger" "audio"; }
  Other triggers: tts, chat, browser.

  System packages (install as needed):
    wl-clipboard  — clipboard + primary selection (required for TextEdit/Snip paste)
    wlrctl        — type/paste + hybrid Ctrl+C for keyboard-only selection
    grim, slurp   — region screenshot (SnipTool)
    portaudio     — PyAudio devices / monitor sources
    paplay (or pw-play / ffplay) — optional feedback sounds

  Selection capture: prefers primary (mouse highlight, no clipboard pollution);
  if empty, falls back to hybrid wlrctl Ctrl+C + restore.
        """,
    )
    parser.add_argument("--show-console", action="store_true", help="Start with console visible")
    parser.add_argument("--dummy", action="store_true", help="Dummy argument (does nothing)")
    parser.add_argument(
        "--trigger",
        choices=list(KNOWN_TRIGGERS),
        metavar="NAME",
        help=(
            f"Linux IPC client: send a trigger to the running instance and exit (one of: {', '.join(KNOWN_TRIGGERS)})"
        ),
    )
    parser.add_argument(
        "--launched-mode",
        help=argparse.SUPPRESS,  # Hidden argument used by launchers
    )
    return parser.parse_args()


def dispatch_trigger(name: str) -> tuple:
    """
    Server-side trigger dispatch — same entry points as tray/hotkeys.

    Returns:
        (ok: bool, detail: str)  detail empty on success; error body on failure.
    """
    global _TOOLS_READY

    name = (name or "").strip().lower()
    if not name:
        return False, "missing trigger name"

    if not _TOOLS_READY:
        return False, "not ready"

    try:
        if name in ("textedit", "chat"):
            from src.gui.text_edit_tool import get_instance

            app = get_instance()
            if app is None or not hasattr(app, "_on_hotkey_pressed"):
                return False, "tool unavailable"
            app._on_hotkey_pressed()
            return True, ""

        if name == "snip":
            from src.gui.snip_tool import get_instance

            app = get_instance()
            if app is None or not hasattr(app, "_on_hotkey_pressed"):
                return False, "tool unavailable"
            app._on_hotkey_pressed()
            return True, ""

        if name == "audio":
            from src.gui.audio_tool import get_instance

            app = get_instance()
            if app is None or not hasattr(app, "_on_hotkey_pressed"):
                return False, "tool unavailable"
            app._on_hotkey_pressed()
            return True, ""

        if name == "tts":
            # Prefer tool instance (same as hotkey); fall back to tray-style path
            try:
                from src.gui.tts_tool import get_instance

                app = get_instance()
                if app is not None and hasattr(app, "_on_hotkey_pressed"):
                    app._on_hotkey_pressed()
                    return True, ""
            except ImportError:
                pass

            if not web_server.CONFIG or not web_server.CONFIG.get("tts_enabled", True):
                return False, "tool unavailable"
            if not HAVE_GUI:
                return False, "tool unavailable"
            from src.gui.core import GUICoordinator

            GUICoordinator.get_instance().request_tts_window(
                web_server.CONFIG, web_server.AI_PARAMS, web_server.KEY_MANAGERS, initial_text=""
            )
            return True, ""

        if name == "browser":
            if not HAVE_GUI:
                return False, "tool unavailable"
            from src.gui.core import show_session_browser

            show_session_browser()
            return True, ""

        if name == "settings":
            if not HAVE_GUI:
                return False, "tool unavailable"
            from src.gui.core import show_settings_window

            show_settings_window()
            return True, ""

        if name == "prompts":
            if not HAVE_GUI:
                return False, "tool unavailable"
            from src.gui.core import show_prompt_editor

            show_prompt_editor()
            return True, ""

        return False, f"unknown trigger: {name}"
    except Exception as e:
        logging.exception("Trigger dispatch failed for %s", name)
        return False, f"handler failed: {e}"


def run_trigger_client(trigger_name: str) -> int:
    """
    Client mode for ``--trigger``: contact running instance over Unix socket.

    Does not start the full app. Exit 0 on ok, non-zero on error.
    """
    if is_windows():
        # Phase 1: IPC triggers are Linux-only (Windows keeps tray/hotkeys).
        msg = "IPC --trigger is only available on Linux. On Windows use the system tray or global hotkeys."
        if HAVE_RICH:
            print_error(msg)
        else:
            print(f"❌ {msg}")
        return 1

    ok, message = send_trigger(trigger_name)
    if ok:
        if HAVE_RICH:
            print_success(f"trigger {trigger_name}: {message}")
        else:
            print(f"✅ trigger {trigger_name}: {message}")
        return 0

    if HAVE_RICH:
        print_error(f"trigger {trigger_name}: {message}")
    else:
        print(f"❌ trigger {trigger_name}: {message}")
    return 1


from src.utils import is_compiled as _is_compiled


def _move_if_exists(src: Path, dst: Path):
    """Move a single file or directory if source exists. Silent on failure."""
    try:
        if not src.exists():
            return
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        shutil.move(str(src), str(dst))
    except Exception:
        pass


def _migrate_stale_files(bin_dir: Path, root_dir: Path):
    """
    Move any leftover config/data files from bin/ to root/ in the background.
    This handles the edge case where files end up next to the internal .exe
    instead of the launcher directory.
    """
    managed_files = ["chat_sessions.json", "tools_config.json", "keys.json", "profiles.json"]
    managed_globs = ["config.ini*", "prompts.json*", "*file_processor.json", ".file_processor_*.json"]
    managed_folders = ["session_attachments"]

    try:
        for filename in managed_files:
            _move_if_exists(bin_dir / filename, root_dir / filename)

        for pattern in managed_globs:
            for file_path in bin_dir.glob(pattern):
                _move_if_exists(file_path, root_dir / file_path.name)

        for foldername in managed_folders:
            _move_if_exists(bin_dir / foldername, root_dir / foldername)
    except Exception:
        pass  # Non-blocking, best-effort


def setup_workspace(launched_mode):
    """
    Set up the working directory based on how the app was launched.

    Rules:
      - From source (python main.py): No changes needed, use current directory.
      - Compiled + launcher (--launched-mode): CWD = launcher's directory (parent of bin/).
      - Compiled + no launcher: Refuse to run (must use launcher).

    Args:
        launched_mode: Value of --launched-mode arg (None if not set).

    Returns:
        True if setup succeeded, False if the app should exit.
    """
    if not _is_compiled():
        # Running from source - no workspace setup needed
        return True

    if not launched_mode:
        # Compiled binary run directly without a launcher - refuse to start
        msg = (
            "This executable must be launched via one of the launcher files:\n"
            "- AIPromptBridge.exe (Console)\n"
            "- AIPromptBridge-NoConsole.exe (GUI)\n\n"
            "Direct execution of the internal binary is not supported as it bypasses workspace configuration."
        )
        try:
            # 0x10 = MB_ICONERROR
            ctypes.windll.user32.MessageBoxW(0, msg, "AIPromptBridge Error", 0x10)
        except Exception:
            # Fallback if no GUI
            print(f"❌ {msg}")
            import contextlib

            with contextlib.suppress(EOFError):
                input("Press Enter to exit...")
        return False

    # Compiled with launcher: CWD = root directory (parent of bin/)
    bin_dir = Path(sys.executable).parent
    root_dir = bin_dir.parent
    os.chdir(root_dir)

    # Non-blocking: move any stale config files from bin/ to root/
    threading.Thread(target=_migrate_stale_files, args=(bin_dir, root_dir), daemon=True).start()

    return True


def check_port_available(host: str, port: int) -> bool:
    """
    Check if a port is available for binding.
    Returns True if available, False if already in use.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        sock.bind((host, port))
        sock.close()
        return True
    except OSError:
        return False


def find_available_port(host: str, port: int, max_attempts: int = 20) -> int:
    """
    Find an available port starting from the configured port.
    Tries port, port+1, port+2, ... up to max_attempts.

    Returns:
        Available port number

    Raises:
        RuntimeError if no port found within max_attempts
    """
    for offset in range(max_attempts):
        candidate = port + offset
        if candidate > 65535:
            break
        if check_port_available(host, candidate):
            return candidate
    raise RuntimeError(f"No available port found in range {port}-{port + max_attempts - 1}")


def acquire_single_instance_mutex():
    """
    Legacy wrapper — prefer src.platform.acquire_single_instance().

    Windows: named mutex handle or None.
    Non-Windows: \"NotWindows\" (historical; Linux now uses socket ownership).
    """
    from src.platform.single_instance import acquire_single_instance_mutex as _acquire

    return _acquire()


def run_server(config, ai_params):
    """Run the Flask server (used by both tray and terminal modes)"""
    host = web_server.CONFIG.get("host", "127.0.0.1")
    port = int(web_server.CONFIG.get("port", 5000))

    try:
        # Run Flask with minimal output
        web_server.app.run(host=host, port=port, use_reloader=False, threaded=True)
    finally:
        cleanup()


def configure_logging(debug_mode: bool = False):
    """
    Configure global logging with Rich handler if available.

    By default (no --show-console), no logging configuration is done,
    keeping Python's default WARNING level for a clean console.

    When debug_mode is True (--show-console), enables DEBUG level logging
    with Rich formatting for better visibility.

    Args:
        debug_mode: If True, configure DEBUG level logging. Otherwise, minimal setup.
    """
    # Always suppress noisy third-party loggers
    noisy_loggers = ["werkzeug", "PIL", "PIL.PngImagePlugin", "PIL.Image"]
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # If not debug mode, just suppress noise and leave Python's default WARNING level
    if not debug_mode:
        return

    # Debug mode: configure INFO/DEBUG level with Rich handler
    level = logging.DEBUG

    # Try to use Rich's logging handler for better output
    if HAVE_RICH:
        try:
            from rich.logging import RichHandler

            # Configure with Rich handler - use force=True to reconfigure
            logging.basicConfig(
                level=level,
                format="%(message)s",
                datefmt="[%X]",
                handlers=[
                    RichHandler(
                        console=console,
                        show_time=False,  # Cleaner output
                        show_level=True,
                        show_path=False,  # Reduce noise
                        markup=True,
                        rich_tracebacks=True,
                    )
                ],
                force=True,  # Override any existing configuration
            )
        except ImportError:
            # Fallback to basic config
            logging.basicConfig(level=level, format="[%(levelname)s] %(name)s: %(message)s", force=True)
    else:
        # Basic config without Rich
        logging.basicConfig(level=level, format="[%(levelname)s] %(name)s: %(message)s", force=True)

    logging.debug("Debug logging enabled (--show-console)")


def main():
    """Main entry point"""
    global _INSTANCE_LOCK, _TRIGGER_SERVER, _TOOLS_READY

    # Parse command line arguments first (doesn't depend on CWD)
    args = parse_args()

    # ─── IPC client mode (--trigger) ───────────────────────────────────────
    # Contact the running instance and exit. No workspace / full app init.
    if args.trigger:
        sys.exit(run_trigger_client(args.trigger))

    # Set up workspace (CWD resolution for compiled mode)
    if not setup_workspace(args.launched_mode):
        sys.exit(1)

    # ─── Startup Recovery ──────────────────────────────────────────────────
    # Check for interrupted updates and recover before anything else
    try:
        from src.updater import startup_recovery

        startup_recovery()
    except Exception:
        pass  # Non-critical, don't block startup

    # Single instance check (Windows: named mutex; Linux: Unix socket bind)
    # Done early to prevent multiple instances. On Linux the bound socket is
    # reused by the IPC trigger server.
    _INSTANCE_LOCK = acquire_single_instance()
    if _INSTANCE_LOCK is None:
        if args.show_console:
            # If console is visible, we might want to alert
            pass

        if HAVE_RICH:
            print_error("Another instance of AIPromptBridge is already running!")
        else:
            print("❌ ERROR: Another instance of AIPromptBridge is already running!")

        # If console is hidden, just exit silently
        # User probably just double clicked the icon again
        if not args.show_console:
            sys.exit(0)

        import contextlib

        print("Press Enter to exit...")
        with contextlib.suppress(EOFError):
            input()
        sys.exit(1)

    # Linux: start IPC server early so --trigger clients get "not ready"
    # instead of "no instance" while tools initialize.
    if is_linux() and _INSTANCE_LOCK.listen_socket is not None:
        _TRIGGER_SERVER = TriggerServer(
            handler=dispatch_trigger,
            socket_path=_INSTANCE_LOCK.socket_path,
            listen_sock=_INSTANCE_LOCK.listen_socket,
            unlink_on_stop=True,
        )
        # Transfer listen socket ownership to the IPC server (avoid double-close
        # / double-unlink in InstanceLock.release()).
        _INSTANCE_LOCK._listen_sock = None
        _INSTANCE_LOCK._socket_path = None
        try:
            _TRIGGER_SERVER.start()
        except Exception as e:
            if HAVE_RICH:
                print_warning(f"IPC trigger server failed to start: {e}")
            else:
                print(f"⚠️  IPC trigger server failed to start: {e}")
            _TRIGGER_SERVER = None

    # Configure global logging (DEBUG if --show-console, otherwise INFO)
    configure_logging(debug_mode=args.show_console)

    # Determine if we have a real console (for WT relaunch and console toggle)
    # - GUI mode: No console (skip WT, no toggle)
    # - Console mode: Has console (WT check, toggle enabled)
    # - No launched-mode + compiled (Internal.exe): No console (attach mode, skip WT)
    # - No launched-mode + source (python main.py): Has console (WT check, toggle enabled)
    # Note: computed earlier for early-tray launch.

    # Suppress Flask startup banner
    import flask.cli

    flask.cli.show_server_banner = lambda *args: None

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create example config if needed
    if not Path(CONFIG_FILE).exists():
        if HAVE_RICH:
            print_warning(f"Config file '{CONFIG_FILE}' not found.")
            console.print("Creating example configuration file...")
        else:
            print(f"Config file '{CONFIG_FILE}' not found.")
            print("Creating example configuration file...")
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(generate_example_config())
        if HAVE_RICH:
            print_success(f"Created '{CONFIG_FILE}'")
        else:
            print(f"✅ Created '{CONFIG_FILE}'")

    # Check for prompts.json creation notification
    from src.gui.prompts import PROMPTS_FILE, PromptsConfig

    if not Path(PROMPTS_FILE).exists():
        if HAVE_RICH:
            console.print("Creating default prompts configuration...")
        else:
            print("Creating default prompts configuration...")
        # Accessing instance forces creation from defaults if file is missing
        PromptsConfig.get_instance()
        if HAVE_RICH:
            print_success(f"Created '{PROMPTS_FILE}'")
        else:
            print(f"✅ Created '{PROMPTS_FILE}'")

    # ─── Onboarding & Initialization ───────────────────────────────────────────
    # Initialize (new compact output)
    config, ai_params = initialize()

    # Determine if we have a real console (for WT relaunch and console toggle)
    is_compiled = _is_compiled()
    if args.launched_mode == "gui":
        has_real_console = False
    elif args.launched_mode == "console":
        has_real_console = True
    else:
        has_real_console = not is_compiled

    # Resolve port early before starting the server thread to prevent false port-occupied warnings
    host = web_server.CONFIG.get("host", "127.0.0.1")
    configured_port = int(web_server.CONFIG.get("port", 5000))
    try:
        actual_port = find_available_port(host, configured_port)
    except RuntimeError as e:
        if HAVE_RICH:
            console.print()
            print_error(f"Could not find an available port: {e}")
            console.print()
            console.print("[dim]Press Enter to exit...[/dim]")
        else:
            print()
            print(f"❌ ERROR: Could not find an available port: {e}")
            print()
            print("Press Enter to exit...")
        import contextlib

        with contextlib.suppress(EOFError):
            input()
        sys.exit(1)

    if actual_port != configured_port:
        if HAVE_RICH:
            print_warning(f"Port {configured_port} occupied, using {actual_port} instead")
        else:
            print(f"⚠️ Port {configured_port} occupied, using {actual_port} instead")
        # Update config in memory (so run_server picks it up)
        web_server.CONFIG["port"] = actual_port

    # Pre-launch system tray
    # Launching it early prevents race conditions and ensures it respects OS dark mode
    # before heavy UI modules block or alter global app/thread state.
    # HAVE_TRAY is platform-gated (Windows infi.systray / Linux pystray).
    use_tray = HAVE_TRAY
    tray = None
    if use_tray:
        # Start Flask server in background thread
        server_thread = threading.Thread(target=lambda: run_server(config, ai_params), daemon=True)
        server_thread.start()

        allow_console_toggle = has_real_console
        tray = TrayApp(
            on_exit_callback=cleanup, allow_console_toggle=allow_console_toggle, show_edit_file_items=args.show_console
        )
        hide_on_start = not args.show_console

        threading.Thread(target=lambda: tray.start(hide_console_on_start=hide_on_start), daemon=True).start()

    # Check if onboarding completed
    onboarding_completed = config.get("onboarding_completed", False)
    if isinstance(onboarding_completed, str):
        onboarding_completed = onboarding_completed.strip().lower() in ("true", "1")

    if not onboarding_completed and HAVE_GUI:
        if HAVE_RICH:
            console.print("[bold cyan]🚀 Starting Onboarding Wizard...[/bold cyan]")
            console.print()
        else:
            print("🚀 Starting Onboarding Wizard...")
            print()

        from src.gui.windows import show_onboarding_blocking

        show_onboarding_blocking()

        # Reload configuration and key managers after onboarding closes
        config = load_config()
        web_server.CONFIG = config

        key_store = KeyStore.get_instance()
        key_store.load()
        web_server.KEY_MANAGERS = key_store.build_key_managers()

        from src.connection_profiles import ProfileStore

        profile_store = ProfileStore.get_instance()
        # This will reload active profile settings
        profile_store.reload()

    # ─── Background Update Check ───────────────────────────────────────────
    try:
        from src.updater import background_update_check

        background_update_check(config)
    except Exception:
        pass  # Non-critical

    # Check for API keys
    has_any_keys = any(km.has_keys() for km in web_server.KEY_MANAGERS.values())
    if not has_any_keys:
        if HAVE_GUI:
            if HAVE_RICH:
                print_warning("[bold yellow]No API keys configured![/bold yellow]")
                console.print("   Opening Settings Window...")
                console.print()
            else:
                print("⚠️  No API keys configured!")
                print("   Opening Settings Window...")
                print()

            # Open Settings Window directly (blocking)
            # Use GUICoordinator to keep the root alive and avoid re-init delays
            if show_settings_window_blocking is not None:
                show_settings_window_blocking(initial_tab="API Keys")
            else:
                if HAVE_RICH:
                    print_warning("GUI not available — configure API keys in keys.json / Settings later.")
                else:
                    print("⚠️  GUI not available — configure API keys in keys.json / Settings later.")

            # Reload keys after settings window closes
            has_any_keys = any(km.has_keys() for km in web_server.KEY_MANAGERS.values())

        if not has_any_keys:
            if HAVE_RICH:
                console.print("[bold yellow]⚠️  WARNING: No API keys configured![/bold yellow]")
                console.print("   Please add your API keys to [cyan]config.ini[/cyan] or use the Settings window.")
                console.print()
            else:
                print("⚠️  WARNING: No API keys configured!")
                print("   Please add your API keys. Use the Settings window.")
                print()

    # ─── Server Info ──────────────────────────────────────────────────────
    host = web_server.CONFIG.get("host", "127.0.0.1")
    port = int(web_server.CONFIG.get("port", 5000))

    if HAVE_RICH:
        console.print(
            f"[bold green]🚀 Server Running[/bold green]: [link=http://{host}:{port}]http://{host}:{port}[/link]"
        )
    else:
        print(f"🚀 Server Running: http://{host}:{port}")

    # TextEditTool
    text_tool_result = initialize_text_edit_tool(config, ai_params)
    if text_tool_result:
        hotkey = config.get("text_edit_tool_hotkey", "ctrl+space")

    # SnipTool
    snip_tool_result = initialize_snip_tool(config, ai_params)
    if snip_tool_result:
        snip_hotkey = config.get("screen_snip_hotkey", "ctrl+alt+x")

    # AudioTool
    audio_tool_result = initialize_audio_tool(config, ai_params)
    if audio_tool_result:
        audio_hotkey = config.get("audio_tool_hotkey", "ctrl+alt+a")

    # TTSTool
    tts_tool_result = initialize_tts_tool(config, ai_params)
    if tts_tool_result:
        tts_hotkey = config.get("tts_hotkey", "ctrl+alt+t")

    # Tools finished initializing — IPC triggers may dispatch for real
    _TOOLS_READY = True
    if _TRIGGER_SERVER is not None:
        _TRIGGER_SERVER.mark_ready()
        if is_linux():
            from src.platform.ipc import get_socket_path

            if HAVE_RICH:
                console.print(
                    f"[dim]🔌 IPC triggers: [cyan]uv run main.py --trigger <name>[/cyan] "
                    f"(socket: {get_socket_path()})[/dim]"
                )
            else:
                print(f"🔌 IPC triggers: uv run main.py --trigger <name> (socket: {get_socket_path()})")

    if HAVE_RICH:
        console.print()
    else:
        print()

    # ─── Execution Loop ───────────────────────────────────────────────────
    # Re-evaluate in case tray import state is relevant (HAVE_TRAY is fixed at import)
    use_tray = HAVE_TRAY

    if use_tray:
        if is_linux():
            if HAVE_RICH:
                console.print(
                    "[dim]📌 System tray active (pystray). "
                    "Needs a StatusNotifier host (waybar/dms/etc.) for the icon to appear.[/dim]"
                )
            else:
                print(
                    "📌 System tray active (pystray). "
                    "Needs a StatusNotifier host (waybar/dms/etc.) for the icon to appear."
                )

        # Start terminal session manager at the very end so commands box displays after all startup logs
        terminal_thread = threading.Thread(target=lambda: terminal_session_manager(), daemon=True)
        terminal_thread.start()

        # Keep the main thread alive since the tray is already running in a daemon thread.
        # Wait until the main thread gets a keyboard interrupt or shutdown signal.
        import time

        try:
            while True:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            pass
        cleanup()
        os._exit(0)

    else:
        # Fallback terminal + IPC (no tray backend for this OS, or package missing)
        if not HAVE_TRAY:
            if is_linux():
                if HAVE_RICH:
                    console.print(
                        "[dim]📟 Running in terminal mode (tray unavailable — install pystray; hotkeys via IPC)[/dim]"
                    )
                    console.print(
                        "   Window-manager binds: [cyan]uv run main.py --trigger snip[/cyan] "
                        "(also: textedit, audio, tts, chat, browser)"
                    )
                    console.print(
                        "   Tray requires: [cyan]pip install pystray[/cyan] "
                        "+ StatusNotifier host (waybar/dms) + optional libappindicator"
                    )
                else:
                    print("📟 Running in terminal mode (tray unavailable — install pystray; hotkeys via IPC)")
                    print("   Window-manager binds: uv run main.py --trigger snip")
            else:
                if HAVE_RICH:
                    console.print("[dim]📟 Running in terminal-only fallback (tray not available)[/dim]")
                    console.print("   Install with: [cyan]pip install infi.systray[/cyan]")
                else:
                    print("📟 Running in terminal-only fallback (tray not available)")
                    print("   Install with: pip install infi.systray")
        print()

        # Start terminal session manager
        terminal_thread = threading.Thread(target=lambda: terminal_session_manager(), daemon=True)
        terminal_thread.start()

        # Run server in main thread
        run_server(config, ai_params)


if __name__ == "__main__":
    main()
