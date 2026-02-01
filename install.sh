#!/bin/bash
# WhisperSTT Plugin Installation Script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/whisper-stt"
VENV_DIR="$INSTALL_DIR/venv"

echo "╔══════════════════════════════════════════════════════╗"
echo "║       WhisperSTT Plugin Installation                 ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please install Docker first."
    exit 1
fi

# Check NVIDIA Docker
if ! docker info 2>/dev/null | grep -q "Runtimes.*nvidia"; then
    echo "⚠️  NVIDIA Docker runtime not detected. GPU support may not work."
fi

# Create directories
echo "📁 Creating directories..."
mkdir -p "$INSTALL_DIR"

# Create virtual environment
echo "🐍 Setting up Python environment..."
python3 -m venv "$VENV_DIR" 2>/dev/null || {
    echo "Installing python3-venv..."
    sudo apt-get update && sudo apt-get install -y python3-venv python3-dev
    python3 -m venv "$VENV_DIR"
}

# Install dependencies
echo "📦 Installing Python packages..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -q \
    customtkinter \
    sounddevice \
    numpy \
    scipy \
    docker \
    requests \
    pyperclip \
    Pillow \
    pynput \
    pyinstaller

# Build the application
echo "🔨 Building WhisperSTT application..."
cd "$SCRIPT_DIR/app"

# Create icon
"$VENV_DIR/bin/python" - << 'PYTHON'
from PIL import Image, ImageDraw
img = Image.new('RGBA', (128, 128), (102, 126, 234, 255))
draw = ImageDraw.Draw(img)
draw.ellipse([10, 10, 118, 118], fill=(102, 126, 234, 255))
draw.rounded_rectangle([48, 24, 80, 72], radius=16, fill='white')
draw.arc([40, 56, 88, 96], 0, 180, fill='white', width=6)
draw.line([64, 88, 64, 108], fill='white', width=6)
draw.line([48, 108, 80, 108], fill='white', width=6)
img.save('icon.png')
PYTHON

# Build with PyInstaller
"$VENV_DIR/bin/pyinstaller" \
    --name="WhisperSTT" \
    --onefile \
    --windowed \
    --add-data="icon.png:." \
    --hidden-import=PIL._tkinter_finder \
    --hidden-import=customtkinter \
    --hidden-import=pynput.keyboard._xorg \
    --hidden-import=pynput.mouse._xorg \
    --distpath="$INSTALL_DIR" \
    --workpath="/tmp/whisper-build" \
    --specpath="/tmp/whisper-build" \
    stt_app.py -y 2>/dev/null

# Copy icon
cp icon.png "$INSTALL_DIR/"

# Build Docker image if stt-service doesn't exist
if ! docker images | grep -q "stt-service.*latest"; then
    echo "🐳 STT Docker image not found."
    echo "   You need the base stt-service:latest image."
    echo "   The app will prompt you to start it when needed."
else
    echo "✅ STT Docker image found"
fi

# Create desktop entry
echo "🖥️  Creating desktop entry..."
DESKTOP_FILE="$HOME/.local/share/applications/whisper-stt.desktop"
cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Whisper STT
Comment=Speech to Text with Whisper AI (Ctrl+Shift+Space)
Icon=$INSTALL_DIR/icon.png
Exec=$INSTALL_DIR/WhisperSTT
Terminal=false
Categories=AudioVideo;Audio;Utility;
Keywords=speech;text;whisper;transcription;voice;
StartupWMClass=WhisperSTT
EOF

# Update desktop database
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

# Cleanup
rm -rf /tmp/whisper-build 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║       ✅ Installation Complete!                      ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║                                                      ║"
echo "║  Run: ~/.local/share/whisper-stt/WhisperSTT          ║"
echo "║  Or find 'Whisper STT' in your apps menu             ║"
echo "║                                                      ║"
echo "║  Hotkey: Ctrl + Shift + Space                        ║"
echo "║  (works anywhere when app is running)                ║"
echo "║                                                      ║"
echo "╚══════════════════════════════════════════════════════╝"
