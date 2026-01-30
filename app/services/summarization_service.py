"""
Summarization service.

Orchestrates LLM-based analysis and meeting summarization (e.g. Claude).
Consumes transcription output and produces structured summary data.

Features:
- Robust JSON parsing with automatic repair fallback
- Chunking for long transcripts (up to 2+ hours of audio)
- Map-reduce summarization for large meetings
- Retry logic with progressive fallbacks
"""

import json
import logging
import re
from pathlib import Path
from typing import Callable

from anthropic import Anthropic

from app.models.schemas import ActionItem, AnalysisResult, ChunkAnalysis
from app.utils.env_utils import get_anthropic_api_key

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "meeting_summary_prompt.txt"
_CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
_MAX_TOKENS = 8192  # Increased for long transcripts
_MAX_TOKENS_CHUNK = 4096  # For chunk analysis

# Chunking thresholds
_LONG_TRANSCRIPT_THRESHOLD = 20000  # Characters - trigger chunking above this
_CHUNK_SIZE = 12000  # Target chunk size in characters
_CHUNK_OVERLAP = 400  # Overlap between chunks for context preservation

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    """Load the meeting-analysis system prompt from disk."""
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _extract_json(raw: str) -> str:
    """
    Extract JSON from Claude response, removing markdown code fences if present.

    Handles cases where Claude wraps JSON in ```json ... ``` despite prompt instructions.
    Also handles common JSON issues like trailing commas.

    Args:
        raw: Raw Claude response text.

    Returns:
        Cleaned string ready for json.loads.
    """
    s = raw.strip()
    
    # Remove leading code fence markers (```json or ```)
    for marker in ("```json", "```"):
        if s.startswith(marker):
            s = s[len(marker):].lstrip("\n\r")
            break
    
    # Remove trailing ```
    if s.endswith("```"):
        s = s[:-len("```")].rstrip("\n\r")
    
    s = s.strip()
    
    # Try to find JSON object boundaries if there's extra text
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
    Attempt to fix common JSON issues.
    
    - Remove trailing commas before } or ]
    - Fix unescaped newlines in strings
    - Fix unescaped quotes in strings
    """
    # Remove trailing commas (,} or ,])
    s = re.sub(r',(\s*[}\]])', r'\1', s)
    
    # This is tricky - we need to fix newlines inside strings
    # We'll do a simple approach: replace literal newlines with \n
    # But only inside strings (between quotes)
    
    result = []
    in_string = False
    escape_next = False
    i = 0
    
    while i < len(s):
        char = s[i]
        
        if escape_next:
            result.append(char)
            escape_next = False
            i += 1
            continue
            
        if char == '\\':
            escape_next = True
            result.append(char)
            i += 1
            continue
            
        if char == '"':
            in_string = not in_string
            result.append(char)
            i += 1
            continue
            
        if in_string and char == '\n':
            result.append('\\n')
            i += 1
            continue
            
        if in_string and char == '\r':
            i += 1
            continue
            
        if in_string and char == '\t':
            result.append('\\t')
            i += 1
            continue
            
        result.append(char)
        i += 1
    
    return ''.join(result)


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


def _parse_json_safe(text: str) -> dict | None:
    """
    Try to parse JSON with progressive fallbacks.
    
    Returns:
        Parsed dict or None if all attempts fail.
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


def _repair_json_via_claude(broken_text: str, language: str) -> dict:
    """
    Use Claude to repair broken JSON.
    
    Args:
        broken_text: The malformed JSON/text to repair.
        language: Target output language.
        
    Returns:
        Parsed dict from repaired JSON.
        
    Raises:
        ValueError: If repair fails.
    """
    repair_system = """You are a JSON repair specialist. Your ONLY task is to convert the input into valid JSON.

Rules:
1. Output ONLY valid JSON - no markdown, no explanation, no code fences.
2. The JSON must have these exact keys: summary, participants, decisions, action_items, translated_transcript
3. participants, decisions must be arrays of strings
4. action_items must be an array of objects with "description" (string) and "owner" (string or null)
5. All string values must have properly escaped newlines (\\n) and quotes (\\")
6. Do NOT invent or add content. Extract from the input what you can.
7. If a field cannot be determined, use empty string or empty array.
8. Keep the content in the target language specified.

Output the repaired JSON only."""

    repair_user = f"""Target language: {language}

Input to repair:
{broken_text[:8000]}

Output valid JSON only:"""

    try:
        repaired_text = _call_claude(repair_system, repair_user, max_tokens=_MAX_TOKENS)
        
        data = _parse_json_safe(repaired_text)
        if data is not None:
            return data
        
        raise ValueError("Repair produced invalid JSON")
        
    except RuntimeError as e:
        raise ValueError(f"JSON repair failed: {e}") from e


def _parse_analysis_json(text: str, language: str) -> dict:
    """
    Parse Claude's analysis response with retry logic.
    
    Args:
        text: Raw Claude response.
        language: Target language for repair prompt.
        
    Returns:
        Parsed dict.
        
    Raises:
        ValueError: If parsing fails after all retries.
    """
    # First try direct parsing
    data = _parse_json_safe(text)
    if data is not None:
        return data
    
    # Log the failure for debugging (truncated)
    logger.warning(
        "Initial JSON parse failed, attempting repair. First 500 chars: %s",
        text[:500]
    )
    
    # Try Claude repair
    try:
        return _repair_json_via_claude(text, language)
    except ValueError:
        pass
    
    # Final fallback: raise with context
    raise ValueError(
        f"Claude response is not valid JSON after repair attempt. "
        f"Response starts with: {text[:200]}..."
    )


def split_transcript(transcript: str, max_chars: int = _CHUNK_SIZE) -> list[str]:
    """
    Split a transcript into chunks for processing.
    
    Splits on paragraph boundaries where possible, with overlap for context.
    Never splits in the middle of a word.
    
    Args:
        transcript: Full transcript text.
        max_chars: Maximum characters per chunk.
        
    Returns:
        List of transcript chunks.
    """
    if len(transcript) <= max_chars:
        return [transcript]
    
    chunks: list[str] = []
    remaining = transcript
    
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break
        
        # Find a good split point
        chunk = remaining[:max_chars]
        
        # Try to split on paragraph boundary (double newline)
        split_pos = chunk.rfind("\n\n")
        
        # Fall back to single newline
        if split_pos < max_chars // 2:
            split_pos = chunk.rfind("\n")
        
        # Fall back to sentence end
        if split_pos < max_chars // 2:
            for end_char in [". ", "! ", "? ", "。", "！", "？"]:
                pos = chunk.rfind(end_char)
                if pos > split_pos:
                    split_pos = pos + 1  # Include the punctuation
        
        # Fall back to space (word boundary)
        if split_pos < max_chars // 2:
            split_pos = chunk.rfind(" ")
        
        # Worst case: just split at max_chars
        if split_pos < max_chars // 4:
            split_pos = max_chars
        
        chunks.append(remaining[:split_pos].strip())
        
        # Start next chunk with overlap for context
        overlap_start = max(0, split_pos - _CHUNK_OVERLAP)
        remaining = remaining[overlap_start:].strip()
    
    return chunks


def _get_chunk_prompt() -> str:
    """Get the system prompt for chunk analysis."""
    return """You are a meeting analyst processing a PORTION of a longer transcript.

Analyze this transcript chunk and output a JSON object with:
- chunk_summary: Brief summary (2-3 sentences) of what happens in THIS chunk
- participants: Names mentioned in THIS chunk (array of strings)
- decisions: Any decisions made in THIS chunk (array of strings)
- action_items: Tasks assigned in THIS chunk (array of objects with "description" and "owner")
- key_topics: Main topics discussed in THIS chunk (array of strings, max 5)

Rules:
1. Only extract what is explicitly in THIS chunk
2. Output valid JSON only - no markdown, no code fences
3. Use the target language for all content
4. If nothing found for a field, use empty array
5. Keep summaries brief - this is one chunk of many
6. Escape all newlines as \\n in string values

Example output:
{"chunk_summary":"Team reviewed Q1 progress.","participants":["Alice","Bob"],"decisions":["Approved budget increase."],"action_items":[{"description":"Draft proposal","owner":"Alice"}],"key_topics":["Q1 review","budget"]}"""


def _analyze_chunk(chunk: str, chunk_index: int, total_chunks: int, language: str) -> ChunkAnalysis:
    """
    Analyze a single transcript chunk.
    
    Args:
        chunk: Transcript chunk text.
        chunk_index: Index of this chunk (0-based).
        total_chunks: Total number of chunks.
        language: Target output language.
        
    Returns:
        ChunkAnalysis with extracted information.
    """
    system = _get_chunk_prompt()
    user_content = f"""Target language: {language}
Chunk {chunk_index + 1} of {total_chunks}

Transcript chunk:

{chunk}

Output JSON only:"""

    try:
        text = _call_claude(system, user_content, max_tokens=_MAX_TOKENS_CHUNK)
        data = _parse_analysis_json(text, language)
        
        # Normalize the data to ChunkAnalysis
        return ChunkAnalysis(
            chunk_summary=data.get("chunk_summary", ""),
            participants=data.get("participants", []),
            decisions=data.get("decisions", []),
            action_items=[
                ActionItem(
                    description=item.get("description", ""),
                    owner=item.get("owner")
                )
                for item in data.get("action_items", [])
                if isinstance(item, dict)
            ],
            key_topics=data.get("key_topics", []),
        )
    except Exception as e:
        logger.warning("Chunk %d analysis failed: %s", chunk_index, e)
        # Return empty analysis rather than failing entirely
        return ChunkAnalysis(chunk_summary=f"[Chunk {chunk_index + 1} analysis failed]")


def _get_merge_prompt() -> str:
    """Get the system prompt for merging chunk analyses."""
    return """You are a meeting analyst merging multiple chunk analyses into a final summary.

You will receive:
1. Individual chunk summaries and extracted data
2. The target output language

Your task:
1. Synthesize a cohesive overall summary from the chunk summaries
2. Deduplicate participants (same person mentioned in multiple chunks)
3. Merge and deduplicate decisions
4. Merge and deduplicate action items (combine similar tasks)
5. Create a clean, condensed transcript summary (not full transcript)

Output a JSON object with:
- summary: Comprehensive meeting summary (target language)
- participants: Deduplicated list of all participants
- decisions: Deduplicated list of all decisions
- action_items: Merged list of action items (deduplicated by semantic similarity)
- translated_transcript: A condensed, clean version of the meeting flow (not full transcript, but captures key points and exchanges)

Rules:
1. Output valid JSON only - no markdown, no code fences
2. All content in target language
3. Do not invent content - only synthesize from provided chunks
4. For translated_transcript: create a coherent narrative summary of the meeting flow, not a literal transcript
5. Keep the summary comprehensive but concise
6. Escape all newlines as \\n in strings

Example format:
{"summary":"...","participants":["Alice","Bob"],"decisions":["..."],"action_items":[{"description":"...","owner":"Alice"}],"translated_transcript":"Meeting began with...\n\nKey discussion points...\n\nConclusion..."}"""


def _merge_chunk_analyses(
    chunks: list[ChunkAnalysis],
    language: str,
) -> dict:
    """
    Merge multiple chunk analyses into a final result.
    
    Args:
        chunks: List of ChunkAnalysis from individual chunks.
        language: Target output language.
        
    Returns:
        Dict with merged analysis data.
    """
    # Build input for merge prompt
    chunk_data = []
    for i, chunk in enumerate(chunks):
        chunk_data.append(f"""
Chunk {i + 1}:
- Summary: {chunk.chunk_summary}
- Participants: {', '.join(chunk.participants) if chunk.participants else 'None identified'}
- Decisions: {'; '.join(chunk.decisions) if chunk.decisions else 'None'}
- Action items: {'; '.join(f'{a.description} (owner: {a.owner or "unassigned"})' for a in chunk.action_items) if chunk.action_items else 'None'}
- Topics: {', '.join(chunk.key_topics) if chunk.key_topics else 'General discussion'}
""")
    
    system = _get_merge_prompt()
    user_content = f"""Target language: {language}

Number of chunks analyzed: {len(chunks)}

{chr(10).join(chunk_data)}

Synthesize into final JSON:"""

    text = _call_claude(system, user_content, max_tokens=_MAX_TOKENS)
    return _parse_analysis_json(text, language)


def _analyze_short_transcript(transcript: str, output_language: str) -> AnalysisResult:
    """
    Analyze a short/medium transcript in a single pass.
    
    Args:
        transcript: Full transcript text.
        output_language: Target output language.
        
    Returns:
        AnalysisResult with full analysis.
    """
    system = _load_prompt()
    transcript_block = transcript.strip() if transcript.strip() else "(empty)"
    user_content = f"Target output language: {output_language}\n\nTranscript:\n\n{transcript_block}"
    
    text = _call_claude(system, user_content)
    
    if not text:
        raise ValueError("Claude returned empty analysis")
    
    data = _parse_analysis_json(text, output_language)
    
    # Build AnalysisResult with new fields
    action_items = [
        ActionItem(
            description=item.get("description", ""),
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
    Analyze a long transcript using chunking and map-reduce.
    
    Args:
        transcript: Full transcript text.
        output_language: Target output language.
        
    Returns:
        AnalysisResult with analysis and condensed transcript.
    """
    logger.info(
        "Long transcript detected (%d chars). Using chunked analysis.",
        len(transcript)
    )
    
    # Split into chunks
    chunks = split_transcript(transcript)
    logger.info("Split into %d chunks", len(chunks))
    
    # Analyze each chunk
    chunk_analyses: list[ChunkAnalysis] = []
    for i, chunk in enumerate(chunks):
        logger.info("Analyzing chunk %d/%d", i + 1, len(chunks))
        analysis = _analyze_chunk(chunk, i, len(chunks), output_language)
        chunk_analyses.append(analysis)
    
    # Merge results
    logger.info("Merging %d chunk analyses", len(chunk_analyses))
    merged = _merge_chunk_analyses(chunk_analyses, output_language)
    
    # Build final result
    action_items = [
        ActionItem(
            description=item.get("description", ""),
            owner=item.get("owner")
        )
        for item in merged.get("action_items", [])
        if isinstance(item, dict)
    ]
    
    return AnalysisResult(
        summary=merged.get("summary", ""),
        participants=merged.get("participants", []),
        decisions=merged.get("decisions", []),
        action_items=action_items,
        translated_transcript=merged.get("translated_transcript", ""),
        raw_transcript=transcript,
        language=output_language,
        is_condensed=True,  # Mark as condensed for long transcripts
    )


def analyze_transcript(transcript: str, output_language: str) -> AnalysisResult:
    """
    Analyze a meeting transcript and return structured summary data.

    Uses Claude with the meeting-summary system prompt. For short/medium
    transcripts, processes in a single pass. For long transcripts (2+ hours),
    uses chunking and map-reduce for reliable processing.

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
        # Handle empty transcript
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
