"""Point the whole test session at its own throwaway database.

`app.database` reads `DATABASE_URL` once, at import time, and every test
file does `from app.main import app` (or similar) before any test runs. This
module has to set the environment variable before that first import happens
anywhere — pytest guarantees a directory's conftest.py loads before the test
modules in it, so this file is that place.

Without this, tests were running straight against the developer's real
`meeting_assistant.db` (`DATABASE_URL` is blank in `.env`, so every process —
the dev server and pytest alike — falls back to the same file next to
`backend/`). Each run left another batch of synthetic `@example.com` users
and meetings mixed into whatever the app was actually being used for, which
is exactly the pollution that made Alina's real answers reference fake
"AI Meeting Assistant on AWS"-style test data. `app.__init__` loads `.env`
with `override=False`, so setting this here — before anything imports the
`app` package — wins over the blank value in the file without having to
touch it.
"""

import os
from pathlib import Path

_TEST_DB = Path(__file__).resolve().parent / "test_meeting_assistant.db"

# Start every test session from a clean, empty database. Nothing has
# imported `app` yet at this point, so nothing holds this file open. Without
# this, fixtures using a plain descriptive name ("Someone Nobody Knows",
# "Sara" a raw email's local part resolves to) can collide with a
# same-named user a previous run left behind and never cleaned up, which is
# exactly the kind of flaky, order-dependent failure a test database exists
# to prevent.
if _TEST_DB.exists():
    _TEST_DB.unlink()

os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB.as_posix()}")

# Create the schema now, rather than relying on `app.main` being imported
# first. Only test files that exercise the HTTP layer import `app.main` (the
# module that normally calls `Base.metadata.create_all`); plenty of others
# (test_action_items.py among them) talk to the ORM directly and would
# otherwise hit "no such table" the moment this file starts empty instead of
# already carrying tables over from a previous run.
import app.models  # noqa: E402,F401  (registers every model on Base before create_all)
from app.database import Base, engine  # noqa: E402

Base.metadata.create_all(bind=engine)
