"""Persist Zoom RTMS audio chunks through the existing Whisper pipeline."""

from __future__ import annotations

import asyncio
import logging
import wave
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from sqlalchemy import select

from app.ai.service import analyze_meeting
from app.database import SessionLocal
from app.models import ActionItem, Decision, Meeting, Notification, Summary, TranscriptSegment
from app.transcription.base import FasterWhisperService

logger = logging.getLogger(__name__)


class RTMSTranscriptionPipeline:
    """Buffer PCM audio, transcribe complete windows, and persist results."""

    def __init__(self, meeting_id: int, sample_rate: int = 16_000) -> None:
        self.meeting_id = meeting_id
        self.sample_rate = sample_rate
        self._audio = bytearray()
        self._offset = 0.0
        self._service = FasterWhisperService()
        self._lock = asyncio.Lock()

    async def add_chunk(self, chunk: bytes) -> list[str]:
        """Add PCM16 mono audio and return any newly transcribed text."""
        if not chunk:
            return []
        async with self._lock:
            self._audio.extend(chunk)
            window_bytes = self.sample_rate * 2 * 4
            if len(self._audio) < window_bytes:
                return []
            window = bytes(self._audio[:window_bytes])
            del self._audio[:window_bytes]
            return await self._transcribe(window, 4.0)

    async def flush(self) -> list[str]:
        """Transcribe the final partial window, if it contains audio."""
        async with self._lock:
            if not self._audio:
                return []
            window = bytes(self._audio)
            self._audio.clear()
            return await self._transcribe(window, len(window) / (self.sample_rate * 2))

    async def finalize(self) -> None:
        """Flush remaining audio and analyze the saved meeting transcript."""
        await self.flush()
        with SessionLocal() as db:
            meeting = db.scalar(select(Meeting).where(Meeting.id == self.meeting_id))
            transcript = meeting.transcript if meeting else None
        if transcript:
            notes = await analyze_meeting(transcript)
            with SessionLocal() as db:
                meeting = db.scalar(select(Meeting).where(Meeting.id == self.meeting_id))
                if not meeting:
                    return
                summary = db.scalar(select(Summary).where(Summary.meeting_id == self.meeting_id))
                if summary:
                    summary.text = notes["summary"]
                    summary.provider = notes.get("provider", "ollama")
                else:
                    db.add(Summary(
                        meeting_id=self.meeting_id,
                        text=notes["summary"],
                        provider=notes.get("provider", "ollama"),
                    ))
                db.query(Decision).filter(Decision.meeting_id == self.meeting_id).delete()
                db.query(ActionItem).filter(ActionItem.meeting_id == self.meeting_id).delete()
                for decision in notes.get("decisions", []):
                    db.add(Decision(meeting_id=self.meeting_id, text=decision))
                for item in notes.get("action_items", []):
                    db.add(ActionItem(
                        meeting_id=self.meeting_id,
                        task=item["task"],
                        assignee=item.get("assignee"),
                        assigned_by=item.get("assigned_by"),
                        deadline=item.get("deadline"),
                    ))
                meeting.ended_at = datetime.utcnow()
                db.add(Notification(
                    user_id=meeting.owner_id,
                    meeting_id=self.meeting_id,
                    type="summary_ready",
                    title=f"Summary Ready: {meeting.title}",
                    body="RTMS transcript processing completed.",
                    read=False,
                ))
                db.commit()

    async def _transcribe(self, pcm_data: bytes, duration: float) -> list[str]:
        with NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            path = Path(temp_file.name)
        try:
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(pcm_data)
            result = await self._service.transcribe(path)
        except Exception:
            logger.exception("RTMS transcription failed for meeting %d", self.meeting_id)
            return []
        finally:
            path.unlink(missing_ok=True)

        texts = [segment.text.strip() for segment in result.segments if segment.text.strip()]
        if not texts:
            return []

        with SessionLocal() as db:
            meeting = db.scalar(select(Meeting).where(Meeting.id == self.meeting_id))
            if not meeting:
                return []
            for segment in result.segments:
                text = segment.text.strip()
                if not text:
                    continue
                start = self._offset + segment.start
                end = self._offset + segment.end
                db.add(TranscriptSegment(
                    meeting_id=self.meeting_id,
                    text=text,
                    start_time=start,
                    end_time=end,
                    speaker_label="SPEAKER_RTMS",
                    source="rtms",
                ))
            meeting.transcript = f"{meeting.transcript or ''} {result.full_text}".strip()
            db.commit()

        # Real-time WebSocket broadcasting for live UI display
        try:
            from app.services.ws_manager import ws_manager
            for text in texts:
                asyncio.create_task(
                    ws_manager.broadcast(
                        self.meeting_id,
                        "transcript_live",
                        {"speaker": "Speaker", "text": text},
                    )
                )
        except Exception as exc:
            logger.debug("Failed to broadcast transcript_live: %s", exc)

        self._offset += duration
        return texts


def extract_action_item(text: str) -> str | None:
    """Extract explicit spoken task markers from a transcript fragment."""
    lowered = text.lower()
    for marker in ("action item:", "task:", "todo:"):
        if marker in lowered:
            value = text[lowered.index(marker) + len(marker):].strip(" .!?,")
            return value or None
    return None
