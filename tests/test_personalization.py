import datetime as dt
import json
import unittest

import pandas as pd

from core.personalization import apply_personalization


def _row(day, away, home, score=60.0, *, away_injuries=None, home_injuries=None):
    return {
        "Local date": day,
        "Away team": away,
        "Home team": home,
        "aWI": score,
        "Uavg": score / 100.0,
        "Region": "Watchable",
        "Away injuries detail JSON": json.dumps(away_injuries or []),
        "Home injuries detail JSON": json.dumps(home_injuries or []),
        "Away Key Injuries": "",
        "Home Key Injuries": "",
    }


class PersonalizationTests(unittest.TestCase):
    def test_league_pass_view_is_unchanged(self):
        df = pd.DataFrame([_row(dt.date(2026, 10, 20), "Boston Celtics", "New York Knicks", 72.0)])
        result = apply_personalization(df)
        self.assertEqual(result.loc[0, "aWI"], 72.0)
        self.assertEqual(result.loc[0, "Base aWI"], 72.0)
        self.assertFalse(result.loc[0, "Personalization active"])

    def test_team_view_scores_own_team_rivals_and_upcoming_opponents(self):
        df = pd.DataFrame(
            [
                _row(dt.date(2026, 10, 20), "Houston Rockets", "Dallas Mavericks"),
                _row(dt.date(2026, 10, 22), "Golden State Warriors", "Houston Rockets"),
                _row(dt.date(2026, 10, 25), "Sacramento Kings", "Phoenix Suns"),
            ]
        )
        result = apply_personalization(df, favorite_team="Golden State Warriors")

        self.assertEqual(result.loc[0, "Upcoming opponent score"], 100.0)
        self.assertEqual(result.loc[0, "Rival score"], 100.0)
        self.assertEqual(result.loc[1, "Own team score"], 100.0)
        self.assertEqual(result.loc[1, "Rival score"], 100.0)
        self.assertEqual(result.loc[2, "Rival score"], 50.0)
        self.assertIn("Your team", result.loc[1, "Personalization notes"])

    def test_optional_team_components_can_be_disabled_but_own_team_stays_on(self):
        df = pd.DataFrame(
            [
                _row(dt.date(2026, 10, 20), "Houston Rockets", "Dallas Mavericks"),
                _row(dt.date(2026, 10, 22), "Golden State Warriors", "Houston Rockets"),
            ]
        )
        result = apply_personalization(
            df,
            favorite_team="Golden State Warriors",
            enabled_team_components=[],
        )

        self.assertEqual(result.loc[0, "Team fan score"], 0.0)
        self.assertEqual(result.loc[0, "Upcoming opponent score"], 0.0)
        self.assertEqual(result.loc[0, "Rival score"], 0.0)
        self.assertEqual(result.loc[1, "Own team score"], 100.0)
        self.assertEqual(result.loc[1, "Team fan score"], 100.0)
        self.assertTrue(result.loc[1, "Team fan active"])

    def test_former_player_high_score_uses_prior_team(self):
        df = pd.DataFrame([_row(dt.date(2026, 10, 20), "Miami Heat", "Orlando Magic")])
        result = apply_personalization(df, favorite_team="Milwaukee Bucks")
        self.assertEqual(result.loc[0, "Former player score"], 100.0)
        self.assertIn("Giannis Antetokounmpo", result.loc[0, "Personalization notes"])

    def test_favorite_player_boosts_game_when_available(self):
        df = pd.DataFrame([_row(dt.date(2026, 10, 20), "Golden State Warriors", "Phoenix Suns", 40.0)])
        result = apply_personalization(df, favorite_players=["Stephen Curry"])
        self.assertEqual(result.loc[0, "Favorite player score"], 100.0)
        self.assertEqual(result.loc[0, "aWI"], 55.0)
        self.assertIn("Favorite: Stephen Curry", result.loc[0, "Personalization notes"])

    def test_out_favorite_player_does_not_boost_game(self):
        injuries = [{"player": "Stephen Curry", "status": "Out"}]
        df = pd.DataFrame(
            [
                _row(
                    dt.date(2026, 10, 20),
                    "Golden State Warriors",
                    "Phoenix Suns",
                    40.0,
                    away_injuries=injuries,
                )
            ]
        )
        result = apply_personalization(df, favorite_players=["Stephen Curry"])
        self.assertEqual(result.loc[0, "Favorite player score"], 0.0)
        self.assertEqual(result.loc[0, "aWI"], 30.0)
        self.assertIn("Unavailable: Stephen Curry", result.loc[0, "Personalization notes"])

    def test_favorite_player_selection_is_capped_at_five(self):
        selected = [
            "Stephen Curry",
            "LeBron James",
            "Luka Dončić",
            "Victor Wembanyama",
            "Giannis Antetokounmpo",
            "Nikola Jokić",
        ]
        df = pd.DataFrame([_row(dt.date(2026, 10, 20), "Denver Nuggets", "Phoenix Suns", 40.0)])
        result = apply_personalization(df, favorite_players=selected)
        self.assertEqual(result.loc[0, "Favorite player score"], 0.0)


if __name__ == "__main__":
    unittest.main()
