# Architecture

This document describes the technical architecture of AIPromptBridge.

## Overview

AIPromptBridge is a Windows application consisting of:

1. **Flask Web Server** - REST API endpoints for image/text processing
2. **System Tray Application** - Background process management with `infi.systray`
3. **CustomTkinter GUI** - Modern chat windows, session browser, and popups with multi-theme support
4. **Rich Console Interface** - Modernized terminal UI with structured logging and panels
5. **TextEditTool** - Global hotkey assistance with two-tier "Edit" and "General" prompt architecture
6. **AI Provider System** - Unified abstraction for multiple AI backends
7. **Theme System** - Multi-theme support with dark/light modes and system detection
8. **Settings Infrastructure** - GUI editors for config.ini and prompt options with hot-reload
9. **Tools Subsystem** - Batch file processing framework with checkpoints and audio optimization
10. **TTS (Text-to-Speech)** - Gemini-powered speech synthesis with AI Director for expressive style control

## Component Diagram

```mermaid
flowchart TB
    subgraph Main["main.py"]
        Tray["System Tray<br/>(tray.py)"]
        Console["Console UI<br/>(terminal.py)"]
        Tools["Tools<br/>(tools/file_processor.py)"]
        Flask["Flask Server<br/>(web_server.py)"]
        TET["TextEditTool<br/>(text_edit_tool.py)"]
        Snip["SnipTool<br/>(snip_tool.py)"]
        Audio["AudioTool<br/>(audio_tool.py)"]
        TTS["TTSTool<br/>(tts_tool.py)"]
        TTSUI["TTSWindow<br/>(windows/tts_window.py)"]
        Popups["Popups<br/>(popups.py)"]
        Modifiers["Scrollable ModifierBar<br/>(popups.py)"]
        TypingInd["TypingIndicator<br/>(popups.py)"]
    end
    
    subgraph Pipeline["Request Pipeline"]
        RP["request_pipeline.py<br/>• Logging<br/>• Token tracking<br/>• Origin tracking"]
    end
    
    subgraph APIClient["API Client"]
        AC["api_client.py<br/>get_provider_for_type()"]
    end
    
    subgraph Providers["Providers"]
        OAI["OpenAI-compatible<br/>Provider"]
        Gemini["Gemini Native<br/>Provider<br/>+ TTS"]
        Custom["Custom<br/>Endpoint"]
    end
    
    subgraph KeyMgr["Key Manager"]
        KM["key_manager.py<br/>• Multiple keys per provider<br/>• Auto-rotation on error<br/>• Exhaustion detection<br/>• Retry with backoff"]
    end
    
    Tray --> Pipeline
    Flask --> Pipeline
    Console --> Tools
    Tools --> Pipeline
    TET --> Popups
    Snip --> Popups
    Audio --> Popups
    TTS --> TTSUI
    Popups --> Modifiers
    TET --> TypingInd
    Popups --> Pipeline
    Pipeline --> APIClient
    APIClient --> OAI
    APIClient --> Gemini
    APIClient --> Custom
    OAI --> KM
    Gemini --> KM
    Custom --> KM
```

## Provider System

All AI API calls flow through the unified provider system in `src/providers/`.

### Provider Interface

```python
class BaseProvider:
    def call_api(messages, config, ai_params, key_manager) -> ProviderResult
    def call_api_streaming(messages, config, ai_params, key_manager, callback) -> ProviderResult
    def get_model_list(config, key_manager) -> List[str]
    def upload_file(path) -> (file_obj, error)  # Optional
    def create_batch(messages, model, params) -> (batch_obj, error)  # Optional
```

### Available Providers

| Provider | Class | Use Case |
| ---------- | ------- | ---------- |
| `google` | `GeminiNativeProvider` | Native Gemini API (Thinking, Batch, Files) |
| `openrouter` | `OpenAICompatibleProvider` | OpenRouter.ai models |
| `custom` | `OpenAICompatibleProvider` | Any OpenAI-compatible endpoint |

### Retry Logic

The provider system includes automatic retry with key rotation:

| Error | Action | Delay |
| ------- | -------- | ------- |
| 429 Rate Limit | Rotate to next key | None |
| 401/402/403 Auth | Rotate to next key | None |
| 5xx Server Error | Retry same key | 2 seconds |
| Empty Response | Rotate to next key | 2 seconds |
| Network Error | Rotate to next key | 1 second |

## GUI Threading Model

```mermaid
flowchart LR
    subgraph MainThread["Main Thread"]
        GC["GUICoordinator<br/>(singleton)"]
        Root["ctk.CTk()<br/>(single root)"]
    end
    
    subgraph Windows["Windows (CTkToplevel)"]
        Chat["ChatWindow (windows/chat_window.py)"]
        Browser["SessionBrowser (windows/session_browser.py)"]
        Popup["PopupWindow (popups.py)"]
        SnipUI["SnipPopup (snip_popup.py)"]
        AudioUI["AudioAnalyzerWindow (windows/audio_analyzer.py)"]
        TTSUI["TTSWindow (windows/tts_window.py)"]
    end
    
    subgraph OtherThreads["Other Threads"]
        Flask["Flask Thread"]
        Hotkey["Hotkey Thread"]
    end
    
    OtherThreads -->|"request_window()"| GC
    GC -->|"queue-based creation"| Root
    Root --> Chat
    Root --> Browser
    Root --> Popup
    Root --> SnipUI
    Root --> AudioUI
    Root --> TTSUI
```

### Rules

1. **Single ctk.CTk() root** - Managed by `GUICoordinator` on a dedicated GUI thread.
2. **Thread-Safe Requests** - Windows are created via a thread-safe queue.
3. **CTkToplevel for Windows** - All application windows are children of the single root.
4. **Update Loop** - Standalone windows use an update-based loop to coexist with other threads.

## GUI Framework Fallback

To ensure robustness across different environments, AIPromptBridge includes a centralized UI toolkit authority in `src/gui/platform.py`:

1.  **Toolkit Authority**: `HAVE_CTK`, `ctk`, and `CTkImage` are imported from `platform.py` by all GUI modules.
2.  **Fallback Mechanism**: If `customtkinter` is missing or the `ui_force_standard_tk` setting is enabled, the system automatically falls back to standard `tkinter` with optimized layouts and widgets.
3.  **User Configuration**: Users can toggle `ui_force_standard_tk` in the **Theme** tab of the **Settings** window to resolve performance or compatibility issues.

### Window Types

| Window | Purpose |
| -------- | --------- |
| `ChatWindow` | Interactive AI chat with streaming |
| `SessionBrowserWindow` | Browse and restore saved sessions |
| `PopupWindow` | TextEditTool selection/input dialogs with dual input (Edit/Ask), Compare mode, and scrollable ModifierBar |
| `SnipPopup` | Result dialog for screen snipping with image preview and action carousel |
| `AudioAnalyzerWindow` | Audio recording, playback, and analysis interface |
| `TTSWindow` | Text-to-Speech generation with voice selection, AI Director, and audio playback |
| `ErrorPopup` | Dialog for displaying API failures to user |
| `TypingIndicator` | Tooltip showing typing status and abort hotkey |
| `SettingsWindow` | GUI editor for config.ini with tabbed interface |
| `PromptEditorWindow` | GUI editor for prompts.json with Playground testing |

## Request Pipeline

All AI requests flow through `RequestPipeline` for consistent observability, utilizing `src/console.py` for rich output:

```python
pipeline = RequestPipeline(
    origin=RequestOrigin.CHAT_WINDOW,  # or POPUP_INPUT, ENDPOINT_OCR, etc.
    session_id=session.id
)
result = pipeline.execute(provider, messages, config, ai_params, key_manager)
```

### Features

- **Structured Logging**: Uses Rich panels to display request details (model, provider, status)
- **Token Tracking**: Input/Output/Total usage visualized in tables
- **Origin Context**: Clear indication of where the request originated
- **Timing**: Execution time tracking within the results panel
- **Error Handling**: Distinct red panels for failure states

## Session Management

Sessions are stored in `chat_sessions.json` with sequential IDs.

### Session Structure

```json
{
  "1": {
    "id": 1,
    "origin": "textedit:Explain",
    "title": "First message preview...",
    "messages": [
      {"role": "user", "content": "..."},
      {"role": "assistant", "content": "..."}
    ],
    "thinking_content": "...",
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:01:00"
  }
}
```

### Context Injection

When a session is initiated from the TextEditTool (e.g., asking a question about selected text), the first message includes a context marker to ensure the AI has follow-up context:
`[Task: Explain this text]`

### Prompt Architecture

Prompts are managed centrally via `PromptsConfig` (loading `prompts.json` or defaults).

#### Unified Configuration
- `text_edit_tool`: Configuration for text selection actions (Ctrl+Space)
- `snip_tool`: Configuration for screen snipping actions (Ctrl+Alt+X)
- `audio_tool`: Configuration for audio analysis actions (Ctrl+Alt+A)
- `tts_tool`: Configuration for TTS voice list, director prompts, and defaults
- `endpoints`: Flask API endpoint prompts
- `_global_settings`: Shared modifiers and system instructions

#### Modes
- **Edit Mode** (`"edit"`): Strict text replacement (e.g., Proofread). Uses `base_output_rules_edit`.
- **General Mode** (`"general"`): Conversational responses (e.g., Explain). Uses `base_output_rules_general`.

#### Context Injection
- `chat_system_instruction`: Used for initial direct chats via the popup.
- `chat_window_system_instruction`: Default global instruction for follow-up conversations in chat windows.
- **Origin-Awareness**: If `chat_use_origin_system_prompt` is enabled, sessions initiated from specific tool actions (e.g., `textedit:Explain`, `snip:Extract Text`) persist that action's system prompt for the entire conversation, preserving the specific persona/rules defined for that action.

### Design Decision

Sessions do NOT store provider/model. This allows:

- Hot-switching providers mid-conversation
- No migration needed when changing default provider
- Current config is always used at request time

## System Tray (Windows)

The tray application (`src/tray.py`) manages:

- Console show/hide handles both standard console and **Windows Terminal** (console X button is disabled in tray mode)
- Application restart (spawns new process, exits current) via launcher where possible
- Quick access to session browser
- Config file editing

### Console Window Behavior

| Action | Result |
| -------- | -------- |
| Click X on console | Button disabled (grayed out) |
| Tray → Hide Console | Hides console window |
| Tray → Show Console | Shows and focuses console |
| Tray → Quit | Clean shutdown |

## Console Interface (Rich)

The terminal interface (`src/terminal.py` and `src/console.py`) uses the `rich` library for modern console UI:

- **Centralized Configuration**: `src/console.py` defines the global `Console` instance and custom theme.
- **Panels & Tables**: Menus, session lists, and status screens use styled tables tailored for readability.
- **Color-Coded Logs**: Success, error, warning, and info messages have distinct styles.
- **Robust Fallback**: Automatically degrades gracefully if `rich` is missing (though it is a hard dependency).

## Thinking/Reasoning Configuration

Different providers have different thinking mechanisms:

| Provider | Config Key | Values |
| ---------- | ----------- | -------- |
| OpenAI-compatible | `reasoning_effort` | `low`, `medium`, `high` |
| Gemini 2.5 | `thinking_budget` | Integer (tokens, -1 = auto) |
| Gemini 3.x | `thinking_level` | `low`, `high` |

## Configuration System

The config parser (`src/config.py`) is a custom INI parser, NOT Python's `configparser`.

### Special Features

- Multiline values with `\` continuation
- Type coercion (bool, int, float, string)
- API keys are one per line in their section
- Comments with `#` or `;`
- `{lang}` placeholder support for dynamic language in prompts

### Example

```ini
[settings]
streaming_enabled = true
thinking_enabled = false
default_provider = google
google_model = gemini-2.5-flash

[google]
# API keys, one per line
AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
AIzaSyYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY

[endpoints]
# Use {lang} placeholder for dynamic language
ocr_translate = Extract and translate to {lang}. Return only translated text.
```

## Theme System

The theme system (`src/gui/themes.py`) provides centralized color management with multiple presets.

### Available Themes

| Theme | Description | Variants |
| ------- | ------------- | ---------- |
| `catppuccin` | Warm pastel colors | Mocha (dark), Latte (light) |
| `dracula` | Dark purple-based | Classic (dark), Pro (light) |
| `nord` | Arctic blue palette | Polar Night (dark), Snow Storm (light) |
| `gruvbox` | Retro earthy colors | Dark, Light |
| `onedark` | Atom editor theme | Dark, Light |
| `minimal` | Clean, minimal design | Dark, Light |
| `highcontrast` | Maximum readability | Dark, Light |

### Configuration

```ini
[config]
ui_theme = catppuccin
ui_theme_mode = auto  # auto, dark, light
```

### Usage

```python
from src.gui.themes import get_colors, ThemeRegistry

# Get current theme colors
colors = get_colors()
print(colors.bg, colors.fg, colors.accent)

# Get specific theme
dark_nord = ThemeRegistry.get_theme("nord", "dark")

# Check system dark mode
is_dark = ThemeRegistry.is_dark_mode()
```

### ThemeColors Dataclass

The `ThemeColors` dataclass provides standardized color names with legacy property aliases:

| Standard | Legacy Alias | Purpose |
| ---------- | -------------- | --------- |
| `bg` | `base` | Primary background |
| `fg` | `text` | Primary text |
| `accent` | `blue` | Primary accent color |
| `accent_green` | `green` | Success/positive |
| `accent_red` | `red` | Error/danger |
| `code_bg` | `mantle` | Code block background |
| `blockquote` | `subtext0` | Muted text |

## Emoji Support (Twemoji)

AIPromptBridge implements color emoji support for Windows using the Twemoji asset set. This is necessary because Windows Tkinter typically only renders monochrome outlines for emojis in Text widgets.

### EmojiRenderer (`src/gui/emoji_renderer.py`)

The `EmojiRenderer` class manages the loading, caching, and rendering of emoji images:

- **Asset Loading**: PNG images are loaded from `assets/emojis.zip` (Twemoji 72x72 set).
- **Caching**: Images are cached in memory as both `ImageTk.PhotoImage` (for tk.Text) and `CTkImage` (for CTk widgets).
- **Detection**: Uses the `emoji` library (if available) with a robust regex fallback to find emojis in text.
- **Normalization**: Handles Variation Selector 16 (FE0F), flag sequences (regional indicators), and ZWJ (Zero Width Joiner) sequences.

### Rendering Modes

1.  **Markdown Rendering (`src/gui/utils.py`)**:
    *   During markdown parsing, text segments are processed by `insert_with_emojis(text_widget, text, tags)`.
    *   It uses `text_widget.image_create()` to embed the PNG images directly into the flow of the rich text.

2.  **Widget Content (`src/gui/custom_widgets.py`)**:
    *   `prepare_emoji_content(text, size)` extracts leading emojis from button or label text.
    *   It returns the text (without emoji) and a `CTkImage` to be used with the `compound="left"` property.
    *   This is used by `create_emoji_button`, `create_section_header`, and `upgrade_tabview_with_icons`.

## Settings Infrastructure

### SettingsWindow

GUI editor for `config.ini` (`src/gui/settings_window.py`):

- **Tabbed Interface**: General, Provider, Streaming, TextEditTool, API Keys, Endpoints, Theme
- **API Key Naming**: Supports associative names for API keys via inline comments
- **Model Dropdowns**: Interactive dropdowns for model selection with background refreshing
- **Live Preview**: Theme tab shows real-time preview of color changes
- **Validation**: Port numbers, hotkey formats
- **Backup**: Creates `.bak` file before saving
- **Hot-Reload**: API keys and endpoints reload without restart

### PromptEditorWindow

GUI editor for `prompts.json` (`src/gui/prompt_editor.py`):

- **Actions Tab**: Edit actions for both TextEditTool and SnipTool
- **Settings Tab**: Edit text output rules and system instructions
- **Modifiers Tab**: Manage global modifier buttons
- **Groups Tab**: Organize actions into popup groups for both tools
- **Playground Tab**: Test actions and endpoints with live preview
- **Hot-Reload**: Triggers `reload_options()` on save for immediate effect

### Access Methods

```python
# From any thread
from src.gui.settings_window import show_settings_window
from src.gui.prompt_editor import show_prompt_editor

show_settings_window()  # Opens Settings window
show_prompt_editor()    # Opens Prompt Editor
```

Both windows are accessible from the system tray menu.

## Workspace Management (Deployment)

To support clean deployment with Nuitka, the application uses a split structure:

- **Root**: Contains lightweight launchers (`AIPromptBridge.exe`, `AIPromptBridge-NoConsole.exe`) and user config files.
- **Bin**: Contains the heavy standalone application (`bin/AIPromptBridge_Internal.exe`) and dependencies.

Workspace logic is handled inline in `main.py` via `setup_workspace()`:
- **From source**: No CWD change needed; runs in the project directory as-is.
- **Compiled + launcher** (`--launched-mode`): CWD is set to the launcher's directory (parent of `bin/`).
- **Compiled + no launcher**: Refuses to start — the internal binary must be launched via a launcher.
- **Stale file migration**: A non-blocking background thread moves any leftover config/data files from `bin/` to root on startup.

For more details on the build process and launcher architecture, see [BUILD_PROCESS.md](BUILD_PROCESS.md).

## TTS Processor (Batch TTS)

The `TTSProcessor` (`src/tools/tts_processor.py`) provides batch text-to-speech generation capabilities through an interactive terminal wizard.

### Features

- **Text Splitting**: Four modes for segmenting input text
  - Lines: One segment per non-empty line
  - Paragraphs: One segment per blank-line-separated block
  - Sentences: One segment per sentence (simple regex-based splitting)
  - Whole file: Single segment containing entire file

- **Voice & Model Configuration**:
  - Single speaker mode with 30 prebuilt Gemini voices
  - Multi-speaker mode (up to 2 speakers) with individual voice assignment
  - Model selection: `gemini-2.5-flash-preview-tts` (fast) or `gemini-2.5-pro-preview-tts` (quality)

- **Style Instructions**:
  - Manual: Enter custom style instructions
  - Default: Use "Read aloud naturally" as default style
  - No style: Send text directly to TTS without any style prefix
  - AI Director (Single): Analyze sample segments to generate one unified style
  - AI Director (Per-Segment): Generate unique style for each segment

- **Output Modes**:
  - Individual WAV: One `.wav` file per segment
  - Merged WAV: All segments concatenated into single file

### Architecture

```mermaid
flowchart TB
    subgraph Wizard["Interactive Wizard"]
        S1["Step 1: Input & Text Splitting"]
        S2["Step 2: Voice & Model"]
        S3["Step 3: Style Instructions"]
        S4["Step 4: Output Configuration"]
        S5["Step 5: Execution Settings"]
    end
    
    subgraph Checkpoint["Checkpoint System"]
        CM["TTSCheckpointManager"]
        CP["TTSCheckpoint"]
        FC["Failed Checkpoint"]
    end
    
    subgraph TTS["TTS Generation"]
        TD["TTSToolApp"]
        DIR["AI Director"]
        API["GeminiNativeProvider"]
    end
    
    S1 --> S2 --> S3 --> S4 --> S5
    S5 --> CM
    CM --> CP
    CP --> TD
    TD --> DIR
    TD --> API
    CP --> FC
```

### Checkpoint System

The `TTSCheckpointManager` extends the base checkpoint system with TTS-specific functionality:

| Method | Purpose |
|--------|---------|
| `create()` | Create new checkpoint with all TTS parameters |
| `save()` | Save checkpoint to `tts_checkpoint.json` |
| `load()` | Load existing checkpoint |
| `load_failed()` | Load failed-segments checkpoint |
| `create_failed_checkpoint()` | Save failed segments for retry |

### Keyboard Controls

During processing, the following keyboard controls are available:

| Key | Action |
|-----|--------|
| `P` | Pause processing |
| `S` | Stop and save progress |
| `Enter` | Resume from pause |
| `q` | Quit during pause |

### Integration

The TTS Processor integrates with existing TTS infrastructure:

- **Voice Constants**: Uses `TTS_VOICES` from `src/audio/tts_constants.py`
- **TTSToolApp**: Delegates audio generation to existing `TTSToolApp` instance
- **AI Director**: Uses the same director logic as the GUI TTS window
- **WAV Utilities**: Uses `src/audio/wav_utils.py` for audio handling
