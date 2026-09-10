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
import threading
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


def _to_mono_16k(pcm: bytes, channels: int, src_rate: int, dst_rate: int) -> bytes:
    """Downmix interleaved PCM16 to mono, then resample to the target rate."""
    if channels > 1:
        import numpy as np

        usable = len(pcm) - (len(pcm) % (2 * channels))
        frames = np.frombuffer(pcm[:usable], dtype=np.int16).reshape(-1, channels)
        pcm = frames.mean(axis=1).astype(np.int16).tobytes()
    return resample_pcm16(pcm, src_rate, dst_rate)


class MicCaptureStream:
    """Continuously records PCM16 mono audio from a device.

    Two capture modes:

    * ``loopback=False`` (default) — record from an *input* device, e.g. a
      virtual audio cable's recording side.
    * ``loopback=True`` — WASAPI loopback capture of an *output* device: record
      whatever is being played through the speakers/headphones the user already
      listens on, with no rerouting. This is what "attach mode" uses so the
      user does not have to change their Windows or Zoom audio settings.

    With ``loopback=True`` and ``mix_mic=True``, the user's own microphone is
    captured as well and summed in — loopback alone only carries the *other*
    participants (your own voice is never played back to you), so without this
    a solo speaker records as silence.
    """

    def __init__(
        self,
        device_name: str | None,
        sample_rate: int = SAMPLE_RATE,
        *,
        loopback: bool = False,
        mix_mic: bool = False,
        mic_device: str | None = None,
    ) -> None:
        self.device_name = device_name or None
        self.loopback = loopback
        self.mix_mic = mix_mic and loopback
        self.mic_device = mic_device or None
        self.device_index: int | None = None
        # What the pipeline receives. `capture_rate` is what the hardware
        # actually runs at, which may differ.
        self.sample_rate = sample_rate
        self.capture_rate = sample_rate
        self._capture_channels = CHANNELS
        self._stream = None
        self._mic_stream = None
        self._queue: "queue.Queue[bytes]" = queue.Queue()
        self._mic_queue: "queue.Queue[bytes]" = queue.Queue()
        self._running = False

    def start(self) -> None:
        """Open the capture stream on the configured device.

        Raises rather than falling back to a default device: recording the
        wrong source is worse than not recording, because the meeting would
        appear to work while producing a transcript of the wrong audio.
        """
        import sounddevice as sd  # lazy import — optional dependency

        if self.loopback:
            self._start_loopback(sd)
            if self.mix_mic:
                self._start_mic_input(sd)
            return

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

    def _start_mic_input(self, sd) -> None:  # noqa: ANN001
        """Capture the user's own microphone alongside the loopback stream.

        Failure here is non-fatal: loopback (the other participants) still
        works, we just won't have the user's own voice.
        """
        try:
            index = resolve_device(self.mic_device, want_input=True) if self.mic_device else None
            info = sd.query_devices(index if index is not None else sd.default.device[0])
            mic_rate = int(info["default_samplerate"] or self.sample_rate)

            def _cb(indata, frames, time_info, status) -> None:  # noqa: ANN001
                self._mic_queue.put(resample_pcm16(bytes(indata), mic_rate, self.sample_rate))

            self._mic_stream = sd.RawInputStream(
                samplerate=mic_rate,
                channels=1,
                dtype="int16",
                blocksize=int(mic_rate * BLOCK_MS / 1000),
                device=index,
                callback=_cb,
            )
            self._mic_stream.start()
            logger.info(
                "Also capturing your microphone ('%s') for attach mode.", info["name"]
            )
        except Exception:
            logger.warning(
                "Could not open the microphone for attach mode — only the other "
                "participants' audio will be transcribed.", exc_info=True,
            )
            self._mic_stream = None

    def _start_loopback(self, sd) -> None:  # noqa: ANN001
        """Record the system's playback via WASAPI loopback — no rerouting.

        Captures exactly what the user hears (their meeting audio) straight off
        the output device, so no Windows or Zoom audio setting has to change.
        Uses the `soundcard` library, which exposes WASAPI loopback across
        sounddevice versions. Audio is downmixed to mono and resampled to the
        pipeline's 16 kHz.
        """
        try:
            import soundcard as sc
        except ModuleNotFoundError as exc:
            raise DeviceNotFoundError(
                "Loopback capture needs the 'soundcard' package "
                "(pip install soundcard), or set BOT_CAPTURE_MODE=cable."
            ) from exc

        loopback_mics = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
        if not loopback_mics:
            raise DeviceNotFoundError("No WASAPI loopback device is available.")

        mic = None
        if self.device_name:
            wanted = self.device_name.strip().casefold()
            mic = next(
                (m for m in loopback_mics if m.name.strip().casefold() == wanted),
                next((m for m in loopback_mics if wanted in m.name.casefold()), None),
            )
            if mic is None:
                raise DeviceNotFoundError(
                    f"No loopback device matches {self.device_name!r}. Available: "
                    + ", ".join(m.name for m in loopback_mics)
                )
        else:
            # Default: loop back the current default speaker — what the user hears.
            try:
                default_name = sc.default_speaker().name.strip().casefold()
                mic = next(
                    (m for m in loopback_mics if default_name in m.name.casefold()), None
                )
            except Exception:
                mic = None
            mic = mic or loopback_mics[0]

        self._sc_mic = mic
        self.capture_rate = self.sample_rate  # soundcard resamples for us
        self._capture_channels = 1
        self._running = True
        self._sc_thread = threading.Thread(
            target=self._loopback_loop, name="loopback-capture", daemon=True
        )
        self._sc_thread.start()
        logger.info("Loopback capture started on '%s'.", mic.name)

    def _loopback_loop(self) -> None:
        """Blocking soundcard recorder → resampled mono PCM16 into the queue."""
        import warnings

        import numpy as np

        # soundcard talks to WASAPI through COM, which must be initialised on
        # whatever thread uses it — this one.
        try:
            import comtypes

            comtypes.CoInitialize()
            _com = True
        except Exception:
            _com = False

        # soundcard warns on every buffer gap; in a long meeting that is noise.
        warnings.filterwarnings("ignore", message="data discontinuity in recording")

        # Record in ~0.5 s blocks (fewer WASAPI round-trips = fewer gaps), then
        # hand the pipeline its usual small chunks.
        block = int(self.sample_rate * 0.5)
        emit = int(self.sample_rate * BLOCK_MS / 1000) * 2  # bytes per pipeline chunk
        try:
            with self._sc_mic.recorder(samplerate=self.sample_rate, channels=1) as rec:
                buf = bytearray()
                while self._running:
                    data = rec.record(numframes=block)  # float32 (frames, 1)
                    mono = np.clip(data[:, 0] * 32767.0, -32768, 32767).astype(np.int16)
                    buf.extend(mono.tobytes())
                    while len(buf) >= emit:
                        self._queue.put(bytes(buf[:emit]))
                        del buf[:emit]
        except Exception:
            logger.exception("Loopback capture loop crashed")
            self._running = False
        finally:
            if _com:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass

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
        thread = getattr(self, "_sc_thread", None)
        if thread is not None:
            thread.join(timeout=2.0)
            self._sc_thread = None
        for stream in (self._stream, self._mic_stream):
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    logger.exception("Error while stopping a capture stream")
        self._stream = self._mic_stream = None
        logger.info("Mic capture stopped")

    async def chunks(self) -> AsyncIterator[bytes]:
        """Async-yield PCM16 mono chunks until stop() is called.

        In mixed mode, each loopback chunk (the other participants) is summed
        with any microphone audio (the user) that arrived alongside it, so a
        single transcript carries both sides of the conversation.
        """
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                chunk = await loop.run_in_executor(None, self._queue.get, True, 0.5)
            except queue.Empty:
                continue
            if self.mix_mic:
                chunk = self._mix_in_mic(chunk)
            yield chunk

    def _mix_in_mic(self, loopback_chunk: bytes) -> bytes:
        """Sum the user's mic audio into a loopback chunk, clamping to int16."""
        import numpy as np

        mic = bytearray()
        want = len(loopback_chunk)
        while len(mic) < want:
            try:
                mic.extend(self._mic_queue.get_nowait())
            except queue.Empty:
                break
        if not mic:
            return loopback_chunk

        n = min(want, len(mic))
        a = np.frombuffer(loopback_chunk[:n], dtype=np.int16).astype(np.int32)
        b = np.frombuffer(bytes(mic[:n]), dtype=np.int16).astype(np.int32)
        mixed = np.clip(a + b, -32768, 32767).astype(np.int16)
        # Keep any loopback tail beyond what the mic covered.
        return mixed.tobytes() + loopback_chunk[n:]


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
