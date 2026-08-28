"""Tests for Block 3: Live WebSocket Audio Streaming & Text-to-Speech (TTS)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_block3_live_websocket_and_tts_flow():
    # 1. Register & Login
    email = "block3_tester@example.com"
    password = "securePassword123"
    client.post("/api/auth/register", json={"email": email, "password": password})
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create meeting
    m_res = client.post(
        "/api/meetings",
        json={"title": "Sprint 4 Live Streaming", "platform": "in_person"},
        headers=headers,
    )
    assert m_res.status_code == 201
    meeting_id = m_res.json()["id"]

    # 3. Test Text-to-Speech (TTS) endpoint
    tts_res = client.post(
        f"/api/meetings/{meeting_id}/tts/speak",
        json={"text": "The sprint deadline is set for next Monday."},
        headers=headers,
    )
    assert tts_res.status_code == 200
    tts_data = tts_res.json()
    assert "audio_base64" in tts_data
    assert tts_data["content_type"] == "audio/wav"

    # 4. Test WebSocket Live Streaming Connection
    with client.websocket_connect(f"/ws/meetings/{meeting_id}/live?token={token}") as ws:
        connected_msg = ws.receive_json()
        assert connected_msg["type"] == "connected"

        # Send live text segment over websocket
        ws.send_json({
            "type": "text_segment",
            "text": "Action item: Deploy to staging cluster by 5pm.",
            "speaker": "LIVE_SPEAKER",
        })

        resp = ws.receive_json()
        assert resp["type"] == "transcript_segment"
        assert "Deploy to staging cluster" in resp["text"]
        assert resp["action_created"] is not None

        # Stop stream
        ws.send_json({"type": "stop"})
        stop_resp = ws.receive_json()
        assert stop_resp["type"] == "completed"

    # 5. Verify live segment & action item persisted in database
    detail_res = client.get(f"/api/meetings/{meeting_id}", headers=headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert len(detail["action_items"]) >= 1
    assert "Deploy to staging cluster" in detail["transcript"]
