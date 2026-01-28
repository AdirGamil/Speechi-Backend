"""
Transcription service.

Orchestrates audio-to-text via Whisper API.
Handles file validation, format checks, and error handling for transcription.
"""

from pathlib import Path

from openai import OpenAI

from app.utils.env_utils import get_openai_api_key

WHISPER_MODEL = "whisper-1"


def transcribe_audio(file_path: str) -> str:
    """
    Transcribe an audio file to plain text using the OpenAI Whisper API.

    Args:
        file_path: Path to the audio file (e.g. mp3, wav, m4a).

    Returns:
        Plain-text transcript.

    Raises:
        ValueError: Invalid or unreadable file.
        RuntimeError: Missing OPENAI_API_KEY or Whisper API failure.
    """
    path = Path(file_path)
    if not path.exists():
        raise ValueError(f"File not found: {file_path}")
    if not path.is_file():
        raise ValueError(f"Not a file: {file_path}")

    api_key = get_openai_api_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    try:
        client = OpenAI(api_key=api_key)
        with open(path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model=WHISPER_MODEL,
                file=audio_file,
            )
        return response.text or ""
    except OSError as e:
        raise ValueError(f"Cannot read file: {file_path}") from e
    except Exception as e:
        raise RuntimeError(f"Whisper API failed: {e}") from e
