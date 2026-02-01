#!/usr/bin/env python3
"""
MCP Server for Speech-to-Text using Whisper Docker service.
"""

import asyncio
import io
import json
import sys
import wave
import tempfile
import subprocess
from typing import Any

import numpy as np
import requests

# MCP Protocol constants
STT_HOST_PORT = 8001
STT_CONTAINER_NAME = "stt-whisper-gui"
STT_IMAGE = "stt-service:latest"
SAMPLE_RATE = 16000
CHANNELS = 1


def send_response(response: dict):
    """Send JSON-RPC response to stdout."""
    msg = json.dumps(response)
    sys.stdout.write(f"Content-Length: {len(msg)}\r\n\r\n{msg}")
    sys.stdout.flush()


def send_error(id: Any, code: int, message: str):
    """Send JSON-RPC error response."""
    send_response({
        "jsonrpc": "2.0",
        "id": id,
        "error": {"code": code, "message": message}
    })


def send_result(id: Any, result: Any):
    """Send JSON-RPC success response."""
    send_response({
        "jsonrpc": "2.0",
        "id": id,
        "result": result
    })


def ensure_container_running() -> bool:
    """Ensure the STT Docker container is running."""
    try:
        # Check if container exists and is running
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", STT_CONTAINER_NAME],
            capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip() == "true":
            return True

        # Start container
        subprocess.run(
            ["docker", "rm", "-f", STT_CONTAINER_NAME],
            capture_output=True
        )

        subprocess.run([
            "docker", "run", "-d",
            "--name", STT_CONTAINER_NAME,
            "--gpus", "all",
            "-p", f"{STT_HOST_PORT}:8000",
            "--rm",
            STT_IMAGE
        ], check=True, capture_output=True)

        # Wait for API to be ready
        for _ in range(60):
            try:
                resp = requests.get(f"http://localhost:{STT_HOST_PORT}/docs", timeout=2)
                if resp.status_code == 200:
                    return True
            except:
                pass
            asyncio.sleep(1)

        return True
    except Exception as e:
        sys.stderr.write(f"Error starting container: {e}\n")
        return False


def record_audio(duration: float = 5.0) -> bytes:
    """Record audio from microphone using ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        temp_path = f.name

    try:
        # Record using ffmpeg with PulseAudio
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "pulse",
            "-i", "default",
            "-t", str(duration),
            "-ar", str(SAMPLE_RATE),
            "-ac", str(CHANNELS),
            temp_path
        ], capture_output=True, check=True)

        with open(temp_path, "rb") as f:
            return f.read()
    except subprocess.CalledProcessError:
        # Fallback to ALSA
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "alsa",
                "-i", "default",
                "-t", str(duration),
                "-ar", str(SAMPLE_RATE),
                "-ac", str(CHANNELS),
                temp_path
            ], capture_output=True, check=True)

            with open(temp_path, "rb") as f:
                return f.read()
        except Exception as e:
            raise RuntimeError(f"Failed to record audio: {e}")
    finally:
        import os
        try:
            os.unlink(temp_path)
        except:
            pass


def transcribe_audio(audio_data: bytes, language: str = None, target_language: str = "en") -> dict:
    """Send audio to STT service and get transcription."""
    files = {
        "file": ("audio.wav", io.BytesIO(audio_data), "audio/wav")
    }

    data = {
        "session_id": "claude-code-stt",
        "chunk_id": 1,
        "target_language": target_language,
    }

    if language:
        data["language"] = language

    response = requests.post(
        f"http://localhost:{STT_HOST_PORT}/chunk/",
        data=data,
        files=files,
        timeout=120
    )

    if response.status_code == 200:
        return response.json()
    else:
        raise RuntimeError(f"STT API error: {response.status_code}")


def handle_initialize(id: Any, params: dict):
    """Handle initialize request."""
    send_result(id, {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {}
        },
        "serverInfo": {
            "name": "stt-server",
            "version": "1.0.0"
        }
    })


def handle_list_tools(id: Any):
    """Handle tools/list request."""
    send_result(id, {
        "tools": [
            {
                "name": "record_and_transcribe",
                "description": "Record audio from microphone and transcribe using Whisper. Returns transcribed text.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "duration": {
                            "type": "number",
                            "description": "Recording duration in seconds (default: 5)",
                            "default": 5
                        },
                        "target_language": {
                            "type": "string",
                            "description": "Target language for translation (en, ru, uk, cs, es, pl)",
                            "default": "en"
                        }
                    }
                }
            },
            {
                "name": "start_stt_container",
                "description": "Start the Whisper STT Docker container with GPU support",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "stop_stt_container",
                "description": "Stop the Whisper STT Docker container",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]
    })


def handle_call_tool(id: Any, params: dict):
    """Handle tools/call request."""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    try:
        if tool_name == "record_and_transcribe":
            duration = arguments.get("duration", 5)
            target_language = arguments.get("target_language", "en")

            # Ensure container is running
            if not ensure_container_running():
                send_result(id, {
                    "content": [{"type": "text", "text": "Error: Could not start STT container"}]
                })
                return

            # Record audio
            sys.stderr.write(f"Recording for {duration} seconds...\n")
            audio_data = record_audio(duration)

            # Transcribe
            sys.stderr.write("Transcribing...\n")
            result = transcribe_audio(audio_data, target_language=target_language)

            raw_text = result.get("raw_text", "")
            translation = result.get("translation", "")
            detected_lang = result.get("detected_language", "unknown")

            output = f"**Original ({detected_lang}):** {raw_text}\n\n**Translation ({target_language}):** {translation}"

            send_result(id, {
                "content": [{"type": "text", "text": output}]
            })

        elif tool_name == "start_stt_container":
            if ensure_container_running():
                send_result(id, {
                    "content": [{"type": "text", "text": "STT container started successfully"}]
                })
            else:
                send_result(id, {
                    "content": [{"type": "text", "text": "Failed to start STT container"}]
                })

        elif tool_name == "stop_stt_container":
            subprocess.run(["docker", "stop", STT_CONTAINER_NAME], capture_output=True)
            send_result(id, {
                "content": [{"type": "text", "text": "STT container stopped"}]
            })

        else:
            send_error(id, -32601, f"Unknown tool: {tool_name}")

    except Exception as e:
        send_result(id, {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}]
        })


def main():
    """Main MCP server loop."""
    sys.stderr.write("STT MCP Server starting...\n")

    buffer = ""
    content_length = None

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break

            buffer += line

            # Parse headers
            if content_length is None:
                if line.startswith("Content-Length:"):
                    content_length = int(line.split(":")[1].strip())
                continue

            # Check for header/body separator
            if line == "\r\n" or line == "\n":
                # Read body
                body = sys.stdin.read(content_length)
                buffer = ""
                content_length = None

                try:
                    request = json.loads(body)
                    method = request.get("method")
                    id = request.get("id")
                    params = request.get("params", {})

                    if method == "initialize":
                        handle_initialize(id, params)
                    elif method == "initialized":
                        pass  # Notification, no response needed
                    elif method == "tools/list":
                        handle_list_tools(id)
                    elif method == "tools/call":
                        handle_call_tool(id, params)
                    else:
                        if id is not None:
                            send_error(id, -32601, f"Method not found: {method}")

                except json.JSONDecodeError as e:
                    sys.stderr.write(f"JSON decode error: {e}\n")

        except Exception as e:
            sys.stderr.write(f"Error: {e}\n")


if __name__ == "__main__":
    main()
