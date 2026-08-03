---
description: Core project guidelines for AIPromptBridge. Apply when working on code, configuration, or documentation.
alwaysApply: true
inclusion: always
---

# AGENTS.md

Guidance for AI agents working in this repo.

## Project Overview

AIPromptBridge — Windows-first Python desktop app (Linux Wayland / niri supported). Tray + tools + Flask; hotkeys on Windows, IPC `--trigger` on Linux. OS I/O: `src/platform/`. Details: `docs/LINUX.md`.

## Commands

- **Run**: `uv run main.py` (option: `--show-console`)
- **Linux trigger**: `AIPromptBridge --trigger snip|…` (compiled: fast `aipb_trigger.py`) or `python -m src.platform.ipc snip` / `python3 scripts/aipb_trigger.py snip` (source). Requires running instance; do not cold-start Nuitka for binds.
- **Install deps**: `uv pip install -r requirements.txt` (Python **3.13.x**; see `.python-version`)
- **Linux GUI fonts**: For **source/venv** runs, prefer distro `python3.13` + `python3.13-tkinter` (Xft Tk). uv standalone CPython ships **no-xft** Tk → bitmap `fixed` only, broken CTk corners. App auto-falls back to `circle_shapes` via `src/gui/ctk_bootstrap.py`; source runs still need distro Tk for full text quality. Compiled releases already bundle the build-time Xft Tk stack, so the host's distro Python/Tk is not a runtime requirement. Details: `docs/LINUX.md`.

## Testing & Quality (optional, only do at the end)

- **Commands**: `uv pip install -r requirements-dev.txt`, `uv run run_tests.py` (runs Ruff linter, Ruff formatter check, and Pytest unit tests in one command)
- **Conventions**: Test files live in `test/` (e.g. `test_*.py`). New tests use pytest-style `assert` (no `self.assertEqual`). No `sys.path` hacks in tests (handled by `test/conftest.py`). Never leave ephemeral debug files in `test/` — delete after implementation confirmed working.

## Critical Architectural Constraints & Gotchas

### 1. GUI Threading & Dual-UI System (CRITICAL)
- **Central Authority**: All GUI modules MUST import `ctk`, `CTkImage`, `HAVE_CTK` from `src/gui/platform.py`.
- **Linux CTk bootstrap**: `configure_ctk_rendering()` in `src/gui/ctk_bootstrap.py` runs on CTk import (best-effort) and again from `GUICoordinator` with the live root. Do not set `DrawEngine.preferred_drawing_method` ad hoc in individual windows.
- **Single Root**: Managed by `GUICoordinator` in `src/gui/core.py` (main thread only). **DO NOT create new `ctk.CTk()` or `tk.Tk()` instances**.
- **Dual-UI Requirement**: Every major window must support both CustomTkinter and standard Tkinter (controlled via `ui_force_standard_tk`). New UI features → update both CTk code and `_tk.py` fallback (e.g., `audio_analyzer.py` and `audio_analyzer_tk.py`).
- **Rich Text / Markdown**: `CTkTextbox` lacks text tag support. Chat/results use hybrid: standard `tk.Text` widgets styled like CTk, inside `CTkFrame` containers.
- **Font Thread-Safety**: Use `get_ctk_font()` from `src/gui/themes.py` — returns **tuple** (family, size, weight). `CTkFont` in non-main threads → `RuntimeError`.
- **DPI Scaling for Raw Tk Widgets**: Standard Tk widgets (`tk.Label`, `tk.Text`, `tk.Checkbutton`, etc.) do not scale automatically under CustomTkinter's DPI scaling. For these raw widgets, use `get_tk_font(size, weight, family)` or scale sizes manually via `scaled_tk_size(size)` from `src/gui/themes.py` to maintain consistent layout sizes screen-wide.
- **Window Modules**: In `src/gui/windows/` (e.g., `chat_window.py`, `session_browser.py`). Prompt Editor (`src/gui/windows/prompt_editor/`) and Settings Window (`src/gui/windows/settings_window/`) are sub-packages with mixin classes per tab.
- Window creation thread-safe via queue-based requests.
- Standalone windows use update-based loop for thread coexistence.
- **DO NOT create new `ctk.CTk()` or `tk.Tk()` instances** — use `GUICoordinator` request methods.

### 2. Provider System (MANDATORY)

All API calls MUST flow through `src/providers/` — resolve/instantiate providers via `create_provider()` in `src/providers/registry.py`, not direct subclass initialization:
- `GeminiNativeProvider`: Native Gemini API (pure generation pipeline). Large file uploads and other side operations are delegated to `gemini_services.py`.
- `AnthropicProvider`: Native Anthropic Claude Messages API (streaming, adaptive thinking configuration).
- `OpenAICompatibleProvider`: Multi-tenant handler for OpenAI, OpenRouter, xAI (Grok), Mistral, Cohere, and Custom OpenAI-compatible endpoints.
- **Content Ordering**: Providers auto-handle optimal content ordering (e.g., Gemini prefers Media First → Text Last for context caching).
- **Inline Thinking**: Models emitting inline reasoning blocks are parsed via `extract_leading_thinking_blocks()` from `inline_thinking.py`.
- Never use raw `requests.post()` for AI APIs

### 3. Request Pipeline (OBSERVABILITY)

Always use `RequestPipeline` from `src/request_pipeline.py` for API calls:
- Consistent logging and token tracking
- Origin tracking (CHAT_WINDOW, POPUP_INPUT, SNIP_TOOL, AUDIO_TOOL, TTS_TOOL, ENDPOINT, etc.)
- Automatic token usage logging to console

### 4. Message Factory (Centralized Payloads)

All multimodal API message construction MUST use `src/messages.py`:
- **Factory**: Methods like `build_text_message`, `build_audio_message` (`inline_data`), `build_image_message` (`image_url`), `build_file_message` (Files API).
- **Compatibility**: Standardized formats (`inline_data` for audio/small files) that providers adapt.
- **Usage**: GUI tools (`AudioTool`, `SnipTool`) and CLI tools (`FileProcessor`) delegate here instead of manual dict construction.

### 5. Audio Subsystem (Queue-Based Stream)
- Import via `src/audio/backend.py`: **PyAudioWPatch** (Windows WASAPI loopback) / stock **PyAudio** (Linux mics).
- Linux **system audio**: `src/audio/pulse_monitors.py` (`pactl`) + `ffmpeg -f pulse` in `AudioRecorder` (PortAudio often lacks Pulse host API / `*.monitor` names).
- `AudioRecorder` **Unified Stream**: open once for level meter; record via flag + `Queue` (don't stop stream at boundaries).
- **FFmpeg**: `get_creation_flags()` for `CREATE_NO_WINDOW` on Windows. Detection in `src/audio/ffmpeg_utils.py`.
- **Export**: `src/audio/export.py` for all saved audio (Opus/MP3/AAC, metadata, safe names).

### 6. Session Management & Origin Tracking
- Sessions do NOT store provider info (read dynamically for hot-switching).
- **Per-Session Model Override**: `session.model_override` — each chat window selects model independently. `None` = global config model. Chat dropdown shows `"(Use Global: <model>)"` sentinel, updates via `subscribe_config_change()`.
- **Origin Field**: Sessions track creation source (e.g., `textedit:Explain`, `snip:Extract Text`).
- **Origin-Aware System Prompts**: When `chat_use_origin_system_prompt` true, chat windows persist originating action's `system_prompt` from `prompts.json` instead of global chat instruction.
- **Attachment Storage**: Media NOT stored as base64 in session JSON. Stored externally via `AttachmentManager` in `session_attachments/`.

### 7. API Key Management & Rotation
- **KeyStore** (`src/key_store.py`): Singleton, pool-based storage in `keys.json`. Keys XOR-obfuscated at rest. All key access MUST go through `KeyStore.get_instance()`, never direct file reads.
- Keys grouped into named **pools** (`google`, `anthropic`, `openai`, `openrouter`, `xai`, `mistral`, `cohere`, `custom` built-in). Providers map to pools via `provider_pool_map`; users create custom pools and reassign dynamically.
- **Migration**: First launch without `keys.json` → auto-migrate from `config.ini` + env vars. After that, `config.ini` key sections ignored.
- `load_config()` returns `config` dict. Connection settings (provider, model, streaming, thinking, ai_params) are owned by Connection Profiles — injected into CONFIG at startup via `ensure_config_connection_keys()` + `populate_config()`. Endpoints loaded from `prompts.json` defaults.
- **KeyManager** (`src/key_manager.py`): Built by `KeyStore.build_key_managers()`. 429/401/403 → immediate key rotation; 5xx/empty → delay + retry same key.

### 8. Streaming & Keyboard Injection
- **Windows**: pynput / SendInput; streaming type uses ~20-char buffer (`MIN_BUFFER_CHARS`) + small per-char delay.
- **Linux**: `src/platform/input.py` (`wlrctl`) for type/paste; chunked type (no per-char subprocess spam). Selection: primary first, hybrid Ctrl+C via wlrctl if empty (`clipboard.py`).
- **Typing Indicator**: `TypingIndicator` tooltip during streaming with abort hotkey.

### 9. Specific Provider Quirks
- **Gemini Safety**: Use `BLOCK_NONE` threshold, not `OFF`.
- **Thinking Config**: Dynamic per provider:
  - OpenAI-compatible: `reasoning_effort` (low/medium/high)
  - Gemini 2.5: `thinking_budget` (integer)
  - Gemini 3.x: `thinking_level` (low/high)
- **Large Files (>15MB)**: Gemini Native auto-routes through Google **Files API** (`upload_file`) instead of inline Base64.

### 10. Tool Architectures
- **TextEditTool**: Dual input (Edit/Ask), Compare Mode, ModifierBar. Linux invoke: `--trigger textedit` (no pynput hotkeys).
- **SnipTool**: Windows `ScreenSnipOverlay`+ImageGrab; Linux `grim`/`slurp` → same `CaptureResult` → `SnipPopup` → API.
- **AudioTool**: Controller + `AudioAnalyzerWindow` (mic / loopback-or-monitor).
- **TTS Tool**: Bypasses `RequestPipeline` (Gemini-only). 24kHz PCM → WAV (`wav_utils`) → `export.py`.

### 11. Batch Tools System (Sync/Async)

`src/tools/` handles batch processing:
- **Audio**: `ffmpeg` for optimization (Mono/16kHz) and chunking. FFmpeg binary detection centralized in `src/audio/ffmpeg_utils.py` (cached `shutil.which`). Import `is_ffmpeg_available()` from there or `src/audio`.
- **Batch API**: `GeminiNativeProvider` supports `create_batch()` for async large jobs.
- **Checkpoints**: `CheckpointManager` saves progress. **Failure Checkpoints** (`create_failed_checkpoint`) retry only failed files.
- **Console keys**: Non-blocking terminal input via `src/platform/console_input.py` (`msvcrt` on Windows, `termios` cbreak + `select`/`os.read` on Linux). Use `RawConsole` for command loops / Pause·Stop listeners; `line_input()` / `cooked()` around blocking `input()` prompts.
- **Debug Tool**: `python -m src.tools` for interactive file processing without full server.

### 12. Configuration & Hot-Reloading
- **config.ini**: Custom INI parser in `src/config.py` (multiline values, inline comments).
  - `SettingsWindow` edits `config.ini`;
  - **Change Notification**: `subscribe_config_change(cb)` / `notify_config_change(key, value)` — thread-safe pub/sub fired by `save_config_value()` and `SettingsWindow` bulk save. Listeners must marshal to GUI thread themselves.
- **prompts.json**: Unified config for TextEditTool, SnipTool, AudioTool, TTS. Created from defaults if missing.
  - `PromptsConfig` is live singleton. `reload_prompts()` refreshes whole app without restart.
  - `PromptEditorWindow` edits `prompts.json`.
- **tools_config.json**: File Processor tool config. Created on-demand.
- **keys.json**: Pool-based API key storage by `KeyStore` (`src/key_store.py`). Auto-created on first run via migration. Use `KeyStore.get_instance()` for all key access.
- **Config Preservation (prompts.json)**: Default actions carry `_is_default: true`. On load, `_ensure_sections()` deep-merges new defaults without overwriting user-modified actions (`_is_default: false`). Deleted defaults tracked in `_settings.deleted_defaults` to prevent re-insertion. String settings use `_settings.modified_settings` to protect user overrides. `popup_groups` deep-merged with `deleted_groups`/`deleted_group_items` exclusion lists.

### 13. LaTeX Rendering
- No heavy math libraries. `src/gui/latex_renderer.py` converts LaTeX strings to standard Unicode (e.g., `\alpha` → `α`) *before* markdown parsing.

### 14. Emoji Support (Windows Fix)
- Windows Tkinter can't render color emojis in Text widgets natively.
- **Text Widgets**: Use `insert_with_emojis(text_widget, text, tags)` from `src/gui/emoji_renderer.py`.
- **CTk Widgets**: Use `prepare_emoji_content(text, size)` — returns kwargs (`text`, `image`, `compound`) for `CTkButton` or `CTkLabel`.

### 15. Custom Widgets

`src/gui/custom_widgets.py` provides standardized high-level widgets:
- **Button Factory**: `create_emoji_button(parent, text, icon, colors, variant="primary", ...)` — fully styled button (CTk or Tk). Use for standard action buttons, ensures consistent theming.
- **Scrollable Lists**: `ScrollableButtonList` replaces native listboxes with rich button-based selection.
- **Components**: `ScrollableComboBox`, `create_section_header`, `upgrade_tabview_with_icons`.
- **Dialogs**: Use `ask_themed_string(parent, title, prompt, colors)` or `ThemedInputDialog` instead of `simpledialog.askstring` for UI consistency.

### 16. Workspace Management (Split Build)
- Split structure (Windows AV-friendly layout; Linux matches the same CWD rules):
  - **Root**: Windows `AIPromptBridge.exe` / `AIPromptBridge-NoConsole.exe` (cx_Freeze); Linux `AIPromptBridge` (shell wrapper in `scripts/linux_launcher.sh`).
  - **Bin**: `bin/AIPromptBridge_Internal[.exe]` (Nuitka standalone).
- **CWD Handling**: Compiled mode → `setup_workspace()` in `main.py` forces CWD to launcher's directory (parent of `bin/`), migrates stale config files via background thread.
- Internal binary without `--launched-mode` flag intentionally refuses to start.
- **CI packaging**: `.github/workflows/release.yml` builds Windows zip + Linux tar.gz; Linux freezes with **Xft system Tk** (deadsnakes `python3.13-tk`). Assemble via `scripts/assemble_linux_package.sh`. Details: `docs/BUILD_PROCESS.md`.

### 17. Console Output
- Do NOT use `print()`. Use `src/console.py`: `print_success()`, `print_error()`, `print_warning()`, `print_info()`, `print_panel()`.

### 18. Self-Update System
- **Two-phase**: `src/updater.py` downloads & extracts to `_update_staging/`. File replacement handled by launcher (can't overwrite running exe).
- **Signal**: Console mode exits code **42** for launcher apply. GUI mode spawns `AIPromptBridge.exe --apply-update <PID>`.
- **Recovery**: `startup_recovery()` runs early in `main()` — rollback or cleanup of interrupted updates (`_bin_old/`, stale manifests).
- **Source installs**: Notification-only (no auto-apply).

### 19. Connection Profiles
- **ProfileStore** (`src/connection_profiles.py`): Singleton, thread-safe load/save of `profiles.json`. `ConnectionProfile` dataclass — every field always populated (no sparse fallbacks).
- **Storage**: Dedicated `profiles.json`. Auto-created with "Default" profile on first load.
- **Resolution** (`src/profile_resolver.py`): Per-session profile override → Action's `connection_profile` → Active global profile → Hard-coded defaults.
- **Runtime Switching**: `switch_active_profile()` in `web_server.py` updates CONFIG, AI_PARAMS, key managers, fires `_bulk_update` notification.
- **GUI**: `ConnectionProfileManager` window (`src/gui/windows/connection_manager.py`). Accessible via Settings Window "Manage Profiles" button, tray menu, and terminal `P` command.
- **Fields**: `provider`, `model`, `streaming`, `thinking`, `thinking_budget`, `thinking_level`, `reasoning_effort`, `temperature`, `max_tokens`, `request_timeout`, `base_url`, `api_key_name`, `api_key_pool`.

### 20. Platform layer (Linux / dual-OS)
- Put OS I/O in `src/platform/` (no GUI imports): IPC, clipboard, input, screenshot, single-instance.
- Windows: keep Win32/pynput/WPatch paths behind `is_windows()`; do not force Linux CLIs on Windows.
- Linux system tools are **external** (`wl-clipboard`, `wlrctl`, `grim`, `slurp`, …) — detect with `shutil.which`, degrade gracefully. Full guide: `docs/LINUX.md`.
