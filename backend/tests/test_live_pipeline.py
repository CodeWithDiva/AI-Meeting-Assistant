"""Tests for live audio segmentation, language stickiness, and transcript hygiene."""

from __future__ import annotations

import asyncio
import math
import struct

import pytest

from app.services.live_pipeline import (
    MAX_SPEECH_RMS,
    MAX_UTTERANCE_MS,
    MIN_SPEECH_RMS,
    MIN_UTTERANCE_MS,
    SAMPLE_RATE,
    SILENCE_HANG_MS,
    LiveMeetingPipeline,
    MAX_MERGED_WINDOW_S,
    MIN_SPEECH_MS,
    SOFT_CUT_AFTER_MS,
    SOFT_HANG_MS,
    _append_transcript,
    _normalize_level,
    _rms,
)
from app.transcription.base import StickyLanguage, is_hallucination


def _pcm(duration_ms: int, amplitude: int = 6_000, freq: float = 220.0) -> bytes:
    """PCM16 mono audio: a tone at `amplitude`, or silence when amplitude is 0."""
    frames = int(SAMPLE_RATE * duration_ms / 1000)
    if amplitude == 0:
        return b"\x00\x00" * frames
    return b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
        for i in range(frames)
    )


# ── Loudness ────────────────────────────────────────────────────────────


def test_rms_of_silence_is_zero() -> None:
    assert _rms(_pcm(100, amplitude=0)) == 0.0


def test_rms_of_a_tone_is_substantial() -> None:
    assert _rms(_pcm(100, amplitude=6_000)) > 1_000


def test_rms_tolerates_an_odd_trailing_byte() -> None:
    # A truncated device read must not crash the audio loop.
    assert _rms(_pcm(100, amplitude=6_000) + b"\x01") > 1_000


def test_rms_of_an_empty_buffer_is_zero() -> None:
    assert _rms(b"") == 0.0


# ── Utterance segmentation ──────────────────────────────────────────────


@pytest.fixture()
def pipeline(monkeypatch) -> tuple[LiveMeetingPipeline, list[float], list[str]]:
    """A pipeline whose transcriber records each window it is handed.

    Transcription is queued to a background worker rather than awaited inline,
    so tests read the recorded windows (and the text delivered through the
    `on_text` callback) after letting the loop run, not from add_chunk().
    """
    said: list[str] = []

    async def on_text(text: str) -> None:
        said.append(text)

    pipe = LiveMeetingPipeline(meeting_id=1, on_text=on_text)
    windows: list[float] = []

    async def fake_transcribe(pcm_data, duration, start_at, speaker) -> list[str]:
        windows.append(duration)
        return ["text"]

    monkeypatch.setattr(pipe, "_transcribe", fake_transcribe)
    monkeypatch.setattr(pipe, "_write_to_recording", lambda chunk: None)
    return pipe, windows, said


async def _settle(pipe: LiveMeetingPipeline) -> None:
    """Let the background transcription worker drain the queue."""
    await pipe._work.join()


def test_speech_alone_does_not_end_an_utterance(pipeline) -> None:
    pipe, windows, said = pipeline
    # Continuous speech, well under the hard cap — nothing should be cut yet.
    for _ in range(10):
        assert asyncio.run(pipe.add_chunk(_pcm(200))) == []
    assert windows == []


def test_a_pause_after_speech_ends_the_utterance(pipeline) -> None:
    pipe, windows, said = pipeline

    async def run() -> None:
        for _ in range(10):  # 2s of speech, over MIN_UTTERANCE_MS
            await pipe.add_chunk(_pcm(200))
        # Silence longer than the hang time closes the utterance.
        for _ in range(int(SILENCE_HANG_MS / 200) + 1):
            await pipe.add_chunk(_pcm(200, amplitude=0))
        await _settle(pipe)

    asyncio.run(run())
    assert said == ["text"]
    assert len(windows) == 1
    # The window covers the speech plus the trailing pause, not a fixed slice.
    assert windows[0] > MIN_UTTERANCE_MS / 1000


def test_a_brief_noise_burst_is_not_transcribed(pipeline) -> None:
    pipe, windows, said = pipeline

    async def run() -> None:
        await pipe.add_chunk(_pcm(200))  # far shorter than MIN_UTTERANCE_MS
        for _ in range(int(SILENCE_HANG_MS / 200) + 1):
            await pipe.add_chunk(_pcm(200, amplitude=0))

    asyncio.run(run())
    assert windows == []


def test_a_long_talker_is_cut_at_the_hard_cap(pipeline) -> None:
    pipe, windows, said = pipeline

    async def run() -> None:
        # Unbroken speech past MAX_UTTERANCE_MS must still stream out.
        for _ in range(int(MAX_UTTERANCE_MS / 200) + 2):
            await pipe.add_chunk(_pcm(200))
        await _settle(pipe)

    asyncio.run(run())
    assert len(windows) == 1
    assert windows[0] == pytest.approx(MAX_UTTERANCE_MS / 1000, abs=0.3)


def test_pure_silence_is_never_sent_to_whisper(pipeline) -> None:
    pipe, windows, said = pipeline

    async def run() -> None:
        for _ in range(int(MAX_UTTERANCE_MS / 200) + 2):
            await pipe.add_chunk(_pcm(200, amplitude=0))

    asyncio.run(run())
    # Whisper hallucinates filler on silence, so silence must not reach it.
    assert windows == []


def test_flush_emits_a_trailing_utterance(pipeline) -> None:
    pipe, windows, said = pipeline

    async def run() -> None:
        for _ in range(10):
            await pipe.add_chunk(_pcm(200))
        await pipe.flush()
        await _settle(pipe)

    asyncio.run(run())
    assert said == ["text"]
    assert len(windows) == 1


def test_flush_on_an_empty_buffer_is_a_no_op(pipeline) -> None:
    pipe, windows, said = pipeline
    assert asyncio.run(pipe.flush()) == []
    assert windows == []


# ── Adaptive speech threshold ───────────────────────────────────────────
# A fixed loudness cut-off silently discarded whole sentences spoken softly,
# or through a phone-as-microphone / a codec — the words never reached Whisper
# at all, which read as "it skips things". The floor now tracks the room.


def test_soft_speech_in_a_quiet_room_is_still_detected(pipeline) -> None:
    pipe, windows, said = pipeline
    queued: list[float] = []
    pipe._queue_window = lambda window, duration: queued.append(duration)

    async def run() -> None:
        for _ in range(15):  # near-silent background
            await pipe.add_chunk(_pcm(200, amplitude=20))
        for _ in range(10):  # soft speech, under the old fixed 320 cut-off
            await pipe.add_chunk(_pcm(200, amplitude=400))
        for _ in range(int(SILENCE_HANG_MS / 200) + 1):  # pause, closing the utterance
            await pipe.add_chunk(_pcm(200, amplitude=20))

    asyncio.run(run())
    assert queued, "soft speech was dropped as silence"


def test_the_floor_never_drops_to_digital_silence(pipeline) -> None:
    pipe, windows, said = pipeline

    async def run() -> None:
        for _ in range(20):
            await pipe.add_chunk(_pcm(200, amplitude=0))

    asyncio.run(run())
    # Even in a perfectly silent room the floor stays above true silence, or
    # every faint artefact would be transcribed as speech.
    assert pipe._speech_floor() >= MIN_SPEECH_RMS


def test_a_noisy_room_raises_the_floor_but_only_so_far(pipeline) -> None:
    pipe, windows, said = pipeline

    async def run() -> None:
        for _ in range(30):  # loud constant background
            await pipe.add_chunk(_pcm(200, amplitude=5_000))

    asyncio.run(run())
    # Capped, so a noisy room can't push the bar above ordinary speech.
    assert pipe._speech_floor() <= MAX_SPEECH_RMS


# ── Transcript assembly ─────────────────────────────────────────────────


def test_transcript_lines_carry_the_speaker() -> None:
    assert _append_transcript(None, "Ali", ["hello"]) == "[Ali]: hello"


def test_transcript_lines_append_on_separate_lines() -> None:
    first = _append_transcript(None, "Ali", ["hello"])
    assert _append_transcript(first, "Sara", ["hi"]) == "[Ali]: hello\n[Sara]: hi"


# ── Whisper hygiene ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text", ["Thank you.", "you", "...", "شکریہ", "Subtitles by the Amara.org community", " "]
)
def test_silence_filler_is_rejected(text: str) -> None:
    assert is_hallucination(text)


@pytest.mark.parametrize(
    "text",
    [
        "Thank you for sending the report yesterday.",
        "Ali ko client report bhejni hai.",
        "ہمیں یہ رپورٹ کل تک بھیجنی ہے۔",
    ],
)
def test_real_speech_is_kept(text: str) -> None:
    assert not is_hallucination(text)


# ── Language stickiness ─────────────────────────────────────────────────


def test_language_is_unset_until_a_confident_detection() -> None:
    sticky = StickyLanguage()
    assert sticky.language_for_next_window() is None
    sticky.observe("ur", 0.30)
    assert sticky.language_for_next_window() is None


def test_a_confident_detection_locks_the_meeting_language() -> None:
    sticky = StickyLanguage()
    sticky.observe("ur", 0.95)
    assert sticky.language_for_next_window() == "ur"
    # A later low-confidence English window must not flip an Urdu meeting.
    sticky.observe("en", 0.99)
    assert sticky.language_for_next_window() == "ur"


def test_a_forced_language_is_never_overridden() -> None:
    sticky = StickyLanguage(forced="en")
    sticky.observe("ur", 0.99)
    assert sticky.language_for_next_window() == "en"


# ── Backlog handling ────────────────────────────────────────────────────


def test_waiting_windows_from_one_speaker_are_transcribed_in_one_pass(pipeline) -> None:
    pipe, windows, said = pipeline

    async def run() -> None:
        pipe._ensure_worker()
        for _ in range(3):
            pipe._work.put_nowait((_pcm(4_000), 4.0, 0.0, "Ali"))
        await _settle(pipe)

    asyncio.run(run())
    # Whisper charges for a whole 30s window however short the audio, so
    # three 4s utterances waiting in line cost one pass, not three.
    assert windows == [12.0]


def test_windows_are_not_merged_across_speakers(pipeline) -> None:
    pipe, windows, said = pipeline

    async def run() -> None:
        pipe._ensure_worker()
        pipe._work.put_nowait((_pcm(4_000), 4.0, 0.0, "Ali"))
        pipe._work.put_nowait((_pcm(4_000), 4.0, 4.0, "Ali"))
        pipe._work.put_nowait((_pcm(4_000), 4.0, 8.0, "Sara"))
        await _settle(pipe)

    asyncio.run(run())
    assert windows == [8.0, 4.0]


def test_merged_windows_stop_at_the_length_cap(pipeline) -> None:
    pipe, windows, said = pipeline
    each = MAX_MERGED_WINDOW_S * 0.6

    async def run() -> None:
        pipe._ensure_worker()
        for i in range(2):
            pipe._work.put_nowait((_pcm(int(each * 1000)), each, i * each, "Ali"))
        await _settle(pipe)

    asyncio.run(run())
    # Two would exceed the cap together, so they stay separate windows.
    assert windows == [each, each]


def test_a_backlog_switches_to_the_quick_model_and_a_clear_queue_does_not(monkeypatch) -> None:
    pipe = LiveMeetingPipeline(meeting_id=1)
    modes: list[bool] = []

    async def fake_transcribe(pcm_data, duration, start_at, speaker) -> list[str]:
        modes.append(pipe._fast_mode)
        return []

    monkeypatch.setattr(pipe, "_transcribe", fake_transcribe)

    async def run() -> None:
        pipe._ensure_worker()
        # Two different speakers queued back to back: the first pick leaves
        # one still waiting (behind), the second finds the queue empty.
        pipe._work.put_nowait((_pcm(2_000), 2.0, 0.0, "Ali"))
        pipe._work.put_nowait((_pcm(2_000), 2.0, 2.0, "Sara"))
        await pipe._work.join()

    asyncio.run(run())
    assert modes == [True, False]


# ── Segmentation: coughs vs speech ──────────────────────────────────────


def test_a_short_click_followed_by_a_long_pause_is_not_transcribed(pipeline) -> None:
    pipe, windows, said = pipeline

    async def run() -> None:
        await pipe.add_chunk(_pcm(200))  # well under MIN_SPEECH_MS
        for _ in range(int(SILENCE_HANG_MS / 200) + 3):
            await pipe.add_chunk(_pcm(200, amplitude=0))
        await pipe.flush()
        await _settle(pipe)

    asyncio.run(run())
    assert 200 < MIN_SPEECH_MS
    assert windows == []


# ── Loudness normalisation ──────────────────────────────────────────────


def test_quiet_speech_is_brought_up_to_a_workable_level() -> None:
    quiet = _pcm(1_000, amplitude=400)
    assert _rms(_normalize_level(quiet)) > _rms(quiet) * 3


def test_loud_audio_is_left_exactly_as_captured() -> None:
    loud = _pcm(1_000, amplitude=9_000)
    assert _normalize_level(loud) == loud


def test_normalisation_never_clips() -> None:
    import array

    quiet_with_a_spike = bytearray(_pcm(1_000, amplitude=300))
    quiet_with_a_spike[100:102] = struct.pack("<h", 20_000)
    out = array.array("h", _normalize_level(bytes(quiet_with_a_spike)))
    assert max(abs(x) for x in out) <= 32_767


def test_silence_is_returned_untouched() -> None:
    silent = _pcm(500, amplitude=0)
    assert _normalize_level(silent) == silent


# ── Meeting end: the last utterance must not be lost ────────────────────


def test_finalizing_waits_for_an_utterance_that_is_mid_transcription(monkeypatch) -> None:
    pipe = LiveMeetingPipeline(meeting_id=1)
    finished: list[str] = []

    async def slow_transcribe(pcm_data, duration, start_at, speaker) -> list[str]:
        await asyncio.sleep(0.3)
        finished.append("last words")
        return []

    monkeypatch.setattr(pipe, "_transcribe", slow_transcribe)

    async def run() -> None:
        pipe._ensure_worker()
        pipe._work.put_nowait((_pcm(2_000), 2.0, 0.0, "Ali"))
        await asyncio.sleep(0.05)  # the worker has taken it out of the queue
        assert pipe._work.empty()
        await pipe._drain(5)

    asyncio.run(run())
    # The queue looked empty, but the final window was still being decoded —
    # the drain has to wait for it, not return early and let it be cancelled.
    assert finished == ["last words"]


def test_a_long_utterance_is_cut_at_the_next_short_breath_not_mid_word(pipeline) -> None:
    pipe, windows, said = pipeline

    async def run() -> None:
        for _ in range(int(SOFT_CUT_AFTER_MS / 200) + 2):  # past the soft-cut point
            await pipe.add_chunk(_pcm(200))
        # A breath far shorter than the normal end-of-utterance pause.
        for _ in range(int(SOFT_HANG_MS / 200) + 1):
            await pipe.add_chunk(_pcm(200, amplitude=0))
        await _settle(pipe)

    asyncio.run(run())
    assert SOFT_HANG_MS < SILENCE_HANG_MS
    assert len(windows) == 1
    assert windows[0] < MAX_UTTERANCE_MS / 1000  # ended on the breath, not the hard cap


def test_a_short_breath_does_not_end_a_short_utterance(pipeline) -> None:
    pipe, windows, said = pipeline

    async def run() -> None:
        for _ in range(10):  # 2s of speech, nowhere near the soft-cut point
            await pipe.add_chunk(_pcm(200))
        for _ in range(int(SOFT_HANG_MS / 200) + 1):
            await pipe.add_chunk(_pcm(200, amplitude=0))

    asyncio.run(run())
    assert windows == []  # still waiting for a real pause
