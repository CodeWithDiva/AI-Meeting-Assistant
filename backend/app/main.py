"""FastAPI application entry point."""

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

app = FastAPI(
    title="AI Meeting Assistant API",
    version="0.1.0",
    description="Backend API for the AI Meeting Assistant.",
)


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
