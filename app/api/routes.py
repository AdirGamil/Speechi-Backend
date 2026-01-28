"""
API route definitions.

HTTP endpoints for audio upload, transcription, summarization,
and document generation (Word + PDF). No business logic; delegates to services.

Route prefix is configurable via API_PREFIX environment variable:
- Development: /api (routes at /api/process-meeting, etc.)
- Production: "" (routes at /process-meeting, etc.)
"""

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config.settings import settings
from app.models.schemas import APIResponse
from app.services import document_service, summarization_service, transcription_service
from app.utils import file_utils

# Create router with configurable prefix from environment
router = APIRouter(prefix=settings.normalized_api_prefix, tags=["api"])

_SUPPORTED_LANGUAGES = frozenset({"he", "en", "fr", "es", "ar"})


def _validate_request(audio: UploadFile, language: str) -> str:
    """
    Validate audio file and language parameter.
    
    Returns:
        Normalized language code.
        
    Raises:
        HTTPException: If validation fails.
    """
    # Validate language
    lang = language.strip().lower()
    if lang not in _SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language: {language}. Use one of: he, en, fr, es, ar.",
        )
    
    # Validate audio file format
    validation = file_utils.validate_audio_file(audio)
    if not validation.valid:
        raise HTTPException(status_code=400, detail=validation.error)
    
    return lang


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check. Returns API status and configuration info."""
    return {
        "status": "ok",
        "environment": settings.app_env,
        "api_prefix": settings.normalized_api_prefix or "(root)",
    }


@router.get("/supported-formats")
def supported_formats() -> dict[str, list[str]]:
    """Return list of supported audio formats."""
    return {
        "formats": sorted(ext.lstrip(".") for ext in file_utils.ALLOWED_EXTENSIONS),
        "description": file_utils.get_supported_formats_string(),
    }


@router.post("/process-meeting", response_model=APIResponse)
async def process_meeting(
    audio: UploadFile = File(...),
    language: str = Form("en"),
) -> APIResponse:
    """
    Upload audio → transcribe (Whisper) → analyze (Claude) → return transcript + analysis.

    Supported formats: MP3, WAV, M4A, AAC, OGG, FLAC, WEBM, MP4
    language: Output language ISO code (he, en, fr, es, ar). Default en.
    No AI or file logic in route; orchestrates services and utils only.
    """
    lang = _validate_request(audio, language)
    
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    suffix = file_utils.suffix_from_filename(audio.filename or "")
    path = file_utils.write_temp_audio(data, suffix)
    try:
        transcript = transcription_service.transcribe_audio(path)
        analysis = summarization_service.analyze_transcript(transcript, lang)
        return APIResponse(transcript=transcript, analysis=analysis)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    finally:
        file_utils.delete_temp_file(path)


@router.post("/process-meeting/export-docx")
async def process_meeting_export_docx(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    language: str = Form("en"),
):
    """
    E2E: upload audio → transcribe → analyze → generate .docx → return file.

    Supported formats: MP3, WAV, M4A, AAC, OGG, FLAC, WEBM, MP4
    language: Output language ISO code (he, en, fr, es, ar). Default en.
    
    Document headings and content are in the selected language.
    RTL support for Hebrew and Arabic.
    """
    lang = _validate_request(audio, language)
    
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    suffix = file_utils.suffix_from_filename(audio.filename or "")
    path = file_utils.write_temp_audio(data, suffix)
    docx_path = None
    try:
        transcript = transcription_service.transcribe_audio(path)
        analysis = summarization_service.analyze_transcript(transcript, lang)
        docx_path = document_service.generate_word_document(analysis, lang)
        background_tasks.add_task(file_utils.delete_temp_file, docx_path)
        
        # Language-aware filename
        filename = f"meeting_summary_{lang}.docx"
        
        return FileResponse(
            docx_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=filename,
        )
    except ValueError as e:
        if docx_path:
            file_utils.delete_temp_file(docx_path)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        if docx_path:
            file_utils.delete_temp_file(docx_path)
        raise HTTPException(status_code=503, detail=str(e)) from e
    finally:
        file_utils.delete_temp_file(path)


@router.post("/process-meeting/export-pdf")
async def process_meeting_export_pdf(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    language: str = Form("en"),
):
    """
    E2E: upload audio → transcribe → analyze → generate .pdf → return file.

    Supported formats: MP3, WAV, M4A, AAC, OGG, FLAC, WEBM, MP4
    language: Output language ISO code (he, en, fr, es, ar). Default en.
    
    Document headings and content are in the selected language.
    RTL support for Hebrew and Arabic.
    Clean typography with professional styling.
    """
    lang = _validate_request(audio, language)
    
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    suffix = file_utils.suffix_from_filename(audio.filename or "")
    path = file_utils.write_temp_audio(data, suffix)
    pdf_path = None
    try:
        transcript = transcription_service.transcribe_audio(path)
        analysis = summarization_service.analyze_transcript(transcript, lang)
        pdf_path = document_service.generate_pdf_document(analysis, lang)
        background_tasks.add_task(file_utils.delete_temp_file, pdf_path)
        
        # Language-aware filename
        filename = f"meeting_summary_{lang}.pdf"
        
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=filename,
        )
    except ValueError as e:
        if pdf_path:
            file_utils.delete_temp_file(pdf_path)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        if pdf_path:
            file_utils.delete_temp_file(pdf_path)
        raise HTTPException(status_code=503, detail=str(e)) from e
    finally:
        file_utils.delete_temp_file(path)
