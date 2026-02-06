# AIPromptBridge

<p align="center">
  <strong>• AI Desktop Tools & Integration Bridge •</strong>
</p>

**AIPromptBridge** is a Windows desktop application that brings AI assistance to your fingertips. Use global hotkeys to edit text using AI, capture and analyze audio or screen content, and chat with models—all from a lightweight system tray app.

## 📽️ Demo

https://github.com/user-attachments/assets/a104765a-eb48-4bf7-bbe4-2f9a53d97aa5

## ✨ Features

### 🎯 TextEditTool
Press **Ctrl+Space** anywhere to invoke AI on selected text:
- **Understand** - **Explain**, **Generate Summaries**, or **Keypoints**
- **Edit** - **Proofread** (✏️), **Rewrite** (📝), or make it **Casual** (😎)
- **Q&A** - Use the second input box in the popup to ask any question about the text
- **Custom prompts** - Define and group your own actions in the Prompt Editor

Works in any application: browsers, IDEs, Notepad, Word, everywhere.

### 📸 Screen Snip (SnipTool)
Press **Ctrl+Shift+X** to capture a region of your screen and analyze it with AI:
- **OCR** - **Extract Text** or **OCR to Markdown** for clean formatting
- **Analysis** - **Describe**, **Summarize**, or **Explain Code**
- **Data** - **Extract Data** to tables, **Transcribe** handwriting, or **Smart Cleanup** notes
- **Compare** - **Compare Images** to analyze differences between two screenshots
- **Response Modes** - Choose to show result in Chat Window, Result Panel, or Copy to Clipboard

### 🎤 Audio Analyzer
Press **Ctrl+Shift+A** to record and analyze audio:
- **Record** - Capture microphone input or system audio (loopback)
- **Transcribe** - High-fidelity transcription with timestamps and speaker identification
- **Analyze** - Summarize meetings, extract key points, or analyze tone
- **Controls** - Visual level meter, compression settings (Opus/MP3), and preview
- **Integration** - Send audio directly to chat context for follow-up questions

### 💬 Chat Interface
Lightweight chat windows with:
- Streaming responses (real-time typing)
- Markdown rendering
- Session history (browse and restore)
- Multi-theme UI with 7 color schemes

### 🎨 Theme System
Customizable appearance with:
- **7 themes**: Catppuccin, Dracula, Nord, Gruvbox, OneDark, Minimal, High Contrast
- **Dark/Light modes**: Each theme has both variants
- **System detection**: Auto-switches based on Windows theme
- **Live preview**: See theme changes instantly in Settings

### 🔄 Robust Backend
- **Multi-provider support** - Google Gemini, OpenRouter, custom endpoints
- **Automatic key rotation** - Switch API keys on rate limits (429, 401, 403)
- **Smart retry logic** - Handles errors gracefully with configurable delays
- **Empty response detection** - Automatically retries with next key
- **Streaming support** - Real-time responses
- **Batch Processing** - Async processing for large workloads (Gemini Batch API)
- **Attachment Manager** - Efficient external storage for session images, audio, and files

### 🧰 Tools System
The **File Processor** tool enables bulk operations:
- **Batch Processing**: Process folders of Images, Audio, Code, Text, or PDFs
- **Audio Optimization**: Reduce file size (mono, sample rate) for efficient AI processing
- **Configurable**: On-demand `tools_config.json` creation
- **Smart Handling**:
  - **Large Files**: Auto-switches to Gemini Files API or Chunking logic
  - **Checkpoints**: Resume interrupted jobs or retry failures
  - **Interactive Mode**: Pause (`P`), Stop (`S`), or Abort (`Esc`) during processing

## 🚀 Quick Start

### Download (Recommended)

1. Download `AIPromptBridge.exe` from [GitHub Releases](https://github.com/zaxx-q/AIPromptBridge/releases)
2. Run it - on first launch, it creates `config.ini` and automatically opens the Settings window
3. Enter your API keys in the **API Keys** tab and click **Save**
4. The app starts minimized to system tray

### From Source (Alternative)

```bash
git clone https://github.com/zaxx-q/AIPromptBridge.git
cd AIPromptBridge
pip install -r requirements.txt
python main.py
```

### Configuration

You can configure API keys via the **Settings** window (right-click tray icon -> Settings) or by editing `config.ini`.

```ini
[google]
AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX  # My Primary Key

[openrouter]
sk-or-v1-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX # Project Backup
```

> 💡 **Tip**: Add multiple keys (one per line) for automatic rotation when rate limits are hit. You can name your keys using inline comments (`#`).

## 📋 Usage

### System Tray

Right-click the tray icon for:
- **Show/Hide Console** - Toggle console visibility
- **Session Browser** - View chat history
- **Direct Chat** - Open text input popup (Ctrl+Space)
- **Screen Snip** - Trigger screen capture (Ctrl+Shift+X)
- **Audio Analyzer** - Open audio tool (Ctrl+Shift+A)
- **Settings** - Open GUI settings editor
- **Prompt Editor** - Edit TextEditTool prompts
- **Edit config.ini** - Open configuration file
- **Restart** - Restart the application
- **Quit** - Exit completely

### TextEditTool

1. Select text in any application
2. Press **Ctrl+Space**
3. Choose an action (Proofread, Rewrite, etc.)
4. Text is replaced or opened in chat

**Without selection**: Opens a quick input bar for direct questions.

### SnipTool (Screen Snipping)

1. Press **Ctrl+Shift+X**
2. Click and drag to select a screen region
3. Choose an action (Describe, Extract Text, etc.) or ask a question
4. Results open in a chat window with the image attached, can also directly copied to clipboard.

### Audio Tool

1. Press **Ctrl+Shift+A** to open the Audio Analyzer
2. Select input device (Microphone or System Audio)
3. Click **Record** to capture audio
4. Choose an action (Transcribe, Analyze, etc.)
5. Results are streamed to a chat window or displayed in the result panel

### API Endpoints

Access AI via HTTP POST (Advanced). Endpoints are disabled by default (`flask_endpoints_enabled = false`) but can be enabled in `config.ini` for integrations like ShareX.

```bash
# Basic OCR
curl -X POST -F "image=@screenshot.png" http://127.0.0.1:5000/ocr

# With chat window
curl -X POST -F "image=@screenshot.png" "http://127.0.0.1:5000/describe?show=yes"
```

See [ShareX Setup Guide](docs/SHAREX_SETUP.md) for full endpoint documentation.

### Console Commands

When console is visible, press these keys:

Key | Action |
|-----|--------|
`S` | Show system status |
`O` | Open session browser |
`M` | List available models (Use `?N` for details, e.g., `?1`) |
| `P` | Switch AI provider |
| `T` | Toggle thinking mode |
| `R` | Toggle streaming mode |
| `H` | Show help |

## ⚙️ Configuration

### Providers

Set your preferred provider in `config.ini`:

```ini
[config]
default_provider = google
google_model = gemini-2.5-flash
```

Available providers:
- `google` - Native Gemini API (recommended)
- `openrouter` - OpenRouter.ai models
- `custom` - Any OpenAI-compatible endpoint

### Custom Endpoints

Add your own endpoints in `config.ini`:

```ini
[endpoints]
# Simple custom endpoint
my_analyzer = Analyze this image and list all objects found.

# Dynamic language endpoint using {lang} placeholder
my_translator = Translate to {lang}. Keep formatting.
```

Access via `http://127.0.0.1:5000/my_analyzer` or `http://127.0.0.1:5000/my_translator?lang=French`

### Unified Prompts

Customize all prompts (TextEditTool, SnipTool, and Endpoints) in `prompts.json`. This file is automatically created from defaults if missing.

#### Structure
- `text_edit_tool`: Text manipulation prompts (Ctrl+Space)
- `snip_tool`: Image analysis prompts (Ctrl+Shift+X)
- `endpoints`: Flask API endpoint prompts
- `_global_settings`: Shared settings and modifiers

```json
{
  "text_edit_tool": {
    "Proofread": {
      "icon": "✏",
      "prompt_type": "edit",
      "system_prompt": "You are a meticulous proofreader...",
      "task": "Proofread the following text...",
      "show_chat_window_instead_of_replace": false
    }
  },
  "snip_tool": {
    "Describe": {
      "icon": "🖼️",
      "system_prompt": "You are an image analysis expert...",
      "task": "Describe this image in detail...",
      "show_chat_window": true
    }
  }
}
```
    "icon": "💡",
    "prompt_type": "general",
    "system_prompt": "You are a knowledgeable teacher...",
    "task": "Explain the following text...",
    "show_chat_window_instead_of_replace": true
  },
  "Rewrite": {
    "icon": "📝",
    "prompt_type": "edit",
    "system_prompt": "You are an expert editor...",
    "task": "Rewrite this text to improve clarity...",
    "show_chat_window_instead_of_replace": false
  },
}
```

### Text Modifiers

The TextEditTool popup includes a **Modifier Bar** that lets you fine-tune the output. Toggle these modifiers to inject specific instructions into the prompt:

- **Variations** (🔢): Generate 3 alternative versions.
- **Direct** (🎯): Make output direct and concise, no fluff.
- **Explain** (📝): Add an explanation of changes.
- **Creative** (🎨): Take more liberties with phrasing.
- **Literal** (📏): Stay close to the original.
- **Shorter** (✂️): Make the result more concise.
- **Longer** (📖): Expand with more detail.
- **Formal** (💼): Professional/business tone.
- **Informal** (💬): Casual/personal tone.
- **Global** (🌐): Avoid idioms for international audience.

*Note: Some modifiers (like Variations and Explain) force the output to open in a chat window.*

### Theming

Configure the UI theme in Settings or `config.ini`:

```ini
[config]
ui_theme = catppuccin
ui_theme_mode = auto  # auto, dark, light
auto_save_session = on_followup # on_followup, always_window, on_attachment
```

Available themes: `catppuccin`, `dracula`, `nord`, `gruvbox`, `onedark`, `minimal`, `highcontrast`

> 💡 **Performance Tip**: If you experience lag or UI issues with the modern interface, you can disable it by enabling **"Force Standard Tkinter"** in the **Theme** tab of Settings. This switches the app to a high-performance fallback mode using standard Windows widgets.

## 💡 Tips

### For Faster Responses
- Use non-reasoning models (e.g., `gemini-2.0-flash` instead of `gemini-2.5-pro`)
- Disable thinking mode: Press `T` in console or set `thinking_enabled = false`
- Keep streaming enabled for perceived faster responses

### For Better Results
- Enable thinking mode for complex tasks
- Use specific prompts in TextEditTool
- Add context when asking questions

### API Key Management
- Add multiple API keys (one per line) for automatic rotation
- If one key hits rate limits, the next one is used automatically
- The system tracks exhausted keys and skips them
- Keys rotate on: 429 (rate limit), 401/402/403 (auth errors), empty responses

## 🔧 Command Line Options

```bash
AIPromptBridge.exe                    # Normal start (tray mode, console hidden)
AIPromptBridge.exe --no-tray          # No tray icon, console stays visible
AIPromptBridge.exe --show-console     # Tray mode but keep console visible
AIPromptBridge.exe --no-wt            # Skip Windows Terminal detection
```

> 💡 **Console View**: For the best console experience (including full color emoji support), it is highly recommended to use [Windows Terminal](https://apps.microsoft.com/store/detail/windows-terminal/9N0DX20HK701). AIPromptBridge will attempt to automatically relaunch in Windows Terminal if detected.

## 📖 Documentation

- [Project Structure](docs/PROJECT_STRUCTURE.md) - File organization
- [Architecture](docs/ARCHITECTURE.md) - Technical details
- [ShareX Setup](docs/SHAREX_SETUP.md) - Screenshot integration

## 🗺️ Roadmap

- [x] **Prompt Editor** - GUI for editing text_edit_tool_options.json (includes Playground)
- [x] **Settings Window** - GUI for editing config.ini
- [x] **Theme System** - Multiple color schemes with dark/light modes
- [x] **Colored Emoji** - Twemoji-based color emoji rendering in chat and UI widgets
- [x] **Modern UI** - Migrated to CustomTkinter for modern UI, rounded corners, and other GUI improvements
- [x] **Audio Tool** - Recording and analysis of system/mic audio

## 📝 Requirements

- **Windows 10/11** (uses Windows-specific APIs for tray and console)
- **Windows Terminal** (Highly recommended for better console view and colors)
- **Python 3.14+** (if running from source)
- API keys for at least one provider (Google Gemini recommended)

## 📄 License

[MIT License](LICENSE)

### Attribution & Third-Party Licenses

This project uses [Twemoji](https://github.com/jdecked/twemoji) graphics, licensed under [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/).