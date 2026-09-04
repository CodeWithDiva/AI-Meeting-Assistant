"""Audio upload and transcription routes."""

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Meeting, TranscriptSegment, User
from app.services.meeting_analysis import analyze_and_persist
from app.schemas.transcription import TranscriptResponse
from app.transcription.base import FasterWhisperService

router = APIRouter(prefix="/api/transcription", tags=["transcription"])

_ALLOWED_AUDIO_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "audio/ogg",
    "audio/flac",
    "audio/x-m4a",
    "audio/m4a",
    "audio/aac",
    "audio/x-aac",
    "audio/3gpp",
    "audio/x-matroska",
    "video/mp4",
    "video/webm",
    "video/ogg",
    "application/octet-stream",
}
_ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".flac", ".aac", ".mp4"}
_MAX_AUDIO_BYTES = 100 * 1024 * 1024
_transcription_service = FasterWhisperService()


async def _transcribe_upload(
    file: UploadFile,
    meeting: Meeting | None = None,
    db: Session | None = None,
) -> TranscriptResponse:
    """Validate, spool, transcribe and optionally persist segments."""
    ext = Path(file.filename or "").suffix.lower()
    if file.content_type not in _ALLOWED_AUDIO_TYPES and ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported audio file type.")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Audio filename is required.")

    with TemporaryDirectory(prefix="meeting-audio-") as tmp_dir:
        audio_path = Path(tmp_dir) / Path(file.filename).name
        size = 0
        with audio_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > _MAX_AUDIO_BYTES:
                    raise HTTPException(status_code=413, detail="Audio file is too large.")
                output.write(chunk)

        try:
            from av.error import InvalidDataError
        except ImportError:
            InvalidDataError = None

        try:
            result = await _transcription_service.transcribe(audio_path)
            segments = result.segments
            full_transcript = result.full_text

            # Apply speaker diarization
            from app.services.diarization import DiarizationService
            diarizer = DiarizationService()
            segments = diarizer.diarize_segments(audio_path, segments)
        except Exception as error:
            if (InvalidDataError and isinstance(error, InvalidDataError)) or "InvalidData" in type(error).__name__:
                raise HTTPException(status_code=422, detail="Audio file could not be decoded.") from error
            if isinstance(error, RuntimeError):
                raise HTTPException(status_code=503, detail=str(error)) from error
            raise

    # Persist segments to DB if a meeting context is provided
    if meeting is not None and db is not None:
        from app.models import Speaker

        # Remove previous segments & speakers for idempotent re-upload
        db.query(TranscriptSegment).filter(
            TranscriptSegment.meeting_id == meeting.id
        ).delete()
        db.query(Speaker).filter(
            Speaker.meeting_id == meeting.id
        ).delete()

        detected_speakers = set()
        for seg in segments:
            lbl = getattr(seg, "speaker_label", None) or "SPEAKER_00"
            detected_speakers.add(lbl)
            db.add(
                TranscriptSegment(
                    meeting_id=meeting.id,
                    text=seg.text,
                    start_time=seg.start,
                    end_time=seg.end,
                    speaker_label=lbl,
                    source="upload",
                )
            )

        for spk_label in sorted(detected_speakers):
            db.add(
                Speaker(
                    meeting_id=meeting.id,
                    speaker_label=spk_label,
                    display_name=spk_label,
                )
            )

        meeting.transcript = full_transcript
        db.commit()
        await analyze_and_persist(meeting.id, db)

    return TranscriptResponse(
        filename=file.filename,
        status="completed",
        transcript=full_transcript,
        segment_count=len(segments),
    )


@router.post("/upload", response_model=TranscriptResponse)
async def upload_audio(file: UploadFile = File(...)) -> TranscriptResponse:
    """Accept an audio file and return a transcript (no DB persistence)."""
    return await _transcribe_upload(file)


@router.post("/upload/{meeting_id}", response_model=TranscriptResponse)
async def upload_audio_for_meeting(
    meeting_id: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranscriptResponse:
    """Transcribe audio, save segments, and persist transcript on an owned meeting."""
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    return await _transcribe_upload(file, meeting=meeting, db=db)
