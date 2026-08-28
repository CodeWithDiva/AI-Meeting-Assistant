"""WebSocket Real-Time Live Microphone Transcription Router."""

import asyncio
import io
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.auth import get_user_from_token
from app.database import SessionLocal
from app.models import ActionItem, Meeting, TranscriptSegment

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live_transcription"])


def _extract_live_actions(text: str, meeting_id: int, db: Any):
    """Detect live verbal trigger phrases and auto-create action items."""
    lower_text = text.lower()
    trigger_phrases = ["action item:", "take a note:", "todo:", "task:", "note that"]
    for phrase in trigger_phrases:
        if phrase in lower_text:
            task_desc = text[lower_text.find(phrase) + len(phrase):].strip(" .!?,")
            if task_desc:
                new_task = ActionItem(
                    meeting_id=meeting_id,
                    task=task_desc,
                    status="pending",
                )
                db.add(new_task)
                db.commit()
                return task_desc
    return None


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
