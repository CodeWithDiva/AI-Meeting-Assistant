"""Ollama-backed meeting analysis — v4, bilingual (Urdu + English).

Two changes carry most of the quality here:

* **The notes come back in the meeting's own language.** Summarizing an Urdu
  meeting into English throws away exactly the nuance the notes exist to keep,
  so the transcript's script decides the output language.
* **The attendee roster is given to the model.** The bot reads real participant
  names off the meeting UI, and passing them in is what lets "Ali ko ye karna
  hai" resolve to the registered user Ali rather than a loose string.

Small local models are inconsistent about JSON shape, so every field is
normalized on the way out — callers can rely on the contract in
:func:`_normalize`.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Urdu/Arabic script block — presence of these means the meeting was in Urdu.
_URDU_CHARS = re.compile(r"[؀-ۿݐ-ݿ]")
# Enough Urdu to be the meeting's language rather than a stray quoted word.
_URDU_SHARE_THRESHOLD = 0.10


def detect_transcript_language(transcript: str) -> str:
    """Return 'ur' when the transcript is substantially Urdu script, else 'en'.

    Roman Urdu is deliberately reported as 'en': it is written in Latin script,
    and the model handles it best when it is allowed to reply in kind.
    """
    letters = [c for c in transcript if c.isalpha()]
    if not letters:
        return "en"
    urdu = sum(1 for c in letters if _URDU_CHARS.match(c))
    return "ur" if urdu / len(letters) >= _URDU_SHARE_THRESHOLD else "en"


def _build_prompt(transcript: str, participants: list[str] | None, language: str) -> str:
    if language == "ur":
        language_rule = (
            "یہ میٹنگ اردو میں ہے۔ summary، decisions اور tasks سب اردو میں لکھیں۔ "
            "ناموں، اعداد اور انگریزی اصطلاحات (deadline, client, report) کو ویسے ہی رہنے دیں۔"
        )
    else:
        language_rule = (
            "Write the summary, decisions and tasks in English. "
            "If the meeting is in Roman Urdu, keep the speakers' own wording for "
            "names, dates and technical terms instead of translating them away."
        )

    roster = ""
    if participants:
        roster = (
            "\nPeople in this meeting (use these exact names for assignees "
            "whenever the transcript refers to them):\n  "
            + ", ".join(participants)
            + "\n"
        )

    return (
        "You are an expert meeting analyst. Read the transcript and extract "
        "structured notes.\n\n"
        f"{language_rule}\n"
        f"{roster}\n"
        "Return ONLY valid JSON with exactly these keys:\n"
        '  "summary": (string) what the meeting was about and what came out of it\n'
        '  "decisions": (array of strings) each decision the group actually settled on\n'
        '  "action_items": (array of objects) each with:\n'
        '      "assignee":    (string) the ONE person who must do it\n'
        '      "assigned_by": (string or null) who gave them the task\n'
        '      "task":        (string) what exactly they must do\n'
        '      "deadline":    (string or null) when it is due, in the words used\n\n'
        "Rules:\n"
        "- The transcript is labelled with speaker names like '[Ali]: ...'. "
        "That label is only who was SPEAKING. It is NOT automatically the "
        "assignee.\n"
        "- CRITICAL — the assignee is the person NAMED IN THE SENTENCE as the "
        "one who must do the work, not the person who said it. Examples:\n"
        "    '[Sara]: Ali will send the report'  -> assignee 'Ali', assigned_by 'Sara'\n"
        "    '[Sara]: Bilal ko report bhejni hai' -> assignee 'Bilal', assigned_by 'Sara'\n"
        "    '[Sara]: I will send the report'    -> assignee 'Sara', assigned_by null\n"
        "  Only fall back to the speaker when they clearly took the task "
        "themselves ('I will…', 'main kar dunga', 'let me handle it').\n"
        "- Never invent a person who does not appear in the transcript.\n"
        "- One object per person per task. If three people were each given "
        "something, return three objects.\n"
        "- A decision is something the group AGREED. Do not list mere "
        "suggestions, questions, or things still being debated.\n"
        "- If a task has no clear owner, set \"assignee\" to null rather than "
        "guessing.\n"
        "- If nothing was decided or assigned, return empty arrays. Never "
        "invent content to fill them.\n\n"
        "Transcript:\n\n" + transcript
    )


async def _installed_models(client: httpx.AsyncClient, base_url: str) -> list[str]:
    """Names of the models Ollama currently has pulled."""
    try:
        response = await client.get(f"{base_url}/api/tags", timeout=10)
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", []) if m.get("name")]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return []


def _best_available(models: list[str]) -> str | None:
    """Pick the most capable installed model for multilingual meeting notes.

    Qwen handles Urdu markedly better than Llama at the same size, and a
    coder-tuned model is a poor fit for prose, so it sorts last.
    """
    if not models:
        return None
    ranked = sorted(
        models,
        key=lambda name: (
            0 if name.startswith("qwen") and "coder" not in name else
            1 if "coder" not in name else 2,
        ),
    )
    return ranked[0]


async def analyze_with_ollama(
    transcript: str,
    participants: list[str] | None = None,
) -> dict[str, Any]:
    """Ask a local Ollama model for structured, language-matched meeting notes."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    language = detect_transcript_language(transcript)
    prompt = _build_prompt(transcript, participants, language)
    payload = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        # Near-zero temperature: notes must reflect the transcript, not the
        # model's imagination.
        "options": {"temperature": 0.1, "num_ctx": 8192},
    }

    async with httpx.AsyncClient(timeout=300) as client:
        try:
            response = await client.post(f"{base_url}/api/generate", json=payload)
            if response.status_code == 404:
                # The configured model isn't pulled yet (a 4.7GB download can
                # still be running). Any installed model beats falling back to
                # the regex extractor.
                substitute = _best_available(await _installed_models(client, base_url))
                if not substitute:
                    raise RuntimeError(
                        f"Ollama has no model {model!r} and nothing else installed. "
                        f"Run: ollama pull {model}"
                    )
                logger.warning(
                    "Ollama model %r is not installed — using %r for this analysis. "
                    "Run `ollama pull %s` for the intended quality.",
                    model, substitute, model,
                )
                payload["model"] = substitute
                model = substitute
                response = await client.post(f"{base_url}/api/generate", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError(f"Ollama is unavailable or returned an error: {error}") from error

    raw = response.json().get("response")
    if not isinstance(raw, str):
        raise RuntimeError("Ollama returned an invalid analysis response.")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("Ollama did not return parseable JSON.") from error
    if not isinstance(parsed, dict):
        raise RuntimeError("Ollama returned a non-object analysis response.")

    notes = _normalize(parsed)
    notes["language"] = language
    notes["provider"] = f"ollama:{model}"
    return notes


def _normalize(parsed: dict[str, Any]) -> dict[str, Any]:
    """Coerce a small model's loose JSON into the shape callers expect.

    Local models routinely return a decision as `{"decision": "..."}` instead of
    a plain string, or omit `assignee` entirely. Rather than dropping those, the
    salvageable shapes are converted and the rest discarded.
    """
    summary = parsed.get("summary")
    if isinstance(summary, list):
        summary = " ".join(str(part) for part in summary)
    summary = (summary or "").strip() if isinstance(summary, str) else ""

    decisions: list[str] = []
    for raw in parsed.get("decisions") or []:
        if isinstance(raw, str) and raw.strip():
            decisions.append(raw.strip())
        elif isinstance(raw, dict):
            text = raw.get("decision") or raw.get("text") or raw.get("summary")
            if isinstance(text, str) and text.strip():
                decisions.append(text.strip())

    action_items: list[dict[str, Any]] = []
    for raw in parsed.get("action_items") or []:
        if isinstance(raw, str):
            if raw.strip():
                action_items.append({"assignee": None, "assigned_by": None,
                                      "task": raw.strip(), "deadline": None})
            continue
        if not isinstance(raw, dict):
            continue
        task = raw.get("task") or raw.get("action") or raw.get("description")
        if not isinstance(task, str) or not task.strip():
            continue
        action_items.append({
            "assignee": _clean_optional(raw.get("assignee") or raw.get("owner")),
            "assigned_by": _clean_optional(raw.get("assigned_by") or raw.get("requested_by")),
            "task": task.strip(),
            "deadline": _clean_optional(raw.get("deadline") or raw.get("due") or raw.get("due_date")),
        })

    return {"summary": summary, "decisions": decisions, "action_items": action_items}


def _clean_optional(value: Any) -> str | None:
    """Normalize a maybe-present string field, mapping model 'nulls' to None."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.casefold() in {"null", "none", "n/a", "na", "-", "unknown"}:
        return None
    return cleaned
