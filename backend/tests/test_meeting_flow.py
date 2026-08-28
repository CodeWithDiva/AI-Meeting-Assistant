import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_auth_and_full_meeting_flow():
    # 1. Register a test user
    email = "testuser_mvp@example.com"
    password = "password123"

    reg_res = client.post("/api/auth/register", json={"email": email, "password": password})
    assert reg_res.status_code in (201, 409)

    # 2. Login
    login_res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Create a Meeting
    meeting_res = client.post(
        "/api/meetings",
        json={"title": "Q3 Architecture Review", "platform": "zoom"},
        headers=headers,
    )
    assert meeting_res.status_code == 201
    meeting_id = meeting_res.json()["id"]

    # 4. Update meeting with sample transcript
    sample_transcript = (
        "Alice: We decided to deploy the AI Meeting Assistant on AWS. "
        "Bob: Action item for Ali to configure PostgreSQL database by Friday."
    )
    patch_res = client.patch(
        f"/api/meetings/{meeting_id}",
        json={"transcript": sample_transcript},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["transcript"] == sample_transcript

    # 5. Run AI Analysis (fallback or Ollama)
    analyze_res = client.post(f"/api/meetings/{meeting_id}/analyze", headers=headers)
    assert analyze_res.status_code == 200
    data = analyze_res.json()
    assert "summary" in data
    assert "decisions" in data
    assert "action_items" in data

    # 6. Retrieve Meeting Detail
    detail_res = client.get(f"/api/meetings/{meeting_id}", headers=headers)
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["id"] == meeting_id
    assert detail_data["summary"] is not None

    # 7. Check Tasks & Dashboard Stats
    stats_res = client.get("/api/tasks/dashboard/stats", headers=headers)
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert stats["total_meetings"] >= 1

    # 8. Recording Toggle
    rec_res = client.patch(
        f"/api/meetings/{meeting_id}/recording",
        json={"enabled": True},
        headers=headers,
    )
    assert rec_res.status_code == 200
    assert rec_res.json()["enabled"] is True
