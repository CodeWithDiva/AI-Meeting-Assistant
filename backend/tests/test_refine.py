"""Unit tests for the pure helpers behind meeting re-transcription (refine.py).

These don't load a Whisper model — they test the block-cutting, speaker
matching and transcript-building logic against synthetic data, which is fast
enough to run every time (unlike a real refine pass on this hardware).
"""

from __future__ import annotations

import numpy as np

from app.services.refine import (
    SAMPLE_RATE,
    assign_speakers,
    build_transcript,
    split_blocks,
)
from app.models import TranscriptSegment as DbTranscriptSegment
from app.transcription.base import TranscriptSegment


def test_split_blocks_short_audio_is_one_block():
    audio = np.zeros(SAMPLE_RATE * 30, dtype="float32")
    assert split_blocks(audio) == [(0, len(audio))]


def test_split_blocks_empty_audio():
    assert split_blocks(np.zeros(0, dtype="float32")) == []


def test_split_blocks_cuts_long_audio_into_multiple_covering_blocks():
    # ~12 minutes: longer than one 5-minute target block plus search window.
    rng = np.random.default_rng(0)
    audio = (rng.standard_normal(SAMPLE_RATE * 12 * 60) * 0.05).astype("float32")
    # Carve in a few quiet gaps so there is an obvious place to cut.
    for start_s in (280, 290, 580, 590):
        audio[start_s * SAMPLE_RATE: start_s * SAMPLE_RATE + SAMPLE_RATE] *= 0.01

    blocks = split_blocks(audio, target_s=300.0, search_s=20.0)

    assert len(blocks) >= 2
    # Blocks must exactly tile the audio: contiguous, no gaps, no overlap.
    assert blocks[0][0] == 0
    assert blocks[-1][1] == len(audio)
    for (_, end), (next_start, _) in zip(blocks, blocks[1:]):
        assert end == next_start


def _segment(text, start, end):
    return TranscriptSegment(text=text, start=start, end=end)


def test_assign_speakers_matches_by_overlap():
    old = [
        DbTranscriptSegment(text="hi", start_time=0.0, end_time=5.0, speaker_label="Ali"),
        DbTranscriptSegment(text="hi", start_time=5.0, end_time=10.0, speaker_label="Sara"),
    ]
    new = [_segment("hello there", 1.0, 4.0), _segment("my turn now", 6.0, 9.0)]

    assert assign_speakers(new, old) == ["Ali", "Sara"]


def test_assign_speakers_falls_back_to_nearest_when_no_overlap():
    old = [DbTranscriptSegment(text="hi", start_time=0.0, end_time=2.0, speaker_label="Ali")]
    new = [_segment("later on", 50.0, 52.0)]

    assert assign_speakers(new, old) == ["Ali"]


def test_assign_speakers_with_no_labelled_history_returns_none():
    new = [_segment("hello", 0.0, 2.0)]
    assert assign_speakers(new, []) == [None]


def test_build_transcript_merges_consecutive_same_speaker_lines():
    segments = [_segment("hello", 0.0, 1.0), _segment("world", 1.0, 2.0), _segment("hi", 2.0, 3.0)]
    speakers = ["Ali", "Ali", "Sara"]

    assert build_transcript(segments, speakers) == "[Ali]: hello world\n[Sara]: hi"


def test_build_transcript_unknown_speaker_labelled_speaker():
    segments = [_segment("hello", 0.0, 1.0)]
    assert build_transcript(segments, [None]) == "[Speaker]: hello"
