"""Audio I/O against OS-level virtual audio cable devices.

The browser meeting bot (`app.agents.browser_bot`) does not use Zoom RTMS.
Instead it joins the Zoom Web Client like a normal participant and moves
audio through two virtual audio cable devices that you install once on the
machine running the bot (see docs/browser-bot-setup.md):

    CAPTURE device  — what the bot "hears".
                      Windows' default *playback* device is set to this
                      cable's input side, so everything Zoom plays (other
                      participants talking) is routed here. We *record*
                      from this device's output/recording side.

    PLAYBACK device — what the bot "speaks".
                      We play Ava's synthesized TTS reply into this
                      cable's input side. The browser's microphone is set
                      to this cable's output/recording side, so Zoom picks
                      it up as the bot's own mic — a real, live voice
                      reply inside the meeting.

`sounddevice` / `numpy` are optional runtime dependencies: only the machine
that actually runs the browser bot needs them installed. Every function here
imports them lazily so the rest of the backend keeps working (and existing
tests keep passing) even if they're not installed.
"""

from __future__ import annotations

import asyncio
import logging
import queue
from typing import AsyncIterator

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
CHANNELS = 1
BLOCK_MS = 200  # chunk size handed onward to the Whisper pipeline


class MicCaptureStream:
    """Continuously records PCM16 mono audio from a named input device."""

    def __init__(self, device_name: str | None, sample_rate: int = SAMPLE_RATE) -> None:
        self.device_name = device_name or None
        self.sample_rate = sample_rate
        self._stream = None
        self._queue: "queue.Queue[bytes]" = queue.Queue()
        self._running = False

    def start(self) -> None:
        """Open the input stream. Falls back to system default input device if named device is unavailable."""
        import sounddevice as sd  # lazy import — optional dependency

        def _callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
            if status:
                logger.debug("Mic capture status: %s", status)
            self._queue.put(bytes(indata))

        try:
            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                channels=CHANNELS,
                dtype="int16",
                blocksize=int(self.sample_rate * BLOCK_MS / 1000),
                device=self.device_name,
                callback=_callback,
            )
            self._stream.start()
            self._running = True
            logger.info("Mic capture started on device=%r", self.device_name or "(system default)")
        except Exception as exc:
            if self.device_name is not None:
                logger.warning(
                    "Could not open requested mic device %r (%s). Falling back to system default input device.",
                    self.device_name, exc,
                )
                self.device_name = None
                self._stream = sd.RawInputStream(
                    samplerate=self.sample_rate,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=int(self.sample_rate * BLOCK_MS / 1000),
                    device=None,
                    callback=_callback,
                )
                self._stream.start()
                self._running = True
                logger.info("Mic capture started on system default input device.")
            else:
                raise

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                logger.exception("Error while stopping mic capture stream")
            self._stream = None
        logger.info("Mic capture stopped")

    async def chunks(self) -> AsyncIterator[bytes]:
        """Async-yield PCM16 mono chunks until stop() is called."""
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                chunk = await loop.run_in_executor(None, self._queue.get, True, 0.5)
            except queue.Empty:
                continue
            yield chunk


def play_wav_bytes(wav_bytes: bytes, device_name: str | None) -> None:
    """Blocking playback of WAV bytes through a named output device.

    Call this from a worker thread (e.g. via `run_in_executor`) — it blocks
    until playback finishes so the bot's "voice" isn't cut off mid-sentence.
    """
    import io
    import wave

    import numpy as np
    import sounddevice as sd

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())

    audio = np.frombuffer(raw, dtype=np.int16)
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels)

    sd.play(audio, samplerate=sample_rate, device=device_name, blocking=True)


def list_devices() -> list[dict]:
    """Return every audio device sounddevice can see — used by the setup script
    to find the exact virtual-cable device names for your .env file."""
    import sounddevice as sd

    devices = []
    for index, info in enumerate(sd.query_devices()):
        devices.append(
            {
                "index": index,
                "name": info["name"],
                "max_input_channels": info["max_input_channels"],
                "max_output_channels": info["max_output_channels"],
            }
        )
    return devices
