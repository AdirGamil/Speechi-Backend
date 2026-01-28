"""
Environment and secrets utilities.

Load and validate variables from .env. No hardcoded keys or defaults.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def get_openai_api_key() -> str | None:
    """Return OPENAI_API_KEY from environment."""
    return os.getenv("OPENAI_API_KEY")


def get_anthropic_api_key() -> str | None:
    """Return ANTHROPIC_API_KEY from environment."""
    return os.getenv("ANTHROPIC_API_KEY")
