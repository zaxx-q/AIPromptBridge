"""
Updater Dialogs UI Module for AIPromptBridge.
Contains CTkToplevel logic to prevent bloating the tray module.
"""

import threading
import webbrowser

from ...updater import is_compiled, perform_update
from ..core import GUICoordinator
from ..platform import ctk
from ..themes import get_colors, get_ctk_button_colors, get_ctk_font, get_ctk_label_colors, get_ctk_textbox_colors
from .utils import set_dark_titlebar, set_window_icon


def show_up_to_date_dialog(current_version: str):
    """Show the 'You are up to date' dialog."""
    colors = get_colors()

    dialog = ctk.CTkToplevel()
    dialog.withdraw()
    dialog.title("AIPromptBridge Update")
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    dialog.configure(fg_color=colors.bg)

    set_dark_titlebar(dialog)
    set_window_icon(dialog)

    lbl = ctk.CTkLabel(
        dialog,
        text=f"You're up to date!\n\nCurrent version: v{current_version}",
        font=get_ctk_font(13),
        **get_ctk_label_colors(colors),
    )
    lbl.pack(expand=True, padx=30, pady=20)

    btn = ctk.CTkButton(
        dialog, text="OK", width=120, command=dialog.destroy, **get_ctk_button_colors(colors, variant="primary")
    )
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
    colors = get_colors()

    size_str = ""
    if info.asset_size > 0:
        size_mb = info.asset_size / (1024 * 1024)
        size_str = f" ({size_mb:.1f} MB)"

    dialog = ctk.CTkToplevel()
    dialog.withdraw()
    dialog.title("AIPromptBridge Update Available")
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    dialog.configure(fg_color=colors.bg)

    set_dark_titlebar(dialog)
    set_window_icon(dialog)

    # Header label at the top
    header_text = f"A new version is available!\nCurrent: v{current_version}  |  New: v{info.version}{size_str}"
    lbl = ctk.CTkLabel(
        dialog, text=header_text, font=get_ctk_font(13, "bold"), justify="left", **get_ctk_label_colors(colors)
    )
    lbl.pack(padx=30, pady=(20, 10), fill="x")

    # Scrollable Textbox for release notes
    lbl_notes = None
    txt_changelog = None
    if info.release_notes:
        lbl_notes = ctk.CTkLabel(
            dialog,
            text="Release Notes / Changelog:",
            font=get_ctk_font(11, "bold"),
            justify="left",
            **get_ctk_label_colors(colors),
        )
        lbl_notes.pack(padx=30, pady=(0, 2), anchor="w")

        txt_changelog = ctk.CTkTextbox(dialog, font=get_ctk_font(12), height=140, **get_ctk_textbox_colors(colors))
        txt_changelog.pack(padx=30, pady=(0, 10), fill="both", expand=True)
        txt_changelog.insert("1.0", info.release_notes.strip())
        txt_changelog.configure(state="disabled")

    # Prompt label at the bottom of the content area
    prompt_text = (
        "Download and install now?"
        if is_compiled()
        else "You are running from source. Please update manually via git or downloading from GitHub."
    )
    lbl_prompt = ctk.CTkLabel(
        dialog, text=prompt_text, font=get_ctk_font(12), justify="left", wraplength=450, **get_ctk_label_colors(colors)
    )
    lbl_prompt.pack(padx=30, pady=(0, 15), fill="x")

    btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_frame.pack(fill="x", padx=30, pady=(0, 20))

    if is_compiled():

        def on_yes():
            # Hide old buttons, notes label, textbox, and prompt label
            btn_frame.pack_forget()
            if lbl_notes:
                lbl_notes.pack_forget()
            if txt_changelog:
                txt_changelog.pack_forget()
            lbl_prompt.pack_forget()

            # Transition to Progress UI
            dialog.title("AIPromptBridge Updating...")
            lbl.configure(text=f"Downloading update v{info.version}...", justify="center")

            progress_bar = ctk.CTkProgressBar(dialog, width=300, fg_color=colors.surface1, progress_color=colors.accent)
            progress_bar.pack(padx=30, pady=(40, 20))
            progress_bar.set(0)

            dialog.update_idletasks()
            w = 400
            h = 200
            x = (dialog.winfo_screenwidth() - w) // 2
            y = (dialog.winfo_screenheight() - h) // 2
            dialog.geometry(f"{w}x{h}+{x}+{y}")

            # Define progress update handler
            def update_progress(stage, current, total):
                if not dialog.winfo_exists():
                    return
                if stage == "download":
                    if total > 0:
                        pct = current / total
                        progress_bar.set(pct)
                        lbl.configure(text=f"Downloading update ({int(pct * 100)}%)...")
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
                            btn_err = ctk.CTkButton(
                                dialog,
                                text="OK",
                                width=120,
                                command=dialog.destroy,
                                **get_ctk_button_colors(colors, variant="primary"),
                            )
                            btn_err.pack(pady=(10, 20))

                    coordinator.run_on_gui_thread(show_close_button)

            threading.Thread(target=_do_update, daemon=True).start()

        btn_yes = ctk.CTkButton(
            btn_frame, text="Yes", width=100, command=on_yes, **get_ctk_button_colors(colors, variant="primary")
        )
        btn_yes.pack(side="right", padx=(10, 0))

        btn_no = ctk.CTkButton(
            btn_frame,
            text="No",
            width=100,
            command=dialog.destroy,
            fg_color="transparent",
            border_width=1,
            border_color=colors.surface1,
            text_color=colors.fg,
            hover_color=colors.surface0,
        )
        btn_no.pack(side="right")
    else:
        btn_ok = ctk.CTkButton(
            btn_frame, text="OK", width=120, command=dialog.destroy, **get_ctk_button_colors(colors, variant="primary")
        )
        btn_ok.pack(side="right")
        print(f"📦 Running from source. Download: {info.release_url}\n")

    # Add button to open latest GitHub releases
    btn_gh = ctk.CTkButton(
        btn_frame,
        text="GitHub Releases",
        width=140,
        command=lambda: webbrowser.open("https://github.com/zaxx-q/AIPromptBridge/releases/latest"),
        **get_ctk_button_colors(colors, variant="secondary"),
    )
    btn_gh.pack(side="left")

    dialog.update_idletasks()
    w = max(550, dialog.winfo_reqwidth())
    h = max(380, dialog.winfo_reqheight())
    x = (dialog.winfo_screenwidth() - w) // 2
    y = (dialog.winfo_screenheight() - h) // 2
    dialog.geometry(f"{w}x{h}+{x}+{y}")
    dialog.deiconify()
    dialog.focus_force()
