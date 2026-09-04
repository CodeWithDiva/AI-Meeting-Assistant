"""Wake-word voice assistant for meeting transcript responses."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Decision, Meeting, Summary, TranscriptSegment
from app.routers.chat import _ask_llm
from app.services.tts import TTSService

logger = logging.getLogger(__name__)


@dataclass
class VoiceReply:
    question: str
    answer: str
    audio_wav: bytes


class AvaVoiceAssistant:
    """Detect 'Ava' in recognized speech and prepare a spoken answer."""

    wake_words = ("ava", "اوا")

    def __init__(self, meeting_id: int) -> None:
        self.meeting_id = meeting_id
        self.tts = TTSService()
        self.last_reply: VoiceReply | None = None

    async def handle_transcript(self, text: str) -> VoiceReply | None:
        question = self._question_after_wake_word(text)
        if not question:
            return None
        answer = await self._answer(question)
        reply = VoiceReply(question=question, answer=answer, audio_wav=self.tts.synthesize_speech_wav(answer))
        self.last_reply = reply
        return reply

    def audio_base64(self) -> str | None:
        if not self.last_reply:
            return None
        return base64.b64encode(self.last_reply.audio_wav).decode("ascii")

    def _question_after_wake_word(self, text: str) -> str | None:
        lowered = text.casefold()
        for wake_word in self.wake_words:
            position = lowered.find(wake_word)
            if position >= 0:
                question = text[position + len(wake_word):].strip(" ,:;-?!")
                return question or "Please repeat your question."
        return None

    async def _answer(self, question: str) -> str:
        with SessionLocal() as db:
            meeting = db.get(Meeting, self.meeting_id)
            if not meeting:
                return "I could not find this meeting."
            context = [f"Meeting: {meeting.title}"]
            summary = db.scalar(select(Summary).where(Summary.meeting_id == self.meeting_id))
            if summary:
                context.append(f"Summary: {summary.text}")
            decisions = list(db.scalars(select(Decision).where(Decision.meeting_id == self.meeting_id)))
            if decisions:
                context.append("Decisions: " + "; ".join(item.text for item in decisions))
            segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.meeting_id == self.meeting_id).order_by(TranscriptSegment.start_time).limit(40)))
            if segments:
                context.append("Transcript: " + " ".join(item.text for item in segments))
            elif meeting.transcript:
                context.append("Transcript: " + meeting.transcript[:4000])
        return await _ask_llm("\n\n".join(context), question)
