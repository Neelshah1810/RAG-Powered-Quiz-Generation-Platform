"""
Academix AI — Real-time chat hub.

Keeps the open WebSocket connections per user and fans events out to them.
REST endpoints do the writes and then call `hub.publish(user_ids, event)`;
the browser only ever *receives* data over the socket (plus pings and typing
notifications), so every write still goes through the normal auth + authz path.

State is in-process: run the backend as a single instance (one Railway replica,
one uvicorn worker). With several instances a user connected to instance A
would miss events published on instance B — the client refetches on reconnect
and on window focus, so nothing is lost, it just isn't instant.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Iterable

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ChatHub:
    def __init__(self) -> None:
        self._sockets: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def add(self, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._sockets[user_id].add(ws)

    async def remove(self, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            sockets = self._sockets.get(user_id)
            if sockets is not None:
                sockets.discard(ws)
                if not sockets:
                    self._sockets.pop(user_id, None)

    def is_online(self, user_id: str) -> bool:
        return bool(self._sockets.get(user_id))

    async def publish(self, user_ids: Iterable[str], event: dict[str, Any]) -> None:
        """Send `event` to every open socket of every listed user. Never raises."""
        payload = json.dumps(event, default=str)
        async with self._lock:
            targets = [
                (uid, ws)
                for uid in set(user_ids)
                for ws in list(self._sockets.get(uid, ()))
            ]
        if not targets:
            return

        async def _send(uid: str, ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_text(payload), timeout=5)
            except Exception:
                # Dead or stalled socket: drop it; the client reconnects.
                await self.remove(uid, ws)

        await asyncio.gather(*(_send(uid, ws) for uid, ws in targets))


hub = ChatHub()
