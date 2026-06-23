"""Toss realtime client placeholder.

The Toss Open API 1.1.1 spec states that WebSocket support is planned for a
future release. This module keeps the multi-broker shape stable while failing
explicitly instead of pretending to stream data.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.domain.account import BrokerType


class TossWebSocketNotSupportedError(NotImplementedError):
    """Raised when code attempts to start Toss WebSocket streaming."""


@dataclass(slots=True)
class TossWebSocketClient:
    broker: BrokerType = BrokerType.TOSS
    supported: bool = False

    async def subscribe(self, symbols: list[str] | set[str]) -> None:
        raise TossWebSocketNotSupportedError(
            "Toss Open API 1.1.1 does not expose WebSocket streaming yet. "
            "Use TossRestClient.get_current_prices() for REST polling."
        )

    def start(self) -> None:
        raise TossWebSocketNotSupportedError(
            "Toss Open API WebSocket streaming is not available in the provided spec."
        )

    async def stop(self) -> None:
        return None
