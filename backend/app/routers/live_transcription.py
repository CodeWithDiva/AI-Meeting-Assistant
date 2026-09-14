"""WebSocket Real-Time Live Microphone Transcription Router."""

import asyncio
import io
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.auth import get_user_from_token
from app.database import SessionLocal
from app.models import ActionItem, Meeting, TranscriptSegment
from app.services.action_items import normalize_person_name, resolve_assignee
from app.services.deadlines import parse_deadline
from app.services.notifier import notify_task_assigned

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live_transcription"])

# "action item for Ali: send the report", "task for Ali, send the report"
# One of the spoken trigger markers, optionally followed by "for <name>",
# then a colon — the colon is what tells this apart from the word "task" or
# "note" simply coming up in ordinary conversation. Matches:
#   "action item: send the report"
#   "action item for Ali: send the report"
#   "task for Ali Khan, send the report"
_NAME = r"[a-zA-Z؀-ۿ][\w؀-ۿ]*(?:\s+[a-zA-Z؀-ۿ][\w؀-ۿ]*)?"
_TRIGGER = re.compile(
    rf"\b(?:action\s+item|take\s+a\s+note|todo|task|note\s+that)\b"
    rf"(?:\s+for\s+(?P<name>{_NAME}))?"
    rf"\s*[:,]\s*",
    re.I,
)
# "Ali will send the report", "Ali should send the report by Friday" — a name
# named as the sentence's subject, when the trigger itself named no one.
# Deliberately NOT matching a bare "to" — "Deploy to staging" would otherwise
# read "Deploy" as a person; "will"/"should" are what actually name an owner.
_NAMED_SUBJECT = re.compile(rf"^({_NAME})\s+(?:will|should)\s+", re.I)
# "by Friday", "due Friday 5 PM" trailing the task text
_TRAILING_DEADLINE = re.compile(r"\s+\b(?:by|due|before)\s+(.+)$", re.I)


def _extract_live_actions(text: str, meeting_id: int, db: Any) -> str | None:
    """Detect a spoken trigger phrase and auto-create an assigned action item.

    A name said right after the trigger — "action item for Ali: ..." or
    "Ali will send the report" — is matched against registered users the same
    way the end-of-meeting analysis does, so a task assigned by name during a
    live meeting is assigned to that person immediately, not only once the
    meeting ends and "Generate notes" runs.
    """
    trigger_match = _TRIGGER.search(text)
    if not trigger_match:
        return None

    task_desc = text[trigger_match.end():].strip(" .!?,")
    if not task_desc:
        return None

    assignee_name = trigger_match.group("name")
    if not assignee_name:
        subject_match = _NAMED_SUBJECT.match(task_desc)
        if subject_match:
            assignee_name = subject_match.group(1)

    deadline_text = None
    deadline_match = _TRAILING_DEADLINE.search(task_desc)
    if deadline_match:
        deadline_text = deadline_match.group(1).strip(" .!?,")
        task_desc = task_desc[: deadline_match.start()].strip(" .!?,")

    if not task_desc:
        return None

    assignee_clean = normalize_person_name(assignee_name)
    assignee_user = resolve_assignee(assignee_clean, db) if assignee_clean else None

    new_task = ActionItem(
        meeting_id=meeting_id,
        task=task_desc,
        assignee=assignee_clean,
        assignee_user_id=assignee_user.id if assignee_user else None,
        deadline=deadline_text,
        due_at=parse_deadline(deadline_text),
        status="pending",
        priority="medium",
    )
    db.add(new_task)
    db.flush()

    if assignee_user:
        meeting = db.get(Meeting, meeting_id)
        if meeting:
            notify_task_assigned(db, new_task, meeting)

    db.commit()
    return task_desc


@router.websocket("/ws/meetings/{meeting_id}/live")
async def live_audio_websocket(
    websocket: WebSocket,
    meeting_id: int,
):
    """Real-time streaming audio ingestion and live transcription."""
    await websocket.accept()

    # Authenticate token from query parameters
    token = websocket.query_params.get("token")
    if not token:
        await websocket.send_json({"type": "error", "message": "Authentication token required."})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    db = SessionLocal()
    user = None
    try:
        user = get_user_from_token(token, db)
    except Exception:
        pass

    if not user:
        db.close()
        await websocket.send_json({"type": "error", "message": "Invalid authentication token."})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        db.close()
        await websocket.send_json({"type": "error", "message": "Meeting not found or access denied."})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.send_json({
        "type": "connected",
        "meeting_id": meeting_id,
        "message": "Live audio channel connected. Stream audio chunks.",
    })

    audio_buffer = bytearray()
    chunk_counter = 0
    start_time_offset = 0.0

    try:
        from app.transcription.base import FasterWhisperService
        whisper_service = FasterWhisperService()

        while True:
            # Receive audio chunk (bytes or json text)
            message = await websocket.receive()

            if "bytes" in message and message["bytes"]:
                chunk = message["bytes"]
                audio_buffer.extend(chunk)

                # Process every ~3-5 seconds of buffer or if chunk is sizable
                if len(audio_buffer) >= 32000 * 2:  # ~64KB chunk
                    chunk_counter += 1
                    raw_data = bytes(audio_buffer)
                    audio_buffer.clear()

                    # Write temporary file to decode with faster-whisper
                    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_file:
                        tmp_path = Path(tmp_file.name)
                        tmp_file.write(raw_data)

                    try:
                        res = await whisper_service.transcribe(tmp_path)
                        text = res.full_text.strip()
                        if text:
                            duration = 4.0
                            seg_start = start_time_offset
                            seg_end = start_time_offset + duration
                            start_time_offset = seg_end

                            # Save live segment to DB
                            db_seg = TranscriptSegment(
                                meeting_id=meeting_id,
                                text=text,
                                start_time=seg_start,
                                end_time=seg_end,
                                speaker_label="SPEAKER_LIVE",
                                source="live_mic",
                            )
                            db.add(db_seg)

                            # Append to full transcript
                            current_transcript = meeting.transcript or ""
                            meeting.transcript = f"{current_transcript} {text}".strip()
                            db.commit()

                            # Auto trigger action item detection
                            action_created = _extract_live_actions(text, meeting_id, db)

                            await websocket.send_json({
                                "type": "transcript_segment",
                                "text": text,
                                "speaker": "SPEAKER_LIVE",
                                "start_time": seg_start,
                                "end_time": seg_end,
                                "action_created": action_created,
                            })
                    except Exception as exc:
                        logger.warning("Live chunk transcription error: %s", exc)
                    finally:
                        if tmp_path.exists():
                            try:
                                tmp_path.unlink()
                            except OSError:
                                pass

            elif "text" in message and message["text"]:
                data = json.loads(message["text"])
                if data.get("type") == "stop":
                    await websocket.send_json({
                        "type": "completed",
                        "message": "Live stream completed and saved to transcript.",
                    })
                    break
                elif data.get("type") == "text_segment":
                    # Direct client-side speech recognition text stream fallback
                    live_text = data.get("text", "").strip()
                    if live_text:
                        seg_start = data.get("start_time", start_time_offset)
                        seg_end = data.get("end_time", seg_start + 3.0)
                        start_time_offset = seg_end

                        db_seg = TranscriptSegment(
                            meeting_id=meeting_id,
                            text=live_text,
                            start_time=seg_start,
                            end_time=seg_end,
                            speaker_label=data.get("speaker", "SPEAKER_LIVE"),
                            source="live_mic",
                        )
                        db.add(db_seg)
                        current_transcript = meeting.transcript or ""
                        meeting.transcript = f"{current_transcript} {live_text}".strip()
                        db.commit()

                        action_created = _extract_live_actions(live_text, meeting_id, db)

                        await websocket.send_json({
                            "type": "transcript_segment",
                            "text": live_text,
                            "speaker": data.get("speaker", "SPEAKER_LIVE"),
                            "start_time": seg_start,
                            "end_time": seg_end,
                            "action_created": action_created,
                        })

    except WebSocketDisconnect:
        logger.info("Live audio client disconnected for meeting %d", meeting_id)
    except Exception as exc:
        logger.exception("Live audio websocket exception: %s", exc)
    finally:
        db.close()
