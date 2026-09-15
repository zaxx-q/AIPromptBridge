# Linux Support (Wayland / niri)

AIPromptBridge runs on **Windows** (primary) and **Linux Wayland** (wlroots compositors such as **niri**). Config stays **CWD-relative** (portable layout) for both **source** and **Nuitka** installs.

Python: **3.13.x** (see `.python-version`). Install deps with `uv pip install -r requirements.txt` (platform markers skip Windows-only packages on Linux).

**Packaging:** GitHub Releases ship a Linux x86_64 tarball (`AIPromptBridge-v*-linux-x86_64.tar.gz`) built with Nuitka on Ubuntu 24.04 (Xft system Tk). Details: [BUILD_PROCESS.md](BUILD_PROCESS.md).

## Quick start

```bash
cd /path/to/AIPromptBridge
uv venv && source .venv/bin/activate   # if needed
uv pip install -r requirements.txt
uv run main.py --show-console
```

Trigger tools from another terminal or a window-manager bind (no in-process global hotkeys on pure Wayland). **Prefer the fast IPC client** so each keypress does not cold-start Nuitka or the full `main.py` import graph (~3–6 s → tens of ms):

```bash
# Compiled install (outer launcher → aipb_trigger.py + system python3):
AIPromptBridge --trigger textedit

# Source checkout (stdlib only — best for binds):
python3 scripts/aipb_trigger.py snip
python -m src.platform.ipc audio

# Also works after lazy imports, but slower than the scripts above:
uv run main.py --trigger chat

# Triggers: snip, textedit, audio, tts, chat, browser, settings, prompts
```

Example **niri** binds:

```kdl
binds {
    // Compiled PATH install:
    Mod+Shift+T { spawn-sh "AIPromptBridge --trigger textedit"; }
    Mod+Shift+S { spawn-sh "AIPromptBridge --trigger snip"; }
    Mod+Shift+A { spawn-sh "AIPromptBridge --trigger audio"; }
    // Source: spawn-sh "python3 /path/to/AIPromptBridge/scripts/aipb_trigger.py snip";
}
```

## System packages

| Package / binary                                 | Role                                                                                                          |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| **`python3.13` + `python3.13-tkinter`** (distro) | **GUI:** Xft-capable Tk (real fonts + rounded CTk widgets). Prefer over uv’s standalone CPython for the venv. |
| `wl-clipboard` (`wl-copy`, `wl-paste`)           | Clipboard + primary selection                                                                                 |
| `wtype` (recommended) / `wlrctl`                 | Virtual keyboard: smooth Unicode/emoji typing, Ctrl+V/C (TextEdit replace/type, selection capture)            |
| `grim`, `slurp`                                  | Screen region capture (SnipTool)                                                                              |
| PortAudio (+ `PyAudio` wheel)                    | Mic + desktop-monitor recording                                                                               |
| Optional: `tmux`                                 | Persistent console session and tray terminal attachment (`aipromptbridge` session)                            |
| Optional: `paplay` / `pw-play` / `ffplay`        | Snip/textedit feedback sounds                                                                                 |
| StatusNotifier host (e.g. dms, waybar)           | Tray icon via `pystray`                                                                                       |

Python deps with markers: `pystray` and `PyAudio` on Linux; `infi.systray` and `PyAudioWPatch` on Windows only.

### CustomTkinter / Tk fonts (important)

CustomTkinter draws rounded corners with a special shapes font (`font_shapes`) and expects real FreeType fonts via **LibXft**.

**uv’s standalone CPython** (python-build-standalone) ships Tk built **`no-xft`**. On those interpreters Tk only exposes the bitmap font `fixed`, so:

| Symptom                                          | Cause                                                          |
| ------------------------------------------------ | -------------------------------------------------------------- |
| Broken / “corrupted” corners on every CTk widget | Shapes font falls back to `fixed`; `font_shapes` drawing fails |
| Pixelated / horrendous UI text                   | No Xft → no Roboto/Noto/DejaVu in Tk                           |

**App mitigation** (`src/gui/ctk_bootstrap.py`, runs once on GUI start):

- Probes whether `CustomTkinter_shapes_font` actually resolves in Tk
- If not → forces `DrawEngine.preferred_drawing_method = "circle_shapes"` (usable corners globally)
- Installs CTk Roboto + shapes fonts into `~/.fonts` and `~/.local/share/fonts` + `fc-cache` (helps once Xft Tk is available)
- Logs a console warning when the font stack is degraded

**Full fix (Windows-like fonts)** — recreate the venv on **distro** Python 3.13 with tkinter (Fedora example):

```bash
sudo dnf install python3.13 python3.13-tkinter
cd /path/to/AIPromptBridge
uv venv --python /usr/bin/python3.13
uv pip install -r requirements.txt

# Expect many families and a real sans face, not only "fixed":
uv run python -c "import tkinter as tk; r=tk.Tk(); r.withdraw(); print(len(r.tk.call('font','families')), r.tk.call('font','actual','TkDefaultFont')); r.destroy()"
```

Do **not** try to `LD_LIBRARY_PATH` over uv’s `libtcl9tk9.0.so` with distro Tk — ABI skew is fragile.

## How Linux maps to features

| Feature                  | Windows                               | Linux (Wayland / niri)                                                                                                                                         |
| ------------------------ | ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Start tools              | Global hotkeys (pynput) + tray        | **IPC** `--trigger` + tray (if SNI host)                                                                                                                       |
| Launch at login          | Registry `HKCU\…\Run`                 | **XDG autostart** `~/.config/autostart/aipromptbridge.desktop`                                                                                                 |
| Single instance          | Named mutex                           | Unix socket bind (same path as IPC)                                                                                                                            |
| Tray                     | `infi.systray`                        | `pystray` (AppIndicator / StatusNotifier)                                                                                                                      |
| Selection capture        | SendInput Ctrl+C + clipboard sequence | Active Ctrl+C query directly to focused window (supports Google Docs, browser inputs, text editors) without stale primary pollution; optional primary fallback |
| Type / paste into apps   | pynput / SendInput                    | `wtype` (smooth per-keystroke typing, Unicode/emojis) or `wlrctl` (+ `wl-copy` for paste)                                                                      |
| Snip                     | Tk overlay + `PIL.ImageGrab`          | `slurp` geometry + `grim -g` → same `CaptureResult`                                                                                                            |
| System audio             | WASAPI loopback (PyAudioWPatch)       | PipeWire/Pulse **monitor** sources via `pactl` + `ffmpeg -f pulse` (PortAudio often has no Pulse host API)                                                     |
| Interactive console      | Win32 console HWND + Toggle Console   | Named `tmux` session (`aipromptbridge`) + **Open Terminal (tmux)** tray action                                                                                 |
| Sounds                   | `winsound`                            | `paplay` / `pw-play` / `ffplay`                                                                                                                                |
| Settings → Tools hotkeys | Editable global hotkey fields         | Read-only **IPC trigger** command list                                                                                                                         |

## Autostart (XDG `.desktop`)

Settings → **General** → **Launch at Login** toggles an XDG autostart entry (same Settings toggle that uses the Windows Run registry on Windows).

|                   |                                                                                                                     |
| ----------------- | ------------------------------------------------------------------------------------------------------------------- |
| File              | `$XDG_CONFIG_HOME/autostart/aipromptbridge.desktop` (default `~/.config/autostart/`)                                |
| `Exec` (source)   | Current interpreter + absolute `main.py --tmux-detached` (same venv as the running app)                             |
| `Exec` (compiled) | Outer launcher `…/AIPromptBridge --tmux-detached` when present; else `sys.executable --tmux-detached`               |
| `Path`            | Deploy / project root (CWD-relative `config.ini` / `keys.json` / sessions; for `bin/` internals = parent of `bin/`) |

Implemented in `src/startup_manager.py` (`set_startup` / `is_startup_enabled` / `get_startup_info`).

### Interactive console and tmux integration

When `tmux` is installed:

- **Normal manual launches:** outside tmux, the app creates or attaches to a named tmux session `aipromptbridge` (`tmux new-session -A -s aipromptbridge …`). A second manual launch attaches its terminal to the existing session rather than starting a duplicate app process.
- **Autostart:** launched with `--tmux-detached`, creating or reusing the session in the background without needing a visible terminal.
- **Tray attachment:** the tray menu provides **Open Terminal (tmux)**, which opens the desktop's default terminal (`xdg-terminal-exec`, `$TERMINAL`, or discovered terminal emulators) attached to `aipromptbridge`.
- **Manual attachment:** attach anytime from any terminal with:
  ```bash
  tmux attach-session -t aipromptbridge
  ```
- **Inside tmux:** if `$TMUX` is already set (e.g. running inside an existing user pane), the app runs directly without creating nested sessions.
- **IPC triggers:** `--trigger` bypasses tmux entirely, ensuring compositor keybinds remain fast.

If `tmux` is not installed, the app launches directly as before without errors.

**niri caveat:** a bare niri session often does **not** process XDG autostart by itself. The toggle still writes the standard desktop file (for GNOME/KDE/XFCE and sessions that run `dex` / systemd user autostart). On pure niri, also add something like:

```kdl
spawn-at-startup "sh" "-c" "cd /path/to/AIPromptBridge && uv run main.py"
```

(or the absolute `Exec` line shown as **Target** in Settings).

## Prebuilt package (Nuitka)

Release assets include a Linux tarball alongside the Windows zip:

```bash
tar -xzf AIPromptBridge-vX.Y.Z-linux-x86_64.tar.gz
cd AIPromptBridge-vX.Y.Z-linux-x86_64
./AIPromptBridge --show-console
./AIPromptBridge --trigger textedit   # needs a running instance
```

Optional PATH install — keep the full tree together and symlink only the outer launcher (it resolves symlinks to find `bin/`):

```bash
# e.g. extract/move package to ~/.local/AIPromptBridge/
ln -sf ~/.local/AIPromptBridge/AIPromptBridge ~/.local/bin/AIPromptBridge
AIPromptBridge --show-console
```

Do **not** copy only `AIPromptBridge` into `~/.local/bin` without `bin/` beside the real script — config and the Nuitka tree stay at the deploy root.

Layout:

```
AIPromptBridge-…-linux-x86_64/
  AIPromptBridge              # shell launcher (use this)
  aipb_trigger.py             # fast --trigger client (stdlib)
  bin/AIPromptBridge_Internal # Nuitka standalone
  bin/…                       # bundled libs + assets
  README-linux.txt
```

**Runtime packages** are still required (same table as [System packages](#system-packages)): `wl-clipboard`, `wtype` (or `wlrctl`), `grim`, `slurp`, `pactl`, `ffmpeg`, PortAudio, StatusNotifier host, and optional `tmux`.

**glibc:** built on **Ubuntu 24.04** x86_64. Older distributions may not run the binary; use a source install instead.

**Self-update:** compiled Linux builds support **full in-place updates** — download, extract, swap `bin/` + root files, and `os.execv` relaunch. Source installs are notification-only (link to releases page).

**Tk quality:** the CI freeze uses distro `python3.13-tk` (Xft). That is independent of your host’s source-venv Tk; the package embeds the build-time Tk stack inside `bin/`.

CI entry points: `.github/workflows/release.yml` (`platform: linux` on `workflow_dispatch` for dry runs), `scripts/assemble_linux_package.sh`.

## Platform code

OS-facing helpers live under **`src/platform/`** (no GUI imports):

| Module                          | Responsibility                                                             |
| ------------------------------- | -------------------------------------------------------------------------- |
| `detect.py`                     | `is_windows` / `is_linux` / `is_wayland`                                   |
| `ipc.py` / `single_instance.py` | Trigger protocol + instance lock                                           |
| `clipboard.py`                  | `wl-copy` / `wl-paste`, primary, hybrid selection helper                   |
| `pointer.py`                    | Best-effort compositor cursor lookup (Hyprland; optional Sway seat fields) |
| `input.py`                      | `wtype` / `wlrctl` type and key chords                                     |
| `console_input.py`              | Non-blocking single-key TTY input (`termios` cbreak / Windows `msvcrt`)    |
| `screenshot.py`                 | `grim` / `slurp`                                                           |

Audio import dispatch: `src/audio/backend.py` (WPatch on Windows, stock PyAudio on Linux). Device enumeration: `src/audio/devices.py`. Linux system-audio monitors: `src/audio/pulse_monitors.py` (`pactl list sources`) + ffmpeg pulse capture in `recorder.py`. Mic capture still uses PortAudio. Need `pactl` (pulseaudio-utils / PipeWire) and `ffmpeg` with pulse input for loopback when PortAudio is ALSA-only.

Interactive console commands (`--show-console`) and batch Pause/Stop keys use `src/platform/console_input.py`: hold **cbreak** for single-key polls, restore **cooked** mode around `input()` line prompts.

## Known limitations

- Pure Wayland apps that ignore virtual keyboard or selection protocols may not accept type/paste/hybrid capture.
- **Direct Chat:** tray **Direct Chat** and `--trigger chat` always open the input popup; they never capture the primary selection or clipboard. Use `--trigger textedit` for selection-based actions.
- **Selections:** Wayland primary selection can remain indefinitely after a mouse highlight even after deselecting. TextEdit uses an active Ctrl+C query directly into the focused application (works with Google Docs, browser canvas/DOM, and text editors) to avoid resurrecting stale primary selections. Terminal mouse selection fallback can be enabled via `linux_selection_fallback_primary = true` in `config.ini`.
- **Terminal-safe selection:** When the focused window is a terminal emulator, TextEdit automatically reads its Wayland primary selection and sends **no copy shortcut**. This prevents Ghostty and similar terminals from passing Ctrl+Shift+C through as Ctrl+C when nothing is selected, which could interrupt the foreground process. If no terminal selection exists, TextEdit opens its normal input popup. Terminal detection uses compositor IPC (`niri msg`, `swaymsg`, `hyprctl`) to read the focused window's `app_id`. Configure via `text_edit_terminal_copy_shortcut` in `config.ini`: `auto` (default, safe primary-selection capture), `always_ctrl_c`, or `always_ctrl_shift_c`. Compare Mode accepts both Ctrl+C and Ctrl+Shift+C.
- **Popup position & focus:** Hyprland cursor IPC places popups near the visible cursor. On compositors without cursor IPC (niri, Sway), popups automatically center on the currently focused monitor via compositor output queries (avoiding stale Xwayland cursor traps from apps like ONLYOFFICE) and use borderless managed splash windows so the active workspace immediately receives keyboard focus.
- Snip UX uses **slurp** (not the Windows frozen dim overlay).
- Interactive console keys require a real TTY (`stdin.isatty()`); headless launches (such as autostart) can be attached interactively via tray **Open Terminal (tmux)** or `tmux attach-session -t aipromptbridge` when `tmux` is installed.
- Self-update **apply** works for compiled installs on both Windows and Linux; source installs are notification-only.
- Multi-compositor (GNOME/KDE) support is best-effort; niri/wlroots is the validated target.
- **GUI fonts / corners:** uv standalone Python’s no-xft Tk cannot render modern fonts; use distro `python3.13-tkinter` (see above). Theme tweaks alone will not fix bitmap text.
- **Autostart:** XDG `.desktop` runs detached via `--tmux-detached` (managed by tmux when present); pure niri may still need `spawn-at-startup` (see above).

## Related docs

- Architecture overview: [ARCHITECTURE.md](ARCHITECTURE.md)
- Tree / module map: [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)
- Agent constraints (sparse): root `AGENTS.md`
- Historical design notes: `plans/linux-wayland-lessons-from-writingtools.md`
