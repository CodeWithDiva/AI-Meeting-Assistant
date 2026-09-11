"""Tests for audio device resolution and sample-rate conversion."""

from __future__ import annotations

import math
import struct

import pytest

import numpy as np

from app.audio.device_io import (
    SAMPLE_RATE,
    DeviceNotFoundError,
    MicCaptureStream,
    resample_pcm16,
    resolve_device,
)


def _tone(rate: int, ms: int, freq: float = 200.0) -> bytes:
    frames = int(rate * ms / 1000)
    return b"".join(
        struct.pack("<h", int(8_000 * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(frames)
    )


# ── Resampling ──────────────────────────────────────────────────────────


def test_same_rate_is_returned_untouched() -> None:
    data = _tone(16_000, 100)
    assert resample_pcm16(data, 16_000, 16_000) is data


def test_empty_audio_survives() -> None:
    assert resample_pcm16(b"", 48_000, 16_000) == b""


@pytest.mark.parametrize("src", [48_000, 32_000, 44_100, 8_000])
def test_conversion_lands_on_the_expected_length(src: int) -> None:
    data = _tone(src, 200)
    converted = resample_pcm16(data, src, SAMPLE_RATE)
    expected_samples = SAMPLE_RATE * 0.2
    actual_samples = len(converted) / 2
    # Whisper is fed fixed-duration windows, so a rate conversion that changed
    # the duration would silently desynchronise every transcript timestamp.
    assert actual_samples == pytest.approx(expected_samples, rel=0.02)


def test_conversion_preserves_the_signal() -> None:
    # A tone must survive downsampling as a tone, not as silence or noise.
    converted = resample_pcm16(_tone(48_000, 200), 48_000, SAMPLE_RATE)
    import numpy as np

    samples = np.frombuffer(converted, dtype=np.int16).astype(np.float32)
    assert float(np.sqrt(np.mean(samples**2))) > 1_000


def test_upsampling_works_too() -> None:
    converted = resample_pcm16(_tone(8_000, 200), 8_000, SAMPLE_RATE)
    assert len(converted) / 2 == pytest.approx(SAMPLE_RATE * 0.2, rel=0.02)


def test_a_ratio_shorter_than_one_output_sample_does_not_crash() -> None:
    # One 48k sample downsampled 3:1 rounds to zero output samples.
    assert resample_pcm16(struct.pack("<h", 100), 48_000, 16_000) == b""


# ── Device resolution ───────────────────────────────────────────────────


def test_no_name_means_system_default() -> None:
    assert resolve_device(None, want_input=True) is None
    assert resolve_device("", want_input=True) is None


def test_a_numeric_name_is_used_as_an_index() -> None:
    assert resolve_device("7", want_input=True) == 7
    assert resolve_device(7, want_input=True) == 7


def test_an_unknown_device_raises_rather_than_silently_defaulting() -> None:
    # Falling back to the default microphone would record the wrong room while
    # looking like it worked, so this must fail loudly.
    with pytest.raises(DeviceNotFoundError) as excinfo:
        resolve_device("No Such Audio Cable 9000", want_input=True)
    assert "list_audio_devices" in str(excinfo.value)


# ── Mixing loopback + mic (attach mode) ─────────────────────────────────


def _mixer() -> MicCaptureStream:
    """A MicCaptureStream ready for _mix_in_mic without opening real hardware."""
    return MicCaptureStream(
        None, loopback=True, mix_mic=True,
        mic_speaker_name="You", other_speaker_name="Participant",
    )


def test_mixing_never_overflows_int16() -> None:
    # Two independently loud sources, naively summed, would wrap/clip.
    loud = _tone(SAMPLE_RATE, 200, freq=300.0)  # amplitude 8000 in _tone()
    import math as _m
    frames = int(SAMPLE_RATE * 0.2)
    mic = b"".join(
        struct.pack("<h", int(30_000 * _m.sin(2 * _m.pi * 300 * i / SAMPLE_RATE)))
        for i in range(frames)
    )
    stream = _mixer()
    stream._mic_queue.put(mic)
    mixed = stream._mix_in_mic(loud)
    samples = np.frombuffer(mixed, dtype=np.int16)
    assert samples.size == frames
    assert int(np.max(np.abs(samples))) <= 32767


def test_mixing_does_not_hard_clip_when_it_could_scale_instead() -> None:
    # Hard-clipping pins a large fraction of samples at exactly the ceiling,
    # which is audible harsh distortion; scaling the whole waveform down
    # avoids that even when both sources peak together.
    import math as _m
    frames = int(SAMPLE_RATE * 0.2)
    loud = b"".join(
        struct.pack("<h", int(30_000 * _m.sin(2 * _m.pi * 300 * i / SAMPLE_RATE)))
        for i in range(frames)
    )
    mic = b"".join(
        struct.pack("<h", int(30_000 * _m.sin(2 * _m.pi * 300 * i / SAMPLE_RATE)))
        for i in range(frames)
    )
    stream = _mixer()
    stream._mic_queue.put(mic)
    mixed = stream._mix_in_mic(loud)
    samples = np.frombuffer(mixed, dtype=np.int16)
    pinned = int(np.sum(np.abs(samples) >= 32767))
    assert pinned / samples.size < 0.05  # hard clipping would pin most of a full-scale sine


def test_mixing_with_no_mic_data_returns_loopback_unchanged() -> None:
    loopback = _tone(SAMPLE_RATE, 100)
    stream = _mixer()
    assert stream._mix_in_mic(loopback) == loopback


def test_speaker_label_follows_the_louder_source() -> None:
    quiet = b"\x00\x00" * int(SAMPLE_RATE * 0.2)
    loud_mic = _tone(SAMPLE_RATE, 200, freq=300.0)

    stream = _mixer()
    stream._mic_queue.put(loud_mic)
    stream._mix_in_mic(quiet)  # loopback quiet, mic loud -> "You"
    assert stream.last_speaker_label == "You"

    stream2 = _mixer()
    loud_loopback = _tone(SAMPLE_RATE, 200, freq=300.0)
    stream2._mix_in_mic(loud_loopback)  # no mic data at all -> loopback dominates
    assert stream2.last_speaker_label == "Participant"


def test_default_speaker_label_before_any_chunk_is_the_other_participant() -> None:
    # Nobody has spoken yet — attributing to "You" by default would be wrong
    # more often than not.
    stream = _mixer()
    assert stream.last_speaker_label == "Participant"
