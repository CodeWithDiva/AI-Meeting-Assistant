"""How the meeting agent listens — shared by the browser bot and attach mode.

Both `BrowserMeetingBot` (joins the meeting itself) and `CaptureSession`
(attach mode — you join, the assistant only listens) need to turn "what this
machine is playing" into PCM audio. They use the *same* source so the two
cannot drift apart, and so a fix here helps both:

    loopback (default) — WASAPI loopback of the speaker/headphone output, with
        the configured microphone mixed in. Nothing to reroute: whatever
        Windows already plays through the normal output device is captured,
        which is also where the bot's own Chromium window sends the meeting.
        This replaced a cable-only design that required Windows' *system
        default playback device* to be repointed at a virtual cable — that
        works, but it silences every other app (including the user's own Zoom
        client) for as long as the bot runs.

    cable — capture from BOT_MIC_CAPTURE_DEVICE, a virtual audio cable's
        recording side. Set BOT_CAPTURE_MODE=cable to use it; see
        docs/browser-bot-setup.md for the OS routing it needs.
"""

from __future__ import annotations

import os

from app.audio.device_io import MicCaptureStream

BOT_MIC_CAPTURE_DEVICE = os.getenv("BOT_MIC_CAPTURE_DEVICE") or None
BOT_SPEAKER_PLAYBACK_DEVICE = os.getenv("BOT_SPEAKER_PLAYBACK_DEVICE") or None

CAPTURE_MODE = os.getenv("BOT_CAPTURE_MODE", "loopback").strip().lower()
# Blank = loop back whatever the current default output device is.
LOOPBACK_DEVICE = os.getenv("BOT_LOOPBACK_DEVICE") or None
# Loopback alone carries only the *other* participants — your own voice is
# never played back to you — so the mic is captured too and mixed in.
MIX_MIC = os.getenv("BOT_MIX_MIC", "true").strip().lower() not in {"0", "false", "no"}
# Which input device is the mic. Blank = the Windows default input device.
MIC_INPUT_DEVICE = os.getenv("BOT_MIC_INPUT_DEVICE") or None


def build_capture_stream(
    mic_speaker_name: str = "You",
    other_speaker_name: str = "Participant",
    mix_mic: bool | None = None,
) -> MicCaptureStream:
    """Build (but do not start) the configured capture stream.

    `mix_mic` overrides BOT_MIX_MIC for one caller. The bot that joins a
    meeting itself passes False: everyone in the call — including the person
    running it — already reaches the bot's own browser through the meeting, so
    also mixing in a local microphone only adds a constant hiss (measured RMS
    ~180 on a phone-as-microphone), doubles the user's voice, and hands
    Whisper noise to invent words for.
    """
    if CAPTURE_MODE == "cable":
        return MicCaptureStream(BOT_MIC_CAPTURE_DEVICE)

    return MicCaptureStream(
        LOOPBACK_DEVICE,
        loopback=True,
        mix_mic=MIX_MIC if mix_mic is None else mix_mic,
        mic_device=MIC_INPUT_DEVICE,
        mic_speaker_name=mic_speaker_name,
        other_speaker_name=other_speaker_name,
    )


def capture_device_hint() -> str:
    """One-line explanation of the active source, for error messages."""
    if CAPTURE_MODE == "cable":
        return (
            f"capture device {BOT_MIC_CAPTURE_DEVICE!r} (BOT_CAPTURE_MODE=cable). "
            "Check BOT_MIC_CAPTURE_DEVICE in .env against "
            "`python scripts/list_audio_devices.py`."
        )
    return (
        "speaker loopback capture. Set BOT_LOOPBACK_DEVICE in .env to the exact "
        "name of the device you hear the meeting on (see "
        "`python scripts/list_audio_devices.py`), or set BOT_CAPTURE_MODE=cable "
        "to use a virtual audio cable instead."
    )
