"""Meeting transcript analysis routes."""

from fastapi import APIRouter

from app.ai.service import analyze_meeting
from app.schemas.analysis import MeetingNotesRequest, MeetingNotesResponse

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.post("/notes", response_model=MeetingNotesResponse)
async def create_meeting_notes(request: MeetingNotesRequest) -> MeetingNotesResponse:
    """Generate summary, decisions, and action items from a transcript."""
    result = await analyze_meeting(request.transcript)
    return MeetingNotesResponse.model_validate(result)
