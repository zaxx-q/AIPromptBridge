# Changelog

## [5.1.0] - 2026-02-17

### New Features

- **Launch on startup**: Add new option to allow AIPromptBridge to run automatically on Windows boot. Accessible via a new toggle in the Settings window.

### Changes

- **Hotkeys**: Modified default global hotkeys to use `Ctrl+Alt` instead of `Ctrl+Shift` to avoid conflicts with common Windows/app shortcuts:
  - Screen Snip: `Ctrl+Alt+X`
  - Audio Tool: `Ctrl+Alt+A`
  - TTS: `Ctrl+Alt+T`
- **Settings Layout**:
  - Moved "Windows Startup" configuration to the top of the Settings window for better visibility.
  - Relocated "Server Settings" to the bottom and added a safety lock that must be manually unchecked to edit host/port values.

### Improvements

- **Terminal Interface**: Reorganized the console command menu into clearer categories (Features, Info & Toggles) and updated hotkeys for consistency:
  - `[S]` Sessions (was L)
  - `[L]` List Sessions (was S status)
  - `[I]` Info/Status (new)
  - `[K]` Thinking Toggle (was T)
  - `[T]` TTS Window (was Y)
- **Settings UX**: Added explicit warnings when modifying server settings that require a restart.
- **Port Discovery**: Implemented automatic port discovery and conflict resolution for the local web server. The application will now check 20 subsequent ports if the configured port is occupied.
- **Single Instance**: Changed the mechanism to prevent multiple instances of AIPromptBridge from running simultaneously.

## [5.0.0] - 2026-02-17

### New Features

#### 🔊 Text-to-Speech (TTS)
- **Gemini TTS Integration**: Full support for Google's Gemini TTS models with streaming audio generation.
- **Voice Selection**: Access to 30 prebuilt voices with style and gender descriptors.
- **AI Director**: Intelligent style generation that analyzes text to provide expressive performance instructions (tone, pace, emotion) before synthesis.
- **Multi-Format Export**: Save generated audio as WAV, MP3, OGG, AAC, or FLAC (requires FFmpeg).
- **Multi-Speaker**: Support for assigning different voices to up to 2 distinct speakers in a single generation.
- **Integration Points**: Accessible via terminal `[T]`, system tray menu, and directly from input popups.
- **Tkinter Support**: Full functional fallback UI for standard Tkinter environments.

#### 🎤 Audio Tool Enhancements
- **File Upload**: Added support for uploading existing audio files for analysis, alongside live recording.
- **Unified Controls**: Consolidated Record/Stop and Play/Pause buttons into dynamic toggle controls for a cleaner UI.

#### ⚙️ Configuration & Playground
- **Live Preview**: Prompt Editor playground now updates in real-time as settings are modified.
- **Playground Audio**: Added ability to upload audio files directly in the Prompt Editor playground for testing.
- **TTS Settings**: Dedicated "TTS" tab in Settings Window and configuration section in Prompt Editor.

### Improvements

- **Session History**: Increased default maximum sessions from 50 to 200.
- **UI/UX**:
  - Relocated TTS buttons in popups for better layout consistency.
  - Added visual input validation feedback in popups.
  - Added tooltips to TTS controls for better discoverability.
- **Performance**: Centralized FFmpeg utility detection to reduce redundant system calls.

### Fixes

- **Threading**: Resolved thread-safety issues when accessing UI widgets from background threads in the TTS window.
- **Prompts**: Improved robustness of transcript detection to prevent text duplication in AI Director outputs.

## [4.3.2] - 2026-02-15

### Improvements

- **Attachments**: Implemented a background cleanup process to automatically remove orphaned attachment directories from deleted or missing sessions.

### Fixes

- **Console**: Bugfixes and adjustments to make console work reliably.

## [4.3.1] - 2026-02-14

### Fixes

- **Internal**: Renamed internal references to `AIPromptBridge.exe` (Console) and `AIPromptBridge-NoConsole.exe` (GUI)
- **System Tray**: Fix application restart logic to correctly handle both launcher-based and source-based execution modes.
- **UX**: Added a native Windows error dialog when attempting to run the internal binary directly.
- **Audio Tool**: Switched from print statements to proper logging for cleaner output and better diagnostics.

## [4.3.0] - 2026-02-14

### New Features

- **AI Parameters**: Added a dedicated `[ai_params]` section in `config.ini` and Settings window to configure model-specific parameters (temperature, max_tokens, top_p) separately from application settings.
- **Context Handling**: Implemented "Origin System Prompt" persistence as new default setting, allowing follow-up chat messages to respect the specific persona of the initiating tool (e.g., "Transcribe", "Explain") instead of reverting to the generic chat prompt.
- **File Processor**: Automatically injects the filename into the prompt context during batch processing for better model awareness.

### Improvements

- **Prompt Editor**:
  - Changed "Reset to Defaults" to operate in-memory, requiring an explicit "Save All" to persist changes.
  - Added conditional visual states to pagination settings to clarify when they are disabled by grouping.
- **Configuration**: Switched `TextEditTool` to use live `PromptsConfig` references, ensuring settings changes are immediately reflected without restarts.

### Fixes

- **Gemini Provider**: Fixed configuration key format for thinking models (using snake_case and uppercase levels) and removed `topK` parameter from defaults.
- **Chat Window**: Resolved a UI freeze issue by moving model loading to a background thread.
- **Settings GUI**: Fix opening the Settings window directly to specific tabs caused thread-related 9 seconds of delay when opening popups and windows.

### Refactoring

- **Deployment**: Simplified workspace management by inlining logic into `main.py` and removing the legacy `workspace_manager.py` module.

## [4.2.0] - 2026-02-10

### New Features

- **LaTeX Rendering**: Implemented a lightweight, dependency-free LaTeX-to-Unicode renderer to display basic mathematical expressions directly in the chat window.

### Improvements

- **Prompts**: Refined system prompts for "OCR to Markdown" and "Transcribe Audio" tools to better handle visual ambiguities and enforce structure.
- **GUI**: Optimized chat window layout to improve vertical space utilization and resizing behavior.
- **Terminal**: Updated session details in the console to use "Origin" instead of "Endpoint" for consistency.

## [4.1.1] - 2026-02-10

### Improvements

- **Performance**: Implemented lazy loading for tabs in Settings and Prompt Editor windows, rendering content only upon selection to improve window opening speed.

## [4.1.0] - 2026-02-09

### New Features

- **Audio Attachments**: Added support for attaching and playing audio files (MP3, WAV, OGG) directly in the chat window.
- **Markdown Rendering**: Enhanced markdown parsing with support for italicized headers and improved table handling.

### Improvements

- **Workspace**: Improved robustness of frozen state detection to better handle Nuitka and standalone executable environments.

### Build & Deployment

- **Launchers**: Replaced C# launchers with Python-based cx_Freeze implementations to eliminate AV false positives and to simplify and centralize logic.

## [4.0.1] - 2026-02-08

### New Features/Changes

- **Terminal**: Added a new keyboard shortcut `[A]` to directly open the Audio Analyzer from the console main menu.
- **System Tray**: Direct file editing options ("Edit config.ini", "Edit prompts.json") in the tray menu are now conditionally visible only when the application is started with the `--show-console` flag.

### Improvements

- **GUI**: Fix scrolling of Settings and Prompt Editor windows in Tkinter fallback mode.
- **UI/UX**: Adjusted widget widths and layout in the Settings window for better visual consistency, specifically targeting host/port fields, provider selection, and model dropdowns.
- **Terminal**: Reorganized the main command box to prioritize the Audio Tool shortcut rather than Endpoint.

### Internal

- **Request Pipeline**: Simplified request origin tracking by consolidating multiple specific endpoint origins into a single `ENDPOINT` type.

## [4.0.0] - 2026-02-08

### New Features

#### Audio Tool
- **Audio Analyzer**: New tool for recording and analyzing audio from microphone or system loopback.
- **Unified Stream Architecture**: Robust audio handling for simultaneous recording and level monitoring.
- **Visualization**: Real-time audio level meter with gradient visualization and resizable UI.
- **Controls**: Custom input field, action indicator, and response mode toggle (Default, Result Panel, Chat Window).
- **Processing**: Support for large file recordings and automatic audio compression.
- **Tkinter Fallback**: Full support for standard Tkinter environments.

#### System Tray & Navigation
- Added direct access to **Direct Chat**, **Screen Snip**, and **Audio Analyzer** from the tray menu.
- Implemented custom tray menu with separators for better organization.
- Restricted file editing options to console mode.

#### Settings & Configuration
- **Auto-Save**: New `auto_save_session` setting to control when sessions are persisted ("on_followup", "always_window", "on_attachment").
- **Reset Defaults**: Added button to reset configuration to default values.
- **Logging**: Centralized logging configuration with Rich formatting support.

#### Prompts & Actions
- **New Actions**: Added "Extract Data", "Code Review", "Smart Cleanup", "OCR to Markdown", and more.
- **Groups**: Support for enabling/disabling action groups in popup menus.
- **Overhaul**: Comprehensive update to Screen Snip prompts for better results.

### Improvements

- **UI/UX**:
  - Updated blockquote and overlay colors for improved readability across themes.
  - Automatically collapse thinking blocks after streaming finishes.
  - Enhanced Prompt Editor layout and responsiveness.
  - Improved Toast Notification animation and timeout.
  - Button bar visibility improvements at small window sizes.
- **Performance**:
  - Optimized audio loopback buffer size for better responsiveness.
  - Capture screen snips from frozen background to remove capture delay.

### Fixes

- **Gemini Provider**:
  - Treated "thinking-only" responses as empty to trigger automatic retries.
  - Added detection for invalid API keys in error handling.
- **Session Management**:
  - Ensured assistant messages are persisted correctly during auto-save.
  - Fixed issue where attachments could be duplicated in API requests.
  - Prevented writing `None` values to configuration files.
- **General**:
  - Fixed import paths in prompt and settings windows.
  - Corrected ErrorPopup button styling.
  - Resolved custom input handling issues in Audio Tool.

### Refactoring

- **Architecture**:
  - Centralized multimodal message construction logic.
  - Organized GUI window modules into a dedicated package.
  - Moved attachment handling from session-level to message-level.
  - Removed legacy audio recording implementation.
- **Cleanup**:
  - Removed AVIF image format support to simplify dependencies.
  - Converted configuration flags to proper booleans.

### Build & Deployment

- **Nuitka Migration**: Replaced cx_Freeze with Nuitka for standalone executable generation.
- **C# Launchers**: Introduced lightweight C# launchers to replace Python/Nuitka wrappers, significantly reducing binary size.
- **CI/CD**: Updated GitHub Actions workflows for the new build process.
