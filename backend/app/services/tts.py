"""Text-to-Speech (TTS) synthesis service.

Priority chain:
  1. Piper TTS  — if PIPER_PATH env var points to a valid piper binary
  2. pyttsx3    — cross-platform offline TTS
  3. Silent WAV — valid WAV header with silence (safe fallback)
"""

import io
import logging
import os
import subprocess
import tempfile
import wave

logger = logging.getLogger(__name__)

_PIPER_PATH = os.getenv("PIPER_PATH", "")
_PIPER_MODEL = os.getenv("PIPER_MODEL", "")  # e.g. /path/to/en_US-lessac-medium.onnx


class TTSService:
    """Offline and lightweight TTS synthesis engine."""

    def synthesize_speech_wav(self, text: str) -> bytes:
        """Synthesize text into WAV audio bytes using the best available engine."""

        # --- 1. Piper TTS (highest quality, optional) ---
        piper_wav = self._try_piper(text)
        if piper_wav:
            logger.debug("TTS via Piper (%d bytes)", len(piper_wav))
            return piper_wav

        # --- 2. pyttsx3 (cross-platform offline) ---
        pyttsx3_wav = self._try_pyttsx3(text)
        if pyttsx3_wav:
            logger.debug("TTS via pyttsx3 (%d bytes)", len(pyttsx3_wav))
            return pyttsx3_wav

        # --- 3. Silent WAV fallback ---
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
