from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from witty_service.adapter.websocket_client import WebSocketClient

@dataclass(frozen=True)
class AdaptorEndpoint:
    base_url: str
    session_id: str
    sandbox_type: str

class WebSocketClientPool:
    def __init__(self) -> None:
        self._clients: dict[tuple[str, str], WebSocketClient] = {}

    def get_client(
        self,
        agent_id: str,
        endpoint: AdaptorEndpoint,
        factory: Callable[[str], WebSocketClient],
    ) -> WebSocketClient:
        key = (agent_id, endpoint.session_id)
        if key not in self._clients:
            self._clients[key] = factory(endpoint.base_url)
        return self._clients[key]

    def remove_client(self, agent_id: str, session_id: str | None = None) -> None:
        if session_id is None:
            keys = [key for key in self._clients if key[0] == agent_id]
        else:
            keys = [(agent_id, session_id)]
        for key in keys:
            self._clients.pop(key, None)

    async def close_all(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
