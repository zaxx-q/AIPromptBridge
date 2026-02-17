# ShareX Integration Guide

This guide explains how to set up ShareX to work with AIPromptBridge for image processing tasks like OCR, translation, and description.

> **Note**: AIPromptBridge now includes a built-in Screen Snipping feature (**Ctrl+Alt+X**) which provides similar functionality without requiring external tools. This ShareX integration is intended for advanced users who need ShareX's specific workflow capabilities or custom endpoints.

## Demo

https://github.com/user-attachments/assets/f9fcbea2-e403-4ea5-86d5-50edb79454f6

## Prerequisites

- Latest version of [ShareX](https://getsharex.com/) installed
- AIPromptBridge running with Flask endpoints enabled:
  1. Open `config.ini` (Right-click tray icon -> Edit config.ini)
  2. Set `flask_endpoints_enabled = true` under `[config]` (it is disabled by default)
  3. Restart AIPromptBridge

## Step 1: Create Custom Uploader

1. Open ShareX
2. Go to **Custom uploader settings**
3. Click **New** to create a new uploader

## Step 2: Configure the Uploader

Fill in the following settings:

| Setting | Value |
|---------|-------|
| **Name** | `AIPromptBridge - OCR` (or any name) |
| **Destination type** | `Image uploader` |
| **Method** | `POST` |
| **Request URL** | `http://127.0.0.1:5000/ocr` |
| **Body** | `Form data (multipart/form-data)` |
| **File form name** | `image` |
| **URL** | `{response}` |

![Custom uploader settings](images/sharex-new-uploader.jpg)

## Available Endpoints

AIPromptBridge comes with these default endpoints (configurable in `prompts.json`):

| Endpoint | Purpose |
|----------|---------|
| `/ocr` | Extract text from image |
| `/ocr_translate` | Extract and translate text (use `?lang=` parameter) |
| `/translate` | Translate image text to English |
| `/describe` | Describe image content |
| `/summarize` | Summarize image content |
| `/code` | Extract and format code from image |
| `/explain` | Analyze and explain image content |
| `/latex` | Convert equations to LaTeX |
| `/markdown` | Convert content to Markdown |
| `/proofread` | Extract and proofread text |

### Custom Endpoints

You can add your own endpoints by editing `prompts.json` (Right-click tray -> Settings -> Endpoints Tab). The endpoints are defined in the `endpoints` section of the JSON configuration.

## Query Parameters

Add these to the URL for additional behavior:

| Parameter | Example | Effect |
|-----------|---------|--------|
| `?show=yes` | `/ocr?show=yes` | Open result in chat window for follow-up |
| `?show=no` | `/ocr?show=no` | Return text only (default) |
| `?lang=XX` | `/ocr_translate?lang=Japanese` | Target language for translation |
| `?prompt=...` | `/ocr?prompt=Extract+only+numbers` | Override the endpoint prompt |
| `?model=...` | `/ocr?model=gemini-2.5-pro` | Override the model |
| `?provider=...` | `/ocr?provider=openrouter` | Override the provider |

**Examples:**
- `http://127.0.0.1:5000/ocr?show=yes` - OCR with chat follow-up
- `http://127.0.0.1:5000/ocr_translate?lang=English` - Translate to English
- `http://127.0.0.1:5000/ocr_translate?lang=Indonesian` - Translate to Indonesian
- `http://127.0.0.1:5000/describe?show=yes&model=gemini-2.5-pro` - Describe with specific model

## Step 3: Create Hotkey Workflow

1. Go to **Hotkey settings** (or right-click tray → Hotkey settings)
2. Click **Add...** to create a new hotkey
3. Set:
   - **Task**: `Capture region` (or `Capture active window`, etc.)
   - **Hotkey**: Your preferred key combination

![Hotkey setup](images/sharex-hotkey.jpg)

## Step 4: Configure Task Settings

1. Click the **Gear icon** ⚙️ next to your new hotkey
2. Configure **Override after capture tasks**:
   - Check **Upload image to host**
5. Configure **Override after upload tasks**:
   - Check **Copy URL to clipboard**
2. Configure **Override destinations**:
   - Check **Image uploader**
   - Select **Custom image uploader**
3. Configure **Override default custom uploader**:
   - Check and select your `AIPromptBridge - OCR` uploader

![Task settings](images/sharex-task-settings.jpg)

## Usage

1. Press your configured hotkey
2. Select a region on screen (or capture window/fullscreen)
3. Wait for AIPromptBridge to process the image
4. The extracted text is now in your clipboard - paste anywhere!

### Quick Access via Tray

You can also access workflows by:
1. Right-click ShareX tray icon
2. Go to **Workflows**
3. Select your workflow

## Troubleshooting

### "Connection refused" Error

- Make sure AIPromptBridge is running (check system tray for the icon)
- **Check if Flask endpoints are enabled**: Ensure `flask_endpoints_enabled = true` in `config.ini`
- Check the port matches your config (default: 5000)
- Try opening `http://127.0.0.1:5000/` in your browser

### Empty Response

- Check AIPromptBridge console for errors (right-click tray → Show Console)
- Verify your API keys are configured in `config.ini`
- Make sure to use models that supports vision

### Slow Processing

- Use a faster model (e.g., `gemini-2.5-flash` instead of `gemini-2.5-pro`)
- Disable thinking mode: Set `thinking_enabled = false` in config.ini
- Use non-reasoning models for simple tasks

## Example Workflows

Create multiple custom uploaders for different tasks:

| Workflow | URL | Use Case |
|----------|-----|----------|
| Quick OCR | `/ocr` | Fast text extraction |
| OCR + Chat | `/ocr?show=yes` | Text with follow-up questions |
| Translate to English | `/ocr_translate?lang=English` | Any language → English |
| Translate to Japanese | `/ocr_translate?lang=Japanese` | Any language → Japanese |
| Describe Image | `/describe?show=yes` | Image description with chat |
| Extract Code | `/code` | Screenshot to code |
| Explain Code | `/explain_code?show=yes` | Code explanation |

## Tips

- Use `?show=yes` when you want to ask follow-up questions about the image
- Create separate hotkeys for different workflows (e.g., `Ctrl+1` for OCR, `Ctrl+2` for translate)
- The response is plain text - it works with any application that accepts paste
- Add your own custom endpoints in `prompts.json` for specialized prompts
- Use the `{lang}` placeholder in custom endpoints for dynamic language selection
