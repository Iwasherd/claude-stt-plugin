#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Building Whisper STT Application ==="

# Activate virtual environment
source venv/bin/activate

# Create icons
echo "Creating icons..."
python create_icon.py

# Check if icon was created, use fallback if not
if [ ! -f "icon.png" ]; then
    echo "Warning: Icon creation failed. Using fallback method..."
    # Create a simple fallback icon using Python/PIL
    python3 -c "
from PIL import Image, ImageDraw
img = Image.new('RGBA', (128, 128), (102, 126, 234, 255))
draw = ImageDraw.Draw(img)
draw.ellipse([10, 10, 118, 118], fill=(102, 126, 234, 255))
draw.rounded_rectangle([48, 24, 80, 72], radius=16, fill='white')
draw.arc([40, 56, 88, 96], 0, 180, fill='white', width=6)
draw.line([64, 88, 64, 108], fill='white', width=6)
draw.line([48, 108, 80, 108], fill='white', width=6)
img.save('icon.png')
print('Created fallback icon.png')
"
fi

# Build with PyInstaller
echo "Building executable with PyInstaller..."
pyinstaller \
    --name="WhisperSTT" \
    --onefile \
    --windowed \
    --icon=icon.png \
    --add-data="icon.png:." \
    --hidden-import=PIL._tkinter_finder \
    --hidden-import=customtkinter \
    stt_app.py

echo "Build complete!"

# Create installation directory
INSTALL_DIR="$HOME/.local/share/whisper-stt"
mkdir -p "$INSTALL_DIR"

# Copy executable and icon
cp dist/WhisperSTT "$INSTALL_DIR/"
cp icon.png "$INSTALL_DIR/"

# Make executable
chmod +x "$INSTALL_DIR/WhisperSTT"

# Create desktop entry
DESKTOP_FILE="$HOME/.local/share/applications/whisper-stt.desktop"
cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Whisper STT
Comment=Speech to Text with Whisper AI
Icon=$INSTALL_DIR/icon.png
Exec=$INSTALL_DIR/WhisperSTT
Terminal=false
Categories=AudioVideo;Audio;Utility;
Keywords=speech;text;whisper;transcription;voice;
StartupWMClass=WhisperSTT
EOF

echo "=== Installation complete! ==="
echo "Executable: $INSTALL_DIR/WhisperSTT"
echo "Desktop entry: $DESKTOP_FILE"
echo ""
echo "The app should now appear in your Ubuntu applications menu."
echo "You may need to log out and back in, or run: update-desktop-database ~/.local/share/applications"
