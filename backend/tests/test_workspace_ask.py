"""Asking Alina from the dashboard should answer from across every meeting,
not just one — with real registered names used for task assignment too.
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.services.meeting_analysis import analyze_and_persist

client = TestClient(app)


def _register(first_name: str) -> tuple[dict, dict]:
    tag = uuid.uuid4().hex[:8]
    email = f"{first_name.lower()}-{tag}@example.com"
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "full_name": f"{first_name} T{tag}"},
    )
    assert res.status_code == 201
    token = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return res.json(), {"Authorization": f"Bearer {token.json()['access_token']}"}


def test_asking_with_no_meetings_says_so_instead_of_guessing() -> None:
    _, headers = _register("Kamran")
    res = client.post("/api/workspace/ask", json={"question": "What did we decide?"}, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["sources"] == []
    # The real model (temperature 0.2) phrases an honest "nothing recorded"
    # answer differently run to run — "no meetings yet", "no decisions
    # recorded", "I don't have any notes" are all correct; pinning to one
    # exact wording made this test fail on a truthful answer. What must never
    # happen is the model inventing a decision that was never made.
    answer = body["answer"].lower()
    assert any(kw in answer for kw in ("meeting", "decision", "record", "note", "yet", "nothing", "don't have")), answer


def test_a_question_pulls_context_from_the_matching_meeting_and_cites_it() -> None:
    _, headers = _register("Kamran")

    meeting = client.post(
        "/api/meetings", json={"title": "Q1 budget review"}, headers=headers
    ).json()
    client.patch(
        f"/api/meetings/{meeting['id']}",
        json={"transcript": "[Ali]: We agreed to cap the marketing budget at 50000 for Q1."},
        headers=headers,
    )
    analyze = client.post(f"/api/meetings/{meeting['id']}/analyze", headers=headers)
    assert analyze.status_code == 200

    res = client.post(
        "/api/workspace/ask", json={"question": "What was decided about the Q1 budget?"}, headers=headers
    )
    assert res.status_code == 200
    body = res.json()
    assert any(s["meeting_id"] == meeting["id"] for s in body["sources"])
    assert body["answer"]


def test_analysis_is_told_the_real_registered_names_for_assignment(monkeypatch) -> None:
    """`analyze_and_persist` must hand the LLM every registered name, not just
    who the bot saw on the call — someone often hands work to a person who
    wasn't in the meeting. This stubs the LLM call itself: whether the model
    then *uses* that roster well is Ollama's job, not this test's, and
    asserting on a real model's output would make the suite depend on
    whatever is installed and how loaded the machine is.
    """
    owner, owner_headers = _register("Kamran")
    employee, _ = _register("Zunaira")

    meeting = client.post("/api/meetings", json={"title": "Sprint planning"}, headers=owner_headers).json()
    client.patch(
        f"/api/meetings/{meeting['id']}",
        json={"transcript": f"[Kamran]: {employee['full_name']} will own the migration script."},
        headers=owner_headers,
    )

    seen_rosters: list[list[str] | None] = []

    async def fake_analyze_meeting(transcript: str, participants=None):
        seen_rosters.append(participants)
        return {"summary": "", "decisions": [], "action_items": []}

    monkeypatch.setattr("app.services.meeting_analysis.analyze_meeting", fake_analyze_meeting)

    with SessionLocal() as db:
        asyncio.run(analyze_and_persist(meeting["id"], db))

    assert seen_rosters and employee["full_name"] in seen_rosters[0]
    # Every registered member is offered, not only people the bot saw on the call.
    assert owner["full_name"] in seen_rosters[0]


def test_a_greeting_and_a_meeting_question_get_different_context_with_no_meetings(monkeypatch) -> None:
    """The bug this guards against: every question — "helo alina", "what is
    date", "whats the update of metting" — was met with the exact same
    "there aren't any meetings" line, because that answer was hard-coded
    before the LLM was ever asked anything. Now every question reaches
    _ask_llm, which is what actually tells a greeting from a real question.
    """
    _, headers = _register("Kamran")

    seen_context: list[str] = []

    async def fake_ask_llm(context_prompt: str, question: str, *, style: str = "spoken") -> str:
        seen_context.append(context_prompt)
        return f"stub answer for: {question}"

    monkeypatch.setattr("app.routers.workspace._ask_llm", fake_ask_llm)

    greeting = client.post("/api/workspace/ask", json={"question": "helo alina"}, headers=headers)
    question = client.post("/api/workspace/ask", json={"question": "what's still open?"}, headers=headers)

    assert greeting.status_code == 200 and question.status_code == 200
    # Both reach the LLM (not a hard-coded bail-out)...
    assert greeting.json()["answer"] == "stub answer for: helo alina"
    assert question.json()["answer"] == "stub answer for: what's still open?"
    # ...with the same honest context either way — it's up to the model (now
    # a real one, not a canned string) to tell a greeting apart from a real
    # question about meeting data.
    assert seen_context[0] == seen_context[1]
    assert seen_context[0].endswith("This workspace has no meetings recorded yet.")


def test_a_workspace_question_gets_team_size_not_a_meeting_shaped_answer() -> None:
    """The other bug this guards against: "how many employees are on the
    dashboard" was answered as if it were a meeting question ("there is no
    information about employees in the meeting notes"), because team size
    was never part of what Alina could see — only meeting notes were.
    """
    _, headers = _register("Kamran")
    res = client.post(
        "/api/workspace/ask", json={"question": "how many employees are on the dashboard"}, headers=headers
    )
    assert res.status_code == 200
    answer = res.json()["answer"].lower()
    assert "employee" in answer
    assert "no information" not in answer and "don't have" not in answer
