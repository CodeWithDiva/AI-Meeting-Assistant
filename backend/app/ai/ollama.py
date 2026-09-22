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

from app.ai.prompts import build_notes_prompt as _build_prompt
from app.services.name_matching import phonetic_keys

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
        # The JSON is small; without a cap a rambling model can keep
        # generating for minutes on this CPU. Urdu-script output costs ~3-4
        # tokens per word, hence the headroom over an English-sized answer.
        "options": {"temperature": 0.1, "num_ctx": 8192, "num_predict": 900},
        # Keep the model resident — see the matching note in chat.py's
        # _ask_llm. A meeting's wake-word replies and its end-of-meeting
        # analysis both use this model; without this they fight the 5-minute
        # idle-unload and each pay a ~75s cold-load penalty independently.
        "keep_alive": "30m",
    }

    # Measured on this CPU: an Urdu-script meeting took longer than the old 300s
    # limit (model load + a long Urdu prompt + Urdu output), and then fell all
    # the way back to the offline extractor. The user is waiting for notes at
    # the end of a meeting either way, so wait for the real answer.
    async with httpx.AsyncClient(timeout=900) as client:
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
    _snap_assignees(notes, participants, transcript)
    _snap_assigned_by(notes, participants)
    _fill_missing_deadlines(notes, transcript)
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


def _snap_assignees(notes: dict[str, Any], roster: list[str] | None, transcript: str) -> None:
    """Fix each assignee against the roster, and blank the ones nobody said.

    A small model may return a name in Urdu script when the roster has it in
    Latin ("تاسمیہ" vs "Tasmia"), or a slightly mis-heard spelling — both then
    fail to resolve to a real account and the task reaches nobody. Snap to the
    roster spelling when exactly one person fits (exactly or by sound). And a
    name that is in neither the roster nor the transcript was invented; a task
    with no owner is better than one handed to a stranger.
    """
    roster = [name for name in (roster or []) if name]
    lowered = transcript.casefold()
    for item in notes.get("action_items", []):
        name = item.get("assignee")
        if not name:
            continue
        exact = [r for r in roster if r.casefold() == name.casefold()]
        if exact:
            item["assignee"] = exact[0]
            continue
        keys = phonetic_keys(name, min_len=1)
        sounds_like = [r for r in roster if keys and keys & phonetic_keys(r, min_len=1)]
        if len(sounds_like) == 1:
            item["assignee"] = sounds_like[0]
            continue
        first_token = name.split()[0].casefold() if name.split() else ""
        if first_token and first_token not in lowered:
            logger.info("Assignee %r appears nowhere in the meeting — leaving the task unassigned.", name)
            item["assignee"] = None


_FIRST_PERSON_WORDS = {"i", "i'll", "main", "mein", "mai", "میں"}


def _same_person(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    if a.casefold() == b.casefold():
        return True
    keys_a, keys_b = phonetic_keys(a, min_len=2), phonetic_keys(b, min_len=2)
    return bool(keys_a & keys_b)


def _snap_assigned_by(notes: dict[str, Any], roster: list[str] | None) -> None:
    """Tidy `assigned_by`: roster spelling, and never the assignee themselves."""
    roster = [name for name in (roster or []) if name]
    for item in notes.get("action_items", []):
        giver = item.get("assigned_by")
        if not giver:
            continue
        if giver.casefold() in {"speaker", "participant", "unknown"}:
            item["assigned_by"] = None  # the pipeline's placeholder label, not a person
            continue
        if _same_person(giver, item.get("assignee")):
            item["assigned_by"] = None  # "I will..." — nobody handed it to them
            continue
        match = [r for r in roster if _same_person(giver, r)]
        if len(match) == 1:
            item["assigned_by"] = match[0]


def _fill_missing_deadlines(notes: dict[str, Any], transcript: str) -> None:
    """Recover a deadline the model dropped, from the sentence that names the owner.

    Small models drop the deadline when a task sits in a long sentence. The
    fallback's deadline patterns are deterministic, so use them — but only on a
    clause where the assignee is the *subject* (one of its first two words),
    since a deadline lifted from the wrong sentence would set off false
    reminders and overdue alerts, which is worse than no deadline.
    """
    from app.ai.fallback import _CLAUSE_SPLIT, _lines, _split_deadline

    clauses = [
        (speaker, c.strip())
        for speaker, sentence in _lines(transcript)
        for c in _CLAUSE_SPLIT.split(sentence)
    ]
    for item in notes.get("action_items", []):
        name = item.get("assignee")
        if not name or item.get("deadline"):
            continue
        owner_tokens = {t.casefold() for t in re.split(r"\s+", name) if t}
        owner_keys = phonetic_keys(name, min_len=2)
        for speaker, clause in clauses:
            words = [w for w in re.split(r"[\s,.:;!?،۔]+", clause) if w][:2]
            is_subject = any(
                w.casefold() in owner_tokens or (owner_keys and owner_keys & phonetic_keys(w, min_len=2))
                for w in words
            )
            # "I will check it today" said by the owner themselves.
            first_person = bool(words) and words[0].casefold() in _FIRST_PERSON_WORDS
            if not is_subject and not (first_person and _same_person(speaker, name)):
                continue
            _, deadline = _split_deadline(clause)
            if deadline:
                item["deadline"] = deadline
                break
