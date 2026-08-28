"""FastAPI application entry point."""

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.routers.agent import router as agent_router
from app.routers.analysis import router as analysis_router
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.live_transcription import router as live_transcription_router
from app.routers.meetings import router as meetings_router
from app.routers.notifications import router as notifications_router
from app.routers.recording import router as recording_router
from app.routers.search import router as search_router
from app.routers.speakers import router as speakers_router
from app.routers.tasks import router as tasks_router
from app.routers.transcript import router as transcript_router
from app.routers.transcription import router as transcription_router
from app.routers.tts import router as tts_router
from app.routers.zoom import router as zoom_router
from app.database import Base, engine
import app.models  # noqa: F401

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

app = FastAPI(
    title="AI Meeting Assistant API",
    version="1.0.0",
    description="Backend API for the AI Meeting Assistant — Complete System.",
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
app.include_router(transcription_router)
app.include_router(transcript_router)
app.include_router(speakers_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(live_transcription_router)
app.include_router(tts_router)
app.include_router(zoom_router)
app.include_router(notifications_router)
app.include_router(tasks_router)
app.include_router(analysis_router)
app.include_router(agent_router)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import logging
    from fastapi.responses import JSONResponse
    logging.exception("Unhandled error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Server error: {str(exc)}"},
    )

Base.metadata.create_all(bind=engine)

_zoom_token: str | None = None


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Return a lightweight service-health response."""
    return {"status": "ok"}


def _zoom_secret_token() -> str:
    secret = os.getenv("ZOOM_WEBHOOK_SECRET_TOKEN")
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="ZOOM_WEBHOOK_SECRET_TOKEN is not configured.",
        )
    return secret


def _require_zoom_access_token() -> str:
    if not _zoom_token:
        raise HTTPException(
            status_code=401,
            detail="Zoom is not authorized. Complete the OAuth flow first.",
        )
    return _zoom_token


async def _set_rtms_status(meeting_id: int, action: str) -> dict[str, Any]:
    client_id = os.getenv("ZOOM_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=503, detail="ZOOM_CLIENT_ID is not configured.")

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.patch(
            f"https://api.zoom.us/v2/live_meetings/{meeting_id}/rtms_app/status",
            headers={"Authorization": f"Bearer {_require_zoom_access_token()}"},
            json={"action": action, "settings": {"client_id": client_id}},
        )

    if response.is_error:
        raise HTTPException(
            status_code=502,
            detail=f"Zoom RTMS {action} request failed: {response.text}",
        )
    return response.json()


def _verify_zoom_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify a Zoom webhook request using its version-0 HMAC signature."""
    if not timestamp or not signature:
        return False

    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except ValueError:
        return False

    message = f"v0:{timestamp}:{body.decode('utf-8')}".encode()
    expected = "v0=" + hmac.new(
        _zoom_secret_token().encode(), message, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.patch("/api/integrations/zoom/rtms/start/{meeting_id}", tags=["zoom"])
async def start_zoom_rtms(meeting_id: int) -> dict[str, Any]:
    """Start RTMS for a meeting using the authorized Zoom account."""
    return await _set_rtms_status(meeting_id, "start")


@app.patch("/api/integrations/zoom/rtms/stop/{meeting_id}", tags=["zoom"])
async def stop_zoom_rtms(meeting_id: int) -> dict[str, Any]:
    """Stop RTMS for a meeting using the authorized Zoom account."""
    return await _set_rtms_status(meeting_id, "stop")


@app.post("/api/integrations/zoom/webhook", tags=["zoom"])
async def zoom_webhook(request: Request) -> dict[str, str]:
    """Validate Zoom's webhook endpoint and accept verified RTMS lifecycle events."""
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from error

    if payload.get("event") == "endpoint.url_validation":
        plain_token = payload.get("payload", {}).get("plainToken")
        if not plain_token:
            raise HTTPException(status_code=400, detail="Missing Zoom validation token.")
        encrypted_token = hmac.new(
            _zoom_secret_token().encode(), plain_token.encode(), hashlib.sha256
        ).hexdigest()
        return {"plainToken": plain_token, "encryptedToken": encrypted_token}

    if not _verify_zoom_signature(
        body,
        request.headers.get("x-zm-request-timestamp", ""),
        request.headers.get("x-zm-signature", ""),
    ):
        raise HTTPException(status_code=401, detail="Invalid Zoom webhook signature.")

    return {"status": "accepted"}


@app.get("/api/integrations/zoom/callback", tags=["zoom"])
async def zoom_oauth_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
) -> dict[str, str]:
    """Receive the OAuth authorization result from Zoom during local testing."""
    if error:
        raise HTTPException(status_code=400, detail=f"Zoom authorization failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing Zoom authorization code.")

    client_id = os.getenv("ZOOM_CLIENT_ID")
    client_secret = os.getenv("ZOOM_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail="ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET are not configured.",
        )

    redirect_uri = str(request.url).split("?", 1)[0]
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://zoom.us/oauth/token",
            auth=(client_id, client_secret),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )

    if response.is_error:
        raise HTTPException(
            status_code=502,
            detail="Zoom token exchange failed.",
        )

    global _zoom_token
    _zoom_token = response.json().get("access_token")
    if not _zoom_token:
        raise HTTPException(status_code=502, detail="Zoom did not return an access token.")

    return {
        "status": "authorized",
        "message": "Zoom authorization completed successfully.",
    }
