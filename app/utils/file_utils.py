"""
File handling utilities.

Safe I/O for audio uploads, temp files, and generated documents.
Path resolution, cleanup, and format helpers.
"""

import tempfile
from pathlib import Path
from typing import NamedTuple

from fastapi import UploadFile

# ============================================
# Supported Audio Formats
# ============================================

# Centralized list of supported audio formats
# Extension -> MIME types mapping
ALLOWED_AUDIO_FORMATS: dict[str, list[str]] = {
    ".mp3": ["audio/mpeg", "audio/mp3"],
    ".wav": ["audio/wav", "audio/x-wav", "audio/wave"],
    ".m4a": ["audio/mp4", "audio/x-m4a", "audio/m4a"],
    ".aac": ["audio/aac", "audio/x-aac"],
    ".ogg": ["audio/ogg", "application/ogg"],
    ".flac": ["audio/flac", "audio/x-flac"],
    ".webm": ["audio/webm", "video/webm"],  # webm can be audio-only
    ".mp4": ["video/mp4", "audio/mp4"],  # mp4 audio track
    ".mpeg": ["audio/mpeg", "audio/mp3", "audio/x-mpeg", "video/mpeg"],  # MPEG audio
    ".mpg": ["audio/mpeg", "audio/mp3", "audio/x-mpeg", "video/mpeg"],  # MPEG shorthand
}

# Flat set of allowed extensions for quick lookup
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(ALLOWED_AUDIO_FORMATS.keys())

# Flat set of allowed MIME types for quick lookup
ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    mime for mimes in ALLOWED_AUDIO_FORMATS.values() for mime in mimes
)


class AudioValidationResult(NamedTuple):
    """Result of audio file validation."""
    valid: bool
    error: str | None
    extension: str


def validate_audio_file(upload: UploadFile) -> AudioValidationResult:
    """
    Validate an uploaded audio file by extension and MIME type.
    
    Args:
        upload: FastAPI UploadFile object.
        
    Returns:
        AudioValidationResult with validation status, error message (if any),
        and the file extension.
    """
    filename = upload.filename or ""
    extension = suffix_from_filename(filename)
    content_type = upload.content_type or ""
    
    # Check extension
    if extension not in ALLOWED_EXTENSIONS:
        allowed_list = ", ".join(sorted(ALLOWED_EXTENSIONS))
        return AudioValidationResult(
            valid=False,
            error=f"Unsupported file format '{extension}'. Allowed formats: {allowed_list}",
            extension=extension,
        )
    
    # Check MIME type (if provided)
    # We're lenient here: if no content_type or it's generic, we trust the extension
    if content_type and content_type != "application/octet-stream":
        expected_mimes = ALLOWED_AUDIO_FORMATS.get(extension, [])
        if content_type not in expected_mimes and content_type not in ALLOWED_MIME_TYPES:
            # Log but don't reject - browsers sometimes send incorrect MIME types
            pass  # We trust the extension
    
    return AudioValidationResult(valid=True, error=None, extension=extension)


def get_supported_formats_string() -> str:
    """Return a human-readable string of supported audio formats."""
    return ", ".join(ext.lstrip(".").upper() for ext in sorted(ALLOWED_EXTENSIONS))


# ============================================
# Temp File Operations
# ============================================

def write_temp_audio(data: bytes, suffix: str = ".mp3") -> str:
    """
    Write bytes to a temporary audio file.

    Args:
        data: Raw file content.
        suffix: File extension (e.g. .mp3, .wav). Default .mp3.

    Returns:
        Absolute path to the temporary file. Caller must delete via delete_temp_file.
    """
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with open(fd, "wb") as f:
            f.write(data)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise
    return path


def delete_temp_file(path: str) -> None:
    """Remove a temporary file. No-op if already deleted or missing."""
    Path(path).unlink(missing_ok=True)


def suffix_from_filename(filename: str) -> str:
    """
    Extract file extension from filename for temp file naming.

    Normalizes MPEG variants (.mpg) to .mpeg for consistency.

    Returns:
        Extension including leading dot (e.g. .mp3), or .mp3 if none.
    """
    if not filename or "." not in filename:
        return ".mp3"
    ext = "." + filename.rsplit(".", 1)[-1].lower()
    # Normalize .mpg to .mpeg for downstream tools
    if ext == ".mpg":
        return ".mpeg"
    return ext
