#!/usr/bin/env python3
"""
System Tray implementation for AIPromptBridge
Uses infi.systray for Windows with native .ico support (no Pillow needed)
"""

import os
import sys
import shutil
import subprocess
import ctypes
from pathlib import Path
import threading

# Try to import infi.systray
HAVE_SYSTRAY = False
SysTrayIcon = None
try:
    from infi.systray import SysTrayIcon
    from infi.systray.win32_adapter import (
        MENUITEMINFO,
        PackMENUITEMINFO,
        InsertMenuItem,
        CreatePopupMenu,
        ctypes
    )
    # Define constants missing from win32_adapter
    MFT_SEPARATOR = 0x00000800
    MIIM_FTYPE = 0x00000100

    class CustomSysTrayIcon(SysTrayIcon):
        """Custom SysTrayIcon that supports separators"""
        def _create_menu(self, menu, menu_options):
            for option_text, option_icon, option_action, option_id in menu_options[::-1]:
                # Check for separator
                if option_text == "---":
                    item = MENUITEMINFO()
                    item.cbSize = ctypes.sizeof(item)
                    item.fMask = MIIM_FTYPE
                    item.fType = MFT_SEPARATOR
                    InsertMenuItem(menu, 0, 1, ctypes.byref(item))
                    continue
                
                if option_icon:
                    option_icon = self._prep_menu_icon(option_icon)

                if option_id in self._menu_actions_by_id:
                    item = PackMENUITEMINFO(text=option_text,
                                            hbmpItem=option_icon,
                                            wID=option_id)
                    InsertMenuItem(menu, 0, 1, ctypes.byref(item))
                else:
                    submenu = CreatePopupMenu()
                    self._create_menu(submenu, option_action)
                    item = PackMENUITEMINFO(text=option_text,
                                            hbmpItem=option_icon,
                                            hSubMenu=submenu)
                    InsertMenuItem(menu, 0, 1,  ctypes.byref(item))

    # Use our custom class instead
    SysTrayIcon = CustomSysTrayIcon
    HAVE_SYSTRAY = True
except ImportError:
    pass


# ─── Console Window Control (Windows) ─────────────────────────────────────────

from ctypes import wintypes

# Define structures for Toolhelp32
TH32CS_SNAPPROCESS = 0x00000002

# Cache for Windows Terminal window handle
_cached_wt_hwnd = None
_cached_wt_pid = None

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260)]

def get_process_map():
    """Returns a dictionary {pid: (ppid, name)}"""
    try:
        kernel32 = ctypes.windll.kernel32
        hSnapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        
        pe32 = PROCESSENTRY32()
        pe32.dwSize = ctypes.sizeof(PROCESSENTRY32)
        
        proc_map = {}
        
        if kernel32.Process32First(hSnapshot, ctypes.byref(pe32)):
            while True:
                pid = pe32.th32ProcessID
                ppid = pe32.th32ParentProcessID
                name = pe32.szExeFile.decode('utf-8', 'ignore')
                proc_map[pid] = (ppid, name)
                
                if not kernel32.Process32Next(hSnapshot, ctypes.byref(pe32)):
                    break
                    
        kernel32.CloseHandle(hSnapshot)
        return proc_map
    except Exception:
        return {}

def get_console_window(use_cache=True):
    """
    Get the console window handle.
    Handles standard console and Windows Terminal (which hides the real window).
    
    Args:
        use_cache: If True, use cached WT window handle if available
    """
    global _cached_wt_hwnd, _cached_wt_pid
    
    if sys.platform != 'win32':
        return None
    
    user32 = ctypes.windll.user32
        
    # 1. Check if we have a cached WT window handle that's still valid
    if use_cache and _cached_wt_hwnd:
        # Verify the cached window still exists and belongs to the right process
        if user32.IsWindow(_cached_wt_hwnd):
            return _cached_wt_hwnd
        else:
            # Window no longer exists, clear cache
            _cached_wt_hwnd = None
            _cached_wt_pid = None
    
    # 2. Try standard method first
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    
    # If the window is visible, it's likely the real one (standard console)
    if hwnd and user32.IsWindowVisible(hwnd):
        return hwnd
        
    # 3. If standard window is hidden or missing, we might be in Windows Terminal
    # We need to walk up the process tree to find WindowsTerminal.exe
    try:
        my_pid = os.getpid()
        proc_map = get_process_map()
        
        curr = my_pid
        wt_pid = None
        
        # Traverse up for a limited depth
        for _ in range(10):
            if curr not in proc_map:
                break
            ppid, name = proc_map[curr]
            
            # Check for Windows Terminal
            if 'WindowsTerminal.exe' in name:
                wt_pid = curr
                break
                
            if ppid == 0 or ppid == curr:
                break
            curr = ppid
            
        if wt_pid:
            # We found Windows Terminal process. Now find its window.
            # We prioritize CASCADIA_HOSTING_WINDOW_CLASS
            # Note: We search for ANY window (not just visible) so we can find hidden ones too
            found_hwnd = None
            fallback_hwnd = None
            
            def enum_handler(h, ctx):
                nonlocal found_hwnd, fallback_hwnd
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                if pid.value == wt_pid:
                    # Check class name
                    class_buff = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(h, class_buff, 256)
                    class_name = class_buff.value
                    
                    if class_name == 'CASCADIA_HOSTING_WINDOW_CLASS':
                        found_hwnd = h
                        return False # Stop enumeration, found the best match
                    
                    # Only use as fallback if it's a top-level window with a title
                    if fallback_hwnd is None:
                        length = user32.GetWindowTextLengthW(h)
                        if length > 0:
                            fallback_hwnd = h
                            
                return True

            CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(CMPFUNC(enum_handler), 0)
            
            if found_hwnd:
                # Cache this for future use
                _cached_wt_hwnd = found_hwnd
                _cached_wt_pid = wt_pid
                return found_hwnd
            if fallback_hwnd:
                _cached_wt_hwnd = fallback_hwnd
                _cached_wt_pid = wt_pid
                return fallback_hwnd
                
    except Exception as e:
        print(f"[Warning] Failed to resolve Windows Terminal window: {e}")
        
    # Fallback to standard handle even if hidden, or None
    return hwnd


def show_console():
    """Show the console window"""
    if sys.platform == 'win32':
        hwnd = get_console_window()
        if hwnd:
            # Use SW_RESTORE (9) instead of SW_SHOW (5) to handle minimized windows
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            return True
    return False


def hide_console():
    """Hide the console window"""
    if sys.platform == 'win32':
        hwnd = get_console_window()
        if hwnd:
            user32 = ctypes.windll.user32
            
            # Try ShowWindow first
            user32.ShowWindow(hwnd, 0)  # SW_HIDE
            
            # If ShowWindow didn't fully hide it, use SetWindowPos as backup
            # This is more forceful and works better with some window types
            if user32.IsWindowVisible(hwnd):
                # SetWindowPos with SWP_HIDEWINDOW
                SWP_HIDEWINDOW = 0x0080
                SWP_NOSIZE = 0x0001
                SWP_NOMOVE = 0x0002
                SWP_NOZORDER = 0x0004
                SWP_NOACTIVATE = 0x0010
                
                user32.SetWindowPos(
                    hwnd,
                    None,  # hWndInsertAfter (not used with these flags)
                    0, 0, 0, 0,  # x, y, cx, cy (ignored with NOSIZE|NOMOVE)
                    SWP_HIDEWINDOW | SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE
                )
            
            return True
    return False


def is_console_visible():
    """
    Check if console window is currently visible (not hidden).
    Note: A minimized window is still considered "visible" by Windows.
    """
    if sys.platform == 'win32':
        hwnd = get_console_window()
        if hwnd:
            return ctypes.windll.user32.IsWindowVisible(hwnd)
    return True


def is_console_minimized():
    """Check if console window is minimized (iconic)"""
    if sys.platform == 'win32':
        hwnd = get_console_window()
        if hwnd:
            # IsIconic returns non-zero if the window is minimized
            return ctypes.windll.user32.IsIconic(hwnd) != 0
    return False


def disable_console_close_button():
    """
    Disable the close button (X) on the console window.
    This prevents users from accidentally closing the app via the console.
    They should use the tray icon's Quit option instead.
    """
    if sys.platform != 'win32':
        return False
    
    try:
        hwnd = get_console_window()
        if not hwnd:
            return False
        
        # Get the system menu (window menu)
        # GetSystemMenu(hwnd, bRevert) - bRevert=False gets the current menu
        user32 = ctypes.windll.user32
        hmenu = user32.GetSystemMenu(hwnd, False)
        
        if hmenu:
            # SC_CLOSE = 0xF060
            # MF_BYCOMMAND = 0x0000
            # MF_GRAYED = 0x0001
            # DeleteMenu or EnableMenuItem to disable close
            SC_CLOSE = 0xF060
            MF_BYCOMMAND = 0x0000
            MF_GRAYED = 0x0001
            
            # Disable (gray out) the close menu item
            user32.EnableMenuItem(hmenu, SC_CLOSE, MF_BYCOMMAND | MF_GRAYED)
            
            # Also remove it entirely (optional - comment out if you just want grayed)
            # user32.DeleteMenu(hmenu, SC_CLOSE, MF_BYCOMMAND)
            
            return True
    except Exception as e:
        print(f"[Warning] Could not disable console close button: {e}")
    
    return False


def enable_console_close_button():
    """Re-enable the close button on the console window."""
    if sys.platform != 'win32':
        return False
    
    try:
        hwnd = get_console_window()
        if not hwnd:
            return False
        
        user32 = ctypes.windll.user32
        # GetSystemMenu with bRevert=True resets to default
        user32.GetSystemMenu(hwnd, True)
        return True
    except Exception:
        pass
    
    return False


# ─── Tray Application ─────────────────────────────────────────────────────────

class TrayApp:
    """System tray application for AIPromptBridge"""
    
    def __init__(self, icon_path=None, on_exit_callback=None, allow_console_toggle=True, show_edit_file_items=False):
        """
        Initialize the tray application
        
        Args:
            icon_path: Path to the .ico file (default: icon.ico in project root)
            on_exit_callback: Function to call when exiting
            allow_console_toggle: Whether to show "Toggle Console" option
            show_edit_file_items: Whether to show direct file editing options (debug mode)
        """
        self.systray = None
        self.on_exit_callback = on_exit_callback
        self.console_visible = True
        self.allow_console_toggle = allow_console_toggle
        self.show_edit_file_items = show_edit_file_items
        
        # Find icon path
        if icon_path is None:
            # Look for icon.ico
            if getattr(sys, 'frozen', False):
                # Frozen: uses sys.executable parent
                icon_path = Path(sys.executable).parent / "icon.ico"
            else:
                # Dev: uses project root
                project_root = Path(__file__).parent.parent
                icon_path = project_root / "icon.ico"
            
            if not icon_path.exists():
                # Fallback: try current directory/assets (for fallback)
                cwd = Path.cwd()
                if (cwd / "icon.ico").exists():
                    icon_path = cwd / "icon.ico"
                else:
                    icon_path = Path("icon.ico")
        
        self.icon_path = str(icon_path) if Path(icon_path).exists() else None
        
        if not HAVE_SYSTRAY:
            print("[Warning] infi.systray not available - tray functionality disabled")
            print("         Install with: pip install infi.systray")
    
    def _on_toggle_console(self, systray):
        """Toggle console visibility based on actual window state"""
        visible = is_console_visible()
        minimized = is_console_minimized()
        
        # A minimized window is "visible" but not shown - we should restore it
        if visible and not minimized:
            hide_console()
            self.console_visible = False
        else:
            show_console()
            self.console_visible = True
    
    def _on_show_console(self, systray):
        """Show the console window"""
        show_console()
        self.console_visible = True
    
    def _on_hide_console(self, systray):
        """Hide the console window"""
        hide_console()
        self.console_visible = False
    
    def _on_restart(self, systray):
        """Restart the application"""
        print("\n🔄 Restarting AIPromptBridge...")
        
        # Get current state
        script = os.path.abspath(sys.argv[0])
        args = sys.argv[1:]
        
        # Detect mode
        is_compiled = getattr(sys, 'frozen', False) or "__compiled__" in globals() or (sys.executable.lower().endswith(".exe") and "python" not in os.path.basename(sys.executable).lower())
        
        launched_mode = None
        for arg in sys.argv:
            if arg.startswith("--launched-mode="):
                launched_mode = arg.split("=")[1]
                break

        # Only manipulate console if NOT in GUI mode
        if launched_mode != "gui":
            show_console()
            enable_console_close_button()
        
        # Clean up emoji resources
        try:
            from .gui.emoji_renderer import get_emoji_renderer
            if get_emoji_renderer():
                get_emoji_renderer().cleanup()
        except Exception:
            pass
            
        # Strategy 1: Compiled Mode - Restart via Launcher
        if is_compiled and launched_mode:
            try:
                bin_dir = Path(sys.executable).parent
                root_dir = bin_dir.parent
                
                # Determine correct launcher
                # Console mode is AIPromptBridge.exe
                # GUI mode is AIPromptBridge-NoConsole.exe
                launcher_name = "AIPromptBridge-NoConsole.exe" if launched_mode == "gui" else "AIPromptBridge.exe"
                launcher_path = root_dir / launcher_name
                
                if launcher_path.exists():
                    print(f"🔄 Restarting via launcher: {launcher_name}")
                    
                    # Remove --launched-mode arg as launcher adds it
                    new_args = [arg for arg in sys.argv[1:] if not arg.startswith("--launched-mode")]
                    
                    cmd = [str(launcher_path)] + new_args
                    
                    # Detached process group
                    subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                    os._exit(0)
            except Exception as e:
                print(f"[Error] Launcher restart failed, falling back: {e}")

        # Strategy 2: Source Mode / Fallback
        if sys.platform == 'win32':
            try:
                # Legacy console or GUI background restart
                flags = subprocess.CREATE_NEW_PROCESS_GROUP
                
                # Only create new console window if NOT in GUI mode
                if launched_mode != "gui":
                    flags |= subprocess.CREATE_NEW_CONSOLE
                
                if script.endswith('.py'):
                    subprocess.Popen(
                        [sys.executable, script] + args,
                        creationflags=flags,
                        start_new_session=True
                    )
                else:
                    subprocess.Popen(
                        [script] + args,
                        creationflags=flags,
                        start_new_session=True
                    )
            except Exception as e:
                print(f"[Error] Failed to start new process: {e}")
                return
        else:
            os.execv(sys.executable, [sys.executable, script] + args)
        
        os._exit(0)
    
    def _on_session_browser(self, systray):
        """Open the session browser GUI"""
        try:
            from .gui.core import show_session_browser, HAVE_GUI
            if HAVE_GUI:
                show_session_browser()
            else:
                print("[Warning] GUI not available")
        except Exception as e:
            print(f"[Error] Could not open session browser: {e}")
    
    def _on_settings(self, systray):
        """Open settings window"""
        try:
            from .gui.core import show_settings_window, HAVE_GUI
            if HAVE_GUI:
                print("\n⚙️  Opening settings...\n")
                show_settings_window()
            else:
                print("[Warning] GUI not available")
        except Exception as e:
            print(f"[Error] Could not open settings: {e}")
    
    def _on_prompt_editor(self, systray):
        """Open prompt editor window"""
        try:
            from .gui.core import show_prompt_editor, HAVE_GUI
            if HAVE_GUI:
                print("\n📝  Opening prompt editor...\n")
                show_prompt_editor()
            else:
                print("[Warning] GUI not available")
        except Exception as e:
            print(f"[Error] Could not open prompt editor: {e}")

    def _on_direct_chat(self, systray):
        """Show direct chat popup (equivalent to Ctrl+Space with no selection)"""
        try:
            from .gui.text_edit_tool import get_instance
            app = get_instance()
            if app:
                # Trigger hotkey action - since tray is focused, likely no text is selected,
                # so it will open the direct chat input popup.
                app._on_hotkey_pressed()
            else:
                print("[Warning] TextEditTool not running")
        except Exception as e:
            print(f"[Error] Could not open direct chat: {e}")

    def _on_snip_tool(self, systray):
        """Trigger snip tool (equivalent to Ctrl+Alt+X)"""
        try:
            from .gui.snip_tool import get_instance
            app = get_instance()
            if app:
                app._on_hotkey_pressed()
            else:
                print("[Warning] SnipTool not running")
        except Exception as e:
            print(f"[Error] Could not trigger snip tool: {e}")

    def _on_audio_analyzer(self, systray):
        """Open Audio Analyzer window (equivalent to Ctrl+Alt+A)"""
        try:
            from .gui.audio_tool import get_instance
            app = get_instance()
            if app:
                app._on_hotkey_pressed()
            else:
                print("[Warning] AudioTool not running")
        except Exception as e:
            print(f"[Error] Could not open Audio Analyzer: {e}")

    def _on_tts_window(self, systray):
        """Open TTS Window"""
        try:
            from . import web_server
            from .gui.core import GUICoordinator, HAVE_GUI
            
            if HAVE_GUI:
                GUICoordinator.get_instance().request_tts_window(
                    web_server.CONFIG,
                    web_server.AI_PARAMS,
                    web_server.KEY_MANAGERS,
                    initial_text=""
                )
            else:
                print("[Warning] GUI not available")
        except Exception as e:
            print(f"[Error] Could not open TTS Window: {e}")
    
    def _on_edit_config(self, systray):
        """Open config.ini in default editor"""
        config_path = Path.cwd() / "config.ini"
            
        if config_path.exists():
            self._open_file(config_path)
        else:
            print(f"[Error] Config file not found: {config_path}")
    
    def _on_edit_options(self, systray):
        """Open prompts.json in default editor"""
        options_path = Path.cwd() / "prompts.json"
        
        if options_path.exists():
            self._open_file(options_path)
        else:
            print(f"[Error] Options file not found: {options_path}")
    
    def _open_file(self, path):
        """Open a file in the default system editor"""
        path = str(path)
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.run(['open', path])
        else:
            subprocess.run(['xdg-open', path])
    
    def _on_exit(self, systray):
        """Exit the application"""
        print("\n👋 Exiting AIPromptBridge...")
        
        # Show console before exit so user sees the message
        show_console()
        enable_console_close_button()  # Re-enable close button before exit
        
        # Call the exit callback if provided
        if self.on_exit_callback:
            self.on_exit_callback()
            
        # Clean up emoji resources
        try:
            from .gui.emoji_renderer import get_emoji_renderer
            if get_emoji_renderer():
                get_emoji_renderer().cleanup()
        except Exception:
            pass
        
        # Force exit
        os._exit(0)
    
    def start(self, hide_console_on_start=True):
        """
        Start the system tray icon
        
        Args:
            hide_console_on_start: Whether to hide console when tray starts
        """
        if not HAVE_SYSTRAY:
            print("[Warning] System tray not available")
            return False
        
        if not self.icon_path:
            print("[Warning] Icon file not found - using default icon")
        
        # Disable the console close button (X) to prevent accidental closure
        # Users should use tray icon's Quit option instead
        disable_console_close_button()
        
        # Enable dark mode for menus if applicable
        self._enable_dark_mode()
        
        # Helper for separators
        def _separator(systray): pass
        SEP = ("---", _separator)

        # Define menu options with dynamic emoji icon support
        raw_options = []
        
        if self.allow_console_toggle:
            raw_options.append(("💻 Toggle Console", self._on_toggle_console))
            raw_options.append(SEP)
            
        raw_options.extend([
            ("🔍 Session Browser", self._on_session_browser),
            ("💬 Direct Chat", self._on_direct_chat),
            ("📸 Screen Snip", self._on_snip_tool),
            ("🎤 Audio Analyzer", self._on_audio_analyzer),
            ("🔊 TTS", self._on_tts_window),
            SEP,
            ("⚙️ Settings", self._on_settings),
            ("✏️ Prompt Editor", self._on_prompt_editor),
        ])
        
        # File editing options (debug mode)
        if self.show_edit_file_items:
            raw_options.extend([
                ("📝 Edit config.ini (file)", self._on_edit_config),
                ("📄 Edit prompts.json (file)", self._on_edit_options),
            ])
        
        raw_options.extend([
            SEP,
            ("🔄 Restart", self._on_restart),
            SEP # Separator before "Quit" (which is added automatically)
        ])
        
        menu_options = []
        
        try:
            # Try to use emoji renderer to generate icons
            from .gui.emoji_renderer import get_emoji_renderer
            renderer = get_emoji_renderer()
            
            for text, callback in raw_options:
                if text == "---":
                    menu_options.append((text, None, callback))
                    continue

                # Extract emoji
                emoji_char, clean_text = renderer.extract_leading_emoji(text)
                icon_path = None
                
                if emoji_char:
                    # Generate temporary .ico file
                    icon_path = renderer.get_emoji_icon_path(emoji_char)
                
                if icon_path:
                    # Use clean text and custom icon
                    menu_options.append((clean_text, icon_path, callback))
                else:
                    menu_options.append((text, None, callback))
                    
        except Exception as e:
            print(f"[Warning] Failed to generate tray icons: {e}")
            for text, callback in raw_options:
                menu_options.append((text, None, callback))
        
        # Create the system tray icon
        try:
            # Standard initialization: Let library handle the Quit button
            # We removed "Quit" from raw_options to ensure only one button appears
            self.systray = SysTrayIcon(
                self.icon_path,
                "AIPromptBridge",
                tuple(menu_options),
                on_quit=self._on_exit,
                default_menu_index=0  # "Show Console" is default action on double-click
            )
            
            # Hide console if requested
            if hide_console_on_start:
                # Use a short delay and retry to ensure WT window is ready
                import time
                for attempt in range(3):
                    if hide_console():
                        # Verify it actually hid
                        time.sleep(0.1)
                        if not is_console_visible():
                            self.console_visible = False
                            break
                    time.sleep(0.3)  # Wait before retry
                else:
                    # Final attempt
                    hide_console()
                    self.console_visible = not is_console_visible()
            
            # Start the tray (this blocks until shutdown is called)
            self.systray.start()
            return True
            
        except Exception as e:
            print(f"[Error] Failed to start system tray: {e}")
            return False
    
    def _enable_dark_mode(self):
        """
        Attempt to enable dark mode for the application menus.
        Uses undocumented Windows APIs.
        """
        if sys.platform != 'win32':
            return
            
        try:
            # Check if we should use dark mode
            try:
                from .gui.themes import is_dark_mode
                should_be_dark = is_dark_mode()
            except ImportError:
                should_be_dark = True # Default to dark if can't check
            
            if not should_be_dark:
                return

            # uxtheme.dll ordinal 135 is SetPreferredAppMode (Windows 10 1903+)
            # 0 = Default, 1 = AllowDark, 2 = ForceDark, 3 = ForceLight, 4 = Max
            try:
                uxtheme = ctypes.windll.uxtheme
                # Try to load the function by ordinal
                if hasattr(uxtheme, "SetPreferredAppMode"):
                    uxtheme.SetPreferredAppMode(2) # Force Dark
                else:
                    # Try by ordinal for older versions or if not exposed by name
                    try:
                        SetPreferredAppMode = uxtheme[135]
                        SetPreferredAppMode(2)
                    except Exception:
                        pass
            except Exception:
                pass
                
        except Exception as e:
            print(f"[Warning] Failed to enable dark mode for tray: {e}")

    def stop(self):
        """Stop the system tray icon"""
        if self.systray:
            self.systray.shutdown()


def run_with_tray(main_func, icon_path=None, hide_console=True):
    """
    Wrapper to run the main application with tray support
    
    Args:
        main_func: The main function to run (should start Flask, etc.)
        icon_path: Path to icon.ico
        hide_console: Whether to hide console on start
    """
    
    # Create tray app
    tray = TrayApp(icon_path=icon_path)
    
    if not HAVE_SYSTRAY:
        # No tray support - just run main function
        main_func()
        return
    
    # Run main function in a separate thread
    main_thread = threading.Thread(target=main_func, daemon=True)
    main_thread.start()
    
    # Start tray (this blocks)
    tray.start(hide_console_on_start=hide_console)
