# Changelog

## [4.1.0] - 2026-02-09

### New Features

- **Audio Attachments**: Added support for attaching and playing audio files (MP3, WAV, OGG) directly in the chat window.
- **Markdown Rendering**: Enhanced markdown parsing with support for italicized headers and improved table handling.

### Improvements

- **Workspace**: Improved robustness of frozen state detection to better handle Nuitka and standalone executable environments.

### Build & Deployment

- **Launchers**: Replaced C# launchers with Python-based cx_Freeze implementations to eliminate AV false positives and to simplify and centralize logi.

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
