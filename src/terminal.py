#!/usr/bin/env python3
"""
Terminal interactive session manager with enhanced console UI
"""

import sys
import time

from .session_manager import (
    list_sessions, get_session, delete_session, save_sessions,
    CHAT_SESSIONS, SESSION_LOCK, clear_all_sessions
)
from .gui.core import show_session_browser, get_gui_status, HAVE_GUI
from .config import OPENROUTER_URL
from .console import console, Panel, Table, print_panel, print_success, print_error, print_warning, print_info, HAVE_RICH
from rich.align import Align
from rich.columns import Columns
from rich.text import Text


def get_base_url_for_status(config, provider):
    """Get the base URL for a provider (for status display)"""
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
        url = config.get("gemini_endpoint") or "generativelanguage.googleapis.com"
        if "://" in url:
            url = url.split("://")[-1]
        if "/v1beta" in url:
            url = url.split("/v1beta")[0]
        return url
    return "Unknown"


def print_commands_box():
    """Print the terminal commands box"""
    if HAVE_RICH:
        from rich.table import Table
        from rich.panel import Panel
        from rich.layout import Layout
        from rich.align import Align
        
        # Create a grid for the content - do NOT expand, keep it compact
        grid = Table.grid(expand=False, padding=(0, 4))
        
        # Helper to create sub-tables for columns with explicit emoji separation
        def create_column_table(items):
            t = Table.grid(padding=(0, 1))
            # Col 1: Key (e.g. [L]) - Fixed width
            t.add_column(style="bold cyan", width=4, justify="right")
            # Col 2: Icon (Emoji) - Fixed width sufficient for 2-cell emojis
            t.add_column(width=3, justify="center")
            # Col 3: Description - Left aligned
            t.add_column(style="white")
            
            for key, icon, desc in items:
                if key:
                    t.add_row(f"[{key}]", icon, desc)
                else:
                    t.add_row("", "", "")
            return t

        # Column 1: Features
        col1 = create_column_table([
            ("S", "🌐", "Sessions"),
            ("A", "🎤", "Audio"),
            ("T", "🔊", "TTS"),
            ("X", "🧰", "Tools"),
        ])
        
        # Column 2: Configuration
        col2 = create_column_table([
            ("P", "🔄", "Provider"),
            ("M", "🤖", "Models"),
            ("G", "🔨", "Settings"),
            ("W", "📝", "Prompts"),
        ])
        
        # Column 3: Info & Toggles
        col3 = create_column_table([
            ("I", "📊", "Info"),
            ("K", "💭", "Thinking"),
            ("R", "🌊", "Streaming"),
            ("H", "❓", "Help"),
        ])
        
        grid.add_row(col1, col2, col3)
        
        # Use Panel.fit to wrap tightly around the grid, and Align.center to place it in the middle
        console.print(Align.center(Panel.fit(
            grid,
            title="[bold blue] COMMANDS [/bold blue]",
            subtitle="[dim] Ctrl+C to stop [/dim]",
            border_style="blue",
            padding=(0, 2),
        )))
        console.print()
    else:
        print("─" * 64)
        print("  COMMANDS                                       Ctrl+C to stop")
        print("─" * 64)
        print("  [S] 🌐 Sessions      [P] 🔄 Provider     [I] 📊 Info")
        print("  [A] 🎤 Audio         [M] 🤖 Models       [K] 💭 Thinking")
        print("  [T] 🔊 TTS           [G] 🔨 Settings     [R] 🌊 Streaming")
        print("  [X] 🧰 Tools         [W] 📝 Prompts      [H] ❓ Help")
        print("─" * 64)
        print()


def terminal_session_manager(endpoints=None):
    """Interactive terminal session manager"""
    # Print the commands box
    print_commands_box()
    
    def get_input_nonblocking():
        """Get keyboard input without blocking"""
        if sys.platform == 'win32':
            import msvcrt
            if msvcrt.kbhit():
                return msvcrt.getch().decode('utf-8', errors='ignore').lower()
            return None
        else:
            import select
            import tty
            import termios
            old_settings = None
            try:
                old_settings = termios.tcgetattr(sys.stdin)
                tty.setcbreak(sys.stdin.fileno())
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    return sys.stdin.read(1).lower()
            except:
                pass
            finally:
                if old_settings:
                    try:
                        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                    except:
                        pass
            return None
    
    # Store endpoints reference
    _endpoints = endpoints or {}
    
    while True:
        try:
            key = get_input_nonblocking()
            
            if key == 'l':
                sessions = list_sessions()
                print(f"\n{'─'*64}")
                print(f"📋 SESSIONS ({len(sessions)} total)")
                print(f"{'─'*64}")
                if not sessions:
                    print("   (No sessions)")
                else:
                    for i, s in enumerate(sessions):
                        print(f"   [{s['id']}] {s['title'][:35]} ({s['messages']} msgs, {s['origin']})")
                print(f"{'─'*64}\n")

            elif key == 't':
                # Open TTS Window
                if HAVE_GUI:
                    from . import web_server
                    from .gui.core import GUICoordinator
                    
                    if HAVE_RICH:
                        console.print("\n[bold]🔊  Opening TTS Window...[/bold]\n")
                    else:
                        print("\n🔊  Opening TTS Window...\n")
                        
                    GUICoordinator.get_instance().request_tts_window(
                        web_server.CONFIG,
                        web_server.AI_PARAMS,
                        web_server.KEY_MANAGERS,
                        initial_text=""
                    )
                else:
                    if HAVE_RICH:
                        console.print("\n[red]✗ GUI not available[/red]\n")
                    else:
                        print("\n✗ GUI not available\n")
            
            elif key == 's':
                if HAVE_GUI:
                    if HAVE_RICH:
                        console.print("\n[bold]🌐  Opening session browser...[/bold]\n")
                    else:
                        print("\n🖥️  Opening session browser...\n")
                    show_session_browser()
                else:
                    if HAVE_RICH:
                        console.print("\n[red]✗ GUI not available[/red]\n")
                    else:
                        print("\n✗ GUI not available\n")
            
            elif key == 'a':
                # Open Audio Analyzer
                from .gui.audio_tool import get_instance
                app = get_instance()
                
                if app:
                    if HAVE_RICH:
                        console.print("\n[bold]🎤  Opening Audio Analyzer...[/bold]\n")
                    else:
                        print("\n🎤  Opening Audio Analyzer...\n")
                    # Directly trigger the window opening logic
                    app._on_hotkey_pressed()
                else:
                    if HAVE_RICH:
                        console.print("\n[red]✗ Audio Tool not initialized[/red]\n")
                    else:
                        print("\n✗ Audio Tool not initialized\n")
            
            elif key == 'e':
                # List endpoints
                if HAVE_RICH:
                    table = Table(title=f"📡 Endpoints ({len(_endpoints)} registered)", box=None)
                    table.add_column("Path", style="bold green")
                    table.add_column("System Prompt Preview", style="dim")
                    
                    if not _endpoints:
                        console.print(Panel("No endpoints registered", style="yellow"))
                    else:
                        for name, prompt in _endpoints.items():
                            preview = prompt[:60] + "..." if len(prompt) > 60 else prompt
                            table.add_row(f"/{name}", preview)
                        console.print(table)
                        console.print()
                else:
                    print(f"\n{'─'*64}")
                    print(f"📡 ENDPOINTS ({len(_endpoints)} registered)")
                    print(f"{'─'*64}")
                    if not _endpoints:
                        print("   (No endpoints)")
                    else:
                        for name, prompt in _endpoints.items():
                            preview = prompt[:50] + "..." if len(prompt) > 50 else prompt
                            print(f"   /{name}")
                            print(f"      → {preview}")
                    print(f"{'─'*64}\n")

            elif key == 'm':
                # Model management with two-tier display
                from . import web_server
                from .api_client import fetch_models
                from .config import save_config_value
                
                if HAVE_RICH:
                    console.print("[bold]🤖 Model Management[/bold]")
                
                provider = web_server.CONFIG.get("default_provider", "custom")
                current_model = web_server.CONFIG.get(f"{provider}_model", "not set")
                
                if HAVE_RICH:
                    console.print(f"   Provider: [cyan]{provider}[/cyan]")
                    console.print(f"   Current:  [green]{current_model}[/green]")
                    with console.status("[bold blue]Fetching available models...[/bold blue]"):
                        models, error = fetch_models(web_server.CONFIG, web_server.KEY_MANAGERS)
                else:
                    print(f"\n{'─'*64}")
                    print("🤖 MODEL MANAGEMENT")
                    print(f"{'─'*64}")
                    print(f"   Provider: {provider}")
                    print(f"   Current:  {current_model}")
                    print(f"\n   Fetching available models...")
                    models, error = fetch_models(web_server.CONFIG, web_server.KEY_MANAGERS)
                
                if error:
                    if HAVE_RICH:
                        print_error(error)
                    else:
                        print(f"   ✗ {error}")
                elif models:
                    # Helper function to format context length
                    def format_context(ctx):
                        if ctx is None:
                            return "?"
                        if ctx >= 1000000:
                            return f"{ctx // 1000000}M"
                        elif ctx >= 1000:
                            return f"{ctx // 1000}k"
                        return str(ctx)
                    
                    # Helper function to format pricing
                    def format_price_list(m):
                        pricing = m.get('pricing')
                        if not pricing:
                            return ""
                        try:
                            prompt = float(pricing.get('prompt', 0))
                            completion = float(pricing.get('completion', 0))
                            
                            if prompt < 0: return "[dim]Router[/dim]"
                            if prompt == 0 and completion == 0: return "[bold green]Free[/bold green]"
                            
                            # Format as price per 1M tokens
                            p_val = prompt * 1000000
                            c_val = completion * 1000000
                            
                            def fmt(v):
                                if v == 0: return "0"
                                if v < 0.01: return "<.01"
                                return f"{v:.2f}"
                                
                            return f"${fmt(p_val)}/${fmt(c_val)}"
                        except:
                            return ""

                    if HAVE_RICH:
                        table = Table(show_header=True, box=None)
                        table.add_column("#", style="dim", justify="right", width=4)
                        table.add_column("Model ID", style="bold", min_width=30)
                        table.add_column("Context", style="cyan", justify="right", width=8)
                        table.add_column("1M (In/Out)", style="yellow", justify="right", width=14)
                        table.add_column("🧠", justify="center", width=3)
                        
                        for i, m in enumerate(models):
                            marker = " [bold green]◄[/bold green]" if m['id'] == current_model else ""
                            ctx = format_context(m.get('context_length'))
                            thinking = "[green]✓[/green]" if m.get('thinking') else ""
                            price = format_price_list(m)
                            table.add_row(str(i+1), f"{m['id']}{marker}", ctx, price, thinking)
                        
                        console.print(table)
                        console.print("\n   [dim]Enter number, model name, or ?N for details (q = cancel):[/dim] ", end="")
                    else:
                        print(f"\n   Available ({len(models)}):")
                        print(f"   {'#':>3}  {'Model ID':<35} {'Context':>8} {'1M (In/Out)':>14} 🧠")
                        print(f"   {'-'*3}  {'-'*35} {'-'*8} {'-'*14} --")
                        for i, m in enumerate(models):
                            marker = " ◄" if m['id'] == current_model else ""
                            ctx = format_context(m.get('context_length'))
                            thinking = "✓" if m.get('thinking') else ""
                            # Simple pricing for fallback
                            pricing = m.get('pricing')
                            price_str = ""
                            if pricing:
                                try:
                                    p = float(pricing.get('prompt', 0))
                                    c = float(pricing.get('completion', 0))
                                    if p == 0 and c == 0:
                                        price_str = "Free"
                                    else:
                                        price_str = f"${p*1000000:.1f}/${c*1000000:.1f}"
                                except: pass
                            print(f"   {i+1:>3}  {m['id']:<35}{marker} {ctx:>8} {price_str:>14} {thinking}")
                        
                        print("\n   Enter number, model name, or ?N for details (q = cancel): ", end='', flush=True)
                    
                    try:
                        choice = input().strip()
                        
                        # Handle model details request (?N syntax)
                        if choice.startswith('?'):
                            detail_choice = choice[1:].strip()
                            try:
                                detail_idx = int(detail_choice) - 1
                                if 0 <= detail_idx < len(models):
                                    _show_model_details(models[detail_idx])
                                else:
                                    print(f"   ✗ Invalid model number: {detail_choice}")
                            except ValueError:
                                # Try to find by name
                                found = False
                                for m in models:
                                    if m['id'].lower() == detail_choice.lower():
                                        _show_model_details(m)
                                        found = True
                                        break
                                if not found:
                                    print(f"   ✗ Model not found: {detail_choice}")
                        elif choice.lower() != 'q' and choice:
                            try:
                                idx = int(choice) - 1
                                if 0 <= idx < len(models):
                                    new_model = models[idx]['id']
                                else:
                                    new_model = choice
                            except ValueError:
                                new_model = choice
                            
                            config_key = f"{provider}_model"
                            if save_config_value(config_key, new_model):
                                web_server.CONFIG[config_key] = new_model
                                print(f"   ✅ Model: {new_model}")
                            else:
                                print(f"   ✗ Failed to save")
                    except:
                        pass
                else:
                    print("   No models available")
                print(f"{'─'*64}\n")
            
            elif key == 'p':
                # Provider management
                from . import web_server
                from .config import save_config_value
                
                print(f"\n{'─'*64}")
                print("🔄 PROVIDER")
                print(f"{'─'*64}")
                current_provider = web_server.CONFIG.get("default_provider", "google")
                base_url = get_base_url_for_status(web_server.CONFIG, current_provider)
                print(f"   Current: {current_provider} → {base_url}")
                print()
                
                # List available providers
                available = []
                for p, km in web_server.KEY_MANAGERS.items():
                    key_count = km.get_key_count()
                    key_icon = "✅" if key_count > 0 else "✗"
                    key_info = f"({key_count})" if key_count > 0 else "(no keys)"
                    available.append((p, key_count))
                    marker = " ◄" if p == current_provider else ""
                    print(f"      [{len(available)}] {key_icon} {p} {key_info}{marker}")
                
                print("\n   Enter number or name (q = cancel): ", end='', flush=True)
                try:
                    choice = input().strip()
                    if choice.lower() != 'q' and choice:
                        try:
                            idx = int(choice) - 1
                            if 0 <= idx < len(available):
                                new_provider = available[idx][0]
                            else:
                                new_provider = choice.lower()
                        except ValueError:
                            new_provider = choice.lower()
                        
                        if new_provider in web_server.KEY_MANAGERS:
                            if save_config_value("default_provider", new_provider):
                                web_server.CONFIG["default_provider"] = new_provider
                                new_base = get_base_url_for_status(web_server.CONFIG, new_provider)
                                model = web_server.CONFIG.get(f"{new_provider}_model", "not set")
                                print(f"   ✅ {new_provider} → {new_base}")
                                print(f"     Model: {model}")
                            else:
                                print(f"   ✗ Failed to save")
                        else:
                            print(f"   ✗ Unknown: {new_provider}")
                except:
                    pass
                print(f"{'─'*64}\n")
            
            elif key == 'i':
                # Info command - enhanced with base_url
                from . import web_server
                
                provider = web_server.CONFIG.get("default_provider", "google")
                model = web_server.CONFIG.get(f"{provider}_model", "not set")
                base_url = get_base_url_for_status(web_server.CONFIG, provider)
                streaming = web_server.CONFIG.get("streaming_enabled", True)
                thinking = web_server.CONFIG.get("thinking_enabled", False)
                
                if HAVE_RICH:
                    grid = Table.grid(expand=True, padding=(0, 2))
                    grid.add_column(justify="left")
                    grid.add_column(justify="left")
                    
                    # Provider Info
                    grid.add_row("[bold]📡 Provider[/bold]", f"[cyan]{provider}[/cyan]")
                    grid.add_row("[dim]   Base URL[/dim]", f"[dim]{base_url}[/dim]")
                    grid.add_row("[bold]🤖 Model[/bold]", f"[green]{model}[/green]")
                    
                    # Settings
                    stream_icon = "[green]ON[/green]" if streaming else "[red]OFF[/red]"
                    think_icon = "[green]ON[/green]" if thinking else "[red]OFF[/red]"
                    grid.add_row("[bold]🌊 Streaming[/bold]", stream_icon)
                    grid.add_row("[bold]💭 Thinking[/bold]", think_icon)
                    
                    if thinking:
                        thinking_output = web_server.CONFIG.get("thinking_output", "reasoning_content")
                        grid.add_row("[dim]   Output[/dim]", thinking_output)
                    
                    # Server
                    host = web_server.CONFIG.get("host", "127.0.0.1")
                    port = web_server.CONFIG.get("port", 5000)
                    grid.add_row("[bold]🚀 Server[/bold]", f"[link=http://{host}:{port}]http://{host}:{port}[/link]")
                    
                    # Keys
                    key_status = []
                    for p, km in web_server.KEY_MANAGERS.items():
                        count = km.get_key_count()
                        color = "green" if count > 0 else "red"
                        active = " [bold]◄[/bold]" if p == provider else ""
                        key_status.append(f"[{color}]{p}: {count}[/{color}]{active}")
                    
                    grid.add_row("[bold]🔑 API Keys[/bold]", ", ".join(key_status))
                    
                    console.print(Panel(grid, title="[bold]System Info[/bold]", border_style="blue"))
                    console.print()
                else:
                    print(f"\n{'─'*64}")
                    print("📊 INFO")
                    print(f"{'─'*64}")
                    print(f"   📡 Provider:  {provider}")
                    print(f"      Base URL:  {base_url}")
                    print(f"   🤖 Model:     {model}")
                    stream_status = "✅ ON" if streaming else "✗ OFF"
                    think_status = "✅ ON" if thinking else "✗ OFF"
                    print(f"\n   🌊 Streaming: {stream_status}")
                    print(f"   💭 Thinking:  {think_status}")
                    host = web_server.CONFIG.get("host", "127.0.0.1")
                    port = web_server.CONFIG.get("port", 5000)
                    print(f"\n   🚀 Server:    http://{host}:{port}")
                    print(f"\n   🔑 API Keys:")
                    for p, km in web_server.KEY_MANAGERS.items():
                        count = km.get_key_count()
                        print(f"      {p}: {count}")
                    print(f"{'─'*64}\n")
            
            elif key == 'k':
                # Toggle thinking mode
                from . import web_server
                from .config import save_config_value
                
                current = web_server.CONFIG.get("thinking_enabled", False)
                new_value = not current
                
                if save_config_value("thinking_enabled", new_value):
                    web_server.CONFIG["thinking_enabled"] = new_value
                    if HAVE_RICH:
                        status = "[green]ON[/green]" if new_value else "[red]OFF[/red]"
                        console.print(f"\n💭 Thinking: {status}")
                    else:
                        status = "✅ ON" if new_value else "✗ OFF"
                        print(f"\n💭 Thinking: {status}")
                else:
                    if HAVE_RICH:
                        print_error("Failed to toggle thinking")
                    else:
                        print("\n✗ Failed to toggle thinking")
                if HAVE_RICH: console.print()
                else: print()
            
            elif key == 'r':
                # Toggle streaming mode
                from . import web_server
                from .config import save_config_value
                
                current = web_server.CONFIG.get("streaming_enabled", True)
                new_value = not current
                
                if save_config_value("streaming_enabled", new_value):
                    web_server.CONFIG["streaming_enabled"] = new_value
                    if HAVE_RICH:
                        status = "[green]ON[/green]" if new_value else "[red]OFF[/red]"
                        console.print(f"\n🌊 Streaming: {status}\n")
                    else:
                        status = "✅ ON" if new_value else "✗ OFF"
                        print(f"\n🌊 Streaming: {status}\n")
                else:
                    if HAVE_RICH:
                        print_error("Failed to toggle streaming")
                    else:
                        print("\n✗ Failed to toggle streaming\n")
            
            elif key == 'v':
                if HAVE_RICH:
                    console.print("\n[bold]Enter session ID: [/bold]", end="")
                else:
                    print("\nEnter session ID: ", end='', flush=True)
                try:
                    session_id = input().strip()
                    session = get_session(session_id)
                    if session:
                        if HAVE_RICH:
                            console.print(Panel(
                                f"[bold]Title:[/bold] {session.title}\n"
                                f"[dim]Origin:[/dim] {session.origin}\n"
                                f"[dim]Created:[/dim] {session.created_at}",
                                title=f"📋 Session: {session.session_id}"
                            ))
                            for msg in session.messages:
                                role_style = "green" if msg["role"] == "user" else "blue"
                                role_name = "User" if msg["role"] == "user" else "AI"
                                content = msg['content'][:500] + ('...' if len(msg['content']) > 500 else '')
                                console.print(Panel(content, title=f"[{role_style}]{role_name}[/{role_style}]", border_style=role_style))
                        else:
                            print(f"\n{'─'*64}")
                            print(f"📋 SESSION: {session.session_id}")
                            print(f"{'─'*64}")
                            print(f"   Title:    {session.title}")
                            print(f"   Origin: {session.origin}")
                            print(f"   Created:  {session.created_at}")
                            print(f"{'─'*64}")
                            for msg in session.messages:
                                role_icon = "👤" if msg["role"] == "user" else "🤖"
                                role = "USER" if msg["role"] == "user" else "AI"
                                print(f"\n{role_icon} [{role}]")
                                print(msg['content'][:500] + ('...' if len(msg['content']) > 500 else ''))
                            print(f"{'─'*64}\n")
                        
                        if HAVE_GUI:
                            open_gui = input("Open in GUI? [y/N]: ").strip().lower()
                            if open_gui == 'y':
                                from .gui.core import show_chat_gui
                                show_chat_gui(session)
                    else:
                        print(f"✗ Session '{session_id}' not found.\n")
                except:
                    pass
            
            elif key == 'd':
                print("\nEnter session ID to delete: ", end='', flush=True)
                try:
                    session_id = input().strip()
                    if get_session(session_id):
                        confirm = input(f"Delete {session_id}? [y/N]: ").strip().lower()
                        if confirm == 'y':
                            if delete_session(session_id):
                                save_sessions()
                                print(f"✅ Session {session_id} deleted.\n")
                    else:
                        print(f"✗ Session '{session_id}' not found.\n")
                except:
                    pass
            
            elif key == 'c':
                try:
                    confirm = input("\n⚠️  Clear ALL sessions? [y/N]: ").strip().lower()
                    if confirm == 'y':
                        clear_all_sessions()
                        save_sessions()
                        print("✅ All sessions cleared.\n")
                except:
                    pass
            
            elif key == 'g':
                # Open Settings window
                if HAVE_GUI:
                    if HAVE_RICH:
                        console.print("\n[bold]🔨  Opening settings...[/bold]\n")
                    else:
                        print("\n⚙️  Opening settings...\n")
                    from .gui.core import show_settings_window
                    show_settings_window()
                else:
                    if HAVE_RICH:
                        console.print("\n[red]✗ GUI not available[/red]\n")
                    else:
                        print("\n✗ GUI not available\n")
            
            elif key == 'w':
                # Open Prompt Editor window
                if HAVE_GUI:
                    if HAVE_RICH:
                        console.print("\n[bold]📝  Opening prompt editor...[/bold]\n")
                    else:
                        print("\n📝  Opening prompt editor...\n")
                    from .gui.core import show_prompt_editor
                    show_prompt_editor()
                else:
                    if HAVE_RICH:
                        console.print("\n[red]✗ GUI not available[/red]\n")
                    else:
                        print("\n✗ GUI not available\n")
            
            elif key == 'x':
                # Open Tools menu
                try:
                    from .tools.file_processor import show_tools_menu
                except Exception as import_err:
                    # Handle import errors (e.g., atexit during shutdown)
                    error_msg = str(import_err)
                    if "atexit" in error_msg.lower():
                        # Retry once if atexit error occurred during import
                        try:
                            from .tools.file_processor import show_tools_menu
                        except Exception:
                            if HAVE_RICH:
                                print_error("\nFailed to open Tools menu. Please try again.")
                            else:
                                print("\n✗ Failed to open Tools menu. Please try again.")
                            continue
                    else:
                        raise
                if HAVE_RICH:
                    console.print("\n[bold]🧰  Opening Tools menu...[/bold]\n")
                else:
                    print("\n🧰  Opening Tools menu...\n")
                show_tools_menu(_endpoints)
                # Reprint commands box after returning
                print()
                print_commands_box()
            
            elif key == 'h':
                print(f"\n{'─'*64}")
                print("❓ HELP")
                print(f"{'─'*64}")
                print("   Feature Commands:")
                print("   [S] 🌐 Sessions      Open session browser GUI")
                print("   [A] 🎤 Audio         Open Audio Analyzer")
                print("   [T] 🔊 TTS           Open Text-to-Speech window")
                print("   [X] 🧰 Tools         Open tools menu")
                print("\n   Session Management:")
                print("   [L] 📋 List          List recent saved sessions")
                print("   [V] 👁️ View          View a session by ID")
                print("   [D] 🗑️ Delete        Delete a session by ID")
                print("   [C] 🧹 Clear         Clear all sessions")
                print("\n   Configuration:")
                print("   [P] 🔄 Provider      Switch API provider")
                print("   [M] 🤖 Models        List/set models from API")
                print("   [G] 🔨 Settings      Open settings window")
                print("   [W] 📝 Prompts       Open prompt editor")
                print("\n   Info & Toggles:")
                print("   [I] 📊 Info          Show current configuration")
                print("   [K] 💭 Thinking      Toggle thinking mode")
                print("   [R] 🌊 Streaming     Toggle streaming")
                print("   [E] 📡 Endpoints     List registered endpoints")
                print("   [H] ❓ Help          Show this help")
                print(f"{'─'*64}\n")
            
            time.sleep(0.1)
        
        except Exception as e:
            # Suppress atexit errors during shutdown
            error_msg = str(e)
            if "atexit" in error_msg.lower() and "shutdown" in error_msg.lower():
                pass  # Ignore atexit errors during interpreter shutdown
            else:
                print(f"[Terminal Error] {e}")
            time.sleep(1)


def _show_model_details(model: dict):
    """
    Display detailed information about a model (Tier 2).
    Shows all available metadata including unknown/future fields.
    """
    # Helper to format numbers/money with optional rich tags
    def fmt_num(n, rich=True):
        if n is None or n == "" or n == "N/A":
            return "[dim]Unknown[/dim]" if rich else "Unknown"
        try:
            return f"{int(n):,}"
        except: return str(n)
            
    def fmt_money(val, rich=True):
        if val is None or val == "": return "[dim]N/A[/dim]" if rich else "N/A"
        try:
            fval = float(val)
            if fval < 0: return "[dim]Variable[/dim]" if rich else "Variable"
            if fval == 0: return "[bold green]Free[/bold green]" if rich else "Free"
            # Show price per 1M tokens
            per_million = fval * 1000000
            return (f"${per_million:,.2f}" + (" [dim]per 1M[/dim]" if rich else " per 1M"))
        except: return str(val)

    if HAVE_RICH:
        console.print(f"\n{'─'*64}")
        console.print("[bold]📋 MODEL DETAILS[/bold]")
        console.print(f"{'─'*64}")
        
        # Core info
        console.print(f"   [bold]Name:[/bold]        {model.get('name', model.get('id', 'Unknown'))}")
        console.print(f"   [bold]ID:[/bold]          [cyan]{model.get('id', 'Unknown')}[/cyan]")
        if model.get('owned_by'):
             console.print(f"   [bold]Provider:[/bold]    [yellow]{model.get('owned_by')}[/yellow]")
        if model.get('version'):
            console.print(f"   [bold]Version:[/bold]     {model.get('version')}")
        
        if model.get('description'):
            desc = model.get('description', '')
            if len(desc) > 60:
                console.print(f"   [bold]Description:[/bold]")
                words = desc.split()
                line = "                "
                for word in words:
                    if len(line) + len(word) + 1 > 70:
                        console.print(f"   [dim]{line}[/dim]")
                        line = "                " + word
                    else: line += " " + word if line.strip() else word
                if line.strip(): console.print(f"   [dim]{line}[/dim]")
            else: console.print(f"   [bold]Description:[/bold] [dim]{desc}[/dim]")
        
        console.print()
        
        # Performance & Limits
        ctx = model.get('context_length') or model.get('input_token_limit')
        out_limit = model.get('output_token_limit')
        console.print(f"   [bold]Context:[/bold]     {fmt_num(ctx)} tokens (input)")
        console.print(f"   [bold]Max Output:[/bold]  {fmt_num(out_limit)} tokens")
        
        thinking = model.get('thinking', False)
        think_str = "[green]✅ Supported[/green]" if thinking else "[dim]Not supported[/dim]"
        console.print(f"   [bold]Thinking:[/bold]    {think_str}")
        
        # Pricing
        pricing = model.get('pricing')
        if pricing:
            console.print("\n   [bold]Pricing:[/bold]")
            console.print(f"      Prompt:     {fmt_money(pricing.get('prompt'))}")
            console.print(f"      Completion: {fmt_money(pricing.get('completion'))}")

        # Architecture
        arch = model.get('architecture')
        if arch:
            console.print("\n   [bold]Architecture:[/bold]")
            
            # Use specific modality lists for better accuracy (shows audio/video/etc)
            inputs = arch.get('input_modalities')
            outputs = arch.get('output_modalities')
            
            if inputs:
                console.print(f"      Input Mod.: [dim]{', '.join(inputs)}[/dim]")
            if outputs:
                console.print(f"      Output Mod.:[dim]{', '.join(outputs)}[/dim]")
            
            # Fallback to summary string if lists are missing
            if not inputs and arch.get('modality'):
                console.print(f"      Modality:   [dim]{arch.get('modality')}[/dim]")
                
            if arch.get('tokenizer'):
                console.print(f"      Tokenizer:  [dim]{arch.get('tokenizer')}[/dim]")

        console.print()
        
        # Generation defaults
        if any(model.get(k) is not None for k in ['temperature', 'top_p', 'top_k', 'max_temperature']):
            console.print("   [bold]Defaults:[/bold]")
            if model.get('temperature') is not None: console.print(f"      Temp:      {model.get('temperature')}")
            if model.get('max_temperature') is not None: console.print(f"      Max Temp:  {model.get('max_temperature')}")
            if model.get('top_p') is not None: console.print(f"      Top P:     {model.get('top_p')}")
            if model.get('top_k') is not None: console.print(f"      Top K:     {model.get('top_k')}")
            console.print()
        
        methods = model.get('supported_methods', [])
        if methods: console.print(f"   [bold]Methods:[/bold]     {', '.join(methods)}")
        
        # Show any unknown/future fields from _raw
        raw = model.get('_raw', {})
        if raw:
            excluded = {
                'name', 'displayName', 'description', 'version', 'id', 'owned_by',
                'inputTokenLimit', 'outputTokenLimit', 'thinking', 'pricing', 'architecture',
                'supportedGenerationMethods', 'temperature', 'topP', 'topK', 'maxTemperature',
                'context_length', 'input_token_limit', 'output_token_limit', 'supported_methods',
                'supported_parameters', 'input_modalities', 'output_modalities'
            }
            extra_fields = {k: v for k, v in raw.items() if k not in excluded and v is not None}
            
            if extra_fields:
                console.print("\n   [bold]Additional Information:[/bold]")
                for key, value in extra_fields.items():
                    val_str = str(value)[:50] + ("..." if len(str(value)) > 50 else "")
                    console.print(f"      {key}: [dim]{val_str}[/dim]")
        
        console.print(f"{'─'*64}\n")
    else:
        # Plain text fallback
        print(f"\n{'─'*64}\n📋 MODEL DETAILS\n{'─'*64}")
        print(f"   Name:        {model.get('name', 'Unknown')}")
        print(f"   ID:          {model.get('id', 'Unknown')}")
        print(f"   Context:     {fmt_num(model.get('context_length'), False)} tokens")
        
        pricing = model.get('pricing')
        if pricing:
            print(f"   Pricing:     {fmt_money(pricing.get('prompt'), False)} (Prompt)")
            
        if model.get('description'):
            desc = model.get('description', '')
            print(f"   Description: {desc[:60]}...")
            
        raw = model.get('_raw', {})
        if raw:
            print("\n   Additional Fields:")
            for k, v in raw.items():
                if k not in ['id', 'name', 'description', 'pricing']:
                    print(f"      {k}: {str(v)[:50]}")
        print(f"{'─'*64}\n")


def print_usage(usage_data, prefix=""):
    """Print token usage information to console"""
    if not usage_data:
        return
    
    input_tokens = usage_data.get("prompt_tokens", 0)
    output_tokens = usage_data.get("completion_tokens", 0)
    total_tokens = usage_data.get("total_tokens", input_tokens + output_tokens)
    estimated = usage_data.get("estimated", False)
    
    est_mark = " (est)" if estimated else ""
    
    if HAVE_RICH:
        console.print(f"{prefix}[dim]📊 Tokens: [bold green]{input_tokens}[/bold green] in | [bold blue]{output_tokens}[/bold blue] out | [bold white]{total_tokens}[/bold white] total{est_mark}[/dim]")
    else:
        print(f"{prefix}📊 Tokens: {input_tokens} in | {output_tokens} out | {total_tokens} total{est_mark}")

