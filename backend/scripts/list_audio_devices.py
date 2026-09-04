"""List every audio device sounddevice can see.

Run this AFTER installing your virtual audio cable (see
docs/browser-bot-setup.md) to find the exact device names to put in your
.env file for BOT_MIC_CAPTURE_DEVICE and BOT_SPEAKER_PLAYBACK_DEVICE.

Usage (from backend/ with the venv activated):
    python scripts/list_audio_devices.py
"""

from app.audio.device_io import list_devices


def main() -> None:
    devices = list_devices()
    print(f"{'idx':>4}  {'in':>3}  {'out':>3}  name")
    print("-" * 60)
    for d in devices:
        print(f"{d['index']:>4}  {d['max_input_channels']:>3}  {d['max_output_channels']:>3}  {d['name']}")
    print()
    print("Copy the exact 'name' of your virtual cable's recording side into")
    print("BOT_MIC_CAPTURE_DEVICE, and its playback side into")
    print("BOT_SPEAKER_PLAYBACK_DEVICE in your .env file.")


if __name__ == "__main__":
    main()
