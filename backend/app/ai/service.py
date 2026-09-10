"""Resilient meeting-analysis service."""

from __future__ import annotations

import logging
from typing import Any

from app.ai.fallback import analyze_with_fallback
from app.ai.ollama import analyze_with_ollama

logger = logging.getLogger(__name__)


async def analyze_meeting(
    transcript: str,
    participants: list[str] | None = None,
) -> dict[str, Any]:
    """Prefer Ollama; keep the core product available if it is offline.

    Args:
        participants: Names the bot saw in the meeting, used to resolve who
            each action item belongs to.
    """
    try:
        return await analyze_with_ollama(transcript, participants)
    except (RuntimeError, ValueError) as error:
        logger.warning("Ollama analysis unavailable; using offline fallback: %s", error)
        notes = analyze_with_fallback(transcript)
        notes["provider"] = "fallback"
        return notes
