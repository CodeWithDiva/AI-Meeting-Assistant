"""Schemas for transcription endpoints."""

from pydantic import BaseModel


class TranscriptResponse(BaseModel):
    filename: str
    status: str
    transcript: str
