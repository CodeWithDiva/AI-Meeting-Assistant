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
        notes = await analyze_with_ollama(transcript, participants)
        _backfill_from_markers(notes, transcript, participants)
        return notes
    except (RuntimeError, ValueError) as error:
        logger.warning("Ollama analysis unavailable; using offline fallback: %s", error)
        notes = analyze_with_fallback(transcript, participants)
        notes["provider"] = "fallback"
        return notes


def _backfill_from_markers(notes: dict[str, Any], transcript: str, participants: list[str] | None) -> None:
    """Fill a section the model left empty from explicit spoken markers.

    A small model sometimes returns no decisions for a meeting where someone
    plainly said "we decided…" / "faisla kiya…" / "ہم نے فیصلہ کیا…" (measured on
    an Urdu-script meeting). The offline extractor only lifts sentences that
    contain such a marker, so it cannot invent anything — safe to lean on for
    exactly the case where the model produced nothing at all.
    """
    if notes.get("decisions") and notes.get("action_items"):
        return
    marker_notes = analyze_with_fallback(transcript, participants)
    if not notes.get("decisions") and marker_notes["decisions"]:
        notes["decisions"] = marker_notes["decisions"]
    if not notes.get("action_items") and marker_notes["action_items"]:
        notes["action_items"] = marker_notes["action_items"]
