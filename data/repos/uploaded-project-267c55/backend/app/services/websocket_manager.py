"""
Real-time push updates over WebSocket — replaces polling on three
screens that were previously on a timer: per-delivery chat
(DeliveryMessages.jsx, was 5s), the dispatcher's unassigned-orders
queue (DispatcherTable.jsx, was 15s), and the live tracking map
(LiveTrackingMap.jsx / TrackingPage.jsx, was 8s).

A single, simple room-based ConnectionManager: callers connect a
websocket into a named "room" (a string key — e.g. "chat:{delivery_id}"),
and any server-side event broadcasts a JSON payload to everyone
currently in that room. Rooms with nobody connected just have an empty
list — broadcasting to one is a harmless no-op, so every existing write
path (send a message, change a delivery's status, etc.) can
unconditionally broadcast without checking "is anyone listening" first.

This intentionally does NOT replace the REST endpoints as the write
path — POST /deliveries/{id}/messages, PATCH /deliveries/{id}, etc. are
still how a client sends a change. WebSocket here is push-only,
one-directional (server -> connected clients), which keeps the offline-
queue-friendly REST endpoints as the single source of truth for writes
and avoids having to duplicate their validation/auth/conflict-
resolution logic in message-handling code.

A NOTE ON SYNC VS ASYNC: every route that needs to broadcast after a
write (send_message, update_delivery, etc.) is a plain sync `def`, in
keeping with the rest of this codebase — FastAPI runs those in a
worker thread via Starlette's threadpool, which has no running asyncio
event loop of its own. `broadcast_sync()` below bridges that gap with
`asyncio.run()`, which is safe specifically because that thread has no
loop already running: it spins one up just to send whatever's queued
and finish. This is the simplest correct bridge for this codebase's
sync-route convention; it is not the most efficient possible approach
(a single shared event loop your whole app publishes onto would avoid
spinning one up per broadcast), but for this app's traffic level the
difference is not meaningful.
"""

import asyncio
import json
import logging
from typing import Dict, List

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._rooms: Dict[str, List[WebSocket]] = {}

    async def connect(self, room: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._rooms.setdefault(room, []).append(websocket)

    def disconnect(self, room: str, websocket: WebSocket) -> None:
        connections = self._rooms.get(room)
        if not connections:
            return
        if websocket in connections:
            connections.remove(websocket)
        if not connections:
            self._rooms.pop(room, None)

    def connection_count(self) -> dict:
        """Phase 18 monitoring: total live connections and how many distinct rooms currently have at least one, read fresh on every call — no separate counter to keep in sync with connect()/disconnect()."""
        return {
            "total_connections": sum(len(conns) for conns in self._rooms.values()),
            "active_rooms": len(self._rooms),
        }

    async def broadcast(self, room: str, payload: dict) -> None:
        connections = self._rooms.get(room)
        if not connections:
            return  # nobody listening — perfectly normal, not an error

        message = json.dumps(payload)
        dead = []
        for connection in connections:
            try:
                await connection.send_text(message)
            except Exception:
                # A connection that's gone stale (client closed the tab
                # without a clean disconnect, network dropped, etc.) —
                # don't let one dead socket break broadcasting to
                # everyone else in the room.
                dead.append(connection)
        for connection in dead:
            self.disconnect(room, connection)


# One shared instance for the whole process — every route/service that
# needs to broadcast imports this same manager, so a message sent from
# routes/messages.py reaches a client connected via routes/websockets.py.
manager = ConnectionManager()


def broadcast_sync(room: str, payload: dict) -> None:
    """
    Callable from a plain sync `def` route — see this module's
    docstring for why `asyncio.run()` is the right bridge here. Never
    raises: a broadcast is a best-effort push, and a failure here
    (e.g. every connection in the room happened to drop at that exact
    moment) must never take down the REST write it's reporting on.
    """
    try:
        asyncio.run(manager.broadcast(room, payload))
    except Exception:
        logger.exception("WebSocket broadcast failed for room %s", room)


def chat_room(delivery_id: str) -> str:
    return f"chat:{delivery_id}"


def dispatcher_queue_room(org_id: str) -> str:
    return f"dispatcher_queue:{org_id}"


def tracking_room(delivery_id: str) -> str:
    return f"tracking:{delivery_id}"
