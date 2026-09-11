"""End-to-end: assigning a task notifies the employee, who can then work on it."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import ActionItem, Notification
from app.services.notifier import run_deadline_sweep

client = TestClient(app)


def _member(first_name: str) -> tuple[dict, dict]:
    """Register someone with a unique full name, so name matching in other tests is unaffected."""
    tag = uuid.uuid4().hex[:8]
    registered = client.post(
        "/api/auth/register",
        json={
            "email": f"{first_name.lower()}-{tag}@example.com",
            "password": "password123",
            "full_name": f"{first_name} T{tag}",
        },
    )
    assert registered.status_code == 201
    assert registered.json()["full_name"] == f"{first_name} T{tag}"
    token = client.post(
        "/api/auth/login",
        json={"email": registered.json()["email"], "password": "password123"},
    )
    return registered.json(), {"Authorization": f"Bearer {token.json()['access_token']}"}


def test_assigned_task_reaches_the_employee_with_its_deadline() -> None:
    _, owner_headers = _member("Kamran")
    employee, employee_headers = _member("Hamza")

    meeting = client.post(
        "/api/meetings", json={"title": "Launch planning", "platform": "google_meet"},
        headers=owner_headers,
    ).json()

    created = client.post(
        f"/api/tasks/meeting/{meeting['id']}",
        json={
            "task": "Send the revised launch timeline",
            "assignee_user_id": employee["id"],
            "deadline": "Friday 5 PM",
            "priority": "high",
        },
        headers=owner_headers,
    )
    assert created.status_code == 201
    task = created.json()
    assert task["assignee"] == employee["full_name"]
    assert task["priority"] == "high"
    assert task["due_at"] is not None
    assert task["meeting_title"] == "Launch planning"

    # The employee is notified, with the deadline in the message.
    inbox = client.get("/api/notifications", headers=employee_headers).json()
    assigned = [n for n in inbox if n["type"] == "task_assigned"]
    assert len(assigned) == 1
    assert "Send the revised launch timeline" in assigned[0]["body"]
    assert "Due Friday 5 PM" in assigned[0]["body"]
    assert client.get("/api/notifications/unread-count", headers=employee_headers).json()["unread"] >= 1

    # It shows on their own task list even though the meeting is not theirs.
    mine = client.get("/api/tasks?scope=assigned", headers=employee_headers).json()
    assert [t["id"] for t in mine] == [task["id"]]

    # They may move it along, but not rewrite it.
    assert client.patch(
        f"/api/tasks/{task['id']}", json={"task": "Something else"}, headers=employee_headers
    ).status_code == 403
    done = client.patch(f"/api/tasks/{task['id']}", json={"status": "done"}, headers=employee_headers)
    assert done.status_code == 200
    assert done.json()["completed_at"] is not None

    # The owner hears that it was finished.
    owner_inbox = client.get("/api/notifications", headers=owner_headers).json()
    assert any(n["type"] == "task_completed" for n in owner_inbox)

    ics = client.get(f"/api/tasks/{task['id']}/calendar.ics", headers=employee_headers)
    assert ics.status_code == 200
    assert "BEGIN:VEVENT" in ics.text

    # A stranger cannot see the task at all.
    _, stranger_headers = _member("Faraz")
    assert client.get(f"/api/tasks/{task['id']}", headers=stranger_headers).status_code == 404


def test_reassigning_and_changing_the_deadline_notify_the_assignee() -> None:
    _, owner_headers = _member("Kamran")
    first, _ = _member("Nadia")
    second, second_headers = _member("Bilal")
    meeting = client.post("/api/meetings", json={"title": "Ops sync"}, headers=owner_headers).json()

    task = client.post(
        f"/api/tasks/meeting/{meeting['id']}",
        json={"task": "Renew the SSL certificate", "assignee_user_id": first["id"]},
        headers=owner_headers,
    ).json()

    moved = client.patch(
        f"/api/tasks/{task['id']}", json={"assignee_user_id": second["id"]}, headers=owner_headers
    )
    assert moved.status_code == 200 and moved.json()["assignee"] == second["full_name"]
    assert any(
        n["type"] == "task_assigned"
        for n in client.get("/api/notifications", headers=second_headers).json()
    )

    rescheduled = client.patch(
        f"/api/tasks/{task['id']}", json={"deadline": "kal tak"}, headers=owner_headers
    )
    assert rescheduled.status_code == 200 and rescheduled.json()["due_at"] is not None
    assert any(
        n["type"] == "deadline_changed"
        for n in client.get("/api/notifications", headers=second_headers).json()
    )


def test_deadline_sweep_reminds_then_flags_overdue_exactly_once() -> None:
    owner, owner_headers = _member("Kamran")
    employee, employee_headers = _member("Ayesha")
    meeting = client.post("/api/meetings", json={"title": "Finance review"}, headers=owner_headers).json()
    task = client.post(
        f"/api/tasks/meeting/{meeting['id']}",
        json={"task": "Close the Q3 books", "assignee_user_id": employee["id"], "deadline": "tomorrow"},
        headers=owner_headers,
    ).json()

    def alerts(kind: str, user_id: int) -> int:
        with SessionLocal() as db:
            return len(list(db.scalars(select(Notification).where(
                Notification.meeting_id == meeting["id"],
                Notification.user_id == user_id,
                Notification.type == kind,
            ))))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as db:
        db.get(ActionItem, task["id"]).due_at = now + timedelta(hours=3)
        db.commit()
        run_deadline_sweep(db, now=now, task_ids=[task["id"]])
        run_deadline_sweep(db, now=now, task_ids=[task["id"]])
    assert alerts("deadline_approaching", employee["id"]) == 1

    with SessionLocal() as db:
        db.get(ActionItem, task["id"]).due_at = now - timedelta(hours=1)
        db.commit()
        run_deadline_sweep(db, now=now, task_ids=[task["id"]])
        run_deadline_sweep(db, now=now, task_ids=[task["id"]])
    assert alerts("task_overdue", employee["id"]) == 1
    assert alerts("task_overdue", owner["id"]) == 1

    listed = client.get("/api/tasks?scope=assigned", headers=employee_headers).json()
    assert listed[0]["is_overdue"] is True


def test_search_export_and_admin_only_analytics() -> None:
    _, headers = _member("Plain")
    assert client.get("/api/admin/analytics", headers=headers).status_code == 403

    meeting = client.post("/api/meetings", json={"title": "Zebra roadmap review"}, headers=headers).json()
    client.patch(
        f"/api/meetings/{meeting['id']}",
        json={"transcript": "[Ali]: The zebra release moves to October."},
        headers=headers,
    )
    found = client.get("/api/workspace/search?q=zebra", headers=headers).json()
    assert any(m["id"] == meeting["id"] for m in found["meetings"])

    export = client.get(f"/api/meetings/{meeting['id']}/export.md", headers=headers)
    assert export.status_code == 200
    assert export.text.startswith("# Zebra roadmap review")
    assert "## Action items" in export.text
