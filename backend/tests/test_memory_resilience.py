"""Live transcription when the machine is short on RAM.

Seen on the real machine: 654 MB free of 16 GB, `small` failing to load and an
utterance lost mid-decode with `mkl_malloc: failed to allocate memory`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import memory_guard
from app.transcription import base
from app.transcription.base import FasterWhisperService, _is_out_of_memory


@pytest.fixture(autouse=True)
def _clean_model_state():
    base._MODEL_CACHE.clear()
    base._MODEL_FAILED_AT.clear()
    yield
    base._MODEL_CACHE.clear()
    base._MODEL_FAILED_AT.clear()


def test_the_ways_ctranslate2_reports_running_out_of_memory_are_recognised() -> None:
    assert _is_out_of_memory(RuntimeError("mkl_malloc: failed to allocate memory"))
    assert _is_out_of_memory(RuntimeError("Out of memory"))
    assert _is_out_of_memory(MemoryError())
    assert not _is_out_of_memory(RuntimeError("something else broke"))


def _install_fake_whisper(monkeypatch, fail_sizes: set[str]):
    import faster_whisper

    loaded: list[str] = []

    class FakeModel:
        def __init__(self, size, **kwargs) -> None:  # noqa: ANN001
            if size in fail_sizes:
                raise RuntimeError("mkl_malloc: failed to allocate memory")
            self.size = size
            loaded.append(size)

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    return loaded


def test_a_model_that_cannot_load_falls_back_without_replacing_it_forever(monkeypatch) -> None:
    fail = {"small"}
    loaded = _install_fake_whisper(monkeypatch, fail)
    svc = FasterWhisperService(model_size="small")

    stand_in = svc._load_model("small")
    assert stand_in.size == "base"
    # The stand-in is stored as itself — not under the name of the model that
    # failed, which is what used to strand the server on `base` permanently.
    assert "small" not in base._MODEL_CACHE
    assert "base" in base._MODEL_CACHE

    # Memory frees up and the cooldown passes: the real one loads this time.
    fail.clear()
    base._MODEL_FAILED_AT["small"] = -1e9
    assert svc._load_model("small").size == "small"
    assert "small" not in base._MODEL_FAILED_AT


def test_a_recent_load_failure_is_not_retried_immediately(monkeypatch) -> None:
    loaded = _install_fake_whisper(monkeypatch, {"small"})
    svc = FasterWhisperService(model_size="small")

    svc._load_model("small")
    attempts_after_first = loaded.count("small")
    svc._load_model("small")
    # Went straight to the fallback the second time instead of failing again.
    assert loaded.count("small") == attempts_after_first == 0


def test_a_decode_that_runs_out_of_memory_is_retried_with_the_quick_model(monkeypatch) -> None:
    svc = FasterWhisperService(model_size="small")
    models = {"small": SimpleNamespace(size="small"), "base": SimpleNamespace(size="base")}
    monkeypatch.setattr(svc, "_load_model", lambda size=None: models[size or "small"])

    calls: list[str] = []

    def fake_decode(model, audio_path, target):  # noqa: ANN001
        calls.append(model.size)
        if model.size == "small":
            raise RuntimeError("mkl_malloc: failed to allocate memory")
        return [], ["salam"], SimpleNamespace(language_probability=0.9)

    monkeypatch.setattr(svc, "_decode", fake_decode)

    result = svc._transcribe_blocking(Path("window.wav"), "ur")
    assert calls == ["small", "base"]
    assert result.full_text == "salam"


def test_other_decode_errors_still_surface(monkeypatch) -> None:
    svc = FasterWhisperService(model_size="small")
    monkeypatch.setattr(svc, "_load_model", lambda size=None: SimpleNamespace(size=size))

    def broken(model, audio_path, target):  # noqa: ANN001
        raise RuntimeError("corrupt audio")

    monkeypatch.setattr(svc, "_decode", broken)
    with pytest.raises(RuntimeError, match="corrupt audio"):
        svc._transcribe_blocking(Path("window.wav"), "ur")


def test_when_the_quick_model_itself_runs_out_of_memory_the_error_surfaces(monkeypatch) -> None:
    svc = FasterWhisperService(model_size="base")  # nothing smaller to fall back to
    monkeypatch.setattr(svc, "_load_model", lambda size=None: SimpleNamespace(size=size))

    def oom(model, audio_path, target):  # noqa: ANN001
        raise RuntimeError("mkl_malloc: failed to allocate memory")

    monkeypatch.setattr(svc, "_decode", oom)
    with pytest.raises(RuntimeError):
        svc._transcribe_blocking(Path("window.wav"), "en")


# ── Warning about low RAM (never touching the language model) ─────────────


def test_free_ram_can_be_read_on_this_machine() -> None:
    free = memory_guard.free_ram_mb()
    assert free is None or free > 0


def test_no_warning_when_there_is_plenty_of_ram(monkeypatch) -> None:
    monkeypatch.setattr(memory_guard, "free_ram_mb", lambda: memory_guard.MIN_FREE_RAM_MB + 5_000)
    assert memory_guard.low_memory_warning() is None


def test_a_warning_names_the_free_ram_and_what_to_do(monkeypatch) -> None:
    monkeypatch.setattr(memory_guard, "free_ram_mb", lambda: 600)
    message = memory_guard.low_memory_warning()
    assert message and "600 MB" in message and "close" in message.lower()


def test_an_unreadable_memory_figure_never_breaks_the_join(monkeypatch) -> None:
    def boom() -> int:
        raise OSError("no access")

    monkeypatch.setattr(memory_guard, "free_ram_mb", boom)
    assert memory_guard.low_memory_warning() is None


def test_the_guard_never_talks_to_ollama() -> None:
    # Unloading the 7B model to make room could not be undone while the
    # browsers still held the RAM (Ollama: "unable to allocate CPU_REPACK
    # buffer"), which took every answer and the meeting notes down with it.
    assert not hasattr(memory_guard, "httpx")
    assert not hasattr(memory_guard, "make_room_for_transcription")
