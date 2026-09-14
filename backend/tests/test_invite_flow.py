"""Admin adds an employee by name + email only — the employee sets their own
password via a one-time invite link, never handed a password by the admin.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import User

client = TestClient(app)


def _admin() -> tuple[dict, dict]:
    tag = uuid.uuid4().hex[:8]
    email = f"owner-{tag}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "password123", "full_name": f"Owner {tag}"})
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        user.role = "admin"
        db.commit()
    token = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"email": email}, {"Authorization": f"Bearer {token.json()['access_token']}"}


def test_inviting_an_employee_needs_no_password_and_they_set_their_own() -> None:
    _, admin_headers = _admin()
    tag = uuid.uuid4().hex[:8]
    email = f"hamza-{tag}@example.com"

    invited = client.post(
        "/api/auth/admin/users",
        json={"email": email, "full_name": "Hamza Tariq", "role": "employee"},
        headers=admin_headers,
    )
    assert invited.status_code == 201
    body = invited.json()
    assert "invite_link" in body and "token=" in body["invite_link"]
    invite_token = body["invite_link"].split("token=")[1]

    # Cannot log in yet — no password has ever been set.
    login_attempt = client.post("/api/auth/login", json={"email": email, "password": "anything123"})
    assert login_attempt.status_code == 401

    # The invite page can read who it's for before asking for a password.
    details = client.get(f"/api/auth/invite/{invite_token}")
    assert details.status_code == 200
    assert details.json()["email"] == email

    accepted = client.post("/api/auth/accept-invite", json={"token": invite_token, "password": "newpassword1"})
    assert accepted.status_code == 200
    assert accepted.json()["user"]["email"] == email

    # Now they can sign in with the password they chose, and the link is spent.
    login = client.post("/api/auth/login", json={"email": email, "password": "newpassword1"})
    assert login.status_code == 200
    assert client.get(f"/api/auth/invite/{invite_token}").status_code == 404
    assert client.post("/api/auth/accept-invite", json={"token": invite_token, "password": "another1234"}).status_code == 404


def test_a_non_admin_cannot_invite_anyone() -> None:
    tag = uuid.uuid4().hex[:8]
    email = f"plain-{tag}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "password123"})
    token = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}

    res = client.post(
        "/api/auth/admin/users",
        json={"email": f"x-{tag}@example.com", "full_name": "Someone", "role": "employee"},
        headers=headers,
    )
    assert res.status_code == 403


def test_pending_invite_shows_up_as_invited_then_active_and_can_be_resent() -> None:
    _, admin_headers = _admin()
    tag = uuid.uuid4().hex[:8]
    email = f"sara-{tag}@example.com"

    invited = client.post(
        "/api/auth/admin/users",
        json={"email": email, "full_name": "Sara Khan", "role": "employee"},
        headers=admin_headers,
    )
    user_id = invited.json()["user"]["id"]

    listing = client.get("/api/auth/admin/users", headers=admin_headers).json()
    row = next(r for r in listing if r["id"] == user_id)
    assert row["status"] == "invited"

    resent = client.post(f"/api/auth/admin/users/{user_id}/resend-invite", headers=admin_headers)
    assert resent.status_code == 200
    new_token = resent.json()["invite_link"].split("token=")[1]

    client.post("/api/auth/accept-invite", json={"token": new_token, "password": "chosenpass1"})
    listing_after = client.get("/api/auth/admin/users", headers=admin_headers).json()
    row_after = next(r for r in listing_after if r["id"] == user_id)
    assert row_after["status"] == "active"

    # A second resend is refused once they've already set a password.
    assert client.post(f"/api/auth/admin/users/{user_id}/resend-invite", headers=admin_headers).status_code == 400


def test_admin_can_remove_an_invited_or_active_member_but_not_themselves() -> None:
    admin, admin_headers = _admin()
    tag = uuid.uuid4().hex[:8]
    invited = client.post(
        "/api/auth/admin/users",
        json={"email": f"bilal-{tag}@example.com", "full_name": "Bilal", "role": "employee"},
        headers=admin_headers,
    )
    user_id = invited.json()["user"]["id"]

    me = client.get("/api/auth/me", headers=admin_headers).json()
    assert client.delete(f"/api/auth/admin/users/{me['id']}", headers=admin_headers).status_code == 400

    assert client.delete(f"/api/auth/admin/users/{user_id}", headers=admin_headers).status_code == 204
    listing = client.get("/api/auth/admin/users", headers=admin_headers).json()
    assert all(r["id"] != user_id for r in listing)


def test_registering_never_grants_admin_on_its_own_even_with_no_admin_in_the_workspace() -> None:
    """Admin access is only ever explicit — ADMIN_EMAILS, or an existing
    admin promoting someone. A fresh signup must never self-grant it, even
    when the workspace currently has no admin at all — that would let
    whoever registers next (not necessarily the person who meant to) take
    over the workspace.
    """
    with SessionLocal() as db:
        for user in db.query(User).filter(User.role == "admin").all():
            user.role = "employee"
        db.commit()
        assert db.query(User).filter(User.role == "admin").count() == 0

    tag = uuid.uuid4().hex[:8]
    res = client.post(
        "/api/auth/register",
        json={"email": f"nobody-special-{tag}@example.com", "password": "password123", "full_name": "Nobody Special"},
    )
    assert res.status_code == 201
    assert res.json()["role"] == "employee"
