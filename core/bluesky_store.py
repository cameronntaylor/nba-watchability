from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.bluesky_filter import NbaTermMatcher
from core.bluesky_jetstream import JetstreamEvent, POST_COLLECTION


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_or_create_author_key(path: str | Path) -> bytes:
    key_path = Path(path)
    if key_path.exists():
        value = key_path.read_text(encoding="utf-8").strip()
        if not value:
            raise ValueError(f"Author hash key is empty: {key_path}")
        return bytes.fromhex(value)

    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    key_path.write_text(key.hex(), encoding="utf-8")
    os.chmod(key_path, 0o600)
    return key


def author_fingerprint(did: str, key: bytes) -> str:
    return hmac.new(key, did.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class ProcessResult:
    disposition: str
    cursor: int
    uri: str | None = None


class BlueskyStore:
    def __init__(self, path: str | Path, *, stream_id: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream_id = stream_id
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "BlueskyStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS collector_state (
                stream_id TEXT PRIMARY KEY,
                cursor INTEGER NOT NULL,
                event_time TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                events_seen INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS posts (
                uri TEXT PRIMARY KEY,
                cid TEXT,
                author_fingerprint TEXT NOT NULL,
                rkey TEXT NOT NULL,
                text TEXT,
                is_reply INTEGER NOT NULL DEFAULT 0,
                reply_parent_uri TEXT,
                reply_root_uri TEXT,
                langs_json TEXT NOT NULL DEFAULT '[]',
                source_created_at TEXT,
                observed_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT,
                is_relevant INTEGER NOT NULL DEFAULT 1,
                matched_terms_json TEXT NOT NULL DEFAULT '[]',
                match_reasons_json TEXT NOT NULL DEFAULT '[]',
                vocabulary_version INTEGER NOT NULL,
                raw_record_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_posts_relevant_observed
                ON posts(is_relevant, observed_at);
            CREATE INDEX IF NOT EXISTS idx_posts_author
                ON posts(author_fingerprint);
            """
        )
        self.connection.commit()

    def last_cursor(self) -> int | None:
        row = self.connection.execute(
            "SELECT cursor FROM collector_state WHERE stream_id = ?", (self.stream_id,)
        ).fetchone()
        return int(row["cursor"]) if row else None

    def _advance_cursor(self, event: JetstreamEvent) -> None:
        self.connection.execute(
            """
            INSERT INTO collector_state(stream_id, cursor, event_time, updated_at, events_seen)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(stream_id) DO UPDATE SET
                cursor = excluded.cursor,
                event_time = excluded.event_time,
                updated_at = excluded.updated_at,
                events_seen = collector_state.events_seen + 1
            """,
            (self.stream_id, event.seq, event.event_time, utc_now_iso()),
        )

    def process_event(
        self,
        event: JetstreamEvent,
        *,
        matcher: NbaTermMatcher,
        author_key: bytes,
    ) -> ProcessResult:
        current_cursor = self.last_cursor()
        if current_cursor is not None and event.seq <= current_cursor:
            return ProcessResult("replayed", current_cursor, event.uri)

        disposition = "ignored"
        with self.connection:
            if event.kind == "commit" and event.collection == POST_COLLECTION:
                disposition = self._process_post_commit(event, matcher, author_key)
            elif event.kind == "account" and self._account_is_inactive(event):
                fingerprint = author_fingerprint(event.did, author_key)
                self._suppress_author(fingerprint, event.event_time)
                disposition = "account_suppressed"
            elif event.kind == "sync":
                fingerprint = author_fingerprint(event.did, author_key)
                self._suppress_author(fingerprint, event.event_time)
                disposition = "sync_reset"

            self._advance_cursor(event)

        return ProcessResult(disposition, event.seq, event.uri)

    @staticmethod
    def _account_is_inactive(event: JetstreamEvent) -> bool:
        return event.active is False or event.status in {"deactivated", "deleted", "takendown"}

    def _process_post_commit(
        self,
        event: JetstreamEvent,
        matcher: NbaTermMatcher,
        author_key: bytes,
    ) -> str:
        if not event.uri:
            return "invalid"
        if event.operation == "delete":
            self.connection.execute(
                """
                UPDATE posts
                SET is_relevant = 0, deleted_at = ?, updated_at = ?,
                    text = NULL, raw_record_json = NULL
                WHERE uri = ?
                """,
                (event.event_time, event.event_time, event.uri),
            )
            return "deleted"
        if event.operation not in {"create", "update"} or event.record is None:
            return "ignored"

        text = event.record.get("text", "")
        if not isinstance(text, str):
            text = ""
        langs = event.record.get("langs")
        if not isinstance(langs, list):
            langs = []
        has_non_english_label = bool(langs) and not any(
            isinstance(lang, str) and lang.casefold().startswith("en") for lang in langs
        )
        match = matcher.match(text)
        existing = self.connection.execute(
            "SELECT 1 FROM posts WHERE uri = ?", (event.uri,)
        ).fetchone()

        if not match.relevant or has_non_english_label:
            if existing:
                self.connection.execute(
                    """
                    UPDATE posts
                    SET cid = ?, is_relevant = 0, updated_at = ?, deleted_at = NULL,
                        text = NULL, raw_record_json = NULL,
                        matched_terms_json = '[]', match_reasons_json = '[]',
                        vocabulary_version = ?
                    WHERE uri = ?
                    """,
                    (event.cid, event.event_time, match.vocabulary_version, event.uri),
                )
                return "updated_irrelevant"
            return "non_english" if has_non_english_label else "irrelevant"

        reply = event.record.get("reply")
        reply_parent_uri = None
        reply_root_uri = None
        if isinstance(reply, dict):
            parent = reply.get("parent")
            root = reply.get("root")
            if isinstance(parent, dict):
                reply_parent_uri = parent.get("uri")
            if isinstance(root, dict):
                reply_root_uri = root.get("uri")

        created_at = event.record.get("createdAt")
        if not isinstance(created_at, str):
            created_at = None
        observed_at = event.witnessed_at or event.event_time
        fingerprint = author_fingerprint(event.did, author_key)

        self.connection.execute(
            """
            INSERT INTO posts(
                uri, cid, author_fingerprint, rkey, text, is_reply,
                reply_parent_uri, reply_root_uri, langs_json,
                source_created_at, observed_at, updated_at, deleted_at,
                is_relevant, matched_terms_json, match_reasons_json,
                vocabulary_version, raw_record_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?, ?, ?, ?)
            ON CONFLICT(uri) DO UPDATE SET
                cid = excluded.cid,
                author_fingerprint = excluded.author_fingerprint,
                text = excluded.text,
                is_reply = excluded.is_reply,
                reply_parent_uri = excluded.reply_parent_uri,
                reply_root_uri = excluded.reply_root_uri,
                langs_json = excluded.langs_json,
                source_created_at = excluded.source_created_at,
                updated_at = excluded.updated_at,
                deleted_at = NULL,
                is_relevant = 1,
                matched_terms_json = excluded.matched_terms_json,
                match_reasons_json = excluded.match_reasons_json,
                vocabulary_version = excluded.vocabulary_version,
                raw_record_json = excluded.raw_record_json
            """,
            (
                event.uri,
                event.cid,
                fingerprint,
                event.rkey,
                text,
                int(reply_parent_uri is not None),
                reply_parent_uri,
                reply_root_uri,
                json.dumps(langs, separators=(",", ":")),
                created_at,
                observed_at,
                event.event_time,
                json.dumps(match.matched_terms, separators=(",", ":")),
                json.dumps(match.reasons, separators=(",", ":")),
                match.vocabulary_version,
                json.dumps(event.record, separators=(",", ":"), ensure_ascii=False),
            ),
        )
        return "updated" if existing else "stored"

    def _suppress_author(self, fingerprint: str, event_time: str) -> None:
        self.connection.execute(
            """
            UPDATE posts
            SET is_relevant = 0, deleted_at = ?, updated_at = ?,
                text = NULL, raw_record_json = NULL
            WHERE author_fingerprint = ? AND deleted_at IS NULL
            """,
            (event_time, event_time, fingerprint),
        )

    def summary(self) -> dict[str, int | None]:
        counts = self.connection.execute(
            """
            SELECT
                COUNT(*) AS stored,
                SUM(CASE WHEN is_relevant = 1 AND deleted_at IS NULL THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN is_reply = 1 AND is_relevant = 1 AND deleted_at IS NULL THEN 1 ELSE 0 END) AS replies
            FROM posts
            """
        ).fetchone()
        return {
            "cursor": self.last_cursor(),
            "stored": int(counts["stored"] or 0),
            "active": int(counts["active"] or 0),
            "replies": int(counts["replies"] or 0),
        }
