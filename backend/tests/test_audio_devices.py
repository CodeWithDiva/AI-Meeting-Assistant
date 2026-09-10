"""Tests for audio device resolution and sample-rate conversion."""

from __future__ import annotations

import math
import struct

import pytest

from app.audio.device_io import (
    SAMPLE_RATE,
    DeviceNotFoundError,
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
