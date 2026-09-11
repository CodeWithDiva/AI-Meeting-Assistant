"""Wake-word voice assistant for meeting transcript responses.

Full audio loop:
    Meeting audio (PCM)
        → Whisper STT  (in RTMSTranscriptionPipeline, fed by any audio
          source — Zoom RTMS *or* the browser bot's virtual mic capture)
        → AvaVoiceAssistant.handle_transcript()
            → wake-word "Ava" detected
            → LLM answer via _ask_llm()
            → TTS WAV via TTSService
            → ws_manager.broadcast() → frontend audio player (always)
            → on_audio_out(wav_bytes) → optional live voice publish
              (e.g. BrowserMeetingBot plays it into the outbound virtual
              audio cable so Zoom hears it as the bot's own mic)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ActionItem, Decision, Meeting, Summary, TranscriptSegment
from app.routers.chat import _ask_llm
from app.services.tts import TTSService

logger = logging.getLogger(__name__)

AudioOutCallback = Callable[[bytes], Awaitable[None]]


@dataclass
class VoiceReply:
    question: str
    answer: str
    audio_wav: bytes
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @property
    def audio_base64(self) -> str:
        return base64.b64encode(self.audio_wav).decode("ascii")


_WORD = re.compile(r"[a-zA-Z]{2,10}")

# The name people call the assistant by. Defaults to the name it joins under,
# so renaming the bot renames its wake-word too; override with BOT_WAKE_WORD.
WAKE_WORD = (
    os.getenv("BOT_WAKE_WORD")
    or os.getenv("BOT_DISPLAY_NAME", "Alina").split()[0]
).strip().casefold()

# Urdu-script spellings of the wake word, checked as exact substrings.
_URDU_WAKE_WORDS = {
    "alina": ("الینا", "علینا"),
    "ava": ("اوا", "ایوا"),
}

# Spellings Whisper actually produces for these names, beyond what a one-edit
# fuzzy match catches. Listing them explicitly is deliberate: widening the edit
# distance to 2 instead would start matching ordinary words — "align" is two
# edits from "alina" — and a false wake-up mid-meeting is worse than a missed one.
_WAKE_WORD_VARIANTS = {
    "alina": {"aleena", "alena", "aliena", "aleana", "elina", "eleena", "aalina", "halina"},
    "ava": {"eva", "aiva", "ayva", "aava"},
}


def _edit_distance_le1(a: str, b: str) -> bool:
    """True if two short lowercase strings differ by at most one edit.

    Whisper on a weak/CPU model or noisy audio routinely mishears a short
    name — "Alina" as "Aleena"/"Alena"/"Elina" — close enough that a strict
    substring match silently drops the wake-word and the assistant never
    answers. This is a plain Levenshtein check, capped at distance 1, so it
    only forgives a single edit and never matches an unrelated word.
    """
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    la, lb = len(a), len(b)
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[lb] <= 1


class AvaVoiceAssistant:
    """Detect the wake-word in speech, answer with the LLM, publish over WS."""

    def __init__(
        self,
        meeting_id: int,
        on_audio_out: AudioOutCallback | None = None,
        wake_word: str | None = None,
    ) -> None:
        # Per-instance so it can be overridden (tests, or a per-meeting name)
        # rather than being fixed at import time by the environment.
        core = (wake_word or WAKE_WORD).strip().casefold()
        # Exact substrings, checked first (fast path): the Latin-script name
        # plus any Urdu-script spellings known for it.
        self.wake_words = (core, *_URDU_WAKE_WORDS.get(core, ()))
        # Latin-script core, checked word-by-word with a one-edit tolerance so
        # a mis-transcribed name still wakes the assistant. See
        # _question_after_wake_word.
        self._wake_word_core = core
        self._wake_word_variants = _WAKE_WORD_VARIANTS.get(core, set())

        self.meeting_id = meeting_id
        self.tts = TTSService()
        self.last_reply: VoiceReply | None = None
        self._processing = False  # prevent concurrent replies
        # Optional live-voice sink — e.g. BrowserMeetingBot._speak_reply, which
        # plays the WAV into the outbound virtual audio cable so Zoom hears it.
        self._on_audio_out = on_audio_out

    async def handle_transcript(self, text: str) -> VoiceReply | None:
        """
        Called whenever a new transcript chunk is ready from Whisper.
        Returns a VoiceReply if 'Ava' wake-word was detected, else None.
        """
        if self._processing:
            return None  # skip if already generating a reply

        # The reply is played into the meeting, so it comes back round through
        # the capture (loopback of the speakers) and gets transcribed like
        # anyone else's speech. Don't let the assistant answer its own words.
        if self._is_own_echo(text):
            logger.debug("[Ava] Ignoring the assistant's own reply picked up by capture: %r", text)
            return None

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

            # Live in-meeting voice, if a bot audio sink was wired up
            await self._publish_audio_out(reply)

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

        # No exact hit -- Whisper mishearing "Ava" as "Eva"/"Aiva"/"Ave" etc.
        # is common enough on a weak model or noisy audio that a strict
        # substring match would silently drop the wake-word every time. One
        # edit's worth of tolerance on a short word catches those without
        # matching unrelated longer words.
        for match in _WORD.finditer(lowered):
            word = match.group()
            if word in self._wake_word_variants or _edit_distance_le1(word, self._wake_word_core):
                after = text[match.end():].strip(" ,:;-?!").strip()
                return after if after else ""
        return None

    def _extract_question(self, text: str) -> str | None:
        q = self._question_after_wake_word(text)
        if q == "":
            return "Please repeat your question."
        return q

    def _is_own_echo(self, text: str) -> bool:
        """True when a transcript line is mostly the assistant's last answer.

        Word overlap rather than an exact match, because the echo comes back
        through the speakers, the meeting codec and Whisper — it is never
        verbatim. The line must be substantially made of the answer's words,
        so a person merely repeating one or two of them still gets through.
        """
        if not self.last_reply or not self.last_reply.answer:
            return False
        said = set(_WORD.findall(text.casefold()))
        answer = set(_WORD.findall(self.last_reply.answer.casefold()))
        if len(said) < 3 or not answer:
            return False
        return len(said & answer) / len(said) >= 0.6

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

            tasks = list(
                db.scalars(select(ActionItem).where(ActionItem.meeting_id == self.meeting_id))
            )
            if tasks:
                context_parts.append(
                    "Action Items: "
                    + "; ".join(
                        f"{t.task} (Assigned to {t.assignee or 'Unassigned'}, "
                        f"Due: {t.deadline or 'TBD'})"
                        for t in tasks
                    )
                )

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

    async def _publish_audio_out(self, reply: VoiceReply) -> None:
        """
        If a live audio sink was provided (BrowserMeetingBot's virtual-cable
        playback), send Ava's WAV reply there so it's actually spoken inside
        the meeting. Without a sink, this is a harmless no-op — matches the
        old browser-only-read-aloud behaviour.
        """
        if not self._on_audio_out:
            logger.debug(
                "[Ava] No live audio sink attached — %d bytes stayed browser-only for meeting %d",
                len(reply.audio_wav),
                self.meeting_id,
            )
            return
        try:
            await self._on_audio_out(reply.audio_wav)
        except Exception:
            logger.exception("[Ava] Failed to publish live audio reply for meeting %d", self.meeting_id)
