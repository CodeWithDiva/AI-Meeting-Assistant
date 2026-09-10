"""Tests for turning extracted action items into assigned, notified tasks."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ActionItem, Meeting, Notification, User
from app.services.action_items import (
    normalize_person_name,
    persist_meeting_notes,
    resolve_assignee,
)


@pytest.fixture()
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def team(db):
    """An owner plus two teammates, isolated from other tests by a unique tag."""
    tag = uuid.uuid4().hex[:8]
    owner = User(email=f"owner-{tag}@example.com", password_hash="x", full_name=f"Owner {tag}")
    ali = User(email=f"ali-{tag}@example.com", password_hash="x", full_name=f"Ali Khan{tag}")
    sara = User(email=f"sara-{tag}@example.com", password_hash="x", full_name=f"Sara Ahmed{tag}")
    db.add_all([owner, ali, sara])
    db.flush()
    meeting = Meeting(owner_id=owner.id, title="Sprint sync", platform="zoom")
    db.add(meeting)
    db.commit()
    yield {"tag": tag, "owner": owner, "ali": ali, "sara": sara, "meeting": meeting}
    db.query(Notification).filter(Notification.meeting_id == meeting.id).delete()
    db.query(ActionItem).filter(ActionItem.meeting_id == meeting.id).delete()
    db.delete(meeting)
    for user in (owner, ali, sara):
        db.delete(user)
    db.commit()


# ── Name cleaning ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ali", "Ali"),
        ("  Ali  ", "Ali"),
        ("Mr. Ali", "Ali"),
        ("Ali sahab", "Ali"),
        ("sir Ali", "Ali"),
        ("علی صاحب", "علی"),
        ("'Ali'", "Ali"),
    ],
)
def test_honorifics_are_stripped(raw: str, expected: str) -> None:
    assert normalize_person_name(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "team", "everyone", "TBD", "unassigned"])
def test_non_people_are_rejected(raw) -> None:
    assert normalize_person_name(raw) is None


def test_an_all_honorific_string_keeps_its_words() -> None:
    # Stripping everything would silently produce None; keep the original.
    assert normalize_person_name("sahab") == "sahab"


# ── Assignee resolution ─────────────────────────────────────────────────


def test_a_full_name_resolves(db, team) -> None:
    assert resolve_assignee(team["ali"].full_name, db).id == team["ali"].id


def test_an_email_resolves(db, team) -> None:
    assert resolve_assignee(team["sara"].email, db).id == team["sara"].id


def test_a_first_name_resolves_to_the_full_name(db, team) -> None:
    assert resolve_assignee(f"Ali Khan{team['tag']}", db).id == team["ali"].id


def test_an_unknown_name_stays_unresolved(db, team) -> None:
    assert resolve_assignee("Someone Nobody Knows", db) is None


def test_a_partial_word_does_not_match(db, team) -> None:
    # "Ali" must never match "Alina" — whole tokens only.
    assert resolve_assignee("Al", db) is None


def test_an_ambiguous_first_name_is_left_unassigned(db) -> None:
    tag = uuid.uuid4().hex[:8]
    first = User(email=f"a-{tag}@example.com", password_hash="x", full_name=f"Ali {tag}one")
    second = User(email=f"b-{tag}@example.com", password_hash="x", full_name=f"Ali {tag}two")
    db.add_all([first, second])
    db.commit()
    try:
        # Two people share the token — assigning to either would be a guess.
        assert resolve_assignee("Ali", db) is None
    finally:
        db.delete(first)
        db.delete(second)
        db.commit()


# ── Persisting notes ────────────────────────────────────────────────────


def test_tasks_are_linked_to_users_and_notified(db, team) -> None:
    report = persist_meeting_notes(
        team["meeting"].id,
        {
            "summary": "We planned the sprint.",
            "decisions": ["Ship on Monday."],
            "action_items": [
                {"assignee": team["ali"].full_name, "task": "Write the release notes",
                 "deadline": "Friday", "assigned_by": "Owner"},
                {"assignee": "Ghost Person", "task": "Unknown owner task"},
            ],
        },
        db,
    )
    db.commit()

    assert report == {"decisions": 1, "action_items": 2, "assigned": 1, "unassigned": 1}

    items = list(db.scalars(
        select(ActionItem).where(ActionItem.meeting_id == team["meeting"].id)
    ))
    assigned = next(i for i in items if i.assignee_user_id)
    assert assigned.assignee_user_id == team["ali"].id
    assert assigned.deadline == "Friday"

    notifications = list(db.scalars(
        select(Notification).where(
            Notification.meeting_id == team["meeting"].id,
            Notification.type == "task_assigned",
        )
    ))
    assert len(notifications) == 1
    assert notifications[0].user_id == team["ali"].id
    assert "Friday" in notifications[0].body


def test_the_owner_is_not_notified_about_their_own_task(db, team) -> None:
    persist_meeting_notes(
        team["meeting"].id,
        {"summary": "s", "decisions": [],
         "action_items": [{"assignee": team["owner"].full_name, "task": "Book the room"}]},
        db,
    )
    db.commit()

    task_notifications = db.scalars(
        select(Notification).where(
            Notification.meeting_id == team["meeting"].id,
            Notification.type == "task_assigned",
        )
    ).all()
    assert task_notifications == []


def test_reanalysis_replaces_rather_than_duplicates(db, team) -> None:
    notes = {"summary": "s", "decisions": ["D1"],
             "action_items": [{"assignee": team["ali"].full_name, "task": "Task one"}]}
    persist_meeting_notes(team["meeting"].id, notes, db)
    db.commit()
    persist_meeting_notes(team["meeting"].id, notes, db)
    db.commit()

    items = db.scalars(
        select(ActionItem).where(ActionItem.meeting_id == team["meeting"].id)
    ).all()
    assert len(items) == 1


def test_empty_tasks_are_dropped(db, team) -> None:
    report = persist_meeting_notes(
        team["meeting"].id,
        {"summary": "s", "decisions": [], "action_items": [{"assignee": "Ali", "task": "   "}]},
        db,
    )
    db.commit()
    assert report["action_items"] == 0


def test_the_summary_notification_reports_what_was_extracted(db, team) -> None:
    persist_meeting_notes(
        team["meeting"].id,
        {"summary": "s", "decisions": ["D1", "D2"],
         "action_items": [{"assignee": team["sara"].full_name, "task": "Send the deck"}]},
        db,
        notify_summary=True,
    )
    db.commit()

    summary_note = db.scalar(
        select(Notification).where(
            Notification.meeting_id == team["meeting"].id,
            Notification.type == "summary_ready",
        )
    )
    assert summary_note.user_id == team["owner"].id
    assert "2 decision(s)" in summary_note.body
    assert "1 assigned automatically" in summary_note.body
    # Finishing a meeting is what marks it ended.
    db.refresh(team["meeting"])
    assert team["meeting"].ended_at is not None
