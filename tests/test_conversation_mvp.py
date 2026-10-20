import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from core.bluesky_entities import BlueskyEntityResolver
from core.conversation_mvp import (
    CapturedPost,
    associate_topics_to_games,
    build_topic_report,
    classify_category,
    match_post_to_topic,
)
from scripts import build_conversation_mvp


UTC = timezone.utc


def post(index, text, when, terms, *, author=None, reply=False):
    return CapturedPost(
        uri=f"at://test/{index}",
        author_fingerprint=author or f"author-{index}",
        text=text,
        observed_at=when,
        is_reply=reply,
        matched_terms=tuple(terms),
    )


class ConversationMvpTests(unittest.TestCase):
    def setUp(self):
        self.resolver = BlueskyEntityResolver(
            {
                "LeBron James": "Philadelphia 76ers",
                "Stephen Curry": "Golden State Warriors",
            }
        )

    def test_record_chase_maps_player_to_current_team(self):
        item = post(
            1,
            "LeBron James is on the verge of another scoring record",
            datetime(2026, 10, 19, 20, tzinfo=UTC),
            ["lebron james", "record"],
        )
        match = match_post_to_topic(item, self.resolver)
        self.assertEqual(match.category, "record_or_milestone_chase")
        self.assertEqual(match.teams, ("philadelphia 76ers",))
        self.assertIn("LeBron James", match.title)

    def test_off_court_category_takes_priority(self):
        resolved = self.resolver.resolve(
            ["lebron james"], text="LeBron James sports betting lawsuit"
        )
        self.assertEqual(
            classify_category("LeBron James sports betting lawsuit", resolved),
            "off_court_controversy",
        )

    def test_metrics_use_latest_capture_time_and_require_seven_prior_windows(self):
        as_of = datetime(2026, 10, 19, 20, tzinfo=UTC)
        posts = [
            post(
                index,
                "Stephen Curry milestone chase",
                as_of - timedelta(hours=index),
                ["steph curry", "milestone"],
            )
            for index in range(9)
        ]
        topics = build_topic_report(posts, self.resolver, as_of=as_of)
        self.assertEqual(len(topics), 1)
        metric = topics[0]["metrics"]["1"]
        self.assertEqual(metric["absolute_count"], 2)
        self.assertEqual(metric["baseline_sample_count"], 7)
        self.assertIsNotNone(metric["relative_lift"])
        self.assertIsNone(metric["production_storyline_heat"])

    def test_matchup_gets_direct_game_candidate_but_not_production_eligibility(self):
        as_of = datetime(2026, 10, 19, 20, tzinfo=UTC)
        topic = {
            "topic_id": "topic-1",
            "category": "matchup_or_rivalry",
            "teams": ["philadelphia 76ers", "new york knicks"],
        }
        games = [
            {
                "game_id": "game-1",
                "start_time_utc": "2026-10-20T23:30:00Z",
                "home_team": "New York Knicks",
                "away_team": "Philadelphia 76ers",
            }
        ]
        association = associate_topics_to_games([topic], games, as_of=as_of)[0]
        self.assertEqual(association["decision"], "direct")
        self.assertTrue(association["display_candidate"])
        self.assertFalse(association["production_display_eligible"])

    def test_generic_debate_is_not_game_specific(self):
        topic = {
            "topic_id": "topic-2",
            "category": "generic_debate",
            "teams": ["golden state warriors"],
        }
        association = associate_topics_to_games(
            [topic], [], as_of=datetime(2026, 10, 19, 20, tzinfo=UTC)
        )[0]
        self.assertEqual(association["decision"], "not_game_specific")
        self.assertFalse(association["display_candidate"])


class ConversationMvpScriptTests(unittest.TestCase):
    def test_backup_zip_builds_local_html_csv_and_json_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "bluesky.sqlite"
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TABLE posts (
                    uri TEXT PRIMARY KEY,
                    author_fingerprint TEXT NOT NULL,
                    text TEXT,
                    observed_at TEXT NOT NULL,
                    is_reply INTEGER NOT NULL,
                    matched_terms_json TEXT NOT NULL,
                    is_relevant INTEGER NOT NULL,
                    deleted_at TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO posts VALUES (?, ?, ?, ?, ?, ?, 1, NULL)
                """,
                (
                    "at://test/one",
                    "author-one",
                    "Sixers vs Knicks opening night matchup",
                    "2026-10-19T20:00:00Z",
                    0,
                    json.dumps(["sixers", "knicks"]),
                ),
            )
            connection.commit()
            connection.close()
            backup = root / "backup.zip"
            with zipfile.ZipFile(backup, "w") as archive:
                archive.write(database, "bluesky.sqlite")
            output = root / "output"

            argv = [
                "build_conversation_mvp.py",
                "--input",
                str(backup),
                "--output-dir",
                str(output),
                "--offline",
            ]
            with mock.patch.object(sys, "argv", argv):
                build_conversation_mvp.main()

            self.assertTrue((output / "conversation_report.html").exists())
            self.assertTrue((output / "topics.csv").exists())
            report = json.loads((output / "conversation_report.json").read_text())
            self.assertEqual(report["capture"]["active_posts"], 1)
            self.assertEqual(report["topics"][0]["category"], "matchup_or_rivalry")


if __name__ == "__main__":
    unittest.main()
