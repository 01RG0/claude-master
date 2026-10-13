"""brain/api/services/events_service.py — SSE and WebSocket event broker for live telemetry.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncGenerator, Dict, List, Set
from fastapi import WebSocket


class EventBroker:
    def __init__(self) -> None:
        self._queues: Set[asyncio.Queue] = set()
        self._ws_clients: Set[WebSocket] = set()

    def register_queue(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._queues.add(q)
        return q

    def unregister_queue(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    async def register_ws(self, ws: WebSocket) -> None:
        await ws.accept()
        self._ws_clients.add(ws)

    def unregister_ws(self, ws: WebSocket) -> None:
        self._ws_clients.discard(ws)

    async def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        payload = {
            "type": event_type,
            "timestamp": int(time.time() * 1000),
            "data": data,
        }
        raw = json.dumps(payload, ensure_ascii=False)

        # Broadcast to SSE queues
        dead_queues = []
        for q in self._queues:
            try:
                q.put_nowait(raw)
            except asyncio.QueueFull:
                pass
            except Exception:
                dead_queues.append(q)
        for dq in dead_queues:
            self._queues.discard(dq)

        # Broadcast to WebSockets
        dead_ws = []
        for ws in self._ws_clients:
            try:
                await ws.send_text(raw)
            except Exception:
                dead_ws.append(ws)
        for dws in dead_ws:
            self._ws_clients.discard(dws)

    async def sse_stream(self) -> AsyncGenerator[str, None]:
        q = self.register_queue()
        try:
            # Send initial ping event
            init_msg = json.dumps({"type": "connected", "timestamp": int(time.time() * 1000)})
            yield f"data: {init_msg}\n\n"
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat comment
                    yield ": ping\n\n"
        finally:
            self.unregister_queue(q)


GLOBAL_EVENT_BROKER = EventBroker()
