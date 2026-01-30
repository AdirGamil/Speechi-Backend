"""
Pydantic schemas and DTOs.

Request/response models for API, internal data shapes for
transcription, summarization, and document generation.
"""

from typing import Optional

from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    """A single action item from meeting analysis."""

    description: str
    owner: Optional[str] = None


class AnalysisResult(BaseModel):
    """
    Structured output of LLM-based meeting analysis.

    Includes summary, participants, decisions, action items, and transcripts.
    For long recordings, translated_transcript may be condensed while
    raw_transcript always contains the full original transcription.
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
    """Full or condensed transcript in the output language."""

    raw_transcript: str = ""
    """Original Whisper transcript (always full, never condensed)."""

    language: str = "en"
    """Output language code used for analysis."""

    is_condensed: bool = False
    """True if translated_transcript is condensed due to transcript length."""


class ChunkAnalysis(BaseModel):
    """
    Analysis result for a single transcript chunk (internal use).
    
    Used during map-reduce processing of long transcripts.
    """

    chunk_summary: str
    """Brief summary of this chunk's content."""

    participants: list[str] = Field(default_factory=list)
    """Participants mentioned in this chunk."""

    decisions: list[str] = Field(default_factory=list)
    """Decisions identified in this chunk."""

    action_items: list[ActionItem] = Field(default_factory=list)
    """Action items from this chunk."""

    key_topics: list[str] = Field(default_factory=list)
    """Key topics or themes in this chunk."""


class APIResponse(BaseModel):
    """Full API response: transcript plus analysis."""

    transcript: str
    """Raw Whisper transcript (kept for backward compatibility)."""

    analysis: AnalysisResult
    """Structured analysis including both transcripts."""
