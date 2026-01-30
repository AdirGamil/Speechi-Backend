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


class DecisionWithConfidence(BaseModel):
    """A decision with confidence level for context-aware processing."""
    
    decision: str
    """What was decided."""
    
    confidence: str = "medium"
    """Confidence level: high, medium, or low."""


class ActionItemWithDetails(BaseModel):
    """An action item with full details for context-aware processing."""
    
    task: str
    """What needs to be done."""
    
    owner: Optional[str] = None
    """Person responsible."""
    
    due: Optional[str] = None
    """Due date if specified."""


class ChunkAnalysis(BaseModel):
    """
    Analysis result for a single transcript chunk (internal use).
    
    Used during two-phase context-aware processing of long transcripts.
    Contains only INCREMENTAL information not already in global context.
    """

    chunk_summary: str = ""
    """1-2 sentence summary of this chunk's content."""

    new_participants: list[str] = Field(default_factory=list)
    """Participants appearing for the FIRST TIME in this chunk."""

    decisions: list[DecisionWithConfidence] = Field(default_factory=list)
    """New decisions identified in this chunk with confidence."""

    action_items: list[ActionItemWithDetails] = Field(default_factory=list)
    """New action items from this chunk."""

    topics: list[str] = Field(default_factory=list)
    """Topics discussed in this chunk."""
    
    important_notes: list[str] = Field(default_factory=list)
    """Corrections, clarifications, or reversals of earlier info."""


class APIResponse(BaseModel):
    """Full API response: transcript plus analysis."""

    transcript: str
    """Raw Whisper transcript (kept for backward compatibility)."""

    analysis: AnalysisResult
    """Structured analysis including both transcripts."""
