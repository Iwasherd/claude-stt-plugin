---
name: transcribe
description: Record voice from microphone and transcribe to text using Whisper
user_invocable: true
arguments:
  - name: duration
    description: Recording duration in seconds (default 5)
    required: false
  - name: language
    description: Target language (en, ru, uk, cs, es, pl)
    required: false
---

# Voice Transcription

Use the `record_and_transcribe` tool to record audio from the user's microphone and transcribe it.

Arguments provided: $ARGUMENTS

If duration is specified, use that value. Otherwise default to 5 seconds.
If language is specified, use that as target_language. Otherwise default to "en".

After getting the transcription, present both the original text and translation to the user.
