#!/usr/bin/env python3
"""
STT Whisper GUI Application
Speech-to-Text with Docker Whisper service, GPU support, and clipboard integration.
Global hotkey: Ctrl+Shift+Space to record from anywhere.
"""

import io
import os
import sys
import uuid
import wave
import threading
import queue
import subprocess
import tempfile
import logging
from datetime import datetime
from typing import Optional, Set

import customtkinter as ctk
import sounddevice as sd
import numpy as np
import requests
import pyperclip
import docker
from PIL import Image
from pynput import keyboard

# Constants
STT_CONTAINER_NAME = "stt-whisper-gui"
STT_IMAGE = "stt-service:latest"
STT_INTERNAL_PORT = 8000  # Port inside container (uvicorn)
STT_HOST_PORT = 8001      # Port exposed on host
SAMPLE_RATE = 16000
CHANNELS = 1

# Supported languages for translation
SUPPORTED_LANGUAGES = {
    "English": "en",
    "Russian": "ru",
    "Ukrainian": "uk",
    "Czech": "cs",
    "Spanish": "es",
    "Polish": "pl",
}


class LogHandler(logging.Handler):
    """Custom log handler that writes to a CTkTextbox."""
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        def append():
            self.text_widget.configure(state="normal")
            self.text_widget.insert("end", msg + "\n")
            self.text_widget.see("end")
            self.text_widget.configure(state="disabled")
        self.text_widget.after(0, append)


class STTApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window setup
        self.title("Whisper STT")
        self.geometry("700x650")
        self.minsize(600, 550)

        # Set theme
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Docker client
        self.docker_client: Optional[docker.DockerClient] = None
        self.container = None
        self.container_running = False  # Track state explicitly

        # Audio state
        self.recording = False
        self.audio_queue = queue.Queue()
        self.audio_data = []
        self.stream = None
        self.session_id = str(uuid.uuid4())
        self.chunk_counter = 0

        # Hotkey state
        self.hotkey_recording = False
        self.hotkey_audio_data = []
        self.hotkey_stream = None
        self.current_keys: Set = set()
        self.hotkey_active = False
        self.last_hotkey_time = 0
        self.keyboard_listener = None

        # Build UI
        self._create_widgets()

        # Setup logging
        self._setup_logging()

        self._populate_microphones()
        self._check_docker_status()

        # Start global hotkey listener
        self._start_hotkey_listener()

        # Bind close event
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_logging(self):
        """Setup logging to the log textbox."""
        self.logger = logging.getLogger("STTApp")
        self.logger.setLevel(logging.DEBUG)

        # Add handler for the text widget
        handler = LogHandler(self.log_text)
        handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
        self.logger.addHandler(handler)

        # Also log to console
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        self.logger.addHandler(console)

        self.logger.info("Application started")

    def _create_widgets(self):
        # Main container
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # === Docker Status Frame ===
        docker_frame = ctk.CTkFrame(self)
        docker_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        docker_frame.grid_columnconfigure(1, weight=1)

        self.docker_status_label = ctk.CTkLabel(docker_frame, text="Docker: Checking...", font=ctk.CTkFont(size=14))
        self.docker_status_label.grid(row=0, column=0, padx=10, pady=10)

        self.docker_btn = ctk.CTkButton(
            docker_frame,
            text="Start Container",
            command=self._toggle_container,
            width=140
        )
        self.docker_btn.grid(row=0, column=1, padx=10, pady=10, sticky="e")

        self.refresh_btn = ctk.CTkButton(
            docker_frame,
            text="↻ Refresh",
            command=self._check_docker_status,
            width=80
        )
        self.refresh_btn.grid(row=0, column=2, padx=5, pady=10)

        # === Settings Frame ===
        settings_frame = ctk.CTkFrame(self)
        settings_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        settings_frame.grid_columnconfigure(1, weight=1)
        settings_frame.grid_columnconfigure(3, weight=1)

        # Microphone selection
        ctk.CTkLabel(settings_frame, text="Microphone:").grid(row=0, column=0, padx=10, pady=10)
        self.mic_combo = ctk.CTkComboBox(settings_frame, values=["Loading..."], width=200)
        self.mic_combo.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        # Language selection
        ctk.CTkLabel(settings_frame, text="Translate to:").grid(row=0, column=2, padx=10, pady=10)
        self.lang_combo = ctk.CTkComboBox(
            settings_frame,
            values=list(SUPPORTED_LANGUAGES.keys()),
            width=120
        )
        self.lang_combo.set("English")
        self.lang_combo.grid(row=0, column=3, padx=10, pady=10, sticky="ew")

        # Auto-detect source language checkbox
        self.auto_detect_var = ctk.BooleanVar(value=True)
        self.auto_detect_cb = ctk.CTkCheckBox(
            settings_frame,
            text="Auto-detect source language",
            variable=self.auto_detect_var
        )
        self.auto_detect_cb.grid(row=1, column=0, columnspan=4, padx=10, pady=(0, 10))

        # === Record Button ===
        self.record_btn = ctk.CTkButton(
            self,
            text="🎤 Start Recording",
            command=self._toggle_recording,
            height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#c0392b",
            hover_color="#e74c3c"
        )
        self.record_btn.grid(row=2, column=0, padx=10, pady=10, sticky="ew")

        # === Result Frame (Two Columns) ===
        result_frame = ctk.CTkFrame(self)
        result_frame.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        result_frame.grid_columnconfigure(0, weight=1)
        result_frame.grid_columnconfigure(1, weight=1)
        result_frame.grid_rowconfigure(1, weight=1)

        # --- Left Column: Original ---
        ctk.CTkLabel(result_frame, text="Original:", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(5, 0)
        )
        self.copy_raw_btn = ctk.CTkButton(
            result_frame, text="Copy", width=60, height=24,
            command=lambda: self._copy_text("raw")
        )
        self.copy_raw_btn.grid(row=0, column=0, sticky="e", padx=10, pady=(5, 0))

        self.original_text = ctk.CTkTextbox(result_frame, wrap="word", height=100)
        self.original_text.grid(row=1, column=0, padx=(10, 5), pady=5, sticky="nsew")

        # --- Right Column: Translation ---
        ctk.CTkLabel(result_frame, text="Translation:", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=1, sticky="w", padx=10, pady=(5, 0)
        )
        self.copy_trans_btn = ctk.CTkButton(
            result_frame, text="Copy", width=60, height=24,
            command=lambda: self._copy_text("translation")
        )
        self.copy_trans_btn.grid(row=0, column=1, sticky="e", padx=10, pady=(5, 0))

        self.translation_text = ctk.CTkTextbox(result_frame, wrap="word", height=100)
        self.translation_text.grid(row=1, column=1, padx=(5, 10), pady=5, sticky="nsew")

        # === Log Frame ===
        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=4, column=0, padx=10, pady=5, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(log_frame, text="Log:", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w", padx=5, pady=(5, 0)
        )

        self.log_text = ctk.CTkTextbox(log_frame, wrap="word", height=120, font=ctk.CTkFont(size=11))
        self.log_text.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        self.log_text.configure(state="disabled")

        # === Status Bar ===
        self.status_label = ctk.CTkLabel(self, text="Ready", anchor="w")
        self.status_label.grid(row=5, column=0, padx=10, pady=(0, 10), sticky="ew")

        # Store results
        self.last_raw_text = ""
        self.last_translation = ""

    def _populate_microphones(self):
        """Populate microphone dropdown with available input devices."""
        try:
            devices = sd.query_devices()
            input_devices = []

            self.logger.info(f"Found {len(devices)} audio devices")

            for i, dev in enumerate(devices):
                if dev['max_input_channels'] > 0:
                    name = f"{dev['name']}"
                    input_devices.append((i, name))
                    self.logger.debug(f"  Input device {i}: {name}")

            if input_devices:
                self.mic_devices = {name: idx for idx, name in input_devices}
                self.mic_combo.configure(values=list(self.mic_devices.keys()))
                self.mic_combo.set(list(self.mic_devices.keys())[0])
                self.logger.info(f"Selected microphone: {list(self.mic_devices.keys())[0]}")
            else:
                self.mic_combo.configure(values=["No microphones found"])
                self.mic_devices = {}
                self.logger.warning("No microphones found!")
        except Exception as e:
            self.mic_combo.configure(values=[f"Error: {e}"])
            self.mic_devices = {}
            self.logger.error(f"Error enumerating microphones: {e}")

    def _check_docker_status(self):
        """Check Docker and container status."""
        self.logger.info("Checking Docker status...")
        try:
            self.docker_client = docker.from_env()
            self.docker_client.ping()
            self.logger.info("Docker daemon is running")

            # Check if container is running
            try:
                self.container = self.docker_client.containers.get(STT_CONTAINER_NAME)
                self.container.reload()  # Refresh status from Docker
                status = self.container.status
                self.logger.info(f"Container '{STT_CONTAINER_NAME}' found, status: {status}")

                if status == "running":
                    self.container_running = True
                    self._set_docker_status("running")
                    # Verify API is responding
                    self._verify_api_health()
                else:
                    self.container_running = False
                    self._set_docker_status("stopped")
            except docker.errors.NotFound:
                self.container = None
                self.container_running = False
                self.logger.info(f"Container '{STT_CONTAINER_NAME}' not found")
                self._set_docker_status("not_created")

        except Exception as e:
            self.logger.error(f"Docker error: {e}")
            self._set_docker_status("error", str(e))

    def _verify_api_health(self):
        """Check if the STT API is responding."""
        try:
            resp = requests.get(f"http://localhost:{STT_HOST_PORT}/docs", timeout=3)
            if resp.status_code == 200:
                self.logger.info(f"STT API is healthy at port {STT_HOST_PORT}")
            else:
                self.logger.warning(f"STT API responded with status {resp.status_code}")
        except requests.exceptions.ConnectionError:
            self.logger.warning(f"Cannot connect to STT API at port {STT_HOST_PORT}")
        except Exception as e:
            self.logger.warning(f"API health check failed: {e}")

    def _set_docker_status(self, status: str, error: str = ""):
        """Update Docker status display."""
        self.docker_btn.configure(state="normal")

        if status == "running":
            self.docker_status_label.configure(text="Docker: ✅ Running", text_color="green")
            self.docker_btn.configure(text="Stop Container")
            self.container_running = True
        elif status == "stopped":
            self.docker_status_label.configure(text="Docker: ⏸️ Stopped", text_color="orange")
            self.docker_btn.configure(text="Start Container")
            self.container_running = False
        elif status == "not_created":
            self.docker_status_label.configure(text="Docker: ⚪ Not started", text_color="gray")
            self.docker_btn.configure(text="Start Container")
            self.container_running = False
        elif status == "starting":
            self.docker_status_label.configure(text="Docker: ⏳ Starting...", text_color="yellow")
            self.docker_btn.configure(state="disabled")
            self.container_running = False
        else:
            self.docker_status_label.configure(text=f"Docker: ❌ Error", text_color="red")
            self.docker_btn.configure(state="disabled")
            self.container_running = False
            self._set_status(f"Docker error: {error}")

    def _toggle_container(self):
        """Start or stop the STT container."""
        self.logger.info("Toggle container requested")
        threading.Thread(target=self._toggle_container_thread, daemon=True).start()

    def _toggle_container_thread(self):
        """Container toggle in background thread."""
        try:
            # Refresh container status first
            try:
                self.container = self.docker_client.containers.get(STT_CONTAINER_NAME)
                self.container.reload()
                current_status = self.container.status
                self.logger.info(f"Current container status: {current_status}")
            except docker.errors.NotFound:
                current_status = "not_found"
                self.container = None
                self.logger.info("Container not found")

            if current_status == "running":
                self.logger.info("Stopping container...")
                self._set_status("Stopping container...")
                self.container.stop(timeout=10)
                self.container_running = False
                self.after(0, lambda: self._set_docker_status("stopped"))
                self.logger.info("Container stopped")
                self._set_status("Container stopped")
            else:
                self.after(0, lambda: self._set_docker_status("starting"))
                self.logger.info("Starting container with GPU...")
                self._set_status("Starting container with GPU...")

                # Remove existing container if exists
                try:
                    old = self.docker_client.containers.get(STT_CONTAINER_NAME)
                    self.logger.info("Removing old container...")
                    old.remove(force=True)
                except docker.errors.NotFound:
                    pass

                # Start new container with GPU
                self.logger.info(f"Creating container from image {STT_IMAGE}...")
                self.container = self.docker_client.containers.run(
                    STT_IMAGE,
                    name=STT_CONTAINER_NAME,
                    detach=True,
                    ports={f"{STT_INTERNAL_PORT}/tcp": STT_HOST_PORT},  # Map container:8000 -> host:8001
                    device_requests=[
                        docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])
                    ],
                    remove=True
                )
                self.logger.info(f"Container created with ID: {self.container.short_id}")

                # Wait for service to be ready
                self._set_status("Waiting for Whisper model to load (this takes ~30-60s)...")
                self.logger.info("Waiting for API to become ready...")

                import time
                for i in range(90):  # Wait up to 90 seconds
                    try:
                        resp = requests.get(f"http://localhost:{STT_HOST_PORT}/docs", timeout=2)
                        if resp.status_code == 200:
                            self.logger.info(f"API ready after {i+1} seconds")
                            break
                    except requests.exceptions.ConnectionError:
                        pass
                    except Exception as e:
                        self.logger.debug(f"Waiting... ({i+1}s) - {e}")
                    time.sleep(1)
                    if i % 10 == 0:
                        self.logger.info(f"Still waiting for API... ({i}s)")
                else:
                    self.logger.warning("API did not become ready within 90 seconds")

                self.container_running = True
                self.after(0, lambda: self._set_docker_status("running"))
                self.logger.info("Container ready!")
                self._set_status("Container ready!")

        except Exception as e:
            self.logger.error(f"Container error: {e}")
            self.after(0, lambda: self._set_docker_status("error", str(e)))
            self._set_status(f"Error: {e}")

    def _toggle_recording(self):
        """Start or stop recording."""
        if not self.recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        """Start audio recording."""
        self.logger.info("Start recording requested")

        if not self.mic_devices:
            self.logger.error("No microphone available")
            self._set_status("No microphone available")
            return

        # Check container is running
        self.logger.info(f"Container running flag: {self.container_running}")
        self.logger.info(f"Container object: {self.container}")

        if not self.container_running:
            self.logger.warning("Container not running - cannot record")
            self._set_status("Please start the container first")
            return

        # Double-check by refreshing container status
        if self.container:
            try:
                self.container.reload()
                self.logger.info(f"Container status after reload: {self.container.status}")
                if self.container.status != "running":
                    self.logger.warning(f"Container status is {self.container.status}, not running")
                    self._set_status("Container is not running - click Refresh")
                    return
            except Exception as e:
                self.logger.error(f"Error checking container: {e}")
                self._set_status(f"Error: {e}")
                return

        try:
            mic_name = self.mic_combo.get()
            device_id = self.mic_devices.get(mic_name)
            self.logger.info(f"Using microphone: {mic_name} (device {device_id})")

            self.recording = True
            self.audio_data = []
            self.record_btn.configure(
                text="⏹️ Stop Recording",
                fg_color="#27ae60",
                hover_color="#2ecc71"
            )
            self._set_status("Recording...")
            self.logger.info("Recording started")

            # Start audio stream
            self.stream = sd.InputStream(
                device=device_id,
                channels=CHANNELS,
                samplerate=SAMPLE_RATE,
                dtype='float32',
                callback=self._audio_callback
            )
            self.stream.start()

        except Exception as e:
            self.recording = False
            self.logger.error(f"Recording error: {e}")
            self._set_status(f"Recording error: {e}")

    def _audio_callback(self, indata, frames, time, status):
        """Callback for audio stream."""
        if status:
            self.logger.warning(f"Audio callback status: {status}")
        self.audio_data.append(indata.copy())

    def _stop_recording(self):
        """Stop recording and process audio."""
        self.recording = False
        self.record_btn.configure(
            text="🎤 Start Recording",
            fg_color="#c0392b",
            hover_color="#e74c3c"
        )

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        if self.audio_data:
            duration = len(self.audio_data) * 1024 / SAMPLE_RATE  # approximate
            self.logger.info(f"Recording stopped. Captured ~{duration:.1f}s of audio")
            self._set_status("Processing audio...")
            threading.Thread(target=self._process_audio, daemon=True).start()
        else:
            self.logger.warning("No audio data captured")
            self._set_status("No audio recorded")

    def _process_audio(self):
        """Process recorded audio and send to STT service."""
        try:
            # Combine audio chunks
            audio = np.concatenate(self.audio_data, axis=0)
            self.logger.info(f"Audio shape: {audio.shape}, duration: {len(audio)/SAMPLE_RATE:.2f}s")

            # Convert to 16-bit PCM
            audio_int16 = (audio * 32767).astype(np.int16)

            # Create WAV file in memory
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(CHANNELS)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(SAMPLE_RATE)
                wav_file.writeframes(audio_int16.tobytes())

            wav_buffer.seek(0)
            wav_size = len(wav_buffer.getvalue())
            self.logger.info(f"WAV file size: {wav_size} bytes")

            # Prepare request
            target_lang = SUPPORTED_LANGUAGES.get(self.lang_combo.get(), "en")

            self.chunk_counter += 1

            data = {
                "session_id": self.session_id,
                "chunk_id": self.chunk_counter,
                "target_language": target_lang,
            }

            if not self.auto_detect_var.get():
                data["language"] = "en"  # Default source if not auto-detecting

            files = {
                "file": ("audio.wav", wav_buffer, "audio/wav")
            }

            self.logger.info(f"Sending to STT API: session={self.session_id}, chunk={self.chunk_counter}, target={target_lang}")

            # Send to STT service
            response = requests.post(
                f"http://localhost:{STT_HOST_PORT}/chunk/",
                data=data,
                files=files,
                timeout=120
            )

            self.logger.info(f"API response status: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                self.last_raw_text = result.get("raw_text", "")
                self.last_translation = result.get("translation", "")
                detected_lang = result.get("detected_language", "unknown")
                proc_time = result.get("processing_time_s", 0)

                self.logger.info(f"Transcription successful: detected={detected_lang}, time={proc_time:.2f}s")
                self.logger.info(f"Raw text: {self.last_raw_text[:100]}...")

                # Update UI
                self.after(0, lambda: self._display_result(
                    self.last_raw_text,
                    self.last_translation,
                    detected_lang,
                    proc_time
                ))
            else:
                self.logger.error(f"STT API error: {response.status_code} - {response.text}")
                self._set_status(f"STT Error: {response.status_code}")

        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"Cannot connect to STT API: {e}")
            self._set_status("Cannot connect to STT service")
        except Exception as e:
            self.logger.error(f"Processing error: {e}")
            self._set_status(f"Processing error: {e}")

    def _display_result(self, raw: str, translation: str, detected_lang: str, proc_time: float):
        """Display transcription result."""
        # Original text (left column)
        self.original_text.delete("0.0", "end")
        self.original_text.insert("0.0", raw)

        # Translation (right column)
        self.translation_text.delete("0.0", "end")
        self.translation_text.insert("0.0", translation)

        self._set_status(f"Done! Detected: {detected_lang}, time: {proc_time:.2f}s")

    def _copy_text(self, which: str):
        """Copy text to clipboard."""
        try:
            if which == "raw":
                pyperclip.copy(self.last_raw_text)
                self.logger.info("Copied original text to clipboard")
                self._set_status("Original text copied to clipboard!")
            else:
                pyperclip.copy(self.last_translation)
                self.logger.info("Copied translation to clipboard")
                self._set_status("Translation copied to clipboard!")
        except Exception as e:
            self.logger.error(f"Clipboard error: {e}")
            self._set_status(f"Copy failed: {e}")

    def _set_status(self, text: str):
        """Update status bar."""
        self.after(0, lambda: self.status_label.configure(text=text))

    # ==================== GLOBAL HOTKEY SUPPORT ====================

    def _start_hotkey_listener(self):
        """Start the global hotkey listener."""
        self.logger.info("Starting global hotkey listener (Ctrl+Shift+Space)")

        # Define hotkey combinations
        self.hotkey_combo = {keyboard.Key.ctrl_l, keyboard.Key.shift, keyboard.Key.space}
        self.hotkey_combo_alt = {keyboard.Key.ctrl_r, keyboard.Key.shift, keyboard.Key.space}

        def on_press(key):
            self.current_keys.add(key)
            if (self.hotkey_combo.issubset(self.current_keys) or
                self.hotkey_combo_alt.issubset(self.current_keys)):
                if not self.hotkey_active:
                    self.hotkey_active = True
                    self.after(0, self._hotkey_toggle)

        def on_release(key):
            self.current_keys.discard(key)
            if not (self.hotkey_combo.issubset(self.current_keys) or
                    self.hotkey_combo_alt.issubset(self.current_keys)):
                self.hotkey_active = False

        self.keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.keyboard_listener.daemon = True
        self.keyboard_listener.start()

    def _hotkey_toggle(self):
        """Toggle hotkey recording on/off."""
        import time
        now = time.time()
        if now - self.last_hotkey_time < 0.5:
            return
        self.last_hotkey_time = now

        if self.hotkey_recording:
            self._hotkey_stop_recording()
        else:
            self._hotkey_start_recording()

    def _hotkey_start_recording(self):
        """Start recording via hotkey."""
        if self.hotkey_recording:
            return

        if not self.container_running:
            self._notify("STT Error", "Start container first!")
            self.logger.warning("Hotkey: Container not running")
            return

        self.hotkey_recording = True
        self.hotkey_audio_data = []

        self.logger.info("🎤 Hotkey recording started (Ctrl+Shift+Space to stop)")
        self._set_status("🎤 Recording... (Ctrl+Shift+Space to stop)")
        self._notify("🎤 Recording", "Speak now...")
        self._play_sound("start")

        try:
            self.hotkey_stream = sd.InputStream(
                channels=CHANNELS,
                samplerate=SAMPLE_RATE,
                dtype='float32',
                callback=self._hotkey_audio_callback
            )
            self.hotkey_stream.start()
        except Exception as e:
            self.logger.error(f"Hotkey recording error: {e}")
            self.hotkey_recording = False

    def _hotkey_audio_callback(self, indata, frames, time_info, status):
        """Audio callback for hotkey recording."""
        if self.hotkey_recording:
            self.hotkey_audio_data.append(indata.copy())

    def _hotkey_stop_recording(self):
        """Stop hotkey recording and transcribe."""
        if not self.hotkey_recording:
            return

        self.hotkey_recording = False
        self._play_sound("stop")

        if self.hotkey_stream:
            self.hotkey_stream.stop()
            self.hotkey_stream.close()
            self.hotkey_stream = None

        if not self.hotkey_audio_data:
            self.logger.warning("Hotkey: No audio recorded")
            return

        self.logger.info("⏳ Hotkey: Transcribing...")
        self._set_status("⏳ Processing hotkey recording...")
        self._notify("⏳ Processing", "Transcribing...")

        threading.Thread(target=self._hotkey_process_audio, daemon=True).start()

    def _hotkey_process_audio(self):
        """Process hotkey audio and transcribe."""
        try:
            audio = np.concatenate(self.hotkey_audio_data, axis=0)
            duration = len(audio) / SAMPLE_RATE
            self.logger.info(f"Hotkey audio: {duration:.1f}s")

            if duration < 0.5:
                self.logger.warning("Hotkey: Recording too short")
                self._notify("Too Short", "Recording was too short")
                return

            # Convert to WAV
            audio_int16 = (audio * 32767).astype(np.int16)
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(CHANNELS)
                wav_file.setsampwidth(2)
                wav_file.setframerate(SAMPLE_RATE)
                wav_file.writeframes(audio_int16.tobytes())
            wav_buffer.seek(0)

            # Get target language from UI
            target_lang = SUPPORTED_LANGUAGES.get(self.lang_combo.get(), "en")

            # Send to STT
            response = requests.post(
                f"http://localhost:{STT_HOST_PORT}/chunk/",
                data={
                    "session_id": "hotkey-stt",
                    "chunk_id": int(datetime.now().timestamp()),
                    "target_language": target_lang,
                },
                files={"file": ("audio.wav", wav_buffer, "audio/wav")},
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                raw_text = result.get("raw_text", "").strip()
                detected_lang = result.get("detected_language", "unknown")

                if raw_text:
                    pyperclip.copy(raw_text)
                    self.logger.info(f"✅ Hotkey transcribed ({detected_lang}): {raw_text[:50]}...")

                    # Update UI
                    self.after(0, lambda: self._display_hotkey_result(raw_text, result.get("translation", ""), detected_lang))

                    # Auto-type into active window
                    self._auto_type(raw_text)

                    self._notify("✅ Done", raw_text[:80])
                else:
                    self.logger.warning("Hotkey: No speech detected")
                    self._notify("No Speech", "Could not detect speech")
            else:
                self.logger.error(f"Hotkey STT error: {response.status_code}")

        except Exception as e:
            self.logger.error(f"Hotkey processing error: {e}")

    def _display_hotkey_result(self, raw: str, translation: str, detected_lang: str):
        """Display hotkey result in UI."""
        self.last_raw_text = raw
        self.last_translation = translation
        self.original_text.delete("0.0", "end")
        self.original_text.insert("0.0", raw)
        self.translation_text.delete("0.0", "end")
        self.translation_text.insert("0.0", translation)
        self._set_status(f"✅ Hotkey done! ({detected_lang})")

    def _auto_type(self, text: str):
        """Type text into active window using xdotool."""
        try:
            import time
            time.sleep(0.2)
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--delay", "10", text],
                check=True, timeout=30
            )
            self.logger.info("⌨️ Text inserted via xdotool")
        except Exception as e:
            self.logger.warning(f"Auto-type failed: {e} (use Ctrl+V)")

    def _notify(self, title: str, message: str):
        """Send desktop notification."""
        try:
            subprocess.run([
                "notify-send", "-u", "normal", "-t", "2000",
                "-a", "WhisperSTT", title, message
            ], capture_output=True)
        except:
            pass

    def _play_sound(self, sound_type: str):
        """Play feedback sound."""
        sounds = {
            "start": "/usr/share/sounds/freedesktop/stereo/message.oga",
            "stop": "/usr/share/sounds/freedesktop/stereo/complete.oga",
        }
        if sound_type in sounds:
            try:
                subprocess.Popen(["paplay", sounds[sound_type]],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except:
                pass

    def _on_close(self):
        """Handle window close."""
        self.logger.info("Application closing")
        if self.stream:
            self.stream.stop()
            self.stream.close()
        if self.hotkey_stream:
            self.hotkey_stream.stop()
            self.hotkey_stream.close()
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        self.destroy()


def main():
    app = STTApp()
    app.mainloop()


if __name__ == "__main__":
    main()
