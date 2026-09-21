"""Guards against Whisper inventing text, and against feeding it noise."""

from __future__ import annotations

from app.agents import audio_capture
from app.transcription.base import TranscriptSegment, collapse_repetitions


def _segs(*texts: str) -> list[TranscriptSegment]:
    return [TranscriptSegment(text=t) for t in texts]


def _texts(segments: list[TranscriptSegment]) -> list[str]:
    return [s.text for s in segments]


def test_a_repetition_loop_is_dropped_entirely() -> None:
    # The real failure: one sentence, never spoken, twenty-one times in a row.
    loop = ["The globe is on the ground."] * 21
    assert _texts(collapse_repetitions(_segs("Real words here", *loop, "More real words"))) == [
        "Real words here",
        "More real words",
    ]


def test_a_short_run_of_identical_lines_is_collapsed_to_one() -> None:
    assert _texts(collapse_repetitions(_segs("Alina.", "Alina.", "Alina.", "Are you there?"))) == [
        "Alina.",
        "Are you there?",
    ]


def test_repeats_are_matched_ignoring_case_and_punctuation() -> None:
    assert _texts(collapse_repetitions(_segs("Hello there", "hello, there!"))) == ["Hello there"]


def test_distinct_lines_are_untouched() -> None:
    lines = ["one thing", "another thing", "one thing"]
    assert _texts(collapse_repetitions(_segs(*lines))) == lines


def test_an_empty_window_stays_empty() -> None:
    assert collapse_repetitions([]) == []


def test_the_bot_can_opt_out_of_mixing_the_local_microphone(monkeypatch) -> None:
    monkeypatch.setattr(audio_capture, "CAPTURE_MODE", "loopback")
    monkeypatch.setattr(audio_capture, "MIX_MIC", True)

    assert audio_capture.build_capture_stream().mix_mic is True  # attach mode default
    # The bot hears everyone, its operator included, through the meeting itself;
    # a local mic on top only adds hiss and a doubled voice.
    assert audio_capture.build_capture_stream(mix_mic=False).mix_mic is False
