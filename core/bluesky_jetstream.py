from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping


JETSTREAM_HOST = "jetstream.us-west.bsky.network"
POST_COLLECTION = "app.bsky.feed.post"


@dataclass(frozen=True)
class JetstreamEvent:
    seq: int
    kind: str
    did: str
    event_time: str
    witnessed_at: str | None = None
    operation: str | None = None
    collection: str | None = None
    rkey: str | None = None
    cid: str | None = None
    record: Mapping[str, Any] | None = None
    active: bool | None = None
    status: str | None = None

    @property
    def uri(self) -> str | None:
        if not self.did or not self.collection or not self.rkey:
            return None
        return f"at://{self.did}/{self.collection}/{self.rkey}"


def parse_v2_message(message: str | bytes) -> JetstreamEvent | None:
    if isinstance(message, bytes):
        message = message.decode("utf-8")
    envelope = json.loads(message)
    envelope_type = envelope.get("$type")

    if envelope_type == "error":
        error = envelope.get("error", "JetstreamError")
        detail = envelope.get("message", "")
        raise RuntimeError(f"{error}: {detail}".rstrip())
    if envelope_type != "message":
        return None

    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return None
    payload_type = str(payload.get("$type", ""))
    kind = payload_type.rsplit("#", 1)[-1]
    if kind == "info":
        return None

    seq = payload.get("seq")
    did = payload.get("did")
    event_time = payload.get("time")
    if not isinstance(seq, int) or not isinstance(did, str) or not isinstance(event_time, str):
        raise ValueError("Jetstream event is missing seq, did, or time")

    record = payload.get("record")
    if record is not None and not isinstance(record, dict):
        raise ValueError("Jetstream commit record must be a JSON object")

    account = payload.get("account")
    if not isinstance(account, dict):
        account = {}

    return JetstreamEvent(
        seq=seq,
        kind=kind,
        did=did,
        event_time=event_time,
        witnessed_at=payload.get("witnessedAt"),
        operation=payload.get("operation"),
        collection=payload.get("collection"),
        rkey=payload.get("rkey"),
        cid=payload.get("cid"),
        record=record,
        active=account.get("active"),
        status=account.get("status"),
    )
