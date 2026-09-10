"""Parse any pasted meeting link into the details the browser bot needs.

The whole product promise is "paste a link and the agent shows up", so this
module is the single place that turns whatever the user pasted — a bare Zoom
ID, a full invite URL, a Google Meet code — into a normalized
:class:`MeetingLink`. Routers and bots never sniff URLs themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

ZOOM = "zoom"
MEET = "google_meet"

SUPPORTED_PLATFORMS = (ZOOM, MEET)

# Google Meet codes look like "abc-defg-hij".
_MEET_CODE = re.compile(r"\b([a-z]{3,4}-[a-z]{3,4}-[a-z]{3,4})\b", re.IGNORECASE)
_ZOOM_PATH_ID = (
    re.compile(r"/j/(\d+)"),
    re.compile(r"/wc/join/(\d+)"),
    re.compile(r"/wc/(\d+)/join"),
    re.compile(r"/s/(\d+)"),
)


class UnsupportedMeetingLinkError(ValueError):
    """Raised when a pasted link is not a Zoom or Google Meet meeting."""


@dataclass(frozen=True)
class MeetingLink:
    """A pasted meeting link, resolved into everything a bot needs to join."""

    platform: str
    join_url: str
    meeting_code: str
    password: str | None = None

    @property
    def display_title(self) -> str:
        """A sensible default meeting title when the user did not supply one."""
        label = "Zoom" if self.platform == ZOOM else "Google Meet"
        return f"{label} meeting {self.meeting_code}"


def parse_meeting_link(raw: str) -> MeetingLink:
    """Resolve a pasted link (or bare ID/code) into a :class:`MeetingLink`.

    Accepts, among others::

        1234567890
        https://us02web.zoom.us/j/1234567890?pwd=abc123
        https://app.zoom.us/wc/1234567890/join
        abc-defg-hij
        https://meet.google.com/abc-defg-hij

    Raises:
        UnsupportedMeetingLinkError: the text is neither Zoom nor Google Meet.
    """
    candidate = (raw or "").strip()
    if not candidate:
        raise UnsupportedMeetingLinkError("No meeting link was provided.")

    parsed = urlparse(candidate if "//" in candidate else f"//{candidate}", scheme="https")
    host = (parsed.hostname or "").lower()

    if "zoom" in host:
        return _zoom_link(parsed.path, parsed.query)
    if "meet.google.com" in host or "meet.google" in host:
        return _meet_link(parsed.path)

    # No recognizable host — fall back to the shape of the text itself, so a
    # bare Zoom ID or a bare Meet code still works.
    if candidate.replace(" ", "").replace("-", "").isdigit():
        return _zoom_link(f"/j/{re.sub(r'[^0-9]', '', candidate)}", "")
    meet_code = _MEET_CODE.search(candidate)
    if meet_code:
        return _meet_link(f"/{meet_code.group(1)}")

    raise UnsupportedMeetingLinkError(
        "Only Zoom and Google Meet links are supported. "
        "Paste a link like https://zoom.us/j/1234567890 or https://meet.google.com/abc-defg-hij."
    )


def _zoom_link(path: str, query: str) -> MeetingLink:
    meeting_number = ""
    for pattern in _ZOOM_PATH_ID:
        match = pattern.search(path)
        if match:
            meeting_number = match.group(1)
            break
    if not meeting_number:
        meeting_number = re.sub(r"\D", "", path)
    if not meeting_number:
        raise UnsupportedMeetingLinkError("Could not find a Zoom meeting ID in that link.")

    password = (parse_qs(query).get("pwd") or [None])[0]
    # app.zoom.us/wc/<id>/join is the Web Client entry point that skips the
    # "download the app" landing page, which is what the bot must land on.
    join_url = f"https://app.zoom.us/wc/{meeting_number}/join"
    if password:
        join_url = f"{join_url}?pwd={password}"
    return MeetingLink(
        platform=ZOOM,
        join_url=join_url,
        meeting_code=meeting_number,
        password=password,
    )


def _meet_link(path: str) -> MeetingLink:
    match = _MEET_CODE.search(path)
    if not match:
        raise UnsupportedMeetingLinkError("Could not find a Google Meet code in that link.")
    code = match.group(1).lower()
    return MeetingLink(
        platform=MEET,
        join_url=f"https://meet.google.com/{code}",
        meeting_code=code,
    )
