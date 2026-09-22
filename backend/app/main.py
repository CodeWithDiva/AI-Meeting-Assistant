"""FastAPI application entry point.

The assistant joins meetings through its own browser agent
(`app.agents.browser_bot`), so there is no Zoom Marketplace app, no OAuth
handshake and no RTMS webhook anywhere in this service. The only meeting-facing
API is `/api/agent`, which takes a pasted link.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.services.ws_manager import ws_manager

from app.routers.agent import router as agent_router
from app.routers.analysis import router as analysis_router
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.live_transcription import router as live_transcription_router
from app.routers.meetings import router as meetings_router
from app.routers.messages import dm_ws_manager, router as messages_router
from app.routers.notifications import router as notifications_router
from app.routers.recording import router as recording_router
from app.routers.refine import router as refine_router
from app.routers.search import router as search_router
from app.routers.speakers import router as speakers_router
from app.routers.tasks import router as tasks_router
from app.routers.transcript import router as transcript_router
from app.routers.transcription import router as transcription_router
from app.routers.tts import router as tts_router
from app.routers.voice_reply import router as voice_reply_router
from app.routers.workspace import router as workspace_router
from app.database import Base, engine
from app.services.notifier import deadline_reminder_loop, email_enabled
import app.models  # noqa: F401

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

# Uvicorn only configures its own loggers, so everything in `app.*` at INFO —
# joined the meeting, audio level, each transcribed window, language chosen —
# was silently dropped, which made a silent meeting impossible to tell from a
# broken pipeline.
logging.basicConfig(level=logging.WARNING, format="%(levelname)s:     %(name)s: %(message)s")
logging.getLogger("app").setLevel(logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Record the server's event loop so broadcasts fired from the meeting-bot
    # loop thread can be marshalled back onto it.
    ws_manager.bind_loop(asyncio.get_running_loop())
    dm_ws_manager.bind_loop(asyncio.get_running_loop())

    # Deadline reminders and overdue alerts. 0 disables the sweep.
    sweep_seconds = float(os.getenv("TASK_REMINDER_SWEEP_SECONDS", "300"))
    reminders = (
        asyncio.create_task(deadline_reminder_loop(sweep_seconds)) if sweep_seconds > 0 else None
    )
    yield
    if reminders:
        reminders.cancel()
        try:
            await reminders
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="AI Meeting Assistant API",
    version="2.0.0",
    description=(
        "Backend for the AI Meeting Assistant. Paste a Zoom or Google Meet link "
        "and the assistant joins, transcribes (Urdu + English), takes notes, "
        "extracts decisions, and assigns tasks."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://172.31.80.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(meetings_router)
app.include_router(recording_router)
app.include_router(refine_router)
app.include_router(transcription_router)
app.include_router(transcript_router)
app.include_router(speakers_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(live_transcription_router)
app.include_router(tts_router)
app.include_router(voice_reply_router)
app.include_router(notifications_router)
app.include_router(messages_router)
app.include_router(tasks_router)
app.include_router(analysis_router)
app.include_router(agent_router)
app.include_router(workspace_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": f"Server error: {exc}"})


Base.metadata.create_all(bind=engine)

# Keep local MVP databases compatible when a new persisted field is introduced.
_ADDED_COLUMNS = {
    "users": {
        "role": "VARCHAR(20) DEFAULT 'employee'",
        "invite_token": "VARCHAR(64)",
        "invite_expires_at": "DATETIME",
    },
    "action_items": {
        "priority": "VARCHAR(10) DEFAULT 'medium'",
        "due_at": "DATETIME",
        "reminder_sent_at": "DATETIME",
        "overdue_notified_at": "DATETIME",
        "completed_at": "DATETIME",
    },
}

if engine.dialect.name == "sqlite":
    from sqlalchemy import inspect, text

    _added_due_at = False
    for _table, _columns in _ADDED_COLUMNS.items():
        _existing = {column["name"] for column in inspect(engine).get_columns(_table)}
        with engine.begin() as connection:
            for _name, _ddl in _columns.items():
                if _name not in _existing:
                    connection.execute(text(f"ALTER TABLE {_table} ADD COLUMN {_name} {_ddl}"))
                    _added_due_at = _added_due_at or (_table, _name) == ("action_items", "due_at")

    if _added_due_at:
        # Resolve deadlines already on existing tasks, relative to when each
        # task was created ("Friday" said last month is not this Friday). Tasks
        # already past due are marked as alerted so the first reminder sweep
        # does not flood everyone with old overdue notices.
        from datetime import datetime, timezone

        from app.database import SessionLocal
        from app.models import ActionItem
        from app.services.deadlines import parse_deadline

        with SessionLocal() as _db:
            _now = datetime.now(timezone.utc).replace(tzinfo=None)
            for _item in _db.query(ActionItem).filter(ActionItem.deadline.is_not(None)):
                _spoken_at = (_item.created_at or _now).replace(tzinfo=timezone.utc).astimezone()
                _item.due_at = parse_deadline(_item.deadline, now=_spoken_at)
                if _item.due_at and _item.due_at < _now:
                    _item.overdue_notified_at = _now
                    _item.reminder_sent_at = _now
            _db.commit()


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Return a lightweight service-health response."""
    return {"status": "ok"}


@app.get("/", tags=["system"])
async def api_root() -> dict[str, str]:
    """Give a useful response when the API root is opened directly."""
    return {"service": "AI Meeting Assistant API", "status": "ok"}


@app.get("/api/system/capabilities", tags=["system"])
async def capabilities() -> dict[str, object]:
    """Report which optional pieces of the stack are actually installed.

    The bot degrades rather than crashes when Playwright's browsers or the
    virtual audio devices are missing, which makes a silent half-working setup
    easy to miss. This endpoint makes that state visible to the dashboard.
    """
    def _installed(module: str) -> bool:
        import importlib.util

        return importlib.util.find_spec(module) is not None

    from app.services.voice_assistant import WAKE_WORD

    return {
        "assistant_name": os.getenv("BOT_DISPLAY_NAME", "Alina"),
        "wake_word": WAKE_WORD,
        "email_notifications": email_enabled(),
        "virtual_microphone": bool(os.getenv("BOT_VIRTUAL_MIC_LABEL")),
        "platforms": ["zoom", "google_meet"],
        "browser_automation": _installed("playwright"),
        "audio_devices": _installed("sounddevice"),
        "transcription": _installed("faster_whisper"),
        "whisper_model": os.getenv("WHISPER_MODEL", "small"),
        "llm_model": os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
        "tts": _installed("pyttsx3"),
    }
