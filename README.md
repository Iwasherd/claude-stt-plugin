# WhisperSTT - Claude Code Plugin

Speech-to-Text plugin for Claude Code using Whisper AI with GPU acceleration.

## Features

- **Global Hotkey** - `Ctrl+Shift+Space` to record from anywhere
- **Auto-type** - Transcribed text automatically typed into Claude Code
- **GPU Accelerated** - Uses NVIDIA GPU via Docker
- **Multi-language** - English, Russian, Ukrainian, Czech, Spanish, Polish
- **Auto-detect** - Automatically detects source language

## Installation

### Option 1: Claude Code Plugin (Recommended)

```bash
# Install the plugin
claude plugin add github:Iwasherd/claude-stt-plugin

# Run the installer
~/.claude/plugins/stt/install.sh
```

### Option 2: Manual Installation

```bash
# Clone the repo
git clone https://github.com/Iwasherd/claude-stt-plugin.git
cd claude-stt-plugin

# Run installer
chmod +x install.sh
./install.sh
```

## Requirements

- Ubuntu/Linux with X11
- Docker with NVIDIA GPU support
- Python 3.10+
- `stt-service:latest` Docker image (Whisper + M2M100)

## Usage

1. **Start the app:**
   ```bash
   ~/.local/share/whisper-stt/WhisperSTT
   ```
   Or find "Whisper STT" in your applications menu.

2. **Click "Start Container"** in the app (wait ~30-60s for model loading)

3. **Use the global hotkey:**
   - Press `Ctrl + Shift + Space` → starts recording
   - Speak your message
   - Press `Ctrl + Shift + Space` again → stops and transcribes
   - Text is automatically typed into the active window (Claude Code)

## Docker Image

The plugin requires the `stt-service:latest` Docker image with:
- Whisper ASR model
- M2M100 translation model
- CUDA support

Build from `docker/` directory if you have the base image:
```bash
cd docker
docker build -t stt-service:latest .
```

## File Structure

```
claude-stt-plugin/
├── .claude-plugin/
│   └── plugin.json      # Plugin manifest
├── skills/
│   └── transcribe/
│       └── SKILL.md     # /stt:transcribe command
├── app/
│   ├── stt_app.py       # Main GUI application
│   ├── icon.svg         # App icon
│   └── build.sh         # Build script
├── docker/
│   ├── Dockerfile       # Docker build file
│   └── server.py        # FastAPI STT server
├── install.sh           # Installation script
└── README.md
```

## Skill Commands

After installation, use in Claude Code:
- `/stt:transcribe` - Shows usage instructions

## License

MIT
