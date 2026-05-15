# Project Structure

AIPromptBridge follows a modular architecture separating the web server, GUI, system tray, AI providers, and tools.

```
AIPromptBridge/
├── main.py                     # Main entry point (Internal logic)
├── launcher_gui.py             # GUI Launcher (cx_Freeze script)
├── launcher_console.py         # Console Launcher (cx_Freeze script)
├── requirements.txt            # Python dependencies
├── config.ini                  # Configuration (auto-generated on first run)
├── chat_sessions.json          # Saved chat sessions (auto-created)
├── prompts.json                # Unified prompt configuration (TextEdit, Snip, Endpoints)
├── profiles.json               # Connection profiles (auto-generated on first run)
├── keys.json                   # API key pools, XOR-obfuscated (auto-created on first run)
├── tools_config.json           # Tools configuration (auto-generated on demand)
├── session_attachments/        # Directory for message attachment files
├── icon.ico                    # System tray icon
├── assets/
│   ├── emojis.zip              # Twemoji assets
│   └── snip.wav                # Screen snip sound effect
├── LICENSE
├── README.md
│
├── docs/                       # Documentation
│   ├── PROJECT_STRUCTURE.md    # This file
│   ├── ARCHITECTURE.md         # Technical architecture details
│   ├── BUILD_PROCESS.md        # Build system & architecture decisions
│   └── SHAREX_SETUP.md         # ShareX integration guide
│
└── src/
    ├── __init__.py
    ├── api_client.py           # Unified API interface using providers
    ├── attachment_manager.py   # Persistent storage for session attachments
    ├── config.py               # Custom INI parser, configuration management, change notification pub/sub
    ├── console.py              # Centralized Rich console configuration
    ├── key_manager.py          # API key rotation with exhaustion tracking and named key lookup
    ├── messages.py             # Multimodal message construction factory
    ├── connection_profiles.py  # Connection profile store (profiles.json CRUD, ProfileStore singleton)
    ├── profile_resolver.py      # Connection profile resolution (per-action AI config overrides)
    ├── request_pipeline.py     # Unified request processing with logging
    ├── session_manager.py      # Session persistence with sequential IDs and per-session model override
    ├── terminal.py             # Interactive terminal commands (includes Tools menu)
    ├── tray.py                 # System tray application (Windows)
    ├── updater.py              # Self-update: GitHub Releases check, download, staging, trigger
    ├── utils.py                # Utility functions and build state detection (is_compiled)
    ├── version.py              # Application version source of truth
    ├── web_server.py           # Flask server and API endpoints
    │
    ├── audio/                  # Audio Subsystem
    │   ├── __init__.py
    │   ├── devices.py          # PyAudioWPatch device enumeration
    │   ├── export.py           # Centralized audio export, compression, and metadata embedding
    │   ├── ffmpeg_utils.py     # Shared FFmpeg/FFprobe/FFplay detection and helpers
    │   ├── recorder.py         # Recorder class with recording, playback, and compression
    │   ├── tts_constants.py    # TTS voice list and model constants
    │   └── wav_utils.py        # PCM-to-WAV conversion and WAV file utilities
    │
    ├── gui/                    # GUI Package (CustomTkinter)
    │   ├── __init__.py
    │   ├── audio_tool.py       # Audio Tool application controller
    │   ├── core.py             # GUICoordinator singleton for thread-safe GUI
    │   ├── custom_widgets.py   # Reusable UI components (ScrollableButtonList, ScrollableComboBox)
    │   ├── emoji_renderer.py   # Twemoji-based color emoji support for Windows
    │   ├── hotkey.py           # Global hotkey listener (pynput)
    │   ├── platform.py         # UI toolkit authority (HAVE_CTK and fallback logic)
    │   ├── popups.py           # Modern themed popups with scrollable ModifierBar
    │   ├── prompts.py          # Unified PromptsConfig loader/manager
    │   ├── screen_snip.py      # Screenshot capture and overlay
    │   ├── snip_popup.py       # Popup UI for screen snipping results
    │   ├── snip_tool.py        # Screen Snip controller application
    │   ├── text_edit_tool.py   # TextEditTool application controller
    │   ├── text_handler.py     # Text selection and replacement
    │   ├── themes.py           # ThemeRegistry with multi-theme support
    │   ├── utils.py            # GUI utilities (clipboard, markdown render)
    │   └── windows/            # Modular window implementations
    │       ├── __init__.py
    │       ├── audio_analyzer.py   # Audio recording and analysis UI
    │       ├── audio_analyzer_tk.py # Tkinter fallback for Audio Analyzer
    │       ├── chat_base.py        # Base classes for chat windows
    │       ├── chat_window.py      # Interactive chat window
    │       ├── prompt_editor/      # Prompt editor package (modularized)
    │       │   ├── __init__.py         # Public API re-exports
    │       │   ├── data.py             # JSON I/O, constants
    │       │   ├── dialogs.py          # TestResultDialog
    │       │   ├── editor.py           # Core PromptEditorWindow (mixin composition)
    │       │   ├── tab_actions.py      # Actions tab mixin
    │       │   ├── tab_settings.py     # Settings tab mixin
    │       │   ├── tab_modifiers.py    # Modifiers tab mixin
    │       │   ├── tab_groups.py       # Groups tab mixin
    │       │   ├── tab_playground.py   # Playground tab mixin
    │       │   └── tab_tts_playground.py # TTS playground mixin
    │       ├── session_browser.py  # Session history browser
    │       ├── settings_window/    # Settings window package (modularized)
    │       │   ├── __init__.py         # Public API re-exports
    │       │   ├── config_io.py        # ConfigData, parse/save config.ini
    │       │   ├── widgets.py          # ToggleSwitch, FormFieldsMixin (uniform layout)
    │       │   ├── core.py             # Core SettingsWindow (mixin composition)
    │       │   ├── tab_general.py      # General tab mixin (startup, behavior, updates)
    │       │   ├── tab_provider.py     # Provider tab mixin (profile selector, key pools, requests)
    │       │   ├── tab_generation.py   # Generation tab mixin (typing speed settings)
    │       │   ├── tab_tools.py        # Tools tab mixin (TextEdit, ScreenSnip, Audio)
    │       │   ├── tab_tts.py          # TTS tab mixin (voice, director, export)
    │       │   ├── tab_keys.py         # API Keys tab mixin
    │       │   ├── tab_endpoints.py    # Endpoints tab mixin
    │       │   └── tab_theme.py        # Theme tab mixin (theme, chat colors, preview)
    │       ├── connection_manager.py   # Connection Profile Manager window
    │       ├── tts_window.py       # TTS UI (voice selection, AI Director, playback)
    │       └── utils.py            # Window management utilities
    │
    ├── providers/              # AI Provider Implementations
    │   ├── __init__.py         # Provider exports and factory
    │   ├── base.py             # Abstract base provider, retry logic, ProviderResult
    │   ├── gemini_native.py    # Native Gemini API (Batch, Files API, TTS support)
    │   └── openai_compatible.py # OpenRouter, Custom, Google OpenAI-compat
    │
    └── tools/                  # Tools Package - Batch file processing
        ├── __init__.py         # Tool exports
        ├── audio_processor.py  # Audio optimization, chunking, and FFmpeg wrapper
        ├── base.py             # Abstract BaseTool class
        ├── checkpoint.py       # Checkpoint/resume system (Retry Checkpoint support)
        ├── config.py           # Tools configuration loader
        ├── file_handler.py     # File type detection, PDF support, multimodal handling
        └── file_processor.py   # Interactive File Processor (Batch/Files API logic)
```

## Key Modules

### Core (`src/`)

| Module | Purpose |
|--------|---------|
| `tray.py` | System tray icon with console show/hide, restart, session browser |
| `web_server.py` | Flask REST API endpoints for image processing |
| `terminal.py` | Interactive terminal commands when console is visible |
| `console.py` | Centralized Rich console configuration with custom theme |
| `config.py` | Custom INI parser with multiline support, key name parsing, change notification pub/sub |
| `key_manager.py` | Multi-key management with automatic rotation and named key lookup |
| `connection_profiles.py` | Connection profile store — `ProfileStore` singleton, `profiles.json` CRUD |
| `profile_resolver.py` | Connection profile resolution (merges per-action profile overrides with active profile) |
| `request_pipeline.py` | Unified logging and token tracking for all requests |
| `session_manager.py` | Chat session persistence to JSON with per-session model override |
| `attachment_manager.py`| Manages external file storage for session attachments |
| `updater.py` | Self-update: GitHub API, download, extraction, launcher signaling |

### GUI (`src/gui/`)

| Module | Purpose |
|--------|---------|
| `core.py` | GUICoordinator singleton managing all CustomTkinter windows |
| `emoji_renderer.py` | EmojiRenderer for Windows color emoji support (Twemoji) |
| `custom_widgets.py` | Custom scrollable lists and emoji-aware dropdowns (ScrollableComboBox) |
| `text_edit_tool.py` | Global hotkey TextEditTool application |
| `snip_tool.py` | Screen Snipping application controller (`Ctrl+Alt+X`) |
| `platform.py` | Central authority for UI toolkit availability and toolkit fallback |
| `windows/` | Modular package for application windows |
| `popups.py` | Themed popup dialogs with dual inputs (Edit/Ask) and scrollable ModifierBar |
| `hotkey.py` | pynput-based global hotkey listener |
| `themes.py` | ThemeRegistry with 7 themes, dark/light variants, system detection |
| `windows/settings_window/` | Modular settings window package (mixin-based, 12 files) |
| `windows/prompt_editor/` | Modular prompt editor package (mixin-based, 10 files) |

### Providers (`src/providers/`)

| Module | Purpose |
|--------|---------|
| `base.py` | Abstract BaseProvider with retry logic |
| `openai_compatible.py` | OpenAI API format (OpenRouter, custom endpoints) |
| `gemini_native.py` | Native Google Gemini API with thinking and TTS support |

### Tools (`src/tools/`)

| Module | Purpose |
|--------|---------|
| `base.py` | Abstract BaseTool class with pause/resume support |
| `checkpoint.py` | Checkpoint persistence for interrupted batch processing |
| `config.py` | Tools configuration loader with on-demand creation |
| `defaults.py` | Default settings and prompts for tools |
| `file_handler.py` | File type detection, directory scanning, API message building |
| `file_processor.py` | File Processor tool - batch process images/text/code with AI |

## Tools Configuration

The `tools_config.json` file (auto-created on demand) contains:
- Tool prompts (OCR, Describe, Summarize, Code Review, etc.)
- Output modes (individual files or combined)
- File type mappings for auto-detection
- Settings (delay between requests, checkpoint options)

Access via terminal: Press `[X]` → `[1] File Processor`