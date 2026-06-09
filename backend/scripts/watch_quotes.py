"""Connect to the local Q-Lab quote WebSocket and print incoming ticks."""

from __future__ import annotations

import argparse
import asyncio
import json

import websockets


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Watch local Q-Lab quote ticks.")
    parser.add_argument(
        "--url",
        default="ws://localhost:8000/ws/quotes",
        help="Local FastAPI quote WebSocket URL.",
    )
    parser.add_argument(
        "--code",
        action="append",
        default=None,
        help="Stock code to subscribe to. Repeatable. Defaults to 005930.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Stop after N tick frames. 0 means run forever.",
    )
    args = parser.parse_args()

    codes = args.code or ["005930"]
    seen_ticks = 0

    async with websockets.connect(args.url) as websocket:
        await websocket.send(json.dumps({"action": "subscribe", "codes": codes}))
        async for raw_message in websocket:
            print(raw_message)
            try:
                payload = json.loads(raw_message)
            except json.JSONDecodeError:
                continue
            if payload.get("type") != "tick":
                continue
            seen_ticks += 1
            if args.count and seen_ticks >= args.count:
                return 0

    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
