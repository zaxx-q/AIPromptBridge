# Changelog

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
