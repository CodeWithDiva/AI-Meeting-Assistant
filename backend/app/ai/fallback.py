"""Offline, deterministic meeting-notes fallback.

This runs when Ollama is unreachable. It is deliberately conservative: it never
invents decisions, people, or dates — it only lifts sentences that already
contain an explicit decision or assignment marker.

Markers cover English, Urdu script, and Roman Urdu, because a Pakistani office
meeting mixes all three in a single sentence ("Ali, ye report Friday tak bhej
dena"). Transcript lines produced by the live bot are speaker-labelled as
`[Ali]: ...`, and that label is used as the assignee when the sentence itself
names nobody.
"""

from __future__ import annotations

import re
from typing import Any

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?۔؟])\s+|\n+")
_WHITESPACE = re.compile(r"[^\S\n]+")
_SPEAKER_LINE = re.compile(r"^\[(?P<speaker>[^\]]{1,60})\]:\s*(?P<text>.*)$")

_DECISION_MARKER = re.compile(
    r"\b(decided|agreed|approved|confirmed|finalized|will proceed|let'?s go with"
    r"|tay hua|tay kiya|faisla|final hua|manzoor)\b"
    r"|طے\s*ہوا|فیصلہ|منظور|اتفاق",
    re.IGNORECASE | re.UNICODE,
)

# "Ali will send the report by Friday" / "Ali ko report bhejni hai"
_ACTION_ENGLISH = re.compile(
    r"\b(?P<assignee>[A-Z][a-z]{1,30})\s+"
    r"(?:will|shall|should|needs? to|has to|is going to|must)\s+"
    r"(?P<task>[^.!?]+?)(?:\s+by\s+(?P<deadline>[^.!?]+))?[.!?]?$",
    re.IGNORECASE,
)
_ACTION_ROMAN_URDU = re.compile(
    r"\b(?P<assignee>[A-Za-z]{2,30})\s+(?:ko|ne)\s+(?P<task>[^.!?]+?)"
    r"(?:\s+(?P<deadline>(?:kal|aaj|parso|[a-z]+day|\d+\s*\w+)\s*tak))?"
    r"\s*(?:karna|karni|karna hai|karni hai|bhejna|bhejni|dena|deni)\b",
    re.IGNORECASE,
)
_ASSIGNMENT_HINT = re.compile(
    r"\b(karna hai|karni hai|bhejna hai|bhejni hai|dekh lena|complete karna"
    r"|responsible|assign|task|action item|todo)\b"
    r"|کرنا\s*ہے|کرنی\s*ہے|بھیجنا\s*ہے|ذمہ\s*دار",
    re.IGNORECASE | re.UNICODE,
)


def _lines(transcript: str) -> list[tuple[str | None, str]]:
    """Split a transcript into (speaker, sentence) pairs."""
    output: list[tuple[str | None, str]] = []
    for raw_line in transcript.splitlines():
        line = _WHITESPACE.sub(" ", raw_line).strip()
        if not line:
            continue
        speaker = None
        match = _SPEAKER_LINE.match(line)
        if match:
            speaker = match.group("speaker").strip()
            line = match.group("text").strip()
        for sentence in _SENTENCE_BOUNDARY.split(line):
            sentence = sentence.strip(" -•\t")
            if sentence:
                output.append((speaker, sentence))
    return output


def analyze_with_fallback(transcript: str) -> dict[str, Any]:
    """Return safe structured notes without calling an external service."""
    pairs = _lines(transcript)
    sentences = [text for _, text in pairs]
    summary = " ".join(sentences[:3]) if sentences else "No transcript content was provided."

    decisions: list[str] = []
    action_items: list[dict[str, str | None]] = []

    for speaker, sentence in pairs:
        if _DECISION_MARKER.search(sentence) and sentence not in decisions:
            decisions.append(sentence)

        item = _extract_action(sentence, speaker)
        if item and not any(existing["task"] == item["task"] for existing in action_items):
            action_items.append(item)

    return {
        "summary": summary,
        "decisions": decisions,
        "action_items": action_items,
    }


def _extract_action(sentence: str, speaker: str | None) -> dict[str, str | None] | None:
    """Pull one action item out of a sentence, or None if it holds no assignment."""
    for pattern in (_ACTION_ENGLISH, _ACTION_ROMAN_URDU):
        match = pattern.search(sentence)
        if match:
            deadline = match.groupdict().get("deadline")
            return {
                "assignee": match.group("assignee").strip().title(),
                "assigned_by": speaker,
                "task": match.group("task").strip(" ,"),
                "deadline": deadline.strip() if deadline else None,
            }

    # An unmistakable assignment phrase with no parseable name still belongs in
    # the notes — the speaker is recorded, the owner left blank rather than guessed.
    if _ASSIGNMENT_HINT.search(sentence):
        return {
            "assignee": None,
            "assigned_by": speaker,
            "task": sentence,
            "deadline": None,
        }
    return None
