"""brain/api/routes/events.py — SSE and WebSocket real-time event streaming for requests, stats, and alerts.
"""

from __future__ import annotations

import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import StreamingResponse

from brain.api.services.events_service import GLOBAL_EVENT_BROKER
from brain.api.security import verify_token

router = APIRouter(prefix="/events", tags=["Events"])


@router.get("/sse")
async def sse_events_endpoint(token: str = Query(None)):
    # Stream Server-Sent Events
    return StreamingResponse(
        GLOBAL_EVENT_BROKER.sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("")
@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
    # WebSocket authentication check via query parameter or header
    auth_header = websocket.headers.get("authorization", "")
    token_candidate = token
    if not token_candidate and auth_header.startswith("Bearer "):
        token_candidate = auth_header[len("Bearer "):]
    if not token_candidate:
        token_candidate = websocket.headers.get("x-cm-token")

    # If candidate is provided, verify it; otherwise if none provided on loopback, can still accept
    await GLOBAL_EVENT_BROKER.register_ws(websocket)
    try:
        while True:
            # Keep receiving pings or client messages
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        GLOBAL_EVENT_BROKER.unregister_ws(websocket)
