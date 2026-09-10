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


class DeviceNotFoundError(RuntimeError):
    """Raised when a configured audio device name matches nothing available."""


def resolve_device(
    name: str | int | None,
    *,
    want_input: bool,
    samplerate: int | None = None,
) -> int | None:
    """Resolve a device name to a concrete device index.

    Passing a bare name to sounddevice is unreliable on Windows: the same
    virtual cable is exposed once per host API (MME, DirectSound, WASAPI, …),
    so a name like "CABLE Output (VB-Audio Virtual Cable)" is *ambiguous* and
    sounddevice refuses it. Silently falling back to the default device then
    makes the bot record the laptop's own microphone instead of the meeting —
    a failure that produces plausible-looking but completely wrong transcripts.

    Host API choice also matters: WASAPI runs shared-mode streams at the
    device's native rate and rejects anything else, while DirectSound and MME
    resample for us. So when `samplerate` is given, endpoints that actually
    accept it are preferred over the "modern" one that does not.

    Returns None when `name` is empty, meaning "use the system default".

    Raises:
        DeviceNotFoundError: nothing matches the configured name.
    """
    import sounddevice as sd

    if name is None or name == "":
        return None
    if isinstance(name, int) or (isinstance(name, str) and name.strip().isdigit()):
        return int(name)

    wanted = name.strip().casefold()
    channel_key = "max_input_channels" if want_input else "max_output_channels"
    host_apis = sd.query_hostapis()

    exact: list[tuple[int, str]] = []
    partial: list[tuple[int, str]] = []
    for index, info in enumerate(sd.query_devices()):
        if info[channel_key] < 1:
            continue
        device_name = info["name"].strip()
        host = host_apis[info["hostapi"]]["name"]
        if device_name.casefold() == wanted:
            exact.append((index, host))
        elif wanted in device_name.casefold():
            partial.append((index, host))

    candidates = exact or partial
    if not candidates:
        direction = "input" if want_input else "output"
        raise DeviceNotFoundError(
            f"No {direction} device matches {name!r}. Run "
            f"`python backend/scripts/list_audio_devices.py` and copy an exact name "
            f"into your .env."
        )

    if samplerate:
        usable = [c for c in candidates if _supports(c[0], samplerate, want_input)]
        if usable:
            candidates = usable
        else:
            logger.info(
                "No endpoint for %r accepts %d Hz — will capture at its native rate "
                "and resample.", name, samplerate,
            )

    for index, host in candidates:
        if "wasapi" in host.casefold():
            logger.info("Resolved audio device %r to index %d (%s).", name, index, host)
            return index

    index, host = candidates[0]
    logger.info("Resolved audio device %r to index %d (%s).", name, index, host)
    return index


def _supports(index: int, samplerate: int, want_input: bool) -> bool:
    """Whether a device endpoint can open a mono stream at this rate."""
    import sounddevice as sd

    check = sd.check_input_settings if want_input else sd.check_output_settings
    try:
        check(device=index, channels=CHANNELS, dtype="int16", samplerate=samplerate)
        return True
    except Exception:
        return False


def resample_pcm16(pcm_data: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Convert mono PCM16 between sample rates.

    Whole-number ratios (48k → 16k, the common case for virtual cables) are
    averaged in blocks, which both decimates and crudely low-passes; other
    ratios fall back to linear interpolation. Good enough for speech going into
    Whisper, and avoids taking on a scipy dependency for one function.
    """
    if src_rate == dst_rate or not pcm_data:
        return pcm_data

    import numpy as np

    samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return pcm_data

    if src_rate % dst_rate == 0:
        factor = src_rate // dst_rate
        usable = samples.size - (samples.size % factor)
        if usable == 0:
            return b""
        converted = samples[:usable].reshape(-1, factor).mean(axis=1)
    else:
        count = max(1, int(round(samples.size * dst_rate / src_rate)))
        converted = np.interp(
            np.linspace(0, samples.size - 1, count),
            np.arange(samples.size),
            samples,
        )

    return converted.astype(np.int16).tobytes()


class MicCaptureStream:
    """Continuously records PCM16 mono audio from a named input device."""

    def __init__(self, device_name: str | None, sample_rate: int = SAMPLE_RATE) -> None:
        self.device_name = device_name or None
        self.device_index: int | None = None
        # What the pipeline receives. `capture_rate` is what the hardware
        # actually runs at, which may differ.
        self.sample_rate = sample_rate
        self.capture_rate = sample_rate
        self._stream = None
        self._queue: "queue.Queue[bytes]" = queue.Queue()
        self._running = False

    def start(self) -> None:
        """Open the input stream on the configured device.

        Raises rather than falling back to the default microphone: recording
        the wrong device is worse than not recording, because the meeting would
        appear to work while producing a transcript of the wrong room.
        """
        import sounddevice as sd  # lazy import — optional dependency

        self.device_index = resolve_device(
            self.device_name, want_input=True, samplerate=self.sample_rate
        )
        self.capture_rate = self._pick_capture_rate(sd)

        def _callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
            if status:
                logger.debug("Mic capture status: %s", status)
            self._queue.put(
                resample_pcm16(bytes(indata), self.capture_rate, self.sample_rate)
            )

        self._stream = sd.RawInputStream(
            samplerate=self.capture_rate,
            channels=CHANNELS,
            dtype="int16",
            blocksize=int(self.capture_rate * BLOCK_MS / 1000),
            device=self.device_index,
            callback=_callback,
        )
        self._stream.start()
        self._running = True
        logger.info(
            "Mic capture started on %s (index %s) at %d Hz%s.",
            self.device_name or "system default input",
            self.device_index,
            self.capture_rate,
            f", resampled to {self.sample_rate} Hz" if self.capture_rate != self.sample_rate else "",
        )

    def _pick_capture_rate(self, sd) -> int:  # noqa: ANN001
        """Use the requested rate if the endpoint accepts it, else its native one.

        WASAPI shared-mode streams only run at the device's own rate, so asking
        for 16 kHz there fails outright; capturing native and resampling keeps
        the pipeline's contract intact either way.
        """
        if self.device_index is None or _supports(self.device_index, self.sample_rate, True):
            return self.sample_rate
        native = int(sd.query_devices(self.device_index)["default_samplerate"])
        logger.info(
            "Device %s does not accept %d Hz — capturing at its native %d Hz.",
            self.device_index, self.sample_rate, native,
        )
        return native

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

    sd.play(
        audio,
        samplerate=sample_rate,
        device=resolve_device(device_name, want_input=False),
        blocking=True,
    )


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
