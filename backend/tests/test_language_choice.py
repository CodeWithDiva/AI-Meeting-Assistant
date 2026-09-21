"""Urdu-vs-English language choice for live transcription."""

from __future__ import annotations

import pytest

from app.transcription import base
from app.transcription.base import FasterWhisperService, StickyLanguage


class _FakeDetector:
    def __init__(self, probs: dict[str, float]) -> None:
        self._probs = probs

    def detect_language(self, audio, **kwargs):  # noqa: ANN001
        best = max(self._probs, key=self._probs.get)
        return best, self._probs[best], list(self._probs.items())


@pytest.fixture()
def service(monkeypatch) -> FasterWhisperService:
    import faster_whisper.audio

    monkeypatch.setattr(faster_whisper.audio, "decode_audio", lambda path, sampling_rate=16000: [0.0])
    return FasterWhisperService(model_size="small")


def _choose(service, monkeypatch, probs, prefer=None):  # noqa: ANN001
    monkeypatch.setattr(service, "_load_model", lambda size=None: _FakeDetector(probs))
    return service._choose_language("ignored.wav", prefer)


def test_urdu_that_whisper_calls_hindi_is_treated_as_urdu(service, monkeypatch) -> None:
    # The real failure: 3 of 4 Urdu clips came back `hi` at 0.8-0.9.
    language, confidence = _choose(service, monkeypatch, {"hi": 0.85, "ur": 0.05, "en": 0.02})
    assert language == "ur"
    assert confidence > 0.9


def test_english_is_still_recognised(service, monkeypatch) -> None:
    language, _ = _choose(service, monkeypatch, {"en": 0.97, "ur": 0.01, "hi": 0.01})
    assert language == "en"


def test_only_urdu_or_english_can_ever_be_chosen(service, monkeypatch) -> None:
    # Some unrelated language topping the list must not become the meeting's.
    language, _ = _choose(service, monkeypatch, {"de": 0.6, "ur": 0.2, "en": 0.1})
    assert language in {"ur", "en"}


def test_english_uses_the_quick_model_and_urdu_the_accurate_one() -> None:
    svc = FasterWhisperService(model_size="small")
    assert svc.model_size == "small"
    assert svc.english_model_size == "base"


def test_the_quick_model_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("WHISPER_MODEL_EN", "tiny")
    assert FasterWhisperService(model_size="small").english_model_size == "tiny"


def test_a_hindi_detection_can_never_lock_the_meeting() -> None:
    sticky = StickyLanguage()
    sticky.observe("hi", 0.9)
    assert sticky.language_for_next_window() == "ur"


def test_english_must_be_clearly_english_to_win(service, monkeypatch) -> None:
    # Forcing English onto Urdu speech invents fluent nonsense ("the globe is
    # on the ground"), so a merely-probable English is treated as Urdu.
    language, _ = _choose(service, monkeypatch, {"en": 0.6, "ur": 0.25, "hi": 0.1})
    assert language == "ur"


def test_a_meeting_that_was_english_keeps_english_on_a_lower_bar(service, monkeypatch) -> None:
    probs = {"en": 0.66, "ur": 0.2, "hi": 0.1}
    assert _choose(service, monkeypatch, probs)[0] == "ur"
    assert _choose(service, monkeypatch, probs, prefer="en")[0] == "en"


def test_the_english_bar_can_be_tuned(service, monkeypatch) -> None:
    monkeypatch.setenv("WHISPER_EN_THRESHOLD", "0.5")
    assert _choose(service, monkeypatch, {"en": 0.6, "ur": 0.3})[0] == "en"
