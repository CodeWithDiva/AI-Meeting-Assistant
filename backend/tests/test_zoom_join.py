"""Tests for ZoomJoinStrategy's pre-join camera handling.

Measured live: leaving the pre-join camera preview on meant Zoom's own
"Close those apps and try again" media error appeared whenever anything else
on the machine held the webcam, and the Join button spun forever — the join
never completed and looked identical to a plain hang. This bot never sends
video, so `_turn_off_video_preview` stops the preview before Join is ever
clicked, and these tests exercise it against a fake Playwright frame (no
browser needed) since the rest of the join flow needs a real page to drive.
"""

from __future__ import annotations

import asyncio

from app.agents.platforms.zoom import ZoomJoinStrategy


class _FakeLocator:
    def __init__(self, visible: bool, clicks: list[str], label: str) -> None:
        self._visible = visible
        self._clicks = clicks
        self._label = label
        self.first = self

    async def is_visible(self) -> bool:
        return self._visible

    async def click(self) -> None:
        self._clicks.append(self._label)


class _FakeFrame:
    """Just enough of Playwright's Frame API for click_if_visible to work."""

    def __init__(self, button_text: str | None, clicks: list[str]) -> None:
        self._button_text = button_text
        self._clicks = clicks

    def get_by_role(self, role: str, name=None):  # noqa: ANN001
        matches = bool(self._button_text and name and name.search(self._button_text))
        return _FakeLocator(matches, self._clicks, self._button_text or "")

    def get_by_text(self, pattern):  # noqa: ANN001
        matches = bool(self._button_text and pattern.search(self._button_text))
        return _FakeLocator(matches, self._clicks, self._button_text or "")


def test_turns_off_video_preview_when_the_stop_video_button_is_present():
    clicks: list[str] = []
    frame = _FakeFrame("Stop Video", clicks)
    strategy = ZoomJoinStrategy(join_timeout_ms=1000, ui_timeout_ms=1000)

    asyncio.run(strategy._turn_off_video_preview(frame))

    assert clicks == ["Stop Video"]


def test_does_nothing_when_there_is_no_video_preview_control():
    clicks: list[str] = []
    frame = _FakeFrame(None, clicks)
    strategy = ZoomJoinStrategy(join_timeout_ms=1000, ui_timeout_ms=1000)

    # Must not raise even though nothing matches.
    asyncio.run(strategy._turn_off_video_preview(frame))

    assert clicks == []
