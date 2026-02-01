#!/bin/bash
# Install STT Hotkey Daemon

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="/home/washerd/projects/stt-for-develop/venv"

echo "=== Installing STT Hotkey Daemon ==="

# Install Python dependencies
echo "Installing dependencies..."
~/.local/bin/uv pip install --python "$VENV_DIR/bin/python" pynput sounddevice pyperclip requests numpy

# Install systemd service
echo "Installing systemd service..."
mkdir -p ~/.config/systemd/user
cp "$SCRIPT_DIR/stt-hotkey.service" ~/.config/systemd/user/

# Update service paths
sed -i "s|/home/washerd/projects/stt-for-develop/venv|$VENV_DIR|g" ~/.config/systemd/user/stt-hotkey.service
sed -i "s|/home/washerd/projects/stt-for-develop/claude-stt-plugin|$SCRIPT_DIR|g" ~/.config/systemd/user/stt-hotkey.service

# Reload and enable service
systemctl --user daemon-reload
systemctl --user enable stt-hotkey.service
systemctl --user start stt-hotkey.service

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Hotkey: Alt + F9"
echo "  - Hold to record"
echo "  - Release to transcribe"
echo "  - Result copied to clipboard"
echo ""
echo "Commands:"
echo "  systemctl --user status stt-hotkey    # Check status"
echo "  systemctl --user restart stt-hotkey   # Restart"
echo "  systemctl --user stop stt-hotkey      # Stop"
echo "  journalctl --user -u stt-hotkey -f    # View logs"
echo ""
