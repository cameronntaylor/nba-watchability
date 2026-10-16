import csv
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.bluesky_filter import NbaTermMatcher
from core.bluesky_jetstream import JetstreamEvent, POST_COLLECTION
from core.bluesky_store import BlueskyStore
from scripts.backup_bluesky_capture import create_backup
from scripts.inspect_bluesky_capture import capture_summary, connect_readonly, export_csv


class BlueskyToolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "bluesky.sqlite"
        self.key_path = self.root / ".author_hash_key"
        self.key_path.write_text("00" * 32, encoding="utf-8")

        matcher = NbaTermMatcher(
            direct_terms=["nba"],
            contextual_terms=[],
            basketball_context_terms=[],
            storyline_terms=[],
        )
        event = JetstreamEvent(
            seq=1,
            kind="commit",
            did="did:plc:test-author",
            event_time="2026-10-15T20:00:00.000000Z",
            witnessed_at="2026-10-15T20:00:00.000000Z",
            operation="create",
            collection=POST_COLLECTION,
            rkey="post-1",
            cid="cid-1",
            record={
                "$type": POST_COLLECTION,
                "text": "NBA opening night",
                "createdAt": "2026-10-15T20:00:00Z",
                "langs": ["en"],
            },
        )
        with BlueskyStore(self.db_path, stream_id="test-stream") as store:
            store.process_event(event, matcher=matcher, author_key=b"test-key")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_summary_and_csv_export(self):
        export_path = self.root / "capture.csv"
        with connect_readonly(self.db_path) as connection:
            summary = capture_summary(connection)
            count = export_csv(connection, export_path)

        self.assertEqual(summary["events_seen"], 1)
        self.assertEqual(summary["active_rows"], 1)
        self.assertEqual(count, 1)
        with export_path.open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["text"], "NBA opening night")

    def test_live_safe_zip_backup_contains_database_and_key(self):
        backup_path = self.root / "backup.zip"
        result = create_backup(
            self.db_path,
            author_key_path=self.key_path,
            output_path=backup_path,
        )

        self.assertEqual(result, backup_path.resolve())
        with zipfile.ZipFile(backup_path) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"bluesky.sqlite", "metadata.json", ".author_hash_key"},
            )
            extracted_db = self.root / "extracted.sqlite"
            extracted_db.write_bytes(archive.read("bluesky.sqlite"))
        with connect_readonly(extracted_db) as connection:
            self.assertEqual(capture_summary(connection)["active_rows"], 1)


if __name__ == "__main__":
    unittest.main()
