import json
import tempfile
import unittest
from pathlib import Path

from core.bluesky_filter import NbaTermMatcher
from core.bluesky_jetstream import JetstreamEvent, POST_COLLECTION, parse_v2_message
from core.bluesky_store import BlueskyStore


def matcher() -> NbaTermMatcher:
    return NbaTermMatcher(
        direct_terms=["nba", "jayson tatum", "miami heat", "utah jazz"],
        contextual_terms=["heat", "jazz"],
        basketball_context_terms=["basketball", "points"],
        storyline_terms=["return", "record"],
        version=7,
    )


def commit_event(
    seq: int,
    *,
    text: str | None = "Jayson Tatum could return tonight",
    operation: str = "create",
    did: str = "did:plc:test-author",
    langs: list[str] | None = None,
) -> JetstreamEvent:
    record = None
    if operation != "delete":
        record = {
            "$type": POST_COLLECTION,
            "text": text,
            "createdAt": "2026-10-15T20:00:00Z",
            "langs": ["en"] if langs is None else langs,
        }
    return JetstreamEvent(
        seq=seq,
        kind="commit",
        did=did,
        event_time=f"2026-10-15T20:00:{seq:02d}.000000Z",
        witnessed_at=f"2026-10-15T20:00:{seq:02d}.000000Z",
        operation=operation,
        collection=POST_COLLECTION,
        rkey="post-1",
        cid=None if operation == "delete" else f"cid-{seq}",
        record=record,
    )


class BlueskyFilterTests(unittest.TestCase):
    def test_direct_player_match(self):
        result = matcher().match("Jayson Tatum is expected to RETURN tonight")
        self.assertTrue(result.relevant)
        self.assertIn("jayson tatum", result.matched_terms)
        self.assertEqual(result.vocabulary_version, 7)

    def test_ambiguous_team_word_requires_context(self):
        self.assertFalse(matcher().match("The heat is unbearable today").relevant)
        self.assertTrue(matcher().match("The Heat scored 120 points").relevant)

    def test_full_ambiguous_team_name_is_direct(self):
        self.assertTrue(matcher().match("The Utah Jazz made a trade").relevant)


class JetstreamParsingTests(unittest.TestCase):
    def test_parse_v2_commit(self):
        message = json.dumps(
            {
                "$type": "message",
                "payload": {
                    "$type": "network.bsky.jetstream.subscribeEvents#commit",
                    "seq": 42,
                    "did": "did:plc:test-author",
                    "time": "2026-10-15T20:00:00.000000Z",
                    "witnessedAt": "2026-10-15T20:00:00.000000Z",
                    "operation": "create",
                    "collection": POST_COLLECTION,
                    "rkey": "abc",
                    "cid": "cid-42",
                    "record": {"text": "NBA opening night"},
                },
            }
        )
        event = parse_v2_message(message)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.seq, 42)
        self.assertEqual(
            event.uri,
            "at://did:plc:test-author/app.bsky.feed.post/abc",
        )

    def test_info_message_is_ignored(self):
        message = json.dumps(
            {
                "$type": "message",
                "payload": {
                    "$type": "network.bsky.jetstream.subscribeEvents#info",
                    "name": "FutureCursor",
                },
            }
        )
        self.assertIsNone(parse_v2_message(message))

    def test_parse_v2_account_payload(self):
        message = json.dumps(
            {
                "$type": "message",
                "payload": {
                    "$type": "network.bsky.jetstream.subscribeEvents#account",
                    "seq": 43,
                    "did": "did:plc:test-author",
                    "time": "2026-10-15T20:01:00.000000Z",
                    "account": {
                        "did": "did:plc:test-author",
                        "active": False,
                        "status": "deleted",
                        "seq": 99,
                        "time": "2026-10-15T20:01:00Z"
                    }
                }
            }
        )
        event = parse_v2_message(message)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertFalse(event.active)
        self.assertEqual(event.status, "deleted")


class BlueskyStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "capture.sqlite"
        self.store = BlueskyStore(self.db_path, stream_id="test-stream")
        self.author_key = b"test-key"

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_store_replay_update_and_delete(self):
        first = self.store.process_event(
            commit_event(1), matcher=matcher(), author_key=self.author_key
        )
        replay = self.store.process_event(
            commit_event(1), matcher=matcher(), author_key=self.author_key
        )
        update = self.store.process_event(
            commit_event(2, text="NBA record chase"),
            matcher=matcher(),
            author_key=self.author_key,
        )
        deleted = self.store.process_event(
            commit_event(3, operation="delete"),
            matcher=matcher(),
            author_key=self.author_key,
        )

        self.assertEqual(first.disposition, "stored")
        self.assertEqual(replay.disposition, "replayed")
        self.assertEqual(update.disposition, "updated")
        self.assertEqual(deleted.disposition, "deleted")
        self.assertEqual(self.store.summary(), {"cursor": 3, "stored": 1, "active": 0, "replies": 0})

    def test_irrelevant_event_advances_cursor_without_storage(self):
        result = self.store.process_event(
            commit_event(8, text="A quiet walk in the park"),
            matcher=matcher(),
            author_key=self.author_key,
        )
        self.assertEqual(result.disposition, "irrelevant")
        self.assertEqual(self.store.summary()["cursor"], 8)
        self.assertEqual(self.store.summary()["stored"], 0)

    def test_explicit_non_english_post_is_not_stored(self):
        result = self.store.process_event(
            commit_event(9, text="NBA record", langs=["es"]),
            matcher=matcher(),
            author_key=self.author_key,
        )
        self.assertEqual(result.disposition, "non_english")
        self.assertEqual(self.store.summary()["stored"], 0)

    def test_account_deactivation_suppresses_posts(self):
        self.store.process_event(
            commit_event(1), matcher=matcher(), author_key=self.author_key
        )
        account_event = JetstreamEvent(
            seq=2,
            kind="account",
            did="did:plc:test-author",
            event_time="2026-10-15T20:01:00.000000Z",
            active=False,
            status="deactivated",
        )
        result = self.store.process_event(
            account_event, matcher=matcher(), author_key=self.author_key
        )
        self.assertEqual(result.disposition, "account_suppressed")
        self.assertEqual(self.store.summary()["active"], 0)


if __name__ == "__main__":
    unittest.main()
