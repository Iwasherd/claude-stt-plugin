#!/usr/bin/env python3
"""
STT Hotkey Daemon - Global hotkey for speech-to-text.

Press Ctrl+Shift+Space to start recording, press again to stop and insert text.
Or hold the keys to record, release to transcribe.
"""

import io
import os
import sys
import wave
import subprocess
import threading
import time
from typing import Optional, Set

import numpy as np
import requests

from pynput import keyboard
import sounddevice as sd
import pyperclip

# Configuration
STT_HOST_PORT = int(os.environ.get("STT_PORT", 8001))
SAMPLE_RATE = 16000
CHANNELS = 1
TARGET_LANGUAGE = os.environ.get("STT_LANGUAGE", "en")

# Hotkey: Ctrl + Shift + Space
HOTKEY_COMBO = {keyboard.Key.ctrl_l, keyboard.Key.shift, keyboard.Key.space}
# Alternative: also accept right ctrl
HOTKEY_COMBO_ALT = {keyboard.Key.ctrl_r, keyboard.Key.shift, keyboard.Key.space}


class STTHotkeyDaemon:
    def __init__(self):
        self.recording = False
        self.audio_data = []
        self.stream: Optional[sd.InputStream] = None
        self.current_keys: Set = set()
        self.hotkey_active = False
        self.last_toggle_time = 0

        print("""
╔════════════════════════════════════════════════════════╗
║           STT Hotkey Daemon Started                    ║
╠════════════════════════════════════════════════════════╣
║                                                        ║
║   Hotkey:  Ctrl + Shift + Space                        ║
║                                                        ║
║   • Press once to START recording                      ║
║   • Press again to STOP and insert text                ║
║                                                        ║
║   Text will be automatically typed into Claude Code    ║
║                                                        ║
║   Press Ctrl+C to exit                                 ║
╚════════════════════════════════════════════════════════╝
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
                "-a", "STT",
                title,
                message
            ], capture_output=True)
        except:
            pass

    def play_sound(self, sound_type: str):
        """Play a short sound for feedback."""
        try:
            if sound_type == "start":
                subprocess.Popen(["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sound_type == "stop":
                subprocess.Popen(["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sound_type == "error":
                subprocess.Popen(["paplay", "/usr/share/sounds/freedesktop/stereo/dialog-error.oga"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            self.notify("STT Error", "Start STT container first!\n(Run WhisperSTT app)", "critical")
            self.play_sound("error")
            print("❌ STT service not running! Start the container first.")
            return

        self.recording = True
        self.audio_data = []

        print("🎤 Recording... (press Ctrl+Shift+Space again to stop)")
        self.notify("🎤 Recording", "Speak now...\nPress Ctrl+Shift+Space to stop")
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
            self.play_sound("error")

    def stop_recording(self):
        """Stop recording and transcribe."""
        if not self.recording:
            return

        self.recording = False
        self.play_sound("stop")

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        if not self.audio_data:
            print("❌ No audio recorded")
            return

        print("⏳ Transcribing...")
        self.notify("⏳ Processing", "Transcribing audio...")

        # Process in background thread
        threading.Thread(target=self._process_audio, daemon=True).start()

    def _process_audio(self):
        """Process and transcribe recorded audio."""
        try:
            # Combine audio chunks
            audio = np.concatenate(self.audio_data, axis=0)
            duration = len(audio) / SAMPLE_RATE
            print(f"📊 Audio duration: {duration:.1f}s")

            if duration < 0.5:
                print("⚠️ Recording too short")
                self.notify("Too Short", "Recording was too short", "normal")
                return

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
                detected_lang = result.get("detected_language", "unknown")

                if raw_text:
                    # Copy to clipboard
                    pyperclip.copy(raw_text)

                    print(f"✅ Transcribed ({detected_lang}): {raw_text}")

                    # Auto-type into active window (Claude Code)
                    self._type_text(raw_text)

                    self.notify("✅ Done", raw_text[:100] + ("..." if len(raw_text) > 100 else ""))
                else:
                    print("⚠️ No speech detected")
                    self.notify("No Speech", "Could not detect any speech")
            else:
                print(f"❌ STT Error: {response.status_code}")
                self.notify("STT Error", f"API error: {response.status_code}", "critical")
                self.play_sound("error")

        except Exception as e:
            print(f"❌ Error: {e}")
            self.notify("Error", str(e), "critical")
            self.play_sound("error")

    def _type_text(self, text: str):
        """Type text into active window using xdotool."""
        try:
            # Small delay to ensure we're back in focus
            time.sleep(0.2)

            # Use xdotool to type the text
            # --clearmodifiers releases any held keys first
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--delay", "10", text],
                check=True,
                timeout=30
            )
            print("⌨️ Text inserted into active window")
        except subprocess.TimeoutExpired:
            print("⚠️ Typing timeout - text is in clipboard (Ctrl+V)")
        except Exception as e:
            print(f"⚠️ Auto-type failed: {e} - use Ctrl+V to paste")

    def toggle_recording(self):
        """Toggle recording on/off."""
        # Debounce - prevent double triggers
        now = time.time()
        if now - self.last_toggle_time < 0.5:
            return
        self.last_toggle_time = now

        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def on_press(self, key):
        """Handle key press."""
        self.current_keys.add(key)

        # Check if hotkey combo is pressed
        if (HOTKEY_COMBO.issubset(self.current_keys) or
            HOTKEY_COMBO_ALT.issubset(self.current_keys)):
            if not self.hotkey_active:
                self.hotkey_active = True
                self.toggle_recording()

    def on_release(self, key):
        """Handle key release."""
        self.current_keys.discard(key)

        # Reset hotkey state when any key is released
        if not (HOTKEY_COMBO.issubset(self.current_keys) or
                HOTKEY_COMBO_ALT.issubset(self.current_keys)):
            self.hotkey_active = False

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
