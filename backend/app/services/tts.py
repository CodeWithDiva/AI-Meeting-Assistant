"""Text-to-Speech (TTS) synthesis service.

Priority chain:
  1. Piper TTS  — if PIPER_PATH env var points to a valid piper binary
  2. edge-tts   — free Microsoft neural voices, incl. a real Urdu voice
  3. pyttsx3    — cross-platform offline TTS (last resort — see below)
  4. Silent WAV — valid WAV header with silence (safe fallback)

Why edge-tts sits above pyttsx3: pyttsx3 on Windows only ever has whatever
SAPI5 voices are installed system-wide, which is English (and whatever else
happens to be installed) on an ordinary machine — never Urdu. Measured on the
dev machine: asking it to speak Urdu text produced a 46-byte WAV (silence) —
Alina looked like she never answered, every single time the reply was Urdu.
edge-tts ships a real Urdu voice (ur-PK-UzmaNeural) and needs no local voice
pack, only internet (already assumed — the meeting itself is a live web call)
plus ffmpeg on PATH to turn its mp3 output into the WAV the rest of the audio
pipeline expects. pyttsx3 stays as the offline fallback for when either is
unavailable, so a dropped connection mid-meeting still gets an English reply
rather than silence.
"""

import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import wave

logger = logging.getLogger(__name__)

_PIPER_PATH = os.getenv("PIPER_PATH", "")
_PIPER_MODEL = os.getenv("PIPER_MODEL", "")  # e.g. /path/to/en_US-lessac-medium.onnx

# Neural voices, not a system voice pack — this is what actually gets Urdu
# speech out of the assistant. Override either with your own pick from
# `edge-tts --list-voices`.
_EDGE_VOICE_UR = os.getenv("EDGE_TTS_VOICE_UR", "ur-PK-UzmaNeural")
_EDGE_VOICE_EN = os.getenv("EDGE_TTS_VOICE_EN", "en-US-AriaNeural")
_EDGE_TIMEOUT_S = 20  # a stalled connection must not hang a live meeting reply

_URDU_SCRIPT = re.compile(r"[؀-ۿ]")


class TTSService:
    """Offline-first TTS synthesis engine, with a real Urdu voice available."""

    def synthesize_speech_wav(self, text: str) -> bytes:
        """Synthesize text into WAV audio bytes using the best available engine."""

        # --- 1. Piper TTS (highest quality, optional) ---
        piper_wav = self._try_piper(text)
        if piper_wav:
            logger.debug("TTS via Piper (%d bytes)", len(piper_wav))
            return piper_wav

        # --- 2. edge-tts (free neural voices, real Urdu support) ---
        edge_wav = self._try_edge_tts(text)
        if edge_wav:
            logger.debug("TTS via edge-tts (%d bytes)", len(edge_wav))
            return edge_wav

        # --- 3. pyttsx3 (offline fallback — Urdu text will come out silent) ---
        pyttsx3_wav = self._try_pyttsx3(text)
        if pyttsx3_wav:
            logger.debug("TTS via pyttsx3 (%d bytes)", len(pyttsx3_wav))
            return pyttsx3_wav

        # --- 4. Silent WAV fallback ---
        logger.debug("TTS fallback: returning silent WAV")
        return self._silent_wav()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _try_piper(self, text: str) -> bytes | None:
        """Run Piper binary to produce WAV bytes, return None on any error."""
        if not _PIPER_PATH or not os.path.isfile(_PIPER_PATH):
            return None
        if not _PIPER_MODEL or not os.path.isfile(_PIPER_MODEL):
            logger.warning("PIPER_PATH set but PIPER_MODEL not found — skipping Piper TTS")
            return None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            result = subprocess.run(
                [
                    _PIPER_PATH,
                    "--model", _PIPER_MODEL,
                    "--output_file", tmp_path,
                ],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=15,
            )
            if result.returncode != 0:
                logger.warning("Piper TTS failed: %s", result.stderr.decode())
                return None

            with open(tmp_path, "rb") as f:
                wav_bytes = f.read()

            try:
                os.remove(tmp_path)
            except OSError:
                pass

            return wav_bytes if wav_bytes else None
        except Exception as exc:
            logger.debug("Piper TTS error: %s", exc)
            return None

    def _try_edge_tts(self, text: str) -> bytes | None:
        """Synthesize with edge-tts (mp3), then convert to WAV via ffmpeg.

        Picks the Urdu voice whenever the text contains Urdu/Arabic-script
        characters, English otherwise — Roman Urdu is Latin script, so it
        goes through the English voice, which reads it phonetically rather
        than silently failing the way pyttsx3's SAPI5 voice does.
        """
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            logger.debug("ffmpeg not on PATH — skipping edge-tts (mp3 can't become WAV).")
            return None

        try:
            import asyncio

            import edge_tts
        except ImportError:
            return None

        voice = _EDGE_VOICE_UR if _URDU_SCRIPT.search(text) else _EDGE_VOICE_EN
        mp3_path = wav_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                mp3_path = tmp.name

            async def _speak() -> None:
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(mp3_path)

            asyncio.run(asyncio.wait_for(_speak(), timeout=_EDGE_TIMEOUT_S))

            if not os.path.getsize(mp3_path):
                return None

            wav_path = mp3_path[:-4] + ".wav"
            result = subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", mp3_path,
                 "-ar", "16000", "-ac", "1", wav_path],
                capture_output=True,
                timeout=15,
            )
            if result.returncode != 0:
                logger.warning("ffmpeg mp3->wav conversion failed: %s", result.stderr.decode(errors="replace"))
                return None

            with open(wav_path, "rb") as f:
                wav_bytes = f.read()
            return wav_bytes if wav_bytes else None
        except Exception as exc:
            # Network hiccup, DNS failure, Microsoft's endpoint rejecting the
            # request — none of this should ever break an in-meeting reply;
            # pyttsx3 (English) or silence is still a graceful fallback.
            logger.debug("edge-tts error: %s", exc)
            return None
        finally:
            for path in (mp3_path, wav_path):
                if path:
                    try:
                        os.remove(path)
                    except OSError:
                        pass

    def _try_pyttsx3(self, text: str) -> bytes | None:
        """Use pyttsx3 to synthesize speech, return None if not available."""
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", 160)
            engine.setProperty("volume", 0.9)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            engine.save_to_file(text, tmp_path)
            engine.runAndWait()

            with open(tmp_path, "rb") as f:
                wav_bytes = f.read()

            try:
                os.remove(tmp_path)
            except OSError:
                pass

            return wav_bytes if wav_bytes else None
        except Exception as exc:
            logger.debug("pyttsx3 not available: %s", exc)
            return None

    def _silent_wav(self, duration_seconds: float = 0.5) -> bytes:
        """Return a valid silent WAV as a last-resort fallback."""
        buf = io.BytesIO()
        sample_rate = 16_000
        with wave.open(buf, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"\x00\x00" * int(sample_rate * duration_seconds))
        return buf.getvalue()
