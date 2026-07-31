#!/usr/bin/env python3
"""
System Tray implementation for AIPromptBridge.

Backends:
  - Windows: infi.systray (native .ico)
  - Linux:   pystray (AppIndicator / StatusNotifier; needs a tray host)
"""

import ctypes
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from .platform.detect import is_linux, is_windows
from .utils import is_compiled

# ─── Backend availability ─────────────────────────────────────────────────────

HAVE_INFI_SYSTRAY = False
SysTrayIcon = None
try:
    from infi.systray import SysTrayIcon
    from infi.systray.win32_adapter import MENUITEMINFO, CreatePopupMenu, InsertMenuItem, PackMENUITEMINFO, ctypes

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
                    item = PackMENUITEMINFO(text=option_text, hbmpItem=option_icon, wID=option_id)
                    InsertMenuItem(menu, 0, 1, ctypes.byref(item))
                else:
                    submenu = CreatePopupMenu()
                    self._create_menu(submenu, option_action)
                    item = PackMENUITEMINFO(text=option_text, hbmpItem=option_icon, hSubMenu=submenu)
                    InsertMenuItem(menu, 0, 1, ctypes.byref(item))

        def update_menu_options(self, menu_options):
            """Dynamically update menu options of the running tray icon"""
            if self._menu:
                try:
                    ctypes.windll.user32.DestroyMenu(self._menu)
                except Exception as e:
                    print(f"[Warning] Failed to destroy menu: {e}")
                self._menu = None

            self._next_action_id = SysTrayIcon.FIRST_ID
            self._menu_actions_by_id = set()

            full_options = [*menu_options, ("Quit", None, SysTrayIcon.QUIT)]
            self._menu_options = self._add_ids_to_menu_options(full_options)
            self._menu_actions_by_id = dict(self._menu_actions_by_id)

    # Use our custom class instead
    SysTrayIcon = CustomSysTrayIcon
    HAVE_INFI_SYSTRAY = True
except ImportError:
    pass

HAVE_PYSTRAY = False
PystrayIcon = None
PystrayMenu = None
PystrayMenuItem = None
try:
    from pystray import Icon as PystrayIcon
    from pystray import Menu as PystrayMenu
    from pystray import MenuItem as PystrayMenuItem

    HAVE_PYSTRAY = True
except ImportError:
    pass

# Pure D-Bus StatusNotifierItem (preferred on Linux Wayland — works with dms/waybar)
HAVE_STATUS_NOTIFIER = False
try:
    from .platform.status_notifier import (
        StatusNotifierIcon,
        TrayMenuEntry,
        is_status_notifier_available,
        is_status_notifier_host_registered,
    )

    HAVE_STATUS_NOTIFIER = is_status_notifier_available()
except ImportError:
    StatusNotifierIcon = None  # type: ignore[assignment,misc]
    TrayMenuEntry = None  # type: ignore[assignment,misc]

    def is_status_notifier_host_registered(timeout: float = 2.0) -> bool:  # type: ignore[misc]
        return False


# True when a tray backend is available for the current OS.
# Linux: StatusNotifier (jeepney) preferred; pystray kept as optional fallback
# only when AppIndicator GI bindings exist (otherwise pystray uses broken XEmbed).
HAVE_SYSTRAY = (is_windows() and HAVE_INFI_SYSTRAY) or (is_linux() and (HAVE_STATUS_NOTIFIER or HAVE_PYSTRAY))

# Tray icon max edge (px) for StatusNotifier / AppIndicator hosts
_TRAY_ICON_MAX_SIZE = 64


def load_tray_image(icon_path=None):
    """
    Load a Pillow RGBA image for pystray (Linux).

    Prefers ``icon.ico`` / given path; falls back to a simple branded square
    so the tray can still start if the asset is missing or unreadable.
    """
    import warnings

    from PIL import Image

    if icon_path:
        path = Path(icon_path)
        if path.exists():
            try:
                # Multi-size .ico files often warn "Image was not the expected size"
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", message="Image was not the expected size")
                    with Image.open(path) as im:
                        image = im.convert("RGBA")
                if max(image.size) > _TRAY_ICON_MAX_SIZE:
                    image.thumbnail((_TRAY_ICON_MAX_SIZE, _TRAY_ICON_MAX_SIZE), Image.Resampling.LANCZOS)
                elif max(image.size) < 16:
                    # Tiny glyphs are hard to see in some hosts
                    image = image.resize((_TRAY_ICON_MAX_SIZE, _TRAY_ICON_MAX_SIZE), Image.Resampling.NEAREST)
                return image
            except Exception as e:
                print(f"[Warning] Failed to load tray icon {path}: {e}")

    # Fallback: solid brand-ish blue square
    return Image.new("RGBA", (_TRAY_ICON_MAX_SIZE, _TRAY_ICON_MAX_SIZE), (66, 133, 244, 255))


# ─── Console Window Control (Windows) ─────────────────────────────────────────

from ctypes import wintypes

# Define structures for Toolhelp32
TH32CS_SNAPPROCESS = 0x00000002

# Cache for Windows Terminal window handle
_cached_wt_hwnd = None
_cached_wt_pid = None


class PROCESSENTRY32(ctypes.Structure):
    from typing import ClassVar, List, Tuple

    _fields_: ClassVar[List[Tuple[str, type]]] = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


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
                name = pe32.szExeFile.decode("utf-8", "ignore")
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

    if sys.platform != "win32":
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
            if "WindowsTerminal.exe" in name:
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

                    if class_name == "CASCADIA_HOSTING_WINDOW_CLASS":
                        found_hwnd = h
                        return False  # Stop enumeration, found the best match

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
    if sys.platform == "win32":
        hwnd = get_console_window()
        if hwnd:
            # Use SW_RESTORE (9) instead of SW_SHOW (5) to handle minimized windows
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            return True
    return False


def hide_console():
    """Hide the console window"""
    if sys.platform == "win32":
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
                    0,
                    0,
                    0,
                    0,  # x, y, cx, cy (ignored with NOSIZE|NOMOVE)
                    SWP_HIDEWINDOW | SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE,
                )

            return True
    return False


def is_console_visible():
    """
    Check if console window is currently visible (not hidden).
    Note: A minimized window is still considered "visible" by Windows.
    """
    if sys.platform == "win32":
        hwnd = get_console_window()
        if hwnd:
            return ctypes.windll.user32.IsWindowVisible(hwnd)
    return True


def is_console_minimized():
    """Check if console window is minimized (iconic)"""
    if sys.platform == "win32":
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
    if sys.platform != "win32":
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
    if sys.platform != "win32":
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
            allow_console_toggle: Whether to show "Toggle Console" option (Windows only)
            show_edit_file_items: Whether to show direct file editing options (debug mode)
        """
        self.systray = None  # Windows infi.systray instance
        self._pystray_icon = None  # Linux pystray Icon instance (AppIndicator fallback)
        self._sni_icon = None  # Linux StatusNotifierItem (jeepney) instance
        self.on_exit_callback = on_exit_callback
        self.console_visible = True
        # Console toggle is Windows-only (Win32 HWND); never show on Linux
        self.allow_console_toggle = bool(allow_console_toggle) and is_windows()
        self.show_edit_file_items = show_edit_file_items

        # Find icon path
        if icon_path is None:
            # Look for icon.ico
            if is_compiled():
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
            if is_windows():
                print("[Warning] infi.systray not available - tray functionality disabled")
                print("         Install with: pip install infi.systray")
            elif is_linux():
                print("[Warning] Linux tray backend not available - tray functionality disabled")
                print("         Install with: pip install jeepney  (StatusNotifier / dms / waybar)")
                print("         Optional: pip install pystray + system AppIndicator GI bindings")
            else:
                print("[Warning] System tray not available on this platform")

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
        app_is_compiled = is_compiled()

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

        # Strategy 1: Compiled Mode - Restart via outer launcher
        if app_is_compiled and launched_mode:
            try:
                from .startup_manager import get_launcher_path

                launcher_path_str = get_launcher_path()
                launcher_path = Path(launcher_path_str) if launcher_path_str else None

                # Fallback name search if helper returns None
                if launcher_path is None or not launcher_path.is_file():
                    bin_dir = Path(sys.executable).parent
                    root_dir = bin_dir.parent
                    if sys.platform == "win32":
                        names = (
                            ["AIPromptBridge-NoConsole.exe", "AIPromptBridge.exe"]
                            if launched_mode == "gui"
                            else ["AIPromptBridge.exe", "AIPromptBridge-NoConsole.exe"]
                        )
                    else:
                        names = ["AIPromptBridge"]
                    for name in names:
                        candidate = root_dir / name
                        if candidate.is_file():
                            launcher_path = candidate
                            break

                if launcher_path is not None and launcher_path.is_file():
                    print(f"🔄 Restarting via launcher: {launcher_path.name}")

                    # Remove --launched-mode arg as launcher adds it
                    new_args = [arg for arg in sys.argv[1:] if not arg.startswith("--launched-mode")]
                    cmd = [str(launcher_path), *new_args]

                    if sys.platform == "win32":
                        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                    else:
                        subprocess.Popen(cmd, start_new_session=True)
                    os._exit(0)
            except Exception as e:
                print(f"[Error] Launcher restart failed, falling back: {e}")

        # Strategy 2: Source Mode / Fallback
        if sys.platform == "win32":
            try:
                # Legacy console or GUI background restart
                flags = subprocess.CREATE_NEW_PROCESS_GROUP

                # Only create new console window if NOT in GUI mode
                if launched_mode != "gui":
                    flags |= subprocess.CREATE_NEW_CONSOLE

                if script.endswith(".py"):
                    subprocess.Popen([sys.executable, script, *args], creationflags=flags, start_new_session=True)
                else:
                    subprocess.Popen([script, *args], creationflags=flags, start_new_session=True)
            except Exception as e:
                print(f"[Error] Failed to start new process: {e}")
                return
        else:
            # Linux/macOS: re-exec current process image with same argv
            os.execv(sys.executable, [sys.executable, script, *args])

        os._exit(0)

    def _on_session_browser(self, systray):
        """Open the session browser GUI"""
        try:
            from .gui.core import HAVE_GUI, show_session_browser

            if HAVE_GUI:
                show_session_browser()
            else:
                print("[Warning] GUI not available")
        except Exception as e:
            print(f"[Error] Could not open session browser: {e}")

    def _on_settings(self, systray):
        """Open settings window"""
        try:
            from .gui.core import HAVE_GUI, show_settings_window

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
            from .gui.core import HAVE_GUI, show_prompt_editor

            if HAVE_GUI:
                print("\n📝  Opening prompt editor...\n")
                show_prompt_editor()
            else:
                print("[Warning] GUI not available")
        except Exception as e:
            print(f"[Error] Could not open prompt editor: {e}")

    def _on_connection_profiles(self, systray):
        """Open connection profile manager window"""
        try:
            from .gui.core import HAVE_GUI, show_connection_manager

            if HAVE_GUI:
                print("\n🔌  Opening connection profiles...\n")
                show_connection_manager()
            else:
                print("[Warning] GUI not available")
        except Exception as e:
            print(f"[Error] Could not open connection profiles: {e}")

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

            # Check if TTS is enabled in config
            if not web_server.CONFIG.get("tts_enabled", True):
                print("[Warning] TTS not enabled")
                return

            from .gui.core import HAVE_GUI, GUICoordinator

            if HAVE_GUI:
                GUICoordinator.get_instance().request_tts_window(
                    web_server.CONFIG, web_server.AI_PARAMS, web_server.KEY_MANAGERS, initial_text=""
                )
            else:
                print("[Warning] GUI not available")
        except Exception as e:
            print(f"[Error] Could not open TTS Window: {e}")

    def _on_check_updates(self, systray):
        """Check for updates from GitHub Releases"""

        def _check_thread():
            try:
                from . import web_server
                from .updater import (
                    RELEASES_URL,
                    check_for_update,
                    get_cached_update_info,
                    is_compiled,
                    perform_update,
                )
                from .version import __version__

                config = web_server.CONFIG or {}

                print("\n⬆️  Checking for updates...")
                info = check_for_update()

                if not info:
                    print(f"✅ You're up to date! (v{__version__})\n")
                    try:
                        from .gui.core import HAVE_GUI, GUICoordinator

                        if HAVE_GUI:
                            coordinator = GUICoordinator.get_instance()

                            def _show_uptodate_dialog():
                                from .gui.windows.update_dialogs import show_up_to_date_dialog

                                show_up_to_date_dialog(__version__)

                            coordinator.run_on_gui_thread(_show_uptodate_dialog)
                    except Exception as e:
                        print(f"[Error] Failed to show up-to-date dialog: {e}")
                    return

                print(f"⬆️  Update available: v{info.version} (current: v{__version__})")

                # Attempt update via GUI dialog or direct
                try:
                    from .gui.core import HAVE_GUI, GUICoordinator

                    if HAVE_GUI:
                        coordinator = GUICoordinator.get_instance()

                        def _show_update_dialog():
                            from .gui.windows.update_dialogs import show_update_available_dialog

                            show_update_available_dialog(info, __version__)

                        coordinator.run_on_gui_thread(_show_update_dialog)
                        return
                except Exception as e:
                    print(f"[Error] Failed to show update dialog: {e}")

                # Fallback: console prompt
                print("   Press U in the terminal to install.\n")

            except Exception as e:
                print(f"[Error] Update check failed: {e}")

        import threading

        threading.Thread(target=_check_thread, daemon=True).start()

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
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])

    def _on_exit(self, systray=None):
        """Exit the application"""
        print("\n👋 Exiting AIPromptBridge...")

        # Show console before exit so user sees the message (Windows no-op on Linux)
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

    def _on_exit_pystray(self, icon, item=None):
        """Quit handler for pystray (stops icon then runs shared exit path)."""
        try:
            if icon is not None:
                icon.stop()
        except Exception:
            pass
        self._on_exit(icon)

    def start(self, hide_console_on_start=True):
        """
        Start the system tray icon

        Args:
            hide_console_on_start: Whether to hide console when tray starts (Windows)
        """
        if not HAVE_SYSTRAY:
            print("[Warning] System tray not available")
            return False

        if not self.icon_path:
            print("[Warning] Icon file not found - using default/fallback icon")

        # Subscribe to config changes to rebuild menu dynamically
        try:
            from .config import subscribe_config_change

            subscribe_config_change(self._on_config_changed)
        except Exception as e:
            print(f"[Warning] Could not subscribe to config changes in tray: {e}")

        if is_windows() and HAVE_INFI_SYSTRAY:
            return self._start_windows(hide_console_on_start=hide_console_on_start)
        if is_linux():
            return self._start_linux()

        print("[Warning] No tray backend for this platform")
        return False

    def _start_windows(self, hide_console_on_start=True):
        """Start Windows infi.systray backend (blocks until quit)."""
        # Disable the console close button (X) to prevent accidental closure
        # Users should use tray icon's Quit option instead
        disable_console_close_button()

        # Enable dark mode for menus if applicable
        self._enable_dark_mode()

        menu_options = self.build_menu_options()

        try:
            # Standard initialization: Let library handle the Quit button
            # We removed "Quit" from raw_options to ensure only one button appears
            self.systray = SysTrayIcon(
                self.icon_path,
                "AIPromptBridge",
                tuple(menu_options),
                on_quit=self._on_exit,
                default_menu_index=0,  # First item is default action on double-click
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

    def _start_linux(self):
        """
        Start Linux tray backend (blocks until quit).

        Prefer pure D-Bus StatusNotifierItem (works with dms/waybar on Wayland).
        Fall back to pystray only when its AppIndicator backend is usable —
        the XEmbed fallback cannot dock on pure Wayland.
        """
        image = load_tray_image(self.icon_path)

        # 1) StatusNotifierItem via jeepney (correct protocol for dms / SNI hosts)
        if HAVE_STATUS_NOTIFIER and StatusNotifierIcon is not None:
            try:
                if not is_status_notifier_host_registered():
                    print(
                        "[Warning] No StatusNotifier host registered yet "
                        "(start dms/waybar/etc.). Trying SNI registration anyway..."
                    )
                menu_entries = self._build_sni_menu_entries()
                default_cb = None
                for entry in menu_entries:
                    if entry.default and entry.callback is not None:
                        default_cb = entry.callback
                        break
                self._sni_icon = StatusNotifierIcon(
                    image=image,
                    title="AIPromptBridge",
                    app_id="aipromptbridge",
                    menu=menu_entries,
                    on_activate=default_cb,
                )
                # Blocks until stop() (Quit) or process exit
                self._sni_icon.run()
                return True
            except Exception as e:
                print(f"[Warning] StatusNotifier tray failed: {e}")
                self._sni_icon = None

        # 2) pystray AppIndicator (needs PyGObject + libappindicator GI)
        if HAVE_PYSTRAY and self._pystray_backend_is_appindicator():
            try:
                menu = self._build_pystray_menu()
                self._pystray_icon = PystrayIcon(
                    "aipromptbridge",
                    image,
                    "AIPromptBridge",
                    menu,
                )
                self._pystray_icon.run()
                return True
            except Exception as e:
                print(f"[Warning] pystray AppIndicator tray failed: {e}")
                self._pystray_icon = None

        print("[Error] Failed to start system tray on Linux")
        print("         Need a StatusNotifier host (dms, waybar, …) and: pip install jeepney")
        print("         (pystray XEmbed backend cannot dock on pure Wayland)")
        return False

    @staticmethod
    def _pystray_backend_is_appindicator() -> bool:
        """True if pystray selected the AppIndicator backend (not broken XEmbed)."""
        if not HAVE_PYSTRAY or PystrayIcon is None:
            return False
        module = getattr(PystrayIcon, "__module__", "") or ""
        return "appindicator" in module

    def _wrap_tray_action(self, callback):
        """Adapt TrayApp handlers ``(systray)`` for backends that pass different args."""

        def action(*_args, **_kwargs):
            callback(None)

        return action

    def _build_sni_menu_entries(self):
        """Build StatusNotifier/dbusmenu entries from shared menu option logic."""
        if TrayMenuEntry is None:
            return []

        menu_options = self.build_menu_options()
        entries = []

        for entry in menu_options:
            text = entry[0]
            callback = entry[2] if len(entry) >= 3 else entry[1]

            if text == "---":
                entries.append(TrayMenuEntry(label=None))
                continue

            is_default = "Session Browser" in text
            entries.append(
                TrayMenuEntry(
                    label=text,
                    callback=self._wrap_tray_action(callback),
                    default=is_default,
                )
            )

        if entries and entries[-1].label is not None:
            entries.append(TrayMenuEntry(label=None))
        entries.append(TrayMenuEntry(label="Quit", callback=self._on_exit_sni))
        return entries

    def _on_exit_sni(self):
        """Quit handler for StatusNotifier backend."""
        try:
            if self._sni_icon is not None:
                self._sni_icon.stop()
        except Exception:
            pass
        self._on_exit(None)

    def _wrap_pystray_action(self, callback):
        """Adapt TrayApp handlers ``(systray)`` to pystray ``(icon, item)``."""

        def action(icon, item=None):
            callback(icon)

        return action

    def _build_pystray_menu(self):
        """Build a pystray.Menu from shared menu option logic."""
        menu_options = self.build_menu_options()
        items = []

        for entry in menu_options:
            # Windows format: (text, icon_path, callback)
            text = entry[0]
            callback = entry[2] if len(entry) >= 3 else entry[1]

            if text == "---":
                items.append(PystrayMenu.SEPARATOR)
                continue

            # Primary-click default: Session Browser (no Toggle Console on Linux)
            is_default = "Session Browser" in text
            items.append(
                PystrayMenuItem(
                    text,
                    self._wrap_pystray_action(callback),
                    default=is_default,
                )
            )

        # Quit is auto-added by infi.systray; add explicitly for pystray
        if items and items[-1] is not PystrayMenu.SEPARATOR:
            items.append(PystrayMenu.SEPARATOR)
        items.append(PystrayMenuItem("Quit", self._on_exit_pystray))

        return PystrayMenu(*items)

    def _enable_dark_mode(self):
        """
        Attempt to enable dark mode for the application menus.
        Uses undocumented Windows APIs.
        """
        if sys.platform != "win32":
            return

        try:
            # Check if we should use dark mode
            try:
                from .gui.themes import is_dark_mode

                should_be_dark = is_dark_mode()
            except ImportError:
                should_be_dark = True  # Default to dark if can't check

            if not should_be_dark:
                return

            # uxtheme.dll ordinal 135 is SetPreferredAppMode (Windows 10 1903+)
            # 0 = Default, 1 = AllowDark, 2 = ForceDark, 3 = ForceLight, 4 = Max
            try:
                uxtheme = ctypes.windll.uxtheme
                # Try to load the function by ordinal
                if hasattr(uxtheme, "SetPreferredAppMode"):
                    uxtheme.SetPreferredAppMode(2)  # Force Dark
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
        try:
            from .config import unsubscribe_config_change

            unsubscribe_config_change(self._on_config_changed)
        except Exception:
            pass
        if self._sni_icon is not None:
            try:
                self._sni_icon.stop()
            except Exception:
                pass
            self._sni_icon = None
        if self._pystray_icon is not None:
            try:
                self._pystray_icon.stop()
            except Exception:
                pass
            self._pystray_icon = None
        if self.systray:
            self.systray.shutdown()

    def build_menu_options(self):
        # Helper for separators
        def _separator(systray):
            pass

        SEP = ("---", _separator)

        # Read tool enable states from config for conditional menu items
        try:
            from . import web_server

            _cfg = web_server.CONFIG or {}
        except Exception:
            _cfg = {}

        _text_edit_enabled = _cfg.get("text_edit_tool_enabled", True)
        _snip_enabled = _cfg.get("screen_snip_enabled", True)
        _audio_enabled = _cfg.get("audio_tool_enabled", True)
        _tts_enabled = _cfg.get("tts_enabled", True)

        # Define menu options with dynamic emoji icon support
        raw_options = []

        # Toggle Console is Windows-only (Win32 console HWND)
        if self.allow_console_toggle and is_windows():
            raw_options.append(("💻 Toggle Console", self._on_toggle_console))
            raw_options.append(SEP)

        # Always show Session Browser (not a tool)
        raw_options.append(("🔍 Session Browser", self._on_session_browser))

        # Only show tool items if the tool is enabled
        if _text_edit_enabled:
            raw_options.append(("💬 Direct Chat", self._on_direct_chat))
        if _snip_enabled:
            raw_options.append(("📸 Screen Snip", self._on_snip_tool))
        if _audio_enabled:
            raw_options.append(("🎤 Audio Analyzer", self._on_audio_analyzer))
        if _tts_enabled:
            raw_options.append(("🔊 TTS", self._on_tts_window))

        raw_options.append(SEP)
        raw_options.extend(
            [
                ("⚙️ Settings", self._on_settings),
                ("✏️ Prompt Editor", self._on_prompt_editor),
                ("🔌 Profiles", self._on_connection_profiles),
            ]
        )

        # File editing options (debug mode)
        if self.show_edit_file_items:
            raw_options.extend(
                [
                    ("📝 Edit config.ini (file)", self._on_edit_config),
                    ("📄 Edit prompts.json (file)", self._on_edit_options),
                ]
            )

        raw_options.extend(
            [
                SEP,
                ("⬆️ Check for Updates", self._on_check_updates),
                ("🔄 Restart", self._on_restart),
                SEP,  # Separator before "Quit" (which is added automatically)
            ]
        )

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

        return menu_options

    def update_tray_menu(self):
        """Rebuild and update the tray menu options dynamically based on config changes."""
        if self._sni_icon is not None:
            try:
                self._sni_icon.update_menu(self._build_sni_menu_entries())
            except Exception as e:
                print(f"[Warning] Failed to update StatusNotifier menu: {e}")
            return
        if self._pystray_icon is not None:
            try:
                self._pystray_icon.menu = self._build_pystray_menu()
                self._pystray_icon.update_menu()
            except Exception as e:
                print(f"[Warning] Failed to update pystray menu: {e}")
            return
        if not self.systray:
            return
        menu_options = self.build_menu_options()
        self.systray.update_menu_options(menu_options)

    def _on_config_changed(self, key, value):
        # Rebuild tray menu if any tool toggle or bulk update occurs
        if key in (
            "text_edit_tool_enabled",
            "screen_snip_enabled",
            "audio_tool_enabled",
            "tts_enabled",
            "_bulk_update",
            "onboarding_completed",
        ):
            self.update_tray_menu()


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
