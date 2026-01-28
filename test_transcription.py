#!/usr/bin/env python3
"""
CLI test: transcribe a local audio file via OpenAI Whisper only.

Uses transcription_service. Prints the full transcript to stdout.
No Claude, no FastAPI, no summarization. Fails loudly on error.
"""

import sys

from app.services.transcription_service import transcribe_audio


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python test_transcription.py <audio_file_path>")
    path = sys.argv[1].strip()
    if not path:
        raise SystemExit("Error: audio file path is empty")

    transcript = transcribe_audio(path)
    print(transcript)


if __name__ == "__main__":
    main()
