#!/usr/bin/env python3
"""
CLI test: summarization only via Claude Sonnet.

Loads the system prompt, sends a hardcoded transcript, prints raw response
then parsed JSON. No audio, no OpenAI, no FastAPI. Fails loudly if JSON invalid.
"""

import json
from pathlib import Path

from anthropic import Anthropic

from app.models.schemas import AnalysisResult
from app.services.summarization_service import _extract_json
from app.utils.env_utils import get_anthropic_api_key

PROMPT_PATH = Path(__file__).resolve().parent / "app" / "prompts" / "meeting_summary_prompt.txt"
MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 4096
TARGET_LANGUAGE = "en"

# Hardcoded transcript for validation (no audio, no Whisper).
TRANSCRIPT = """Alice: Let's push the launch to March. We need more time for QA.
Bob: I'll update the timeline and notify clients.
Alice: Thanks. Carol, can you own the release notes?
Carol: Yes, I'll have a draft by Friday.
Bob: We also agreed to keep the current budget. No extra spend."""


def main() -> None:
    api_key = get_anthropic_api_key()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    system = PROMPT_PATH.read_text(encoding="utf-8").strip()
    user_content = f"Target output language: {TARGET_LANGUAGE}\n\nTranscript:\n\n{TRANSCRIPT}"

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = ""
    for block in response.content:
        raw += getattr(block, "text", "") or ""
    raw = raw.strip()

    if not raw:
        raise ValueError("Claude returned empty response")

    print("--- Raw Claude response ---")
    print(raw)
    print()

    cleaned = _extract_json(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude response is not valid JSON: {e}") from e

    AnalysisResult.model_validate(data)

    print("--- Parsed JSON (readable) ---")
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
