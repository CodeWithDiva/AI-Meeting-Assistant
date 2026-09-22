"""Tests for the TTS engine chain (Piper -> edge-tts -> pyttsx3 -> silence).

edge-tts is the fix for a real, measured bug: pyttsx3 on Windows only has
whatever SAPI5 voices are installed system-wide — on the dev machine that's
English (and Korean), never Urdu, so asking it to speak Urdu text produced a
46-byte (silent) WAV. Alina looked like she never answered any Urdu question.
These tests mock the network call and ffmpeg so they run fast and offline —
proving the *logic* (voice selection, graceful fallback), not the network.
"""

from __future__ import annotations

import subprocess

import pytest

from app.services.tts import TTSService, _EDGE_VOICE_EN, _EDGE_VOICE_UR


class _FakeCommunicate:
    """Stands in for edge_tts.Communicate — records which voice was asked for."""

    last_voice: str | None = None

    def __init__(self, text: str, voice: str) -> None:
        _FakeCommunicate.last_voice = voice
        self._text = text

    async def save(self, path: str) -> None:
        # A real mp3 would go here; content doesn't matter since the fake
        # ffmpeg below just needs a non-empty input file to "convert".
        with open(path, "wb") as f:
            f.write(b"\xff\xfb\x90fake-mp3-bytes")


def _fake_ffmpeg_run(cmd, **kwargs):
    """Stands in for subprocess.run(["ffmpeg", ...]) — writes a real tiny WAV."""
    import wave

    out_path = cmd[-1]
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x01\x00" * 800)  # not silence — real-looking samples
    return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")


@pytest.fixture(autouse=True)
def _reset_fake_voice():
    _FakeCommunicate.last_voice = None
    yield


def _patch_edge_tts_happy_path(monkeypatch):
    monkeypatch.setattr("app.services.tts.shutil.which", lambda name: "C:/fake/ffmpeg.exe")
    monkeypatch.setattr("app.services.tts.subprocess.run", _fake_ffmpeg_run)
    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", _FakeCommunicate)


def test_edge_tts_is_used_and_picks_the_urdu_voice_for_urdu_script(monkeypatch):
    _patch_edge_tts_happy_path(monkeypatch)
    service = TTSService()
    monkeypatch.setattr(service, "_try_piper", lambda text: None)

    wav = service.synthesize_speech_wav("السلام علیکم، میٹنگ کل ہوگی۔")

    assert wav  # real bytes, not the tiny silent-WAV fallback
    assert _FakeCommunicate.last_voice == _EDGE_VOICE_UR


def test_edge_tts_picks_the_english_voice_for_latin_script(monkeypatch):
    _patch_edge_tts_happy_path(monkeypatch)
    service = TTSService()
    monkeypatch.setattr(service, "_try_piper", lambda text: None)

    wav = service.synthesize_speech_wav("Alina, deployment kab hai?")

    assert wav
    assert _FakeCommunicate.last_voice == _EDGE_VOICE_EN


def test_edge_tts_is_skipped_without_ffmpeg_on_path(monkeypatch):
    monkeypatch.setattr("app.services.tts.shutil.which", lambda name: None)
    service = TTSService()

    assert service._try_edge_tts("hello") is None


def test_edge_tts_network_failure_falls_through_cleanly(monkeypatch):
    monkeypatch.setattr("app.services.tts.shutil.which", lambda name: "C:/fake/ffmpeg.exe")
    import edge_tts

    class _BoomCommunicate:
        def __init__(self, text, voice):
            pass

        async def save(self, path):
            raise ConnectionError("network unreachable")

    monkeypatch.setattr(edge_tts, "Communicate", _BoomCommunicate)
    service = TTSService()

    assert service._try_edge_tts("hello") is None


def test_full_chain_falls_back_to_pyttsx3_when_edge_tts_unavailable(monkeypatch):
    service = TTSService()
    monkeypatch.setattr(service, "_try_piper", lambda text: None)
    monkeypatch.setattr(service, "_try_edge_tts", lambda text: None)
    monkeypatch.setattr(service, "_try_pyttsx3", lambda text: b"pyttsx3-audio-bytes")

    assert service.synthesize_speech_wav("hello") == b"pyttsx3-audio-bytes"


def test_full_chain_falls_back_to_silence_when_nothing_is_available(monkeypatch):
    service = TTSService()
    monkeypatch.setattr(service, "_try_piper", lambda text: None)
    monkeypatch.setattr(service, "_try_edge_tts", lambda text: None)
    monkeypatch.setattr(service, "_try_pyttsx3", lambda text: None)

    wav = service.synthesize_speech_wav("hello")

    assert wav == service._silent_wav()
