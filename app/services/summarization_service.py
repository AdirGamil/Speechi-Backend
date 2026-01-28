"""
Summarization service.

Orchestrates LLM-based analysis and meeting summarization (e.g. Claude).
Consumes transcription output and produces structured summary data.
"""

import json
from pathlib import Path

from anthropic import Anthropic

from app.models.schemas import AnalysisResult
from app.utils.env_utils import get_anthropic_api_key

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "meeting_summary_prompt.txt"
_CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
_MAX_TOKENS = 4096


def _load_prompt() -> str:
    """Load the meeting-analysis system prompt from disk."""
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _extract_json(raw: str) -> str:
    """
    Extract JSON from Claude response, removing markdown code fences if present.

    Handles cases where Claude wraps JSON in ```json ... ``` despite prompt instructions.
    Does not attempt to fix malformed JSON; that remains a ValueError.

    Args:
        raw: Raw Claude response text.

    Returns:
        Cleaned string ready for json.loads.
    """
    s = raw.strip()
    # Remove leading code fence markers (```json or ```)
    for marker in ("```json", "```"):
        if s.startswith(marker):
            s = s[len(marker) :].lstrip("\n\r")
            break
    # Remove trailing ```
    if s.endswith("```"):
        s = s[: -len("```")].rstrip("\n\r")
    return s.strip()


def analyze_transcript(transcript: str, output_language: str) -> AnalysisResult:
    """
    Analyze a meeting transcript and return structured summary data.

    Uses Claude with the meeting-summary system prompt. Sends transcript and
    target output language; expects raw JSON conforming to AnalysisResult.
    Parses and validates. No markdown or extra text in LLM output.

    Args:
        transcript: Plain-text transcript (e.g. from Whisper).
        output_language: Target output language ISO code (he, en, fr, es, ar).

    Returns:
        AnalysisResult with summary, participants, decisions, action_items,
        translated_transcript.

    Raises:
        RuntimeError: Missing ANTHROPIC_API_KEY or Claude API failure.
        ValueError: Response could not be parsed as valid AnalysisResult.
    """
    api_key = get_anthropic_api_key()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    system = _load_prompt()
    transcript_block = transcript.strip() if transcript.strip() else "(empty)"
    user_content = f"Target output language: {output_language}\n\nTranscript:\n\n{transcript_block}"

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as e:
        raise RuntimeError(f"Claude API failed: {e}") from e

    text = ""
    for block in response.content:
        text += getattr(block, "text", "") or ""

    text = text.strip()
    if not text:
        raise ValueError("Claude returned empty analysis")

    # Extract JSON, removing markdown code fences if present.
    cleaned = _extract_json(text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude response is not valid JSON: {e}") from e

    try:
        return AnalysisResult.model_validate(data)
    except Exception as e:
        raise ValueError(f"Analysis result does not match schema: {e}") from e
