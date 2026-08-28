"""Tests for Block 2: Speaker Diarization, Semantic Search, and AI Chat Copilot."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_block2_speakers_search_chat_flow():
    # 1. Register & Login
    email = "block2_tester_new@example.com"
    password = "securePassword123"
    client.post("/api/auth/register", json={"email": email, "password": password})
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create meeting with transcript
    m_res = client.post(
        "/api/meetings",
        json={"title": "Q4 Strategy & Planning", "platform": "zoom"},
        headers=headers,
    )
    assert m_res.status_code == 201
    meeting_id = m_res.json()["id"]

    client.patch(
        f"/api/meetings/{meeting_id}",
        json={"transcript": "Ali: We agreed to launch the beta next week. Sara: I will prepare marketing ads."},
        headers=headers,
    )

    # 3. Analyze meeting
    client.post(
        f"/api/meetings/{meeting_id}/analyze",
        headers=headers,
    )

    # 4. Test Speakers listing
    spk_res = client.get(f"/api/meetings/{meeting_id}/speakers", headers=headers)
    assert spk_res.status_code == 200

    # 5. Test Semantic Search
    search_res = client.post(
        f"/api/meetings/{meeting_id}/search",
        json={"query": "launch beta marketing", "limit": 5},
        headers=headers,
    )
    assert search_res.status_code == 200
    assert "results" in search_res.json()

    # 6. Test AI Meeting Q&A Copilot
    chat_res = client.post(
        f"/api/meetings/{meeting_id}/chat/ask",
        json={"question": "What is the launch plan?"},
        headers=headers,
    )
    assert chat_res.status_code == 200
    chat_data = chat_res.json()
    assert "answer" in chat_data
    assert len(chat_data["answer"]) > 0
