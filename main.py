#!/usr/bin/env python3
"""
AIPromptBridge - AI Desktop Tools & Integration Bridge
Main entry point

Usage:
    python main.py              # Start with tray (console hidden)
    python main.py --show-console   # Start with tray + console visible
    python main.py --no-wt      # Skip Windows Terminal auto-detection

Nuitka Configuration:
(Moved to .github/workflows/manual_release.yml)
"""

import sys
import os
import socket
import logging
import threading
import signal
import argparse
import shutil
import ctypes
from pathlib import Path

from src.console import console, Panel, Table, print_panel, print_success, print_error, print_warning, HAVE_RICH
from src.config import load_config, generate_example_config, CONFIG_FILE, OPENROUTER_URL
from src.version import __version__
from src.key_store import KeyStore
from src.session_manager import load_sessions, list_sessions
from src.attachment_manager import AttachmentManager
from src.terminal import terminal_session_manager, print_commands_box
from src.gui.core import HAVE_GUI, show_settings_window_blocking
from src import web_server

# System tray support
HAVE_TRAY = False
try:
    from src.tray import TrayApp, hide_console, show_console, HAVE_SYSTRAY
    HAVE_TRAY = HAVE_SYSTRAY
except ImportError:
    pass

# TextEditTool - now part of gui module
TEXT_EDIT_TOOL_APP = None
try:
    from src.gui import TextEditToolApp
    HAVE_TEXT_EDIT_TOOL = True
except ImportError as e:
    HAVE_TEXT_EDIT_TOOL = False
    # Silent - will show in startup

# SnipTool - screen snipping feature
SNIP_TOOL_APP = None
try:
    from src.gui.snip_tool import SnipToolApp
    HAVE_SNIP_TOOL = True
except ImportError as e:
    HAVE_SNIP_TOOL = False
    # Silent - will show in startup

# AudioTool - audio analysis feature
AUDIO_TOOL_APP = None
try:
    from src.gui.audio_tool import AudioToolApp
    HAVE_AUDIO_TOOL = True
except ImportError as e:
    HAVE_AUDIO_TOOL = False
    # Silent - will show in startup

# TTSTool - text-to-speech feature
TTS_TOOL_APP = None
try:
    from src.gui.tts_tool import TTSToolApp
    HAVE_TTS_TOOL = True
except ImportError as e:
    HAVE_TTS_TOOL = False
    # Silent - will show in startup


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
            border_style="cyan"
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
        TEXT_EDIT_TOOL_APP = TextEditToolApp(
            config=config,
            ai_params=ai_params,
            key_managers=web_server.KEY_MANAGERS
        )
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
        SNIP_TOOL_APP = SnipToolApp(
            config=config,
            ai_params=ai_params,
            key_managers=web_server.KEY_MANAGERS
        )
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
        AUDIO_TOOL_APP = AudioToolApp(
            config=config,
            ai_params=ai_params,
            key_managers=web_server.KEY_MANAGERS
        )
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
        TTS_TOOL_APP = TTSToolApp(
            config=config,
            ai_params=ai_params,
            key_managers=web_server.KEY_MANAGERS
        )
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
    if TEXT_EDIT_TOOL_APP and hasattr(TEXT_EDIT_TOOL_APP, 'is_copying') and TEXT_EDIT_TOOL_APP.is_copying():
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
  python main.py                  Start with tray (console hidden by default)
  python main.py --show-console   Start with tray and console visible
  python main.py --no-wt          Skip Windows Terminal auto-detection
        """
    )
    parser.add_argument(
        '--show-console',
        action='store_true',
        help='Start with console visible (when using tray mode)'
    )
    parser.add_argument(
        '--dummy',
        action='store_true',
        help='Dummy argument (does nothing)'
    )
    parser.add_argument(
        '--launched-mode',
        help=argparse.SUPPRESS  # Hidden argument used by launchers
    )
    return parser.parse_args()


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
            try:
                input("Press Enter to exit...")
            except EOFError:
                pass
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
    Acquire a named mutex to ensure single instance.
    
    Returns:
        mutex_handle if acquired successfully (first instance)
        None if another instance is already running
    """
    if sys.platform != 'win32':
        return "NotWindows"
        
    kernel32 = ctypes.windll.kernel32
    mutex_name = "AIPromptBridge_SingleInstance"
    
    # CreateMutexW(security_attributes, initial_owner, name)
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    
    # ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == 183:
        # Another instance owns the mutex
        if mutex:
            kernel32.CloseHandle(mutex)
        return None
    
    # We own the mutex - keep the handle alive for process lifetime
    return mutex


def run_server(config, ai_params):
    """Run the Flask server (used by both tray and terminal modes)"""
    host = web_server.CONFIG.get('host', '127.0.0.1')
    port = int(web_server.CONFIG.get('port', 5000))
    
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
    noisy_loggers = ['werkzeug', 'PIL', 'PIL.PngImagePlugin', 'PIL.Image']
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
                handlers=[RichHandler(
                    console=console,
                    show_time=False,  # Cleaner output
                    show_level=True,
                    show_path=False,  # Reduce noise
                    markup=True,
                    rich_tracebacks=True
                )],
                force=True  # Override any existing configuration
            )
        except ImportError:
            # Fallback to basic config
            logging.basicConfig(
                level=level,
                format="[%(levelname)s] %(name)s: %(message)s",
                force=True
            )
    else:
        # Basic config without Rich
        logging.basicConfig(
            level=level,
            format="[%(levelname)s] %(name)s: %(message)s",
            force=True
        )
    
    logging.debug("Debug logging enabled (--show-console)")


def main():
    """Main entry point"""
    # Parse command line arguments first (doesn't depend on CWD)
    args = parse_args()

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
    
    # Single instance check via named mutex (Windows only)
    # We do this early to prevent multiple instances
    mutex_handle = None
    if sys.platform == 'win32':
        mutex_handle = acquire_single_instance_mutex()
        if mutex_handle is None:
            if args.show_console:
                # If console is visible, we might want to alert
                pass
            
            if HAVE_RICH:
                print_error("Another instance of AIPromptBridge is already running!")
            else:
                print("❌ ERROR: Another instance of AIPromptBridge is already running!")
            
            # If we are in tray mode (hidden console), just exit silently
            # User probably just double clicked the icon again
            if not args.show_console:
                sys.exit(0)

            print("Press Enter to exit...")
            try:
                input()
            except EOFError:
                pass
            sys.exit(1)
            
    # Configure global logging (DEBUG if --show-console, otherwise INFO)
    configure_logging(debug_mode=args.show_console)
    
    # Determine if we have a real console (for WT relaunch and console toggle)
    # - GUI mode: No console (skip WT, no toggle)
    # - Console mode: Has console (WT check, toggle enabled)
    # - No launched-mode + compiled (Internal.exe): No console (attach mode, skip WT)
    # - No launched-mode + source (python main.py): Has console (WT check, toggle enabled)
    is_compiled = _is_compiled()
    
    if args.launched_mode == "gui":
        has_real_console = False
    elif args.launched_mode == "console":
        has_real_console = True
    else:
        # No launcher: compiled (direct Internal.exe) has no console, source does
        has_real_console = not is_compiled
        
    # Suppress Flask startup banner
    import flask.cli
    flask.cli.show_server_banner = lambda *args: None
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create example config if needed (don't use tray mode for first-run config creation)
    if not Path(CONFIG_FILE).exists():
        if HAVE_RICH:
            print_warning(f"Config file '{CONFIG_FILE}' not found.")
            console.print("Creating example configuration file...")
        else:
            print(f"Config file '{CONFIG_FILE}' not found.")
            print("Creating example configuration file...")
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
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
    
    # Initialize (new compact output)
    config, ai_params = initialize()
    
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
            show_settings_window_blocking(initial_tab="API Keys")
            
            # Reload keys after settings window closes
            has_any_keys = any(km.has_keys() for km in web_server.KEY_MANAGERS.values())
            
        if not has_any_keys:
            if HAVE_RICH:
                console.print("[bold yellow]⚠️  WARNING: No API keys configured![/bold yellow]")
                console.print("   Please add your API keys to [cyan]config.ini[/cyan] or use the Settings window.")
                console.print()
            else:
                print("⚠️  WARNING: No API keys configured!")
                print("   Please add your API keys to config.ini or use the Settings window.")
                print()
    
    # ─── Server Info ──────────────────────────────────────────────────────
    host = web_server.CONFIG.get('host', '127.0.0.1')
    configured_port = int(web_server.CONFIG.get('port', 5000))
    
    # Auto-switch port if occupied
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
        try:
            input()
        except EOFError:
            pass
        sys.exit(1)

    if actual_port != configured_port:
        if HAVE_RICH:
            print_warning(f"Port {configured_port} occupied, using {actual_port} instead")
        else:
            print(f"⚠️ Port {configured_port} occupied, using {actual_port} instead")
        
        # Update config in memory (so run_server picks it up)
        web_server.CONFIG['port'] = actual_port
    
    port = actual_port
    
    if HAVE_RICH:
        console.print(f"[bold green]🚀 Server Running[/bold green]: [link=http://{host}:{port}]http://{host}:{port}[/link]")
        if HAVE_GUI:
            console.print(" 🖥️ GUI available (on-demand)")
    else:
        print(f"🚀 Server Running: http://{host}:{port}")
        if HAVE_GUI:
            print(" 🖥️ GUI available (on-demand)")
    
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
    
    if HAVE_RICH:
        console.print()
    else:
        print()
    
    # ─── Tray Mode vs Terminal Mode ───────────────────────────────────────
    use_tray = HAVE_TRAY and sys.platform == 'win32'
    
    if use_tray:
        # Tray mode: hide console by default, run server in background
        if HAVE_RICH:
            console.print("[bold blue]🔲 Starting in tray mode...[/bold blue]")
            console.print("   Right-click tray icon for menu")
            if not args.launched_mode == "gui":
                console.print("   Double-click tray icon to show console")
            console.print()
        else:
            print("🔲 Starting in tray mode...")
            print("   Right-click tray icon for menu")
            if not args.launched_mode == "gui":
                print("   Double-click tray icon to show console")
            print()
        
        # Start terminal session manager
        terminal_thread = threading.Thread(
            target=lambda: terminal_session_manager(),
            daemon=True
        )
        terminal_thread.start()
        
        # Start Flask server in background thread
        server_thread = threading.Thread(
            target=lambda: run_server(config, ai_params),
            daemon=True
        )
        server_thread.start()
        
        # Determine if console toggling is allowed
        # Uses has_real_console computed earlier (handles source vs compiled)
        allow_console_toggle = has_real_console
        
        # Start tray (this blocks until exit)
        # Edit file items only show when --show-console is used
        tray = TrayApp(
            on_exit_callback=cleanup,
            allow_console_toggle=allow_console_toggle,
            show_edit_file_items=args.show_console
        )
        hide_on_start = not args.show_console
        tray.start(hide_console_on_start=hide_on_start)
        
    else:
        # Terminal mode: normal behavior
        if not HAVE_TRAY:
            if HAVE_RICH:
                console.print("[dim]📟 Running in terminal mode (tray not available)[/dim]")
                console.print("   Install with: [cyan]pip install infi.systray[/cyan]")
            else:
                print("📟 Running in terminal mode (tray not available)")
                print("   Install with: pip install infi.systray")
        print()
        
        # Start terminal session manager
        terminal_thread = threading.Thread(
            target=lambda: terminal_session_manager(),
            daemon=True
        )
        terminal_thread.start()
        
        # Run server in main thread
        run_server(config, ai_params)


if __name__ == '__main__':
    main()

