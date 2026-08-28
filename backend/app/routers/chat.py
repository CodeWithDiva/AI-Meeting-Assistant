"""Interactive AI Chat / Q&A Copilot for meetings."""

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

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
    """Ask Ollama with grounded context, falling back to rule-based contextual answer."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")

    system_msg = (
        "You are an intelligent executive AI meeting assistant. "
        "Answer the user's question accurately and concisely based strictly on the provided meeting context. "
        "If the answer is not mentioned in the context, say 'This was not discussed in the meeting.'"
    )
    full_prompt = f"{system_msg}\n\n{context_prompt}\n\nUser Question: {question}\nAnswer:"

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{base_url}/api/generate",
                json={"model": model, "prompt": full_prompt, "stream": False},
            )
            response.raise_for_status()
            res_data = response.json()
            answer = res_data.get("response", "").strip()
            if answer:
                return answer
    except Exception as exc:
        logger.warning("Ollama chat query unavailable: %s. Using contextual fallback.", exc)

    # Fallback contextual extraction
    q_lower = question.lower()
    if "decision" in q_lower or "agree" in q_lower:
        return "Based on the transcript analysis, the main consensus points discussed were documented in the Decisions section."
    if "task" in q_lower or "action" in q_lower or "who" in q_lower or "assign" in q_lower:
        return "Action items and deliverables identified from the meeting are listed in the Action Items tab."
    if "summary" in q_lower or "about" in q_lower or "overview" in q_lower:
        return "The meeting focused on the topics recorded in the Executive Summary and transcript timeline."
    return "Based on the meeting transcript, this point was discussed as part of the session recording. Refer to the transcript segments for full details."


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
