# Build Process & Architecture Decisions

This document outlines the build process for AIPromptBridge and documents key architectural decisions for packaging.

> **Windows** uses a split launcher (cx_Freeze) + Nuitka internal binary.  
> **Linux** uses a thin shell launcher + Nuitka internal binary (no cx_Freeze).  
> Source installs remain fully supported on both platforms (`uv run main.py`). See [LINUX.md](LINUX.md).

## Overview

Both official packages use a **split layout** so config stays CWD-relative at the deploy root while heavy deps live under `bin/`:

| | Windows | Linux |
|--|---------|--------|
| **Root launcher** | `AIPromptBridge.exe` / `AIPromptBridge-NoConsole.exe` (cx_Freeze) | `AIPromptBridge` (shell wrapper) |
| **Internal app** | `bin/AIPromptBridge_Internal.exe` (Nuitka standalone) | `bin/AIPromptBridge_Internal` (Nuitka standalone) |
| **Artifact** | `AIPromptBridge-vX.Y.Z-windows-x86_64.zip` | `AIPromptBridge-vX.Y.Z-linux-x86_64.tar.gz` |
| **Self-update apply** | Yes (launcher exit 42 / bin swap) | Notification + manual download (for now) |

## Component 1: The Launchers (Root)

### Windows — cx_Freeze

The launchers (`launcher_console.py` and `launcher_gui.py`) are compiled using **cx_Freeze**.

#### Why cx_Freeze?
*   **Clean Root Directory**: cx_Freeze places all dependency files in a `lib/` subdirectory, keeping the root folder clean (unlike Nuitka Standalone, which dumps many `.pyd` and `.dll` files next to the executable).
*   **AV Evasion**: cx_Freeze wrappers are generally less prone to false positives from antivirus software compared to compiled C# executables or PyInstaller bootloaders.
*   **Startup Speed**: Faster than Nuitka Onefile (which requires unpacking to a temp directory).
*   **Update apply**: Console launcher owns `bin/` replacement after the internal process exits with code 42.

#### Optimization Strategy
To keep the launcher footprint minimal (~6MB total), we aggressively strip unused libraries in `src/launchers/setup_launchers.py`:
*   **Excluded Packages**: `email`, `importlib` (partial), `ctypes`, `typing`, `distutils`, `multiprocessing`, `unittest`, `logging`.
*   **Zip Excludes**: We explicitly force the removal of persistent packages like `email` and `pkg_resources` from `library.zip`.
*   **Encoding Stripping**: We remove unused encodings, keeping only essentials like `utf-8`, `ascii`, and `mbcs`.

#### Known Limitations
*   **Duplicate Python DLL**: The root launcher requires `python313.dll` (or similar version) to be present in the root directory. This results in a duplication of the Python DLL (one in root for launcher, one in `bin/` for internal app).
    *   *Reason*: The Windows PE loader searches for DLLs in the executable's directory. We cannot easily point the root launcher to use the DLL in `bin/` without recompiling the cx_Freeze C stub or using unstable hacks.
    *   *Decision*: We accept the ~4MB duplication to maintain a clean file structure and AV safety.
*   **Symlinks**: We do **not** use symbolic links to deduplicate the DLL because they are unreliable in ZIP distributions (often failing extraction or requiring Admin privileges).

### Linux — shell wrapper

Linux does **not** use cx_Freeze. The outer launcher is `scripts/linux_launcher.sh`, installed as `AIPromptBridge` at the package root:

```bash
_LAUNCHER="$(readlink -f "${BASH_SOURCE[0]}")"   # resolve PATH symlinks
ROOT="$(cd "$(dirname "${_LAUNCHER}")" && pwd)"
# --trigger → system python3 + aipb_trigger.py (stdlib IPC, ~tens of ms)
# else     → Nuitka Internal with --launched-mode=console
exec "$ROOT/bin/AIPromptBridge_Internal" --launched-mode=console "$@"
```

`--launched-mode` is required: `main.setup_workspace()` refuses a bare internal binary so CWD/config always resolve to the deploy root (parent of `bin/`). Symlink resolution lets users put only a link on `PATH` (e.g. `~/.local/bin/AIPromptBridge` → install root) without breaking the `bin/` lookup.

**`--trigger` fast path:** compositor binds must not cold-start the ~100MB Nuitka tree. The outer launcher execs `aipb_trigger.py` (stdlib-only; also in source as `scripts/aipb_trigger.py` / `python -m src.platform.ipc`) so hotkeys stay in the tens of milliseconds.
## Component 2: The Internal Application (Bin)

The core application (`main.py`) is compiled using **Nuitka** in `standalone` mode on both platforms.

### Why Nuitka?
*   **Performance**: Compiles Python to C, offering better performance for the heavy logic.
*   **Dependency Management**: Nuitka's standalone mode is excellent at bundling complex dependencies like `customtkinter`, `rich`, and `PIL`.
*   **Isolation**: Placing the internal app in `bin/` allows it to have its own massive dependency tree without cluttering the user's root folder.

### Linux Tk / Xft requirement

CustomTkinter needs an **Xft-capable** Tk at freeze time. CI uses **deadsnakes `python3.13` + `python3.13-tk`** on Ubuntu 24.04 and **asserts** that Tk exposes more than a handful of font families before Nuitka runs. Freezing with a `no-xft` / bitmap-`fixed`-only Tk produces broken CTk corners and unreadable UI.

## Build Workflow (GitHub Actions)

Automated in `.github/workflows/release.yml`:

| Job | Runner | Role |
|-----|--------|------|
| `determine-version` | ubuntu | Resolve `vX.Y.Z`, platform flags (`all` / `windows` / `linux`), whether to publish |
| `build-windows` | windows-latest | Nuitka internal + cx_Freeze launchers → zip |
| `build-linux` | ubuntu-24.04 | System Python 3.13+Tk → Nuitka → `scripts/assemble_linux_package.sh` → tar.gz |
| `publish-release` | ubuntu | Download artifacts, extract CHANGELOG notes, create GitHub Release |

### Triggers

*   **Tag push** (`v*`): build **both** platforms and create a release.
*   **workflow_dispatch**: optional `version`, `release_notes`, `create_release`, and **`platform`** (`all` / `windows` / `linux`) for faster iteration (e.g. Linux-only dry runs with `create_release=false`).

### Windows steps (summary)

1. Setup Python 3.13.x; install `requirements.txt`.
2. Patch `src/version.py`.
3. Nuitka standalone → `build_internal/main.dist` (`AIPromptBridge_Internal.exe`).
4. cx_Freeze launchers → `build_launchers_cx/`.
5. Assemble `dist_final/` (launchers at root, internal under `bin/`).
6. Zip as `AIPromptBridge-<version>-windows-x86_64.zip`.

### Linux steps (summary)

1. Install deadsnakes Python 3.13, `python3.13-tk`, `patchelf`, `ccache`, PortAudio dev, `xvfb`.
2. **Font probe** under `xvfb-run` (fail if Tk font families ≤ 5).
3. venv on that interpreter; `pip install -r requirements.txt` + Nuitka.
4. Patch `src/version.py`.
5. `python -m nuitka --standalone … --output-filename=AIPromptBridge_Internal main.py`.
6. `scripts/assemble_linux_package.sh` → tarball with launcher + `README-linux.txt`.

### Local Linux assemble (after a local Nuitka build)

```bash
# Only when debugging CI (~25–30 min full Nuitka compile)
python3.13 -m nuitka --standalone --output-dir=build_internal \
  --output-filename=AIPromptBridge_Internal --enable-plugin=tk-inter \
  --include-data-dir=assets=assets --include-data-files=icon.ico=icon.ico \
  --include-package=rich --include-package-data=customtkinter \
  --include-package-data=emoji main.py
./scripts/assemble_linux_package.sh v0.0.0-dev .
```

Prefer validating via GHA `workflow_dispatch` with `platform=linux` and `create_release=false` instead of local compiles.

## Runtime system deps (Linux package)

Not bundled; same as source install:

| Package | Role |
|---------|------|
| `wl-clipboard`, `wlrctl` | clipboard / type-paste |
| `grim`, `slurp` | snip |
| `pactl`, `ffmpeg` | system-audio loopback |
| `libportaudio2` | mic (if not fully bundled into `.dist`) |
| StatusNotifier host | tray |

**glibc baseline**: Ubuntu 24.04 x86_64. Older distros may need a source install.

## Related code

*   `main.setup_workspace()` — compiled CWD / `--launched-mode` gate  
*   `src/startup_manager.py` — launcher discovery (`AIPromptBridge` on Linux, `.exe` on Windows)  
*   `src/updater.py` — platform asset selection; in-place apply is Windows-only  
*   `scripts/linux_launcher.sh`, `scripts/assemble_linux_package.sh`, `scripts/README-linux.txt`
