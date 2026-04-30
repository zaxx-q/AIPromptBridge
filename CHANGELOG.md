# Changelog

## [6.4.1] - 2026-04-30

### Improvements
- **Popup UI**: Simplified layout in popup menus by removing redundant "Preset:" and "Actions:" text labels from dropdown frames, giving the dropdowns more room to expand responsively.

### Fixes
- **Chat Window**: Fixed an issue where the "Copy Last" button wouldn't work immediately when reopening an existing session. The last response is now properly initialized from the session history payload on load.
- **Provider Reliability**: Enhanced empty response detection during API streaming to ignore incomplete responses that only contain "thinking" blocks without any actual text or tool outputs, ensuring these upstream API glitches trigger an automatic retry.

## [6.4.0] - 2026-04-30

### New Features

- **Preset Selector Mode**: Model dropdowns in the Chat Window and Audio Analyzer now support a "preset mode" that displays saved model presets instead of raw model lists. When enabled and presets are defined, selecting a preset automatically applies its full configuration (provider, model, temperature, thinking, etc.) to the session. A new toggle in General Settings (`Use model presets in dropdowns`) controls this behavior.
- **Popup Preset Override**: TextEdit and Snip Tool popups now include a model preset dropdown, allowing you to override the model configuration on a per-request basis without changing global settings. The selected preset is automatically carried over to any resulting chat sessions.
- **Copy Response Mode**: Added a "Copy" option to response mode toggles in TextEdit Tool popups. Selecting "Copy" sends the AI response directly to your clipboard with a toast notification, instead of replacing text or opening a chat window.
- **Preset Manager in Settings**: The Model Preset Manager is now accessible directly from the Settings window's Generation tab, in addition to the Prompt Editor. The manager has been enhanced with provider-specific field visibility, a model dropdown with live fetching, a summary panel showing overridden vs. default fields, a "Test" button for verifying presets, and a "Populate from Config" shortcut.

### Improvements

- **Prompt Editor Modularization**: The Prompt Editor has been restructured from a single large file into a dedicated package with separate modules for each tab, improving maintainability and code organization.
- **Settings Window Modularization**: The Settings Window has been similarly restructured into a modular package with dedicated files for each settings tab and shared widget utilities.
- **Settings Layout**: Adjusted the Settings window default size and reorganized the Theme tab to show the live preview first for immediate visual feedback. The Generation tab now includes a dedicated Model Presets section.
- **Icon Picker**: Simplified the icon input process in the Prompt Editor by replacing the emoji picker button with direct paste instructions and a placeholder.

### Fixes

- **LaTeX Currency Detection**: Fixed inline LaTeX parsing to correctly render single-digit math expressions like `$3$` or `$9$` that were previously being misidentified as currency values and skipped.
- **LaTeX Display Blocks**: Fixed an issue where display math blocks (`$$...$$`) wrapped in Markdown bold or italic markers (e.g., `**$$...$$**`) would render as raw `__LATEX_DISPLAY_N__` placeholders instead of being properly converted to Unicode.
- **Preset Manager Thread Safety**: Fixed potential crashes in the Preset Manager where accessing UI elements from background threads during model fetching could cause RuntimeErrors.

## [6.3.0] - 2026-04-06

### New Features

- **Chat Clipboard Paste**: You can now paste images and files directly into the chat input using `Ctrl+V`. Bitmap screenshots from the clipboard are attached as PNG, and files copied from Explorer (images, audio, PDFs) are attached automatically — no file picker needed.
- **Per-Session Model Selection**: The model dropdown in the chat window now sets a per-session override instead of changing the global model. A new "(Use Global: …)" sentinel entry lets you follow the global default, while selecting any other model pins that session to it. Branched sessions inherit the parent's model override.
- **Session Management in Chat**: Added rename (✏️) and delete (🗑️) buttons directly in the chat toolbar for quick session management without opening the Session Browser.
- **Custom Chat Backgrounds**: New settings to customize or disable the colored backgrounds for user and assistant messages in the chat window. Configure hex colors or turn off background tinting entirely via Settings or `config.ini`.

### Improvements

- **Session Browser Auto-Refresh**: Renaming or deleting a session from the chat window now automatically refreshes any open Session Browser windows.
- **Emoji Preloading**: Application-used emoji icons are now preloaded in a background thread on startup, minimizing the first-open delay when displaying popup windows and toolbars.
- **Config Change Notifications**: Replaced periodic polling with an event-driven publish/subscribe system for configuration changes. Chat windows now update their global model sentinel instantly when the model is changed in Settings.

### Fixes

- **Inline Image Context Menu**: Fixed an issue where right-clicking on inline images in the chat window would open both the image in default app and the general message context menu simultaneously.
- **Clipboard Attachment Saving**: Fixed a race condition where temporary files from clipboard pastes could be deleted before being copied to permanent session storage.

## [6.2.0] - 2026-03-30

### New Features

- **Answer Action**: Added a new "Answer" action to both the Text Edit Tool and Snip Tool. This action acts as an expert problem solver, analyzing selected text or captured screenshots containing questions, exercises, or problems (math, logic, programming, etc.) and providing step-by-step reasoning alongside a clear final answer.
- **Default Active Modifiers**: Modifiers can now be configured to activate automatically for specific tools. A new "Default for Tools" section in the Prompt Editor lets you choose which tools (TextEdit, SnipTool, AudioTool) should have each modifier pre-selected when their popup opens, eliminating the need to manually toggle frequently used modifiers every time.

### Improvements

- **Popup Tooltips**: Added descriptive tooltips to response mode toggle buttons (Default, Replace, Show, Copy, Type) across all popup windows, making it easier to understand what each mode does at a glance.

## [6.1.5] - 2026-03-30

### Improvements

- **Audio Export**: Reduced the default Opus (OGG) export bitrate from 64k to 32k, significantly decreasing file size while maintaining transparent speech quality thanks to Opus's superior compression efficiency.
- **TTS Output**: Voice name is now always included in saved TTS audio filenames for easier identification, instead of only appearing as a fallback when transcript text was unavailable.

### Fixes

- **TTS Generation**: Fixed an issue where generating audio directly from an existing AI Director transcript would incorrectly display a "No input text" error, requiring text in the input field even when a complete transcript was already present in the director panel.
- **TTS Endpoint**: Fixed the `tts_use_official_endpoint` setting being silently ignored, causing TTS requests to always route through the custom Gemini endpoint instead of the official Google endpoint when configured.
- **Settings**: Fixed an issue where testing API connectivity from the Settings window would fail with a "No API keys configured" error if the API Keys tab had not been opened yet during the current session.
- **Combobox**: Fixed an issue where manually typed text in dropdown comboboxes was discarded when clicking away without pressing Enter, requiring users to explicitly confirm their input.

## [6.1.4] - 2026-03-27

- **Updater**: Replaced standard system alert boxes with modernized, theme-aware dialogs indicating when updates are available or the app is already up to date. This dialog now includes a fully functional progress bar during download and extraction. Also fixed an issue where graphical update notifications triggered from the system tray would occasionally fail to display or cause thread-locking, and added a short delay to background checks to prevent startup freezing.
- **Update Cleanup**: Implemented automatic cleanup of `.old` file remnants on startup, safely removing files left behind by previous application updates and streamlining updater dialog background logic into a dedicated module.
- **Theme Consistency**: Applied the centralized custom color theming system to the `Update Available` and `Up To Date` notifications, creating a visually consistent appearance instead of relying on default styles.

## [6.1.0] - 2026-03-27

### New Features

- **Snip Tool**: Completely revamped text extraction actions. Introduced distinct `Quick Extract` (fast, unformatted text only) and `Exact Extract` (preserves spatial formatting but ignores typographical markdown syntax)
- **Config Tracking**: A new tracking mechanism explicitly monitors and preserves user-customized text strings/prompts during internal migrations. This ensures your customized `system_prompt`s or `task` definitions are fully insulated from internal app updates.
- **Modifiers Recovery**: Implemented deep merging for prompt modifiers ensuring built-in features (like the new `language` modifier) populate automatically even if you had customized your global settings previously.
- **Terminal UX**: Updated the terminal hotkey hint to more clearly reflect that `[H]` is used to list all active commands.

### Improvements

- **Updater**: Added a graphical message box when checking for updates manually via the system tray, providing clear visual feedback if you're already on the latest version.

### Fixes

- **Dialog Editor**: Fixed a bug where multi-line strings with explicit newline characters (e.g. `\n`) were dropping their escape formatting when viewed inside single-line entry widgets in the Prompt Editor, safely displaying them as literal backslash-n sequences.
- **Prompt Resurgence**: Fixed instances where default popup groups or modifiers that you previously deleted completely would stubbornly reappear after restarting the application.

## [6.0.0] - 2026-03-24

### New Features

- **Auto-Update System**: Introduced a seamless self-update mechanism with automatic background checks and safe startup recovery. Automatically checks GitHub for new versions on launch (configurable in Settings), allowing you to update directly from within the app or system tray.
- **Model Presets**: Added a new model presets system. You can now define custom AI configurations (e.g., choosing a specific provider, model, temperature, or enabling Gemini thinking mode) and assign them directly to individual tool actions (like Snip, Audio, or Text Edit tasks) in the Prompt Editor.
- **Preset Manager**: Added a new GUI dialog in the Prompt Editor to easily create, edit, duplicate, and delete model presets interactively.
- **Parallel Task Execution**: The Audio Tool, Snip Tool, and Text Edit Tool can now process multiple requests concurrently without resetting or interrupting each other's processing states.
- **Smart Digitize Format**: Added a new "Smart Digitize (to Markdown)" built-in robust prompt designed to intelligently extract and format textual content from mixed printed and handwritten documents.
- **Language Modifier**: Added a new global "Language" modifier that allows you to force AI outputs into a specific language (defaults to Indonesian).
- **TTS AI Director Constraints**: The AI Director now automatically receives the selected voice's gender information context, ensuring generated style prompts correctly match character genders for more natural and coherent speech synthesis.
- **Official Google Endpoint Fallback for TTS**: Added a setting to force Text-to-Speech interactions to route through the official Google Generative Language endpoint. This is useful if you are using a custom Google-compatible proxy for chat that doesn't support Gemini's TTS model.

### Improvements

- **Audio Export Centralization**: Standardized audio output formats (Opus, MP3, WAV, FLAC, AAC) across both the Text-to-Speech and Audio Analyzer tools. A single output configuration setting (`audio_output_format`) now governs saved formats across the application.
- **Audio Output**: The Audio Analyzer now uses ffmpeg (if available) to export highly optimized Opus or AAC files, and automatically embeds transcripts or OCR outputs as audio metadata properties.
- **Prompt Configuration Integrity**: Improved prompt configuration to utilize deep-merging. Changes to internal default prompts will now safely merge without overwriting your customizations. Additionally, built-in defaults that you explicitly delete will remain deleted and won't reappear upon restarting the app.
- **Markdown Rendering**: Improved line-wrapping and visualization for "Thinking" response blocks, giving them a distinct background color and separating line to differentiate the thought process from the final answer.
- **Inline Math Formulation**: Improved Markdown rendering by proactively processing inline LaTeX (`$...$`). This fixes an issue where math symbols wrapped in markdown formatting blocks (like bold or italics) could break formatting or be parsed incorrectly.
- **TTS UX**: Updated default configurations to rename `tts_output` directories simply to `audio_output` to reflect unified exports.

### Fixes

- **Memory Leaks**: Implemented eager destruction logic and explicit garbage collection for `tkinter` variables during background thread lifetimes in popup windows. This eliminates persistent `RuntimeError: main thread is not in main loop` crashes commonly encountered after repeated popup usage.
- **State Updates**: Resolved an off-by-one index error that caused thinking blocks in the chat window to improperly expand/collapse when external modules (like the Snip Tool) injected multi-stage payloads.

## [5.4.1] - 2026-02-28

### Fixes

- **File Processor**: Fixed an issue where multi-modal message extraction was producing empty request bodies for image inputs.
- **Batch API**: Corrected logic for generating Gemini Batch API requests from within the File Processor.
- **Batch TTS**: Fixed an API timeout behavior and guaranteed the TTS internal singleton initializes correctly when entering the terminal tool interface without a prior GUI instantiation.
- **Build Configurations**: Excluded `zlib1.dll` from packaged launcher exclusions.

## [5.4.0] - 2026-02-26

### New Features

- **Chat Interface**: Added right-click context menus and inline action buttons (edit, rerun, more) to individual messages. This allows for modifying sent messages, regenerating responses without creating new user prompts, copying text, deleting, or branching off into a completely new session from any point in the conversation history.
- **Session Browser**: Added a "Rename" button to the Session Browser, allowing custom titles to be set via a modal dialog.
- **Text Selection Strategies**: The Text Edit Tool now utilizes low-level Win32 `SendInput` and `WM_COPY` parallel algorithms simultaneously to capture highlighted text. This significantly increases compatibility across various Windows applications where standard clipboard polling or basic Ctrl+C injection fails.

### Improvements

- **Markdown Rendering**: Implemented hanging indents for markdown bulleted and numbered lists. Wrapped lines now correctly align with the text content rather than wrapping back under the list marker. Also ensured that markdown code blocks are properly padded with newlines so they don't break when immediately following other text.
- **UI & Themes**: Applied user and assistant background colors to the chat dialog instead of relying on transparent backgrounds. Improved text selection visibility by ensuring highlighted text always appears above these background colors.
- **Window Management**: Implemented dark DWM titlebar overrides and used a withdraw-and-deiconify loading pattern for all modal windows to eliminate the bright white titlebar flash that occurs before custom scaling is applied.
- **Emoji Rendering**: Improved the internal emoji loading pipeline. Built-in Unicode emojis rendered on standard standard Windows GDI menus now use an alpha compositing strategy against native gray/dark-mode theme hues instead of creating white-box transparency artifacts.

### Fixes

- **File Processor**: Fixed an issue where the directory structure was not preserved during recursive repository formatting or parsing scans.
- **Audio Splitting**: Improved FFmpeg chunk duration estimation to account for target compression bitrates and added an optimization to pass-through the audio stream directly without transcoding when formats match, decreasing chunking times.
- **Internal Configurations**: Centralized and fixed `_IS_COMPILED` application state detection checks.

## [5.3.2] - 2026-02-23

### Fixes

- **File Processor**: Fixed an issue where temporary file names were injected into the AI context instead of the original user-facing filenames when processing certain media modes. Also improved context injection for chunked audio (e.g., appended `Part 1/3`).

## [5.3.1] - 2026-02-22

### Fixes

- **Launch on Startup**: Fixed an issue where the standard Tkinter UI fallback setting was ignored when the app was launched automatically on Windows startup.
- **Sounds**: Fixed an issue where notification sounds would not play when using the standalone executable package.

## [5.3.0] - 2026-02-21

### New Features

- **Snip Tool**: Added a new "Type" response mode that types the AI's response directly into the active text field.

### Improvements

- **Settings UX**: Clarified the `auto_save_session` setting logic in the UI and documentation to explicitly state that sessions are always saved upon receiving an AI response or sending a reply, regardless of the selected trigger mode.

### Fixes

- **Providers**: Prevented automatic API key rotation when receiving empty responses from Gemini and OpenAI compatible endpoints. Empty responses are now handled via a standard delay-and-retry mechanism.
- **Prompt Editor**: Fixed an initialization issue where updating the live preview could cause attribute errors if the playground tab had not yet been loaded.

## [5.2.0] - 2026-02-20

### New Features

- **Text Comparison**: Introduced "Compare mode" for the Text Edit Tool. Now it's possible to select and capture a second piece of text to perform direct comparisons.
  - Added default comparative actions: "Compare Texts", "Find Differences", "Which is Better", and "Before/After".
  - Added a dedicated Compare button (🔀) directly within the popup's "Ask" input field.
- **Batch TTS Processor**: Added a new terminal tool for batch text-to-speech generation.
  - Supports automatic style generation via AI Director (single aggregated style or unique per-segment styles).
  - Robust progress tracking with checkpoints and the ability to resume or retry failed segments.
  - Includes an option to merge all generated segment WAV files into a single unified output.
- **TTS Playground**: Added a dedicated "TTS" mode to the Prompt Editor's playground area, enabling real-time testing of models, voices, and AI Director style generation without leaving the editor.
- **Prompt Loading from File**: The CLI File Processor now supports loading custom prompts directly from text files (`[F] Load prompt from file`).

### Improvements

- **Audio Exporting**: Optimized FFmpeg conversion logic to use format-specific encoders (`libmp3lame`, `libvorbis`, `flac`, `aac`) for significantly better compression and quality when exporting in TTS window.
- **File Processor**: Added an option to inject the filename directly into the AI context for non-text file types (images, audio, documents), improving the model's awareness of the processed file. This preference is now saved and restored within checkpoints.
- **Prompt Editor UX**:
  - Relocated the "Save Action" button outside of the scrollable area, ensuring it is always visible regardless of the list length.
  - Added the "Compare mode" checkbox for both Text Edit Tool and Snip Tool configurations.
- **Settings & Notifications**:
  - Made the server settings safety unlock transient, preventing the unlocked state from persisting into `config.ini` across app restarts.
  - Improved toast notification handling with programmatic dismissal for faster workflows.
- **Context Handling**: Re-engineered chat requests to properly format multimodal messages, ensuring compare mode and follow-up prompts display flawlessly in the chat window.

## [5.1.1] - 2026-02-18

### Improvements

- **Thinking Mode**: Standardized "Thinking" behavior across all tools (Audio, Snip, TextEdit) to respect the global `thinking_enabled` setting instead of using hardcoded defaults.

### Fixes

- **Launch on startup**: Reimplemented launcher detection with a more robust multi-path search strategy to fix the "Launch on startup" feature in compiled builds.
- **Chat Persistence**: Implemented immediate session saving after user messages and modifications, ensuring chat history is preserved and retry/regeneration is possible even if an API error occurs.
- **Regenerate Button**: Fixed assistant message handling in the chat window to correctly support response regeneration and session state persistence.

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
