---
name: transcribe
description: Information about using the STT (Speech-to-Text) plugin
user_invocable: true
---

# WhisperSTT - Speech to Text Plugin

This plugin provides speech-to-text functionality using Whisper AI.

## Usage

### Global Hotkey (Recommended)

When the WhisperSTT app is running:

1. Press `Ctrl + Shift + Space` to **start recording**
2. Speak your message
3. Press `Ctrl + Shift + Space` again to **stop and transcribe**
4. Text is automatically typed into the active window

### Installation

If not installed yet, run:
```bash
~/.claude/plugins/stt/install.sh
```

### Starting the App

```bash
~/.local/share/whisper-stt/WhisperSTT
```

Or find "Whisper STT" in your applications menu.

### Requirements

- Docker with NVIDIA GPU support
- The STT container must be running (click "Start Container" in the app)

## Supported Languages

- English, Russian, Ukrainian, Czech, Spanish, Polish
- Auto-detects source language
