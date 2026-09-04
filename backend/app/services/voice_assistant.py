"""Wake-word voice assistant for meeting transcript responses.

Full audio loop:
    Meeting audio (PCM)
        → Whisper STT  (in RTMSTranscriptionPipeline)
        → AvaVoiceAssistant.handle_transcript()
            → wake-word "Ava" detected
            → LLM answer via _ask_llm()
            → TTS WAV via TTSService
            → ws_manager.broadcast() → frontend audio player
            → RTMS outbound stub (future Zoom publish)
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from datetime import datetime

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
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @property
    def audio_base64(self) -> str:
        return base64.b64encode(self.audio_wav).decode("ascii")


class AvaVoiceAssistant:
    """Detect 'Ava' in recognized speech, generate an LLM answer, and publish via WebSocket."""

    # Multilingual wake-words — add more as needed
    wake_words = ("ava", "اوا", "ایوا")

    def __init__(self, meeting_id: int) -> None:
        self.meeting_id = meeting_id
        self.tts = TTSService()
        self.last_reply: VoiceReply | None = None
        self._processing = False  # prevent concurrent replies

    async def handle_transcript(self, text: str) -> VoiceReply | None:
        """
        Called whenever a new transcript chunk is ready from Whisper.
        Returns a VoiceReply if 'Ava' wake-word was detected, else None.
        """
        if self._processing:
            return None  # skip if already generating a reply

        question = self._extract_question(text)
        if not question:
            return None

        self._processing = True
        try:
            logger.info("[Ava] Wake-word detected in meeting %d — question: %s", self.meeting_id, question)
            answer = await self._answer(question)
            wav_bytes = await asyncio.get_event_loop().run_in_executor(
                None, self.tts.synthesize_speech_wav, answer
            )
            reply = VoiceReply(question=question, answer=answer, audio_wav=wav_bytes)
            self.last_reply = reply

            # Broadcast to all connected frontend clients
            await self._broadcast_reply(reply)

            # Stub: future Zoom RTMS outbound publish
            await self._publish_to_rtms(reply)

            return reply
        finally:
            self._processing = False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _question_after_wake_word(self, text: str) -> str | None:
        """Return text after wake-word, or None if no wake-word found."""
        lowered = text.casefold()
        for wake_word in self.wake_words:
            idx = lowered.find(wake_word)
            if idx >= 0:
                after = text[idx + len(wake_word) :].strip(" ,:;-?!٪۔،؟\u060c\u061f").strip()
                return after if after else ""
        return None

    def _extract_question(self, text: str) -> str | None:
        q = self._question_after_wake_word(text)
        if q == "":
            return "Please repeat your question."
        return q

    async def _answer(self, question: str) -> str:
        """Build context from DB and ask the LLM."""
        with SessionLocal() as db:
            meeting = db.get(Meeting, self.meeting_id)
            if not meeting:
                return "I could not find this meeting in the system."

            context_parts = [f"Meeting: {meeting.title}"]

            summary = db.scalar(
                select(Summary).where(Summary.meeting_id == self.meeting_id)
            )
            if summary:
                context_parts.append(f"Summary: {summary.text}")

            decisions = list(
                db.scalars(select(Decision).where(Decision.meeting_id == self.meeting_id))
            )
            if decisions:
                context_parts.append("Decisions: " + "; ".join(d.text for d in decisions))

            segments = list(
                db.scalars(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.meeting_id == self.meeting_id)
                    .order_by(TranscriptSegment.start_time)
                    .limit(60)
                )
            )
            if segments:
                context_parts.append(
                    "Transcript:\n"
                    + "\n".join(
                        f"[{s.speaker_label or 'Speaker'}]: {s.text}" for s in segments
                    )
                )
            elif meeting.transcript:
                context_parts.append(f"Transcript: {meeting.transcript[:5000]}")

        return await _ask_llm("\n\n".join(context_parts), question)

    async def _broadcast_reply(self, reply: VoiceReply) -> None:
        """Push the reply to all frontend WebSocket clients for this meeting."""
        try:
            from app.services.ws_manager import ws_manager

            await ws_manager.broadcast(
                self.meeting_id,
                "ava_reply",
                {
                    "question": reply.question,
                    "answer": reply.answer,
                    "audio_base64": reply.audio_base64,
                    "content_type": "audio/wav",
                    "timestamp": reply.timestamp,
                },
            )
            logger.info("[Ava] Reply broadcasted to %d WS client(s)", ws_manager.connection_count(self.meeting_id))
        except Exception as exc:
            logger.warning("[Ava] WebSocket broadcast failed: %s", exc)

    async def _publish_to_rtms(self, reply: VoiceReply) -> None:
        """
        STUB — future Zoom RTMS outbound audio injection.
        When Zoom officially supports outbound PCM injection via RTMS SDK,
        this method will send reply.audio_wav to the media WebSocket.
        """
        logger.debug(
            "[Ava] RTMS outbound stub: %d bytes of audio ready for meeting %d",
            len(reply.audio_wav),
            self.meeting_id,
        )
