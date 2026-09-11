"""Interactive AI Chat / Q&A Copilot for meetings."""

import logging
import os
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


async def _ask_llm(context_prompt: str, question: str) -> str:
    """Ask Ollama with grounded context, falling back to a context-derived answer."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")

    system_msg = (
        "You are Alina, an AI meeting assistant. Answer the question accurately "
        "and briefly — one to three short sentences, since the answer may be "
        "spoken aloud in the meeting — using ONLY the meeting context below. "
        "Reply in the same language the question was asked in (English, Urdu, "
        "or Roman Urdu). When asked who has a task, the owner is the person "
        "the transcript names as doing it — '[Sara]: Ali will send the report' "
        "means Ali's task, not Sara's. Do not start with your own name. If the "
        "context does not contain the answer, say it was not discussed in the "
        "meeting."
    )
    full_prompt = f"{system_msg}\n\n{context_prompt}\n\nQuestion: {question}\nAnswer:"
    payload = {
        "model": model,
        "prompt": full_prompt,
        "stream": False,
        # Low temperature keeps answers to what the transcript says; the token
        # cap keeps a spoken reply short and bounds latency on a slow CPU.
        "options": {"temperature": 0.2, "num_predict": 160},
    }

    try:
        # A cold model load on a modest CPU measured ~25s before the first
        # token, so the old 45s ceiling left little margin.
        async with httpx.AsyncClient(timeout=90) as client:
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


def _fallback_answer(context_prompt: str, question: str) -> str:
    """Answer from the context itself when no LLM is reachable.

    The old fallback returned the same stock sentence ("refer to the tab")
    whatever was asked, which sounds like an answer but tells nobody anything.
    This quotes what the context actually holds for the kind of question asked.
    """
    lines = {
        key: value.strip()
        for key, _, value in (line.partition(": ") for line in context_prompt.splitlines())
        if key in {"Decisions", "Action Items", "Summary"} and value.strip()
    }
    q_lower = question.lower()
    wants = [
        ("Decisions", ("decid", "decision", "agree", "faisla", "tay")),
        ("Action Items", ("task", "action", "assign", "who", "kaam", "kis ne", "kisko")),
        ("Summary", ("summary", "about", "overview", "khulasa", "kya baat")),
    ]
    for key, words in wants:
        if any(w in q_lower for w in words) and key in lines:
            return f"{key}: {lines[key]}"
    if "Summary" in lines:
        return lines["Summary"]
    return "I don't have enough from this meeting yet to answer that."


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
                f"{t.task} (Assigned to {t.assignee or 'Unassigned'}, Due: {t.deadline or 'TBD'})"
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

    answer = await _ask_llm(context_str, request.question)

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
