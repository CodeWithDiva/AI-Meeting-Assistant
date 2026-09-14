"""Interactive AI Chat / Q&A Copilot for meetings."""

import logging
import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.ollama import _best_available, _installed_models
from app.auth import get_current_user
from app.database import get_db
from app.models import ActionItem, Decision, Meeting, Summary, TranscriptSegment, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings/{meeting_id}/chat", tags=["chat"])


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class QuestionResponse(BaseModel):
    question: str
    answer: str
    sources: list[str] = []


def _owned_meeting(meeting_id: int, user: User, db: Session) -> Meeting:
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return meeting


async def _ask_llm(context_prompt: str, question: str, *, style: str = "spoken") -> str:
    """Ask Ollama with grounded context, falling back to a context-derived answer.

    `style` controls how much room the answer gets:
    * "spoken"  — a live wake-word reply that gets synthesized and played into
      a meeting. Must stay to a sentence or two, both because a long spoken
      answer is unusable in a meeting and because generation time is what the
      room waits through.
    * "written" — read on screen (the meeting Q&A tab, the workspace-wide ask
      panel), never spoken. Free to be a short list when the question asks
      for one ("what's still open", "all pending tasks") instead of being
      squeezed into three sentences that can only name one thing.
    """
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    multi_meeting = context_prompt.count("\nMeeting: ") + context_prompt.startswith("Meeting: ") > 1

    if style == "written":
        length_rule = (
            "Answer fully — if the question asks for a list (open tasks, "
            "decisions, what's new), give every matching item as its own "
            "line starting with '- ', not just the first one you find. "
            "Otherwise a few sentences is fine. Don't pad the answer with "
            "filler once it's complete."
        )
    else:
        length_rule = (
            "Answer in one to three short sentences — this will be spoken "
            "aloud in the meeting, so favour the single most relevant fact "
            "over an exhaustive list."
        )

    scope_rule = (
        "The context below covers several different meetings, each starting "
        "with 'Meeting: <title>'. Treat them as separate meetings — pull "
        "together everything relevant across ALL of them, and when you name "
        "an item from a specific meeting, say which one if more than one "
        "meeting has something relevant. Never merge facts from different "
        "meetings into one item.\n"
        if multi_meeting else ""
    )

    system_msg = (
        "You are Alina, an AI meeting assistant. Answer the question "
        f"accurately, using ONLY the context below. {length_rule}\n"
        f"{scope_rule}"
        "Reply in the same language the question was asked in (English, Urdu, "
        "or Roman Urdu). When asked who has a task, the owner is the person "
        "the transcript names as doing it — '[Sara]: Ali will send the report' "
        "means Ali's task, not Sara's. Do not start with your own name. If the "
        "context does not contain the answer, say so plainly rather than "
        "guessing or padding — don't invent a meeting, task or decision that "
        "isn't in the context."
    )
    full_prompt = f"{system_msg}\n\n{context_prompt}\n\nQuestion: {question}\nAnswer:"
    payload = {
        "model": model,
        "prompt": full_prompt,
        "stream": False,
        # Low temperature keeps answers to what the context says, not the
        # model's imagination. The token cap bounds latency on a slow CPU;
        # "written" answers get more room since they may need to list several
        # items rather than name just one.
        "options": {"temperature": 0.2, "num_predict": 160 if style == "spoken" else 450},
        # Ollama's default is to unload a model 5 minutes after its last use.
        # Measured on a weak 2-core CPU: ~75s to load qwen2.5:7b cold vs. ~7s
        # once warm — reloading between two questions in the same meeting is
        # the difference between Alina answering promptly and seeming to
        # ignore the wake word for over a minute. Keep it resident through a
        # normal meeting instead.
        "keep_alive": "30m",
    }

    try:
        # qwen2.5:7b on a weak 2-core CPU has measured well over 60s for a
        # cold model load plus generation — the old 90s ceiling was cutting
        # that close enough to fall back to the canned answer more often
        # than it should. Alina always replies with *something* either way
        # (the except below never raises), but a completed LLM answer beats
        # the generic fallback whenever there is time for one.
        async with httpx.AsyncClient(timeout=150) as client:
            response = await client.post(f"{base_url}/api/generate", json=payload)
            if response.status_code == 404:
                # The configured model isn't pulled. Previously this fell
                # straight through to the canned fallback below, so the
                # assistant "answered" every question with a stock sentence
                # even though a perfectly usable model was installed.
                substitute = _best_available(await _installed_models(client, base_url))
                if substitute:
                    logger.warning(
                        "Ollama model %r is not installed — answering with %r. "
                        "Run `ollama pull %s` for the intended quality.",
                        model, substitute, model,
                    )
                    payload["model"] = substitute
                    response = await client.post(f"{base_url}/api/generate", json=payload)
            response.raise_for_status()
            answer = response.json().get("response", "").strip()
            if answer:
                return answer
    except Exception as exc:
        logger.warning("Ollama chat query unavailable: %s. Using contextual fallback.", exc)

    return _fallback_answer(context_prompt, question)


# A question wants this section if any of its trigger words appear.
_FALLBACK_INTENTS: list[tuple[str, tuple[str, ...]]] = [
    ("Action Items", (
        "task", "action", "assign", "who", "pending", "open", "todo", "overdue",
        "kaam", "kis ne", "kisko", "baqi", "project", "new update", "status",
    )),
    ("Decisions", ("decid", "decision", "agree", "faisla", "tay")),
    ("Summary", ("summary", "about", "overview", "khulasa", "kya baat")),
]


def _fallback_answer(context_prompt: str, question: str) -> str:
    """Answer from the context itself when no LLM is reachable.

    `context_prompt` may describe one meeting or several, each starting with
    a "Meeting: <title>" line. A question about tasks or decisions gets every
    matching section from every meeting block — not just whichever meeting's
    lines happened to appear last, which is what a flat key→value scan over
    the whole prompt would silently collapse to.
    """
    blocks = re.split(r"(?=^Meeting: )", context_prompt, flags=re.MULTILINE)
    meetings: list[dict[str, str]] = []
    for block in blocks:
        if not block.strip():
            continue
        title = "This meeting"
        fields: dict[str, str] = {}
        for line in block.splitlines():
            key, sep, value = line.partition(": ")
            if not sep:
                continue
            if key == "Meeting" or key == "Meeting Title":
                title = value.strip()
            elif key in {"Decisions", "Action Items", "Summary"} and value.strip():
                fields[key] = value.strip()
        if fields:
            meetings.append({"title": title, **fields})

    if not meetings:
        return "I don't have enough notes yet to answer that — try again once a meeting has been analyzed."

    q_lower = question.lower()
    explicit_key = next(
        (key for key, words in _FALLBACK_INTENTS if any(w in q_lower for w in words)),
        None,
    )
    wanted_key = explicit_key or "Summary"
    matches = [(m["title"], wanted_key, m[wanted_key]) for m in meetings if wanted_key in m]
    if not matches:
        # Nothing for the section the question seems to want — fall back to
        # whatever each meeting does have, in a fixed order of preference.
        for key in ("Summary", "Action Items", "Decisions"):
            matches = [(m["title"], key, m[key]) for m in meetings if key in m]
            if matches:
                break

    if not matches:
        return "I don't have enough notes yet to answer that."
    # A single meeting answering with the section it fell back to on its own
    # (nothing in the question pointed at Decisions/Action Items/Summary)
    # reads better as the bare fact, not a label nobody asked for.
    if len(matches) == 1 and not explicit_key:
        return matches[0][2]
    if len(matches) == 1:
        return f"{matches[0][1]}: {matches[0][2]}"
    return "\n".join(f"- {title} — {key}: {value}" for title, key, value in matches)


@router.post("/ask", response_model=QuestionResponse)
async def ask_meeting_question(
    meeting_id: int,
    request: QuestionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QuestionResponse:
    meeting = _owned_meeting(meeting_id, user, db)

    # Gather meeting context
    summary_obj = db.scalar(select(Summary).where(Summary.meeting_id == meeting_id))
    decisions = list(db.scalars(select(Decision).where(Decision.meeting_id == meeting_id)))
    tasks = list(db.scalars(select(ActionItem).where(ActionItem.meeting_id == meeting_id)))
    segments = list(
        db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.start_time)
        )
    )

    context_lines = [f"Meeting Title: {meeting.title}"]
    if summary_obj and summary_obj.text:
        context_lines.append(f"Summary: {summary_obj.text}")
    if decisions:
        context_lines.append("Decisions: " + "; ".join(d.text for d in decisions))
    if tasks:
        context_lines.append(
            "Action Items: "
            + "; ".join(
                f"{t.task} (Assigned to {t.assignee or 'Unassigned'}, "
                f"Status: {t.status}, Due: {t.deadline or 'TBD'})"
                for t in tasks
            )
        )
    if segments:
        context_lines.append(
            "Transcript:\n" + "\n".join(f"[{s.speaker_label or 'Speaker'}]: {s.text}" for s in segments[:30])
        )
    elif meeting.transcript:
        context_lines.append(f"Transcript: {meeting.transcript[:2000]}")

    context_str = "\n\n".join(context_lines)

    # This tab is read on screen, never spoken — unlike the wake-word reply
    # in a live meeting, it can afford a real list when the question wants one.
    answer = await _ask_llm(context_str, request.question, style="written")

    sources = []
    if summary_obj:
        sources.append("Executive Summary")
    if tasks:
        sources.append(f"{len(tasks)} Action Items")
    if segments:
        sources.append(f"{len(segments)} Transcript Segments")

    return QuestionResponse(
        question=request.question,
        answer=answer,
        sources=sources,
    )
