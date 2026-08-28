"""Contract for structured meeting analysis providers."""

from typing import Protocol


class AIService(Protocol):
    async def analyze_meeting(self, transcript: str) -> dict[str, object]:
        """Return structured notes for a transcript."""
