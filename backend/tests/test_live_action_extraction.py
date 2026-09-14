"""A task spoken live, naming who owns it, should assign itself immediately —
not only once the meeting ends and "Generate notes" runs.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Notification
from app.routers.live_transcription import _extract_live_actions

client = TestClient(app)


def _register(first_name: str) -> tuple[dict, dict]:
    tag = uuid.uuid4().hex[:8]
    email = f"{first_name.lower()}-{tag}@example.com"
    # "T{tag}" rather than a bare tag: a name token has to start with a
    # letter for the live-extraction regex to treat it as a name at all
    # (correctly so — a token starting with a digit is never a person's
    # name), and a uuid hex tag starts with a digit about 60% of the time.
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "full_name": f"{first_name} T{tag}"},
    )
    assert res.status_code == 201
    token = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return res.json(), {"Authorization": f"Bearer {token.json()['access_token']}"}


def _meeting(headers: dict) -> int:
    res = client.post("/api/meetings", json={"title": "Live standup"}, headers=headers)
    assert res.status_code == 201
    return res.json()["id"]


def test_a_named_owner_after_the_trigger_phrase_is_assigned_and_notified() -> None:
    owner, owner_headers = _register("Kamran")
    employee, _ = _register("Hamza")
    meeting_id = _meeting(owner_headers)

    with SessionLocal() as db:
        task_desc = _extract_live_actions(
            f"Action item for {employee['full_name']}: send the client the revised proposal by Friday",
            meeting_id=meeting_id,
            db=db,
        )
        assert task_desc == "send the client the revised proposal"

        notifs = list(db.query(Notification).filter(Notification.user_id == employee["id"]).all())
    assert len(notifs) == 1
    assert notifs[0].type == "task_assigned"
    assert "Friday" in notifs[0].body


def test_a_named_subject_before_will_is_assigned() -> None:
    owner, owner_headers = _register("Kamran")
    employee, _ = _register("Nadiya")
    meeting_id = _meeting(owner_headers)

    with SessionLocal() as db:
        task_desc = _extract_live_actions(
            f"task: {employee['full_name']} will update the deployment docs",
            meeting_id=meeting_id,
            db=db,
        )
        notifs = list(db.query(Notification).filter(Notification.user_id == employee["id"]).all())

    # The whole sentence stays the task text (no "for X:" boilerplate to
    # strip) — only the assignee is resolved from the leading name.
    assert task_desc == f"{employee['full_name']} will update the deployment docs"
    assert len(notifs) == 1


def test_deploy_to_staging_is_never_read_as_a_person_named_deploy() -> None:
    """"X to Y" is an ordinary sentence, not "X will Y" — must not misfire."""
    owner, owner_headers = _register("Kamran")
    meeting_id = _meeting(owner_headers)

    with SessionLocal() as db:
        task_desc = _extract_live_actions(
            "Action item: Deploy to staging cluster by 5pm.",
            meeting_id=meeting_id,
            db=db,
        )
    assert task_desc == "Deploy to staging cluster"
