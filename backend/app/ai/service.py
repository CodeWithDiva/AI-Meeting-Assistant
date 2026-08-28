"""Resilient meeting-analysis service."""

import logging
from typing import Any

from app.ai.fallback import analyze_with_fallback
from app.ai.ollama import analyze_with_ollama

logger = logging.getLogger(__name__)


async def analyze_meeting(transcript: str) -> dict[str, Any]:
    """Prefer Ollama; keep the core product available if it is offline."""
    try:
        return await analyze_with_ollama(transcript)
    except (RuntimeError, ValueError) as error:
        logger.warning("Ollama analysis unavailable; using offline fallback: %s", error)
        return analyze_with_fallback(transcript)
