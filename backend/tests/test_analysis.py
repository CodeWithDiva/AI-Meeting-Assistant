import asyncio

from app.ai.fallback import analyze_with_fallback


def test_fallback_extracts_safe_structured_notes() -> None:
    result = analyze_with_fallback(
        "The team agreed to launch the dashboard. Ali will prepare the release notes by Friday."
    )

    assert result["summary"].startswith("The team agreed")
    assert result["decisions"] == ["The team agreed to launch the dashboard."]
    assert result["action_items"] == [
        {"assignee": "Ali", "task": "prepare the release notes", "deadline": "Friday"}
    ]


def test_analysis_service_falls_back_when_ollama_is_offline(monkeypatch) -> None:
    async def unavailable(_: str) -> dict[str, object]:
        raise RuntimeError("Ollama is unavailable")

    monkeypatch.setattr("app.ai.service.analyze_with_ollama", unavailable)

    result = asyncio.run(
        __import__("app.ai.service", fromlist=["analyze_meeting"]).analyze_meeting(
            "Sara will send the agenda by tomorrow."
        )
    )

    assert result["action_items"][0]["assignee"] == "Sara"
