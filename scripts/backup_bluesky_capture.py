#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "conversation" / "bluesky.sqlite"
DEFAULT_KEY = ROOT / "data" / "conversation" / ".author_hash_key"


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def create_backup(
    db_path: str | Path,
    *,
    author_key_path: str | Path | None = None,
    output_path: str | Path | None = None,
    overwrite: bool = False,
) -> Path:
    source_path = Path(db_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Capture database not found: {source_path}")

    output = Path(output_path) if output_path else source_path.with_name(
        f"bluesky-backup-{timestamp_slug()}.zip"
    )
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not overwrite:
        raise FileExistsError(f"Backup already exists: {output}")

    key_path = Path(author_key_path).resolve() if author_key_path else None
    if key_path is not None and not key_path.exists():
        raise FileNotFoundError(f"Author hash key not found: {key_path}")

    with tempfile.TemporaryDirectory(dir=output.parent) as temp_dir:
        snapshot_path = Path(temp_dir) / "bluesky.sqlite"
        source = sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True)
        destination = sqlite3.connect(str(snapshot_path))
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

        metadata = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database_filename": "bluesky.sqlite",
            "includes_author_hash_key": key_path is not None,
        }
        mode = "w" if overwrite else "x"
        with zipfile.ZipFile(output, mode=mode, compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot_path, arcname="bluesky.sqlite")
            archive.writestr("metadata.json", json.dumps(metadata, indent=2) + "\n")
            if key_path is not None:
                archive.write(key_path, arcname=".author_hash_key")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a consistent ZIP backup while the Bluesky collector is running."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--author-key-file", default=str(DEFAULT_KEY))
    parser.add_argument("--output")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = create_backup(
        args.db,
        author_key_path=args.author_key_file,
        output_path=args.output,
        overwrite=args.overwrite,
    )
    print(output)


if __name__ == "__main__":
    main()
