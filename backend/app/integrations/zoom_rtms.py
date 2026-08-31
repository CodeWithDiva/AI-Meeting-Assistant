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

import hashlib
import hmac
import json
import os
import time

import websockets
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID", "")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET", "")
ZOOM_WEBHOOK_SECRET_TOKEN = os.getenv("ZOOM_WEBHOOK_SECRET_TOKEN", "")


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

    print(f"[Zoom Webhook] Received event: {event}")

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

    print(f"[RTMS] Started for meeting {meeting_uuid}, connecting to {server_urls}")

    # Background task — isko block nahi karna chahiye webhook response ko
    import asyncio
    asyncio.create_task(
        connect_to_rtms_media_server(meeting_uuid, rtms_stream_id, server_urls)
    )


async def handle_rtms_stopped(payload: dict):
    data = payload["payload"]
    meeting_uuid = data["meeting_uuid"]
    print(f"[RTMS] Stopped for meeting {meeting_uuid}")
    # TODO: yahan par apna existing /analyze pipeline trigger karo
    # taake summary + decisions + action items generate ho jayen,
    # bilkul waise jaise uploaded audio ke liye Day 16-18 mein bana tha.


def generate_signature(meeting_uuid: str, rtms_stream_id: str) -> str:
    """Signaling server ke saath handshake ke liye required HMAC signature."""
    message = f"{ZOOM_CLIENT_ID},{meeting_uuid},{rtms_stream_id}"
    return hmac.new(
        ZOOM_CLIENT_SECRET.encode(), message.encode(), hashlib.sha256
    ).hexdigest()


async def connect_to_rtms_media_server(meeting_uuid: str, rtms_stream_id: str, server_urls: str):
    """
    Signaling server se connect karke media server ka address maangte hain,
    phir media server se connect karke actual raw audio milna shuru hota hai.
    """
    signature = generate_signature(meeting_uuid, rtms_stream_id)

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
                await stream_audio_to_pipeline(media_server_url, meeting_uuid, rtms_stream_id)
                break

            if msg_type == "KEEP_ALIVE_REQ":
                await ws.send(json.dumps({
                    "msg_type": "KEEP_ALIVE_RESP",
                    "sequence": msg.get("sequence"),
                }))


async def stream_audio_to_pipeline(media_server_url: str, meeting_uuid: str, rtms_stream_id: str):
    """
    Media WebSocket se raw audio chunks receive karke apne existing
    faster-whisper pipeline mein feed karo.
    """
    signature = generate_signature(meeting_uuid, rtms_stream_id)

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
                # TODO: apne existing whisper service ko call karo, e.g.:
                # await transcription_service.process_audio_chunk(message, meeting_uuid)
                pass
            else:
                # JSON control messages (KEEP_ALIVE etc.)
                msg = json.loads(message)
                if msg.get("msg_type") == "KEEP_ALIVE_REQ":
                    await media_ws.send(json.dumps({
                        "msg_type": "KEEP_ALIVE_RESP",
                        "sequence": msg.get("sequence"),
                    }))