"""Turn a spoken or typed deadline into a real point in time.

Deadlines arrive as free text — the LLM copies whatever was said ("Friday",
"kal tak", "agle hafte", "15 March 5 PM") and people type the same kind of
thing into the task form. Reminders and overdue alerts need an actual
datetime, so this module resolves that text against "now".

It is deliberately conservative: text it cannot read confidently returns
None and the task simply has no reminder, rather than a reminder firing on a
guessed date. The original text is always kept on the task for display.

Resolution happens in the server's local timezone (the machine the meeting
assistant runs on, where "5 PM" means 5 PM) and the result is returned as a
naive UTC datetime, matching every other timestamp in the database.
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta, timezone

# When only a day is given, the task is due at the end of that day.
_DEFAULT_HOUR = 23
_DEFAULT_MINUTE = 59

_WEEKDAYS = {
    "monday": 0, "mon": 0, "peer": 0, "pir": 0, "somwar": 0,
    "tuesday": 1, "tue": 1, "tues": 1, "mangal": 1, "mangalwar": 1,
    "wednesday": 2, "wed": 2, "budh": 2, "budhwar": 2,
    "thursday": 3, "thu": 3, "thurs": 3, "jumerat": 3, "jumeraat": 3,
    "friday": 4, "fri": 4, "juma": 4, "jumma": 4, "jummah": 4,
    "saturday": 5, "sat": 5, "sanichar": 5,
    "sunday": 6, "sun": 6, "itwar": 6, "itwaar": 6, "etwar": 6,
}
_MONTHS = {
    **{name.lower(): index for index, name in enumerate(calendar.month_name) if name},
    **{name.lower(): index for index, name in enumerate(calendar.month_abbr) if name},
    "sept": 9,
}
_NEXT_WORDS = {"next", "agle", "agla", "agli"}

_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})(?:[t\s]+(\d{1,2}):(\d{2}))?")
_DMY = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b")
_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3,9})\b(?:,?\s+(\d{4}))?")
_MONTH_DAY = re.compile(r"\b([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?")
_TIME_12 = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)")
_TIME_24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_TIME_BAJE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*baje\b")
_EVENING = re.compile(r"\b(shaam|sham|raat|dopahar|dopehar|evening|night)\b")
_IN_UNITS = re.compile(
    r"\b(?:in\s+)?(\d{1,3})\s*(days?|din|hours?|hrs?|ghante|ghanta|ghanton|weeks?|hafte|hafton)\b"
)


def parse_deadline(text: str | None, now: datetime | None = None) -> datetime | None:
    """Resolve deadline text to a naive-UTC datetime, or None if unreadable.

    `now` is an aware datetime in the timezone the text was spoken in; it
    defaults to the server's local time and exists so tests can pin it.
    """
    if not text or not text.strip():
        return None
    local_now = now or datetime.now().astimezone()
    if local_now.tzinfo is None:
        local_now = local_now.astimezone()
    lowered = " ".join(text.casefold().split())

    day = _resolve_day(lowered, local_now)
    hour, minute = _resolve_time(lowered)

    if day is None:
        relative = _IN_UNITS.search(lowered)
        if relative:
            amount, unit = int(relative.group(1)), relative.group(2)
            if unit.startswith(("hour", "hr", "ghant")):
                return _to_utc(local_now + timedelta(hours=amount))
            if unit.startswith(("week", "haft")):
                day = local_now + timedelta(weeks=amount)
            else:
                day = local_now + timedelta(days=amount)
        elif hour is not None:
            # "5 PM" on its own means today, or tomorrow if that has passed.
            candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= local_now:
                candidate += timedelta(days=1)
            return _to_utc(candidate)
        else:
            return None

    resolved = day.replace(
        hour=_DEFAULT_HOUR if hour is None else hour,
        minute=_DEFAULT_MINUTE if hour is None else minute,
        second=0,
        microsecond=0,
    )
    return _to_utc(resolved)


def _resolve_day(text: str, now: datetime) -> datetime | None:
    iso = _ISO.search(text)
    if iso:
        return _safe_date(now, int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    dmy = _DMY.search(text)
    if dmy:
        # Day first, the way dates are written in Pakistan.
        day, month, year = (int(dmy.group(i)) for i in (1, 2, 3))
        return _safe_date(now, year + 2000 if year < 100 else year, month, day)

    for pattern, day_group, month_group in ((_DAY_MONTH, 1, 2), (_MONTH_DAY, 2, 1)):
        for match in pattern.finditer(text):
            month = _MONTHS.get(match.group(month_group))
            if not month:
                continue
            day = int(match.group(day_group))
            year = int(match.group(3)) if match.group(3) else now.year
            candidate = _safe_date(now, year, month, day)
            if candidate and not match.group(3) and candidate.date() < now.date():
                candidate = _safe_date(now, year + 1, month, day)
            return candidate

    words = re.findall(r"[a-z]+", text)
    word_set = set(words)
    if word_set & {"today", "aaj", "tonight", "eod"}:
        return now
    if {"day", "after", "tomorrow"} <= word_set or word_set & {"parson", "parsoon"}:
        return now + timedelta(days=2)
    if word_set & {"tomorrow", "tmrw", "tomorow", "kal"}:
        return now + timedelta(days=1)
    if {"end", "month"} <= word_set or "month-end" in text:
        return now.replace(day=calendar.monthrange(now.year, now.month)[1])
    if word_set & _NEXT_WORDS and word_set & {"month", "mahine", "mahina"}:
        return now + timedelta(days=30)
    if {"end", "week"} <= word_set or "this week" in text or "is hafte" in text:
        return _next_weekday(now, 4, allow_today=True)

    weekday = next((_WEEKDAYS[w] for w in words if w in _WEEKDAYS), None)
    if word_set & _NEXT_WORDS and word_set & {"week", "hafte", "hafta"}:
        if weekday is not None:
            # "next week Monday" — that weekday within the coming Mon–Sun week.
            next_monday = now + timedelta(days=7 - now.weekday())
            return next_monday + timedelta(days=weekday)
        return now + timedelta(days=7)
    if weekday is not None:
        return _next_weekday(now, weekday, allow_today=True)
    return None


def _resolve_time(text: str) -> tuple[int | None, int]:
    iso = _ISO.search(text)
    if iso and iso.group(4):
        return _valid_time(int(iso.group(4)), int(iso.group(5)))

    match = _TIME_12.search(text)
    if match:
        hour = int(match.group(1)) % 12
        if match.group(3).startswith("p"):
            hour += 12
        return _valid_time(hour, int(match.group(2) or 0))

    match = _TIME_BAJE.search(text)
    if match:
        hour = int(match.group(1))
        # "shaam 5 baje" / "raat 9 baje" are afternoon or evening hours.
        if hour < 12 and _EVENING.search(text):
            hour += 12
        return _valid_time(hour, int(match.group(2) or 0))

    if not iso:
        match = _TIME_24.search(text)
        if match:
            return _valid_time(int(match.group(1)), int(match.group(2)))
    if re.search(r"\bnoon\b", text):
        return 12, 0
    return None, 0


def _valid_time(hour: int, minute: int) -> tuple[int | None, int]:
    if 0 <= hour < 24 and 0 <= minute < 60:
        return hour, minute
    return None, 0


def _next_weekday(now: datetime, weekday: int, *, allow_today: bool) -> datetime:
    ahead = (weekday - now.weekday()) % 7
    if ahead == 0 and not allow_today:
        ahead = 7
    return now + timedelta(days=ahead)


def _safe_date(now: datetime, year: int, month: int, day: int) -> datetime | None:
    try:
        return now.replace(year=year, month=month, day=day)
    except ValueError:
        return None


def _to_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def format_due(due_at: datetime | None) -> str | None:
    """Readable local time for a naive-UTC due date, e.g. 'Fri 12 Sep 2026, 5:00 PM'."""
    if due_at is None:
        return None
    local = due_at.replace(tzinfo=timezone.utc).astimezone()
    if local.hour == _DEFAULT_HOUR and local.minute == _DEFAULT_MINUTE:
        return local.strftime("%a %d %b %Y")
    return f"{local.strftime('%a %d %b %Y')}, {local.strftime('%I:%M %p').lstrip('0')}"
