import sqlite3
import unittest

from core.bluesky_entities import (
    BlueskyEntityResolver,
    build_player_team_map,
    normalize_entity_name,
)
from scripts.analyze_bluesky_teams import aggregate_team_trends


class BlueskyEntityTests(unittest.TestCase):
    def setUp(self):
        self.player_teams = {
            "LeBron James": "Philadelphia 76ers",
            "Stephen Curry": "Golden State Warriors",
            "Tyrese Maxey": "Philadelphia 76ers",
        }
        self.resolver = BlueskyEntityResolver(self.player_teams)

    def test_build_player_team_map_from_espn_rosters(self):
        result = build_player_team_map(
            {
                "Philadelphia 76ers": "20",
                "Golden State Warriors": "9",
            },
            {
                "20": [("1966", "LeBron James", None)],
                "9": [("3975", "Stephen Curry", None)],
            },
        )
        self.assertEqual(result["lebron james"], "philadelphia 76ers")
        self.assertEqual(result["stephen curry"], "golden state warriors")

    def test_player_aliases_resolve_to_current_roster_team(self):
        lebron = self.resolver.resolve(["lebron"])
        curry = self.resolver.resolve(["steph curry"])
        self.assertEqual(lebron.players, ("lebron james",))
        self.assertEqual(lebron.teams, ("philadelphia 76ers",))
        self.assertEqual(curry.players, ("stephen curry",))
        self.assertEqual(curry.teams, ("golden state warriors",))

    def test_direct_team_and_player_team_are_deduplicated(self):
        resolved = self.resolver.resolve(
            ["philadelphia 76ers", "lebron james"],
            text="LeBron James is back for the Sixers",
        )
        self.assertEqual(resolved.teams, ("philadelphia 76ers",))
        self.assertEqual(resolved.direct_teams, ("philadelphia 76ers",))
        self.assertEqual(resolved.player_teams, ("philadelphia 76ers",))

    def test_roster_player_can_be_found_in_retained_post_text(self):
        resolved = self.resolver.resolve(
            ["nba"],
            text="NBA opening night belongs to Tyrese Maxey",
        )
        self.assertEqual(resolved.players, ("tyrese maxey",))
        self.assertEqual(resolved.teams, ("philadelphia 76ers",))

    def test_unicode_player_names_are_normalized(self):
        self.assertEqual(normalize_entity_name("Luka Dončić"), "luka doncic")

    def test_hourly_aggregation_counts_team_once_per_post(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT 'one' AS uri, '2026-10-16T03:10:00Z' AS observed_at,
                   'LeBron James and the Sixers' AS text,
                   '["lebron james","philadelphia 76ers","sixers"]' AS matched_terms_json
            UNION ALL
            SELECT 'two', '2026-10-16T03:20:00Z',
                   'Steph Curry hits another three', '["steph curry"]'
            """
        ).fetchall()

        totals, hourly, players = aggregate_team_trends(rows, self.resolver)

        self.assertEqual(totals["philadelphia 76ers"]["posts"], 1)
        self.assertEqual(totals["philadelphia 76ers"]["direct_posts"], 1)
        self.assertEqual(totals["philadelphia 76ers"]["player_posts"], 1)
        self.assertEqual(totals["golden state warriors"]["posts"], 1)
        self.assertEqual(hourly["2026-10-16T03:00Z"]["philadelphia 76ers"], 1)
        self.assertEqual(players[("stephen curry", "golden state warriors")], 1)


if __name__ == "__main__":
    unittest.main()
