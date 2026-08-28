"""Offline, deterministic meeting-notes fallback.

This is deliberately conservative: it never invents decisions, people, or dates.
It keeps the upload-to-notes flow useful when a local LLM is unavailable.
"""

import re
from typing import Any

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")
_WHITESPACE = re.compile(r"\s+")
_DECISION_MARKER = re.compile(
    r"\b(decided|agreed|approved|confirmed|will proceed|let'?s go with)\b",
    re.IGNORECASE,
)
_ACTION_PATTERN = re.compile(
    r"\b(?P<assignee>[A-Z][a-z]{1,30})\s+"
    r"(?:will|shall|needs? to|is going to)\s+(?P<task>[^.!?]+?)(?:\s+by\s+(?P<deadline>[^.!?]+))?[.!?]?$",
    re.IGNORECASE,
)


def _sentences(transcript: str) -> list[str]:
    cleaned = _WHITESPACE.sub(" ", transcript).strip()
    return [sentence.strip(" -•\t") for sentence in _SENTENCE_BOUNDARY.split(cleaned) if sentence.strip()]


def analyze_with_fallback(transcript: str) -> dict[str, Any]:
    """Return safe structured notes without calling an external service."""
    sentences = _sentences(transcript)
    summary = " ".join(sentences[:3]) if sentences else "No transcript content was provided."

    decisions: list[str] = []
    action_items: list[dict[str, str | None]] = []
    for sentence in sentences:
        if _DECISION_MARKER.search(sentence) and sentence not in decisions:
            decisions.append(sentence)

        match = _ACTION_PATTERN.search(sentence)
        if match:
            task = match.group("task").strip(" ,")
            deadline = match.group("deadline")
            action_items.append(
                {
                    "assignee": match.group("assignee").title(),
                    "task": task,
                    "deadline": deadline.strip() if deadline else None,
                }
            )

    return {
        "summary": summary,
        "decisions": decisions,
        "action_items": action_items,
    }
