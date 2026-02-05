#!/usr/bin/env python3
"""
AIPromptBridge - AI Desktop Tools & Integration Bridge
Main entry point

Usage:
    python main.py              # Start with tray (console hidden)
    python main.py --no-tray    # Start in terminal mode (no tray)
    python main.py --show-console   # Start with tray + console visible
    python main.py --no-wt      # Skip Windows Terminal auto-detection

Nuitka Configuration:
# nuitka-project: --mode=standalone
# nuitka-project: --windows-icon-from-ico={MAIN_DIRECTORY}/icon.ico
# nuitka-project: --include-data-dir={MAIN_DIRECTORY}/assets=assets
# nuitka-project: --include-data-files={MAIN_DIRECTORY}/icon.ico=icon.ico
# nuitka-project: --enable-plugin=tk-inter
# nuitka-project: --windows-disable-console
# nuitka-project: --nofollow-import-to=pytest,unittest,notebook
# nuitka-project: --include-package-data=customtkinter
# nuitka-project: --include-package-data=emoji
# nuitka-project: --output-filename=AIPromptBridge.exe
# nuitka-project: --noinclude-unittest-mode=nofollow
# nuitka-project: --nofollow-import-to=numpy
# nuitka-project: --nofollow-import-to=pandas
# nuitka-project: --nofollow-import-to=scipy
# nuitka-project: --nofollow-import-to=matplotlib
# nuitka-project: --nofollow-import-to=cv2
# nuitka-project: --nofollow-import-to=xmlrpc
# nuitka-project: --nofollow-import-to=curses
# nuitka-project: --clean-cache=all
"""

import sys
import os
import socket
import logging
import threading
import signal
import argparse
import shutil
import subprocess
from pathlib import Path

from src.console import console, Panel, Table, print_panel, print_success, print_error, print_warning, HAVE_RICH
from src.config import load_config, generate_example_config, CONFIG_FILE, OPENROUTER_URL
from src.version import __version__
from src.key_manager import KeyManager
from src.session_manager import load_sessions, list_sessions
from src.terminal import terminal_session_manager, print_commands_box
from src.gui.core import HAVE_GUI
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


def get_base_url(config, provider):
    """Get the base URL for a provider"""
    if provider == "custom":
        url = config.get("custom_url", "")
        if url:
            # Extract base URL (remove /chat/completions if present)
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
    config, ai_params, endpoints, keys = load_config()
    
    # Set global configuration
    web_server.CONFIG = config
    web_server.AI_PARAMS = ai_params
    web_server.ENDPOINTS = endpoints
    
    # Initialize key managers
    for provider in ["custom", "openrouter", "google"]:
        web_server.KEY_MANAGERS[provider] = KeyManager(keys[provider], provider)
    
    # ─── Configuration Summary ────────────────────────────────────────────
    provider = config.get('default_provider', 'google')
    model = config.get(f'{provider}_model', 'not set')
    base_url = get_base_url(config, provider)
    streaming = config.get('streaming_enabled', True)
    thinking = config.get('thinking_enabled', False)
    
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
    if HAVE_RICH:
        console.print(f"[bold]📂 Sessions[/bold]  {len(sessions)} loaded")
        console.print()
    else:
        print(f"📂 Sessions: {len(sessions)} loaded")
        print()
    
    # Initialize web server (silent)
    web_server.init_web_server(config, ai_params, endpoints, web_server.KEY_MANAGERS)
    
    return config, ai_params, endpoints


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


def cleanup():
    """Cleanup on shutdown"""
    global TEXT_EDIT_TOOL_APP, SNIP_TOOL_APP, AUDIO_TOOL_APP
    
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
  python main.py --no-tray        Start in terminal mode (no tray icon)
  python main.py --show-console   Start with tray and console visible
  python main.py --no-wt          Skip Windows Terminal auto-detection
        """
    )
    parser.add_argument(
        '--no-tray',
        action='store_true',
        help='Run in terminal mode without system tray'
    )
    parser.add_argument(
        '--show-console',
        action='store_true',
        help='Start with console visible (when using tray mode)'
    )
    parser.add_argument(
        '--no-wt',
        action='store_true',
        help='Skip Windows Terminal auto-detection (stay in current console)'
    )
    parser.add_argument(
        '--dummy',
        action='store_true',
        help='Dummy argument (does nothing)'
    )
    return parser.parse_args()


def ensure_windows_terminal() -> bool:
    """
    Check if running in legacy Windows Console and relaunch in Windows Terminal if available.
    
    Windows Terminal provides full color emoji support, while the legacy conhost.exe
    only renders emojis as monochrome outlines.
    
    Returns:
        True if we should exit (because we relaunched in Windows Terminal)
        False to continue in current terminal
    """
    # Only applies to Windows
    if sys.platform != 'win32':
        return False
    
    # Check if already running in Windows Terminal (WT_SESSION env var is set)
    if os.environ.get("WT_SESSION"):
        return False
    
    # Check if Windows Terminal is installed
    wt_path = shutil.which("wt.exe")
    if not wt_path:
        return False
    
    # Prevent infinite relaunch loops
    if os.environ.get("AI_PROMPT_BRIDGE_WT_LAUNCHED"):
        return False
    
    print("🔄 Relaunching in Windows Terminal for full emoji support...")
    
    # Build the command to relaunch
    # Determine script/executable path safely
    if getattr(sys, 'frozen', False):
        script_path = sys.executable
    else:
        script_path = os.path.abspath(__file__)
    
    args = sys.argv[1:]
    
    # Set environment variable to prevent loops
    env = os.environ.copy()
    env["AI_PROMPT_BRIDGE_WT_LAUNCHED"] = "1"
    
    try:
        # Use Windows Terminal to open a new tab with the current script
        # -w 0: target the first window (or create new if none)
        # -d: set working directory
        cmd = [wt_path, "-w", "0", "-d", os.getcwd()]
        
        if script_path.endswith('.py'):
            cmd.extend([sys.executable, script_path] + args)
        else:
            # Frozen executable
            cmd.extend([script_path] + args)
        
        subprocess.Popen(cmd, env=env, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        return True
        
    except Exception as e:
        print(f"⚠️  Failed to relaunch in Windows Terminal: {e}")
        print("   Continuing in legacy console...")
        return False


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


def setup_working_directory():
    """
    Ensure the working directory is set to the application's directory.
    This fixes issues when launching from Windows Search or other contexts
    where the CWD might be System32 or elsewhere.
    """
    try:
        if getattr(sys, 'frozen', False):
            # If frozen (PyInstaller, cx_Freeze, etc.)
            application_path = os.path.dirname(sys.executable)
        else:
            # If running as a script
            application_path = os.path.dirname(os.path.abspath(__file__))

        current_cwd = os.getcwd()
        
        # Log directory diagnosis for debugging
        # print(f"[Debug] Launch CWD: {current_cwd}")
        # print(f"[Debug] App Path:   {application_path}")
        
        if os.path.normpath(current_cwd).lower() != os.path.normpath(application_path).lower():
            # print(f"[Debug] CWD mismatch detected. Switching to App Path...")
            os.chdir(application_path)
            # print(f"[Debug] New CWD:    {os.getcwd()}")
            
    except Exception as e:
        print(f"Warning: Failed to set working directory: {e}")


def run_server(config, ai_params, endpoints):
    """Run the Flask server (used by both tray and terminal modes)"""
    host = web_server.CONFIG.get('host', '127.0.0.1')
    port = int(web_server.CONFIG.get('port', 5000))
    
    try:
        # Run Flask with minimal output
        web_server.app.run(host=host, port=port, use_reloader=False, threaded=True)
    finally:
        cleanup()


def main():
    """Main entry point"""
    # Ensure correct working directory before doing anything else
    setup_working_directory()

    # Parse command line arguments
    args = parse_args()
    
    # Try to relaunch in Windows Terminal for emoji support (unless --no-wt)
    if not args.no_wt and ensure_windows_terminal():
        sys.exit(0)  # Exit this instance, new one launched in WT
    
    # Suppress Flask/werkzeug logging (only show errors)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    
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
    config, ai_params, endpoints = initialize()
    
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
            from src.gui.windows import SettingsWindow
            settings = SettingsWindow()
            settings.show(initial_tab="API Keys")
            
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
    port = int(web_server.CONFIG.get('port', 5000))
    
    # Check if port is available (single instance check)
    if not check_port_available(host, port):
        if HAVE_RICH:
            console.print()
            print_error(f"Port {port} is already in use!")
            console.print()
            print_warning("Another instance of AIPromptBridge may already be running.")
            console.print(f"[dim]Check if port {port} is in use: netstat -an | findstr {port}[/dim]")
            console.print()
            console.print("[dim]Press Enter to exit...[/dim]")
        else:
            print()
            print(f"❌ ERROR: Port {port} is already in use!")
            print()
            print("Another instance of AIPromptBridge may already be running.")
            print(f"Check if port {port} is in use: netstat -an | findstr {port}")
            print()
            print("Press Enter to exit...")
        input()
        sys.exit(1)
    
    # Show endpoint status based on flask_endpoints_enabled
    flask_endpoints_enabled = config.get("flask_endpoints_enabled", False)
    
    if HAVE_RICH:
        if flask_endpoints_enabled:
            console.print(f"[bold green]🚀 API Server Active[/bold green]: [link=http://{host}:{port}]http://{host}:{port}[/link]")
            console.print(f"   📡  {len(endpoints)} endpoints registered")
        else:
            console.print(f"[dim]ℹ️  Internal Server Running locally (API endpoints disabled)[/dim]")
            console.print("   📡  Endpoints disabled (use built-in snipping)")
        if HAVE_GUI:
            console.print("   🖥️  GUI available (on-demand)")
    else:
        if flask_endpoints_enabled:
            print(f"🚀 API Server Active: http://{host}:{port}")
            print(f"   📡  {len(endpoints)} endpoints registered")
        else:
            print("ℹ️ Internal Server Running locally (API endpoints disabled)")
            print("   📡  Endpoints disabled (use built-in snipping)")
        if HAVE_GUI:
            print("   🖥️  GUI available (on-demand)")
    
    # TextEditTool
    text_tool_result = initialize_text_edit_tool(config, ai_params)
    if text_tool_result:
        hotkey = config.get("text_edit_tool_hotkey", "ctrl+space")
    
    # SnipTool
    snip_tool_result = initialize_snip_tool(config, ai_params)
    if snip_tool_result:
        snip_hotkey = config.get("screen_snip_hotkey", "ctrl+shift+x")
    
    # AudioTool
    audio_tool_result = initialize_audio_tool(config, ai_params)
    if audio_tool_result:
        audio_hotkey = config.get("audio_tool_hotkey", "ctrl+shift+a")
    
    if HAVE_RICH:
        console.print()
    else:
        print()
    
    # ─── Tray Mode vs Terminal Mode ───────────────────────────────────────
    use_tray = HAVE_TRAY and not args.no_tray and sys.platform == 'win32'
    
    if use_tray:
        # Tray mode: hide console by default, run server in background
        if HAVE_RICH:
            console.print("[bold blue]🔲 Starting in tray mode...[/bold blue]")
            console.print("   Right-click tray icon for menu")
            console.print("   Double-click tray icon to show console")
            console.print()
        else:
            print("🔲 Starting in tray mode...")
            print("   Right-click tray icon for menu")
            print("   Double-click tray icon to show console")
            print()
        
        # Start terminal session manager
        terminal_thread = threading.Thread(
            target=lambda: terminal_session_manager(endpoints),
            daemon=True
        )
        terminal_thread.start()
        
        # Start Flask server in background thread
        server_thread = threading.Thread(
            target=lambda: run_server(config, ai_params, endpoints),
            daemon=True
        )
        server_thread.start()
        
        # Start tray (this blocks until exit)
        tray = TrayApp(on_exit_callback=cleanup)
        hide_on_start = not args.show_console
        tray.start(hide_console_on_start=hide_on_start)
        
    else:
        # Terminal mode: normal behavior
        if args.no_tray:
            if HAVE_RICH:
                console.print("[dim]📟 Running in terminal mode (--no-tray)[/dim]")
            else:
                print("📟 Running in terminal mode (--no-tray)")
        elif not HAVE_TRAY:
            if HAVE_RICH:
                console.print("[dim]📟 Running in terminal mode (tray not available)[/dim]")
                console.print("   Install with: [cyan]pip install infi.systray[/cyan]")
            else:
                print("📟 Running in terminal mode (tray not available)")
                print("   Install with: pip install infi.systray")
        print()
        
        # Start terminal session manager
        terminal_thread = threading.Thread(
            target=lambda: terminal_session_manager(endpoints),
            daemon=True
        )
        terminal_thread.start()
        
        # Run server in main thread
        run_server(config, ai_params, endpoints)


if __name__ == '__main__':
    main()

