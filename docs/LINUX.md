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
| `wl-clipboard` (`wl-copy`, `wl-paste`) | Clipboard + primary selection |
| `wlrctl` | Virtual keyboard: type, Ctrl+V/C (TextEdit replace/type, hybrid capture) |
| `grim`, `slurp` | Screen region capture (SnipTool) |
| PortAudio (+ `PyAudio` wheel) | Mic + desktop-monitor recording |
| Optional: `paplay` / `pw-play` / `ffplay` | Snip/textedit feedback sounds |
| StatusNotifier host (e.g. dms, waybar) | Tray icon via `pystray` |

Python deps with markers: `pystray` and `PyAudio` on Linux; `infi.systray` and `PyAudioWPatch` on Windows only.

## How Linux maps to features

| Feature | Windows | Linux (Wayland / niri) |
|---------|---------|-------------------------|
| Start tools | Global hotkeys (pynput) + tray | **IPC** `--trigger` + tray (if SNI host) |
| Single instance | Named mutex | Unix socket bind (same path as IPC) |
| Tray | `infi.systray` | `pystray` (AppIndicator / StatusNotifier) |
| Selection capture | SendInput Ctrl+C + clipboard sequence | Primary selection first; hybrid **Ctrl+C** via `wlrctl` if empty |
| Type / paste into apps | pynput / SendInput | `wlrctl` (+ `wl-copy` for paste) |
| Snip | Tk overlay + `PIL.ImageGrab` | `slurp` geometry + `grim -g` → same `CaptureResult` |
| System audio | WASAPI loopback (PyAudioWPatch) | PipeWire/Pulse **monitor** sources via PortAudio |
| Sounds | `winsound` | `paplay` / `pw-play` / `ffplay` |

## Platform code

OS-facing helpers live under **`src/platform/`** (no GUI imports):

| Module | Responsibility |
|--------|----------------|
| `detect.py` | `is_windows` / `is_linux` / `is_wayland` |
| `ipc.py` / `single_instance.py` | Trigger protocol + instance lock |
| `clipboard.py` | `wl-copy` / `wl-paste`, primary, hybrid selection helper |
| `input.py` | `wlrctl` type and key chords |
| `screenshot.py` | `grim` / `slurp` |

Audio import dispatch: `src/audio/backend.py` (WPatch on Windows, stock PyAudio on Linux). Device enumeration and monitor heuristics: `src/audio/devices.py`.

## Known limitations

- Pure Wayland apps that ignore virtual keyboard or selection protocols may not accept type/paste/hybrid capture.
- Snip UX uses **slurp** (not the Windows frozen dim overlay).
- Batch tools’ non-blocking terminal keys still assume Windows `msvcrt` in places.
- Self-update **apply** path is Windows launcher-oriented; source installs stay notification-oriented.
- Multi-compositor (GNOME/KDE) support is best-effort; niri/wlroots is the validated target.

## Related docs

- Architecture overview: [ARCHITECTURE.md](ARCHITECTURE.md)
- Tree / module map: [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)
- Agent constraints (sparse): root `AGENTS.md`
- Historical design notes: `plans/linux-wayland-lessons-from-writingtools.md`
