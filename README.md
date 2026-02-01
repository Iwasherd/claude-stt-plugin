# Claude Code STT Plugin

Speech-to-Text plugin for Claude Code using Whisper.

## Features

- Record voice from microphone
- Transcribe using Whisper (GPU accelerated)
- Translate to multiple languages (en, ru, uk, cs, es, pl)
- Auto-detect source language

## Requirements

- Docker with NVIDIA GPU support
- `stt-service:latest` Docker image
- ffmpeg (for audio recording)
- Python 3.10+

## Installation

### Option 1: Local Installation

```bash
# Clone or copy the plugin
cd ~/projects/stt-for-develop/claude-stt-plugin

# Install dependencies
pip install -r requirements.txt

# Add MCP server to Claude Code
claude mcp add stt python3 /full/path/to/claude-stt-plugin/stt_mcp_server.py
```

### Option 2: Use Plugin Directory

```bash
# Run Claude Code with the plugin
claude --plugin-dir ~/projects/stt-for-develop/claude-stt-plugin
```

### Option 3: Install from GitHub

```bash
# Add plugin from GitHub (after pushing to repo)
claude plugin add github:washerd/claude-stt-plugin
```

## Usage

### Via Skill Command

```
/stt:transcribe
/stt:transcribe 10        # Record for 10 seconds
/stt:transcribe 5 ru      # Record 5s, translate to Russian
```

### Via MCP Tools

The plugin exposes these tools:

- `record_and_transcribe` - Record and transcribe audio
- `start_stt_container` - Start the Whisper Docker container
- `stop_stt_container` - Stop the container

### Via Hotkey

Add to `~/.claude/keybindings.json`:

```json
{
  "bindings": [
    {
      "key": "alt+v",
      "command": "skill",
      "args": { "name": "stt:transcribe" }
    }
  ]
}
```

## Configuration

Environment variables:

- `STT_HOST_PORT` - Host port for STT service (default: 8001)
- `STT_IMAGE` - Docker image to use (default: stt-service:latest)

## License

MIT
