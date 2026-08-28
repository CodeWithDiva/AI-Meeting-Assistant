"""Zoom Meeting Bot Agent Controller."""

import asyncio
import logging
from typing import Any

from app.integrations.zoom.rtms_client import ZoomRTMSClient

logger = logging.getLogger(__name__)


class ZoomBotAgent:
    """Manages autonomous bot joining, streaming, and leaving Zoom meetings."""

    def __init__(self, meeting_id: int, user_id: int, oauth_token: str | None = None) -> None:
        self.meeting_id = meeting_id
        self.user_id = user_id
        self.oauth_token = oauth_token
        self.status = "idle"  # idle -> joining -> listening -> left
        self.client: ZoomRTMSClient | None = None
        self.transcript_buffer: list[str] = []

    async def join_meeting(self, zoom_meeting_url_or_id: str) -> dict[str, Any]:
        """Join a Zoom meeting as an automated assistant bot."""
        self.status = "joining"
        logger.info("Zoom Bot joining meeting %s for user %d...", zoom_meeting_url_or_id, self.user_id)

        async def _handle_audio(chunk: bytes):
            # Pass to live faster-whisper pipeline
            pass

        async def _handle_event(event: dict[str, Any]):
            logger.debug("Zoom RTMS event: %s", event)

        self.client = ZoomRTMSClient(
            meeting_id=self.meeting_id,
            oauth_token=self.oauth_token,
            on_audio_chunk=_handle_audio,
            on_event=_handle_event,
        )

        await self.client.connect()
        self.status = "listening"
        return {
            "status": "listening",
            "meeting_id": self.meeting_id,
            "message": "Zoom bot successfully joined and is listening to live audio.",
        }

    async def leave_meeting(self) -> dict[str, Any]:
        """Leave the Zoom meeting and finalize notes."""
        self.status = "leaving"
        if self.client:
            await self.client.disconnect()
            self.client = None
        self.status = "left"
        return {
            "status": "left",
            "meeting_id": self.meeting_id,
            "message": "Zoom bot left the meeting.",
        }

    def get_status(self) -> dict[str, Any]:
        return {
            "meeting_id": self.meeting_id,
            "status": self.status,
            "is_connected": self.client.is_connected if self.client else False,
        }
