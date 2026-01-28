"""
Pydantic schemas and DTOs.

Request/response models for API, internal data shapes for
transcription, summarization, and document generation.
"""

from typing import Optional

from pydantic import BaseModel


class ActionItem(BaseModel):
    """A single action item from meeting analysis."""

    description: str
    owner: Optional[str] = None


class AnalysisResult(BaseModel):
    """
    Structured output of LLM-based meeting analysis.

    Includes summary, participants, decisions, action items, and a
    translated transcript in the requested output language.
    """

    summary: str
    """Concise meeting summary in the output language."""

    participants: list[str]
    """Names or identifiers of participants. Empty if none identified."""

    decisions: list[str]
    """Decisions clearly stated or agreed. Empty if none."""

    action_items: list[ActionItem]
    """Action items with description and optional owner."""

    translated_transcript: str
    """Full transcript translated and cleaned in the output language."""


class APIResponse(BaseModel):
    """Full API response: transcript plus analysis."""

    transcript: str
    analysis: AnalysisResult
