# Linux Support (Wayland / niri)

AIPromptBridge runs on **Windows** (primary) and **Linux Wayland** (wlroots compositors such as **niri**). Linux is source-install oriented: config stays **CWD-relative** (portable layout). Official split-build packaging (cx_Freeze / Nuitka) remains Windows-focused.

Python: **3.13.x** (see `.python-version`). Install deps with `uv pip install -r requirements.txt` (platform markers skip Windows-only packages on Linux).

## Quick start

```bash
cd /path/to/AIPromptBridge
uv venv && source .venv/bin/activate   # if needed
uv pip install -r requirements.txt
uv run main.py --show-console
```

Trigger tools from another terminal or a window-manager bind (no in-process global hotkeys on pure Wayland):

```bash
uv run main.py --trigger textedit   # also: snip, audio, tts, chat, browser, settings, prompts
```

Example **niri** binds (adjust path / `uv` as needed):

```kdl
binds {
    Mod+Shift+T { spawn-sh "cd /path/to/AIPromptBridge && uv run main.py --trigger textedit"; }
    Mod+Shift+S { spawn-sh "cd /path/to/AIPromptBridge && uv run main.py --trigger snip"; }
    Mod+Shift+A { spawn-sh "cd /path/to/AIPromptBridge && uv run main.py --trigger audio"; }
}
```

## System packages

| Package / binary | Role |
|------------------|------|
| **`python3.13` + `python3.13-tkinter`** (distro) | **GUI:** Xft-capable Tk (real fonts + rounded CTk widgets). Prefer over uv’s standalone CPython for the venv. |
| `wl-clipboard` (`wl-copy`, `wl-paste`) | Clipboard + primary selection |
| `wlrctl` | Virtual keyboard: type, Ctrl+V/C (TextEdit replace/type, hybrid capture) |
| `grim`, `slurp` | Screen region capture (SnipTool) |
| PortAudio (+ `PyAudio` wheel) | Mic + desktop-monitor recording |
| Optional: `paplay` / `pw-play` / `ffplay` | Snip/textedit feedback sounds |
| StatusNotifier host (e.g. dms, waybar) | Tray icon via `pystray` |

Python deps with markers: `pystray` and `PyAudio` on Linux; `infi.systray` and `PyAudioWPatch` on Windows only.

### CustomTkinter / Tk fonts (important)

CustomTkinter draws rounded corners with a special shapes font (`font_shapes`) and expects real FreeType fonts via **LibXft**.

**uv’s standalone CPython** (python-build-standalone) ships Tk built **`no-xft`**. On those interpreters Tk only exposes the bitmap font `fixed`, so:

| Symptom | Cause |
|---------|--------|
| Broken / “corrupted” corners on every CTk widget | Shapes font falls back to `fixed`; `font_shapes` drawing fails |
| Pixelated / horrendous UI text | No Xft → no Roboto/Noto/DejaVu in Tk |

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

| Feature | Windows | Linux (Wayland / niri) |
|---------|---------|-------------------------|
| Start tools | Global hotkeys (pynput) + tray | **IPC** `--trigger` + tray (if SNI host) |
| Single instance | Named mutex | Unix socket bind (same path as IPC) |
| Tray | `infi.systray` | `pystray` (AppIndicator / StatusNotifier) |
| Selection capture | SendInput Ctrl+C + clipboard sequence | Primary selection first; hybrid **Ctrl+C** via `wlrctl` if empty |
| Type / paste into apps | pynput / SendInput | `wlrctl` (+ `wl-copy` for paste) |
| Snip | Tk overlay + `PIL.ImageGrab` | `slurp` geometry + `grim -g` → same `CaptureResult` |
| System audio | WASAPI loopback (PyAudioWPatch) | PipeWire/Pulse **monitor** sources via `pactl` + `ffmpeg -f pulse` (PortAudio often has no Pulse host API) |
| Sounds | `winsound` | `paplay` / `pw-play` / `ffplay` |

## Platform code

OS-facing helpers live under **`src/platform/`** (no GUI imports):

| Module | Responsibility |
|--------|----------------|
| `detect.py` | `is_windows` / `is_linux` / `is_wayland` |
| `ipc.py` / `single_instance.py` | Trigger protocol + instance lock |
| `clipboard.py` | `wl-copy` / `wl-paste`, primary, hybrid selection helper |
| `input.py` | `wlrctl` type and key chords |
| `console_input.py` | Non-blocking single-key TTY input (`termios` cbreak / Windows `msvcrt`) |
| `screenshot.py` | `grim` / `slurp` |

Audio import dispatch: `src/audio/backend.py` (WPatch on Windows, stock PyAudio on Linux). Device enumeration: `src/audio/devices.py`. Linux system-audio monitors: `src/audio/pulse_monitors.py` (`pactl list sources`) + ffmpeg pulse capture in `recorder.py`. Mic capture still uses PortAudio. Need `pactl` (pulseaudio-utils / PipeWire) and `ffmpeg` with pulse input for loopback when PortAudio is ALSA-only.

Interactive console commands (`--show-console`) and batch Pause/Stop keys use `src/platform/console_input.py`: hold **cbreak** for single-key polls, restore **cooked** mode around `input()` line prompts.

## Known limitations

- Pure Wayland apps that ignore virtual keyboard or selection protocols may not accept type/paste/hybrid capture.
- Snip UX uses **slurp** (not the Windows frozen dim overlay).
- Interactive console keys require a real TTY (`stdin.isatty()`); piped/redirected stdin falls back to tray / `--trigger`.
- Self-update **apply** path is Windows launcher-oriented; source installs stay notification-oriented.
- Multi-compositor (GNOME/KDE) support is best-effort; niri/wlroots is the validated target.
- **GUI fonts / corners:** uv standalone Python’s no-xft Tk cannot render modern fonts; use distro `python3.13-tkinter` (see above). Theme tweaks alone will not fix bitmap text.

## Related docs

- Architecture overview: [ARCHITECTURE.md](ARCHITECTURE.md)
- Tree / module map: [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)
- Agent constraints (sparse): root `AGENTS.md`
- Historical design notes: `plans/linux-wayland-lessons-from-writingtools.md`
