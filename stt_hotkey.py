#!/usr/bin/env python3
"""
STT Hotkey Daemon - Global hotkey for speech-to-text.

Press and hold Alt+V to record, release to transcribe.
Result is copied to clipboard and optionally typed into active window.
"""

import io
import os
import sys
import wave
import subprocess
import tempfile
import threading
import time
from typing import Optional

import numpy as np
import requests

try:
    from pynput import keyboard
except ImportError:
    print("Installing pynput...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pynput"], check=True)
    from pynput import keyboard

try:
    import sounddevice as sd
except ImportError:
    print("Installing sounddevice...")
    subprocess.run([sys.executable, "-m", "pip", "install", "sounddevice"], check=True)
    import sounddevice as sd

try:
    import pyperclip
except ImportError:
    print("Installing pyperclip...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pyperclip"], check=True)
    import pyperclip

# Configuration
STT_HOST_PORT = int(os.environ.get("STT_PORT", 8001))
SAMPLE_RATE = 16000
CHANNELS = 1
HOTKEY = keyboard.Key.f9  # Change this to your preferred key
MODIFIER = keyboard.Key.alt  # Modifier key (alt, ctrl, etc.)
AUTO_TYPE = os.environ.get("STT_AUTO_TYPE", "false").lower() == "true"
TARGET_LANGUAGE = os.environ.get("STT_LANGUAGE", "en")


class STTHotkeyDaemon:
    def __init__(self):
        self.recording = False
        self.audio_data = []
        self.stream: Optional[sd.InputStream] = None
        self.modifier_pressed = False
        self.hotkey_pressed = False

        print(f"""
╔══════════════════════════════════════════════════════╗
║           STT Hotkey Daemon Started                  ║
╠══════════════════════════════════════════════════════╣
║  Hotkey: Alt + F9                                    ║
║  Hold to record, release to transcribe               ║
║                                                      ║
║  Result → Clipboard (Ctrl+V to paste)                ║
║                                                      ║
║  Press Ctrl+C to exit                                ║
╚══════════════════════════════════════════════════════╝
""")

    def check_stt_service(self) -> bool:
        """Check if STT service is running."""
        try:
            resp = requests.get(f"http://localhost:{STT_HOST_PORT}/docs", timeout=2)
            return resp.status_code == 200
        except:
            return False

    def notify(self, title: str, message: str, urgency: str = "normal"):
        """Send desktop notification."""
        try:
            subprocess.run([
                "notify-send",
                "-u", urgency,
                "-t", "2000",
                title,
                message
            ], capture_output=True)
        except:
            pass

    def play_sound(self, sound_type: str):
        """Play a short sound for feedback."""
        try:
            if sound_type == "start":
                # Short beep for start
                subprocess.run(["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"],
                             capture_output=True, timeout=1)
            elif sound_type == "stop":
                # Different sound for stop
                subprocess.run(["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                             capture_output=True, timeout=1)
        except:
            pass

    def audio_callback(self, indata, frames, time_info, status):
        """Callback for audio stream."""
        if self.recording:
            self.audio_data.append(indata.copy())

    def start_recording(self):
        """Start recording audio."""
        if self.recording:
            return

        if not self.check_stt_service():
            self.notify("STT Error", "STT service not running!\nStart it from WhisperSTT app", "critical")
            print("❌ STT service not running!")
            return

        self.recording = True
        self.audio_data = []

        print("🎤 Recording... (release Alt+F9 to stop)")
        self.notify("Recording", "Speak now...")
        self.play_sound("start")

        try:
            self.stream = sd.InputStream(
                channels=CHANNELS,
                samplerate=SAMPLE_RATE,
                dtype='float32',
                callback=self.audio_callback
            )
            self.stream.start()
        except Exception as e:
            print(f"❌ Recording error: {e}")
            self.recording = False

    def stop_recording(self):
        """Stop recording and transcribe."""
        if not self.recording:
            return

        self.recording = False

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        self.play_sound("stop")

        if not self.audio_data:
            print("❌ No audio recorded")
            return

        print("⏳ Transcribing...")
        self.notify("Processing", "Transcribing audio...")

        # Process in background thread
        threading.Thread(target=self._process_audio, daemon=True).start()

    def _process_audio(self):
        """Process and transcribe recorded audio."""
        try:
            # Combine audio chunks
            audio = np.concatenate(self.audio_data, axis=0)
            duration = len(audio) / SAMPLE_RATE
            print(f"📊 Audio duration: {duration:.1f}s")

            # Convert to 16-bit PCM
            audio_int16 = (audio * 32767).astype(np.int16)

            # Create WAV in memory
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(CHANNELS)
                wav_file.setsampwidth(2)
                wav_file.setframerate(SAMPLE_RATE)
                wav_file.writeframes(audio_int16.tobytes())

            wav_buffer.seek(0)

            # Send to STT service
            files = {"file": ("audio.wav", wav_buffer, "audio/wav")}
            data = {
                "session_id": "hotkey-stt",
                "chunk_id": int(time.time()),
                "target_language": TARGET_LANGUAGE,
            }

            response = requests.post(
                f"http://localhost:{STT_HOST_PORT}/chunk/",
                data=data,
                files=files,
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                raw_text = result.get("raw_text", "").strip()
                translation = result.get("translation", "").strip()
                detected_lang = result.get("detected_language", "unknown")

                # Use original if same language, otherwise use translation
                if detected_lang == TARGET_LANGUAGE:
                    final_text = raw_text
                else:
                    final_text = translation

                if final_text:
                    # Copy to clipboard
                    pyperclip.copy(final_text)

                    print(f"✅ Transcribed ({detected_lang}): {raw_text[:50]}...")
                    print(f"📋 Copied to clipboard!")

                    self.notify("Transcription Complete",
                              f"{final_text[:100]}..." if len(final_text) > 100 else final_text)

                    # Auto-type if enabled
                    if AUTO_TYPE:
                        self._type_text(final_text)
                else:
                    print("⚠️ No speech detected")
                    self.notify("No Speech", "Could not detect any speech")
            else:
                print(f"❌ STT Error: {response.status_code}")
                self.notify("STT Error", f"API error: {response.status_code}", "critical")

        except Exception as e:
            print(f"❌ Error: {e}")
            self.notify("Error", str(e), "critical")

    def _type_text(self, text: str):
        """Type text into active window using xdotool."""
        try:
            # Small delay to ensure window focus
            time.sleep(0.1)
            subprocess.run(["xdotool", "type", "--clearmodifiers", text], check=True)
        except Exception as e:
            print(f"⚠️ Auto-type failed: {e}")

    def on_press(self, key):
        """Handle key press."""
        if key == MODIFIER:
            self.modifier_pressed = True
        elif key == HOTKEY and self.modifier_pressed:
            if not self.hotkey_pressed:
                self.hotkey_pressed = True
                self.start_recording()

    def on_release(self, key):
        """Handle key release."""
        if key == MODIFIER:
            self.modifier_pressed = False
            if self.hotkey_pressed:
                self.hotkey_pressed = False
                self.stop_recording()
        elif key == HOTKEY:
            if self.hotkey_pressed:
                self.hotkey_pressed = False
                self.stop_recording()

    def run(self):
        """Run the hotkey daemon."""
        with keyboard.Listener(on_press=self.on_press, on_release=self.on_release) as listener:
            try:
                listener.join()
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")


def main():
    daemon = STTHotkeyDaemon()
    daemon.run()


if __name__ == "__main__":
    main()
