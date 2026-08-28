"""Tests for Block 4 (Zoom Bot) and Block 5 (Notifications System)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_block4_zoom_and_block5_notifications():
    # 1. Register & Login
    email = "block45_tester@example.com"
    password = "securePassword123"
    client.post("/api/auth/register", json={"email": email, "password": password})
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create Meeting
    m_res = client.post(
        "/api/meetings",
        json={"title": "Enterprise Zoom All-Hands", "platform": "zoom"},
        headers=headers,
    )
    assert m_res.status_code == 201
    meeting_id = m_res.json()["id"]

    # 3. Test Block 4: Zoom Bot Join & Leave
    join_res = client.post(
        f"/api/zoom/join/{meeting_id}",
        json={"zoom_url_or_id": "https://zoom.us/j/1234567890"},
        headers=headers,
    )
    assert join_res.status_code == 200
    assert join_res.json()["status"] == "listening"

    status_res = client.get(f"/api/zoom/status/{meeting_id}", headers=headers)
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "listening"

    leave_res = client.post(f"/api/zoom/leave/{meeting_id}", headers=headers)
    assert leave_res.status_code == 200
    assert leave_res.json()["status"] == "left"

    # 4. Test Block 5: Meeting Analysis creates Notification
    client.patch(
        f"/api/meetings/{meeting_id}",
        json={"transcript": "Ali: We will ship version 1.0 on Monday."},
        headers=headers,
    )
    analyze_res = client.post(f"/api/meetings/{meeting_id}/analyze", headers=headers)
    assert analyze_res.status_code == 200

    # 5. Fetch In-App Notifications
    notif_res = client.get("/api/notifications", headers=headers)
    assert notif_res.status_code == 200
    notifications = notif_res.json()
    assert len(notifications) >= 1
    notif_id = notifications[0]["id"]
    assert "Summary Ready" in notifications[0]["title"]

    # 6. Mark Notification as Read
    read_res = client.patch(f"/api/notifications/{notif_id}/read", headers=headers)
    assert read_res.status_code == 200
    assert read_res.json()["read"] is True

    # 7. Mark All Notifications as Read
    mark_all = client.post("/api/notifications/mark-all-read", headers=headers)
    assert mark_all.status_code == 200
