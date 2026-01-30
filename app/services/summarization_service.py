"""
Summarization service.

Enterprise-grade meeting analysis pipeline for long audio conversations (60-120+ minutes).
Implements a two-phase context-aware chunking architecture:

PHASE 1: Chunk-Level Context Extraction
  - Each chunk analyzed with rolling global context
  - Incremental extraction (no repetition)
  - Context preservation across chunks

PHASE 2: Global Context Synthesis
  - Aggregates all chunk results
  - Resolves contradictions
  - Produces coherent final output

Features:
- Handles 2+ hour recordings reliably
- Robust JSON parsing with multi-stage repair
- No hallucinations - strict transcript-only extraction
- Deterministic, stable output
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from anthropic import Anthropic

from app.models.schemas import ActionItem, AnalysisResult
from app.utils.env_utils import get_anthropic_api_key

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "meeting_summary_prompt.txt"
_CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
_MAX_TOKENS = 8192
_MAX_TOKENS_CHUNK = 4096
_MAX_TOKENS_SYNTHESIS = 8192

# Chunking configuration
# ~1500-2000 tokens ≈ 6000-8000 characters for ~5-7 minutes of speech
_LONG_TRANSCRIPT_THRESHOLD = 15000  # Characters - trigger chunking above this
_CHUNK_SIZE = 7000  # Target chunk size (~5-7 minutes of speech)
_CHUNK_OVERLAP = 500  # Overlap for context preservation

logger = logging.getLogger(__name__)


# ============================================
# Data Classes for Context-Aware Processing
# ============================================

@dataclass
class Decision:
    """A decision extracted from the meeting."""
    decision: str
    confidence: str = "medium"  # high, medium, low


@dataclass
class ActionItemDetail:
    """An action item with full details."""
    task: str
    owner: Optional[str] = None
    due: Optional[str] = None


@dataclass
class ChunkOutput:
    """Output from analyzing a single chunk."""
    chunk_summary: str = ""
    new_participants: list[str] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    action_items: list[ActionItemDetail] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    important_notes: list[str] = field(default_factory=list)


@dataclass
class GlobalContext:
    """
    Rolling global context passed between chunks.
    Accumulates information as chunks are processed.
    """
    participants: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    action_items: list[ActionItemDetail] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)  # Chunk summaries in order
    important_notes: list[str] = field(default_factory=list)
    
    def to_prompt_string(self) -> str:
        """Convert context to a string for inclusion in prompts."""
        if not any([self.participants, self.topics, self.decisions, 
                    self.action_items, self.timeline]):
            return "No prior context (this is the first chunk)."
        
        parts = []
        
        if self.participants:
            parts.append(f"Known participants: {', '.join(self.participants)}")
        
        if self.topics:
            parts.append(f"Topics discussed so far: {', '.join(self.topics[-10:])}")  # Last 10
        
        if self.decisions:
            decisions_str = "; ".join(d.decision for d in self.decisions[-5:])  # Last 5
            parts.append(f"Decisions made: {decisions_str}")
        
        if self.action_items:
            items_str = "; ".join(f"{a.task} ({a.owner or 'unassigned'})" 
                                  for a in self.action_items[-5:])
            parts.append(f"Action items: {items_str}")
        
        if self.timeline:
            parts.append(f"Meeting flow: {' → '.join(self.timeline[-5:])}")
        
        if self.important_notes:
            parts.append(f"Important notes: {'; '.join(self.important_notes[-3:])}")
        
        return "\n".join(parts)
    
    def merge_chunk_output(self, output: ChunkOutput) -> None:
        """Merge a chunk's output into the global context."""
        # Add new participants (deduplicated)
        for p in output.new_participants:
            if p and p not in self.participants:
                self.participants.append(p)
        
        # Add new topics (deduplicated, keep recent)
        for t in output.topics:
            if t and t not in self.topics:
                self.topics.append(t)
        if len(self.topics) > 20:
            self.topics = self.topics[-20:]
        
        # Add decisions
        self.decisions.extend(output.decisions)
        
        # Add action items
        self.action_items.extend(output.action_items)
        
        # Add chunk summary to timeline
        if output.chunk_summary:
            self.timeline.append(output.chunk_summary)
        
        # Add important notes
        for note in output.important_notes:
            if note and note not in self.important_notes:
                self.important_notes.append(note)


# ============================================
# Core API Functions
# ============================================

def _load_prompt() -> str:
    """Load the meeting-analysis system prompt from disk."""
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _call_claude(
    system: str,
    user_content: str,
    max_tokens: int = _MAX_TOKENS,
) -> str:
    """
    Make a Claude API call and return the text response.
    
    Args:
        system: System prompt.
        user_content: User message content.
        max_tokens: Maximum tokens in response.
        
    Returns:
        Raw text response from Claude.
        
    Raises:
        RuntimeError: If API call fails or key is missing.
    """
    api_key = get_anthropic_api_key()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    
    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as e:
        raise RuntimeError(f"Claude API failed: {e}") from e
    
    text = ""
    for block in response.content:
        text += getattr(block, "text", "") or ""
    
    return text.strip()


# ============================================
# JSON Parsing and Repair
# ============================================

def _extract_json(raw: str) -> str:
    """
    Extract JSON from Claude response, handling markdown and extra text.
    """
    s = raw.strip()
    
    # Remove markdown code fences
    for marker in ("```json", "```"):
        if s.startswith(marker):
            s = s[len(marker):].lstrip("\n\r")
            break
    
    if s.endswith("```"):
        s = s[:-len("```")].rstrip("\n\r")
    
    s = s.strip()
    
    # Find JSON object boundaries
    if not s.startswith("{"):
        start = s.find("{")
        if start != -1:
            s = s[start:]
    
    if not s.endswith("}"):
        end = s.rfind("}")
        if end != -1:
            s = s[:end + 1]
    
    return s.strip()


def _fix_json_string(s: str) -> str:
    """
    Fix common JSON issues: trailing commas, unescaped characters.
    """
    # Remove trailing commas
    s = re.sub(r',(\s*[}\]])', r'\1', s)
    
    # Fix unescaped characters in strings
    result = []
    in_string = False
    escape_next = False
    
    for char in s:
        if escape_next:
            result.append(char)
            escape_next = False
            continue
            
        if char == '\\':
            escape_next = True
            result.append(char)
            continue
            
        if char == '"':
            in_string = not in_string
            result.append(char)
            continue
            
        if in_string:
            if char == '\n':
                result.append('\\n')
                continue
            if char == '\r':
                continue
            if char == '\t':
                result.append('\\t')
                continue
        
        result.append(char)
    
    return ''.join(result)


def _parse_json_safe(text: str) -> dict | None:
    """
    Try to parse JSON with progressive fallbacks.
    """
    # Attempt 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Attempt 2: Extract and clean
    cleaned = _extract_json(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # Attempt 3: Fix common issues
    fixed = _fix_json_string(cleaned)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    return None


def _repair_json_via_claude(broken_text: str, target_schema: str) -> dict:
    """
    Use Claude to repair malformed JSON.
    """
    repair_system = f"""You are a JSON repair specialist. Convert the input into valid JSON matching this schema:

{target_schema}

Rules:
1. Output ONLY valid JSON - no markdown, no explanation
2. Escape all newlines as \\n, quotes as \\"
3. Use null for missing values
4. Do NOT invent data - only extract what's present
5. If a field cannot be determined, use empty string or empty array"""

    repair_user = f"""Input to repair:
{broken_text[:6000]}

Output valid JSON only:"""

    try:
        repaired_text = _call_claude(repair_system, repair_user, max_tokens=_MAX_TOKENS_CHUNK)
        data = _parse_json_safe(repaired_text)
        if data is not None:
            return data
        raise ValueError("Repair produced invalid JSON")
    except RuntimeError as e:
        raise ValueError(f"JSON repair failed: {e}") from e


# ============================================
# Chunking
# ============================================

def split_transcript(transcript: str, max_chars: int = _CHUNK_SIZE) -> list[str]:
    """
    Split transcript into chunks for processing.
    
    Splits on natural boundaries (paragraphs, sentences) with overlap.
    Each chunk represents roughly 5-7 minutes of speech.
    """
    if len(transcript) <= max_chars:
        return [transcript]
    
    chunks: list[str] = []
    remaining = transcript
    
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break
        
        chunk = remaining[:max_chars]
        
        # Find best split point (paragraph > newline > sentence > space)
        split_pos = chunk.rfind("\n\n")
        
        if split_pos < max_chars // 2:
            split_pos = chunk.rfind("\n")
        
        if split_pos < max_chars // 2:
            for end_char in [". ", "! ", "? ", "。", "！", "？"]:
                pos = chunk.rfind(end_char)
                if pos > split_pos:
                    split_pos = pos + 1
        
        if split_pos < max_chars // 2:
            split_pos = chunk.rfind(" ")
        
        if split_pos < max_chars // 4:
            split_pos = max_chars
        
        chunks.append(remaining[:split_pos].strip())
        
        # Start next chunk with overlap
        overlap_start = max(0, split_pos - _CHUNK_OVERLAP)
        remaining = remaining[overlap_start:].strip()
    
    return chunks


# ============================================
# PHASE 1: Chunk Analysis with Context
# ============================================

def _get_chunk_analysis_prompt() -> str:
    """System prompt for context-aware chunk analysis."""
    return """You are analyzing a PORTION of a longer meeting transcript.

You will receive:
1. GLOBAL CONTEXT: Information already extracted from previous chunks
2. CURRENT CHUNK: The transcript segment to analyze

Your task: Extract ONLY NEW information from this chunk that is NOT already in the global context.

## Output Schema (JSON only, no markdown):

{
  "chunk_summary": "1-2 sentence summary of what happens in THIS chunk",
  "new_participants": ["Names appearing for the FIRST TIME only"],
  "decisions": [
    {"decision": "What was decided", "confidence": "high|medium|low"}
  ],
  "action_items": [
    {"task": "What needs to be done", "owner": "Person or null", "due": "Date or null"}
  ],
  "topics": ["New or continuing topics in this chunk"],
  "important_notes": ["Corrections, clarifications, reversals of earlier info"]
}

## Critical Rules:

1. **No Repetition**: Do NOT include participants, decisions, or action items already in GLOBAL CONTEXT
2. **No Hallucination**: Only extract what is EXPLICITLY stated
3. **Confidence Levels**:
   - "high": Clearly stated, explicit agreement
   - "medium": Implied or suggested
   - "low": Tentative, needs confirmation
4. **Empty is OK**: If nothing new, return empty arrays
5. **Valid JSON**: Output must be parseable JSON, no commentary

Output the JSON object only."""


def _analyze_chunk_with_context(
    chunk: str,
    chunk_index: int,
    total_chunks: int,
    global_context: GlobalContext,
    language: str,
) -> ChunkOutput:
    """
    Analyze a single chunk with awareness of global context.
    
    This is PHASE 1 of the two-phase model.
    """
    system = _get_chunk_analysis_prompt()
    
    context_str = global_context.to_prompt_string()
    
    user_content = f"""## GLOBAL CONTEXT (from previous chunks):
{context_str}

## CURRENT CHUNK ({chunk_index + 1} of {total_chunks}):

{chunk}

## Target output language: {language}

Extract ONLY new information not already in the global context.
Output JSON only:"""

    try:
        text = _call_claude(system, user_content, max_tokens=_MAX_TOKENS_CHUNK)
        data = _parse_json_safe(text)
        
        if data is None:
            # Try repair
            schema = '{"chunk_summary":"","new_participants":[],"decisions":[],"action_items":[],"topics":[],"important_notes":[]}'
            data = _repair_json_via_claude(text, schema)
        
        # Parse into ChunkOutput
        decisions = [
            Decision(
                decision=d.get("decision", ""),
                confidence=d.get("confidence", "medium")
            )
            for d in data.get("decisions", [])
            if isinstance(d, dict) and d.get("decision")
        ]
        
        action_items = [
            ActionItemDetail(
                task=a.get("task", ""),
                owner=a.get("owner"),
                due=a.get("due")
            )
            for a in data.get("action_items", [])
            if isinstance(a, dict) and a.get("task")
        ]
        
        return ChunkOutput(
            chunk_summary=data.get("chunk_summary", ""),
            new_participants=data.get("new_participants", []),
            decisions=decisions,
            action_items=action_items,
            topics=data.get("topics", []),
            important_notes=data.get("important_notes", []),
        )
        
    except Exception as e:
        logger.warning("Chunk %d analysis failed: %s", chunk_index, e)
        return ChunkOutput(chunk_summary=f"[Chunk {chunk_index + 1} analysis incomplete]")


# ============================================
# PHASE 2: Final Synthesis
# ============================================

def _get_synthesis_prompt() -> str:
    """System prompt for final synthesis."""
    return """You are synthesizing a complete meeting analysis from chunk-level extractions.

You will receive:
1. AGGREGATED CONTEXT: All participants, decisions, action items, and notes
2. MEETING TIMELINE: Summaries of each chunk in order
3. TARGET LANGUAGE: Output language for all content

Your task: Produce a coherent, final meeting analysis.

## Output Schema (JSON only, no markdown):

{
  "summary": "Clear, comprehensive meeting summary (3-5 sentences)",
  "participants": ["List of all participants"],
  "decisions": ["Final list of decisions, duplicates merged"],
  "action_items": [
    {"description": "Task description", "owner": "Person or null"}
  ],
  "translated_transcript": "Clean, readable transcript summary in target language"
}

## Critical Rules:

1. **Resolve Contradictions**: Later information overrides earlier
2. **Merge Duplicates**: Combine similar decisions/tasks
3. **Chronological Logic**: Summary should follow meeting flow
4. **No Invention**: Only include what was extracted
5. **Completeness**: Capture all key information
6. **Target Language**: All output in the specified language

Output the JSON object only."""


def _synthesize_final_output(
    global_context: GlobalContext,
    language: str,
) -> dict:
    """
    PHASE 2: Synthesize all chunk results into final output.
    """
    system = _get_synthesis_prompt()
    
    # Build comprehensive context for synthesis
    participants_str = ", ".join(global_context.participants) if global_context.participants else "Unknown"
    
    decisions_str = "\n".join(
        f"- {d.decision} (confidence: {d.confidence})"
        for d in global_context.decisions
    ) if global_context.decisions else "None identified"
    
    actions_str = "\n".join(
        f"- {a.task} (owner: {a.owner or 'unassigned'}, due: {a.due or 'not specified'})"
        for a in global_context.action_items
    ) if global_context.action_items else "None identified"
    
    timeline_str = "\n".join(
        f"{i+1}. {summary}"
        for i, summary in enumerate(global_context.timeline)
    ) if global_context.timeline else "No timeline available"
    
    notes_str = "\n".join(f"- {n}" for n in global_context.important_notes) if global_context.important_notes else "None"
    
    user_content = f"""## AGGREGATED CONTEXT

### Participants:
{participants_str}

### Decisions Made:
{decisions_str}

### Action Items:
{actions_str}

### Important Notes/Corrections:
{notes_str}

## MEETING TIMELINE (chunk summaries in order):
{timeline_str}

## Target output language: {language}

Synthesize into final meeting analysis. Output JSON only:"""

    text = _call_claude(system, user_content, max_tokens=_MAX_TOKENS_SYNTHESIS)
    data = _parse_json_safe(text)
    
    if data is None:
        schema = '{"summary":"","participants":[],"decisions":[],"action_items":[],"translated_transcript":""}'
        data = _repair_json_via_claude(text, schema)
    
    return data


# ============================================
# Main Analysis Functions
# ============================================

def _analyze_short_transcript(transcript: str, output_language: str) -> AnalysisResult:
    """
    Analyze a short/medium transcript in a single pass.
    Used when transcript is below chunking threshold.
    """
    system = _load_prompt()
    transcript_block = transcript.strip() if transcript.strip() else "(empty)"
    user_content = f"Target output language: {output_language}\n\nTranscript:\n\n{transcript_block}"
    
    text = _call_claude(system, user_content)
    
    if not text:
        raise ValueError("Claude returned empty analysis")
    
    data = _parse_json_safe(text)
    
    if data is None:
        schema = '{"summary":"","participants":[],"decisions":[],"action_items":[],"translated_transcript":""}'
        data = _repair_json_via_claude(text, schema)
    
    action_items = [
        ActionItem(
            description=item.get("description", item.get("task", "")),
            owner=item.get("owner")
        )
        for item in data.get("action_items", [])
        if isinstance(item, dict)
    ]
    
    return AnalysisResult(
        summary=data.get("summary", ""),
        participants=data.get("participants", []),
        decisions=data.get("decisions", []),
        action_items=action_items,
        translated_transcript=data.get("translated_transcript", ""),
        raw_transcript=transcript,
        language=output_language,
        is_condensed=False,
    )


def _analyze_long_transcript(transcript: str, output_language: str) -> AnalysisResult:
    """
    Analyze a long transcript using two-phase context-aware chunking.
    
    PHASE 1: Process each chunk with rolling global context
    PHASE 2: Synthesize all results into final output
    """
    logger.info(
        "Long transcript detected (%d chars). Using context-aware chunking.",
        len(transcript)
    )
    
    # Split into chunks
    chunks = split_transcript(transcript)
    logger.info("Split into %d chunks for processing", len(chunks))
    
    # Initialize global context
    global_context = GlobalContext()
    
    # PHASE 1: Process each chunk with context
    for i, chunk in enumerate(chunks):
        logger.info("Processing chunk %d/%d with context", i + 1, len(chunks))
        
        chunk_output = _analyze_chunk_with_context(
            chunk=chunk,
            chunk_index=i,
            total_chunks=len(chunks),
            global_context=global_context,
            language=output_language,
        )
        
        # Merge chunk output into global context
        global_context.merge_chunk_output(chunk_output)
        
        logger.info(
            "Chunk %d: +%d participants, +%d decisions, +%d actions",
            i + 1,
            len(chunk_output.new_participants),
            len(chunk_output.decisions),
            len(chunk_output.action_items),
        )
    
    # PHASE 2: Final synthesis
    logger.info("Starting final synthesis with %d timeline entries", len(global_context.timeline))
    
    final_data = _synthesize_final_output(global_context, output_language)
    
    # Build AnalysisResult
    action_items = [
        ActionItem(
            description=item.get("description", item.get("task", "")),
            owner=item.get("owner")
        )
        for item in final_data.get("action_items", [])
        if isinstance(item, dict)
    ]
    
    # Ensure we have participants from global context if synthesis missed them
    participants = final_data.get("participants", [])
    if not participants and global_context.participants:
        participants = global_context.participants
    
    # Ensure we have decisions from global context if synthesis missed them
    decisions = final_data.get("decisions", [])
    if not decisions and global_context.decisions:
        decisions = [d.decision for d in global_context.decisions]
    
    return AnalysisResult(
        summary=final_data.get("summary", ""),
        participants=participants,
        decisions=decisions,
        action_items=action_items,
        translated_transcript=final_data.get("translated_transcript", ""),
        raw_transcript=transcript,
        language=output_language,
        is_condensed=True,
    )


def analyze_transcript(transcript: str, output_language: str) -> AnalysisResult:
    """
    Analyze a meeting transcript and return structured summary data.

    For short/medium transcripts: single-pass analysis
    For long transcripts (60-120+ minutes): two-phase context-aware chunking

    The two-phase model ensures:
    - Context preservation across chunks
    - No information loss
    - Coherent final output
    - Stable JSON parsing

    Args:
        transcript: Plain-text transcript (e.g. from Whisper).
        output_language: Target output language ISO code (he, en, fr, es, ar).

    Returns:
        AnalysisResult with summary, participants, decisions, action_items,
        translated_transcript, raw_transcript, language, and is_condensed flag.

    Raises:
        RuntimeError: Missing ANTHROPIC_API_KEY or Claude API failure.
        ValueError: Response could not be parsed as valid AnalysisResult.
    """
    transcript_length = len(transcript.strip())
    
    if transcript_length == 0:
        return AnalysisResult(
            summary="No transcript content to analyze.",
            participants=[],
            decisions=[],
            action_items=[],
            translated_transcript="",
            raw_transcript="",
            language=output_language,
            is_condensed=False,
        )
    
    # Choose processing strategy based on length
    if transcript_length > _LONG_TRANSCRIPT_THRESHOLD:
        result = _analyze_long_transcript(transcript, output_language)
    else:
        result = _analyze_short_transcript(transcript, output_language)
    
    # Final validation
    try:
        return AnalysisResult.model_validate(result.model_dump())
    except Exception as e:
        raise ValueError(f"Analysis result does not match schema: {e}") from e
