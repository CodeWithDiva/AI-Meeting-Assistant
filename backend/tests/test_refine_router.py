"""Router-level tests for POST/GET /api/meetings/{id}/refine.

The actual Whisper re-transcription is exercised by test_refine.py's pure
helpers; here `start_refine` is monkeypatched so these run fast and without a
model.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import refine as refine_service

client = TestClient(app)


def _register_and_login(email: str) -> dict:
    client.post("/api/auth/register", json={"email": email, "password": "password123"})
    res = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_meeting(headers: dict) -> int:
    res = client.post("/api/meetings", json={"title": "Refine test meeting", "platform": "zoom"}, headers=headers)
    assert res.status_code == 201
    return res.json()["id"]


def test_refine_requires_a_recording():
    headers = _register_and_login("refine_no_recording@example.com")
    meeting_id = _create_meeting(headers)

    res = client.post(f"/api/meetings/{meeting_id}/refine", headers=headers)

    assert res.status_code == 409


def test_refine_status_idle_before_starting():
    headers = _register_and_login("refine_idle@example.com")
    meeting_id = _create_meeting(headers)

    res = client.get(f"/api/meetings/{meeting_id}/refine", headers=headers)

    assert res.status_code == 200
    assert res.json()["status"] == "idle"


def test_refine_starts_when_a_recording_exists(monkeypatch):
    headers = _register_and_login("refine_ok@example.com")
    meeting_id = _create_meeting(headers)

    rec_res = client.patch(f"/api/meetings/{meeting_id}/recording", json={"enabled": True}, headers=headers)
    assert rec_res.status_code == 200

    # The router only checks Recording.enabled and Recording.file_path; set the
    # path directly via the recording toggle's DB row isn't exposed by the API,
    # so reach into the service the way `_open_recording` would have.
    from app.database import SessionLocal
    from app.models import Recording
    from sqlalchemy import select

    with SessionLocal() as db:
        rec = db.scalar(select(Recording).where(Recording.meeting_id == meeting_id))
        rec.file_path = "does-not-matter-for-this-test.wav"
        db.commit()

    started = {}

    def fake_start_refine(mid, regenerate_notes=True):
        started["meeting_id"] = mid
        job = refine_service.RefineJob(meeting_id=mid, status="running", model="medium")
        refine_service._JOBS[mid] = job
        return job

    monkeypatch.setattr(refine_service, "start_refine", fake_start_refine)

    res = client.post(f"/api/meetings/{meeting_id}/refine", headers=headers)

    assert res.status_code == 200
    assert res.json()["status"] == "running"
    assert started["meeting_id"] == meeting_id


def test_refine_rejects_another_users_meeting():
    owner_headers = _register_and_login("refine_owner@example.com")
    meeting_id = _create_meeting(owner_headers)
    other_headers = _register_and_login("refine_other@example.com")

    res = client.post(f"/api/meetings/{meeting_id}/refine", headers=other_headers)

    assert res.status_code == 404
