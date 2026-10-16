#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import logging
import ssl
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bluesky_filter import NbaTermMatcher
from core.bluesky_jetstream import JETSTREAM_HOST, POST_COLLECTION, parse_v2_message
from core.bluesky_store import BlueskyStore, load_or_create_author_key


LOGGER = logging.getLogger("bluesky-capture")


def build_stream_url(host: str, cursor: int | None) -> str:
    params = [
        ("kinds", "commit"),
        ("kinds", "account"),
        ("kinds", "sync"),
        ("collections", POST_COLLECTION),
    ]
    if cursor is not None:
        params.append(("cursor", str(cursor)))
    return f"wss://{host}/xrpc/network.bsky.jetstream.subscribeEvents?{urlencode(params)}"


async def capture(args: argparse.Namespace) -> None:
    try:
        import certifi
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed
    except ImportError as exc:
        raise SystemExit("Install dependencies first: pip install -r requirements.txt") from exc

    matcher = NbaTermMatcher.from_json_file(args.terms)
    author_key = load_or_create_author_key(args.author_key_file)
    dispositions: Counter[str] = Counter()
    messages_seen = 0
    retry_seconds = 1
    start_from_live_tip = args.from_live_tip
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    with BlueskyStore(args.db, stream_id=args.stream_id) as store:
        while args.max_events is None or messages_seen < args.max_events:
            saved_cursor = store.last_cursor()
            if start_from_live_tip:
                cursor = None
            elif saved_cursor is not None:
                cursor = saved_cursor
            elif args.lookback_seconds:
                cursor = int((time.time() - args.lookback_seconds) * 1_000_000)
            else:
                cursor = None
            url = build_stream_url(args.host, cursor)
            LOGGER.info("Connecting to %s (cursor=%s)", args.host, cursor or "live")
            try:
                async with connect(
                    url,
                    subprotocols=["xrpc.v1.json"],
                    compression=None,
                    open_timeout=20,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=2 * 1024 * 1024,
                    user_agent_header="nba-watchability-bluesky-collector/0.1",
                    ssl=ssl_context,
                ) as websocket:
                    start_from_live_tip = False
                    retry_seconds = 1
                    async for message in websocket:
                        event = parse_v2_message(message)
                        if event is None:
                            continue
                        result = store.process_event(
                            event,
                            matcher=matcher,
                            author_key=author_key,
                        )
                        messages_seen += 1
                        dispositions[result.disposition] += 1

                        if messages_seen % args.log_every == 0:
                            LOGGER.info(
                                "events=%s dispositions=%s database=%s",
                                messages_seen,
                                dict(dispositions),
                                store.summary(),
                            )
                        if args.max_events is not None and messages_seen >= args.max_events:
                            break
            except (ConnectionClosed, OSError, TimeoutError) as exc:
                LOGGER.warning("Stream disconnected: %s; retrying in %ss", exc, retry_seconds)
                await asyncio.sleep(retry_seconds)
                retry_seconds = min(retry_seconds * 2, 60)

        LOGGER.info(
            "Capture complete: events=%s dispositions=%s database=%s",
            messages_seen,
            dict(dispositions),
            store.summary(),
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture likely NBA posts and replies from Bluesky Jetstream."
    )
    parser.add_argument(
        "--db",
        default=str(ROOT / "data" / "conversation" / "bluesky.sqlite"),
        help="SQLite output path.",
    )
    parser.add_argument(
        "--terms",
        default=str(ROOT / "config" / "bluesky_nba_terms.json"),
        help="NBA vocabulary JSON path.",
    )
    parser.add_argument(
        "--author-key-file",
        default=str(ROOT / "data" / "conversation" / ".author_hash_key"),
        help="Local HMAC key used to pseudonymize author DIDs.",
    )
    parser.add_argument("--host", default=JETSTREAM_HOST)
    parser.add_argument("--stream-id", default="bluesky-us-west-posts-v2")
    parser.add_argument("--max-events", type=int)
    parser.add_argument("--log-every", type=int, default=5_000)
    parser.add_argument(
        "--lookback-seconds",
        type=int,
        default=300,
        help="First-run replay before switching to live capture (default: 300).",
    )
    parser.add_argument(
        "--from-live-tip",
        action="store_true",
        help="Ignore the saved cursor for this connection and start at the live tip.",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        asyncio.run(capture(args))
    except KeyboardInterrupt:
        LOGGER.info("Capture stopped by user")


if __name__ == "__main__":
    main()
