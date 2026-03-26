"""
Updater Dialogs UI Module for AIPromptBridge.
Contains CTkToplevel logic to prevent bloating the tray module.
"""

import threading
from ...updater import perform_update, is_compiled
from ..platform import ctk
from .utils import set_window_icon, set_dark_titlebar
from ..core import GUICoordinator


def show_up_to_date_dialog(current_version: str):
    """Show the 'You are up to date' dialog."""
    dialog = ctk.CTkToplevel()
    dialog.withdraw()
    dialog.title("AIPromptBridge Update")
    dialog.resizable(False, False)
    dialog.attributes('-topmost', True)
    
    set_dark_titlebar(dialog)
    set_window_icon(dialog)
    
    lbl = ctk.CTkLabel(dialog, text=f"You're up to date!\n\nCurrent version: v{current_version}", font=("Segoe UI", 13))
    lbl.pack(expand=True, padx=30, pady=20)
    
    btn = ctk.CTkButton(dialog, text="OK", width=120, command=dialog.destroy)
    btn.pack(pady=(0, 20))
    
    dialog.update_idletasks()
    w = max(350, dialog.winfo_reqwidth())
    h = max(180, dialog.winfo_reqheight())
    x = (dialog.winfo_screenwidth() - w) // 2
    y = (dialog.winfo_screenheight() - h) // 2
    dialog.geometry(f"{w}x{h}+{x}+{y}")
    dialog.deiconify()
    dialog.focus_force()


def show_update_available_dialog(info, current_version: str):
    """
    Show 'New version available' dialog.
    If 'Yes' is clicked, transitions to a download progress dialog and triggers the background update.
    """
    coordinator = GUICoordinator.get_instance()
    
    size_str = ""
    if info.asset_size > 0:
        size_mb = info.asset_size / (1024 * 1024)
        size_str = f" ({size_mb:.1f} MB)"
    
    notes_preview = ""
    if info.release_notes:
        lines = info.release_notes.strip().split("\n")[:5]
        notes_preview = "\n".join(l.strip() for l in lines)
        if len(info.release_notes.strip().split("\n")) > 5:
            notes_preview += "\n..."
    
    message = (
        f"A new version is available!\n\n"
        f"Current: v{current_version}\n"
        f"New: v{info.version}{size_str}\n"
    )
    if notes_preview:
        message += f"\nRelease Notes:\n{notes_preview}\n"
    
    dialog = ctk.CTkToplevel()
    dialog.withdraw()
    dialog.title("AIPromptBridge Update Available")
    dialog.resizable(False, False)
    dialog.attributes('-topmost', True)
    
    set_dark_titlebar(dialog)
    set_window_icon(dialog)
    
    lbl = ctk.CTkLabel(dialog, text=message, font=("Segoe UI", 13), justify="left")
    lbl.pack(padx=30, pady=20, fill="both", expand=True)

    btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_frame.pack(fill="x", padx=30, pady=(0, 20))
    
    if is_compiled():
        lbl.configure(text=message + "\nDownload and install now?")
        
        def on_yes():
            # Hide old buttons
            btn_frame.pack_forget()
            
            # Transition to Progress UI
            dialog.title("AIPromptBridge Updating...")
            lbl.configure(text=f"Downloading update v{info.version}...", justify="center")
            
            progress_bar = ctk.CTkProgressBar(dialog, width=300)
            progress_bar.pack(padx=30, pady=(0, 20))
            progress_bar.set(0)
            
            dialog.update_idletasks()
            w = max(400, dialog.winfo_reqwidth())
            h = max(200, dialog.winfo_reqheight())
            x = (dialog.winfo_screenwidth() - w) // 2
            y = (dialog.winfo_screenheight() - h) // 2
            dialog.geometry(f"{w}x{h}+{x}+{y}")
            
            # Define progress update handler
            def update_progress(stage, current, total):
                if not dialog.winfo_exists(): return
                if stage == "download":
                    if total > 0:
                        pct = current / total
                        progress_bar.set(pct)
                        lbl.configure(text=f"Downloading update ({int(pct*100)}%)...")
                    else:
                        lbl.configure(text="Downloading update...")
                elif stage == "extract":
                    progress_bar.configure(mode="indeterminate")
                    progress_bar.start()
                    lbl.configure(text="Extracting update... Please wait.")
            
            # Start actual update in background thread
            def _do_update():
                # Safe dispatch to GUI thread
                def safe_progress(s, c, t):
                    coordinator.run_on_gui_thread(lambda: update_progress(s, c, t))
                
                success, msg = perform_update(info, progress_callback=safe_progress)
                if not success:
                    coordinator.run_on_gui_thread(lambda: lbl.configure(text=f"❌  {msg}"))
                    coordinator.run_on_gui_thread(lambda: progress_bar.stop())
                    
                    # Provide an OK button to close the error
                    def show_close_button():
                        if dialog.winfo_exists():
                            btn_err = ctk.CTkButton(dialog, text="OK", width=120, command=dialog.destroy)
                            btn_err.pack(pady=(10, 20))
                    coordinator.run_on_gui_thread(show_close_button)
            
            threading.Thread(target=_do_update, daemon=True).start()
            
        btn_yes = ctk.CTkButton(btn_frame, text="Yes", width=100, command=on_yes)
        btn_yes.pack(side="right", padx=(10, 0))
        
        btn_no = ctk.CTkButton(btn_frame, text="No", width=100, command=dialog.destroy, fg_color="transparent", border_width=1, text_color=("black", "white"))
        btn_no.pack(side="right")
    else:
        lbl.configure(text=message + "\n\nYou are running from source. Please update manually via git or downloading from GitHub.")
        btn_ok = ctk.CTkButton(btn_frame, text="OK", width=120, command=dialog.destroy)
        btn_ok.pack(side="right")
        print(f"📦 Running from source. Download: {info.release_url}\n")
    
    dialog.update_idletasks()
    w = max(450, dialog.winfo_reqwidth())
    h = max(250, dialog.winfo_reqheight())
    x = (dialog.winfo_screenwidth() - w) // 2
    y = (dialog.winfo_screenheight() - h) // 2
    dialog.geometry(f"{w}x{h}+{x}+{y}")
    dialog.deiconify()
    dialog.focus_force()
