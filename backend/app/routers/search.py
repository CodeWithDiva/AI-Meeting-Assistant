"""Semantic search router for meetings."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Meeting, TranscriptSegment, User
from app.services.embeddings import SearchResult, SemanticSearchService

router = APIRouter(prefix="/api/meetings/{meeting_id}/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    limit: int = 10


class SearchItemResponse(BaseModel):
    segment_id: int
    text: str
    speaker_label: str | None
    start_time: float
    end_time: float
    score: float


class SearchResponse(BaseModel):
    query: str
    total_matches: int
    results: list[SearchItemResponse]


@router.post("", response_model=SearchResponse)
def search_meeting_transcript(
    meeting_id: int,
    request: SearchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SearchResponse:
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.owner_id == user.id)
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    segments = list(
        db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.start_time)
        )
    )

    searcher = SemanticSearchService()
    results = searcher.search_segments(request.query, segments, limit=request.limit)

    return SearchResponse(
        query=request.query,
        total_matches=len(results),
        results=[
            SearchItemResponse(
                segment_id=r.segment_id,
                text=r.text,
                speaker_label=r.speaker_label,
                start_time=r.start_time,
                end_time=r.end_time,
                score=r.score,
            )
            for r in results
        ],
    )
