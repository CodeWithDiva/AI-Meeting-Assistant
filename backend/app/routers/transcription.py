"""Audio upload and transcription routes."""

from pathlib import Path
from tempfile import TemporaryDirectory

from av.error import InvalidDataError
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Meeting, User
from app.schemas.transcription import TranscriptResponse
from app.transcription.base import FasterWhisperService

router = APIRouter(prefix="/api/transcription", tags=["transcription"])

_ALLOWED_AUDIO_TYPES = {
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "audio/ogg",
}
_MAX_AUDIO_BYTES = 100 * 1024 * 1024
_transcription_service = FasterWhisperService()


async def _transcribe_upload(file: UploadFile) -> TranscriptResponse:
    """Validate, spool, and transcribe one uploaded audio file."""
    if file.content_type not in _ALLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio file type.")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Audio filename is required.")

    with TemporaryDirectory(prefix="meeting-audio-") as temporary_directory:
        audio_path = Path(temporary_directory) / Path(file.filename).name
        size = 0
        with audio_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > _MAX_AUDIO_BYTES:
                    raise HTTPException(status_code=413, detail="Audio file is too large.")
                output.write(chunk)

        try:
            transcript = await _transcription_service.transcribe(audio_path)
        except InvalidDataError as error:
            raise HTTPException(status_code=422, detail="Audio file could not be decoded.") from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    return TranscriptResponse(filename=file.filename, status="completed", transcript=transcript)


@router.post("/upload", response_model=TranscriptResponse)
async def upload_audio(file: UploadFile = File(...)) -> TranscriptResponse:
    """Accept an audio file and return a transcript when a provider is configured."""
    return await _transcribe_upload(file)


@router.post("/upload/{meeting_id}", response_model=TranscriptResponse)
async def upload_audio_for_meeting(
    meeting_id: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranscriptResponse:
    """Transcribe audio and persist its transcript on an owned meeting."""
    meeting = db.scalar(select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id))
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    result = await _transcribe_upload(file)
    meeting.transcript = result.transcript
    db.commit()
    return result
