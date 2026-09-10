"""Per-platform join strategies for the browser meeting bot.

Adding a platform means adding one module here and one entry in
:data:`_STRATEGIES` — nothing in the bot, the routers or the frontend needs to
change.
"""

from __future__ import annotations

from app.agents.meeting_link import MEET, ZOOM
from app.agents.platforms.base import JoinFailedError, JoinStrategy
from app.agents.platforms.google_meet import GoogleMeetJoinStrategy
from app.agents.platforms.zoom import ZoomJoinStrategy

_STRATEGIES = {
    ZOOM: ZoomJoinStrategy,
    MEET: GoogleMeetJoinStrategy,
}

__all__ = ["JoinFailedError", "JoinStrategy", "get_strategy"]


def get_strategy(platform: str, join_timeout_ms: int, ui_timeout_ms: int) -> JoinStrategy:
    """Return the join strategy for a platform key from `meeting_link`."""
    try:
        factory = _STRATEGIES[platform]
    except KeyError as error:
        raise ValueError(f"No meeting bot is implemented for platform {platform!r}.") from error
    return factory(join_timeout_ms=join_timeout_ms, ui_timeout_ms=ui_timeout_ms)
