# Build Process & Architecture Decisions

This document outlines the build process for AIPromptBridge and documents key architectural decisions regarding the dual-launcher system.

## Overview

The application uses a split-process architecture to balance startup speed, file organization, and antivirus (AV) evasion.

*   **Root Directory**: Contains lightweight launchers (`AIPromptBridge.exe`).
*   **Bin Directory (`bin/`)**: Contains the heavy internal application (`AIPromptBridge_Internal.exe`) and all dependencies.

## Component 1: The Launchers (Root)

The launchers (`launcher_console.py` and `launcher_gui.py`) are compiled using **cx_Freeze**.

### Why cx_Freeze?
*   **Clean Root Directory**: cx_Freeze places all dependency files in a `lib/` subdirectory, keeping the root folder clean (unlike Nuitka Standalone, which dumps many `.pyd` and `.dll` files next to the executable).
*   **AV Evasion**: cx_Freeze wrappers are generally less prone to false positives from antivirus software compared to compiled C# executables or PyInstaller bootloaders.
*   **Startup Speed**: Faster than Nuitka Onefile (which requires unpacking to a temp directory).

### Optimization Strategy
To keep the launcher footprint minimal (~6MB total), we aggressively strip unused libraries in `src/launchers/setup_launchers.py`:
*   **Excluded Packages**: `email`, `importlib` (partial), `ctypes`, `typing`, `distutils`, `multiprocessing`, `unittest`, `logging`.
*   **Zip Excludes**: We explicitly force the removal of persistent packages like `email` and `pkg_resources` from `library.zip`.
*   **Encoding Stripping**: We remove unused encodings, keeping only essentials like `utf-8`, `ascii`, and `mbcs`.

### Known Limitations
*   **Duplicate Python DLL**: The root launcher requires `python313.dll` (or similar version) to be present in the root directory. This results in a duplication of the Python DLL (one in root for launcher, one in `bin/` for internal app).
    *   *Reason*: The Windows PE loader searches for DLLs in the executable's directory. We cannot easily point the root launcher to use the DLL in `bin/` without recompiling the cx_Freeze C stub or using unstable hacks.
    *   *Decision*: We accept the ~4MB duplication to maintain a clean file structure and AV safety.
*   **Symlinks**: We do **not** use symbolic links to deduplicate the DLL because they are unreliable in ZIP distributions (often failing extraction or requiring Admin privileges).

## Component 2: The Internal Application (Bin)

The core application (`main.py`) is compiled using **Nuitka** in `standalone` mode.

### Why Nuitka?
*   **Performance**: Compiles Python to C, offering better performance for the heavy logic.
*   **Dependency Management**: Nuitka's standalone mode is excellent at bundling complex dependencies like `customtkinter`, `rich`, and `PIL`.
*   **Isolation**: Placing the internal app in `bin/` allows it to have its own massive dependency tree without cluttering the user's root folder.

## Build Workflow

The build process is automated in `.github/workflows/release.yml`:

1.  **Setup**: Installs Python 3.13.x.
2.  **Build Internal**: Runs `Nuitka` to compile `main.py` into `build_internal/`.
3.  **Build Launchers**: Runs `cx_Freeze` via `src/launchers/setup_launchers.py` to compile launchers into `build_launchers_cx/`.
4.  **Assembly**:
    *   Moves internal build to `dist_final/bin/`.
    *   Moves launcher build (executables + DLLs + `lib/`) to `dist_final/` (root).
5.  **Packaging**: Zips `dist_final/` for release.
