"""
Zoom RTMS Integration
======================
Backend/app/integrations/zoom_rtms.py

Ye module Zoom se do cheezein handle karta hai:
1. Webhook endpoint - Zoom se events receive karta hai (URL validation + rtms_started/rtms_stopped)
2. Media WebSocket client - jab RTMS start ho, actual audio stream yahan se milta hai

SETUP (backend/.env mein add karo):
    ZOOM_CLIENT_ID=vXG3OiSqT6q_OVg...
    ZOOM_CLIENT_SECRET=<Client Secret from App Credentials page>
    ZOOM_WEBHOOK_SECRET_TOKEN=<Secret Token from Event Subscription page - alag hota hai Client Secret se>

main.py mein register karna hoga:
    from app.integrations.zoom_rtms import router as zoom_router
    app.include_router(zoom_router, prefix="/api/integrations/zoom", tags=["zoom"])
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

import websockets
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()
logger = logging.getLogger(__name__)

# meeting_uuid → RTMSTranscriptionPipeline
_rtms_pipelines: dict[str, Any] = {}

# meeting_uuid → meeting_id (DB) — set when bot joins via /api/zoom/join
_uuid_to_meeting_id: dict[str, int] = {}

ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID", "")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET", "")
ZOOM_WEBHOOK_SECRET_TOKEN = os.getenv("ZOOM_WEBHOOK_SECRET_TOKEN", "")


def register_meeting_uuid(meeting_uuid: str, meeting_id: int) -> None:
    """Register the DB meeting_id for a Zoom meeting UUID (called when bot joins)."""
    _uuid_to_meeting_id[meeting_uuid] = meeting_id
    logger.info("Registered meeting UUID %s → DB meeting_id %d", meeting_uuid, meeting_id)


# ---------------------------------------------------------------------------
# 1. MAIN WEBHOOK ENDPOINT
# ---------------------------------------------------------------------------
@router.post("/webhook")
async def zoom_webhook(request: Request):
    """
    Zoom sabhi events (URL validation, rtms_started, rtms_stopped) isi
    ek endpoint pe POST karta hai. Event type 'event' field se pata chalta hai.
    """
    body = await request.body()
    payload = json.loads(body)
    event = payload.get("event", "")

    logger.info("[Zoom Webhook] Received event: %s", event)

    # --- Step A: Zoom ka one-time URL validation (endpoint setup ke waqt) ---
    if event == "endpoint.url_validation":
        return handle_url_validation(payload)

    # --- Step B: RTMS lifecycle events ---
    if event == "meeting.rtms_started":
        await handle_rtms_started(payload)
        return JSONResponse({"status": "received"})

    if event == "meeting.rtms_stopped":
        await handle_rtms_stopped(payload)
        return JSONResponse({"status": "received"})

    # Unknown/unused event — just acknowledge
    return JSONResponse({"status": "ignored"})


def handle_url_validation(payload: dict) -> JSONResponse:
    """
    Jab tum Event Subscription page pe endpoint URL save karte ho, Zoom ek
    'endpoint.url_validation' request bhejta hai jisme ek plainToken hota hai.
    Humein Webhook Secret Token se HMAC-SHA256 sign karke wapas bhejna hota hai
    — warna Zoom endpoint ko invalid mark kar dega.
    """
    plain_token = payload["payload"]["plainToken"]
    encrypted_token = hmac.new(
        ZOOM_WEBHOOK_SECRET_TOKEN.encode(),
        plain_token.encode(),
        hashlib.sha256,
    ).hexdigest()

    return JSONResponse(
        {
            "plainToken": plain_token,
            "encryptedToken": encrypted_token,
        }
    )


def verify_signature(request_body: str, timestamp: str, received_signature: str) -> bool:
    """Har real event ke saath Zoom ek signature header bhejta hai — verify karna best practice hai."""
    message = f"v0:{timestamp}:{request_body}"
    computed = "v0=" + hmac.new(
        ZOOM_WEBHOOK_SECRET_TOKEN.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, received_signature)


# ---------------------------------------------------------------------------
# 2. RTMS STARTED -> connect to media server, stream audio
# ---------------------------------------------------------------------------
async def handle_rtms_started(payload: dict):
    data = payload["payload"]
    meeting_uuid = data["meeting_uuid"]
    rtms_stream_id = data["rtms_stream_id"]
    server_urls = data["server_urls"]  # signaling server URL
    meeting_id_str = data.get("meeting_id")

    # Try to resolve DB meeting_id from UUID registry, then from payload
    meeting_id: int | None = _uuid_to_meeting_id.get(meeting_uuid)
    if meeting_id is None and meeting_id_str is not None:
        try:
            meeting_id = int(meeting_id_str)
        except (ValueError, TypeError):
            pass

    logger.info("[RTMS] Started for meeting %s (DB id=%s), connecting to %s", meeting_uuid, meeting_id, server_urls)

    # Broadcast agent state update to connected frontend clients
    if meeting_id is not None:
        from app.services.ws_manager import ws_manager
        await ws_manager.broadcast(meeting_id, "agent_state", {"state": "IN_MEETING", "meeting_uuid": meeting_uuid})

    # Background task — isko block nahi karna chahiye webhook response ko
    asyncio.create_task(
        connect_to_rtms_media_server(meeting_uuid, rtms_stream_id, server_urls, meeting_id)
    )


async def handle_rtms_stopped(payload: dict):
    data = payload["payload"]
    meeting_uuid = data["meeting_uuid"]
    logger.info("[RTMS] Stopped for meeting %s", meeting_uuid)

    meeting_id = _uuid_to_meeting_id.get(meeting_uuid)

    pipeline = _rtms_pipelines.pop(meeting_uuid, None)
    if pipeline:
        if meeting_id is not None:
            from app.services.ws_manager import ws_manager
            await ws_manager.broadcast(meeting_id, "agent_state", {"state": "PROCESSING"})

        await pipeline.finalize()

        if meeting_id is not None:
            from app.services.ws_manager import ws_manager
            await ws_manager.broadcast(meeting_id, "agent_state", {"state": "COMPLETE"})


def generate_signature(meeting_uuid: str, rtms_stream_id: str) -> str:
    """Signaling server ke saath handshake ke liye required HMAC signature."""
    message = f"{ZOOM_CLIENT_ID},{meeting_uuid},{rtms_stream_id}"
    return hmac.new(
        ZOOM_CLIENT_SECRET.encode(), message.encode(), hashlib.sha256
    ).hexdigest()


async def connect_to_rtms_media_server(
    meeting_uuid: str,
    rtms_stream_id: str,
    server_urls: str,
    meeting_id: int | None = None,
):
    """
    Signaling server se connect karke media server ka address maangte hain,
    phir media server se connect karke actual raw audio milna shuru hota hai.
    """
    signature = generate_signature(meeting_uuid, rtms_stream_id)

    try:
        async with websockets.connect(server_urls) as ws:
            handshake = {
                "msg_type": "SIGNALING_HAND_SHAKE_REQ",
                "protocol_version": 1,
                "meeting_uuid": meeting_uuid,
                "rtms_stream_id": rtms_stream_id,
                "sequence": int(time.time() * 1000),
                "signature": signature,
            }
            await ws.send(json.dumps(handshake))

            async for message in ws:
                msg = json.loads(message)
                msg_type = msg.get("msg_type")

                if msg_type == "SIGNALING_HAND_SHAKE_RESP":
                    media_server_url = msg["media_server"]["server_urls"]["audio"]
                    # Media server se connect karo — yahan se raw audio (PCM) milega
                    await stream_audio_to_pipeline(
                        media_server_url, meeting_uuid, rtms_stream_id, meeting_id
                    )
                    break

                if msg_type == "KEEP_ALIVE_REQ":
                    await ws.send(json.dumps({
                        "msg_type": "KEEP_ALIVE_RESP",
                        "sequence": msg.get("sequence"),
                    }))
    except Exception as exc:
        logger.error("[RTMS] Signaling connection failed for %s: %s", meeting_uuid, exc)
        if meeting_id is not None:
            from app.services.ws_manager import ws_manager
            await ws_manager.broadcast(meeting_id, "agent_state", {"state": "FAILED_JOIN", "error": str(exc)})


async def stream_audio_to_pipeline(
    media_server_url: str,
    meeting_uuid: str,
    rtms_stream_id: str,
    meeting_id: int | None = None,
):
    """
    Media WebSocket se raw audio chunks receive karke apne existing
    faster-whisper pipeline mein feed karo. Har transcribed chunk ke baad
    AvaVoiceAssistant ko bhi pass karo — wake-word detection ke liye.
    """
    signature = generate_signature(meeting_uuid, rtms_stream_id)
    pipeline = None
    voice_assistant = None

    if meeting_id is not None:
        from app.services.rtms_transcription import RTMSTranscriptionPipeline
        from app.services.voice_assistant import AvaVoiceAssistant
        from app.services.ws_manager import ws_manager

        pipeline = RTMSTranscriptionPipeline(meeting_id)
        voice_assistant = AvaVoiceAssistant(meeting_id)
        _rtms_pipelines[meeting_uuid] = pipeline

    try:
        async with websockets.connect(media_server_url) as media_ws:
            handshake = {
                "msg_type": "DATA_HAND_SHAKE_REQ",
                "protocol_version": 1,
                "meeting_uuid": meeting_uuid,
                "rtms_stream_id": rtms_stream_id,
                "signature": signature,
                "media_type": 1,  # 1 = audio
            }
            await media_ws.send(json.dumps(handshake))

            async for message in media_ws:
                # Binary audio frames yahan aayenge (PCM 16-bit, 16kHz typically)
                if isinstance(message, bytes):
                    if pipeline:
                        texts = await pipeline.add_chunk(message)
                        for text in texts:
                            logger.debug("[RTMS] Transcribed: %s", text)

                            # Broadcast live transcript segment to frontend
                            if meeting_id is not None:
                                from app.services.ws_manager import ws_manager
                                await ws_manager.broadcast(
                                    meeting_id,
                                    "transcript_live",
                                    {"text": text, "source": "rtms"},
                                )

                            # Check for Ava wake-word
                            if voice_assistant:
                                await voice_assistant.handle_transcript(text)
                else:
                    # JSON control messages (KEEP_ALIVE etc.)
                    msg = json.loads(message)
                    if msg.get("msg_type") == "KEEP_ALIVE_REQ":
                        await media_ws.send(json.dumps({
                            "msg_type": "KEEP_ALIVE_RESP",
                            "sequence": msg.get("sequence"),
                        }))
    except Exception as exc:
        logger.error("[RTMS] Media stream error for %s: %s", meeting_uuid, exc)