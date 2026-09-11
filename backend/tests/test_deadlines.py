"""Tests for resolving spoken / typed deadlines into real due dates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.deadlines import parse_deadline

PKT = timezone(timedelta(hours=5))
# Wednesday 9 September 2026, 10:00 in Pakistan.
NOW = datetime(2026, 9, 9, 10, 0, tzinfo=PKT)


def local(result: datetime | None) -> tuple[int, int, int, int, int] | None:
    if result is None:
        return None
    moment = result.replace(tzinfo=timezone.utc).astimezone(PKT)
    return (moment.year, moment.month, moment.day, moment.hour, moment.minute)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Friday", (2026, 9, 11, 23, 59)),
        ("by Friday 5 PM", (2026, 9, 11, 17, 0)),
        ("juma tak", (2026, 9, 11, 23, 59)),
        ("wednesday", (2026, 9, 9, 23, 59)),
        ("kal tak", (2026, 9, 10, 23, 59)),
        ("tomorrow 11am", (2026, 9, 10, 11, 0)),
        ("parson", (2026, 9, 11, 23, 59)),
        ("aaj shaam 6 baje", (2026, 9, 9, 18, 0)),
        ("today", (2026, 9, 9, 23, 59)),
        ("next week", (2026, 9, 16, 23, 59)),
        ("agle hafte", (2026, 9, 16, 23, 59)),
        ("next week Monday", (2026, 9, 14, 23, 59)),
        ("agle hafte jumma", (2026, 9, 18, 23, 59)),
        ("in 3 days", (2026, 9, 12, 23, 59)),
        ("2 ghante", (2026, 9, 9, 12, 0)),
        ("end of month", (2026, 9, 30, 23, 59)),
        ("end of the week", (2026, 9, 11, 23, 59)),
        ("15 March", (2027, 3, 15, 23, 59)),
        ("September 20th", (2026, 9, 20, 23, 59)),
        ("2026-09-20", (2026, 9, 20, 23, 59)),
        ("2026-09-20 14:30", (2026, 9, 20, 14, 30)),
        ("20/09/2026", (2026, 9, 20, 23, 59)),
        ("5 pm", (2026, 9, 9, 17, 0)),
        ("9 am", (2026, 9, 10, 9, 0)),
    ],
)
def test_deadline_text_resolves_to_a_date(text: str, expected) -> None:
    assert local(parse_deadline(text, now=NOW)) == expected


@pytest.mark.parametrize("text", [None, "", "   ", "ASAP", "jaldi", "soon", "when possible"])
def test_unreadable_deadlines_are_left_unset(text) -> None:
    assert parse_deadline(text, now=NOW) is None


def test_result_is_naive_utc() -> None:
    result = parse_deadline("Friday 5 PM", now=NOW)
    assert result is not None and result.tzinfo is None
    assert result == datetime(2026, 9, 11, 12, 0)
