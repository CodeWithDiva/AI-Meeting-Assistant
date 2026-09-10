"""Tests for the link-first meeting agent API and its link parsing."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.meeting_link import (
    MEET,
    ZOOM,
    UnsupportedMeetingLinkError,
    parse_meeting_link,
)
from app.main import app


# ── Link parsing ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "platform", "code"),
    [
        ("1234567890", ZOOM, "1234567890"),
        ("https://zoom.us/j/1234567890", ZOOM, "1234567890"),
        ("https://us02web.zoom.us/j/1234567890?pwd=secret", ZOOM, "1234567890"),
        ("https://app.zoom.us/wc/1234567890/join", ZOOM, "1234567890"),
        ("https://meet.google.com/abc-defg-hij", MEET, "abc-defg-hij"),
        ("abc-defg-hij", MEET, "abc-defg-hij"),
        ("https://meet.google.com/ABC-DEFG-HIJ?authuser=0", MEET, "abc-defg-hij"),
    ],
)
def test_parse_meeting_link_detects_platform(raw: str, platform: str, code: str) -> None:
    link = parse_meeting_link(raw)
    assert link.platform == platform
    assert link.meeting_code == code


def test_zoom_password_is_carried_into_the_join_url() -> None:
    link = parse_meeting_link("https://zoom.us/j/1234567890?pwd=secret")
    assert link.password == "secret"
    assert "pwd=secret" in link.join_url
    # The web-client URL is what skips Zoom's "download the app" landing page.
    assert link.join_url.startswith("https://app.zoom.us/wc/1234567890/join")


@pytest.mark.parametrize("raw", ["", "   ", "https://example.com/some-page", "hello there"])
def test_unsupported_links_are_rejected(raw: str) -> None:
    with pytest.raises(UnsupportedMeetingLinkError):
        parse_meeting_link(raw)


# ── Agent API ───────────────────────────────────────────────────────────


@pytest.fixture()
def auth_client(monkeypatch) -> tuple[TestClient, dict[str, str]]:
    """A logged-in client whose bot never actually opens a browser."""
    async def fake_join(self, join_url: str) -> dict[str, object]:
        self.status = "listening"
        self.is_connected = True
        return {"status": "listening", "platform": "zoom", "simulated": True}

    async def fake_leave(self) -> dict[str, object]:
        self.status = "left"
        self.is_connected = False
        return {"status": "left", "message": "left", "notes": {"action_items": 0}}

    monkeypatch.setattr("app.agents.browser_bot.BrowserMeetingBot.join_meeting", fake_join)
    monkeypatch.setattr("app.agents.browser_bot.BrowserMeetingBot.leave_meeting", fake_leave)

    client = TestClient(app)
    email = "agent_tester@example.com"
    password = "securePassword123"
    client.post("/api/auth/register", json={"email": email, "password": password})
    token = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    ).json()["access_token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_join_from_a_link_creates_the_meeting(auth_client) -> None:
    client, headers = auth_client

    response = client.post(
        "/api/agent/join",
        json={"link": "https://zoom.us/j/1234567890", "title": "Sprint sync"},
        headers=headers,
    )
    assert response.status_code == 202
    body = response.json()
    assert body["platform"] == ZOOM
    assert body["state"] == "JOINING"
    assert body["title"] == "Sprint sync"
    assert body["recording_enabled"] is False

    # The meeting must exist immediately, so the UI has a page to open.
    meeting = client.get(f"/api/meetings/{body['meeting_id']}", headers=headers)
    assert meeting.status_code == 200
    assert meeting.json()["platform"] == ZOOM


def test_join_derives_a_title_when_none_is_given(auth_client) -> None:
    client, headers = auth_client
    response = client.post(
        "/api/agent/join",
        json={"link": "https://meet.google.com/abc-defg-hij"},
        headers=headers,
    )
    assert response.status_code == 202
    assert response.json()["title"] == "Google Meet meeting abc-defg-hij"
    assert response.json()["platform"] == MEET


def test_opting_into_recording_records_consent(auth_client) -> None:
    client, headers = auth_client
    meeting_id = client.post(
        "/api/agent/join",
        json={"link": "https://zoom.us/j/1234567890", "record": True},
        headers=headers,
    ).json()["meeting_id"]

    recording = client.get(f"/api/meetings/{meeting_id}/recording", headers=headers).json()
    assert recording["enabled"] is True
    assert recording["consent_given_at"] is not None


def test_a_junk_link_is_rejected_before_a_meeting_is_created(auth_client) -> None:
    client, headers = auth_client
    response = client.post(
        "/api/agent/join", json={"link": "https://example.com/not-a-meeting"}, headers=headers
    )
    assert response.status_code == 400
    assert "Zoom and Google Meet" in response.json()["detail"]


def test_leaving_without_an_active_bot_is_not_an_error(auth_client) -> None:
    client, headers = auth_client
    meeting_id = client.post(
        "/api/meetings", json={"title": "Standalone", "platform": "zoom"}, headers=headers
    ).json()["id"]

    response = client.post(f"/api/agent/leave/{meeting_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["state"] == "DISCONNECTED"


def test_status_of_a_meeting_the_agent_never_joined(auth_client) -> None:
    client, headers = auth_client
    meeting_id = client.post(
        "/api/meetings", json={"title": "Untouched", "platform": "zoom"}, headers=headers
    ).json()["id"]

    response = client.get(f"/api/agent/status/{meeting_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["state"] == "idle"
    assert response.json()["is_connected"] is False


def test_agent_endpoints_require_authentication() -> None:
    client = TestClient(app)
    assert client.post("/api/agent/join", json={"link": "https://zoom.us/j/1"}).status_code == 401
