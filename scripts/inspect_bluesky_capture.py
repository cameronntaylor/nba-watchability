#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "conversation" / "bluesky.sqlite"


def connect_readonly(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Capture database not found: {db_path}")
    connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def capture_summary(connection: sqlite3.Connection) -> dict[str, object]:
    post_counts = connection.execute(
        """
        SELECT
            COUNT(*) AS retained_rows,
            SUM(CASE WHEN is_relevant = 1 AND deleted_at IS NULL THEN 1 ELSE 0 END)
                AS active_rows,
            SUM(CASE WHEN is_reply = 1 AND is_relevant = 1 AND deleted_at IS NULL
                     THEN 1 ELSE 0 END) AS active_replies,
            SUM(CASE WHEN is_reply = 0 AND is_relevant = 1 AND deleted_at IS NULL
                     THEN 1 ELSE 0 END) AS active_posts,
            SUM(CASE WHEN deleted_at IS NOT NULL THEN 1 ELSE 0 END) AS deleted_rows,
            COUNT(DISTINCT CASE WHEN is_relevant = 1 AND deleted_at IS NULL
                                THEN author_fingerprint END) AS active_authors,
            MIN(observed_at) AS first_observed_at,
            MAX(observed_at) AS last_observed_at
        FROM posts
        """
    ).fetchone()
    state = connection.execute(
        """
        SELECT stream_id, cursor, event_time, updated_at, events_seen
        FROM collector_state
        ORDER BY updated_at DESC
        LIMIT 1
        """
    ).fetchone()

    result = {key: post_counts[key] for key in post_counts.keys()}
    if state:
        result.update({key: state[key] for key in state.keys()})
    return result


def hourly_counts(connection: sqlite3.Connection, hours: int) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT
            substr(observed_at, 1, 13) || ':00Z' AS hour,
            COUNT(*) AS retained,
            SUM(CASE WHEN is_reply = 1 THEN 1 ELSE 0 END) AS replies,
            COUNT(DISTINCT author_fingerprint) AS authors
        FROM posts
        WHERE is_relevant = 1 AND deleted_at IS NULL
        GROUP BY substr(observed_at, 1, 13)
        ORDER BY hour DESC
        LIMIT ?
        """,
        (max(0, hours),),
    ).fetchall()


def recent_items(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT
            observed_at,
            CASE WHEN is_reply = 1 THEN 'reply' ELSE 'post' END AS content_type,
            replace(replace(text, char(10), ' '), char(13), ' ') AS text,
            matched_terms_json
        FROM posts
        WHERE is_relevant = 1 AND deleted_at IS NULL
        ORDER BY observed_at DESC
        LIMIT ?
        """,
        (max(0, limit),),
    ).fetchall()


def export_csv(connection: sqlite3.Connection, output: str | Path) -> int:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = connection.execute(
        """
        SELECT
            uri,
            cid,
            observed_at,
            source_created_at,
            CASE WHEN is_reply = 1 THEN 'reply' ELSE 'post' END AS content_type,
            reply_parent_uri,
            reply_root_uri,
            text,
            langs_json,
            matched_terms_json,
            match_reasons_json,
            vocabulary_version,
            author_fingerprint
        FROM posts
        WHERE is_relevant = 1 AND deleted_at IS NULL
        ORDER BY observed_at
        """
    ).fetchall()

    columns = [description[0] for description in connection.execute(
        """
        SELECT
            uri, cid, observed_at, source_created_at, '' AS content_type,
            reply_parent_uri, reply_root_uri, text, langs_json,
            matched_terms_json, match_reasons_json, vocabulary_version,
            author_fingerprint
        FROM posts LIMIT 0
        """
    ).description]
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(tuple(row) for row in rows)
    return len(rows)


def _print_key_values(values: dict[str, object]) -> None:
    width = max((len(key) for key in values), default=0)
    for key, value in values.items():
        print(f"{key:<{width}}  {value if value is not None else '-'}")


def _print_rows(title: str, rows: Iterable[sqlite3.Row], *, text_limit: int = 160) -> None:
    rows = list(rows)
    print(f"\n{title}")
    if not rows:
        print("  No rows")
        return
    for row in rows:
        values = []
        for key in row.keys():
            value = row[key]
            if key == "text" and isinstance(value, str) and len(value) > text_limit:
                value = value[: text_limit - 1] + "…"
            values.append(f"{key}={value}")
        print("  " + " | ".join(values))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect a Bluesky capture database.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--recent", type=int, default=20)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--export-csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with connect_readonly(args.db) as connection:
        print("Capture summary")
        _print_key_values(capture_summary(connection))
        _print_rows(f"Hourly retained volume (latest {args.hours})", hourly_counts(connection, args.hours))
        _print_rows(f"Most recent {args.recent} items", recent_items(connection, args.recent))
        if args.export_csv:
            count = export_csv(connection, args.export_csv)
            print(f"\nExported {count} active rows to {Path(args.export_csv).resolve()}")


if __name__ == "__main__":
    main()
