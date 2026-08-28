"""Text-to-Speech (TTS) endpoints for voice synthesis."""

import base64
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Meeting, User
from app.services.tts import TTSService

router = APIRouter(prefix="/api/meetings/{meeting_id}/tts", tags=["tts"])


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class SpeakResponse(BaseModel):
    text: str
    audio_base64: str
    content_type: str = "audio/wav"


@router.post("/speak", response_model=SpeakResponse)
def synthesize_speech(
    meeting_id: int,
    request: SpeakRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SpeakResponse:
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    tts = TTSService()
    wav_bytes = tts.synthesize_speech_wav(request.text)
    b64_audio = base64.b64encode(wav_bytes).decode("utf-8")

    return SpeakResponse(
        text=request.text,
        audio_base64=b64_audio,
        content_type="audio/wav",
    )
