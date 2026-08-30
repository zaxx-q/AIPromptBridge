# Changelog

## [8.2.0] - 2026-08-30

### New Features

- **"Digest" Content Action & Preset**: Added a new built-in action to the TextEditTool ("Digest") and the batch File Processor ("Digest Content") to turn messy, dense, or poorly structured material into a clean reference. Rather than compressing content like a traditional summary, it retains useful context, details, examples, decisions, code, and relationships while removing noise and clutter. It adaptively structures the output based on the content's inferred purpose (study material, meeting transcripts, technical logs, web articles, or notes/archives).

### Fixes

- **Console Keyboard Interception in Interactive Prompts**: Suspended the background console keyboard listener (`p` pause / `s` stop) during interactive prompts in the batch File Processor and TTS Processor (such as large file mode selection and per-file instruction inputs). This ensures listener threads release raw terminal console mode before blocking on user input, preventing user-typed characters from being intercepted or falsely triggering stop/pause events.

## [8.1.0] - 2026-08-03

### New Features

- **"Humanize" Text Edit Action**: Added a new built-in prompt to the TextEditTool to transform AI-generated writing into natural, human-sounding text. Based on [Wikipedia's "Signs of AI writing"](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing) guide, maintained by WikiProject AI Cleanup. This comprehensive guide comes from observations of thousands of instances of AI-generated text.

### Improvements

- **Linux Eliminated GUI Cold-Start Delay**: GUI initialization and font loading now warm up in the background during application startup, removing the cold-start delay when opening the first popup or window.
- **Linux Idle CPU Consumption**: Replaced polling-based GUI loops with native event-driven event handling, eliminating idle CPU consumption. Reduced system theme and background IPC polling frequency on Linux.

### Fixes

- **Linux Dropdown & Menu Behavior**: Fixed mousewheel scrolling in dropdown combo boxes and ensured popup menus (such as split button menus and message context menus) dismiss properly when clicking outside of them on Linux.
- **Linux Terminal Output on Restart**: Fixed restarting the compiled Linux application from the system tray to ensure console output remains attached to the terminal emulator instead of detaching into a new background session.
- **Cross-Platform Paths**: Fixed an issue where chat attachments (such as images and audio clips) could fail to open, play back, or load when sharing or transferring sessions between Windows and Linux due to platform path differences.

## [8.0.0] - Linux Wayland Support

### Added

- **Linux Wayland support** — full platform layer for wlroots compositors (niri, Sway, Hyprland)
- **IPC trigger system** — fast `--trigger` client for compositor keybindings (~40ms latency)
- **Wayland clipboard** — `wl-clipboard` integration with primary selection, hybrid Ctrl+C capture, and rich HTML copy
- **Virtual keyboard** — `wlrctl` text typing, paste, and key chord injection
- **Screen capture** — `grim` + `slurp` region snipping for SnipTool
- **System audio recording** — PipeWire/Pulse monitor sources via `pactl` + `ffmpeg`
- **StatusNotifier tray** — D-Bus `org.kde.StatusNotifierItem` (jeepney) with pystray fallback
- **XDG autostart** — `.desktop` entry for Launch at Login on Linux
- **Sound feedback** — `paplay` / `pw-play` / `ffplay` for notification sounds
- **Cross-platform console input** — `termios` cbreak single-key polling (replaces Windows `msvcrt`)
- **CustomTkinter bootstrap** — automatic `circle_shapes` fallback + font installation for no-xft Tk
- **Linux self-update** — in-place `bin/` swap + `os.execv` relaunch for compiled installs
- **Nuitka Linux packaging** — GitHub Actions workflow for x86_64 tarball releases

### Changed

- Platform-abstracted all OS I/O into `src/platform/` (clipboard, input, screenshot, IPC, console)
- Audio backend dispatch: PyAudioWPatch on Windows, stock PyAudio on Linux
- Tray: `infi.systray` on Windows, StatusNotifier/pystray on Linux
- Font resolution: `get_tk_font()` / `get_ctk_font()` with per-platform family detection

Other desktop environments (GNOME, KDE, XFCE, Cinnamon, MATE, LXQt) are yet to be tested and likely won't work. If you encounter any issues, please open an issue.

## [7.2.0] - 2026-06-23

### New Features

- **Split Copy Buttons**: Replaced the standard chat copy buttons with dropdown split buttons, allowing users to copy all conversation history or the last response as Markdown, stripped plaintext, or rich-text HTML.
- **Markdown Table Clipboard Support**: Added support for converting Markdown tables to HTML format when copying messages as rich text, allowing them to render with correct borders and structure when pasted into external applications like Microsoft Word.

### Improvements

- **Unified Split Button Design**: Enhanced the CustomTkinter split buttons to render as single rounded capsules, drawing the separator and dropdown arrow directly on the button's canvas.
- **Standard Tkinter DPI Scaling**: Implemented a system to scale standard Tkinter font sizes, row heights, and layout margins on high-DPI displays, resolving misalignment, text overlap, and cropping issues across fallback widgets.

### Fixes

- **Visual Chat Indentation**: Fixed copied text retaining visual layout padding by stripping styling leading spaces from manually copied sections.

## [7.1.1] - 2026-06-16

### Improvements

- **Non-Streaming Abort Support**: Added support for the escape hotkey and typing indicator to cancel non-streaming replace/typing operations in both the Text Edit Tool and Screen Snipping Tool (Type mode).
- **Typing Delay Defaults**: Default streaming typing delay is now set to 0ms (no limit) for maximum speed, and the separate "uncapped" speed toggle has been deprecated. The settings spinbox range is simplified to [0, 100] ms.
- **Update Dialog**: Replaced the static, truncated 5-line changelog in the Update Available dialog with a themed, scrollable text box showing the full release notes. Also updated the layout and added Github button.

### Fixes

- **Profile Override Streaming**: Fixed an issue where streaming settings of a selected connection profile override were not being respected during the API request.

## [7.1.0] - 2026-06-15

### New Features

- **API Key Export & Import**: Export plaintext JSON backups and import/merge API keys directly from the API Keys settings tab, with automatic duplicate key detection when importing.
- **Portable Key Storage Mode**: Added a "Disable API key obfuscation" toggle in General settings, allowing plaintext key storage in `keys.json` for easy portability across machines. Keys are automatically re-encoded when toggling the mode.
- **Action & Modifier Visibility**: Individual actions and modifiers can now be hidden from tool popups without deleting them. Toggle visibility directly in the Prompt Editor using the visibility button, with a "Show Hidden" switch to reveal dimmed disabled items in the action list.
- **Expanded Onboarding Wizard**: The first-time setup wizard now includes 6 steps with new pages for toggling individual tools on/off and selecting which default actions and modifiers to enable, including a "Minimal" quick-preset for a clean starting point.
- **Slow App Text Capture**: Added an optional retry strategy for capturing selected text in slow applications like Obsidian, XMind, and Anki. Enable via Settings > Tools > "Slow app text capture retry".
- **Draggable Popups**: Borderless popup windows (input popup, prompt popup, snip popup, typing indicator, error popup) can now be repositioned by clicking and dragging any non-interactive area.
- **Dynamic Tray Menu**: The system tray menu now automatically updates when tools are enabled or disabled, hiding entries for inactive tools without requiring a restart.
- **TTS AI Director Connection Profile**: The TTS AI Director now uses a connection profile dropdown instead of a manual model text field, allowing full provider/model/key configuration for style generation requests.
- **Active Profile Tooltips**: Hovering over default/sentinel values (like "(Default)" or "(Use Active)") in connection profile dropdowns now displays the currently active profile's details including provider, model, and endpoint.

### Improvements

- **Tool Visibility in Menus & Popups**: Disabled tools are automatically hidden from the system tray menu, and the TTS button is removed from Text Edit popups when TTS is disabled in configuration.
- **Onboarding Performance**: Improved tab switching speed in the onboarding wizard's action/modifier selection step by caching tab frames instead of rebuilding them on each switch.
- **Default Popup Group Order**: The "Text Edit" action category is now displayed first in the default popup group list for quicker access to common actions.

### Fixes

- **Text Pasting on Non-English Keyboards**: Fixed text paste operations failing when Caps Lock is active or a non-English keyboard layout is in use, by replacing character-based key presses with Win32 virtual key code injection.
- **Text Capture in Slow Applications**: Fixed the Text Edit Tool failing to capture selected text in Electron-based apps (Obsidian), JavaFX apps (XMind), and similar programs that process copy commands asynchronously.

## [7.0.0] - 2026-05-21

### New Features

- **Connection Profiles**: Introduced a dedicated Connection Profile system (`profiles.json`) replacing the previous model presets. Each profile is a complete, self-contained set of AI connection settings; provider, model, streaming, thinking, temperature, max tokens, timeout, base URL, and API key overrides; with no sparse fallbacks. Profiles can be assigned globally or per-action, and switched at runtime from the terminal, tray menu, or a new Connection Profile Manager window.
- **Connection Profile Manager**: A new GUI window for creating, editing, duplicating, testing, and deleting connection profiles. Features include a live summary panel, unsaved-change indicators, field validation, contextual help tooltips, and in-editor model fetching with fallback lists. Accessible from the system tray ("Profiles"), Settings window, Prompt Editor, and terminal (`P` key).
- **Anthropic Claude Support**: Added a native Anthropic Claude Messages API provider with SSE streaming, adaptive thinking configuration, and full integration into the provider registry.
- **Multi-Provider Architecture**: Expanded provider support from 3 to 8 built-in providers; Google Gemini, Anthropic Claude, OpenAI, OpenRouter, xAI (Grok), Mistral, Cohere, and Custom OpenAI-compatible endpoints; all managed through a centralized provider registry with per-provider metadata, default base URLs, and key pool mappings.
- **Pool-Based API Key Management**: API keys are now stored in `keys.json` (XOR-obfuscated) organized into named pools, managed by a new `KeyStore` singleton. Keys are automatically migrated from `config.ini` and environment variables on first launch. The Keys tab in Settings provides full pool CRUD (create, rename, delete) and per-key management (add, remove, reorder). Provider-to-pool assignments are configured in the Connection tab.
- **Onboarding Wizard**: A new first-time setup wizard guides users through API key entry, provider/model selection, and a feature tour with hotkey reference cards. The wizard can be re-launched anytime from Settings ("Run Welcome Guide").
- **PDF Processing**: Added PDF document support for OpenAI-compatible and OpenRouter providers. The File Processor tool now offers optional page-by-page splitting for PDF files using `pypdf`, with support for page range selection (e.g., "1-5", "3,5,8", "all").
- **Inline Thinking Extraction**: Models served via OpenRouter or custom endpoints that emit reasoning text in XML-style tags (e.g., `<think>`, `<thinking>`) are now automatically parsed, separating thinking content from the final response for collapsible display.
- **Fallback Model Lists**: All model dropdowns (Chat Window, Audio Analyzer, Connection Manager, Onboarding) now display curated fallback model lists when live API fetching fails or is unavailable.
- **Gemma 4 System Instructions**: Gemma 4+ models now use native `systemInstruction` support instead of prepending system prompts to user messages (legacy Gemma 1–3 behavior is preserved).
- **Per-Session Manual Override**: Added manual mode support to the chat window, allowing users to toggle between profile selection and manual provider/model selection directly from the toolbar, with overrides persisted independently per-session.
- **Connection Profiles in Playground**: Integrated connection profile support into the Prompt Editor's playground tab, enabling testing prompts with saved profiles or manual settings, with auto-updated tooltips.
- **Gemini 3.1 TTS Support**: Added support for the `gemini-3.1-flash-tts-preview` model and set it as the default choice for the Text-to-Speech tool.
- **ScrollableComboBox Tooltips**: Dropdown list items in the custom `ScrollableComboBox` now display detailed contextual tooltips on hover (such as showing provider, model, and base URL for connection profiles).
- **Unsaved Changes Tracking**: Implemented robust dirty-state tracking with title-bar indicators and save prompts when attempting to close the Settings window or Prompt Editor with unsaved changes.
- **Active Environment Keys**: Updated `KeyStore` to unconditionally scan for API keys in environment variables on every startup, automatically importing and persisting newly discovered keys to local storage key pools.
- **Enable/Disable Connection Profiles**: Added support for enabling or disabling individual connection profiles, allowing users to temporarily hide profiles from dropdown selectors without deleting them.
- **Standardized Test Suite**: Consolidated the testing workflow into a unified `run_tests.py` script that automates Ruff linting/fixes, formatting checks, and Pytest unit tests in a single command.
- **New UI Themes**: Introduced three new color themes ("Rose", "Coffee", and "Violet") in both light and dark variants across all application interfaces.
- **Gemini Response Parts**: Added support for capturing and propagating raw Gemini response parts (like deep reasoning thought signatures) through the API pipeline and persisting them in chat session histories.

### Improvements

- **Unified Provider Architecture**: Redesigned the provider subsystem to eliminate code duplication. A centralized `BaseProvider` now owns retry loops, key rotation, timing, abort signal propagation, and HTTP error handling. Subclasses only implement request compilation and response parsing.
- **Streaming Idle Timeout**: Added content-idle timeout detection for streaming responses, catching hangs masked by SSE heartbeats or empty keep-alive signals that standard socket timeouts miss.
- **Better API Error Messages**: Streaming and non-streaming API errors now show the actual error message from the provider (e.g., rate limit details, safety blocks) instead of generic "Empty response" messages.
- **Settings Reorganization**: The Generation tab has been merged into the Tools tab (typing settings) and Provider tab (renamed to "Connection"), simplifying the settings interface. The Connection tab now features the active profile selector and key pool assignments.
- **Theme Refinements**: Removed the OneDark theme and optimized accent contrast across all remaining themes. Button text colors now use a dedicated `accent_fg` field for consistent readability against colored backgrounds.
- **Terminal Dashboard**: The `I` (Info) command now displays comprehensive profile metadata including description, API key pool/name, thinking parameters, temperature, max tokens, timeout, and total key counts across all pools.
- **Session-Scoped Toggles**: Thinking and streaming toggles in the terminal (`K` and `R` keys) now apply only to the current session and are not persisted to `config.ini`, preventing accidental permanent changes.
- **Configuration Simplification**: Connection settings (provider, model, streaming, thinking, AI parameters) have been removed from `config.ini` and are now exclusively managed through Connection Profiles. The `load_config()` function returns only the config dict; endpoints are loaded from `prompts.json`.
- **File Processor Profiles**: The batch File Processor now uses connection profiles instead of raw provider/model selection. Execution settings offer profile switching or manual override, and checkpoints store the profile name for consistent resume behavior.
- **Relocated Dialogs**: `ThemedInputDialog` and `ask_themed_string` moved from the Prompt Editor package to `custom_widgets.py` for broader reuse across Settings and other windows.
- **ScrollableComboBox**: Fixed focus-out race conditions that could overwrite explicit dropdown selections, and improved filtering logic to correctly reflect entry text when the dropdown is opened or values are refreshed.
- **Tooltip Readability**: Increased font size in the Tooltip component for improved readability across all UI elements.
- **API Key Logging**: Named API keys are now shown by name in request logs instead of generic index numbers. Key rotation is automatically disabled when a specific named key is selected via a profile override.
- **Terminal Profile Table**: Enhanced the connection profile switching command in the terminal dashboard (`P` key) to show a beautiful, detailed table of profile configurations including API key pool/name, streaming/thinking toggles, temperature, max tokens, and custom endpoints.
- **Connection Profile Manager Performance**: Optimized summary updates in the Connection Profile Manager by caching widget rows, replacing heavy dynamic rebuilding with static update-only panels.
- **Earlier Tray Initialization**: Re-architected application startup to initialize the system tray earlier, preventing thread blockages during heavy module load times and ensuring proper OS dark mode synchronization.
- **Earlier Port Conflict Resolution**: Moved local server port detection and conflict resolution to the very beginning of the startup sequence, preventing race conditions with tray launch and false port warnings.
- **Thinking Configuration**: Added a `medium` option to thinking level configuration inputs for Gemini 3.x models in the Connection Profiles UI.
- **Unsafe Code Refactoring**: Performed a major Ruff-driven cleanup of codebase quality, resolving unsafe try-except blocks, import conventions, static typings, and Windows subprocess window flags.
- **Default Theme Change**: Updated the default application theme from "Dracula" to "Minimal" and refined its dark mode palette for better styling.
- **Startup Descriptions**: Refined CLI help menus and descriptions to use modern desktop terminology instead of terminal-focused legacy descriptions.

### Removed

- **Flask API Endpoints**: Removed the entire Flask API endpoint feature (HTTP POST routes like `/ocr`, `/ocr_translate`). The built-in Snip Tool and direct tool integrations fully replace this functionality.
- **`--no-tray` Option**: Removed the `--no-tray` command-line argument. The application now always runs in tray mode on Windows.
- **OneDark Theme**: Removed the OneDark theme (both dark and light variants) from the theme registry.
- **`thinking_output` Setting**: Removed the `thinking_output` config option (`filter`/`raw`/`reasoning_content`). Thinking content is now always displayed as collapsible `reasoning_content`.
- **Terminal Info**: Removed the internal server URL from the terminal Info command output.

### Fixes

- **Profile Resolution Leakage**: Fixed active profile settings (base_url, temperature, max_tokens, etc.) leaking into override profiles. When an action selects a different connection profile, only that profile's values are used; empty fields now properly clear inherited parameters instead of falling through to the active profile.
- **TTS Base URL**: Fixed TTS audio generation ignoring the resolved connection profile's `base_url` when `tts_use_official_endpoint` is disabled.
- **Audio Analyzer Stability**: Fixed potential `TclError` crashes during Audio Analyzer window destruction by immediately nullifying level meter widgets before cleanup, preventing queued thread-safe callbacks from touching destroyed widgets.
- **Snip Tool Overrides**: Fixed action configuration not being passed through to API calls in the Snip Tool, ensuring per-action settings (like connection profiles) are correctly applied.
- **Audio Tool Presets**: Fixed preset/profile overrides not being carried through the Audio Tool's background processing pipeline.
- **Chat Window Profiles**: Fixed chat window not applying connection profile overrides for configuration, AI parameters, and key managers during streaming and non-streaming requests.
- **Preset Manager**: Fixed model fetching not reflecting custom Gemini endpoints, and added proper API key pool/name override support for preset testing.
- **Settings Save**: Fixed an error when saving settings if the Keys tab had never been loaded during the current session.
- **Profile Method Indentation**: Fixed `_get_profile_names` being incorrectly nested inside another method's return statement in both Audio Analyzer and Chat Base classes.
- **ScrollableComboBox Robustness**: Added defensive checks and error-handling blocks to the custom `ScrollableComboBox` to prevent asynchronous UI crashes or post-destruction lifecycle errors.
- **Test Connection Pipeline**: Restructured the test connection logic in the Connection Profile Manager and the Playground to route through `RequestPipeline` instead of deprecated API methods, and updated the test result window to report token usage statistics.

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
