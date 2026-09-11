"""AI Meeting Assistant backend package.

The project's `.env` is loaded here, before any submodule is imported, because
several modules read their configuration into module-level constants at import
time (the meeting bot's display name, its virtual microphone, the reply audio
device, Whisper's beam size, …). `app.main` and `app.auth` also load `.env`,
but only *after* the routers — and everything they import — have already run,
so those constants were silently taking their built-in defaults: the bot joined
as "Ava Notetaker" instead of the configured name, and its microphone was never
pinned to the reply cable.

`override=False`, so anything already set in the real environment (a test, a
one-off `BOT_HEADLESS=True` run) still wins over the file.
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
