"""Tests for offline note extraction — English, Roman Urdu, and Urdu script."""

import asyncio

from app.ai.fallback import analyze_with_fallback
from app.ai.ollama import _normalize, detect_transcript_language
from app.ai.service import analyze_meeting


def test_fallback_extracts_safe_structured_notes() -> None:
    result = analyze_with_fallback(
        "The team agreed to launch the dashboard. Ali will prepare the release notes by Friday."
    )

    assert result["summary"].startswith("The team agreed")
    assert result["decisions"] == ["The team agreed to launch the dashboard."]
    assert result["action_items"] == [
        {
            "assignee": "Ali",
            "assigned_by": None,
            "task": "prepare the release notes",
            "deadline": "Friday",
        }
    ]


def test_fallback_invents_nothing_when_nothing_was_decided() -> None:
    result = analyze_with_fallback("We talked about the weather and then the build times.")
    assert result["decisions"] == []
    assert result["action_items"] == []


def test_fallback_uses_the_speaker_label_as_the_assigner() -> None:
    result = analyze_with_fallback("[Sara]: Bilal ko client report bhejni hai.")
    assert result["action_items"][0]["assignee"] == "Bilal"
    assert result["action_items"][0]["assigned_by"] == "Sara"


def test_fallback_reads_urdu_script_decisions() -> None:
    result = analyze_with_fallback("ٹیم کا فیصلہ ہے کہ نیا ڈیش بورڈ پیر کو لانچ ہوگا۔")
    assert len(result["decisions"]) == 1


def test_analysis_service_falls_back_when_ollama_is_offline(monkeypatch) -> None:
    async def unavailable(transcript, participants=None):
        raise RuntimeError("Ollama is unavailable")

    monkeypatch.setattr("app.ai.service.analyze_with_ollama", unavailable)

    result = asyncio.run(analyze_meeting("Sara will send the agenda by tomorrow."))

    assert result["action_items"][0]["assignee"] == "Sara"
    assert result["provider"] == "fallback"


# ── Language detection ──────────────────────────────────────────────────


def test_urdu_script_is_detected() -> None:
    assert detect_transcript_language("ہمیں یہ رپورٹ کل تک بھیجنی ہے۔") == "ur"


def test_roman_urdu_is_treated_as_latin_script() -> None:
    # Roman Urdu is written in Latin script, so the model should answer in kind.
    assert detect_transcript_language("Ali ko report kal tak bhejni hai.") == "en"


def test_a_stray_urdu_word_does_not_flip_an_english_meeting() -> None:
    transcript = (
        "We reviewed the quarterly numbers and agreed to move the launch date. "
        "The client asked for a shorter demo. Sara will rewrite the deck. (شکریہ)"
    )
    assert detect_transcript_language(transcript) == "en"


# ── Loose model output ──────────────────────────────────────────────────


def test_normalize_rescues_decisions_returned_as_objects() -> None:
    notes = _normalize({"summary": "s", "decisions": [{"decision": "Ship on Monday"}]})
    assert notes["decisions"] == ["Ship on Monday"]


def test_normalize_maps_model_nulls_to_none() -> None:
    notes = _normalize({
        "action_items": [{"task": "Send the report", "assignee": "N/A", "deadline": "null"}]
    })
    assert notes["action_items"][0]["assignee"] is None
    assert notes["action_items"][0]["deadline"] is None


def test_normalize_drops_action_items_with_no_task() -> None:
    notes = _normalize({"action_items": [{"assignee": "Ali"}, {"task": "  "}]})
    assert notes["action_items"] == []
