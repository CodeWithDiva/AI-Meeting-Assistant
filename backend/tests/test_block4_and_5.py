"""Tests for the meeting-agent lifecycle and the notifications system."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_agent_lifecycle_and_notifications(monkeypatch):
    async def fake_join(self, join_url: str) -> dict[str, object]:
        self.status = "listening"
        self.is_connected = True
        return {"status": "listening", "platform": "zoom", "simulated": True}

    async def fake_leave(self) -> dict[str, object]:
        self.status = "left"
        self.is_connected = False
        return {"status": "left", "message": "left", "notes": {"assigned": 0}}

    monkeypatch.setattr("app.agents.browser_bot.BrowserMeetingBot.join_meeting", fake_join)
    monkeypatch.setattr("app.agents.browser_bot.BrowserMeetingBot.leave_meeting", fake_leave)

    # 1. Register & login
    email = "block45_tester@example.com"
    password = "securePassword123"
    client.post("/api/auth/register", json={"email": email, "password": password})
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

    # 2. Send the agent in with nothing but a link
    join_res = client.post(
        "/api/agent/join",
        json={"link": "https://zoom.us/j/1234567890", "title": "Enterprise All-Hands"},
        headers=headers,
    )
    assert join_res.status_code == 202
    meeting_id = join_res.json()["meeting_id"]
    assert join_res.json()["state"] == "JOINING"

    # 3. Status is readable for a meeting the agent was dispatched to
    status_res = client.get(f"/api/agent/status/{meeting_id}", headers=headers)
    assert status_res.status_code == 200
    assert status_res.json()["state"] in {"JOINING", "IN_MEETING", "idle"}

    # 4. Leaving finalizes the session
    leave_res = client.post(f"/api/agent/leave/{meeting_id}", headers=headers)
    assert leave_res.status_code == 200
    assert leave_res.json()["state"] == "COMPLETE"

    # 5. Analysis of a saved transcript raises a notification
    client.patch(
        f"/api/meetings/{meeting_id}",
        json={"transcript": "[Ali]: We agreed to ship version 1.0 on Monday."},
        headers=headers,
    )
    analyze_res = client.post(f"/api/meetings/{meeting_id}/analyze", headers=headers)
    assert analyze_res.status_code == 200

    # 6. Fetch in-app notifications
    notif_res = client.get("/api/notifications", headers=headers)
    assert notif_res.status_code == 200
    notifications = notif_res.json()
    assert len(notifications) >= 1
    assert "Summary Ready" in notifications[0]["title"]
    notif_id = notifications[0]["id"]

    # 7. Mark one, then all, as read
    read_res = client.patch(f"/api/notifications/{notif_id}/read", headers=headers)
    assert read_res.status_code == 200
    assert read_res.json()["read"] is True
    assert client.post("/api/notifications/mark-all-read", headers=headers).status_code == 200
